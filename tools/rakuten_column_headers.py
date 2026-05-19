# -*- coding: utf-8 -*-
"""
Rakuten bulk-edit CSV: Japanese display headers and aliases for merge (UTF-8 in file;
this module is ASCII-only via \\u escapes).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional, Tuple

# Rakuten bulk upload: filename must start with normal-item_ (e.g. normal-item_upload.csv)
RAKUTEN_UPLOAD_NAME_PREFIX = "normal-item_"
DEFAULT_RAKUTEN_UPLOAD_SUFFIX = "upload"

# Rakuten RMS download (before 抽出 / マージ source)
RAKUTEN_DOWNLOAD_GLOB = "dl-normal-item_*.csv"
RAKUTEN_DOWNLOAD_EXAMPLE = "dl-normal-item_20260519091441.csv"

# Extract step output (edit in Excel/Sheets) — not the Rakuten dl-normal-item_*.csv download name
EXTRACT_EDIT_BASENAME = "mae_edit"
EXTRACT_EDIT_GLOB = f"{EXTRACT_EDIT_BASENAME}_*.csv"

# --- Rakuten source CSV column names (must match download) ---
# 商品管理番号（商品URL）
ITEM_CODE_RAKUTEN = "\u5546\u54c1\u7ba1\u7406\u756a\u53f7\uff08\u5546\u54c1\u0055\u0052\u004c\uff09"
# スマートフォン用商品説明文
SP_COL_RAKUTEN = "\u30b9\u30de\u30fc\u30c8\u30d5\u30a9\u30f3\u7528\u5546\u54c1\u8aac\u660e\u6587"
# PC用販売説明文
PC_COL_RAKUTEN = "\u0050\u0043\u7528\u8ca9\u58f2\u8aac\u660e\u6587"

# --- Extract/merge flat edit sheet: minimal fields ---
H_CODE = "\u5546\u54c1\u7ba1\u7406\u756a\u53f7"
H_P1_CODE = "\u5546\u54c1\u0031\u005f\u5546\u54c1\u7ba1\u7406\u756a\u53f7"
H_P1_NAME = "\u5546\u54c1\u0031\u005f\u5546\u54c1\u540d"
H_P1_IMG = "\u5546\u54c1\u0031\u005f\u753b\u50cf\u30d1\u30b9"
H_P2_CODE = "\u5546\u54c1\u0032\u005f\u5546\u54c1\u7ba1\u7406\u756a\u53f7"
H_P2_NAME = "\u5546\u54c1\u0032\u005f\u5546\u54c1\u540d"
H_P2_IMG = "\u5546\u54c1\u0032\u005f\u753b\u50cf\u30d1\u30b9"

# First column mojibake we used to write by mistake; still in some saved CSVs
LEGACY_MANGLED_CODE_HEADER = "???i??????"

# Internal keys used in merge logic (after normalization)
K_CODE = "code"
K_P1_CODE = "p1_code"
K_P1_NAME = "p1_name"
K_P1_IMG = "p1_img"
K_P2_CODE = "p2_code"
K_P2_NAME = "p2_name"
K_P2_IMG = "p2_img"

# Order of (internal_key, Japanese header) for extract CSV columns
EXTRACT_ORDER: List[Tuple[str, str]] = [
    (K_CODE, H_CODE),
    (K_P1_CODE, H_P1_CODE),
    (K_P1_NAME, H_P1_NAME),
    (K_P1_IMG, H_P1_IMG),
    (K_P2_CODE, H_P2_CODE),
    (K_P2_NAME, H_P2_NAME),
    (K_P2_IMG, H_P2_IMG),
]

# Map any known CSV header (Japanese, English, legacy) -> internal key
def _build_alias_to_canonical() -> Dict[str, str]:
    m: Dict[str, str] = {}
    for k, h in EXTRACT_ORDER:
        m[k] = k
        m[h] = k
    # Backward compatible aliases for old edit files.
    m["pc_product1_href"] = K_P1_CODE
    m["pc_product1_alt"] = K_P1_NAME
    m["pc_product1_img_src"] = K_P1_IMG
    m["pc_product2_href"] = K_P2_CODE
    m["pc_product2_alt"] = K_P2_NAME
    m["pc_product2_img_src"] = K_P2_IMG
    m["sp_product1_href"] = K_P1_CODE
    m["sp_product1_alt"] = K_P1_NAME
    m["sp_product1_img_src"] = K_P1_IMG
    m["sp_product2_href"] = K_P2_CODE
    m["sp_product2_alt"] = K_P2_NAME
    m["sp_product2_img_src"] = K_P2_IMG
    # Previous Japanese headers used before this simplification.
    m["\u0050\u0043\u005f\u5546\u54c1\u0031\u005f\u5546\u54c1\u30da\u30fc\u30b8\u0055\u0052\u004c"] = K_P1_CODE
    m["\u0050\u0043\u005f\u5546\u54c1\u0031\u005f\u4ee3\u66ff\u30c6\u30ad\u30b9\u30c8"] = K_P1_NAME
    m["\u0050\u0043\u005f\u5546\u54c1\u0031\u005f\u753b\u50cf\u0055\u0052\u004c"] = K_P1_IMG
    m["\u0050\u0043\u005f\u5546\u54c1\u0032\u005f\u5546\u54c1\u30da\u30fc\u30b8\u0055\u0052\u004c"] = K_P2_CODE
    m["\u0050\u0043\u005f\u5546\u54c1\u0032\u005f\u4ee3\u66ff\u30c6\u30ad\u30b9\u30c8"] = K_P2_NAME
    m["\u0050\u0043\u005f\u5546\u54c1\u0032\u005f\u753b\u50cf\u0055\u0052\u004c"] = K_P2_IMG
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0031\u005f\u5546\u54c1\u30da\u30fc\u30b8\u0055\u0052\u004c"] = K_P1_CODE
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0031\u005f\u4ee3\u66ff\u30c6\u30ad\u30b9\u30c8"] = K_P1_NAME
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0031\u005f\u753b\u50cf\u0055\u0052\u004c"] = K_P1_IMG
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0032\u005f\u5546\u54c1\u30da\u30fc\u30b8\u0055\u0052\u004c"] = K_P2_CODE
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0032\u005f\u4ee3\u66ff\u30c6\u30ad\u30b9\u30c8"] = K_P2_NAME
    m["\u30b9\u30de\u30db\u005f\u5546\u54c1\u0032\u005f\u753b\u50cf\u0055\u0052\u004c"] = K_P2_IMG
    m[ITEM_CODE_RAKUTEN] = K_CODE
    m[LEGACY_MANGLED_CODE_HEADER] = K_CODE
    return m


ALIAS_TO_CANONICAL: Dict[str, str] = _build_alias_to_canonical()

CANONICAL_EDIT_KEYS: List[str] = [k for k, _ in EXTRACT_ORDER]


def normalize_edit_row_header(key: str) -> str:
    """Map one DictReader column name to internal key, or '' if unknown."""
    s = (key or "").lstrip("\ufeff").strip()
    return ALIAS_TO_CANONICAL.get(s) or s


def normalize_edit_row(row: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_k, v in row.items():
        ck = normalize_edit_row_header(raw_k)
        if ck in CANONICAL_EDIT_KEYS:
            out[ck] = (v or "").strip()
    return out


def extract_fieldnames_ja() -> List[str]:
    return [h for _k, h in EXTRACT_ORDER]


def extract_edit_filename(for_date: Optional[date] = None) -> str:
    """Flat edit sheet after 抽出 (UTF-8), e.g. mae_edit_20260519.csv."""
    d = for_date or date.today()
    return f"{EXTRACT_EDIT_BASENAME}_{d.strftime('%Y%m%d')}.csv"


def rakuten_source_csv_label() -> str:
    """File uploader label for the original Rakuten download CSV."""
    return f"\u5143\u0043\u0053\u0056\uff08{RAKUTEN_DOWNLOAD_GLOB}\uff09"


def rakuten_upload_filename(suffix: str = DEFAULT_RAKUTEN_UPLOAD_SUFFIX) -> str:
    """Build a Rakuten-compatible upload CSV name: normal-item_<suffix>.csv"""
    raw = (suffix or DEFAULT_RAKUTEN_UPLOAD_SUFFIX).strip()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", raw) or DEFAULT_RAKUTEN_UPLOAD_SUFFIX
    return f"{RAKUTEN_UPLOAD_NAME_PREFIX}{safe}.csv"
