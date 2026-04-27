#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
from pathlib import Path
from typing import List

import streamlit as st

ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from rakuten_html_bulk_editor import run_extract, run_merge

IMAGE_PREVIEW_BASE = os.environ.get(
    "RAKUTEN_IMAGE_PREVIEW_BASE",
    "https://image.rakuten.co.jp/chikuya/cabinet/",
)
IMAGE_COLS = {"商品1_画像パス", "商品2_画像パス"}


def _read_csv_rows(data: bytes, max_rows: int = 200) -> List[List[str]]:
    text = data.decode("utf-8-sig", errors="replace")
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

    # Lightweight image preview for edit-sheet output.
    if IMAGE_COLS.issubset(set(header)) and body:
        idx1 = header.index("商品1_画像パス")
        idx2 = header.index("商品2_画像パス")
        st.markdown("#### 画像プレビュー（上位20行）")
        for r in body[:20]:
            p1 = r[idx1] if idx1 < len(r) else ""
            p2 = r[idx2] if idx2 < len(r) else ""
            c1, c2 = st.columns(2)
            with c1:
                st.caption(f"商品1: {p1}")
                u1 = _to_abs_image_url(p1)
                if u1:
                    st.image(u1, use_container_width=True)
            with c2:
                st.caption(f"商品2: {p2}")
                u2 = _to_abs_image_url(p2)
                if u2:
                    st.image(u2, use_container_width=True)


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
        st.caption("元CSVと、編集した `mae_edit.csv` の2つを選んでください。")
        src_file = st.file_uploader("元CSV（item_mae.csv）", type=["csv"], key="merge_src")
        edit_file = st.file_uploader("編集済みCSV（mae_edit.csv）", type=["csv"], key="merge_edit")
        if st.button("マージを実行", type="primary", disabled=(src_file is None or edit_file is None)):
            try:
                out = _run_merge(src_file.getvalue(), edit_file.getvalue())
                st.success("マージが完了しました。")
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
