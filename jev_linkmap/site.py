"""One command for a whole site, two ways to run it.

  --mode system1            Jev alone with a rubric that is already trained (rubrics/v3.json). No other model,
                            no other account. Seconds and cents.
  --mode system1+system2    Jev plus the loop: a deep model referees blocks of pages, System 2 rewrites the rubric
                            from the disagreements, and the site is mapped with the rubric that scored best on a
                            held-out block. The deep model is Claude (default) or Codex: LINKMAP_DEEP=codex.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def step(*args: str) -> None:
    print("+", " ".join(args), file=sys.stderr)
    subprocess.run([sys.executable, "-m", *args], check=True, stdout=subprocess.DEVNULL)


def best_rubric(runs: Path, versions: int) -> int:
    """The version the held-out block liked most: links the referee confirms and links Jev found, equally weighted."""
    def score(v: int) -> float:
        a = json.loads((runs / f"holdout-v{v}" / "block.json").read_text("utf-8"))["agreement"]
        return (a["jev_yes_confirmed"] or 0) + (a["frontier_yes_found"] or 0)
    return max(range(1, versions + 1), key=score)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sitemap")
    ap.add_argument("--mode", choices=["system1", "system1+system2"], default="system1")
    ap.add_argument("--rubric", default="rubrics/v3.json", help="system1: the trained rubric to use")
    ap.add_argument("--blocks", type=int, default=2, help="system1+system2: rubric rewrites")
    ap.add_argument("--sample", type=int, default=24, help="system1+system2: pages per block")
    ap.add_argument("--verify", action="store_true", help="editor pass over the placed links before you ship them")
    ap.add_argument("--out", default="out")
    ap.add_argument("--runs", default="runs")
    args = ap.parse_args()

    step("jev_linkmap.crawl", args.sitemap)
    rubric = args.rubric
    if args.mode == "system1+system2":
        site_rubrics, runs = Path("rubrics/site"), Path(args.runs)
        site_rubrics.mkdir(parents=True, exist_ok=True)
        shutil.copy("rubrics/v1.json", site_rubrics / "v1.json")  # a new site starts from the hand-written rubric
        for b in range(args.blocks):
            v = b + 1
            step("jev_linkmap.run", "block", "--rubric", str(site_rubrics / f"v{v}.json"), "--sample", str(args.sample), "--index", str(b), "--out", str(runs / f"block{v}"))
            step("jev_linkmap.system2", "--rubric", str(site_rubrics / f"v{v}.json"), "--block", str(runs / f"block{v}"), "--rubrics", str(site_rubrics))
        for v in range(1, args.blocks + 2):
            step("jev_linkmap.run", "block", "--rubric", str(site_rubrics / f"v{v}.json"), "--sample", str(args.sample), "--index", "9", "--out", str(runs / f"holdout-v{v}"))
        rubric = str(site_rubrics / f"v{best_rubric(runs, args.blocks + 1)}.json")
    step("jev_linkmap.run", "map", "--rubric", rubric, "--out", args.out)
    if args.verify:
        step("jev_linkmap.verify", "--out", args.out)
    step("jev_linkmap.report", "--out", args.out, "--runs", args.runs)
    print(f"{args.out}/report.html  {args.out}/linkmap.csv  (rubric: {rubric})")


if __name__ == "__main__":
    main()
