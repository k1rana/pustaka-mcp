"""Core engine — search theses via OAI-PMH and HTML scraping."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Callable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import (
    Skripsi, HEADERS, OAI_NS, COVER_PATTERN, FULLTEXT_PATTERN,
    LOGIN_REDIRECT_PATTERN, STATUS_LOCKED, compute_score, determine_status,
)
from .pdf_analyzer import PDFMINER_AVAILABLE, analyze_full

log = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
REPO_CONFIG = _PACKAGE_DIR / "repositories.json"
CACHE_DIR = _PACKAGE_DIR / ".cache_skripsi"
CACHE_DIR.mkdir(exist_ok=True)


def load_config(path: Path = REPO_CONFIG) -> dict:
    if not path.exists():
        alt = Path.cwd() / "repositories.json"
        if alt.exists(): path = alt
        else: raise FileNotFoundError(f"repositories.json not found at {REPO_CONFIG} or {alt}")
    with open(path, "r", encoding="utf-8") as f: return json.load(f)


def create_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    a = requests.adapters.HTTPAdapter(max_retries=requests.adapters.Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]))
    s.mount("http://", a); s.mount("https://", a)
    return s


def safe_get(session: requests.Session, url: str, params: dict = None, timeout: int = 20) -> Optional[requests.Response]:
    try:
        r = session.get(url, params=params, timeout=timeout, allow_redirects=True)
        r.raise_for_status(); return r
    except requests.exceptions.SSLError:
        try:
            import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = session.get(url, params=params, timeout=timeout, verify=False, allow_redirects=True)
            r.raise_for_status(); return r
        except Exception: return None
    except Exception: return None


def _cache_key(url: str, params: dict = None) -> str:
    return hashlib.md5((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()


def cache_get(url: str, params: dict = None) -> Optional[str]:
    p = CACHE_DIR / f"{_cache_key(url, params)}.cache"
    if p.exists() and (time.time() - p.stat().st_mtime) < 86400: return p.read_text(encoding="utf-8", errors="ignore")
    return None


def cache_set(url: str, params: dict, content: str):
    try: (CACHE_DIR / f"{_cache_key(url, params)}.cache").write_text(content, encoding="utf-8")
    except Exception: pass


def fetch_with_cache(session: requests.Session, url: str, params: dict = None) -> Optional[str]:
    c = cache_get(url, params)
    if c: return c
    r = safe_get(session, url, params)
    if r: cache_set(url, params or {}, r.text); return r.text
    return None


def oai_request(session: requests.Session, base_url: str, verb: str, params: dict = None) -> Optional[ET.Element]:
    qp = {"verb": verb}
    if params: qp.update(params)
    r = safe_get(session, base_url, qp)
    if not r: return None
    try: return ET.fromstring(r.content)
    except ET.ParseError: return None


def _oai_text(meta: ET.Element, tag: str, all_vals: bool = False) -> str:
    ns = tag.replace("dc:", "{http://purl.org/dc/elements/1.1/}")
    els = meta.findall(ns)
    if not els: return ""
    return " ".join(e.text or "" for e in els) if all_vals else (els[0].text or "").strip()


def oai_search(session: requests.Session, oai_url: str, keyword: str, max_records: int = 30) -> list[Skripsi]:
    results: list[Skripsi] = []
    token, total_fetched = None, 0
    while total_fetched < max_records * 10:
        root = oai_request(session, oai_url, "ListRecords",
                           {"resumptionToken": token} if token else {"metadataPrefix": "oai_dc"})
        if root is None or root.find(".//oai:error", OAI_NS) is not None: break
        records = root.findall(".//oai:record", OAI_NS)
        total_fetched += len(records)
        for rec in records:
            meta = rec.find(".//oai_dc:dc", OAI_NS) or rec.find(".//oai:metadata/*", OAI_NS)
            if meta is None: continue
            title = _oai_text(meta, "dc:title")
            if not title: continue
            author, date_str = _oai_text(meta, "dc:creator"), _oai_text(meta, "dc:date")
            abstract, subject = _oai_text(meta, "dc:description"), _oai_text(meta, "dc:subject")
            types = _oai_text(meta, "dc:type", all_vals=True)
            if keyword.lower() not in f"{title} {abstract} {subject}".lower(): continue
            ids = [el.text or "" for el in meta.findall("dc:identifier", OAI_NS)]
            url_detail = next((i for i in ids if i.startswith("http")), "")
            url_pdf = next((i for i in ids if ".pdf" in i.lower()), "")
            year = re.search(r"\b(19|20)\d{2}\b", date_str).group() if date_str and re.search(r"\b(19|20)\d{2}\b", date_str) else ""
            score, chs = compute_score(f"{title} {abstract} {subject} {types}")
            results.append(Skripsi(universitas="", kode_univ="", judul=title, penulis=author, tahun=year,
                        abstrak=abstract[:300] if abstract else "", url_detail=url_detail, url_pdf=url_pdf,
                        status_full_text=determine_status(score), skor_full_text=score, bab_terdeteksi=chs, metode_fetch="oai"))
            if len(results) >= max_records: break
        if len(results) >= max_records: break
        te = root.find(".//oai:resumptionToken", OAI_NS)
        if te is not None and te.text: token = te.text
        else: break
    return results


def _extract_year(text: str) -> str:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return m.group() if m else ""


def parser_eprints(soup: BeautifulSoup, base_url: str) -> list[dict]:
    items: list[dict] = []
    containers = (soup.find_all("div", class_=re.compile(r"ep_search_result|ep_block"))
                  or soup.find_all("li", class_=re.compile(r"summary_item"))
                  or soup.find_all("tr", class_=re.compile(r"ep_search")) or [])
    if containers:
        for c in containers:
            link = c.find("a", href=True)
            if not link: continue
            title = link.get_text(strip=True)
            if len(title) < 8: continue
            pe = c.find(class_=re.compile(r"creator|author|ep_name"))
            author = pe.get_text(strip=True) if pe else ""
            items.append({"judul": title, "url": urljoin(base_url, link["href"]), "penulis": author, "tahun": _extract_year(c.get_text())})
    else:
        for a in soup.find_all("a", href=re.compile(r"/\d+/?$")):
            t = a.get_text(strip=True)
            if len(t) >= 8: items.append({"judul": t, "url": urljoin(base_url, a["href"]), "penulis": "", "tahun": ""})
    return items[:25]


def parser_dspace(soup: BeautifulSoup, base_url: str) -> list[dict]:
    items: list[dict] = []
    containers = (soup.find_all("div", class_=re.compile(r"artifact-description|ds-artifact"))
                  or soup.find_all("li", class_=re.compile(r"ds-artifact|search-result")) or [])
    if containers:
        for c in containers:
            tt = c.find(class_=re.compile(r"artifact-title|ds-title")) or c.find("a", href=re.compile(r"/handle/"))
            if not tt: continue
            link = tt if tt.name == "a" else tt.find("a")
            if not link: continue
            items.append({"judul": tt.get_text(strip=True), "url": urljoin(base_url, link["href"]), "penulis": "", "tahun": _extract_year(c.get_text())})
    else:
        for a in soup.find_all("a", href=re.compile(r"/handle/")):
            t = a.get_text(strip=True)
            if len(t) >= 8: items.append({"judul": t, "url": urljoin(base_url, a["href"]), "penulis": "", "tahun": ""})
    return items[:25]


def parser_senayan(soup: BeautifulSoup, base_url: str) -> list[dict]:
    items: list[dict] = []
    for row in soup.find_all("div", class_=re.compile(r"book|result")):
        link = row.find("a", href=True)
        if not link: continue
        t = link.get_text(strip=True)
        if len(t) >= 8: items.append({"judul": t, "url": urljoin(base_url, link["href"]), "penulis": "", "tahun": _extract_year(row.get_text())})
    return items[:25]


def parser_generic(soup: BeautifulSoup, base_url: str) -> list[dict]:
    items, seen = [], set()
    src = soup.find_all(True, class_=re.compile(r"result|item|entry|record|thesis|skripsi|tugas.?akhir", re.I)) or [soup]
    for s in src:
        for a in s.find_all("a", href=True):
            h, t = a["href"], a.get_text(strip=True)
            if len(t) < 12 or h in seen or any(x in h.lower() for x in ["javascript", "mailto", "login", "#", "logout"]) or any(x in t.lower() for x in ["home", "login", "search", "daftar", "menu", "contact"]): continue
            seen.add(h); items.append({"judul": t, "url": urljoin(base_url, h), "penulis": "", "tahun": ""})
    return items[:20]


PARSERS_HTML = {"eprints": parser_eprints, "dspace": parser_dspace, "senayan": parser_senayan,
                "slims": parser_senayan, "generic": parser_generic, "gdl_itb": parser_generic,
                "ui_lontar": parser_generic, "binus": parser_generic}


def extract_pdf_from_detail(soup: BeautifulSoup, base_url: str) -> tuple[str, str, str]:
    all_pdf: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not (".pdf" in href.lower() or re.search(r"/bitstream/|/retrieve/|/download/", href, re.I)): continue
        label = a.get_text(strip=True)
        if not label:
            pt = a.find_parent("td")
            if pt: label = pt.get_text(separator=" ", strip=True)
        size_kb = 0
        parent = a.find_parent(["tr", "li", "div"])
        if parent:
            m = re.search(r"([\d.,]+)\s*(Kb|KB|Mb|MB|Gb|GB)", parent.get_text(separator=" "))
            if m:
                v, u = float(m.group(1).replace(",", ".")), m.group(2).upper()
                size_kb = v if "KB" in u else v * 1024 if "MB" in u else v * 1024 * 1024
        u = urljoin(base_url, href)
        all_pdf.append({"url": u, "label": label, "size_kb": size_kb,
                        "is_cover": bool(COVER_PATTERN.search(label) or COVER_PATTERN.search(href)),
                        "is_fulltext": bool(FULLTEXT_PATTERN.search(label) or FULLTEXT_PATTERN.search(href))})
    if not all_pdf: return "", "", ""
    cover_url = next((p["url"] for p in all_pdf if p["is_cover"]), "")
    cands = [p for p in all_pdf if p["is_fulltext"]] or [p for p in all_pdf if not p["is_cover"]] or all_pdf
    cands.sort(key=lambda p: p["size_kb"], reverse=True)
    note = f"Found {len(all_pdf)} PDF files; cover separated from fulltext" if len(all_pdf) > 1 and cover_url else ""
    return cands[0]["url"], cover_url, note


def check_pdf_access(session: requests.Session, pdf_url: str, timeout: int = 10) -> tuple[bool, str]:
    if not pdf_url: return False, "Empty URL"
    try:
        resp = session.head(pdf_url, timeout=timeout, allow_redirects=True)
        for r in resp.history:
            if LOGIN_REDIRECT_PATTERN.search(r.headers.get("Location", "")): return False, "Redirected to login"
        if LOGIN_REDIRECT_PATTERN.search(resp.url): return False, "Final URL contains login pattern"
        if resp.status_code in STATUS_LOCKED: return False, f"HTTP {resp.status_code} — access denied"
        ct = resp.headers.get("Content-Type", "").lower()
        if resp.status_code == 200:
            if "application/pdf" in ct or "octet-stream" in ct: return True, "OK"
            if "text/html" in ct:
                try:
                    rg = session.get(pdf_url, timeout=timeout, stream=True, allow_redirects=True)
                    chunk = b""
                    for c in rg.iter_content(2048): chunk += c; break
                    rg.close()
                    t = chunk.decode("utf-8", errors="ignore").lower()
                    if LOGIN_REDIRECT_PATTERN.search(t) or re.search(r"<form.*?login|input.*?password", t): return False, "Login page"
                    if t.startswith("%pdf"): return True, "OK"
                except Exception: pass
                return False, "Server returned HTML, not PDF"
            return True, f"OK ({ct})"
        return False, f"HTTP {resp.status_code}"
    except requests.exceptions.SSLError:
        try:
            import urllib3; urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = session.head(pdf_url, timeout=timeout, allow_redirects=True, verify=False)
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "").lower()
                if "pdf" in ct or "octet" in ct: return True, "OK (SSL ignored)"
            return False, f"SSL error, HTTP {resp.status_code}"
        except Exception as e: return False, f"SSL error: {e}"
    except requests.exceptions.Timeout: return False, "Timeout"
    except Exception as e: return False, f"Error: {e}"


class ThesisSearcher:
    def __init__(self, delay: float = 1.2, use_cache: bool = True, max_workers: int = 3):
        self.session = create_session()
        self.delay = delay
        self.use_cache = use_cache
        self.max_workers = max_workers
        self._config = load_config()

    def list_universities(self, univ_type: str = None, province: str = None) -> list[dict]:
        unis = self._config["universitas"]
        if univ_type: unis = [u for u in unis if u["tipe"].lower() == univ_type.lower()]
        if province: unis = [u for u in unis if province.lower() in u["provinsi"].lower()]
        return unis

    def search_one_university(self, univ: dict, keyword: str, max_results: int = 20, method: str = "auto") -> list[Skripsi]:
        results: list[Skripsi] = []
        if method in ("auto", "oai") and univ.get("oai_endpoint"):
            time.sleep(self.delay * 0.5)
            try:
                records = oai_search(self.session, univ["oai_endpoint"], keyword, max_records=max_results)
                for r in records: r.universitas = univ["nama"]; r.kode_univ = univ["id"]
                results.extend(records)
            except Exception as e: log.warning("OAI failed for %s: %s", univ["id"], e)
        if not results and method != "oai":
            time.sleep(self.delay)
            params = {k: v.replace("{keyword}", keyword) for k, v in univ["search_params"].items()}
            html = fetch_with_cache(self.session, univ["search_url"], params) if self.use_cache else None
            if html is None:
                resp = safe_get(self.session, univ["search_url"], params)
                if resp: html = resp.text
            if not html: return []
            soup = BeautifulSoup(html, "lxml")
            parser_fn = PARSERS_HTML.get(univ["parser"], parser_generic)
            for item in parser_fn(soup, univ["url_base"])[:max_results]:
                if not item.get("url"): continue
                time.sleep(self.delay * 0.7)
                dh = fetch_with_cache(self.session, item["url"]) if self.use_cache else None
                if dh is None:
                    dr = safe_get(self.session, item["url"])
                    if dr: dh = dr.text
                score, chs = (0, []); pdf_url = ""; pdf_note = ""; pdf_analysis = None
                if dh:
                    ds = BeautifulSoup(dh, "lxml"); score, chs = compute_score(ds.get_text())
                    pdf_url, _, pdf_note = extract_pdf_from_detail(ds, univ["url_base"])
                    if pdf_url and PDFMINER_AVAILABLE:
                        pdf_analysis = analyze_full(self.session, pdf_url, ds, univ["url_base"], self.delay * 0.4)
                        if pdf_analysis.status == "locked": score -= 8; pdf_note = f"Locked: {pdf_analysis.technical_note}"; pdf_url = ""
                        elif pdf_analysis.status == "full": score += 20; chs = pdf_analysis.chapters_from_pdf or chs
                        elif pdf_analysis.status == "partial": score += 10; chs = pdf_analysis.chapters_from_pdf or chs
                        else: score += 5
                    elif pdf_url:
                        ok, reason = check_pdf_access(self.session, pdf_url)
                        if ok: score += 5
                        else: score -= 8; pdf_note = f"Locked: {reason}"; pdf_url = ""
                status = determine_status(score)
                if not pdf_url and pdf_note and "locked" in pdf_note.lower() and status != "locked": status = "locked"
                results.append(Skripsi(
                    universitas=univ["nama"], kode_univ=univ["id"], judul=item["judul"],
                    penulis=item.get("penulis", ""), tahun=item.get("tahun", ""),
                    url_detail=item["url"], url_pdf=pdf_url, status_full_text=status,
                    skor_full_text=score, bab_terdeteksi=chs, metode_fetch="html",
                    catatan=" | ".join(filter(None, [pdf_note])),
                    pdf_analisis_status=pdf_analysis.status if pdf_analysis else "",
                    bab_pdf=pdf_analysis.chapters_from_pdf if pdf_analysis else [],
                    url_per_bab=pdf_analysis.url_per_chapter if pdf_analysis else {},
                    bab_terkunci=pdf_analysis.locked_chapters if pdf_analysis else [],
                    estimasi_halaman=pdf_analysis.estimated_pages if pdf_analysis else 0,
                    pdf_analisis_catatan=pdf_analysis.technical_note if pdf_analysis else "",
                ))
        return results

    def search_many(self, keyword: str, id_list: list[str] = None, univ_type: str = None,
                    province: str = None, max_per_univ: int = 10, method: str = "auto",
                    only_full: bool = False, on_progress: Callable = None) -> list[Skripsi]:
        unis = self.list_universities(univ_type, province)
        if id_list: unis = [u for u in unis if u["id"] in id_list]
        all_results: list[Skripsi] = []
        completed, total = 0, len(unis)
        def _worker(u):
            try: return self.search_one_university(u, keyword, max_per_univ, method)
            except Exception: return []
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            fs = {ex.submit(_worker, u): u for u in unis}
            for f in fs:
                try: all_results.extend(f.result(timeout=60))
                except Exception: pass
                completed += 1
                if on_progress: on_progress(completed, total, fs[f]["id"])
        if only_full: all_results = [h for h in all_results if h.status_full_text in ("full", "partial")]
        all_results.sort(key=lambda x: ({"full": 0, "partial": 1, "unknown": 2, "locked": 3}.get(x.status_full_text, 3), -x.skor_full_text))
        return all_results
