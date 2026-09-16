"""Data models and constants for thesis full-text detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

# ── Score weights ────────────────────────────────────────────────────

SCORE_INDICATORS: dict[str, int] = {
    "full.?text":               +10,
    "open.?access":             +8,
    "download.*pdf":            +7,
    "unduh.*lengkap":           +7,
    r"bab\s+[1-9].*bab\s+[2-9]": +9,
    "kesimpulan":               +5,
    "daftar.*pustaka":          +5,
    "metodologi.*penelitian":   +4,
    "tinjauan.*pustaka":        +4,
    "pembahasan":               +4,
    "pdf":                      +3,
    "restricted":               -10,
    "embargo":                  -10,
    r"hanya\s+bab\s+[1i]":     -9,
    "campus.?only":             -9,
    "akses.*terbatas":          -8,
    "login.*untuk.*download":   -8,
    r"bab\s+[1i]\s+saja":       -8,
    "not.*available":           -7,
    "access.*denied":           -7,
    "under.*embargo":           -7,
    r"please.*login.*view":     -10,
    r"login.*to.*access":       -10,
    r"you.*must.*log.*in":      -10,
    "authorization required":   -10,
    "please login":             -9,
    "silakan login":            -9,
    "sign in to":               -9,
}

THRESHOLD_FULL = 15
THRESHOLD_PARTIAL = 5

CHAPTER_KEYWORDS = [
    "pendahuluan", "latar belakang", "tinjauan pustaka", "kajian pustaka",
    "landasan teori", "kerangka teori", "metodologi", "metode penelitian",
    "hasil penelitian", "pembahasan", "analisis data", "kesimpulan",
    "penutup", "saran", "daftar pustaka", "referensi", "daftar isi",
    "chapter 1", "chapter 2", "chapter 3", "chapter 4", "chapter 5",
    "bab i", "bab ii", "bab iii", "bab iv", "bab v",
]

COVER_PATTERN = re.compile(
    r"cover|sampul|halaman.?judul|title.?page|hal\.?judul|cover\.pdf",
    re.IGNORECASE,
)

FULLTEXT_PATTERN = re.compile(
    r"full.?text|fulltext|full_text|naskah.?lengkap|skripsi.?full|"
    r"tesis.?full|disertasi.?full|manuscript|document\.pdf|full\.pdf",
    re.IGNORECASE,
)

LOGIN_REDIRECT_PATTERN = re.compile(
    r"login|signin|sign.in|shibboleth|cas\.(?:ac|edu|go)\.id|"
    r"auth\..*redirect|/account/|/user/login",
    re.IGNORECASE,
)

STATUS_LOCKED = {401, 403}

OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SkripsiSearchBot/1.2; "
        "+https://github.com/pencari-skripsi-id)"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}


@dataclass
class Skripsi:
    """Thesis entry from a university repository."""
    universitas: str
    kode_univ: str
    judul: str
    penulis: str = ""
    tahun: str = ""
    abstrak: str = ""
    program_studi: str = ""
    url_detail: str = ""
    url_pdf: str = ""
    doi: str = ""
    status_full_text: str = "unknown"
    skor_full_text: int = 0
    bab_terdeteksi: list = field(default_factory=list)
    metode_fetch: str = "html"
    catatan: str = ""
    timestamp_cari: str = field(default_factory=lambda: datetime.now().isoformat())
    pdf_analisis_status: str = ""
    bab_pdf: list = field(default_factory=list)
    url_per_bab: dict = field(default_factory=dict)
    bab_terkunci: list = field(default_factory=list)
    estimasi_halaman: int = 0
    pdf_analisis_catatan: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Scoring helpers ──────────────────────────────────────────────────

def compute_score(text: str) -> tuple[int, list[str]]:
    text_lower = text.lower()
    score = 0
    for pattern, weight in SCORE_INDICATORS.items():
        if re.search(pattern, text_lower):
            score += weight
    chapters = [kw for kw in CHAPTER_KEYWORDS if kw in text_lower]
    if len(chapters) >= 6:
        score += 8
    elif len(chapters) >= 4:
        score += 4
    return score, chapters


def determine_status(score: int) -> str:
    if score >= THRESHOLD_FULL:
        return "full"
    if score >= THRESHOLD_PARTIAL:
        return "partial"
    if score < 0:
        return "locked"
    return "unknown"
