"""Public-safe synthetic multi-domain web MVP for the UzLocEng AI demo."""

from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import re
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DEMO_DATA_DIR = ROOT / "demo_data"
SESSIONS: set[str] = set()
INSUFFICIENT_DATA_TEXT = "В синтетической демонстрационной базе недостаточно данных для точного ответа или расчёта."

# Facts are never duplicated in answer templates: prefixes select the exact public
# synthetic source line that is returned as both answer material and evidence.
DOMAINS = {
    "energy": {
        "source_id": "S1", "source_path": DEMO_DATA_DIR / "synthetic_energy_demo.txt",
        "objects": {"motor": ("электродвигател", "двигател"), "transformer": ("трансформатор",)},
        "parameters": {
            "motor_power": ("motor", ("мощност", "квт"), "1."),
            "motor_voltage": ("motor", ("напряжен", "вольт"), "2."),
            "motor_current": ("motor", ("ток", "ампер"), "3."),
            "motor_frequency": ("motor", ("частот", "герц", "гц"), "4."),
            "motor_cosphi": ("motor", ("cos", "коэффициент мощности"), "5."),
            "motor_efficiency": ("motor", ("кпд", "эффективност"), "6."),
            "motor_speed": ("motor", ("оборотов", "об/мин", "скорост вращения"), "7."),
            "transformer_power": ("transformer", ("мощност", "ква"), "8."),
            "transformer_voltage": ("transformer", ("напряжен", "вольт", "кв"), "9."),
            "transformer_ratio": ("transformer", ("коэффициент трансформац", "трансформац"), "10."),
        },
        "summaries": {"motor": ("motor_power", "motor_voltage", "motor_current", "motor_frequency", "motor_cosphi")},
    },
    "mechanics": {
        "source_id": "S2", "source_path": DEMO_DATA_DIR / "synthetic_mechanics_demo.txt",
        "objects": {"pump": ("насос", "насосного агрегат"), "gearbox": ("редуктор",), "shaft": ("вал",), "bearing": ("подшипник",)},
        "parameters": {
            "capacity": ("pump", ("производительност", "подач", "расход"), "1."),
            "head": ("pump", ("напор",), "2."),
            "pump_speed": ("pump", ("частота вращения", "оборотов", "об/мин"), "3."),
            "shaft_diameter": ("shaft", ("диаметр", "вал"), "4."),
            "bearing": ("bearing", ("подшипник",), "5."),
            "gearbox_input_speed": ("gearbox", ("входн", "частота вращения", "оборотов"), "6."),
            "gear_ratio": ("gearbox", ("передаточн", "коэффициент редукц"), "7."),
            "vibration": ("pump", ("вибрац",), "8."),
        },
        "summaries": {"pump": ("capacity", "head", "pump_speed", "shaft_diameter", "bearing")},
    },
    "technology": {
        "source_id": "S3", "source_path": DEMO_DATA_DIR / "synthetic_technology_demo.txt",
        "objects": {"filter": ("фильтр", "рукав"), "gas": ("газов", "газ")},
        "parameters": {
            "flow": ("gas", ("расход", "газовый поток", "газов"), "1."),
            "diameter": ("filter", ("диаметр",), "2."),
            "height": ("filter", ("высот", "длин"), "3."),
            "count": ("filter", ("количеств", "число", "рукавов"), "4."),
            "pressure": ("filter", ("перепад давлен", "давлен"), "5."),
            "filtration": ("filter", ("эффективност фильтрац", "фильтрац"), "6."),
            "pulse": ("filter", ("импульс", "продувк"), "7."),
            "cycle": ("filter", ("режим", "цикл"), "8."),
        },
        "summaries": {"filter": ("flow", "diameter", "height", "count", "pressure")},
    },
}


def _source_line(domain: dict, prefix: str) -> str:
    for line in domain["source_path"].read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.strip()
    raise RuntimeError(f"Missing synthetic evidence line {prefix}")


def _fact_text(line: str) -> str:
    return line.split(". ", 1)[1] if ". " in line else line


def _result(
    domain: dict,
    keys: tuple[str, ...],
    answer: str | None = None,
    formula: tuple[str, ...] | None = None,
) -> dict[str, object]:
    lines = [_source_line(domain, domain["parameters"][key][2]) for key in keys]
    result = {
        "found": True,
        "answer": answer if answer is not None else " ".join(_fact_text(line) for line in lines),
        "citations": [domain["source_id"]],
        "evidence": lines,
    }
    if formula:
        result["formula"] = formula
    return result


def _insufficient() -> dict[str, object]:
    return {"found": False, "answer": INSUFFICIENT_DATA_TEXT, "citations": [], "evidence": []}


def _object_for(domain: dict, question: str) -> str | None:
    matches = [
        (max(len(alias) for alias in aliases if alias in question), object_id)
        for object_id, aliases in domain["objects"].items()
        if any(alias in question for alias in aliases)
    ]
    return max(matches, default=(0, None))[1]


def _single_parameter(domain: dict, question: str, object_id: str | None) -> str | None:
    matches = []
    for key, (parameter_object, aliases, _prefix) in domain["parameters"].items():
        if object_id and parameter_object != object_id:
            continue
        if key.endswith("_voltage") and "номинальн" not in question:
            continue
        found_aliases = [alias for alias in aliases if alias in question]
        if found_aliases:
            matches.append((max(map(len, found_aliases)), key))
    if not matches and object_id:
        return _single_parameter(domain, question, None)
    return max(matches, default=(0, None))[1]


def _number(domain: dict, key: str, pattern: str) -> float:
    match = re.search(pattern, _source_line(domain, domain["parameters"][key][2]))
    if not match:
        raise ValueError("synthetic calculation input is missing")
    return float(match.group(1).replace(",", ".").replace(" ", ""))


def _calculation(domain_id: str, domain: dict, question: str) -> dict[str, object] | None:
    if not any(word in question for word in ("рассчита", "расчёт", "расчет", "вычисл")):
        return None
    try:
        if domain_id == "energy" and any(word in question for word in ("ток", "электродвигател", "двигател")):
            keys = ("motor_power", "motor_voltage", "motor_cosphi", "motor_efficiency")
            power = _number(domain, "motor_power", r"— ([0-9 ]+) кВт") * 1000
            voltage = _number(domain, "motor_voltage", r"— ([0-9]+) В")
            cos_phi = _number(domain, "motor_cosphi", r"— ([0-9,]+)")
            efficiency = _number(domain, "motor_efficiency", r"— ([0-9,]+)")
            current = power / (math.sqrt(3) * voltage * cos_phi * efficiency)
            formula = (
                "I = P / (√3 × U × cosφ × η)",
                f"I = {power:,.0f} / (√3 × {voltage:.0f} × {cos_phi:.2f} × {efficiency:.2f})".replace(",", " ").replace(".", ","),
            )
            return _result(domain, keys, f"Расчётный ток: {current:.1f} А".replace(".", ","), formula)
        if domain_id == "mechanics" and any(word in question for word in ("редуктор", "выходн")):
            keys = ("gearbox_input_speed", "gear_ratio")
            input_speed = _number(domain, "gearbox_input_speed", r"— ([0-9 ]+) об/мин")
            ratio = _number(domain, "gear_ratio", r"— ([0-9,]+)")
            output_speed = input_speed / ratio
            formula = ("nвых = nвх / i", f"nвых = {input_speed:.0f} / {ratio:.1f}".replace(".", ","))
            return _result(domain, keys, f"Частота вращения выходного вала: {output_speed:.1f} об/мин".replace(".", ","), formula)
        if domain_id == "technology" and any(word in question for word in ("площад", "фильтрац")):
            keys = ("diameter", "height", "count")
            diameter = _number(domain, "diameter", r"— ([0-9,]+) мм") / 1000
            height = _number(domain, "height", r"— ([0-9,]+) м")
            count = _number(domain, "count", r"— ([0-9]+)")
            area = math.pi * diameter * height * count
            formula = ("F = π × d × L × N", f"F = π × {diameter:.3f} × {height:.1f} × {count:.0f}".replace(".", ","))
            return _result(domain, keys, f"Общая площадь фильтрации: {area:.1f} м²".replace(".", ","), formula)
    except ValueError:
        return _insufficient()
    return _insufficient()


def answer_for(question: str, domain_id: str) -> dict[str, object]:
    """Answer only with source-backed synthetic facts or explicit calculations."""
    domain = DOMAINS.get(domain_id)
    normalized = " ".join(question.casefold().split())
    if not domain or not normalized:
        return _insufficient()
    if any(term in normalized for term in ("класс", "тип", "вид", "марка", "категор")):
        return _insufficient()
    calculation = _calculation(domain_id, domain, normalized)
    if calculation is not None:
        return calculation
    object_id = _object_for(domain, normalized)
    is_multi = any(phrase in normalized for phrase in ("основн", "какие параметр", "указаны в базе", "доступны для оценки"))
    if is_multi and object_id and object_id in domain["summaries"]:
        return _result(domain, domain["summaries"][object_id])
    key = _single_parameter(domain, normalized, object_id)
    return _result(domain, (key,)) if key else _insufficient()


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демонстрация</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.card{max-width:440px;margin:12vh auto;background:#fff;padding:32px;border-radius:14px;box-shadow:0 8px 26px #1233}.brand{color:#087e8b}input,button,textarea,select{box-sizing:border-box;width:100%;padding:12px;margin-top:10px;border:1px solid #b8c6d4;border-radius:8px;font:inherit}button{background:#087e8b;color:#fff;border:0;font-weight:bold;cursor:pointer}.error{color:#b42318;min-height:22px}</style>
</head><body><main class="card"><h1>UzLocEng <span class="brand">AI</span></h1><p>Демонстрационная версия</p><label>Логин<input id="login" autocomplete="username"></label><label>Пароль<input id="password" type="password" autocomplete="current-password"></label><button onclick="signIn()">Войти</button><p id="error" class="error"></p></main><script>
async function signIn(){const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login:login.value,password:password.value})});if(r.ok)location='/';else error.textContent='Неверный логин или пароль.'}
</script></body></html>"""

APP_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>UzLocEng AI — Демонстрация</title>
<style>body{margin:0;background:#f2f6fa;color:#102a43;font:16px Arial,sans-serif}.top{background:#062f4f;color:#fff;padding:18px 7%;display:flex;justify-content:space-between}.wrap{max-width:980px;margin:30px auto;padding:0 20px}.panel{background:#fff;padding:24px;margin:18px 0;border-radius:12px;box-shadow:0 4px 16px #1232}textarea,select{width:100%;min-height:52px;padding:12px;box-sizing:border-box;border:1px solid #b8c6d4;border-radius:8px;font:inherit}textarea{min-height:110px}button{margin-top:12px;background:#087e8b;color:white;border:0;padding:12px 18px;border-radius:8px;font-weight:bold;cursor:pointer}.hidden{display:none}.answer{white-space:pre-wrap;line-height:1.6}.formula{margin:10px 0;padding:12px 14px;border-left:4px solid #087e8b;background:#f6fbfb;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}.calculation-result{margin-top:10px;font-weight:bold;color:#075d67}.tag{display:inline-block;background:#d9f3f4;color:#075d67;border-radius:14px;padding:4px 10px;margin-right:6px}.evidence{border-left:4px solid #087e8b;padding:10px 14px;background:#f6fbfb;margin:8px 0}.muted{color:#486581}.directions{display:flex;gap:8px;flex-wrap:wrap}.direction{border:1px solid #b8c6d4;border-radius:8px;padding:9px 12px;background:#f6fbfb}</style>
</head><body><header class="top"><strong>UzLocEng AI</strong><span>Демонстрационная версия</span></header><main class="wrap"><section class="panel"><h2>Демонстрационные направления</h2><p class="muted">Демонстрационная база поддерживает поиск параметров, сопоставление данных и отдельные инженерные расчёты.</p><div class="directions"><span class="direction">Энергетика</span><span class="direction">Механика</span><span class="direction">Технология</span></div></section><section class="panel"><h1>Технический вопрос</h1><p><span class="tag">Синтетическая база знаний</span></p><label>Направление<select id="domain"><option value="energy">Энергетика</option><option value="mechanics">Механика</option><option value="technology">Технология</option></select></label><textarea id="question" placeholder="Введите технический вопрос на русском языке"></textarea><button onclick="ask()">Получить ответ</button></section><section id="result" class="panel hidden"><h2>Ответ</h2><div id="answer" class="answer"></div><h3>Использованные источники</h3><div id="citations"></div><h3>Доказательства</h3><div id="evidence"></div></section></main><script>
function esc(v){const e=document.createElement('span');e.textContent=v;return e.innerHTML}async function ask(){const question=document.getElementById('question').value.trim();if(!question)return;const r=await fetch('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,domain:domain.value})});if(r.status===401){location='/login';return}const data=await r.json();result.classList.remove('hidden');answer.innerHTML=data.formula?'<div class="formula">'+data.formula.map(esc).join('\n')+'</div><div class="calculation-result">'+esc(data.answer)+'</div>':esc(data.answer);citations.innerHTML=data.citations.length?data.citations.map(x=>'<span class="tag">['+esc(x)+']</span>').join(''):'<span class="muted">Нет использованных источников.</span>';evidence.innerHTML=data.evidence.length?data.evidence.map(x=>'<div class="evidence">'+esc(x)+'</div>').join(''):'<span class="muted">Нет доказательств.</span>'}
</script></body></html>"""


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "UzLocEngPublicDemo/3.0"

    @property
    def username(self) -> str: return self.server.username  # type: ignore[attr-defined]

    @property
    def password(self) -> str: return self.server.password  # type: ignore[attr-defined]

    def _session_token(self) -> str | None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        return cookie.get("uzloceng_demo_session").value if "uzloceng_demo_session" in cookie else None

    def _authenticated(self) -> bool:
        token = self._session_token()
        return bool(token and token in SESSIONS)

    def _send(self, status: HTTPStatus, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8"); self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(data)

    def _json(self, status: HTTPStatus, payload: dict[str, object], cookie: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8"); self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(data)))
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
            if not self._authenticated(): self.send_response(HTTPStatus.SEE_OTHER); self.send_header("Location", "/login"); self.end_headers(); return
            self._send(HTTPStatus.OK, APP_PAGE)
        else: self._send(HTTPStatus.NOT_FOUND, "Страница не найдена.")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try: payload = self._payload()
        except (ValueError, json.JSONDecodeError): self._json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос."}); return
        if path == "/api/login":
            valid = hmac.compare_digest(payload.get("login", ""), self.username) and hmac.compare_digest(payload.get("password", ""), self.password)
            if not valid: self._json(HTTPStatus.UNAUTHORIZED, {"error": "Неверные учётные данные."}); return
            token = secrets.token_urlsafe(32); SESSIONS.add(token); self._json(HTTPStatus.OK, {"ok": True}, f"uzloceng_demo_session={token}; HttpOnly; SameSite=Lax; Path=/"); return
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
