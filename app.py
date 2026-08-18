"""Public-safe synthetic multi-domain web MVP for the UzLocEng AI demo."""

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
DEMO_DATA_DIR = ROOT / "demo_data"
SESSIONS: set[str] = set()
NOT_FOUND_TEXT = "В синтетической демонстрационной базе точный ответ на этот вопрос не найден."

# Each entry is intentionally synthetic.  The line number is used only to extract
# evidence from the public demo file, so an answer never includes its whole source.
DOMAINS = {
    "energy": {
        "label": "Энергетика",
        "source_id": "S1",
        "source_path": DEMO_DATA_DIR / "synthetic_energy_demo.txt",
        "parameters": (
            ("voltage", ("напряжен", "вольт"), "Номинальное напряжение силового трансформатора — 6,3 кВ.", "1."),
            ("power", ("мощност", "ква"), "Номинальная мощность силового трансформатора — 1 250 кВА.", "2."),
            ("frequency", ("частот", "герц", "гц"), "Номинальная частота питания — 50 Гц.", "3."),
            ("ratio", ("коэффициент трансформац", "трансформац"), "Коэффициент трансформации — 6,3/0,4 кВ.", "4."),
            ("efficiency", ("кпд", "эффективност"), "Расчётный КПД трансформатора — 98 %.", "5."),
            ("current", ("ток", "ампер"), "Номинальный ток низковольтной обмотки — 1 805 А.", "6."),
            ("motor_power", ("двигател", "электродвигател"), "Номинальная мощность демонстрационного электродвигателя — 75 кВт.", "7."),
            ("motor_speed", ("оборотов", "об/мин", "скорост вращения"), "Номинальная частота вращения электродвигателя — 1 480 об/мин.", "8."),
        ),
    },
    "mechanics": {
        "label": "Механика",
        "source_id": "S2",
        "source_path": DEMO_DATA_DIR / "synthetic_mechanics_demo.txt",
        "parameters": (
            ("capacity", ("производительност", "подач", "расход"), "Производительность центробежного насоса — 180 м³/ч.", "1."),
            ("head", ("напор",), "Номинальный напор центробежного насоса — 42 м.", "2."),
            ("speed", ("частота вращения", "оборотов", "об/мин"), "Номинальная частота вращения вала — 1 450 об/мин.", "3."),
            ("shaft", ("вал", "диаметр вала"), "Диаметр вала — 55 мм.", "4."),
            ("impeller", ("рабоч колес", "колесо"), "Диаметр рабочего колеса — 260 мм.", "5."),
            ("bearing", ("подшипник",), "В демонстрационном насосе применён подшипниковый узел серии BX-42.", "6."),
            ("vibration", ("вибрац",), "Допустимый уровень вибрации корпуса — не более 2,8 мм/с.", "7."),
            ("temperature", ("температур",), "Расчётная температура перекачиваемой синтетической среды — 35 °C.", "8."),
        ),
    },
    "technology": {
        "label": "Технология",
        "source_id": "S3",
        "source_path": DEMO_DATA_DIR / "synthetic_technology_demo.txt",
        "parameters": (
            ("flow", ("расход газа", "газовый поток", "газов"), "Расход газа через рукавный фильтр — 12 000 м³/ч.", "1."),
            ("diameter", ("диаметр",), "Диаметр фильтровальных рукавов — 160 мм.", "2."),
            ("height", ("высот", "длин"), "Высота фильтровальных рукавов — 6 м.", "3."),
            ("temperature", ("температур",), "Температура синтетического газового потока — 120 °C.", "4."),
            ("pressure", ("перепад давлен", "давлен"), "Расчётный перепад давления на фильтре — 1,4 кПа.", "5."),
            ("filtration", ("фильтрац", "очистк"), "Демонстрационная эффективность фильтрации — 96 %.", "6."),
            ("pulse", ("импульс", "продувк"), "Длительность импульса очистки рукава — 0,12 с.", "7."),
            ("cycle", ("режим", "цикл"), "Демонстрационный цикл очистки выполняется каждые 45 с.", "8."),
        ),
    },
}


def _evidence(source_path: Path, prefix: str) -> str:
    """Extract one cited fact, never the complete source document."""
    for line in source_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.strip()
    raise RuntimeError(f"Missing synthetic evidence line {prefix} in {source_path.name}")


def answer_for(question: str, domain_id: str) -> dict[str, object]:
    """Return only parameter facts explicitly present in the chosen synthetic source."""
    domain = DOMAINS.get(domain_id)
    normalized = " ".join(question.casefold().split())
    if not domain or not normalized:
        return {"found": False, "answer": NOT_FOUND_TEXT, "citations": [], "evidence": []}
    matches = [
        (max(len(word) for word in item[1] if word in normalized), item)
        for item in domain["parameters"]
        if any(word in normalized for word in item[1])
    ]
    selected = [item for score, item in matches if score == max((score for score, _ in matches), default=0)]
    if not selected:
        return {"found": False, "answer": NOT_FOUND_TEXT, "citations": [], "evidence": []}
    return {
        "found": True,
        "answer": " ".join(item[2] + f" [{domain['source_id']}]" for item in selected),
        "citations": [domain["source_id"]],
        "evidence": [_evidence(domain["source_path"], item[3]) for item in selected],
    }


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демонстрация</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.card{max-width:440px;margin:12vh auto;background:#fff;padding:32px;border-radius:14px;box-shadow:0 8px 26px #1233}.brand{color:#087e8b}input,button,textarea,select{box-sizing:border-box;width:100%;padding:12px;margin-top:10px;border:1px solid #b8c6d4;border-radius:8px;font:inherit}button{background:#087e8b;color:#fff;border:0;font-weight:bold;cursor:pointer}.error{color:#b42318;min-height:22px}</style>
</head><body><main class="card"><h1>UzLocEng <span class="brand">AI</span></h1><p>Демонстрационная версия</p><label>Логин<input id="login" autocomplete="username"></label><label>Пароль<input id="password" type="password" autocomplete="current-password"></label><button onclick="signIn()">Войти</button><p id="error" class="error"></p></main><script>
async function signIn(){const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login:login.value,password:password.value})});if(r.ok)location='/';else error.textContent='Неверный логин или пароль.'}
</script></body></html>"""

APP_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демонстрация</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.top{background:#062f4f;color:#fff;padding:18px 7%;display:flex;justify-content:space-between}.wrap{max-width:980px;margin:30px auto;padding:0 20px}.panel{background:#fff;padding:24px;margin:18px 0;border-radius:12px;box-shadow:0 4px 16px #1232}textarea,select{width:100%;min-height:52px;padding:12px;box-sizing:border-box;border:1px solid #b8c6d4;border-radius:8px;font:inherit}textarea{min-height:110px}button{margin-top:12px;background:#087e8b;color:white;border:0;padding:12px 18px;border-radius:8px;font-weight:bold;cursor:pointer}.hidden{display:none}.answer{white-space:pre-wrap;line-height:1.6}.tag{display:inline-block;background:#d9f3f4;color:#075d67;border-radius:14px;padding:4px 10px;margin-right:6px}.evidence{border-left:4px solid #087e8b;padding:10px 14px;background:#f6fbfb;margin:8px 0}.muted{color:#486581}.directions{display:flex;gap:8px;flex-wrap:wrap}.direction{border:1px solid #b8c6d4;border-radius:8px;padding:9px 12px;background:#f6fbfb}</style>
</head><body><header class="top"><strong>UzLocEng AI</strong><span>Демонстрационная версия</span></header><main class="wrap"><section class="panel"><h2>Демонстрационные направления</h2><p class="muted">Выберите направление и задайте технический вопрос по доступной синтетической базе знаний.</p><div class="directions"><span class="direction">Энергетика</span><span class="direction">Механика</span><span class="direction">Технология</span></div></section><section class="panel"><h1>Технический вопрос</h1><p><span class="tag">Синтетическая база знаний</span></p><label>Направление<select id="domain"><option value="energy">Энергетика</option><option value="mechanics">Механика</option><option value="technology">Технология</option></select></label><textarea id="question" placeholder="Введите технический вопрос на русском языке"></textarea><button onclick="ask()">Получить ответ</button></section><section id="result" class="panel hidden"><h2>Ответ</h2><div id="answer" class="answer"></div><h3>Использованные источники</h3><div id="citations"></div><h3>Доказательства</h3><div id="evidence"></div></section></main><script>
function esc(v){const e=document.createElement('span');e.textContent=v;return e.innerHTML} async function ask(){const question=document.getElementById('question').value.trim();if(!question)return;const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,domain:domain.value})});if(r.status===401){location='/login';return}const data=await r.json();result.classList.remove('hidden');answer.innerHTML=esc(data.answer);citations.innerHTML=data.citations.length?data.citations.map(x=>'<span class="tag">['+esc(x)+']</span>').join(''):'<span class="muted">Нет использованных источников.</span>';evidence.innerHTML=data.evidence.length?data.evidence.map(x=>'<div class="evidence">'+esc(x)+'</div>').join(''):'<span class="muted">Нет доказательств.</span>'}
</script></body></html>"""


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "UzLocEngPublicDemo/2.0"

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
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

    def _json(self, status: HTTPStatus, payload: dict[str, object], cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store")
        if cookie: self.send_header("Set-Cookie", cookie)
        self.end_headers(); self.wfile.write(data)

    def _payload(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 4096: raise ValueError("invalid body length")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict): raise ValueError("invalid JSON payload")
        return {str(key): str(value) for key, value in data.items()}

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/login": self._send(HTTPStatus.OK, LOGIN_PAGE)
        elif path == "/":
            if not self._authenticated():
                self.send_response(HTTPStatus.SEE_OTHER); self.send_header("Location", "/login"); self.end_headers(); return
            self._send(HTTPStatus.OK, APP_PAGE)
        else: self._send(HTTPStatus.NOT_FOUND, "Страница не найдена.")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try: payload = self._payload()
        except (ValueError, json.JSONDecodeError): self._json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос."}); return
        if path == "/api/login":
            valid = hmac.compare_digest(payload.get("login", ""), self.username) and hmac.compare_digest(payload.get("password", ""), self.password)
            if not valid: self._json(HTTPStatus.UNAUTHORIZED, {"error": "Неверные учётные данные."}); return
            token = secrets.token_urlsafe(32); SESSIONS.add(token)
            self._json(HTTPStatus.OK, {"ok": True}, f"uzloceng_demo_session={token}; HttpOnly; SameSite=Lax; Path=/"); return
        if path == "/api/query":
            if not self._authenticated(): self._json(HTTPStatus.UNAUTHORIZED, {"error": "Требуется вход."}); return
            question = payload.get("question", "").strip()
            if not question or len(question) > 1000: self._json(HTTPStatus.BAD_REQUEST, {"error": "Введите вопрос длиной до 1000 символов."}); return
            self._json(HTTPStatus.OK, answer_for(question, payload.get("domain", ""))); return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Маршрут не найден."})

    def log_message(self, _format: str, *_args: object) -> None: return


def main() -> None:
    parser = argparse.ArgumentParser(description="UzLocEng AI public-safe synthetic MVP")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1")); parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args(); username = os.environ.get("UZLOCENG_DEMO_USERNAME", ""); password = os.environ.get("UZLOCENG_DEMO_PASSWORD", "")
    if not username or not password: raise SystemExit("Требуются переменные UZLOCENG_DEMO_USERNAME и UZLOCENG_DEMO_PASSWORD.")
    if any(not domain["source_path"].is_file() for domain in DOMAINS.values()): raise SystemExit("Synthetic demonstration data not found.")
    server = ThreadingHTTPServer((args.host, args.port), DemoHandler); server.username = username; server.password = password  # type: ignore[attr-defined]
    print(f"UzLocEng AI demo: http://{args.host}:{args.port}"); server.serve_forever()


if __name__ == "__main__": main()
