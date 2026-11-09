# -*- coding: utf-8 -*-
"""Сторож пульсу команди: Telegram партнеру на кожну відповідь Google-форми пульсу. Без LLM.

Форма: 4 питання (Your name списком, Energy 1-5, How clear 1-5, What blocks you most). Одна форма на всі місяці,
раунд визначається датою відповіді (PULSE_ROUNDS). Розбір робить сесія Claude («розбери пульс») і пише в платформу,
колекція `pulse`, документ = дата старту раунду.

Налаштування (.env поруч або змінні середовища):
  BOT_TOKEN, TG_CHAT_ID           Telegram-бот і чат, куди слати
  PULSE_FORM_ID                   ID Google-форми (з URL docs.google.com/forms/d/<ID>/edit)
  PULSE_ROSTER                    хто має відповісти, як у списку «Your name»: "Anna,Oleh,Maria"
  PULSE_ROUNDS                    раунди старт:дедлайн через кому: "2026-11-23:2026-11-25,2026-12-21:2026-12-23"
  GOOGLE_TOKEN_FILE               authorized_user JSON з scope forms.body.readonly + forms.responses.readonly
  TZ_NAME                         таймзона команди, за замовчуванням America/New_York

Запуск:  python pulse_watch.py [--seed | --status | --dry]
Cron:    */15 * * * * cd /path && flock -n /tmp/pulse_watch.lock python pulse_watch.py >> state/pulse_watch.log 2>&1
"""
import datetime, html, json, os, sys, time, urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state", "pulse_seen.json")
FORM_ID = None  # з env, див. main()
NY = ZoneInfo(os.environ.get("TZ_NAME", "America/New_York"))
ROSTER = []  # з env PULSE_ROSTER
ROUNDS = []  # з env PULSE_ROUNDS
DIGEST_HOUR_NY = 10  # підсумок «хто не відповів» не раніше 10:00 NY наступного дня після дедлайну
FLAG_AT = 2          # 2 і нижче по енергії або ясності = флаг


def env(name):
    v = os.environ.get(name)
    if v:
        return v
    try:
        for line in open(os.path.join(HERE, ".env"), encoding="utf-8"):
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return ""


def api(url):
    """GET до Google API з токеном authorized_user (google-auth)."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    cr = Credentials.from_authorized_user_file(env("GOOGLE_TOKEN_FILE"))
    if not cr.valid:
        cr.refresh(Request())
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + cr.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def configure():
    global FORM_ID, ROSTER, ROUNDS
    FORM_ID = env("PULSE_FORM_ID")
    ROSTER = [x.strip() for x in env("PULSE_ROSTER").split(",") if x.strip()]
    ROUNDS = [tuple(x.strip().split(":")) for x in env("PULSE_ROUNDS").split(",") if ":" in x]
    if not (FORM_ID and ROSTER and ROUNDS):
        sys.exit("Заповни PULSE_FORM_ID, PULSE_ROSTER, PULSE_ROUNDS у .env")


def tg(text, dry=False):
    if dry:
        print("[dry tg]\n" + text + "\n"); return
    tok, chat = env("BOT_TOKEN"), env("TG_CHAT_ID")
    if not (tok and chat):
        print("[tg] немає BOT_TOKEN або TG_CHAT_ID"); return
    payload = {"chat_id": int(chat), "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load_state():
    try:
        s = json.load(open(STATE))
        return {"seen": set(s.get("seen", [])), "notified": set(s.get("notified", []))}
    except (FileNotFoundError, ValueError):
        return {"seen": set(), "notified": set()}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump({"seen": sorted(s["seen"]), "notified": sorted(s["notified"])}, open(STATE, "w"), indent=1)


def responses():
    form = api(f"https://forms.googleapis.com/v1/forms/{FORM_ID}")
    qmap = {}
    for it in form.get("items", []):
        q = it.get("questionItem", {}).get("question", {})
        if q.get("questionId"):
            t = it.get("title", "").lower()
            qmap[q["questionId"]] = "name" if "name" in t else "energy" if "energy" in t else "clarity" if "clear" in t else "blocker"
    out = []
    for r in api(f"https://forms.googleapis.com/v1/forms/{FORM_ID}/responses").get("responses", []):
        x = {"id": r.get("responseId", ""), "at": r.get("lastSubmittedTime") or r.get("createTime", "")}
        for qid, a in r.get("answers", {}).items():
            vals = [t.get("value", "") for t in a.get("textAnswers", {}).get("answers", [])]
            x[qmap.get(qid, qid)] = ", ".join(vals).strip()
        x["ny"] = datetime.datetime.fromisoformat(x["at"].replace("Z", "+00:00")).astimezone(NY)
        out.append(x)
    return sorted(out, key=lambda x: x["at"])


def round_of(dt_ny):
    d = dt_ny.date().isoformat()
    cur = None
    for start, deadline in ROUNDS:
        if start <= d:
            cur = (start, deadline)
    return cur


def current_round(now_ny):
    return round_of(now_ny)


def in_round(rs, rnd):
    return [r for r in rs if round_of(r["ny"]) == rnd and r.get("name", "").upper() != "TEST"]


def tally(rs, rnd):
    got = {}
    for r in in_round(rs, rnd):
        got[r.get("name", "?")] = r  # остання відповідь людини в раунді
    missing = [n for n in ROSTER if n not in got]
    return got, missing


def esc(t):
    return html.escape(t, quote=False)


def num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def describe(r, rs):
    rnd = round_of(r["ny"])
    got, missing = tally([x for x in rs if x["at"] <= r["at"]], rnd)  # стан на момент цієї відповіді
    e, c = num(r.get("energy")), num(r.get("clarity"))
    flag = (e is not None and e <= FLAG_AT) or (c is not None and c <= FLAG_AT)
    lines = [f"📊 <b>Пульс: {esc(r.get('name', '?'))}</b> · енергія {r.get('energy', '?')} · ясність {r.get('clarity', '?')}",
             f"Заважало: {esc(r.get('blocker', '') or '—')}"]
    if flag:
        lines.append(f"⚠️ {FLAG_AT} і нижче: 1:1 протягом 5 робочих днів, CEO рядок «⚠️ + що зробив»")
    lines.append(f"Відповіли {len(got)} з {len(ROSTER)}" + (f" · чекаємо: {', '.join(missing)}" if missing else " · усі ✅"))
    if not missing:
        lines.append("Розбір: «розбери пульс» у сесії Claude → платформа")
    return "\n".join(lines)


def summary(rs, rnd, title):
    got, missing = tally(rs, rnd)
    es = [num(r.get("energy")) for r in got.values() if num(r.get("energy")) is not None]
    cs = [num(r.get("clarity")) for r in got.values() if num(r.get("clarity")) is not None]
    avg = lambda a: f"{sum(a) / len(a):.1f}" if a else "?"
    lines = [f"📊 <b>{title}</b> (старт {rnd[0][8:10]}.{rnd[0][5:7]}, дедлайн {rnd[1][8:10]}.{rnd[1][5:7]})",
             f"Відповіли {len(got)} з {len(ROSTER)} · енергія {avg(es)} · ясність {avg(cs)}"]
    lines.append(f"Не відповіли: {', '.join(missing)}" if missing else "Відповіли всі ✅")
    for n, r in got.items():
        lines.append(f"• {esc(n)}: {r.get('energy', '?')}/{r.get('clarity', '?')}")
    lines.append("Розбір: «розбери пульс» у сесії Claude → платформа")
    return "\n".join(lines)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    dry = mode == "--dry"
    configure()
    now = datetime.datetime.now(NY)
    st = load_state()
    rs = responses()
    if mode == "--seed":
        st["seen"] = {r["id"] for r in rs}; save_state(st); print(f"seed: {len(rs)} відповідей позначено як побачені"); return
    rnd = current_round(now)
    if mode == "--status":
        tg(summary(rs, rnd, "Пульс: стан зараз") if rnd else "📊 pulse_watch працює, раунду пульсу зараз немає"); print("status sent"); return
    new = [r for r in rs if r["id"] not in st["seen"]]
    for r in new:
        tg(describe(r, rs), dry); print(now.strftime("%Y-%m-%d %H:%M"), "нова відповідь:", r["id"][:12], r.get("name"))
    # Підсумок після дедлайну: один раз на раунд, не раніше DIGEST_HOUR_NY наступного дня
    for start, deadline in ROUNDS:
        due = datetime.datetime.fromisoformat(deadline).replace(tzinfo=NY) + datetime.timedelta(days=1, hours=DIGEST_HOUR_NY)
        if start not in st["notified"] and start <= now.date().isoformat() and now >= due and now - due < datetime.timedelta(days=3):
            tg(summary(rs, (start, deadline), "Пульс: дедлайн минув"), dry); st["notified"].add(start)
            print(now.strftime("%Y-%m-%d %H:%M"), "підсумок раунду", start)
    if not dry:
        st["seen"] |= {r["id"] for r in rs}
        save_state(st)
    if not new:
        print(now.strftime("%Y-%m-%d %H:%M"), f"нових немає ({len(rs)} всього)")


if __name__ == "__main__":
    main()
