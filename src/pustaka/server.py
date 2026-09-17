"""MCP Server — search Indonesian thesis full text via OAI-PMH & HTML scraping.

Tools:
  - search_thesis          — search thesis by keyword
  - list_universities      — list supported universities
  - analyze_pdf            — deep PDF content analysis
  - search_and_analyze     — combined search + PDF analysis

Resources:
  - skripsi://universities — all universities
  - skripsi://stats        — repository statistics
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import ThesisSearcher, PDFMINER_AVAILABLE

logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("pustaka")

mcp = MCPServer(
    "pustaka",
    instructions="""\
Search thesis full text from 75+ Indonesian university repositories.

Main tools:
- `search_thesis` — search by keyword, filter university/type/province
- `list_universities` — list supported universities
- `analyze_pdf` — analyze PDF content directly (requires pdfminer.six)
- `search_and_analyze` — search + PDF analysis in one call
""",
)

_searcher: ThesisSearcher | None = None


def _get_searcher() -> ThesisSearcher:
    global _searcher
    if _searcher is None:
        import os
        _searcher = ThesisSearcher(
            delay=float(os.environ.get("PUSTAKA_DELAY", "1.2")),
            use_cache=os.environ.get("PUSTAKA_NO_CACHE", "").lower() not in ("1", "true"),
            max_workers=int(os.environ.get("PUSTAKA_WORKERS", "5")),
        )
    return _searcher


def _thesis_to_dict(s: Any) -> dict:
    d = s.to_dict()
    return {k: v for k, v in d.items() if v is not None and v != "" and v != [] and v != {}}


# ── Tools ────────────────────────────────────────────────────────────

@mcp.tool(name="search_thesis",
          description="Search thesis from 75+ Indonesian university repositories. Returns results with full/partial/locked status.")
async def search_thesis(
    keyword: str,
    max_per_univ: int = 10,
    method: str = "auto",
    only_full: bool = False,
    universities: list[str] | None = None,
    univ_type: str | None = None,
    province: str | None = None,
) -> str:
    searcher = _get_searcher()
    results = searcher.search_many(
        keyword=keyword, id_list=universities, univ_type=univ_type,
        province=province, max_per_univ=max_per_univ, method=method, only_full=only_full,
    )
    return json.dumps([{"no": i + 1, **_thesis_to_dict(r)} for i, r in enumerate(results)], ensure_ascii=False, indent=2)


@mcp.tool(name="list_universities",
          description="List supported universities. Filter by type (PTN/PTS) or province.")
async def list_universities(tipe: str | None = None, provinsi: str | None = None) -> str:
    searcher = _get_searcher()
    unis = searcher.list_universities(tipe, provinsi)
    return json.dumps([{"id": u["id"], "nama": u["nama"], "kota": u.get("kota", ""),
                        "provinsi": u["provinsi"], "tipe": u["tipe"], "platform": u["platform"],
                        "oai": bool(u.get("oai_endpoint"))} for u in unis], ensure_ascii=False, indent=2)


@mcp.tool(name="analyze_pdf",
          description="Deep PDF content analysis. Detects chapters inside the document, estimates page count, and checks access status.")
async def analyze_pdf(url_pdf: str, url_detail: str | None = None) -> str:
    if not PDFMINER_AVAILABLE:
        return json.dumps({"error": "pdfminer.six not installed. Run: pip install pdfminer.six"}, ensure_ascii=False, indent=2)
    from .pdf_analyzer import analyze_full
    from bs4 import BeautifulSoup
    searcher = _get_searcher()
    detail_soup, base_url = None, ""
    if url_detail:
        try:
            resp = searcher.session.get(url_detail, timeout=20, allow_redirects=True)
            if resp.status_code == 200: detail_soup = BeautifulSoup(resp.text, "lxml"); base_url = url_detail.rsplit("/", 1)[0] + "/"
        except Exception: pass
    result = analyze_full(searcher.session, url_pdf, detail_soup, base_url, delay=0.5)
    return json.dumps({
        "status": result.status, "summary": result.summary,
        "chapters_from_pdf": result.chapters_from_pdf,
        "chapters_from_filename": result.chapters_from_filename,
        "all_chapters": result.all_chapters,
        "url_pdf_verified": result.url_pdf_verified,
        "url_per_chapter": result.url_per_chapter,
        "locked_chapters": result.locked_chapters,
        "pdf_read": result.pdf_read, "estimated_pages": result.estimated_pages,
        "technical_note": result.technical_note,
    }, ensure_ascii=False, indent=2)


@mcp.tool(name="search_and_analyze",
          description="Combined search + PDF analysis in one call. Slower but returns accurate status immediately.")
async def search_and_analyze(
    keyword: str, max_per_univ: int = 5, method: str = "auto",
    only_full: bool = False, universities: list[str] | None = None,
    univ_type: str | None = None, province: str | None = None,
) -> str:
    if not PDFMINER_AVAILABLE:
        return json.dumps({"error": "pdfminer.six not installed."}, ensure_ascii=False, indent=2)
    from .pdf_analyzer import analyze_full
    from bs4 import BeautifulSoup
    searcher = _get_searcher()
    results = searcher.search_many(keyword=keyword, id_list=universities, univ_type=univ_type,
                                    province=province, max_per_univ=max_per_univ, method=method, only_full=only_full)
    enriched = []
    for r in results:
        item = _thesis_to_dict(r)
        if r.url_pdf:
            ds, base = None, ""
            if r.url_detail:
                try:
                    resp = searcher.session.get(r.url_detail, timeout=20, allow_redirects=True)
                    if resp.status_code == 200: ds = BeautifulSoup(resp.text, "lxml"); base = r.url_detail.rsplit("/", 1)[0] + "/"
                except Exception: pass
            an = analyze_full(searcher.session, r.url_pdf, ds, base, delay=0.3)
            item["pdf_analysis"] = {"status": an.status, "chapters_from_pdf": an.chapters_from_pdf,
                                     "chapters_from_filename": an.chapters_from_filename, "all_chapters": an.all_chapters,
                                     "url_per_chapter": an.url_per_chapter, "locked_chapters": an.locked_chapters,
                                     "estimated_pages": an.estimated_pages, "technical_note": an.technical_note}
        enriched.append(item)
    return json.dumps(enriched, ensure_ascii=False, indent=2)


# ── Resources ────────────────────────────────────────────────────────

@mcp.resource(uri="skripsi://universities", name="University List",
              description="All supported universities", mime_type="application/json")
async def get_universities() -> str:
    searcher = _get_searcher()
    unis = searcher.list_universities()
    return json.dumps([{"id": u["id"], "nama": u["nama"], "kota": u.get("kota", ""),
                        "provinsi": u["provinsi"], "tipe": u["tipe"], "platform": u["platform"],
                        "oai": bool(u.get("oai_endpoint"))} for u in unis], ensure_ascii=False, indent=2)


@mcp.resource(uri="skripsi://stats", name="Repository Stats",
              description="Statistics by type and platform", mime_type="application/json")
async def get_stats() -> str:
    searcher = _get_searcher()
    unis = searcher.list_universities()
    by_type: dict[str, int] = {}; by_platform: dict[str, int] = {}; by_province: dict[str, int] = {}; oai_count = 0
    for u in unis:
        by_type[u["tipe"]] = by_type.get(u["tipe"], 0) + 1
        by_platform[u["platform"]] = by_platform.get(u["platform"], 0) + 1
        by_province[u["provinsi"]] = by_province.get(u["provinsi"], 0) + 1
        if u.get("oai_endpoint"): oai_count += 1
    return json.dumps({"total": len(unis), "by_type": by_type, "by_platform": by_platform,
                        "top_provinces": sorted(by_province.items(), key=lambda x: -x[1])[:10],
                        "oai_enabled": oai_count, "pdfminer_available": PDFMINER_AVAILABLE}, ensure_ascii=False, indent=2)


@mcp.prompt(name="search_thesis", description="Template prompt for searching thesis full text")
def prompt_search_thesis(keyword: str = "") -> str:
    return f"""\
Search thesis full text about "{keyword}" from Indonesian university repositories.

Use the search_thesis tool with:
- keyword: "{keyword}"
- max_per_univ: 10
- method: auto

After results, summarize:
1. Total thesis found
2. How many are FULL, PARTIAL, LOCKED
3. Top 5 FULL entries with university and PDF link
"""


def main():
    mcp.run()


if __name__ == "__main__":
    main()