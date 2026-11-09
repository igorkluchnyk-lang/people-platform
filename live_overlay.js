/* Live layer (shared by the Vercel copy and the claude.ai artifact).
   liveApply(L) takes the /api/live payload: { asOf, months:[{id,person,createdAt,goals:[{id,title,url,due,state,type,completedAt}]}], company:{patients,target,arr,postedAt} }
   and patches S in place: statuses from Linear, new month goals appear by themselves, previous month goals go to the archive,
   company patients come from the Slack goals channel. Goals done since the viewer's last visit get g.fresh=true. */
const LIVE={at:null,ok:null,err:null,src:[]};
const liveId=u=>{const m=String(u||"").match(/issue\/([A-Z]+-\d+)/);return m?m[1]:null};
function liveStatus(x){if(x.type==="completed")return"done";if(x.type==="canceled")return"dropped";if(/review/i.test(x.state||""))return"waiting";
  if(x.due&&x.due<TODAY)return"behind";if(x.due&&dayDiff(TODAY,x.due)<=3&&x.type!=="started")return"at_risk";return"on_track"}
function liveApply(L){if(!L)return;LIVE.at=L.asOf;LIVE.src=L.sources||[];LIVE.ok=(L.sources||[]).every(s=>s.ok!==false);
  const months=L.months||[],latest={};months.forEach(p=>{if(!latest[p.person]||p.createdAt>latest[p.person].createdAt)latest[p.person]=p});
  const older=new Set(),byId={};months.forEach(p=>p.goals.forEach(g=>{byId[g.id]={...g,person:p.person,parentIssue:p.id};if(latest[p.person]!==p)older.add(g.id)}));
  let seen=[];try{seen=JSON.parse(localStorage.getItem("cp_live_done")||"[]")}catch(e){}
  const mark=(g,x)=>{const ns=liveStatus(x);if(!(g.status==="paused"&&ns!=="done"))g.status=ns;g.live=x.state;g.liveAt=L.asOf;g.doneAt=x.completedAt?x.completedAt.slice(0,10):null;if(x.due)g.due=x.due;if(g.status==="done"&&!seen.includes(x.id))g.fresh=true};
  S.goals.forEach(g=>{const id=liveId(g.url);if(!id||!byId[id])return;mark(g,byId[id]);if(older.has(id))g.archived=true});
  Object.values(latest).forEach(p=>p.goals.forEach((x,i)=>{if(S.goals.some(g=>liveId(g.url)===x.id))return;
    const n=(x.title.match(/goal\s*(\d+)/i)||[])[1];const g={id:"lin-"+x.id,person:p.person,title:x.title.replace(/^.*?goal\s*\d+\s*[:.]\s*/i,""),url:x.url,source:"Linear "+p.id+" · "+p.title,order:"L"+String(n||i+1).padStart(2,"0"),measure:"на свою дату виконано або ні",parent:null};mark(g,x);S.goals.push(g)}));
  S.goals=S.goals.filter(g=>!g.archived);
  const done=S.goals.filter(g=>g.status==="done"&&liveId(g.url)).map(g=>liveId(g.url));try{localStorage.setItem("cp_live_done",JSON.stringify([...new Set([...seen,...done])].slice(-500)))}catch(e){}
  const c=L.company;if(c&&c.patients!=null){const co=S.goals.find(g=>g.level==="company");if(co){co.current=c.patients;if(c.target)co.target=c.target;co.liveAt=c.postedAt}
    let m=S.company.find(x=>x.id==="main");if(!m){m={id:"main"};S.company.push(m)}m.patients={...(m.patients||{}),current:c.patients,target:c.target||250,asOf:String(c.postedAt||"").slice(0,10)};if(c.arr!=null)m.arr={current:c.arr,target:c.arrTarget}}}
function liveBadge(){const w=document.getElementById("who");if(!w)return;let b=document.getElementById("livebadge");if(!b){b=document.createElement("span");b.id="livebadge";b.className="pill";b.style.cssText="font-size:12px;white-space:nowrap;margin-right:6px";w.prepend(b)}
  if(!LIVE.at){b.className="pill";b.textContent=LIVE.err?"● offline":"● …";b.title=LIVE.err||"";return}
  const t=new Intl.DateTimeFormat("en-GB",{timeZone:"America/New_York",hour:"2-digit",minute:"2-digit"}).format(new Date(LIVE.at));
  b.className="pill "+(LIVE.ok?"good":"warn");b.textContent="● Live "+t+" NY";b.title=LIVE.src.map(s=>s.name+(s.ok===false?" ✗ "+(s.error||""):" ✓")).join(" · ")}
