"""PDF content analysis — text extraction and chapter structure detection."""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from pdfminer.high_level import extract_text_to_fp
    from pdfminer.layout import LAParams
    PDFMINER_AVAILABLE = True
except ImportError:
    PDFMINER_AVAILABLE = False


CHAPTER_PATTERNS: list[tuple[str, list[str]]] = [
    ("cover/title", [r"halaman\s+judul", r"lembar\s+judul", r"title\s+page", r"universitas\s+\w+"]),
    ("approval/endorsement", [r"lembar\s+persetujuan", r"lembar\s+pengesahan", r"halaman\s+persetujuan", r"approval\s+sheet"]),
    ("abstract", [r"\babstrak\b", r"\babstract\b", r"intisari"]),
    ("foreword", [r"kata\s+pengantar", r"prakata", r"foreword", r"preface"]),
    ("table of contents", [r"daftar\s+isi", r"table\s+of\s+contents", r"contents"]),
    ("chapter 1 - introduction", [
        r"bab\s+[i1]\s*[\.\:\-]?\s*(pendahuluan|latar\s+belakang|introduction)",
        r"chapter\s+[i1]\s*[\.\:\-]?\s*(introduction|background)",
        r"^1[\.\s]+(pendahuluan|latar\s+belakang|introduction)",
        r"latar\s+belakang\s+(masalah|penelitian)", r"rumusan\s+masalah", r"tujuan\s+penelitian",
    ]),
    ("chapter 2 - literature review", [
        r"bab\s+[ii2]\s*[\.\:\-]?\s*(tinjauan|kajian|landasan|kerangka|teori)",
        r"chapter\s+(ii|2)\s*[\.\:\-]?\s*(literature|review|theoretical)",
        r"^2[\.\s]+(tinjauan|kajian|landasan)",
        r"tinjauan\s+pustaka", r"kajian\s+pustaka", r"landasan\s+teori",
        r"kerangka\s+teori", r"kerangka\s+konsep",
    ]),
    ("chapter 3 - methodology", [
        r"bab\s+[iii3]\s*[\.\:\-]?\s*(metod|penelitian)",
        r"chapter\s+(iii|3)\s*[\.\:\-]?\s*(method|research)",
        r"^3[\.\s]+(metod)", r"metode\s+penelitian", r"metodologi\s+penelitian",
        r"desain\s+penelitian", r"populasi\s+dan\s+sampel",
        r"teknik\s+(pengumpulan|analisis)\s+data",
    ]),
    ("chapter 4 - results", [
        r"bab\s+[iv4]\s*[\.\:\-]?\s*(hasil|analisis|pembahasan|temuan|finding)",
        r"chapter\s+(iv|4)\s*[\.\:\-]?\s*(result|finding|analysis|discussion)",
        r"^4[\.\s]+(hasil|analisis|pembahasan)", r"hasil\s+penelitian",
        r"hasil\s+dan\s+pembahasan", r"analisis\s+data", r"temuan\s+penelitian",
    ]),
    ("chapter 5 - conclusion", [
        r"bab\s+[v5]\s*[\.\:\-]?\s*(kesimpulan|penutup|simpulan|saran|conclusion)",
        r"chapter\s+(v|5)\s*[\.\:\-]?\s*(conclusion|closing|recommendation)",
        r"^5[\.\s]+(kesimpulan|penutup|simpulan)", r"kesimpulan\s+dan\s+saran",
        r"simpulan\s+dan\s+saran", r"penutup",
    ]),
    ("bibliography", [r"daftar\s+pustaka", r"daftar\s+referensi", r"references", r"bibliography", r"kepustakaan"]),
    ("appendix", [r"lampiran", r"appendix", r"appendices"]),
]

REQUIRED_CHAPTERS = {"chapter 1 - introduction", "chapter 3 - methodology", "chapter 4 - results", "chapter 5 - conclusion", "bibliography"}
PARTIAL_MIN_CHAPTERS = 3

FILE_NAME_CHAPTER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cover/title",          re.compile(r"cover|sampul|judul|halaman.?judul|title", re.I)),
    ("approval/endorsement", re.compile(r"persetujuan|pengesahan|approval|lembar", re.I)),
    ("abstract",             re.compile(r"abstrak|abstract|intisari", re.I)),
    ("foreword",             re.compile(r"kata.?pengantar|prakata|foreword|preface", re.I)),
    ("table of contents",    re.compile(r"daftar.?isi|contents|toc", re.I)),
    ("chapter 1 - introduction",      re.compile(r"bab.?[i1](?!\w)|bab.?1|chapter.?[i1](?!\w)|chapter.?1|pendahuluan", re.I)),
    ("chapter 2 - literature review", re.compile(r"bab.?i{2}(?!\w)|bab.?2|chapter.?2|tinjauan|kajian|landasan", re.I)),
    ("chapter 3 - methodology",       re.compile(r"bab.?i{3}(?!\w)|bab.?3|chapter.?3|metod", re.I)),
    ("chapter 4 - results",           re.compile(r"bab.?iv(?!\w)|bab.?4|chapter.?4|hasil|pembahasan|analisis", re.I)),
    ("chapter 5 - conclusion",        re.compile(r"bab.?v(?!\w)|bab.?5|chapter.?5|kesimpulan|penutup|simpulan", re.I)),
    ("bibliography",         re.compile(r"daftar.?pustaka|referensi|bibliography|references", re.I)),
    ("appendix",             re.compile(r"lampiran|appendix|appendices", re.I)),
]

LOGIN_PATTERN = re.compile(r"login|signin|sign.in|shibboleth|cas\.(?:ac|edu|go)\.id|auth\..*redirect|/account/|/user/login", re.IGNORECASE)


@dataclass
class PdfAnalysisResult:
    status: str = "unknown"
    chapters_from_pdf: list[str] = field(default_factory=list)
    chapters_from_filename: list[str] = field(default_factory=list)
    url_pdf_verified: str = ""
    url_per_chapter: dict[str, str] = field(default_factory=dict)
    locked_chapters: list[str] = field(default_factory=list)
    pdf_read: bool = False
    estimated_pages: int = 0
    technical_note: str = ""

    @property
    def all_chapters(self) -> list[str]:
        return list(dict.fromkeys(self.chapters_from_pdf + self.chapters_from_filename))

    @property
    def summary(self) -> str:
        ch = self.all_chapters
        n = len(ch)
        if self.status == "full":     return f"✓ Full — {n} chapters detected"
        if self.status == "partial":  return f"~ Partial — {', '.join(ch[:3])}{f' +{n-3}' if n > 3 else ''}"
        if self.status == "locked":   return "✗ Locked"
        if self.url_per_chapter:      return f"? Multi-file: {len(self.url_per_chapter)} files"
        return "? Cannot analyze"


def _download_pdf_snippet(session: requests.Session, url: str, head_bytes: int = 150_000,
                          tail_bytes: int = 100_000, timeout: int = 20) -> Optional[bytes]:
    try:
        head = session.head(url, timeout=timeout, allow_redirects=True)
        if head.status_code not in (200, 206): return None
        cl = int(head.headers.get("Content-Length", 0))
        ar = head.headers.get("Accept-Ranges", "").lower() == "bytes"
        if ar and cl > head_bytes + tail_bytes:
            s = _range_get(session, url, 0, head_bytes - 1, timeout)
            e = _range_get(session, url, max(0, cl - tail_bytes), cl - 1, timeout)
            if s and e: return s + e
            if s: return s
        r = session.get(url, stream=True, timeout=timeout, allow_redirects=True)
        if r.status_code != 200: return None
        if "html" in r.headers.get("Content-Type", "").lower(): return None
        data = b""
        for chunk in r.iter_content(8192):
            data += chunk
            if len(data) >= head_bytes: break
        r.close()
        return data if data else None
    except Exception:
        return None


def _range_get(session: requests.Session, url: str, start: int, end: int, timeout: int) -> Optional[bytes]:
    try:
        r = session.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=timeout, allow_redirects=True)
        return r.content if r.status_code in (200, 206) else None
    except Exception:
        return None


def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> Optional[str]:
    if not PDFMINER_AVAILABLE: return None
    try:
        output = io.StringIO()
        lp = LAParams(line_margin=0.3, word_margin=0.1, char_margin=2.0, boxes_flow=0.5)
        extract_text_to_fp(io.BytesIO(pdf_bytes), output, laparams=lp, output_type="text", codec="utf-8")
        return output.getvalue()
    except Exception:
        return None


def detect_chapters_from_text(text: str) -> list[str]:
    if not text: return []
    tl = text.lower()
    found = []
    for name, patterns in CHAPTER_PATTERNS:
        for pat in patterns:
            try:
                if re.search(pat, tl, re.MULTILINE): found.append(name); break
            except re.error: continue
    return found


def estimate_pages(text: str) -> int:
    if not text: return 0
    return max(1, len(text.split()) // 250)


def determine_status_from_chapters(chapters: list[str], pdf_read: bool = True) -> str:
    if not chapters: return "unknown"
    cs = set(chapters)
    if REQUIRED_CHAPTERS.issubset(cs): return "full"
    cc = {c for c in cs if any(k in c for k in ["chapter 1", "chapter 2", "chapter 3", "chapter 4", "chapter 5", "methodology", "results", "conclusion", "bibliography"])}
    if len(cs) >= PARTIAL_MIN_CHAPTERS or len(cc) >= 2: return "partial"
    return "unknown"


def classify_pdfs_per_chapter(pdf_list: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for pdf in pdf_list:
        search = f"{pdf.get('label', '')} {pdf.get('url', '')}".lower()
        for name, pat in FILE_NAME_CHAPTER_PATTERNS:
            if pat.search(search):
                if name not in result: result[name] = pdf["url"]
                break
    return result


def verify_access_batch(session: requests.Session, url_per_chapter: dict[str, str],
                        delay: float = 0.5, timeout: int = 10) -> tuple[dict[str, str], list[str]]:
    accessible: dict[str, str] = {}
    locked: list[str] = []
    for name, url in url_per_chapter.items():
        try:
            time.sleep(delay)
            resp = session.head(url, timeout=timeout, allow_redirects=True)
            rl = any(LOGIN_PATTERN.search(r.headers.get("Location", "")) for r in resp.history)
            if rl or LOGIN_PATTERN.search(resp.url) or resp.status_code in (401, 403):
                locked.append(name); continue
            ct = resp.headers.get("Content-Type", "").lower()
            if resp.status_code == 200 and ("pdf" in ct or "octet" in ct or "application" in ct):
                accessible[name] = url
            elif resp.status_code in (200, 206): accessible[name] = url
            else: locked.append(name)
        except Exception: locked.append(name)
    return accessible, locked


def collect_all_pdfs_from_page(soup: BeautifulSoup, base_url: str) -> list[dict]:
    result, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not (href.lower().endswith(".pdf") or re.search(r"/bitstream/|/retrieve/|/download/|/files/|/content/", href, re.I)):
            continue
        u = urljoin(base_url, href)
        if u in seen: continue
        seen.add(u)
        label = a.get_text(strip=True)
        if not label:
            for pt in ["td", "th", "li", "div", "span"]:
                p = a.find_parent(pt)
                if p: label = p.get_text(separator=" ", strip=True)[:80]; break
        skb = 0
        pr = a.find_parent(["tr", "li", "div"])
        if pr:
            m = re.search(r"([\d.,]+)\s*(B|Kb|KB|Mb|MB|Gb|GB)\b", pr.get_text(separator=" "))
            if m:
                v, u2 = float(m.group(1).replace(",", ".")), m.group(2).upper()
                skb = v / 1024 if u2 == "B" else v if "KB" in u2 else v * 1024 if "MB" in u2 else v * 1024 * 1024
        result.append({"url": u, "label": label, "size_kb": skb, "href_raw": href})
    result.sort(key=lambda x: x["size_kb"], reverse=True)
    return result


def analyze_single_pdf(session: requests.Session, pdf_url: str, delay: float = 0.5) -> PdfAnalysisResult:
    r = PdfAnalysisResult()
    if not pdf_url: r.technical_note = "Empty PDF URL"; return r
    if not PDFMINER_AVAILABLE: r.technical_note = "pdfminer not available"; return r
    time.sleep(delay)
    pdf = _download_pdf_snippet(session, pdf_url)
    if not pdf: r.technical_note = "Failed to download PDF"; return r
    if not pdf[:5].startswith(b"%PDF"): r.technical_note = "Not a PDF file"; return r
    r.pdf_read = True
    text = extract_text_from_pdf_bytes(pdf)
    if not text or len(text.strip()) < 100: r.status = "unknown"; r.technical_note = "No extractable text"; return r
    r.chapters_from_pdf = detect_chapters_from_text(text)
    r.estimated_pages = estimate_pages(text)
    r.status = determine_status_from_chapters(r.chapters_from_pdf, True)
    r.url_pdf_verified = pdf_url
    r.technical_note = f"Text: {len(text.split())} words | {len(r.chapters_from_pdf)} ch | ~{r.estimated_pages}p"
    return r


def collect_pdfs_per_chapter(session: requests.Session, detail_soup: BeautifulSoup, base_url: str, delay: float = 0.5) -> PdfAnalysisResult:
    r = PdfAnalysisResult()
    all_pdfs = collect_all_pdfs_from_page(detail_soup, base_url)
    if not all_pdfs: r.technical_note = "No PDF links found"; return r
    if len(all_pdfs) == 1: r.technical_note = "Single PDF"; r.url_pdf_verified = all_pdfs[0]["url"]; return r
    raw = classify_pdfs_per_chapter(all_pdfs)
    if not raw:
        r.url_per_chapter = {f"file_{i+1}": p["url"] for i, p in enumerate(all_pdfs)}
        r.technical_note = f"{len(all_pdfs)} files unclassified"; r.status = "unknown"; return r
    acc, locked = verify_access_batch(session, raw, delay=delay)
    r.url_per_chapter, r.locked_chapters, r.chapters_from_filename = acc, locked, list(acc.keys())
    r.status = determine_status_from_chapters(list(acc.keys()), False) if acc else "locked"
    r.technical_note = f"Multi-file: {len(raw)} files | {len(acc)} ok | {len(locked)} locked"
    return r


def analyze_full(session: requests.Session, pdf_url: str, detail_soup: Optional[BeautifulSoup],
                 base_url: str, delay: float = 0.5) -> PdfAnalysisResult:
    mr = PdfAnalysisResult()
    if detail_soup is not None:
        if len(collect_all_pdfs_from_page(detail_soup, base_url)) >= 2:
            mr = collect_pdfs_per_chapter(session, detail_soup, base_url, delay)
            if mr.status == "full": return mr
    if pdf_url:
        pr = analyze_single_pdf(session, pdf_url, delay)
        if mr.chapters_from_filename:
            pr.chapters_from_filename, pr.url_per_chapter, pr.locked_chapters = mr.chapters_from_filename, mr.url_per_chapter, mr.locked_chapters
            if pr.all_chapters:
                ns = determine_status_from_chapters(pr.all_chapters, pr.pdf_read)
                rank = {"full": 0, "partial": 1, "unknown": 2, "locked": 3}
                if rank.get(ns, 3) < rank.get(pr.status, 3): pr.status = ns
        return pr
    return mr if mr.all_chapters else PdfAnalysisResult(technical_note="No PDF URL and no detail page")


def format_chapter_list(chapters: list[str], max_show: int = 6) -> str:
    if not chapters: return "(none)"
    shown = chapters[:max_show]
    r = len(chapters) - max_show
    return " → ".join(shown) + (f" (+{r} more)" if r > 0 else "")


def format_url_per_chapter(url_per_chapter: dict[str, str], locked_chapters: list[str]) -> str:
    if not url_per_chapter and not locked_chapters: return ""
    lines = [f"  ✓ {n:<30} {u}" for n, u in url_per_chapter.items()]
    lines += [f"  ✗ {n:<30} [LOCKED]" for n in locked_chapters]
    return "\n".join(lines)