from __future__ import annotations

import datetime as dt
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "index.html"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini-2025-08-07")


ZODIAC_RANGES = [
    ("염소자리", (12, 22), (1, 19)),
    ("물병자리", (1, 20), (2, 18)),
    ("물고기자리", (2, 19), (3, 20)),
    ("양자리", (3, 21), (4, 19)),
    ("황소자리", (4, 20), (5, 20)),
    ("쌍둥이자리", (5, 21), (6, 20)),
    ("게자리", (6, 21), (7, 22)),
    ("사자자리", (7, 23), (8, 22)),
    ("처녀자리", (8, 23), (9, 22)),
    ("천칭자리", (9, 23), (10, 22)),
    ("전갈자리", (10, 23), (11, 21)),
    ("사수자리", (11, 22), (12, 21)),
]

ZODIAC_INDEX = {name: index for index, (name, _, _) in enumerate(ZODIAC_RANGES)}


def parse_birth_date(value: str) -> dt.date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("생년월일은 YYYY-MM-DD 형식이어야 합니다.")

    year, month, day = map(int, value.split("-"))
    return dt.date(year, month, day)


def get_zodiac(date: dt.date) -> str:
    month_day = (date.month, date.day)

    for name, start, end in ZODIAC_RANGES:
        if start <= end:
            if start <= month_day <= end:
                return name
        else:
            if month_day >= start or month_day <= end:
                return name

    return "염소자리"


def build_numbers(date: dt.date, zodiac: str) -> tuple[list[int], int]:
    zodiac_offset = ZODIAC_INDEX.get(zodiac, 0) * 97
    seed = date.year * 10000 + date.month * 100 + date.day + zodiac_offset

    state = seed & 0xFFFFFFFF
    picked: list[int] = []
    seen: set[int] = set()

    while len(picked) < 6:
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        number = state % 45 + 1
        if number not in seen:
            seen.add(number)
            picked.append(number)

    picked.sort()
    return picked, seed


def build_local_reply(birth_date: dt.date, zodiac: str, numbers: list[int]) -> dict[str, str]:
    return {
        "reply": (
            f"{birth_date.isoformat()}은 {zodiac} 흐름으로 읽혔어요. "
            f"생년월일 숫자와 별자리 가중치를 섞은 시드로 1부터 45까지를 중복 없이 섞은 뒤 "
            f"{', '.join(map(str, numbers))}을 골랐습니다. "
            "이 조합은 재미로 즐겨보세요."
        ),
        "disclaimer": "별자리와 로또 해석은 오락용입니다.",
    }


def call_openai(birth_date: dt.date, zodiac: str, numbers: list[int], seed: int) -> dict[str, str]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

    schema = {
        "type": "object",
        "properties": {
            "reply": {"type": "string"},
            "disclaimer": {"type": "string"},
        },
        "required": ["reply", "disclaimer"],
        "additionalProperties": False,
    }

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "너는 한국어로 답하는 친절한 별자리 로또 챗봇이다. "
                            "과학적 예언처럼 말하지 말고, 오락용 추천임을 분명히 해라. "
                            "반드시 JSON만 출력하라."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"생년월일: {birth_date.isoformat()}\n"
                            f"별자리: {zodiac}\n"
                            f"시드: {seed}\n"
                            f"번호: {', '.join(map(str, numbers))}\n\n"
                            "요구사항:\n"
                            "1. 친근한 한국어로 2~4문장 정도 설명해라.\n"
                            "2. 왜 이 번호가 나왔는지, 생년월일 숫자와 별자리 흐름을 섞어 설명해라.\n"
                            "3. 마지막에 오락용이라는 점을 짧게 덧붙여라."
                        ),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "zodiac_lotto_reply",
                "strict": True,
                "schema": schema,
            }
        },
        "temperature": 0.7,
    }

    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        raw_text = data.get("output_text", "")
        if not raw_text:
            for item in data.get("output", []):
                if item.get("type") != "message":
                    continue
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        raw_text += content.get("text", "")

        parsed = json.loads(raw_text) if raw_text else {}
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI 응답 형식이 올바르지 않습니다.")

        reply = str(parsed.get("reply", "")).strip()
        disclaimer = str(parsed.get("disclaimer", "")).strip()

        if not reply:
            raise ValueError("OpenAI 응답에 reply가 없습니다.")

        return {
            "reply": reply,
            "disclaimer": disclaimer or "별자리와 로또 해석은 오락용입니다.",
        }
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API 오류: {exc.code} {details}") from exc
    except (error.URLError, ValueError, json.JSONDecodeError, TimeoutError) as exc:
        raise RuntimeError(f"OpenAI 호출 실패: {exc}") from exc


class Handler(BaseHTTPRequestHandler):
    server_version = "StarLotto/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_index(self) -> None:
        body = INDEX_PATH.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._send_index()
            return

        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/api/draw":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            birth_date = parse_birth_date(payload.get("birthDate", ""))
            zodiac = get_zodiac(birth_date)
            numbers, seed = build_numbers(birth_date, zodiac)
            ai_result = call_openai(birth_date, zodiac, numbers, seed)

            response = {
                "birthDate": birth_date.isoformat(),
                "zodiac": zodiac,
                "numbers": numbers,
                "seed": seed,
                "reply": ai_result["reply"],
                "disclaimer": ai_result["disclaimer"],
                "selectionBasis": (
                    "생년월일 숫자와 별자리 가중치를 합친 시드로 1부터 45까지를 "
                    "중복 없이 섞어 뽑았습니다."
                ),
            }
            self._send_json(HTTPStatus.OK, response)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": str(exc)},
            )
        except Exception:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "서버에서 번호를 계산하지 못했습니다."},
            )


def main() -> None:
    if not INDEX_PATH.exists():
        raise FileNotFoundError("index.html 파일을 찾을 수 없습니다.")

    if not OPENAI_API_KEY:
        print("Warning: OPENAI_API_KEY is not set.")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving on http://{HOST}:{PORT}")
    print(f"Model: {OPENAI_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
