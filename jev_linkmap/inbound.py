"""Inbound coverage: the same pass, asked from the other side.

`run map` asks every page which of its 15 nearest neighbours it should link TO. Coverage of a page as a
TARGET was never an objective, so a page that is nobody's top-15 neighbour, or that lost a yes/no call, is
never revisited and can end up with no inbound link at all. Measured on www.bles-software.com 25 Sep 2026,
three months after the first run: 246 of the 571 URLs in sitemap.xml had zero inbound internal links from
any served page and were reachable only from sitemap.xml. Google's index admission had the same shape,
1 of 261 for the largest cohort.

This mode starts from the pages that need the link. For each one it takes the pages most similar to it as
candidate SOURCES, and for each pair asks the same two questions with the same trained rubric: should this
source link here, and which 2 to 6 word phrase already in the source's copy is the honest anchor. Nothing
else changes: same crawl, same TF-IDF search, same thresholds, same cap of 3 new links per run on one
source page, same rule that a pair which does not clear the bar stays unlinked. The cap counts this run's
links, not the ones a page already serves, so merging into a live map can leave a page with more than 3.

  python3 -m jev_linkmap.inbound --scope scope.json --pages data/inbound/pages.jsonl --out out/inbound

The scope file says which pages need inbound links and which pages may carry one:

  {"targets": ["https://site.com/orphan/", ...], "sources": ["https://site.com/can-link/", ...]}

`sources` is optional; without it every crawled page may be a source. The editor pass runs on the result
the same way it runs on a full map: `python3 -m jev_linkmap.verify --out out/inbound`.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .candidates import Index
from .crawl import norm
from .judge import judge_jev, place_links
from .run import load_pages, write_map

# 15 targets is the request shape the trained rubric was scored on: one copy of the page, 30 questions.
# A page that is the nearest neighbour of 30 orphans is asked in chunks of that size rather than in one
# oversized request, and the placement rule then runs once over the merged answers, so the cap of 3 new
# links per source page holds across the chunks.
CHUNK = 15

# A host whose IPv6 route to the API is blackholed hangs for the full timeout instead of failing, and
# getaddrinfo puts the AAAA record first (measured on this box 24 Sep 2026: every request to the
# decisions endpoint timed out at 60 s while the same call over IPv4 answered in 0.4 s). Prefer the A
# record when both exist; nothing else about the connection changes.
if not getattr(socket.getaddrinfo, "_ipv4_first", False):
    _gai = socket.getaddrinfo
    socket.getaddrinfo = lambda *a, **k: sorted(_gai(*a, **k), key=lambda r: r[0] != socket.AF_INET)
    socket.getaddrinfo._ipv4_first = True


def build_jobs(idx: Index, pages: list[dict], targets: list[int], allowed: set[int] | None, per_target: int, anchors: int) -> tuple[list[dict], dict]:
    """Orphan-driven pairs, grouped back into the per-source job shape the judge already reads."""
    by_source: dict[int, list[tuple[float, int, list[dict]]]] = {}
    no_candidate, no_anchor = [], 0
    for j in targets:
        usable = 0
        for i, sim in idx.sources(j, per_target, allowed):
            found = idx.anchors(i, j, anchors)
            if not found:  # the source never wrote a phrase that could carry this link
                no_anchor += 1
                continue
            by_source.setdefault(i, []).append((sim, j, found))
            usable += 1
        if not usable:
            no_candidate.append(pages[j]["url"])
    jobs = []
    for i, cands in by_source.items():
        cands.sort(key=lambda c: -c[0])
        jobs.append(
            {
                "source": pages[i]["key"],
                "url": pages[i]["url"],
                "targets": [
                    {
                        "id": f"t{n}",
                        "key": pages[j]["key"],
                        "url": pages[j]["url"],
                        "title": re.split(r"\s[|\u2013\u2014]\s", pages[j]["title"])[0] or pages[j]["h1"],
                        "about": (pages[j]["description"] or (pages[j]["blocks"][0] if pages[j]["blocks"] else ""))[:240],
                        "similarity": round(sim, 4),
                        "anchors": found,
                    }
                    for n, (sim, j, found) in enumerate(cands, 1)
                ],
            }
        )
    stats = {
        "pairs": sum(len(j["targets"]) for j in jobs),
        "pairs_without_an_anchor_in_the_source_copy": no_anchor,
        "targets_without_a_candidate_source": no_candidate,
    }
    return jobs, stats


def judge_source(job: dict, page: dict, rubric: dict) -> dict:
    """One source page, its candidates asked in chunks of CHUNK, the placement rule run once on the merge."""
    verdicts, meters = {}, []
    for start in range(0, len(job["targets"]), CHUNK):
        chunk = dict(job, targets=job["targets"][start : start + CHUNK])
        res = judge_jev(chunk, page, rubric)
        verdicts.update(res["verdicts"])
        meters.append(res["meter"])
    return {
        "source": job["source"],
        "verdicts": verdicts,
        "links": place_links(job, verdicts, rubric),
        "requests": len(meters),
        "meter": {
            "seconds": round(sum(m["seconds"] for m in meters), 3),
            "cost": sum(m["cost"] for m in meters),
            "input_tokens": sum(m.get("input_tokens", 0) for m in meters),
            "model": meters[-1].get("model") if meters else None,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", required=True, help="{'targets': [url...], 'sources': [url...]}")
    ap.add_argument("--pages", default="data/pages.jsonl")
    ap.add_argument("--rubric", default="rubrics/v3.json")
    ap.add_argument("--out", default="out/inbound")
    ap.add_argument("--sources-per-target", type=int, default=15, help="candidate source pages per page that needs a link, the mirror of run map's --k")
    ap.add_argument("--anchors", type=int, default=5, help="anchor options offered per pair")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--dry", action="store_true", help="build the queue and print the counts, ask nothing")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = load_pages(args.pages)
    by_key = {p["key"]: p for p in pages}
    index_of = {p["key"]: i for i, p in enumerate(pages)}
    rubric = json.loads(Path(args.rubric).read_text("utf-8"))
    scope = json.loads(Path(args.scope).read_text("utf-8"))

    targets = [index_of[norm(u)] for u in scope["targets"] if norm(u) in index_of]
    uncrawled = [u for u in scope["targets"] if norm(u) not in index_of]
    allowed = {index_of[norm(u)] for u in scope.get("sources", []) if norm(u) in index_of} if scope.get("sources") else None
    if not targets:
        raise SystemExit(f"none of the {len(scope['targets'])} scope targets is in {args.pages}")

    started = time.perf_counter()
    idx = Index(pages)
    jobs, stats = build_jobs(idx, pages, targets, allowed, args.sources_per_target, args.anchors)
    print(
        f"queue: {stats['pairs']} candidate pairs for {len(targets)} pages that need a link, "
        f"{len(jobs)} source pages, built in {time.perf_counter() - started:.1f}s",
        file=sys.stderr,
    )
    if args.dry:
        print(json.dumps({**stats, "sources": len(jobs), "requests": sum((len(j['targets']) + CHUNK - 1) // CHUNK for j in jobs)}, indent=1))
        return

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda job: judge_source(job, by_key[job["source"]], rubric), jobs))
    seconds = time.perf_counter() - started

    links = [l for r in results for l in r["links"]]
    declined = stats["pairs"] - len(links)
    covered = {l["target"] for l in links}
    refused = [j["url"] for j, r in zip(jobs, results) if not r["links"]]
    write_map(out, links, refused)
    summary = {
        "mode": "inbound",
        "rubric": rubric["version"],
        "model": next((r["meter"]["model"] for r in results if r["meter"]["model"]), None),
        "pages_needing_a_link": len(targets),
        "pages_that_got_one": len(covered),
        "still_without_one": sorted(pages[j]["url"] for j in targets if pages[j]["url"] not in covered),
        "links_placed": len(links),
        "source_pages_used": len({l["source"] for l in links}),
        "candidate_pairs": stats["pairs"],
        "pairs_declined": declined,
        "pairs_without_an_anchor_in_the_source_copy": stats["pairs_without_an_anchor_in_the_source_copy"],
        "targets_without_a_candidate_source": stats["targets_without_a_candidate_source"],
        "targets_not_in_the_crawl": uncrawled,
        "requests": sum(r["requests"] for r in results),
        "cost": round(sum(r["meter"]["cost"] for r in results), 6),
        "input_tokens": sum(r["meter"]["input_tokens"] for r in results),
        "wall_seconds": round(seconds, 2),
    }
    (out / "inbound-results.json").write_text(json.dumps(results, ensure_ascii=False), "utf-8")
    (out / "inbound.json").write_text(json.dumps(summary, indent=1), "utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
