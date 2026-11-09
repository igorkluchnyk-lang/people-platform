#!/usr/bin/env python3
"""Щоденний рух по цілях людей у Slack the goals channel (без LLM).

Джерела: Linear (батьківські задачі «<Name>'s <Month> goals» і їхні дочірні цілі) + ранковий пост бота про 250 пацієнтів.
Пише відповідь у тред під сьогоднішнім постом бота (або окреме повідомлення, якщо поста ще немає).
Запуск: python3 goals_daily.py            -> тільки друкує чернетку
        python3 goals_daily.py --send     -> відправляє (сервер, cron 10:05 NY пн-пт)
Env: LINEAR_API_KEY, SLACK_TOKEN, GOALS_CHANNEL .
Стан (що вже було done вчора): goals_daily_state.json поруч зі скриптом.
"""
import json, os, re, sys, urllib.request, urllib.parse, datetime as dt
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
CH = os.environ["GOALS_CHANNEL"]
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goals_daily_state.json")
NAMES = json.loads(os.environ.get("NAMES_MAP", "{}"))  # {"anna": "Anna"}: person key → display name
MONTHS = ["january","february","march","april","may","june","july","august","september","october","november","december"]

def post(url, data, headers):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json", **headers})
    return json.load(urllib.request.urlopen(req, timeout=30))

def linear(q):
    r = post("https://api.linear.app/graphql", {"query": q}, {"Authorization": os.environ["LINEAR_API_KEY"]})
    if r.get("errors"): raise SystemExit(r["errors"])
    return r["data"]

def slack(method, params=None, body=None):
    tok = os.environ["SLACK_TOKEN"]
    if body is not None:
        return post("https://slack.com/api/" + method, body, {"Authorization": "Bearer " + tok})
    url = "https://slack.com/api/%s?%s" % (method, urllib.parse.urlencode(params or {}))
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}), timeout=30))

def months():
    q = '''{ issues(first:50, filter:{ title:{ containsIgnoreCase:"goals" }, createdAt:{ gt:"-P120D" } }){ nodes{
      identifier title createdAt parent{ identifier } assignee{ name }
      children(first:50){ nodes{ identifier title dueDate completedAt state{ name type } } } } } }'''
    out = []
    for n in linear(q)["issues"]["nodes"]:
        m = re.search(r"^(\S+?)['’]s\s+([A-Za-z]+)\s+goals", n["title"], re.I)
        if not m or n["parent"] or m.group(2).lower() not in MONTHS: continue
        out.append({"id": n["identifier"], "who": NAMES.get(m.group(1).lower(), m.group(1)), "month": m.group(2).capitalize(),
                    "createdAt": n["createdAt"], "goals": n["children"]["nodes"]})
    latest = {}
    for p in sorted(out, key=lambda x: x["createdAt"]):
        latest[p["who"]] = p
    return list(latest.values())

def status(g, today):
    t = g["state"]["type"]
    if t == "completed": return "done"
    if t == "canceled": return "dropped"
    if re.search("review", g["state"]["name"], re.I): return "review"
    if g.get("dueDate") and g["dueDate"] < today: return "overdue"
    return "open"

def short(title):
    return re.sub(r"^.*?goal\s*\d+\s*[:.]\s*", "", title, flags=re.I)

def build(today):
    try: prev = json.load(open(STATE))
    except Exception: prev = {"done": []}
    lines, done_now = [], []
    for p in sorted(months(), key=lambda x: x["who"]):
        gs = [g for g in p["goals"] if g["state"]["type"] != "canceled"]
        if not gs: continue
        st = {g["identifier"]: status(g, today) for g in gs}
        d = sum(1 for v in st.values() if v == "done"); rv = sum(1 for v in st.values() if v == "review"); od = [g for g in gs if st[g["identifier"]] == "overdue"]
        nxt = sorted([g for g in gs if st[g["identifier"]] in ("open", "review") and g.get("dueDate")], key=lambda g: g["dueDate"])
        bar = "🟩" * d + "🟨" * rv + "⬜" * (len(gs) - d - rv - len(od)) + "🟥" * len(od)
        s = f"*{p['who']}* · {p['month']}: {d}/{len(gs)} done {bar}"
        if rv: s += f" · {rv} in review"
        if nxt: s += f"\n      next: {short(nxt[0]['title'])} · due {dt.date.fromisoformat(nxt[0]['dueDate']).strftime('%b %-d')}"
        if od: s += "\n      past due: " + "; ".join(short(g["title"]) for g in od)
        for g in gs:
            if st[g["identifier"]] == "done":
                done_now.append(g["identifier"])
                if g["identifier"] not in prev.get("done", []): s += f"\n      ✅ done: {short(g['title'])}"
        lines.append(s)
    return lines, done_now

def main():
    send = "--send" in sys.argv
    now = dt.datetime.now(NY); today = now.date().isoformat()
    lines, done_now = build(today)
    head = f"*Team goals, {now.strftime('%a %b %-d')}*  (live from Linear)"
    text = head + "\n" + ("\n".join(lines) if lines else "No monthly goals in Linear yet.")
    h = slack("conversations.history", {"channel": CH, "limit": 10, "oldest": str(now.replace(hour=0, minute=0, second=0).timestamp())})
    parent = next((m for m in h.get("messages", []) if "active patients" in (m.get("text") or "")), None)
    if not send:
        print(text); print("\n[thread under bot post]" if parent else "\n[separate message: no bot post today yet]"); return
    body = {"channel": CH, "text": text, "unfurl_links": False}
    if parent: body["thread_ts"] = parent["ts"]
    r = slack("chat.postMessage", body=body)
    if not r.get("ok"): raise SystemExit(r)
    json.dump({"done": done_now, "sentAt": now.isoformat()}, open(STATE, "w"))
    print("sent", r["ts"])

if __name__ == "__main__":
    main()
