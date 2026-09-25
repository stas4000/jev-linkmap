"""Code does the search, the model does the judging.

For every page: the K most similar pages it does not link to yet (TF-IDF cosine, standard library), and for
each of those the phrases ALREADY in the page's copy that could carry the link. Nothing is written, so
every anchor the model can pick is text the author put there.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .crawl import plain_copy

STOP = set(
    "a an the and or but if then else for to of in on at by with from as is are was were be been being it its this that these those "
    "you your we our us they their them he she his her i me my not no yes do does did done can could should would will may might must "
    "have has had having more most less least very much many few some any all each every other another such than too also just only "
    "about into over under again once here there when where why how what which who whom whose so up out off down own same both "
    "new best top guide complete vs versus using use used get make made way ways need needs like one two three".split()
)
WORD = re.compile(r"[a-z0-9][a-z0-9\-\+\.#]*[a-z0-9\+#]|[a-z0-9]", re.I)


def stem(w: str) -> str:
    """Just enough to let 'agents' meet 'agent' and 'pipelines' meet 'pipeline'."""
    for suf, cut in (("ies", 3), ("sses", 2), ("ing", 3), ("es", 1), ("s", 1)):
        if w.endswith(suf) and len(w) - cut >= 4 and not w.endswith("ss"):
            return w[: -cut] + ("y" if suf == "ies" else "")
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in (m.group(0).lower() for m in WORD.finditer(text)) if w not in STOP and len(w) > 1]


def slug_words(url: str) -> str:
    return re.sub(r"[-_/%]+", " ", url.split("//", 1)[-1].split("/", 1)[-1])


def page_topic(p: dict) -> str:
    brand_cut = re.split(r"\s[|–—]\s", p.get("title") or "")[0]
    return " ".join([brand_cut, p.get("h1") or "", slug_words(p["url"])])


class Index:
    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.by_key = {p["key"]: i for i, p in enumerate(pages)}
        docs = []
        for p in pages:
            body = Counter(tokens(plain_copy(" ".join(p["blocks"]))))
            head = Counter(tokens(page_topic(p) + " " + " ".join(p["headings"])))
            for t, n in head.items():  # what a page says it is about outweighs what it happens to mention
                body[t] += 4 * n
            docs.append(body)
        n = len(docs)
        df = Counter(t for d in docs for t in d)
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vecs: list[dict[str, float]] = []
        for d in docs:
            v = {t: (1 + math.log(c)) * self.idf[t] for t, c in d.items()}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            self.vecs.append({t: x / norm for t, x in v.items()})
        self.postings: dict[str, list[tuple[int, float]]] = {}
        for i, v in enumerate(self.vecs):
            for t, x in v.items():
                self.postings.setdefault(t, []).append((i, x))
        inbound = Counter(k for p in pages for k in p["links_out_all"])
        # a page linked from most of the site is menu chrome, a contextual link to it adds nothing
        self.chrome = {k for k, c in inbound.items() if c >= 0.5 * n}
        # The same rule one level down, for copy. A block that appears verbatim on a twentieth of the site
        # is a template line, not this page's own words: a byline, a disclaimer, a CTA. It reads like copy
        # in the served HTML, so an anchor gets offered from it, and the link then lands on every page at
        # once or on none of them. Measured on www.bles-software.com 25 Sep 2026: the publisher byline
        # added to 500+ CMS bodies on 18 Sep supplied 4 of 285 proposed anchors ("API integrations",
        # "custom software"), and it is not in the source markdown at all, so none of them could be placed.
        blocks = Counter(b for p in pages for b in set(p["blocks"]))
        self.boilerplate = {b for b, c in blocks.items() if c >= max(3, 0.05 * n)}
        self.topic_terms = [self._topic_terms(p) for p in pages]

    def _topic_terms(self, p: dict) -> dict[str, float]:
        c = Counter(tokens(page_topic(p)))
        return {t: self.idf.get(t, 1.0) for t in c}

    def _cosine(self, i: int) -> list[tuple[int, float]]:
        """Every other page by cosine similarity to page i, best first. Read from both ends: down the
        column for the pages page i could link to, across the row for the pages that could link to it."""
        scores: dict[int, float] = {}
        for t, x in self.vecs[i].items():
            for j, y in self.postings[t]:
                if j != i:
                    scores[j] = scores.get(j, 0.0) + x * y
        return sorted(scores.items(), key=lambda kv: -kv[1])

    def similar(self, i: int, k: int) -> list[tuple[int, float]]:
        src = self.pages[i]
        linked = set(src["links_out"])
        ranked = self._cosine(i)
        out = []
        for j, s in ranked:
            tgt = self.pages[j]
            if tgt["key"] in linked or tgt["key"] in self.chrome or tgt.get("lang") != src.get("lang"):
                continue
            out.append((j, s))
            if len(out) == k:
                break
        return out

    def sources(self, j: int, k: int, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        """The mirror of similar(): the K pages most like page j that could link TO it and do not yet.

        similar() asks what one page should link to, so a page that is nobody's nearest neighbour is never
        anybody's candidate and ends with no inbound link at all. This side of the matrix starts from the
        page that needs the link. `allowed` is the set of pages whose copy can actually carry a link.
        """
        tgt = self.pages[j]
        out = []
        for i, s in self._cosine(j):
            src = self.pages[i]
            # already linked from here, so a second link adds no discovery path; a page in another
            # language never links across, the same rule similar() applies.
            if tgt["key"] in src["links_out_all"] or src.get("lang") != tgt.get("lang"):
                continue
            if allowed is not None and i not in allowed:
                continue
            out.append((i, s))
            if len(out) == k:
                break
        return out

    def anchors(self, i: int, j: int, limit: int = 5) -> list[dict]:
        """Phrases of 2 to 6 words already in page i's copy that speak the topic of page j."""
        terms = self.topic_terms[j]
        if not terms:
            return []
        total = sum(terms.values())
        found: dict[str, dict] = {}
        for b, block in enumerate(self.pages[i]["blocks"]):
            if b == 0 and block == self.pages[i].get("h1"):
                continue
            if block in self.boilerplate:
                continue
            for sent in re.split(r"(?<=[\.\!\?])\s+", block):
                shown = plain_copy(sent).strip()[:320]
                sent = re.sub(r"\u27e6[^\u27e7]*\u27e7?", " | ", sent)  # already a link: not an anchor
                words = [(m.group(0), m.start(), m.end()) for m in WORD.finditer(sent)]
                stems = [stem(w.lower()) if w.lower() not in STOP else "" for w, _, _ in words]
                for a in range(len(words)):
                    if stems[a] not in terms:
                        continue
                    for z in range(a + 1, min(a + 6, len(words))):
                        if stems[z] not in terms:
                            continue
                        hit = {s for s in stems[a : z + 1] if s in terms}
                        if len(hit) < 2:
                            continue
                        span = sent[words[a][1] : words[z][2]]
                        if re.search(r"[,;:\(\)\"“”\|/↔]", span):
                            continue
                        cover = sum(terms[s] for s in hit) / total
                        density = len(hit) / (z - a + 1)
                        score = cover * (0.5 + 0.5 * density)
                        key = span.lower()
                        if key not in found or found[key]["score"] < score:
                            found[key] = {"phrase": span, "sentence": shown, "block": b, "score": round(score, 4)}
        picked: list[dict] = []
        for cand in sorted(found.values(), key=lambda c: (-c["score"], len(c["phrase"]))):
            low = cand["phrase"].lower()
            if any(low in p["phrase"].lower() or p["phrase"].lower() in low for p in picked):
                continue
            picked.append(cand)
            if len(picked) == limit:
                break
        return picked


def build_queue(pages: list[dict], k: int = 15, anchors: int = 5, min_words: int = 120) -> list[dict]:
    """One job per page: the page's copy and its K candidate targets, each with its possible anchors."""
    idx = Index(pages)
    queue = []
    for i, p in enumerate(pages):
        if p["words"] < min_words:
            queue.append({"source": p["key"], "url": p["url"], "targets": [], "skipped": "thin page"})
            continue
        targets = []
        for n, (j, sim) in enumerate(idx.similar(i, k), 1):
            t = pages[j]
            targets.append(
                {
                    "id": f"t{n}",
                    "key": t["key"],
                    "url": t["url"],
                    "title": re.split(r"\s[|–—]\s", t["title"])[0] or t["h1"],
                    "about": (t["description"] or (t["blocks"][0] if t["blocks"] else ""))[:240],
                    "similarity": round(sim, 4),
                    "anchors": idx.anchors(i, j, anchors),
                }
            )
        queue.append({"source": p["key"], "url": p["url"], "targets": targets})
    return queue
