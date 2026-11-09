// Live layer for People Platform: goals from Linear ("<Name>'s <Month> goals" parent issues and their children)
// and company numbers from the daily bot post in a Slack goals channel. Read-only, behind the same password middleware.
// Env: LINEAR_API_KEY, SLACK_TOKEN (optional), GOALS_CHANNEL, PEOPLE_MAP.
const PEOPLE = JSON.parse(process.env.PEOPLE_MAP || "{}"); // {"ana":"anna"}: first word of "<Name>'s <Month> goals" → person key
const MONTHS = ["january","february","march","april","may","june","july","august","september","october","november","december"];

function personKey(title, assignee) {
  const m = String(title).match(/^(\S+?)['’]s\s+([A-Za-z]+)\s+goals/i);
  const first = (m ? m[1] : String(assignee || "").split(" ")[0]).toLowerCase();
  return PEOPLE[first] || first;
}

async function linear(query, variables) {
  const r = await fetch("https://api.linear.app/graphql", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: process.env.LINEAR_API_KEY },
    body: JSON.stringify({ query, variables }),
  });
  const j = await r.json();
  if (j.errors) throw new Error(j.errors.map(e => e.message).join("; "));
  return j.data;
}

const Q = `query($after:String){ issues(first:50, after:$after, filter:{ title:{ containsIgnoreCase:"goals" }, createdAt:{ gt:"-P120D" } }){
  pageInfo{ hasNextPage endCursor }
  nodes{ identifier title url createdAt assignee{ name } parent{ identifier }
    children(first:50){ nodes{ identifier title url dueDate completedAt canceledAt updatedAt state{ name type } } } } } }`;

async function goals() {
  const parents = [];
  let after = null;
  for (let i = 0; i < 4; i++) {
    const d = await linear(Q, { after });
    for (const n of d.issues.nodes) {
      const m = String(n.title).match(/['’]s\s+([A-Za-z]+)\s+goals/i);
      if (!m || n.parent || !MONTHS.includes(m[1].toLowerCase())) continue;
      parents.push({
        id: n.identifier, title: n.title, url: n.url, createdAt: n.createdAt,
        month: MONTHS.indexOf(m[1].toLowerCase()) + 1,
        person: personKey(n.title, n.assignee && n.assignee.name),
        goals: n.children.nodes.map(c => ({
          id: c.identifier, title: c.title, url: c.url, due: c.dueDate, state: c.state.name, type: c.state.type,
          completedAt: c.completedAt, canceledAt: c.canceledAt, updatedAt: c.updatedAt,
        })),
      });
    }
    if (!d.issues.pageInfo.hasNextPage) break;
    after = d.issues.pageInfo.endCursor;
  }
  return parents.sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
}

async function company() {
  const tok = process.env.SLACK_TOKEN;
  if (!tok) return null;
  const ch = process.env.GOALS_CHANNEL;
  if (!ch) return null;
  const r = await fetch(`https://slack.com/api/conversations.history?channel=${ch}&limit=15`, { headers: { Authorization: "Bearer " + tok } });
  const j = await r.json();
  if (!j.ok) return { error: j.error };
  const m = (j.messages || []).find(x => /active patients/.test(x.text || ""));
  if (!m) return null;
  const t = m.text;
  const num = re => { const x = t.match(re); return x ? Number(x[1].replace(/,/g, "")) : null; };
  const arr = t.match(/\*\$([\d.]+)([KM])\*\s+of\s+\$([\d.]+)([KM])\s+ARR/);
  const k = (v, u) => Number(v) * (u === "M" ? 1e6 : 1e3);
  return {
    patients: num(/\*(\d+)\*\s+of\s+\d+\s+active patients/), target: num(/of\s+(\d+)\s+active patients/),
    newToday: num(/\+(\d+)\s+new/), leftToday: num(/−(\d+)\s+left/),
    arr: arr ? k(arr[1], arr[2]) : null, arrTarget: arr ? k(arr[3], arr[4]) : null,
    postedAt: new Date(Number(m.ts) * 1000).toISOString(), text: t.slice(0, 600),
  };
}

export default async function handler(req, res) {
  const out = { asOf: new Date().toISOString(), sources: [] };
  try { out.months = await goals(); out.sources.push({ name: "Linear", ok: true, n: out.months.length }); }
  catch (e) { out.months = []; out.sources.push({ name: "Linear", ok: false, error: String(e.message || e) }); }
  try { out.company = await company(); out.sources.push({ name: "goals channel", ok: !!(out.company && !out.company.error) }); }
  catch (e) { out.company = null; out.sources.push({ name: "goals channel", ok: false, error: String(e.message || e) }); }
  res.setHeader("Cache-Control", "s-maxage=120, stale-while-revalidate=600");
  res.status(200).json(out);
}
