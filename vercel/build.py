"""Read-only copy of the platform for Vercel (for people without claude.ai access).
python3 build.py [seed_dir] -> site/index.html with data from seed/<collection>/<id>.json and a mocked window.claude
(no writes, no Claude). The live layer (live_overlay.js) is wired to /api/live, refreshed every 5 minutes."""
import json, os, sys, glob
B = os.path.dirname(os.path.abspath(__file__))
seed = sys.argv[1] if len(sys.argv) > 1 else os.path.join(B, "..", "seed_example")
page = open(os.path.join(B, "..", "platform.html"), encoding="utf-8").read()
data = {}
for f in glob.glob(os.path.join(seed, "*", "*.json")):
    col = os.path.basename(os.path.dirname(f)); doc = os.path.splitext(os.path.basename(f))[0]
    data.setdefault(col, {})[doc] = json.load(open(f, encoding="utf-8"))
mock = """<script>
const DATA=%s;
const mkSnap=p=>({docs:Object.entries(DATA[p]||{}).map(([id,v])=>({id,data:()=>v}))});
const dbm={collection:p=>({onSnapshot:cb=>{setTimeout(()=>cb(mkSnap(p)),0);return()=>{}},add:async()=>{throw new Error("read-only")}}),doc:p=>({set:async()=>{throw new Error("read-only")},update:async()=>{throw new Error("read-only")}})};
const um={me:async()=>({id:"u_view",name:"",isOwner:false,canEdit:false}),can:async()=>false,profiles:async()=>({})};
window.claude={use:async n=>n==="db"?dbm:n==="user"?um:null};
</script>""" % json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
loader = """<script>
async function liveLoad(){try{const r=await fetch("/api/live",{cache:"no-store"});if(!r.ok)throw new Error("HTTP "+r.status);const L=await r.json();
  const wait=()=>new Promise(ok=>{const t=setInterval(()=>{if(S.ready){clearInterval(t);ok()}},150)});await wait();liveApply(L)}catch(e){LIVE.err=String(e.message||e)}liveBadge();render()}
liveLoad();setInterval(liveLoad,5*60*1000);document.addEventListener("visibilitychange",()=>{if(!document.hidden)liveLoad()});
</script>"""
i = page.rfind("<script>")
head = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
out = head + page[:i] + mock + page[i:] + loader
open(os.path.join(B, "site", "index.html"), "w", encoding="utf-8").write(out)
print("site/index.html", len(out))
