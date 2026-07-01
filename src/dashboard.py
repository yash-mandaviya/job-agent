"""Build a self-contained, interactive HTML dashboard of all scraped jobs.

Reads the dedup store (data/seen_jobs.db) and renders a single local HTML file
(data/dashboard.html) with search, source/company/score filters, sorting, and a
clickable link to each posting. Fully offline — no external requests, no data
leaves the machine. Regenerated at the end of every run, or via
`python scripts/build_dashboard.py`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import store

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard.html"


def _hours_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def build_dashboard(out_path: Path | None = None) -> Path:
    out_path = out_path or OUT_PATH
    jobs = store.all_jobs()

    rows = []
    for j in jobs:
        hrs = _hours_since(j.get("first_seen"))
        rows.append({
            "company": j.get("company") or "—",
            "title": j.get("title") or "—",
            "source": (j.get("source") or "").split(":")[0] or "—",
            "url": j.get("url") or "",
            "score": j.get("score"),
            "emailed": bool(j.get("emailed_at")),
            "first_seen": j.get("first_seen") or "",
            "hours": round(hrs, 1) if hrs is not None else None,
        })

    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = (
        _TEMPLATE
        .replace("/*__JOBS__*/", json.dumps(rows, ensure_ascii=False))
        .replace("__GENERATED__", generated)
        .replace("__COUNT__", str(len(rows)))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Watcher — Dashboard</title>
<style>
  :root{
    --bg:#0b1020; --panel:#141b2e; --panel2:#1b2742; --line:#28324d;
    --txt:#e7ecf5; --muted:#93a1bd; --accent:#5b8cff; --accent2:#22d3ee;
    --good:#22c55e; --mid:#f59e0b; --low:#64748b; --pink:#f472b6;
  }
  *{box-sizing:border-box}
  body{margin:0;background:linear-gradient(160deg,#0b1020,#0e1530 60%,#0b1020);
    color:var(--txt);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  a{color:var(--accent);text-decoration:none}
  .wrap{max-width:1200px;margin:0 auto;padding:28px 18px 60px}
  h1{font-size:24px;margin:0 0 2px;font-weight:800;letter-spacing:-.3px}
  h1 .dot{color:var(--accent2)}
  .sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
  .runbox{text-align:right}
  .run{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#06122e;border:none;
    cursor:pointer;font-weight:800;font-size:13px;padding:11px 18px;border-radius:11px;box-shadow:0 4px 14px rgba(91,140,255,.3)}
  .run:hover{filter:brightness(1.08)}
  .run:disabled{cursor:progress;opacity:.8;animation:pulse 1.2s ease-in-out infinite}
  @keyframes pulse{50%{opacity:.55}}
  .runstatus{color:var(--muted);font-size:11px;margin-top:7px;max-width:340px;margin-left:auto;
    font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-word}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
  .stat .n{font-size:26px;font-weight:800}
  .stat .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  .stat.accent .n{color:var(--accent2)}
  .controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center;background:var(--panel);
    border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:16px;position:sticky;top:10px;z-index:5;
    backdrop-filter:blur(6px)}
  .controls input[type=search],.controls select{background:var(--panel2);border:1px solid var(--line);
    color:var(--txt);border-radius:10px;padding:9px 12px;font-size:13px;outline:none}
  .controls input[type=search]{flex:1;min-width:200px}
  .controls label{color:var(--muted);font-size:12px;display:flex;align-items:center;gap:6px}
  .controls .scoreval{color:var(--accent2);font-weight:700;min-width:26px;text-align:right}
  table{width:100%;border-collapse:separate;border-spacing:0 8px}
  th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;text-align:left;
    padding:0 14px 6px;cursor:pointer;user-select:none}
  th:hover{color:var(--txt)}
  td{background:var(--panel);border-top:1px solid var(--line);border-bottom:1px solid var(--line);
    padding:12px 14px;vertical-align:middle}
  tr td:first-child{border-left:1px solid var(--line);border-radius:12px 0 0 12px}
  tr td:last-child{border-right:1px solid var(--line);border-radius:0 12px 12px 0}
  tr.row:hover td{background:var(--panel2)}
  .title{font-weight:600}
  .company{color:var(--muted);font-size:12px}
  .badge{display:inline-block;font-size:11px;font-weight:700;padding:3px 9px;border-radius:99px;white-space:nowrap}
  .src{background:#23314f;color:#b9c8ea;text-transform:capitalize}
  .score{min-width:38px;text-align:center}
  .s-good{background:rgba(34,197,94,.16);color:#4ade80}
  .s-mid{background:rgba(245,158,11,.16);color:#fbbf24}
  .s-low{background:rgba(100,116,139,.18);color:#9fb0c9}
  .s-none{background:#1b2742;color:#5d6b87}
  .pill{font-size:10px;padding:2px 7px;border-radius:99px;background:rgba(244,114,182,.16);color:var(--pink);font-weight:700}
  .fresh{font-size:10px;padding:2px 7px;border-radius:99px;background:rgba(34,211,238,.14);color:var(--accent2);font-weight:700}
  .open{background:var(--accent);color:#fff;padding:7px 13px;border-radius:9px;font-weight:600;font-size:12px;white-space:nowrap}
  .open:hover{filter:brightness(1.1)}
  .when{color:var(--muted);font-size:12px;white-space:nowrap}
  .empty{text-align:center;color:var(--muted);padding:60px 0}
  .foot{color:var(--muted);font-size:12px;margin-top:18px;text-align:center}
  .count{color:var(--muted);font-size:12px;margin:0 4px}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <div>
      <h1>Job Watcher <span class="dot">●</span> Dashboard</h1>
      <div class="sub">__COUNT__ scraped roles · generated __GENERATED__ · 100% local</div>
    </div>
    <div class="runbox">
      <button id="runbtn" class="run">↻ Refresh — run full flow</button>
      <div id="runstatus" class="runstatus"></div>
    </div>
  </div>

  <div class="stats" id="stats"></div>

  <div class="controls">
    <input type="search" id="q" placeholder="Search company or title…">
    <select id="source"><option value="">All sources</option></select>
    <select id="company"><option value="">All companies</option></select>
    <label>Min score <input type="range" id="minscore" min="0" max="100" value="0" step="5">
      <span class="scoreval" id="minscoreval">0</span></label>
    <label><input type="checkbox" id="scoredonly"> Scored only</label>
    <label><input type="checkbox" id="freshonly"> Fresh &lt;24h</label>
    <select id="sort">
      <option value="score">Sort: Score ↓</option>
      <option value="recent">Sort: Newest</option>
      <option value="company">Sort: Company</option>
    </select>
  </div>

  <table>
    <thead><tr>
      <th data-sort="score">Score</th>
      <th data-sort="title">Role</th>
      <th data-sort="source">Source</th>
      <th data-sort="recent">Seen</th>
      <th></th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="empty" id="empty" style="display:none">No roles match your filters.</div>
  <div class="foot">Built from <code>data/seen_jobs.db</code> · click a role to open the posting</div>
</div>

<script>
const JOBS = /*__JOBS__*/;
const $ = s => document.querySelector(s);

function scoreClass(s){ if(s==null) return 's-none'; if(s>=80) return 's-good'; if(s>=60) return 's-mid'; return 's-low'; }
function esc(t){ const d=document.createElement('div'); d.textContent=t==null?'':t; return d.innerHTML; }
function whenLabel(h){ if(h==null) return '—'; if(h<1) return 'just now'; if(h<24) return Math.round(h)+'h ago'; return Math.round(h/24)+'d ago'; }

// populate filter dropdowns
const sources=[...new Set(JOBS.map(j=>j.source))].sort();
const companies=[...new Set(JOBS.map(j=>j.company))].sort();
for(const s of sources){ const o=document.createElement('option'); o.value=s; o.textContent=s; $('#source').appendChild(o); }
for(const c of companies){ const o=document.createElement('option'); o.value=c; o.textContent=c; $('#company').appendChild(o); }

function stats(list){
  const scored=list.filter(j=>j.score!=null);
  const fresh=list.filter(j=>j.hours!=null&&j.hours<24);
  const emailed=list.filter(j=>j.emailed);
  const top=scored.filter(j=>j.score>=80);
  const cards=[
    ['Total roles', list.length, ''],
    ['Scored', scored.length, ''],
    ['Strong fit (80+)', top.length, 'accent'],
    ['Fresh <24h', fresh.length, ''],
    ['Companies', new Set(list.map(j=>j.company)).size, ''],
    ['Emailed', emailed.length, ''],
  ];
  $('#stats').innerHTML = cards.map(([l,n,c])=>`<div class="stat ${c}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('');
}

function render(){
  const q=$('#q').value.toLowerCase().trim();
  const src=$('#source').value, co=$('#company').value;
  const mins=+$('#minscore').value, scoredOnly=$('#scoredonly').checked, freshOnly=$('#freshonly').checked;
  const sort=$('#sort').value;
  $('#minscoreval').textContent=mins;

  let list=JOBS.filter(j=>{
    if(q && !(j.company.toLowerCase().includes(q)||j.title.toLowerCase().includes(q))) return false;
    if(src && j.source!==src) return false;
    if(co && j.company!==co) return false;
    if(scoredOnly && j.score==null) return false;
    if(mins>0 && (j.score==null || j.score<mins)) return false;
    if(freshOnly && !(j.hours!=null&&j.hours<24)) return false;
    return true;
  });

  list.sort((a,b)=>{
    if(sort==='company') return a.company.localeCompare(b.company);
    if(sort==='recent') return (a.hours??1e9)-(b.hours??1e9);
    return (b.score??-1)-(a.score??-1); // score desc, unscored last
  });

  stats(list);
  const rows=list.map(j=>`<tr class="row">
    <td><span class="badge score ${scoreClass(j.score)}">${j.score==null?'—':j.score}</span></td>
    <td><div class="title">${esc(j.title)}</div><div class="company">${esc(j.company)}${j.emailed?' <span class="pill">emailed</span>':''}${(j.hours!=null&&j.hours<24)?' <span class="fresh">fresh</span>':''}</div></td>
    <td><span class="badge src">${esc(j.source)}</span></td>
    <td><span class="when">${whenLabel(j.hours)}</span></td>
    <td>${j.url?`<a class="open" href="${esc(j.url)}" target="_blank" rel="noopener">Open ↗</a>`:''}</td>
  </tr>`).join('');
  $('#rows').innerHTML=rows;
  $('#empty').style.display=list.length?'none':'block';
}

for(const id of ['#q','#source','#company','#minscore','#scoredonly','#freshonly','#sort'])
  $(id).addEventListener('input', render);
document.querySelectorAll('th[data-sort]').forEach(th=>th.addEventListener('click',()=>{
  const m={score:'score',recent:'recent',title:'company',source:'score'};
  $('#sort').value=m[th.dataset.sort]||'score'; render();
}));
render();

// ── Refresh button → triggers the full pipeline via the local server ──
const runBtn=$('#runbtn'), runStatus=$('#runstatus');
const IDLE='↻ Refresh — run full flow';
function setRunning(on,line){
  runBtn.disabled=on;
  runBtn.textContent=on?'● Running…':IDLE;
  if(line!=null) runStatus.textContent=line;
}
async function poll(){
  try{
    const s=await (await fetch('/status',{cache:'no-store'})).json();
    if(s.running){ setRunning(true, s.last_line||'working…'); setTimeout(poll,2000); }
    else if(runBtn.dataset.was==='1'){ runStatus.textContent='done — reloading…'; location.reload(); }
    else setRunning(false,'');
  }catch(e){ setRunning(false,'Server not running. Start it: python scripts/serve_dashboard.py'); }
}
runBtn.addEventListener('click', async ()=>{
  if(location.protocol==='file:'){
    runStatus.textContent='Open via the server to refresh: python scripts/serve_dashboard.py';
    return;
  }
  runBtn.dataset.was='1'; setRunning(true,'starting…');
  try{ await fetch('/run',{method:'POST'}); poll(); }
  catch(e){ setRunning(false,'could not reach server'); }
});
// resume polling if a run is already in progress when the page loads
if(location.protocol!=='file:')
  fetch('/status',{cache:'no-store'}).then(r=>r.json()).then(s=>{ if(s.running){ runBtn.dataset.was='1'; poll(); } }).catch(()=>{});
</script>
</body>
</html>
"""
