"""The editor pass: before links go on a live site, a deep model reads only the links Jev placed.

It sees the sentence, the anchor and the target, twenty links to a call, and keeps or cuts each one. It never adds
a link and never rewrites an anchor. This is a few cents of deep-model reading instead of a full frontier pass,
because Jev already threw away the 8,000 pairs that were never going to be links.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import deep

SYSTEM = """You are the final editor of an internal link map. Each item is one proposed link: a sentence that already exists on the source page, the exact words in it that would become the link (the anchor), and the target page.

Keep a link only when all three hold:
1. The anchor names the target page's own subject, so a reader who clicks gets what the words promised.
2. The sentence around the anchor is really about that subject.
3. The anchor is a complete, natural phrase, not a fragment cut mid-clause, a bare brand or product pair, a heading label, or boilerplate.

Cut everything else. When in doubt, cut: a missing link costs nothing, a wrong link costs trust.

Answer with one JSON object and nothing else, one entry per item id: {"1": true, "2": false, ...}"""


def batches(links: list[dict], size: int) -> list[list[tuple[int, dict]]]:
    numbered = list(enumerate(links, 1))
    return [numbered[i : i + size] for i in range(0, len(numbered), size)]


def review(batch: list[tuple[int, dict]]) -> tuple[dict[int, bool], dict]:
    items = [{"id": n, "source_page": l["source"].rstrip("/").rsplit("/", 1)[-1].replace("-", " ")[:100], "sentence": l["sentence"], "anchor": l["anchor"], "target_page": l["target_title"]} for n, l in batch]
    text, meter = deep.call("referee", SYSTEM, json.dumps(items, ensure_ascii=False), timeout=600)
    m = re.search(r"\{.*\}", text or "", re.S)
    answer = json.loads(m.group(0)) if m else {}
    return {n: answer.get(str(n)) is True for n, _ in batch}, meter  # no answer for an item means cut


def main() -> None:
    ap = argparse.ArgumentParser(description="Editor pass over out/linkmap.json: writes linkmap-verified.json and .csv")
    ap.add_argument("--out", default="out")
    ap.add_argument("--batch", type=int, default=20)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    out = Path(args.out)
    links = json.loads((out / "linkmap.json").read_text("utf-8"))["links"]
    keep: dict[int, bool] = {}
    cost = seconds = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for verdicts, meter in pool.map(review, batches(links, args.batch)):
            keep.update(verdicts)
            cost += meter["cost"]
            seconds += meter.get("model_seconds", meter["seconds"])
    kept = [l for n, l in enumerate(links, 1) if keep.get(n)]
    summary = {"proposed": len(links), "kept": len(kept), "cut": len(links) - len(kept), "pages": len({l["source"] for l in kept}), "editor": deep.model_name("referee"), "cost": round(cost, 4), "model_seconds": round(seconds, 1)}
    (out / "linkmap-verified.json").write_text(json.dumps({"summary": summary, "links": kept}, ensure_ascii=False, indent=1), "utf-8")
    with (out / "linkmap-verified.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "anchor", "target", "target_title", "confidence", "sentence"])
        w.writeheader()
        w.writerows(kept)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
