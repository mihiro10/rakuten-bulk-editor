#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import streamlit as st

ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rakuten_column_headers import ITEM_CODE_RAKUTEN, PC_COL_RAKUTEN, SP_COL_RAKUTEN
from rakuten_html_bulk_editor import parse_two_product_block, run_extract, run_merge

IMAGE_PREVIEW_BASE = os.environ.get(
    "RAKUTEN_IMAGE_PREVIEW_BASE",
    "https://image.rakuten.co.jp/chikuya/cabinet/",
)
IMAGE_COLS = {"商品1_画像パス", "商品2_画像パス"}
# Bump when deploying so users can confirm Streamlit Cloud picked up the build.
APP_VERSION = "2026-05-19-preview-encoding"


def _decode_csv_bytes(data: bytes) -> str:
    """Match Rakuten + tool output: UTF-8 (edit sheet) or Shift_JIS (merge upload file)."""
    for enc in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_csv_rows(data: bytes, max_rows: int = 200) -> List[List[str]]:
    text = _decode_csv_bytes(data)
    out: List[List[str]] = []
    for i, row in enumerate(csv.reader(io.StringIO(text))):
        if i >= max_rows:
            break
        out.append(row)
    return out


def _to_abs_image_url(path_or_url: str) -> str:
    s = (path_or_url or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://") or low.startswith("//"):
        return s
    return IMAGE_PREVIEW_BASE.rstrip("/") + "/" + s.lstrip("/")


def _resolve_rakuten_col_indices(header: List[str]) -> Optional[Tuple[int, int, int]]:
    name_to_idx = {name: i for i, name in enumerate(header)}
    code_i = name_to_idx.get(ITEM_CODE_RAKUTEN)
    sp_i = name_to_idx.get(SP_COL_RAKUTEN)
    pc_i = name_to_idx.get(PC_COL_RAKUTEN)
    if code_i is not None and sp_i is not None and pc_i is not None:
        return code_i, sp_i, pc_i
    return None


def _render_image_preview(p1: str, p2: str, p1_name: str = "", p2_name: str = "") -> None:
    c1, c2 = st.columns(2)
    with c1:
        label = f"商品1: {p1_name}" if p1_name else "商品1"
        st.caption(f"{label} — {p1}" if p1 else label)
        u1 = _to_abs_image_url(p1)
        if u1:
            st.image(u1, use_container_width=True)
    with c2:
        label = f"商品2: {p2_name}" if p2_name else "商品2"
        st.caption(f"{label} — {p2}" if p2 else label)
        u2 = _to_abs_image_url(p2)
        if u2:
            st.image(u2, use_container_width=True)


def _preview_rakuten_html_images(data: bytes, max_items: int = 20) -> None:
    """Parse SP/PC HTML (full file) and show thumbnails for primary product rows."""
    rows = _read_csv_rows(data, max_rows=5000)
    if len(rows) < 2:
        return
    header = rows[0]
    body = rows[1:]
    rakuten_cols = _resolve_rakuten_col_indices(header)
    if not rakuten_cols or not body:
        return
    code_i, sp_i, pc_i = rakuten_cols
    st.markdown("#### 画像プレビュー（HTMLから抽出）")
    shown = 0
    seen_codes: set[str] = set()
    for r in body:
        if shown >= max_items:
            break
        if code_i >= len(r):
            continue
        code = (r[code_i] or "").strip()
        if not code or code in seen_codes:
            continue
        sp_html = r[sp_i] if sp_i < len(r) else ""
        pc_html = r[pc_i] if pc_i < len(r) else ""
        parsed = parse_two_product_block(pc_html) or parse_two_product_block(sp_html)
        if not parsed:
            continue
        seen_codes.add(code)
        st.caption(f"商品管理番号: {code}")
        _render_image_preview(
            parsed.p1.img_src,
            parsed.p2.img_src,
            parsed.p1.alt,
            parsed.p2.alt,
        )
        shown += 1
    if shown == 0:
        st.caption("2商品ブロック（幅50%の表）が見つかる行がありませんでした。")


def _preview_csv(data: bytes, title: str) -> None:
    st.subheader(title)
    rows = _read_csv_rows(data)
    if not rows:
        st.info("CSVが空です。")
        return
    header = rows[0]
    body = rows[1:]
    st.caption(f"{len(body)} 行 / {len(header)} 列（プレビュー）")
    st.dataframe(body, use_container_width=True, column_config={h: h for h in header})

    # Image preview for flat edit sheet (mae_edit.csv).
    if IMAGE_COLS.issubset(set(header)) and body:
        idx1 = header.index("商品1_画像パス")
        idx2 = header.index("商品2_画像パス")
        st.markdown("#### 画像プレビュー（上位20行）")
        for r in body[:20]:
            p1 = r[idx1] if idx1 < len(r) else ""
            p2 = r[idx2] if idx2 < len(r) else ""
            _render_image_preview(p1, p2)
        return

    if _resolve_rakuten_col_indices(header):
        _preview_rakuten_html_images(data)


def _run_extract(source_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "item_mae.csv"
        out = tmp / "mae_edit.csv"
        src.write_bytes(source_bytes)
        run_extract(src, out)
        return out.read_bytes()


def _run_merge(source_bytes: bytes, edit_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "item_mae.csv"
        edit = tmp / "mae_edit.csv"
        out = tmp / "item_ato.csv"
        src.write_bytes(source_bytes)
        edit.write_bytes(edit_bytes)
        run_merge(src, edit, out)
        return out.read_bytes()


def main() -> None:
    st.set_page_config(page_title="楽天 商品説明 一括編集ツール", layout="wide")
    st.sidebar.caption(f"バージョン: {APP_VERSION}")
    st.title("楽天 商品説明 一括編集ツール")
    st.write("`item_mae.csv` から編集用CSVを作成し、編集後CSVを `item_ato.csv` に反映します。")
    st.info(
        "使い方: ①「抽出」で編集用CSVを作成 → ②Googleスプレッドシート/Excelで編集 → "
        "③「マージ」で `item_ato.csv` を作成"
    )

    tab_extract, tab_merge = st.tabs(["1) 抽出（編集用CSV作成）", "2) マージ（反映）"])

    with tab_extract:
        st.header("抽出: item_mae.csv -> mae_edit.csv")
        st.caption("楽天からダウンロードした `item_mae.csv` を選んでください。")
        src_file = st.file_uploader("元CSV（item_mae.csv）", type=["csv"], key="extract_src")
        if st.button("抽出を実行", type="primary", disabled=src_file is None):
            try:
                out = _run_extract(src_file.getvalue())
                st.success("抽出が完了しました。")
                st.download_button(
                    "mae_edit.csv をダウンロード",
                    data=out,
                    file_name="mae_edit.csv",
                    mime="text/csv",
                )
                _preview_csv(out, "抽出結果プレビュー")
            except Exception as exc:
                st.error(f"抽出に失敗しました: {exc}")

    with tab_merge:
        st.header("マージ: item_mae.csv + 編集済みCSV -> item_ato.csv")
        st.caption(
            "元CSVと、編集した `mae_edit.csv` の2つを選んでください。"
            " 出力は楽天アップロード用に Shift_JIS（元CSVと同じ文字コード）です。"
        )
        src_file = st.file_uploader("元CSV（item_mae.csv）", type=["csv"], key="merge_src")
        edit_file = st.file_uploader("編集済みCSV（mae_edit.csv）", type=["csv"], key="merge_edit")
        if st.button("マージを実行", type="primary", disabled=(src_file is None or edit_file is None)):
            try:
                out = _run_merge(src_file.getvalue(), edit_file.getvalue())
                st.success("マージが完了しました。Shift_JIS形式です。そのまま楽天にアップロードできます。")
                st.download_button(
                    "item_ato.csv をダウンロード",
                    data=out,
                    file_name="item_ato.csv",
                    mime="text/csv",
                )
                _preview_csv(out, "マージ結果プレビュー")
            except Exception as exc:
                st.error(f"マージに失敗しました: {exc}")


if __name__ == "__main__":
    main()
