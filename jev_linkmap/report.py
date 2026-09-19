"""One self-contained HTML page: the race, the loop, and the link map itself. Every number comes from the run files."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

JEV, FRONTIER = "#2a78d6", "#eb6834"

CSS = """
:root{--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--ink3:#8a8984;--rule:#e6e5e0;--jev:#2a78d6;--fr:#eb6834;--card:#ffffff}
*{box-sizing:border-box}html{background:var(--surface)}
body{margin:0;color:var(--ink);font:400 17px/1.6 Manrope,sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:1120px;margin:0 auto;padding:72px 28px 120px}
h1{font:400 clamp(3rem,7vw,5.6rem)/1.02 "Instrument Serif",serif;letter-spacing:-.01em;margin:0 0 20px}
h2{font:400 clamp(2.2rem,4vw,3.1rem)/1.1 "Instrument Serif",serif;margin:96px 0 12px}
.lede{font-size:1.2rem;color:var(--ink2);max-width:62ch;margin:0}
.kicker{font:600 .78rem/1 Manrope;letter-spacing:.14em;text-transform:uppercase;color:var(--ink3);margin:0 0 22px}
.note{color:var(--ink2);max-width:70ch}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:48px 0 0}
.tile{background:var(--card);border:1px solid var(--rule);border-radius:14px;padding:22px 22px 20px}
.tile b{display:block;font:400 clamp(2.4rem,4.4vw,3.4rem)/1 "Instrument Serif",serif}
.tile span{display:block;margin-top:10px;color:var(--ink2);font-size:.92rem;line-height:1.4}
.lanes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:28px}
.lane{min-width:0;background:var(--card);border:1px solid var(--rule);border-radius:14px;padding:24px}
.lane h3{font:600 1rem/1 Manrope;margin:0 0 18px;display:flex;align-items:center;gap:10px}
.tag{margin-left:auto;font:600 .72rem/1 Manrope;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3)}
.lane p{color:var(--ink2);font-size:.95rem;margin:18px 0 0}
pre{margin:16px 0 0;background:#f3f2ee;border-radius:10px;padding:14px 16px;overflow-x:auto}
code{font:500 .8rem/1.6 'JetBrains Mono',ui-monospace,monospace;color:var(--ink);white-space:pre-wrap;overflow-wrap:anywhere}
.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
.lane dl{display:grid;grid-template-columns:1fr auto;gap:9px 16px;margin:0;font-size:.98rem}
.lane dt{color:var(--ink2)}.lane dd{margin:0;font-weight:600;font-variant-numeric:tabular-nums;text-align:right}
figure{margin:28px 0 0;background:var(--card);border:1px solid var(--rule);border-radius:14px;padding:24px 24px 14px;position:relative}
figcaption{font:600 1rem/1.3 Manrope;margin-bottom:4px}
figure p{margin:0 0 12px;color:var(--ink2);font-size:.92rem}
.legend{display:flex;gap:20px;font-size:.9rem;color:var(--ink2);margin-bottom:6px}
.legend i{display:inline-flex;align-items:center;gap:7px;font-style:normal}
svg text{font:500 12px Manrope;fill:var(--ink2)}
#tip{position:absolute;pointer-events:none;background:#0b0b0b;color:#fff;font:500 12.5px/1.45 Manrope;padding:8px 11px;border-radius:8px;opacity:0;transition:opacity .1s;white-space:nowrap;z-index:3}
table{width:100%;border-collapse:collapse;font-size:.95rem;font-variant-numeric:tabular-nums}
th{text-align:left;font:600 .76rem/1 Manrope;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);padding:12px 12px 12px 0;border-bottom:1px solid var(--ink)}
td{padding:13px 12px 13px 0;border-bottom:1px solid var(--rule);vertical-align:top}
td.n,th.n{text-align:right}
.tablewrap{overflow-x:auto;margin-top:24px}
.review{border-left:2px solid var(--ink);padding:2px 0 2px 20px;margin:26px 0;max-width:74ch}
.review b{font:600 .8rem/1 Manrope;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);display:block;margin-bottom:8px}
.review ul{margin:10px 0 0;padding-left:18px;color:var(--ink2);font-size:.95rem}
input[type=search]{width:100%;font:500 1rem Manrope;padding:14px 16px;border:1px solid var(--rule);border-radius:12px;background:var(--card);margin-top:24px;color:var(--ink)}
input[type=search]:focus{outline:2px solid var(--jev);outline-offset:1px}
.src{color:var(--ink3);font-size:.84rem;word-break:break-all}
mark{background:#dbe9fb;color:inherit;padding:1px 3px;border-radius:4px}
a{color:inherit;text-decoration-color:var(--ink3);text-underline-offset:3px}
.more{margin-top:16px;color:var(--ink2);font-size:.92rem}
details{margin-top:24px}summary{cursor:pointer;font-weight:600}
details li{font-size:.9rem;color:var(--ink2);word-break:break-all}
footer{margin-top:96px;color:var(--ink3);font-size:.88rem}
@media(max-width:760px){main{padding:44px 18px 80px}.tiles{grid-template-columns:1fr 1fr}.lanes{grid-template-columns:1fr}td,th{padding-right:10px}}
"""

JS = """
const D=JSON.parse(document.getElementById('data').textContent);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function rows(q){q=q.toLowerCase();const hit=D.links.filter(l=>!q||(l.source+' '+l.target+' '+l.anchor+' '+l.target_title).toLowerCase().includes(q));
const body=document.getElementById('links');body.innerHTML=hit.slice(0,40).map(l=>{const i=l.sentence.toLowerCase().indexOf(l.anchor.toLowerCase());
const s=i<0?esc(l.sentence):esc(l.sentence.slice(0,i))+'<mark>'+esc(l.sentence.slice(i,i+l.anchor.length))+'</mark>'+esc(l.sentence.slice(i+l.anchor.length));
return `<tr><td>${s}<div class="src">on ${esc(l.source)}</div></td><td><a href="${esc(l.target)}">${esc(l.target_title)}</a></td><td class="n">${l.confidence.toFixed(2)}</td></tr>`}).join('');
document.getElementById('count').textContent=hit.length>40?`Showing 40 of ${hit.length} links. Search narrows it, linkmap-verified.csv has all of them.`:`${hit.length} links.`}
document.getElementById('q').addEventListener('input',e=>rows(e.target.value));rows('');
const tip=document.getElementById('tip'),svg=document.getElementById('chart');
if(svg){const fig=svg.closest('figure'),g=JSON.parse(svg.dataset.g),cross=document.getElementById('cross');
svg.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*g.W;const t=Math.max(0,Math.min(g.T,(x-g.L)/(g.W-g.L-g.R)*g.T));
const at=a=>a.filter(v=>v<=t).length;cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.style.opacity=x>=g.L&&x<=g.W-g.R?1:0;
tip.innerHTML=`${t.toFixed(1)} s<br>Jev: ${at(D.jev_at)} pages<br>${esc(D.frontier_name)}: ${at(D.frontier_at)} pages`;tip.style.opacity=1;
const fr=fig.getBoundingClientRect();let lx=e.clientX-fr.left+14;if(lx>fr.width-170)lx-=190;tip.style.left=lx+'px';tip.style.top=(e.clientY-fr.top-10)+'px'});
svg.addEventListener('mouseleave',()=>{tip.style.opacity=0;cross.style.opacity=0})}
"""


def money(x: float) -> str:
    return f"${x:,.2f}" if x >= 1 else (f"${x:.3f}" if x >= 0.01 else f"${x:.4f}")


def step_path(times: list[float], total_t: float, ymax: int, g: dict) -> str:
    sx = lambda t: g["L"] + t / total_t * (g["W"] - g["L"] - g["R"])
    sy = lambda n: g["H"] - g["B"] - n / ymax * (g["H"] - g["T0"] - g["B"])
    d = [f"M{sx(0):.1f},{sy(0):.1f}"]
    for n, t in enumerate(sorted(times), 1):
        d.append(f"H{sx(t):.1f}V{sy(n):.1f}")
    d.append(f"H{sx(total_t):.1f}")
    return "".join(d)


def chart(jev_at: list[float], fr_at: list[float], total_t: float, name: str) -> str:
    g = {"W": 1040, "H": 360, "L": 52, "R": 120, "T0": 16, "B": 36, "T": total_t}
    ymax = max(len(jev_at), 1)
    sy = lambda n: g["H"] - g["B"] - n / ymax * (g["H"] - g["T0"] - g["B"])
    sx = lambda t: g["L"] + t / total_t * (g["W"] - g["L"] - g["R"])
    nice = next(n for n in (1, 2, 5, 10, 20, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10**9) if n >= ymax / 4.5)
    ticks_y = list(range(0, ymax + 1, nice))
    step_t = max(1, round(total_t / 6))
    ticks_x = list(range(0, int(total_t) + 1, step_t))
    grid = "".join(f'<line x1="{g["L"]}" x2="{g["W"] - g["R"]}" y1="{sy(n):.1f}" y2="{sy(n):.1f}" stroke="#e6e5e0"/><text x="{g["L"] - 10}" y="{sy(n) + 4:.1f}" text-anchor="end">{n}</text>' for n in ticks_y)
    xs = "".join(f'<text x="{sx(t):.1f}" y="{g["H"] - 12}" text-anchor="middle">{t}s</text>' for t in ticks_x)
    end_x = g["W"] - g["R"] + 10
    fr_y = min(sy(len(fr_at)), sy(0) - 4)
    return (
        f'<svg id="chart" viewBox="0 0 {g["W"]} {g["H"]}" width="100%" role="img" aria-label="Pages finished over time, Jev against {html.escape(name)}" data-g=\'{json.dumps(g)}\'>'
        f"{grid}{xs}"
        f'<path d="{step_path(fr_at, total_t, ymax, g)}" fill="none" stroke="{FRONTIER}" stroke-width="2" stroke-linejoin="round"/>'
        f'<path d="{step_path(jev_at, total_t, ymax, g)}" fill="none" stroke="{JEV}" stroke-width="2" stroke-linejoin="round"/>'
        f'<text x="{end_x}" y="{sy(len(jev_at)) + 12:.1f}" style="font-weight:700;fill:#0b0b0b">Jev {len(jev_at)}</text>'
        f'<text x="{end_x}" y="{fr_y:.1f}" style="font-weight:700;fill:#0b0b0b">{html.escape(name)} {len(fr_at)}</text>'
        f'<line id="cross" y1="{g["T0"]}" y2="{g["H"] - g["B"]}" stroke="#0b0b0b" stroke-dasharray="3 3" style="opacity:0"/></svg>'
    )


def loop_rows(runs: Path) -> tuple[list[dict], list[dict]]:
    holdout, reviews = [], []
    for d in sorted(runs.glob("holdout-v*"), key=lambda p: int(p.name.split("v")[-1])):
        b = json.loads((d / "block.json").read_text("utf-8"))
        holdout.append({"rubric": b["rubric"], **b["agreement"], "jev_cost": b["jev"]["cost"], "frontier_cost": b["frontier"]["cost"]})
    for d in sorted(runs.glob("block*")):
        if (d / "system2.json").exists():
            reviews.append(json.loads((d / "system2.json").read_text("utf-8")))
    return holdout, reviews


def pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def build(out: Path, runs: Path, site: str) -> str:
    rep = json.loads((out / "report.json").read_text("utf-8"))
    lm = json.loads((out / "linkmap.json").read_text("utf-8"))
    jev_res = json.loads((out / "jev-results.json").read_text("utf-8"))
    fr_file = out / "frontier-results.json"
    fr_res = json.loads(fr_file.read_text("utf-8")) if fr_file.exists() else []
    j, f, pp, ag = rep["jev"], rep.get("frontier"), rep.get("per_page"), rep.get("agreement")
    name = "Claude Opus 5" if fr_res and "opus-5" in (fr_res[0]["meter"].get("model") or "") else (fr_res[0]["meter"].get("model") if fr_res else "frontier")
    holdout, reviews = loop_rows(runs)

    tiles = [
        (f'{j["wall_seconds"]:.1f}s', f'for Jev to judge all {j["pages"]} pages, {j["decisions"]:,} link decisions'),
        (f'{j["links_placed"]}', f'links placed, each on a phrase the page already contains'),
        (f'{j["pages_refused"]}', "pages left exactly as they are: Jev places a link only when it is sure"),
        (money(j["cost"]), "total Jev cost for the whole site"),
    ]
    h = [f'<p class="kicker">jev-linkmap &middot; {html.escape(site)}</p><h1>The internal link map, rebuilt in {j["wall_seconds"]:.0f} seconds</h1>']
    price = None
    hb = runs / f"holdout-v{rep['rubric']}" / "block.json"
    if hb.exists():  # a random block judged by the frontier model with this same rubric is the fair price sample
        b = json.loads(hb.read_text("utf-8"))["frontier"]
        price = {"pages": b["pages"], "per_page": b["cost"] / b["pages"], "seconds": b["model_seconds"] / b["pages"]}
    elif f and f["pages"]:
        price = {"pages": f["pages"], "per_page": f["cost"] / f["pages"], "seconds": f["model_seconds"] / f["pages"]}
    if f:
        by_clock = f.get("pages_by_the_clock", f["pages"])
        lede = f'Jev read {j["pages"]} pages and answered {j["decisions"]:,} link questions for {money(j["cost"])}. {name}, same queue, same rubric, same clock, had finished {by_clock} {"page" if by_clock == 1 else "pages"} when Jev was done.'
        if price:
            jp = j["cost"] / j["pages"]
            lede += f' Priced on {price["pages"]} random pages, {name} costs {money(price["per_page"])} a page against {money(jp)}: {price["per_page"] / jp:.0f} times more, about {money(price["per_page"] * j["pages"])} for the full pass.'
        h.append(f'<p class="lede">{lede}</p>')
    h.append('<div class="tiles">' + "".join(f"<div class='tile'><b>{a}</b><span>{b}</span></div>" for a, b in tiles) + "</div>")

    if f:
        h.append('<h2>The race</h2><p class="note">Both judges pull from one queue, read the same page copy, the same 15 candidate targets and the same anchor phrases, and answer by the same rubric. The clock stops the moment Jev finishes, and only pages the frontier model completed by then count. Calls already in flight are allowed to land so the chart shows when they did; no new page starts after the clock.</p>')
        h.append(f'<figure><figcaption>Pages finished over time</figcaption><p>Jev ran {j["workers"]} requests at a time, {name} ran {f["workers"]} at a time.</p><div class="legend"><i><span class="dot" style="background:{JEV}"></span>Jev</i><i><span class="dot" style="background:{FRONTIER}"></span>{name}</i></div>{chart([r["at"] for r in jev_res], [r["at"] for r in fr_res], max([j["wall_seconds"]] + [r["at"] for r in fr_res]) * 1.04, name)}<div id="tip"></div></figure>')
        lane = lambda title, color, d, extra: f'<div class="lane"><h3><span class="dot" style="background:{color}"></span>{title}</h3><dl>' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in [("Pages finished by the clock", d.get("pages_by_the_clock", d["pages"])), ("Pages finished in all", d["pages"]), ("Link decisions", f'{d["decisions"]:,}'), ("Cost", money(d["cost"])), ("Cost per page", money(d["cost"] / max(d["pages"], 1))), ("Model time per page", f'{d["model_seconds"] / max(d["pages"], 1):.2f}s'), *extra]) + "</dl></div>"
        h.append('<div class="lanes">' + lane("Jev", JEV, j, [("Links placed", j["links_placed"])]) + lane(name, FRONTIER, f, [("Links placed", f["links_placed"])]) + "</div>")
        if price and f["pages"] and hb.exists():
            h.append(f'<p class="note" style="margin-top:22px">The {f["pages"]} pages {name} landed are the short pages at the top of the queue, so its per-page cost here runs low. The price used above comes from {price["pages"]} random pages judged with this same rubric: {money(price["per_page"])} and {price["seconds"]:.1f}s of model time a page.</p>')
        if ag and ag["decisions"] and not holdout:
            h.append(f'<p class="note" style="margin-top:22px">On the {ag["pages"]} pages both finished, the two judges made the same place-or-skip call on {pct(ag["agree"])} of {ag["decisions"]} decisions. {name} would also have placed {pct(ag["jev_yes_confirmed"])} of the links Jev placed there.</p>')

    verified_file = out / "linkmap-verified.json"
    verified = json.loads(verified_file.read_text("utf-8")) if verified_file.exists() else None

    code = lambda c: f"<pre><code>{html.escape(c)}</code></pre>"
    h.append('<h2>Two ways to run it</h2><p class="note">Jev is System 1: fast, cheap and literal, so the question it is asked is the product. You can run it alone with a rubric that is already trained, or put a deep model behind it as System 2 to train the rubric on your own site first.</p>')
    one = [("Models you need", "Jev"), ("This site", f'{j["wall_seconds"]:.1f}s, {money(j["cost"])}'), ("Links placed", j["links_placed"]), ("Rubric", f'v{rep["rubric"]}, already trained')]
    card = lambda title, tag, rows, body: f'<div class="lane"><h3>{title}<span class="tag">{tag}</span></h3><dl>' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + f"</dl>{body}</div>"
    cards = card("System 1", "Jev alone", one, '<p>One key, no other account. Use it when your site looks like the one the rubric was trained on, or when seconds and cents matter more than the last few links.</p>' + code("python3 -m jev_linkmap.site https://your-site.com/sitemap.xml --mode system1"))
    if holdout:
        first, last = holdout[0], holdout[-1]
        loop_cost = sum(json.loads(p.read_text("utf-8"))["frontier"]["cost"] for p in runs.glob("*/block.json")) + sum((r.get("cost") or 0) for r in reviews)
        two = [("Models you need", "Jev + Claude or Codex"), ("Referee links Jev finds", f'{pct(first["frontier_yes_found"])} to {pct(last["frontier_yes_found"])}'), ("Same anchor as referee", f'{pct(first["same_anchor_when_both_yes"])} to {pct(last["same_anchor_when_both_yes"])}'), ("One-time training cost", money(loop_cost))]
        cards += card("System 1 + System 2", "Jev + a deep model", two, '<p>A deep model referees small blocks of pages, reads where it and Jev disagreed, and rewrites Jev\'s rubric. Then Jev maps the whole site alone with the rubric that scored best. You pay for the deep model once, on a few dozen pages, never on the whole site.</p>' + code("python3 -m jev_linkmap.site https://your-site.com/sitemap.xml --mode system1+system2\n\n# System 2 on your ChatGPT plan, through the Codex CLI\nLINKMAP_DEEP=codex python3 -m jev_linkmap.site https://your-site.com/sitemap.xml --mode system1+system2"))
    h.append(f'<div class="lanes">{cards}</div>')

    if holdout:
        h.append('<h2>What System 2 adds</h2><p class="note">After each block of pages System 2 rewrites the rubric: the question wording, up to six one-line lessons, the two thresholds. Every rubric version is then scored on one held-out block that no version was written from. Jev never sees the deep model, only the new rubric.</p>')
        h.append('<div class="tablewrap"><table><thead><tr><th>Rubric</th><th class="n">Decisions</th><th class="n">Same call as referee</th><th class="n">Jev links the referee confirms</th><th class="n">Referee links Jev found</th><th class="n">Same anchor</th><th class="n">Jev placed</th><th class="n">Referee placed</th></tr></thead><tbody>')
        for r in holdout:
            h.append(f'<tr><td style="white-space:nowrap">v{r["rubric"]}{" (System 1, written by hand)" if r["rubric"] == 1 else " (System 1 + System 2)"}</td><td class="n">{r["decisions"]}</td><td class="n">{pct(r["agree"])}</td><td class="n">{pct(r["jev_yes_confirmed"])}</td><td class="n">{pct(r["frontier_yes_found"])}</td><td class="n">{pct(r["same_anchor_when_both_yes"])}</td><td class="n">{r["jev_yes"]}</td><td class="n">{r["frontier_yes"]}</td></tr>')
        h.append("</tbody></table></div>")

    shown = verified["links"] if verified else lm["links"]
    if verified:
        v = verified["summary"]
        h.append(f'<h2>The link map</h2><p class="note">Jev placed {v["proposed"]} links. Before anything went on the live site an editor pass ({html.escape(v["editor"])}, {money(v["cost"])}) read only those links, twenty to a call, and kept the {v["kept"]} below on {v["pages"]} pages. It can cut a link, it can never add one. The highlighted words are already in the page, so placing a link means wrapping them, not rewriting anything.</p>')
    else:
        h.append(f'<h2>The link map</h2><p class="note">{len(lm["links"])} links across {j["pages_linked"]} pages, made with rubric v{rep["rubric"]}. The highlighted words are already in the page, so placing a link means wrapping them, not rewriting anything.</p>')
    h.append('<input id="q" type="search" placeholder="Search a page, a target or an anchor" aria-label="Search the link map"><div class="tablewrap"><table><thead><tr><th>Anchor in its sentence</th><th>Links to</th><th class="n">Confidence</th></tr></thead><tbody id="links"></tbody></table></div><p class="more" id="count"></p>')
    h.append('<footer>Built with <a href="https://github.com/stas4000/jev-linkmap">jev-linkmap</a>. Jev by TypeSafe through OpenRouter. Costs are the amounts the APIs reported for this run.</footer>')

    data = {"links": sorted(shown, key=lambda l: -l["confidence"]), "jev_at": sorted(r["at"] for r in jev_res), "frontier_at": sorted(r["at"] for r in fr_res), "frontier_name": name}
    fonts = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=JetBrains+Mono:wght@500&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">'
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Internal link map: {html.escape(site)}</title>{fonts}<style>{CSS}</style></head><body><main>{"".join(h)}</main><script id="data" type="application/json">{json.dumps(data, ensure_ascii=False).replace("</", "<\\/")}</script><script>{JS}</script></body></html>'


def main() -> None:
    ap = argparse.ArgumentParser(description="Render out/report.html from the run files")
    ap.add_argument("--out", default="out")
    ap.add_argument("--runs", default="runs")
    ap.add_argument("--site", default="")
    ap.add_argument("--loop-only", action="store_true", help="print the held-out table and exit")
    args = ap.parse_args()
    if args.loop_only:
        for r in loop_rows(Path(args.runs))[0]:
            print(f'v{r["rubric"]}: same call {pct(r["agree"])}, jev links confirmed {pct(r["jev_yes_confirmed"])}, referee links found {pct(r["frontier_yes_found"])}, same anchor {pct(r["same_anchor_when_both_yes"])}')
        return
    out = Path(args.out)
    site = args.site or json.loads((out / "linkmap.json").read_text("utf-8"))["links"][0]["source"].split("/")[2]
    (out / "report.html").write_text(build(out, Path(args.runs), site), "utf-8")
    print(out / "report.html")


if __name__ == "__main__":
    main()
