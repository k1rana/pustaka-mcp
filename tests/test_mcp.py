"""Tests for pustaka."""

import re
import pytest

from pustaka.models import (
    Skripsi, compute_score, determine_status,
    SCORE_INDICATORS, THRESHOLD_FULL, THRESHOLD_PARTIAL,
)
from pustaka.pdf_analyzer import (
    PdfAnalysisResult, detect_chapters_from_text, estimate_pages,
    determine_status_from_chapters, classify_pdfs_per_chapter,
    format_chapter_list, REQUIRED_CHAPTERS,
)
from pustaka.engine import (
    ThesisSearcher, load_config, _extract_year,
)
from pustaka import __version__


def test_version():
    assert __version__ == "2.0.0"


class TestScoring:
    def test_full_text_detected(self):
        s, ch = compute_score("full text download pdf lengkap bab 1 bab 2 bab 3 bab 4 bab 5 daftar pustaka")
        assert s >= THRESHOLD_FULL
        assert "daftar pustaka" in ch

    def test_locked_detected(self):
        s, ch = compute_score("restricted campus only please login to view")
        assert s < 0

    def test_partial(self):
        s, ch = compute_score("metodologi penelitian tinjauan pustaka")
        assert THRESHOLD_PARTIAL <= s < THRESHOLD_FULL

    def test_empty(self):
        s, ch = compute_score("")
        assert s == 0 and ch == []

    def test_status_full(self):
        assert determine_status(15) == "full"
        assert determine_status(20) == "full"

    def test_status_partial(self):
        assert determine_status(5) == "partial"
        assert determine_status(10) == "partial"

    def test_status_locked(self):
        assert determine_status(-1) == "locked"
        assert determine_status(-10) == "locked"

    def test_status_unknown(self):
        assert determine_status(0) == "unknown"
        assert determine_status(3) == "unknown"


class TestChapterDetection:
    def test_detect_intro(self):
        ch = detect_chapters_from_text("BAB I PENDAHULUAN\nLatar Belakang")
        assert "chapter 1 - introduction" in ch

    def test_detect_all(self):
        ch = detect_chapters_from_text("""
        BAB I PENDAHULUAN
        BAB II TINJAUAN PUSTAKA
        BAB III METODOLOGI PENELITIAN
        BAB IV HASIL DAN PEMBAHASAN
        BAB V KESIMPULAN
        DAFTAR PUSTAKA
        """)
        assert len(ch) >= 6

    def test_empty(self):
        assert detect_chapters_from_text("") == []
        assert detect_chapters_from_text(None) == []

    def test_estimate_pages(self):
        assert estimate_pages("kata " * 500) == 2
        assert estimate_pages("") == 0

    def test_status_from_chapters_full(self):
        ch = ["chapter 1 - introduction", "chapter 3 - methodology",
              "chapter 4 - results", "chapter 5 - conclusion", "bibliography"]
        assert determine_status_from_chapters(ch) == "full"

    def test_status_from_chapters_partial(self):
        ch = ["chapter 1 - introduction", "chapter 3 - methodology", "table of contents"]
        assert determine_status_from_chapters(ch) == "partial"

    def test_status_from_chapters_unknown(self):
        assert determine_status_from_chapters(["cover/title"]) == "unknown"
        assert determine_status_from_chapters([]) == "unknown"


class TestPdfAnalysisResult:
    def test_summary_full(self):
        r = PdfAnalysisResult(status="full", chapters_from_pdf=["ch1", "ch3", "ch4", "ch5", "bib"])
        assert "Full" in r.summary

    def test_summary_locked(self):
        r = PdfAnalysisResult(status="locked")
        assert "Locked" in r.summary

    def test_all_chapters_dedup(self):
        r = PdfAnalysisResult(chapters_from_pdf=["ch1", "ch3"], chapters_from_filename=["ch1", "ch3", "ch5"])
        assert r.all_chapters == ["ch1", "ch3", "ch5"]


class TestFormatChapter:
    def test_normal(self):
        assert "ch1 → ch2" in format_chapter_list(["ch1", "ch2"])

    def test_truncated(self):
        r = format_chapter_list([f"ch{i}" for i in range(10)], max_show=3)
        assert "+7 more" in r

    def test_empty(self):
        assert format_chapter_list([]) == "(none)"


class TestClassifyMultiFile:
    def test_classify(self):
        r = classify_pdfs_per_chapter([
            {"url": "http://repo.ac.id/cover.pdf", "label": "Cover"},
            {"url": "http://repo.ac.id/bab1.pdf", "label": "Bab 1"},
            {"url": "http://repo.ac.id/bab3.pdf", "label": "Bab 3"},
        ])
        assert "chapter 1 - introduction" in r
        assert "cover/title" in r

    def test_empty(self):
        assert classify_pdfs_per_chapter([]) == {}


class TestEngine:
    def test_load_config(self):
        config = load_config()
        assert "universitas" in config
        assert len(config["universitas"]) > 0

    def test_extract_year(self):
        assert _extract_year("Thesis 2023") == "2023"
        assert _extract_year("no year") == ""

    def test_searcher_init(self):
        s = ThesisSearcher(delay=0.1, max_workers=1)
        assert s.delay == 0.1 and s.max_workers == 1 and s.session is not None

    def test_list_universities_filter_type(self):
        s = ThesisSearcher(delay=0.1, max_workers=1)
        ptn = s.list_universities(univ_type="PTN")
        assert len(ptn) > 0 and all(u["tipe"] == "PTN" for u in ptn)

    def test_list_universities_filter_province(self):
        s = ThesisSearcher(delay=0.1, max_workers=1)
        jatim = s.list_universities(province="jawa timur")
        assert len(jatim) > 0 and all("jawa timur" in u["provinsi"].lower() for u in jatim)

    def test_list_universities_empty(self):
        s = ThesisSearcher(delay=0.1, max_workers=1)
        assert s.list_universities(univ_type="NONEXIST") == []


class TestSkripsi:
    def test_to_dict(self):
        s = Skripsi(universitas="Test", kode_univ="t", judul="Judul")
        d = s.to_dict()
        assert d["universitas"] == "Test" and d["judul"] == "Judul" and d["status_full_text"] == "unknown"

    def test_timestamp(self):
        s = Skripsi(universitas="X", kode_univ="x", judul="Y")
        assert s.timestamp_cari


class TestEdgeCases:
    def test_skripsi_defaults(self):
        s = Skripsi(universitas="A", kode_univ="a", judul="B")
        assert s.penulis == "" and s.tahun == "" and s.abstrak == "" and s.url_detail == ""

    def test_all_regex_valid(self):
        for pat in SCORE_INDICATORS:
            try: re.compile(pat)
            except re.error as e: pytest.fail(f"Invalid regex: {pat!r} — {e}")


def test_required_chapters_in_patterns():
    from pustaka.pdf_analyzer import CHAPTER_PATTERNS
    names = {n for n, _ in CHAPTER_PATTERNS}
    for w in REQUIRED_CHAPTERS:
        assert w in names, f"REQUIRED_CHAPTERS '{w}' not in CHAPTER_PATTERNS"