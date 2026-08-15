"""Public-safe local web MVP for the UzLocEng AI competition demonstration.

The service uses only the synthetic text bundled beside this file.  Runtime
credentials are supplied through environment variables and are never embedded
in the page or source bundle.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
SOURCE_PATH = ROOT / "demo_data" / "synthetic_bag_filter_demo.txt"
SOURCE_ID = "S1"
SESSIONS: set[str] = set()
NOT_FOUND_TEXT = "В синтетическом демонстрационном источнике точный ответ на этот вопрос не найден."
PARAMETERS = (
    {
        "keywords": ("скорост",),
        "answer": "Запыленный газ поступает в нижнюю часть рукавного фильтра со скоростью 12 м/с [S1].",
        "evidence_prefix": "1.",
    },
    {
        "keywords": ("диаметр",),
        "answer": "Диаметр фильтровальных рукавов составляет 100–300 мм [S1].",
        "evidence_prefix": "2.",
    },
    {
        "keywords": ("высот",),
        "answer": "Высота фильтровальных рукавов составляет 0,5–10 м [S1].",
        "evidence_prefix": "3.",
    },
)


def read_source() -> str:
    return SOURCE_PATH.read_text(encoding="utf-8")


def answer_for(question: str) -> dict[str, object]:
    """Return only facts explicitly present in the synthetic demonstration text."""
    normalized = " ".join(question.casefold().split())
    selected = [
        parameter
        for parameter in PARAMETERS
        if any(keyword in normalized for keyword in parameter["keywords"])
    ]
    if not selected:
        return {
            "found": False,
            "answer": NOT_FOUND_TEXT,
            "citations": [],
            "evidence": [],
        }

    source_lines = read_source().splitlines()
    evidence = [
        next(line.strip() for line in source_lines if line.startswith(parameter["evidence_prefix"]))
        for parameter in selected
    ]
    return {
        "found": True,
        "answer": " ".join(parameter["answer"] for parameter in selected),
        "citations": [SOURCE_ID],
        "evidence": evidence,
    }


LOGIN_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демо</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.card{max-width:440px;margin:12vh auto;background:#fff;padding:32px;border-radius:14px;box-shadow:0 8px 26px #1233}.brand{color:#087e8b}input,button,textarea{box-sizing:border-box;width:100%;padding:12px;margin-top:10px;border:1px solid #b8c6d4;border-radius:8px;font:inherit}button{background:#087e8b;color:white;border:0;font-weight:bold;cursor:pointer}.error{color:#b42318;min-height:22px}</style>
</head><body><main class="card"><h1>UzLocEng <span class="brand">AI</span></h1><p>Локальная конкурсная демонстрация</p><label>Логин<input id="login" autocomplete="username"></label><label>Пароль<input id="password" type="password" autocomplete="current-password"></label><button onclick="signIn()">Войти</button><p id="error" class="error"></p></main><script>
async function signIn(){const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login:login.value,password:password.value})});if(r.ok)location='/';else error.textContent='Неверный логин или пароль.'}
</script></body></html>"""


APP_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демо</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.top{background:#062f4f;color:#fff;padding:18px 7%;display:flex;justify-content:space-between}.wrap{max-width:980px;margin:30px auto;padding:0 20px}.panel{background:#fff;padding:24px;margin:18px 0;border-radius:12px;box-shadow:0 4px 16px #1232}textarea{width:100%;min-height:110px;padding:12px;box-sizing:border-box;border:1px solid #b8c6d4;border-radius:8px;font:inherit}button{margin-top:12px;background:#087e8b;color:white;border:0;padding:12px 18px;border-radius:8px;font-weight:bold;cursor:pointer}.hidden{display:none}.answer{white-space:pre-wrap;line-height:1.6}.tag{display:inline-block;background:#d9f3f4;color:#075d67;border-radius:14px;padding:4px 10px;margin-right:6px}.evidence{border-left:4px solid #087e8b;padding:10px 14px;background:#f6fbfb;margin:8px 0}.muted{color:#486581}</style>
</head><body><header class="top"><strong>UzLocEng AI</strong><span>Локальная MVP-демонстрация</span></header><main class="wrap"><section class="panel"><h1>Технический вопрос</h1><p class="muted">Доступна только синтетическая демонстрационная база знаний.</p><textarea id="question" placeholder="Введите вопрос на русском языке"></textarea><button onclick="ask()">Получить ответ</button></section><section id="result" class="panel hidden"><h2>Ответ</h2><div id="answer" class="answer"></div><h3>Использованные источники</h3><div id="citations"></div><h3>Доказательства</h3><div id="evidence"></div></section></main><script>
function esc(v){const e=document.createElement('span');e.textContent=v;return e.innerHTML}
async function ask(){const question=document.getElementById('question').value.trim();if(!question)return;const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});if(r.status===401){location='/login';return}const data=await r.json();result.classList.remove('hidden');answer.innerHTML=esc(data.answer);citations.innerHTML=data.citations.length?data.citations.map(x=>'<span class="tag">['+esc(x)+']</span>').join(''):'<span class="muted">Нет использованных источников.</span>';evidence.innerHTML=data.evidence.length?data.evidence.map(x=>'<div class="evidence">'+esc(x)+'</div>').join(''):'<span class="muted">Нет доказательств.</span>'}
</script></body></html>"""


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "UzLocEngPublicDemo/1.0"

    @property
    def username(self) -> str:
        return self.server.username  # type: ignore[attr-defined]

    @property
    def password(self) -> str:
        return self.server.password  # type: ignore[attr-defined]

    def _session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        return cookie.get("uzloceng_demo_session").value if "uzloceng_demo_session" in cookie else None

    def _authenticated(self) -> bool:
        token = self._session_token()
        return bool(token and token in SESSIONS)

    def _send(self, status: HTTPStatus, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: HTTPStatus, payload: dict[str, object], cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _payload(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096:
            raise ValueError("invalid body length")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid JSON payload")
        return {str(key): str(value) for key, value in data.items()}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/login":
            self._send(HTTPStatus.OK, LOGIN_PAGE)
        elif path == "/":
            if not self._authenticated():
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            self._send(HTTPStatus.OK, APP_PAGE)
        else:
            self._send(HTTPStatus.NOT_FOUND, "Страница не найдена.")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._payload()
        except (ValueError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос."})
            return
        if path == "/api/login":
            valid = hmac.compare_digest(payload.get("login", ""), self.username) and hmac.compare_digest(payload.get("password", ""), self.password)
            if not valid:
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Неверные учётные данные."})
                return
            token = secrets.token_urlsafe(32)
            SESSIONS.add(token)
            self._json(HTTPStatus.OK, {"ok": True}, f"uzloceng_demo_session={token}; HttpOnly; SameSite=Lax; Path=/")
            return
        if path == "/api/query":
            if not self._authenticated():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Требуется вход."})
                return
            question = payload.get("question", "").strip()
            if not question or len(question) > 1000:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Введите вопрос длиной до 1000 символов."})
                return
            self._json(HTTPStatus.OK, answer_for(question))
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден."})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="UzLocEng AI public-safe local MVP")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    username = os.environ.get("UZLOCENG_DEMO_USERNAME", "")
    password = os.environ.get("UZLOCENG_DEMO_PASSWORD", "")
    if not username or not password:
        raise SystemExit("UZLOCENG_DEMO_USERNAME ва UZLOCENG_DEMO_PASSWORD муҳит ўзгарувчилари талаб қилинади.")
    if not SOURCE_PATH.is_file():
        raise SystemExit("Synthetic demonstration data not found.")
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler)
    server.username = username  # type: ignore[attr-defined]
    server.password = password  # type: ignore[attr-defined]
    print(f"UzLocEng AI демо: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
