"""Two judges, one job. Both read the same page copy, the same candidate targets, the same anchor options
and the same rubric. Jev answers with probabilities, the frontier model answers with JSON. The rule that
turns answers into placed links lives here, in code, and is the same for both.
"""

from __future__ import annotations

import json
import os
import re
from . import deep, jev
from .crawl import plain_copy

COPY_WORDS = int(os.environ.get("LINKMAP_COPY_WORDS", "1500"))


def job_state(job: dict, page: dict, rubric: dict) -> dict:
    words = " ".join(plain_copy(b) for b in page["blocks"]).split()
    state = {
        "source": {"url": page["url"], "title": page["title"], "copy": " ".join(words[:COPY_WORDS])},
        "targets": [{"id": t["id"], "title": t["title"], "about": t["about"]} for t in job["targets"]],
    }
    if rubric.get("examples"):
        state["lessons"] = rubric["examples"]
    return state


def anchor_options(target: dict) -> dict[str, str]:
    opts = {f"a{n}": f'"{a["phrase"]}" in the sentence: {a["sentence"]}' for n, a in enumerate(target["anchors"], 1)}
    opts["none"] = "none of these phrases is an honest anchor for this target"
    return opts


def jev_questions(job: dict, rubric: dict) -> dict:
    qs = {}
    for t in job["targets"]:
        qs[f"{t['id']}_link"] = jev.noul(f"TARGET {t['id']}: {t['title']}. {rubric['link_instructions']}")
        if t["anchors"]:
            qs[f"{t['id']}_anchor"] = jev.choice(f"TARGET {t['id']}: {t['title']}. {rubric['anchor_instructions']}", anchor_options(t))
    return qs


def judge_jev(job: dict, page: dict, rubric: dict) -> dict:
    if not job["targets"]:
        return {"source": job["source"], "verdicts": {}, "meter": {"seconds": 0, "cost": 0, "input_tokens": 0}}
    answers, meter = jev.ask(job_state(job, page, rubric), jev_questions(job, rubric))
    verdicts = {}
    for t in job["targets"]:
        link = answers.get(f"{t['id']}_link") or {}
        anchor = answers.get(f"{t['id']}_anchor") or {}
        verdicts[t["id"]] = {
            "link": round(float(link.get("noul") or 0), 3),
            "anchor": anchor.get("choice") or "none",
            "anchor_confidence": round(float(anchor.get("confidence") or 0), 3),
        }
    return {"source": job["source"], "verdicts": verdicts, "meter": meter}


FRONTIER_SYSTEM = """You audit internal links for a website. You get one SOURCE page and a list of candidate TARGET pages. For each target you also get phrases that already exist in the source copy and could carry the link.

For every target decide two things, by this rubric.

LINK: {link_instructions}

ANCHOR: {anchor_instructions}

Answer with one JSON object and nothing else, one entry per target id:
{{"t1": {{"link": true | false, "anchor": "a1" | "a2" | ... | "none"}}, ...}}
"link" is your decision: true only when the rubric is met."""


def frontier_prompt(job: dict, page: dict, rubric: dict) -> str:
    state = job_state(job, page, rubric)
    for t, full in zip(state["targets"], job["targets"]):
        t["anchor_options"] = anchor_options(full)
    return json.dumps(state, ensure_ascii=False)


def parse_frontier(job: dict, text: str, meter: dict) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    answer = json.loads(m.group(0)) if m else {}
    verdicts = {}
    for t in job["targets"]:
        a = answer.get(t["id"]) or {}
        verdicts[t["id"]] = {
            "link": 1.0 if a.get("link") is True else 0.0,
            "anchor": a.get("anchor") if a.get("anchor") in anchor_options(t) else "none",  # an option never offered is not an anchor
            "anchor_confidence": 1.0,
        }
    return {"source": job["source"], "verdicts": verdicts, "meter": meter}


def judge_frontier(job: dict, page: dict, rubric: dict, procs: set | None = None) -> dict:
    """One deep-model call per page. `procs` lets the race kill calls still in flight when the clock stops."""
    text, meter = deep.call("referee", FRONTIER_SYSTEM.format(**rubric), frontier_prompt(job, page, rubric), procs, timeout=600)
    return parse_frontier(job, text, meter)


def place_links(job: dict, verdicts: dict, rubric: dict) -> list[dict]:
    """The rule both judges are held to: sure enough about the link, an anchor that exists, best first, each phrase once."""
    ranked = []
    for t in job["targets"]:
        v = verdicts.get(t["id"])
        if not v or v["link"] < rubric["link_threshold"] or v["anchor"] == "none" or v["anchor_confidence"] < rubric["anchor_confidence"]:
            continue
        a = t["anchors"][int(v["anchor"][1:]) - 1]
        ranked.append((v["link"], t, a))
    ranked.sort(key=lambda r: -r[0])
    placed, used = [], set()
    for p, t, a in ranked:
        low = a["phrase"].lower()
        if any(low in u or u in low for u in used):
            continue
        used.add(low)
        placed.append({"source": job["url"], "target": t["url"], "target_title": t["title"], "anchor": a["phrase"], "sentence": a["sentence"], "confidence": p})
        if len(placed) == rubric["max_links_per_page"]:
            break
    return placed


def decision(v: dict, rubric: dict) -> bool:
    return v["link"] >= rubric["link_threshold"] and v["anchor"] != "none" and v["anchor_confidence"] >= rubric["anchor_confidence"]
