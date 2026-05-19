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

from rakuten_column_headers import (
    DEFAULT_RAKUTEN_UPLOAD_SUFFIX,
    H_CODE,
    H_P1_CODE,
    H_P1_NAME,
    H_P2_CODE,
    H_P2_NAME,
    ITEM_CODE_RAKUTEN,
    PC_COL_RAKUTEN,
    SP_COL_RAKUTEN,
    extract_edit_filename,
    rakuten_source_csv_label,
    rakuten_upload_filename,
    RAKUTEN_DOWNLOAD_EXAMPLE,
)
from rakuten_html_bulk_editor import parse_two_product_block, run_extract, run_merge

IMAGE_PREVIEW_BASE = os.environ.get(
    "RAKUTEN_IMAGE_PREVIEW_BASE",
    "https://image.rakuten.co.jp/chikuya/cabinet/",
)
IMAGE_COLS = {"商品1_画像パス", "商品2_画像パス"}
# Bump when deploying so users can confirm Streamlit Cloud picked up the build.
APP_VERSION = "2026-05-19-merge-dl-source"


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


def _href_item_code(href: str) -> str:
    s = (href or "").strip().rstrip("/")
    if not s:
        return ""
    return s.rsplit("/", 1)[-1].strip()


def _slot_preview_lines(
    slot_label: str,
    item_code: str,
    item_name: str,
    img_ref: str,
) -> str:
    lines = [f"**{slot_label}**"]
    code = (item_code or "").strip()
    name = (item_name or "").strip()
    if code:
        lines.append(f"商品管理番号: {code}")
    if name:
        lines.append(f"商品名: {name}")
    if img_ref and not code and not name:
        lines.append(f"画像: {img_ref[:80]}…" if len(img_ref) > 80 else f"画像: {img_ref}")
    return "\n\n".join(lines)


def _render_image_preview(
    p1: str,
    p2: str,
    p1_name: str = "",
    p2_name: str = "",
    *,
    management_code: str = "",
    p1_code: str = "",
    p2_code: str = "",
) -> None:
    mc = (management_code or "").strip()
    if mc:
        st.markdown(f"**商品管理番号（親）:** {mc}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_slot_preview_lines("商品1", p1_code, p1_name, p1))
        u1 = _to_abs_image_url(p1)
        if u1:
            st.image(u1, use_container_width=True)
    with c2:
        st.markdown(_slot_preview_lines("商品2", p2_code, p2_name, p2))
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
        _render_image_preview(
            parsed.p1.img_src,
            parsed.p2.img_src,
            parsed.p1.alt,
            parsed.p2.alt,
            management_code=code,
            p1_code=_href_item_code(parsed.p1.href),
            p2_code=_href_item_code(parsed.p2.href),
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
        code_idx = header.index(H_CODE) if H_CODE in header else None
        idx1_code = header.index(H_P1_CODE) if H_P1_CODE in header else None
        idx2_code = header.index(H_P2_CODE) if H_P2_CODE in header else None
        idx1_name = header.index(H_P1_NAME) if H_P1_NAME in header else None
        idx2_name = header.index(H_P2_NAME) if H_P2_NAME in header else None
        st.markdown("#### 画像プレビュー（上位20行）")
        for r in body[:20]:
            p1 = r[idx1] if idx1 < len(r) else ""
            p2 = r[idx2] if idx2 < len(r) else ""
            c1 = (
                r[idx1_code].strip()
                if idx1_code is not None and idx1_code < len(r)
                else ""
            )
            c2 = (
                r[idx2_code].strip()
                if idx2_code is not None and idx2_code < len(r)
                else ""
            )
            n1 = (
                r[idx1_name].strip()
                if idx1_name is not None and idx1_name < len(r)
                else ""
            )
            n2 = (
                r[idx2_name].strip()
                if idx2_name is not None and idx2_name < len(r)
                else ""
            )
            mgmt = (
                r[code_idx].strip()
                if code_idx is not None and code_idx < len(r)
                else ""
            )
            _render_image_preview(
                p1,
                p2,
                n1,
                n2,
                management_code=mgmt,
                p1_code=c1,
                p2_code=c2,
            )
        return

    if _resolve_rakuten_col_indices(header):
        _preview_rakuten_html_images(data)


def _run_extract(source_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "item_mae.csv"
        out = tmp / extract_edit_filename()
        src.write_bytes(source_bytes)
        run_extract(src, out)
        return out.read_bytes()


def _run_merge(source_bytes: bytes, edit_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "item_mae.csv"
        edit = tmp / extract_edit_filename()
        out = tmp / "item_ato.csv"
        src.write_bytes(source_bytes)
        edit.write_bytes(edit_bytes)
        run_merge(src, edit, out)
        return out.read_bytes()


def main() -> None:
    st.set_page_config(page_title="楽天 商品説明 一括編集ツール", layout="wide")
    st.sidebar.caption(f"バージョン: {APP_VERSION}")
    st.title("楽天 商品説明 一括編集ツール")
    st.write(
        f"楽天の `dl-normal-item_*.csv` から編集用 `{extract_edit_filename()}` を作成し、"
        "マージ後は `normal-item_*.csv` を楽天にアップロードします。"
    )
    st.info(
        "使い方: ①「抽出」で編集用CSVを作成 → ②Googleスプレッドシート/Excelで編集 → "
        "③「マージ」で楽天アップロード用CSV（`normal-item_*.csv`）を作成"
    )

    tab_extract, tab_merge = st.tabs(["1) 抽出（編集用CSV作成）", "2) マージ（反映）"])

    edit_name = extract_edit_filename()
    rakuten_src_label = rakuten_source_csv_label()

    with tab_extract:
        st.header(f"抽出: 楽天CSV → {edit_name}")
        st.caption(
            f"楽天からダウンロードした CSV（例: `{RAKUTEN_DOWNLOAD_EXAMPLE}`）を選び、"
            f"抽出後は必ず **`{edit_name}`** という名前で保存してください。"
        )
        src_file = st.file_uploader(
            rakuten_src_label,
            type=["csv"],
            key="extract_src",
        )
        if st.button("抽出を実行", type="primary", disabled=src_file is None):
            try:
                out = _run_extract(src_file.getvalue())
                st.session_state["extract_csv_bytes"] = out
                st.success(f"抽出が完了しました。ダウンロード名は `{edit_name}` です。")
            except Exception as exc:
                st.session_state.pop("extract_csv_bytes", None)
                st.error(f"抽出に失敗しました: {exc}")

        extract_out = st.session_state.get("extract_csv_bytes")
        if extract_out:
            st.markdown(f"**保存ファイル名:** `{edit_name}`")
            st.download_button(
                f"{edit_name} をダウンロード",
                data=extract_out,
                file_name=edit_name,
                mime="text/csv",
                key="download_extract_mae_edit",
            )
            _preview_csv(extract_out, "抽出結果プレビュー")

    with tab_merge:
        st.header(f"マージ: 楽天CSV + {edit_name} → 楽天アップロード用CSV")
        st.caption(
            f"**元CSV** は抽出と同じ楽天ダウンロード（例: `{RAKUTEN_DOWNLOAD_EXAMPLE}`）。"
            f"**編集済み** は `{edit_name}`。"
            " 出力は Shift_JIS（元CSVと同じ文字コード）、ファイル名は `normal-item_○○.csv` 形式です。"
        )
        upload_suffix = st.text_input(
            "アップロード用ファイル名（normal-item_ の後ろ）",
            value=DEFAULT_RAKUTEN_UPLOAD_SUFFIX,
            help="例: upload → normal-item_upload.csv（英数字・ハイフン・アンダースコアのみ）",
            key="merge_upload_suffix",
        )
        upload_name = rakuten_upload_filename(upload_suffix)
        st.caption(f"ダウンロード名: **{upload_name}**")
        src_file = st.file_uploader(rakuten_src_label, type=["csv"], key="merge_src")
        edit_file = st.file_uploader(
            f"編集済みCSV（{edit_name}）",
            type=["csv"],
            key="merge_edit",
        )
        if st.button("マージを実行", type="primary", disabled=(src_file is None or edit_file is None)):
            try:
                out = _run_merge(src_file.getvalue(), edit_file.getvalue())
                st.success(
                    f"マージが完了しました。Shift_JIS形式の `{upload_name}` です。"
                    "そのまま楽天にアップロードできます。"
                )
                st.download_button(
                    f"{upload_name} をダウンロード",
                    data=out,
                    file_name=upload_name,
                    mime="text/csv",
                    key="download_merge_upload",
                )
                _preview_csv(out, "マージ結果プレビュー")
            except Exception as exc:
                st.error(f"マージに失敗しました: {exc}")


if __name__ == "__main__":
    main()
