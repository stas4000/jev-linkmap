"""jev-linkmap: rebuild a site's internal link map with a decision model, and race a frontier model on the same queue.

  map     Jev alone over the whole site: the deliverable.
  race    Jev and the frontier model on the same queue, same rubric, same clock. The clock stops when Jev finishes.
  block   A sample of pages judged by both with no clock, so System 2 can read where they disagree.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .candidates import build_queue
from .judge import decision, judge_frontier, judge_jev, place_links


def load_pages(path: str) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text("utf-8").splitlines() if l.strip()]


def load_queue(pages: list[dict], out: Path, k: int) -> list[dict]:
    stamp = hashlib.sha1("".join(p["key"] + str(p["words"]) for p in pages).encode()).hexdigest()[:10]
    f = out / f"queue-k{k}-{stamp}.json"  # another site, or the same site after an edit, never reuses an old queue
    if f.exists():
        return json.loads(f.read_text("utf-8"))
    started = time.perf_counter()
    queue = build_queue(pages, k=k)
    print(f"queue: {len(queue)} pages, {sum(len(j['targets']) for j in queue)} link decisions, built in {time.perf_counter() - started:.1f}s", file=sys.stderr)
    out.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(queue, ensure_ascii=False), "utf-8")
    return queue


def run_jev(queue: list[dict], by_key: dict, rubric: dict, workers: int, on_done=None) -> tuple[list[dict], float]:
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(judge_jev, job, by_key[job["source"]], rubric): job for job in queue}
        for fut in as_completed(futures):
            res = fut.result()
            res["at"] = round(time.perf_counter() - started, 3)
            results.append(res)
            if on_done:
                on_done(res)
    return results, time.perf_counter() - started


def run_frontier(queue: list[dict], by_key: dict, rubric: dict, workers: int, stop: threading.Event | None = None, kill: bool = False) -> tuple[list[dict], list[str], float]:
    """Same queue, same order. With `stop`, no new page starts after the clock stops. Calls in flight are killed,
    or allowed to finish and marked late: a late page never counts in the race, it only prices a frontier page."""
    results, errors, procs = [], [], set()
    lock = threading.Lock()
    it = iter([j for j in queue if j["targets"]])
    started = time.perf_counter()

    def worker() -> None:
        while not (stop and stop.is_set()):
            with lock:
                job = next(it, None)
            if job is None:
                return
            try:
                res = judge_frontier(job, by_key[job["source"]], rubric, procs)
            except Exception as e:
                if not (stop and stop.is_set()):
                    errors.append(f"{job['source']}: {e}")
                continue
            res["late"] = bool(stop and stop.is_set())
            res["at"] = round(time.perf_counter() - started, 3)
            results.append(res)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    if stop:
        stop.wait()
        for p in list(procs) if kill else []:
            p.kill()
    for t in threads:
        t.join()
    return results, errors, time.perf_counter() - started


def totals(results: list[dict]) -> dict:
    return {
        "pages": len(results),
        "decisions": sum(len(r["verdicts"]) for r in results),
        "cost": round(sum(r["meter"]["cost"] for r in results), 6),
        "input_tokens": sum(r["meter"].get("input_tokens", 0) for r in results),
        "model_seconds": round(sum(r["meter"].get("model_seconds", r["meter"]["seconds"]) for r in results), 2),
    }


def link_map(queue: list[dict], results: list[dict], rubric: dict) -> tuple[list[dict], list[str]]:
    jobs = {j["source"]: j for j in queue}
    links, refused = [], []
    for r in results:
        placed = place_links(jobs[r["source"]], r["verdicts"], rubric)
        links.extend(placed)
        if not placed:
            refused.append(jobs[r["source"]]["url"])
    return links, refused


def agreement(queue: list[dict], a: list[dict], b: list[dict], rubric: dict) -> dict:
    """Pair by pair, on the pages both judges finished: does the link get placed or not."""
    bb = {r["source"]: r for r in b}
    both = yes_a = yes_b = yes_both = same = same_anchor = 0
    rows = []
    jobs = {j["source"]: j for j in queue}
    for ra in a:
        rb = bb.get(ra["source"])
        if not rb:
            continue
        for tid, va in ra["verdicts"].items():
            vb = rb["verdicts"].get(tid)
            if vb is None:
                continue
            da, db = decision(va, rubric), decision(vb, rubric)
            both += 1
            yes_a += da
            yes_b += db
            yes_both += da and db
            same += da == db
            same_anchor += da and db and va["anchor"] == vb["anchor"]
            t = next(t for t in jobs[ra["source"]]["targets"] if t["id"] == tid)
            rows.append({"source": jobs[ra["source"]]["url"], "target": t["title"], "about": t["about"], "anchors": [x["phrase"] for x in t["anchors"]], "jev": va, "frontier": vb, "jev_places": da, "frontier_places": db})
    return {
        "pages": sum(1 for r in a if r["source"] in bb),
        "decisions": both,
        "agree": round(same / both, 4) if both else None,
        "jev_yes": yes_a,
        "frontier_yes": yes_b,
        "both_yes": yes_both,
        "jev_yes_confirmed": round(yes_both / yes_a, 4) if yes_a else None,
        "frontier_yes_found": round(yes_both / yes_b, 4) if yes_b else None,
        "same_anchor_when_both_yes": round(same_anchor / yes_both, 4) if yes_both else None,
        "rows": rows,
    }


def write_map(out: Path, links: list[dict], refused: list[str]) -> None:
    (out / "linkmap.json").write_text(json.dumps({"links": links, "refused": refused}, ensure_ascii=False, indent=1), "utf-8")
    with (out / "linkmap.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "anchor", "target", "target_title", "confidence", "sentence"])
        w.writeheader()
        w.writerows(links)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["map", "race", "block"])
    ap.add_argument("--pages", default="data/pages.jsonl")
    ap.add_argument("--rubric", default="rubrics/v1.json")
    ap.add_argument("--out", default="out")
    ap.add_argument("--k", type=int, default=15, help="candidate targets per page")
    ap.add_argument("--jev-workers", type=int, default=32)
    ap.add_argument("--frontier-workers", type=int, default=8)
    ap.add_argument("--sample", type=int, default=30, help="block mode: pages in the block")
    ap.add_argument("--index", type=int, default=0, help="block mode: which disjoint slice of the shuffled site")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kill-inflight", action="store_true", help="race mode: kill frontier calls still running when Jev finishes, instead of letting them finish as late pages")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages = load_pages(args.pages)
    by_key = {p["key"]: p for p in pages}
    rubric = json.loads(Path(args.rubric).read_text("utf-8"))
    queue = load_queue(pages, Path(args.pages).parent, args.k)

    if args.mode == "block":
        rng = random.Random(args.seed)
        shuffled = [j for j in queue if j["targets"]]
        rng.shuffle(shuffled)  # one shuffle, disjoint slices: block 0, block 1, ... never share a page
        block = shuffled[args.index * args.sample : (args.index + 1) * args.sample]
        jev_res, jev_s = run_jev(block, by_key, rubric, args.jev_workers)
        fr_res, errors, fr_s = run_frontier(block, by_key, rubric, args.frontier_workers)
        agr = agreement(block, jev_res, fr_res, rubric)
        report = {"mode": "block", "rubric": rubric["version"], "seed": args.seed, "index": args.index, "pages": [j["url"] for j in block], "jev": {**totals(jev_res), "wall_seconds": round(jev_s, 2)}, "frontier": {**totals(fr_res), "wall_seconds": round(fr_s, 2), "errors": errors}, "agreement": {k: v for k, v in agr.items() if k != "rows"}}
        (out / "block.json").write_text(json.dumps(report, indent=1), "utf-8")
        (out / "block-rows.json").write_text(json.dumps(agr["rows"], ensure_ascii=False, indent=1), "utf-8")
        print(json.dumps(report, indent=1))
        return

    stop = threading.Event()
    frontier_box: dict = {}
    thread = None
    if args.mode == "race":
        thread = threading.Thread(target=lambda: frontier_box.update(zip(("results", "errors", "seconds"), run_frontier(queue, by_key, rubric, args.frontier_workers, stop, args.kill_inflight))))
        thread.start()
    jev_res, jev_s = run_jev(queue, by_key, rubric, args.jev_workers)
    stop.set()
    links, refused = link_map(queue, jev_res, rubric)
    write_map(out, links, refused)
    (out / "jev-results.json").write_text(json.dumps(jev_res, ensure_ascii=False), "utf-8")
    report = {
        "mode": args.mode,
        "rubric": rubric["version"],
        "site_pages": len(pages),
        "jev": {**totals(jev_res), "wall_seconds": round(jev_s, 2), "workers": args.jev_workers, "links_placed": len(links), "pages_refused": len(refused), "pages_linked": len({l["source"] for l in links})},
    }
    if thread:
        thread.join()
        fr_res = frontier_box.get("results", [])
        (out / "frontier-results.json").write_text(json.dumps(fr_res, ensure_ascii=False), "utf-8")
        on_time = [r for r in fr_res if not r.get("late")]
        ft = totals(fr_res)  # priced on every page it finished, late ones included, so the per-page cost has a sample
        fl, _ = link_map(queue, fr_res, rubric)
        report["frontier"] = {**ft, "pages_by_the_clock": len(on_time), "cost_by_the_clock": round(sum(r["meter"]["cost"] for r in on_time), 6), "late_pages": len(fr_res) - len(on_time), "last_late_page_at": max((r["at"] for r in fr_res), default=0), "wall_seconds": round(jev_s, 2), "workers": args.frontier_workers, "links_placed": len(fl), "errors": frontier_box.get("errors", [])}
        agr = agreement(queue, jev_res, fr_res, rubric)
        report["agreement"] = {k: v for k, v in agr.items() if k != "rows"}
        jt = report["jev"]
        if ft["pages"] and jt["pages"]:
            per_jev, per_fr = jt["cost"] / jt["pages"], ft["cost"] / ft["pages"]
            report["per_page"] = {"jev": round(per_jev, 6), "frontier": round(per_fr, 6), "times_cheaper": round(per_fr / per_jev, 1), "frontier_full_pass_cost": round(per_fr * jt["pages"], 2)}
    (out / "report.json").write_text(json.dumps(report, indent=1), "utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
