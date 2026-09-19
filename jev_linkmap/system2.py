"""System 2: a deep model reads where Jev and the frontier referee disagreed on the last block and rewrites the rubric.

Jev never sees this model's prose at run time. It only sees the new question wording, the new lessons and the
new thresholds. The deep model is called once per block, so its cost is a rounding error next to a frontier
model judging every page.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import deep

BRIEF = """You are System 2 in a two-speed loop that rebuilds a website's internal link map.

System 1 is Jev, a decision model. It writes no text. For each SOURCE page it gets the page copy and 15 candidate TARGET pages, and for each target it answers two questions: a yes/no probability ("link": should this page link to that target) and a multiple choice ("anchor": which phrase that already exists in the source copy should carry the link, or none). It answers a whole page in half a second for about $0.0003. It reads the question wording literally and has no memory between pages. Code places a link only when link >= link_threshold and the anchor choice is not none with confidence >= anchor_confidence, and keeps at most max_links_per_page per page, best first.

A frontier model judged the same block with the same rubric as a referee. It is slow and costs about 300 times more, so it cannot run on the whole site. It is a strong reader but not ground truth: when Jev and the referee disagree, decide who is right by the evidence in the row, then change the rubric so Jev gets that kind of case right next time.

You get the current rubric, the block's agreement numbers, and the disagreement rows (plus a few agreements for contrast). Rewrite the rubric. Rules:
- link_instructions and anchor_instructions are read by Jev for every single target, so keep each under 120 words, concrete, and written as a test a fast reader can apply. Name the failure patterns you saw.
- examples is a list of at most 6 short lessons (one sentence each) shown to both judges with every page. Use it for patterns, never for specific page names.
- link_threshold must stay between 0.5 and 0.95, anchor_confidence between 0.3 and 0.9. Move them only when the rows show the probabilities are systematically too eager or too shy.
- Do not change max_links_per_page.
- The goal is a link map a careful SEO editor would sign: no link without a real reason, no anchor that does not name the target's subject, and no missed link where the source clearly discusses the target's subject.

Answer with one JSON object and nothing else:
{"diagnosis": "what went wrong in this block, in 2 to 4 sentences", "changes": ["each change and why"], "expected_effect": "one sentence", "rubric": {"link_instructions": "...", "anchor_instructions": "...", "link_threshold": 0.0, "anchor_confidence": 0.0, "examples": ["..."]}}"""


def compact(row: dict) -> dict:
    return {
        "source": row["source"].rstrip("/").rsplit("/", 1)[-1][:90],
        "target": row["target"][:110],
        "target_about": row["about"][:160],
        "anchor_options": row["anchors"],
        "jev": row["jev"],
        "referee": {"link": bool(row["frontier"]["link"]), "anchor": row["frontier"]["anchor"]},
        "jev_places": row["jev_places"],
        "referee_places": row["frontier_places"],
    }


def build_prompt(rubric: dict, block: dict, rows: list[dict], max_rows: int = 70) -> str:
    wrong = [r for r in rows if r["jev_places"] != r["frontier_places"]]
    anchor_split = [r for r in rows if r["jev_places"] and r["frontier_places"] and r["jev"]["anchor"] != r["frontier"]["anchor"]]
    agree_yes = [r for r in rows if r["jev_places"] and r["frontier_places"] and r["jev"]["anchor"] == r["frontier"]["anchor"]][:8]
    agree_no = [r for r in rows if not r["jev_places"] and not r["frontier_places"]][:8]
    return json.dumps(
        {
            "current_rubric": {k: rubric[k] for k in ("link_instructions", "anchor_instructions", "link_threshold", "anchor_confidence", "max_links_per_page", "examples")},
            "block_agreement": block["agreement"],
            "jev_placed_referee_did_not": [compact(r) for r in wrong if r["jev_places"]][: max_rows // 2],
            "referee_placed_jev_did_not": [compact(r) for r in wrong if r["frontier_places"]][: max_rows // 2],
            "both_placed_different_anchor": [compact(r) for r in anchor_split][:15],
            "both_placed_same_anchor": [compact(r) for r in agree_yes],
            "both_refused": [compact(r) for r in agree_no],
        },
        ensure_ascii=False,
    )


def think(prompt: str) -> tuple[dict, dict]:
    text, meter = deep.call("system2", BRIEF, prompt)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"system 2 wrote no JSON: {text[:300]}")
    return json.loads(m.group(0)), {"cost": meter["cost"], "seconds": meter["seconds"]}


def apply(old: dict, answer: dict) -> dict:
    r = answer["rubric"]
    new = dict(old)
    new["version"] = old["version"] + 1
    new["author"] = f"system 2 ({deep.model_name('system2')})"
    new["link_instructions"] = str(r["link_instructions"]).strip()
    new["anchor_instructions"] = str(r["anchor_instructions"]).strip()
    new["link_threshold"] = min(0.95, max(0.5, float(r.get("link_threshold", old["link_threshold"]))))
    new["anchor_confidence"] = min(0.9, max(0.3, float(r.get("anchor_confidence", old["anchor_confidence"]))))
    new["examples"] = [str(e).strip() for e in (r.get("examples") or [])][:6]
    return new


def main() -> None:
    ap = argparse.ArgumentParser(description="Rewrite the rubric from one block's disagreements")
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--block", required=True, help="the block's out directory (block.json and block-rows.json)")
    ap.add_argument("--rubrics", default="rubrics")
    args = ap.parse_args()
    old = json.loads(Path(args.rubric).read_text("utf-8"))
    block = json.loads((Path(args.block) / "block.json").read_text("utf-8"))
    rows = json.loads((Path(args.block) / "block-rows.json").read_text("utf-8"))
    prompt = build_prompt(old, block, rows)
    answer, meta = think(prompt)
    new = apply(old, answer)
    out = Path(args.rubrics) / f"v{new['version']}.json"
    out.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", "utf-8")
    review = {"from_version": old["version"], "to_version": new["version"], "model": deep.model_name("system2"), "prompt_chars": len(prompt), **meta, "diagnosis": answer.get("diagnosis"), "changes": answer.get("changes"), "expected_effect": answer.get("expected_effect")}
    (Path(args.block) / "system2.json").write_text(json.dumps(review, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(review, ensure_ascii=False, indent=1))
    print(out)


if __name__ == "__main__":
    main()
