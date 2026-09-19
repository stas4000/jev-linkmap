"""Read a whole site from its sitemap: title, headings, body copy, and the internal links it already has.

Standard library only. Pages are cached on disk, so a second run costs no requests.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

UA = "jev-linkmap/0.1 (+https://github.com/stas4000/jev-linkmap)"
SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "form", "button", "select"}
CHROME_TAGS = {"nav", "footer", "header", "aside"}
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "blockquote", "div", "section", "article", "br", "tr", "dt", "dd", "figcaption"}
LINK_OPEN, LINK_CLOSE = "\u27e6", "\u27e7"  # copy that is already a link keeps its brackets, so nobody links it twice
VOID_TAGS = {"br", "img", "input", "meta", "link", "hr", "source", "area", "base", "col", "embed", "track", "wbr"}


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data


def sitemap_urls(sitemap: str, seen: set[str] | None = None) -> list[str]:
    """Every <loc> in a sitemap, following sitemap indexes one level at a time."""
    seen = seen if seen is not None else set()
    if sitemap in seen:
        return []
    seen.add(sitemap)
    xml = fetch(sitemap).decode("utf-8", "replace")
    locs = [m.strip().replace("&amp;", "&") for m in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)]
    if "<sitemapindex" in xml:
        out: list[str] = []
        for loc in locs:
            out.extend(sitemap_urls(loc, seen))
        return out
    return locs


class PageParser(HTMLParser):
    """Body copy without the site chrome, paragraph by paragraph, plus every link and where it sat."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.title = ""
        self.h1 = ""
        self.description = ""
        self.lang = ""
        self.canonical = ""
        self.noindex = False
        self.headings: list[str] = []
        self.blocks: list[str] = []
        self.links: list[dict] = []  # {"href", "text", "in_copy"}
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._capture: str | None = None
        self._capture_buf: list[str] = []
        self._link: dict | None = None

    def _inside(self, tags: set[str]) -> bool:
        return any(t in tags for t in self._stack)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        plain = re.sub(r"\u27e6[^\u27e7]*\u27e7?", "", text).strip()
        if len(text) >= 40 and len(plain) >= 25:  # menu crumbs, button labels and bare link lists are not copy
            self.blocks.append(text)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag == "html":
            self.lang = (a.get("lang") or "").lower()
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name == "description":
                self.description = (a.get("content") or "").strip()
            if name == "robots" and "noindex" in (a.get("content") or "").lower():
                self.noindex = True
        if tag == "link" and "canonical" in (a.get("rel") or "").lower():
            self.canonical = urljoin(self.base, a.get("href") or "")
        if tag in VOID_TAGS:
            if tag == "br":
                self._buf.append(" ")
            return
        if tag in BLOCK_TAGS and not self._inside(SKIP_TAGS):
            self._flush()
        self._stack.append(tag)
        if tag in ("title", "h1", "h2", "h3"):
            self._capture, self._capture_buf = tag, []
        if tag == "a" and a.get("href"):
            self._buf.append(LINK_OPEN)
            self._link = {"href": urldefrag(urljoin(self.base, a["href"]))[0], "text": "", "in_copy": not self._inside(CHROME_TAGS)}

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS or tag not in self._stack:
            return
        while self._stack and self._stack.pop() != tag:
            pass
        if self._capture == tag:
            text = re.sub(r"\s+", " ", "".join(self._capture_buf)).strip()
            if tag == "title":
                self.title = self.title or text
            elif text:
                if tag == "h1":
                    self.h1 = self.h1 or text
                self.headings.append(text)
            self._capture = None
        if tag == "a" and self._link:
            self._buf.append(LINK_CLOSE)
            self._link["text"] = re.sub(r"\s+", " ", self._link["text"]).strip()
            self.links.append(self._link)
            self._link = None
        if tag in BLOCK_TAGS and not self._inside(SKIP_TAGS):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._capture_buf.append(data)
        if self._link is not None:
            self._link["text"] += data
        if self._inside(SKIP_TAGS) or self._inside(CHROME_TAGS) or "title" in self._stack:
            return
        self._buf.append(data)


def plain_copy(block: str) -> str:
    return block.replace(LINK_OPEN, "").replace(LINK_CLOSE, "")


def norm(url: str) -> str:
    """One spelling per page: no fragment, no query, no trailing slash, no www."""
    u = urlparse(urldefrag(url)[0])
    host = u.netloc.lower().removeprefix("www.")
    return f"{host}{u.path.rstrip('/')}".lower()


def parse_page(url: str, html: str) -> dict:
    p = PageParser(url)
    try:
        p.feed(html)
        p.close()
    except Exception:  # broken markup: keep what was read so far
        pass
    p._flush()
    seen: set[str] = set()
    blocks = [b for b in p.blocks if not (b in seen or seen.add(b))]
    host = urlparse(url).netloc.lower().removeprefix("www.")
    internal = [l for l in p.links if urlparse(l["href"]).netloc.lower().removeprefix("www.") == host]
    return {
        "url": url,
        "key": norm(url),
        "title": p.title,
        "h1": p.h1,
        "description": p.description,
        "lang": p.lang,
        "noindex": p.noindex,
        "canonical": p.canonical,
        "headings": p.headings[:30],
        "blocks": blocks,
        "words": sum(len(plain_copy(b).split()) for b in blocks),
        "links_out": sorted({norm(l["href"]) for l in internal if l["in_copy"]} - {norm(url)}),
        "links_out_all": sorted({norm(l["href"]) for l in internal} - {norm(url)}),
    }


def crawl(sitemap: str, cache: Path, workers: int = 8, limit: int = 0) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    urls = list(dict.fromkeys(sitemap_urls(sitemap)))
    if limit:
        urls = urls[:limit]

    def one(url: str) -> dict | None:
        f = cache / (hashlib.sha1(url.encode()).hexdigest() + ".html")
        try:
            if f.exists():
                html = f.read_text("utf-8", "replace")
            else:
                html = fetch(url).decode("utf-8", "replace")
                f.write_text(html, "utf-8")
        except Exception as e:
            print(f"skip {url}: {e}", file=sys.stderr)
            return None
        return parse_page(url, html)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pages = [p for p in pool.map(one, urls) if p]
    print(f"read {len(pages)}/{len(urls)} pages in {time.perf_counter() - started:.1f}s", file=sys.stderr)
    return pages


def main() -> None:
    ap = argparse.ArgumentParser(description="Read a site from its sitemap into pages.jsonl")
    ap.add_argument("sitemap")
    ap.add_argument("--out", default="data/pages.jsonl")
    ap.add_argument("--cache", default="data/html")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    pages = crawl(args.sitemap, Path(args.cache), args.workers, args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(out)


if __name__ == "__main__":
    main()
