#!/usr/bin/env bash
# The loop: judge a block, let System 2 rewrite the rubric from the disagreements, judge the next block with it.
# Then every rubric version is scored on one held-out block none of them was written from.
set -euo pipefail
BLOCKS=${BLOCKS:-2}; SAMPLE=${SAMPLE:-24}; HOLDOUT=${HOLDOUT:-9}
for ((b = 0; b < BLOCKS; b++)); do
  v=$((b + 1))
  python3 -m jev_linkmap.run block --rubric rubrics/v$v.json --sample "$SAMPLE" --index "$b" --out runs/block$v > /dev/null
  python3 -m jev_linkmap.system2 --rubric rubrics/v$v.json --block runs/block$v > /dev/null
done
for ((v = 1; v <= BLOCKS + 1; v++)); do
  python3 -m jev_linkmap.run block --rubric rubrics/v$v.json --sample "$SAMPLE" --index "$HOLDOUT" --out runs/holdout-v$v > /dev/null
done
python3 -m jev_linkmap.report --loop-only  # or use: python3 -m jev_linkmap.site <sitemap> --mode system1+system2
