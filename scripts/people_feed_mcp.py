#!/usr/bin/env python3
"""people-feed: local MCP server (stdio) for the brief button of People Platform. READ ONLY.

Why: the claude.ai Slack connector may point at another workspace and the Gmail connector at a personal inbox,
so the page cannot see the team's Slack or the work mailbox. This server runs on the owner's computer, reads the
team Slack (user token, read-only scopes) and the work mailbox, and hands the page one compact feed per person.
The page calls it as `host:people-feed` (Claude desktop app, page opened by its owner).

Settings (environment, or KEY=value lines in SECRETS_FILE):
  SLACK_USER_TOKEN   Slack user token of the people partner, read-only scopes:
                     search:read, users:read, im:history (for LEAD_DM_CHANNEL)
  OWNER_SLACK_ID     people partner's Slack user id (owner of the page)
  LEAD_SLACK_ID      lead's (CEO's) Slack user id
  LEAD_DM_CHANNEL    id of the DM between the people partner and the lead (their notes about people)
  TEAM_CHANNEL       id of the team channel where the partner and the lead post meeting recaps
  GOOGLE_TOKEN_FILE  authorized_user JSON (client_id, client_secret, refresh_token, token_uri),
                     scope gmail.readonly, for the work mailbox
  MAILBOX_ADDRESS    optional: work mailbox address, only for links (authuser=...)
  TZ_NAME            optional: team time zone for date labels, default America/New_York
  SECRETS_FILE       optional: path to a KEY=value file, read when a variable is not in the environment

Tool `person_feed` {slack_id, names[], emails[], since:"YYYY-MM-DD", history_since} returns JSON:
  counts + from_person, dm_owner, mentions, dm_lead, team, mail, declines, errors
  (each item: d "DD.MM", ch, who, t text, l link).

Install (once): claude mcp add --scope user people-feed -- python3 /path/to/people_feed_mcp.py
Test:           python3 scripts/people_feed_mcp.py --test <slack_id> <YYYY-MM-DD> <name> [<name> ...]
"""
import datetime, json, os, re, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

_secrets = None
_users = {}


def env(k):
    global _secrets
    if os.environ.get(k):
        return os.environ[k]
    if _secrets is None:
        _secrets = {}
        path = os.environ.get("SECRETS_FILE")
        if path:
            try:
                for line in open(os.path.expanduser(path)):
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        a, b = line.split("=", 1)
                        _secrets[a.strip()] = b.strip().strip('"').strip("'")
            except OSError:
                pass
    return _secrets.get(k, "")


OWNER = env("OWNER_SLACK_ID")
LEAD = env("LEAD_SLACK_ID")
DM_LEAD = env("LEAD_DM_CHANNEL")
TEAM_CH = env("TEAM_CHANNEL")
TZ = ZoneInfo(env("TZ_NAME") or "America/New_York")  # date labels only


def slack(method, params):
    tok = env("SLACK_USER_TOKEN")
    if not tok:
        raise RuntimeError("SLACK_USER_TOKEN not set")
    u = "https://slack.com/api/" + method + "?" + urllib.parse.urlencode(params)
    r = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "Bearer " + tok}), timeout=30))
    if not r.get("ok"):
        raise RuntimeError("slack " + method + ": " + str(r.get("error")))
    return r


def uname(uid):
    if not _users:
        try:
            cur = ""
            while True:
                r = slack("users.list", {"limit": 200, "cursor": cur})
                for m in r.get("members", []):
                    p = m.get("profile") or {}
                    _users[m["id"]] = p.get("display_name") or p.get("real_name") or m.get("name") or m["id"]
                cur = (r.get("response_metadata") or {}).get("next_cursor") or ""
                if not cur:
                    break
        except Exception:
            _users["_"] = "_"
    return _users.get(uid, uid)


def clean(t, n):
    t = re.sub(r"<@(U[A-Z0-9]+)(\|[^>]*)?>", lambda m: "@" + uname(m.group(1)), t or "")
    t = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2", t)
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n] + ("…" if len(t) > n else "")


def day(ts):
    return datetime.datetime.fromtimestamp(float(ts), TZ).strftime("%d.%m")


def search(q, n=500, count=40):
    r = slack("search.messages", {"query": q, "count": count, "sort": "timestamp", "sort_dir": "asc"})
    out = []
    for m in r["messages"]["matches"]:
        ch = m.get("channel") or {}
        name = "DM" if ch.get("is_im") or str(ch.get("id", "")).startswith("D") else "#" + str(ch.get("name", ""))
        out.append({"d": day(m["ts"]), "ch": name, "who": m.get("username") or uname(m.get("user", "")),
                    "t": clean(m.get("text"), n), "l": m.get("permalink", ""), "_ts": m["ts"]})
    return out


def feed(slack_id, names, emails, since, history_since=None):
    after = (datetime.date.fromisoformat(since) - datetime.timedelta(days=1)).isoformat()  # Slack after: is exclusive
    res = {"since": since, "errors": []}

    # short names (3 letters) must end as a whole word, so a short name does not catch a longer one that starts the same;
    # longer names match by stem to catch Ukrainian cases
    def stem(x):  # Олена → Олен (Олені, Оленою), Марія → Марі (Марії, Марією)
        return x[:-1] if len(x) >= 4 and x[-1].lower() in "аяіоеєуюиь" else x
    alts = [re.escape(stem(x)) + (r"\b" if len(x) <= 3 else "") for x in names if x and len(x) > 2]
    pat = re.compile(r"\b(" + "|".join(alts) + r")", re.I) if alts else None

    def safe(key, fn):
        try:
            res[key] = fn()
        except Exception as e:
            res[key] = []
            res["errors"].append(key + ": " + str(e)[:120])

    if slack_id:
        safe("from_person", lambda: [x for x in search(f"from:<@{slack_id}> after:{after}", 700) if x["ch"] != "DM"])
        safe("dm_owner", lambda: search(f"in:<@{slack_id}> after:{after}", 400))  # the token is the owner's: DM owner↔person
        safe("mentions", lambda: [x for x in search(f"<@{slack_id}> after:{after}", 900) if x["who"] != uname(slack_id)])
    else:
        res.update(from_person=[], dm_owner=[], mentions=[])

    def dml():
        if not DM_LEAD:
            raise RuntimeError("LEAD_DM_CHANNEL not set")
        h = min(since, history_since or since)  # partner's notes about the person: longer window (6 weeks) for open loops
        r = slack("conversations.history", {"channel": DM_LEAD, "oldest": str(time.mktime(time.strptime(h, "%Y-%m-%d"))), "limit": 400})
        out = []
        for m in reversed(r.get("messages", [])):
            t = m.get("text", "")
            if pat and pat.search(t) or (slack_id and slack_id in t):
                out.append({"d": day(m["ts"]), "ch": "DM партнер↔лід", "who": uname(m.get("user", "")), "t": clean(t, 1800), "l": ""})
        return out
    safe("dm_lead", dml)

    def team():
        if not TEAM_CH:
            raise RuntimeError("TEAM_CHANNEL not set")
        out = []
        for who in [x for x in (OWNER, LEAD) if x]:
            for x in search(f"in:<#{TEAM_CH}> from:<@{who}> after:{after}", 1500):
                if len(x["t"]) >= 280:  # recaps: weekly sync, monthly, strategy session
                    out.append(x)
        seen = set()
        mention = {x["_ts"] for x in res.get("mentions", [])}
        out = [x for x in sorted(out, key=lambda x: x["_ts"]) if not (x["_ts"] in seen or seen.add(x["_ts"]))]
        for x in out:
            x["mentionsPerson"] = x["_ts"] in mention
        res["mentions"] = [x for x in res.get("mentions", []) if x["_ts"] not in seen]  # recaps live in team
        return out
    safe("team", team)

    def mail():
        if not emails:
            return []
        tf = os.path.expanduser(env("GOOGLE_TOKEN_FILE"))
        if not tf or not os.path.exists(tf):
            raise RuntimeError("GOOGLE_TOKEN_FILE not set or not found")
        t = json.load(open(tf))
        d = urllib.parse.urlencode({"client_id": t["client_id"], "client_secret": t["client_secret"],
                                    "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
        tok = json.load(urllib.request.urlopen(urllib.request.Request(t.get("token_uri", "https://oauth2.googleapis.com/token"), data=d), timeout=30))["access_token"]

        def g(path, params):
            u = "https://gmail.googleapis.com/gmail/v1/users/me/" + path + "?" + urllib.parse.urlencode(params, doseq=True)
            return json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization": "Bearer " + tok}), timeout=30))
        box = env("MAILBOX_ADDRESS")
        link = "https://mail.google.com/mail/u/" + ("?authuser=" + urllib.parse.quote(box) if box else "0/") + "#all/"
        q = "(" + " OR ".join(f"from:{e} OR to:{e}" for e in emails) + f") after:{since.replace('-', '/')} -subject:Accepted -subject:Declined -subject:Invitation"
        out = []
        for m in g("messages", {"q": q, "maxResults": 15}).get("messages", []):
            m = g("messages/" + m["id"], {"format": "metadata", "metadataHeaders": ["From", "Subject"]})
            h = {x["name"]: x["value"] for x in m["payload"].get("headers", [])}
            out.append({"d": day(int(m["internalDate"]) / 1000), "ch": "робоча пошта", "who": h.get("From", "")[:60],
                        "t": (h.get("Subject", "") + ": " + m.get("snippet", ""))[:400],
                        "l": link + m["threadId"], "_ts": m["internalDate"]})
        out = sorted(out, key=lambda x: x["_ts"])
        dec = []  # calendar replies are noise, except declines: a declined 1:1 or sync changes the meeting
        for m in g("messages", {"q": "(" + " OR ".join(f"from:{e}" for e in emails) + f") subject:Declined after:{since.replace('-', '/')}", "maxResults": 10}).get("messages", []):
            m = g("messages/" + m["id"], {"format": "metadata", "metadataHeaders": ["Subject"]})
            h = {x["name"]: x["value"] for x in m["payload"].get("headers", [])}
            dec.append({"d": day(int(m["internalDate"]) / 1000), "ch": "календар", "t": h.get("Subject", "")[:200], "l": "", "_ts": m["internalDate"]})
        res["declines"] = sorted(dec, key=lambda x: x["_ts"])
        return out
    safe("mail", mail)

    caps = {"from_person": 15, "mentions": 10, "dm_owner": 20, "dm_lead": 12, "team": 8, "mail": 10, "declines": 5}
    res["counts"] = {k: len(res.get(k, [])) for k in caps}
    for k, n in caps.items():  # newest win when the window is long
        res[k] = res.get(k, [])[-n:]
        for x in res[k]:
            x.pop("_ts", None)
    return res


TOOL = {"name": "person_feed",
        "description": "Team Slack (the person's messages, mentions, DM with the people partner, partner↔lead DM lines about the person, "
                       "team channel recaps by the partner or the lead) and the work mailbox since a date. Read only.",
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
        "inputSchema": {"type": "object", "required": ["since"], "properties": {
            "slack_id": {"type": "string", "description": "Slack user id of the person (U...)"},
            "names": {"type": "array", "items": {"type": "string"}, "description": "name variants to find the person in the partner↔lead DM"},
            "emails": {"type": "array", "items": {"type": "string"}},
            "since": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
            "history_since": {"type": "string", "description": "YYYY-MM-DD; partner↔lead DM notes about the person from this date (open loops)"}}}}


def handle(msg):
    mid, method, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": p.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "people-feed", "version": "1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}}
    if method == "tools/call":
        a = p.get("arguments") or {}
        try:
            if p.get("name") != "person_feed":
                raise ValueError("unknown tool")
            since = str(a.get("since", ""))[:10]
            datetime.date.fromisoformat(since)
            hs = str(a.get("history_since") or "")[:10] or None
            if hs:
                datetime.date.fromisoformat(hs)
            r = feed(str(a.get("slack_id") or ""), [str(x) for x in a.get("names") or []], [str(x) for x in a.get("emails") or []], since, hs)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(r, ensure_ascii=False)}], "structuredContent": r}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "error: " + str(e)}], "isError": True}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return None


def main():
    if len(sys.argv) > 3 and sys.argv[1] == "--test":
        r = feed(sys.argv[2], sys.argv[4:], [], sys.argv[3])
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            out = handle(json.loads(line))
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if out:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
