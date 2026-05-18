#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from rakuten_column_headers import (
    EXTRACT_ORDER,
    ITEM_CODE_RAKUTEN,
    K_CODE,
    K_P1_CODE,
    K_P1_IMG,
    K_P1_NAME,
    K_P2_CODE,
    K_P2_IMG,
    K_P2_NAME,
    PC_COL_RAKUTEN,
    SP_COL_RAKUTEN,
    extract_fieldnames_ja,
    normalize_edit_row,
)

ITEM_CODE_COL = ITEM_CODE_RAKUTEN
SP_COL = SP_COL_RAKUTEN
PC_COL = PC_COL_RAKUTEN


@dataclass
class ProductSlot:
    href: str
    img_src: str
    alt: str


@dataclass
class ParsedBlock:
    prefix: str
    suffix: str
    p1: ProductSlot
    p2: ProductSlot
    block_html: str


def _safe_get(row: Dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _find_columns(fieldnames: List[str]) -> Tuple[str, str, str]:
    normalized = [f.lstrip("\ufeff") for f in fieldnames]

    code_col = None
    sp_col = None
    pc_col = None
    for original, norm in zip(fieldnames, normalized):
        if norm == ITEM_CODE_COL:
            code_col = original
        elif norm == SP_COL:
            sp_col = original
        elif norm == PC_COL:
            pc_col = original

    missing = [name for name, col in [(ITEM_CODE_COL, code_col), (SP_COL, sp_col), (PC_COL, pc_col)] if col is None]
    if missing:
        # Fallback for mojibake headers: assume Rakuten canonical ordering.
        if len(fieldnames) >= 3:
            return fieldnames[0], fieldnames[1], fieldnames[2]
        raise ValueError(f"Required CSV columns missing: {', '.join(missing)}")
    return code_col, sp_col, pc_col


def parse_two_product_block(html: str) -> Optional[ParsedBlock]:
    if not html or "width=\"50%\"" not in html:
        return None

    table_pattern = re.compile(
        r"<table[^>]*>\s*<tr>\s*<td[^>]*width=\"50%\"[^>]*>.*?</td>\s*<td[^>]*width=\"50%\"[^>]*>.*?</td>\s*</tr>\s*</table>",
        re.IGNORECASE | re.DOTALL,
    )
    table_match = table_pattern.search(html)
    if not table_match:
        return None

    block_html = table_match.group(0)
    td_pattern = re.compile(r"<td[^>]*width=\"50%\"[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
    td_matches = td_pattern.findall(block_html)
    if len(td_matches) != 2:
        return None

    def parse_slot(td_inner: str) -> Optional[ProductSlot]:
        href_match = re.search(r"<a[^>]*href=\"([^\"]*)\"", td_inner, re.IGNORECASE | re.DOTALL)
        img_match = re.search(r"<img[^>]*src=\"([^\"]*)\"[^>]*>", td_inner, re.IGNORECASE | re.DOTALL)
        if not href_match or not img_match:
            return None

        img_tag = img_match.group(0)
        alt_match = re.search(r"\salt=\"([^\"]*)\"", img_tag, re.IGNORECASE | re.DOTALL)
        return ProductSlot(
            href=href_match.group(1),
            img_src=img_match.group(1),
            alt=alt_match.group(1) if alt_match else "",
        )

    p1 = parse_slot(td_matches[0])
    p2 = parse_slot(td_matches[1])
    if not p1 or not p2:
        return None

    return ParsedBlock(
        prefix=html[: table_match.start()],
        suffix=html[table_match.end() :],
        p1=p1,
        p2=p2,
        block_html=block_html,
    )


def build_two_product_block(p1: ProductSlot, p2: ProductSlot) -> str:
    return (
        '<table width="100%" align="center">\n'
        "    <tr>\n"
        '        <td width="50%">\n'
        f'            <a href="{p1.href}">\n'
        f'                <img src="{p1.img_src}" width="100%" alt="{p1.alt}">\n'
        "            </a>\n"
        "        </td>\n"
        '        <td width="50%">\n'
        f'            <a href="{p2.href}">\n'
        f'                <img src="{p2.img_src}" width="100%" alt="{p2.alt}">\n'
        "            </a>\n"
        "        </td>\n"
        "    </tr>\n"
        "</table>"
    )


def _replace_nth_group(pattern: str, text: str, values: List[str]) -> str:
    idx = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal idx
        if idx >= len(values):
            return m.group(0)
        out = m.group(1) + values[idx] + m.group(3)
        idx += 1
        return out

    return re.sub(pattern, _repl, text, flags=re.IGNORECASE | re.DOTALL)


def _rebuild_block_preserve_format(block_html: str, p1: ProductSlot, p2: ProductSlot) -> str:
    # Keep original whitespace/indentation exactly; only patch attribute values.
    out = block_html
    out = _replace_nth_group(r'(<a[^>]*\shref=")([^"]*)(")', out, [p1.href, p2.href])
    out = _replace_nth_group(r'(<img[^>]*\ssrc=")([^"]*)(")', out, [p1.img_src, p2.img_src])
    out = _replace_nth_group(r'(<img[^>]*\salt=")([^"]*)(")', out, [p1.alt, p2.alt])
    return out


def _open_csv_reader_with_fallback(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    encodings = ["utf-8-sig", "cp932", "shift_jis"]
    last_error: Optional[Exception] = None
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    raise ValueError("Input CSV has no header.")
                fieldnames = list(reader.fieldnames)
                rows = list(reader)
            return rows, fieldnames
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise ValueError("Failed to open CSV.")


def read_csv_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str], str, str, str]:
    rows, fieldnames = _open_csv_reader_with_fallback(path)
    code_col, sp_col, pc_col = _find_columns(fieldnames)
    return rows, fieldnames, code_col, sp_col, pc_col


def write_csv_rows(path: Path, fieldnames: List[str], rows: List[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def find_primary_rows(
    rows: List[Dict[str, str]], code_col: str, sp_col: str, pc_col: str
) -> Dict[str, int]:
    idx_map: Dict[str, int] = {}
    for idx, row in enumerate(rows):
        code = _safe_get(row, code_col)
        if not code or code in idx_map:
            continue
        if _safe_get(row, sp_col) or _safe_get(row, pc_col):
            idx_map[code] = idx
    return idx_map


def _common_prefix(values: List[str]) -> str:
    non_empty = [v for v in values if v]
    if len(non_empty) < 2:
        return ""
    prefix = non_empty[0]
    for v in non_empty[1:]:
        i = 0
        max_i = min(len(prefix), len(v))
        while i < max_i and prefix[i] == v[i]:
            i += 1
        prefix = prefix[:i]
        if not prefix:
            return ""

    # Keep boundary at path separator to avoid odd partial tokens.
    slash = prefix.rfind("/")
    if slash >= 8:
        prefix = prefix[: slash + 1]
    elif len(prefix) < 12:
        return ""
    return prefix


def _collect_url_bases(rows: List[Dict[str, str]], code_col: str, sp_col: str, pc_col: str) -> Dict[str, str]:
    hrefs: List[str] = []
    imgs: List[str] = []
    primary = find_primary_rows(rows, code_col, sp_col, pc_col)
    for _code, idx in sorted(primary.items(), key=lambda kv: kv[1]):
        src_row = rows[idx]
        pc_html = _safe_get(src_row, pc_col)
        sp_html = _safe_get(src_row, sp_col)
        for parsed in (parse_two_product_block(pc_html) if pc_html else None, parse_two_product_block(sp_html) if sp_html else None):
            if not parsed:
                continue
            hrefs.extend([parsed.p1.href, parsed.p2.href])
            imgs.extend([parsed.p1.img_src, parsed.p2.img_src])
    href_base = _common_prefix(hrefs)
    img_base = _common_prefix(imgs)
    # Keep one directory level visible for image paths (e.g. "kanren/file.jpg").
    if img_base.endswith("/"):
        trimmed = img_base.rstrip("/")
        slash = trimmed.rfind("/")
        if slash > 0:
            img_base = trimmed[: slash + 1]
    return {"href": href_base, "img": img_base}


def _is_absolute_url(value: str) -> bool:
    s = value.lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("//")


def _strip_base(value: str, base: str) -> str:
    if not value or not base:
        return value
    return value[len(base) :] if value.startswith(base) else value


def _normalize_href_for_extract(value: str) -> str:
    # Make item codes easier to edit in Excel: show "10023" instead of "10023/".
    if value.endswith("/") and value[:-1].isdigit():
        return value[:-1]
    return value


def _restore_base(value: str, base: str) -> str:
    if not value:
        return value
    if not base or _is_absolute_url(value):
        return value
    return base + value


def _restore_href_for_merge(value: str) -> str:
    # Rebuild canonical Rakuten item path if user edited only numeric code.
    if value.isdigit():
        return value + "/"
    return value


def _compact_href_to_code(value: str, url_bases: Dict[str, str]) -> str:
    return _normalize_href_for_extract(_strip_base(value, url_bases["href"]))


def _pick_edit_source(pc_parsed: Optional[ParsedBlock], sp_parsed: Optional[ParsedBlock]) -> Optional[ParsedBlock]:
    return pc_parsed or sp_parsed


def _extract_edit_values(source: Optional[ParsedBlock], url_bases: Dict[str, str]) -> Dict[str, str]:
    if not source:
        return {
            K_P1_CODE: "",
            K_P1_NAME: "",
            K_P1_IMG: "",
            K_P2_CODE: "",
            K_P2_NAME: "",
            K_P2_IMG: "",
        }
    return {
        K_P1_CODE: _compact_href_to_code(source.p1.href, url_bases),
        K_P1_NAME: source.p1.alt,
        K_P1_IMG: source.p1.img_src,
        K_P2_CODE: _compact_href_to_code(source.p2.href, url_bases),
        K_P2_NAME: source.p2.alt,
        K_P2_IMG: source.p2.img_src,
    }


def run_extract(input_csv: Path, output_csv: Path) -> int:
    rows, _, code_col, sp_col, pc_col = read_csv_rows(input_csv)
    primary_map = find_primary_rows(rows, code_col, sp_col, pc_col)
    url_bases = _collect_url_bases(rows, code_col, sp_col, pc_col)

    out_fields = extract_fieldnames_ja()
    out_rows: List[Dict[str, str]] = []

    warn_no_block_pc: List[str] = []
    warn_no_block_sp: List[str] = []

    for code, idx in sorted(primary_map.items(), key=lambda kv: kv[1]):
        src_row = rows[idx]
        pc_html = _safe_get(src_row, pc_col)
        sp_html = _safe_get(src_row, sp_col)

        pc_parsed = parse_two_product_block(pc_html) if pc_html else None
        sp_parsed = parse_two_product_block(sp_html) if sp_html else None

        if pc_html and not pc_parsed:
            warn_no_block_pc.append(code)
        if sp_html and not sp_parsed:
            warn_no_block_sp.append(code)

        internal: Dict[str, str] = {K_CODE: code}
        internal.update(_extract_edit_values(_pick_edit_source(pc_parsed, sp_parsed), url_bases))
        ja_row = {hja: internal[ik] for ik, hja in EXTRACT_ORDER}
        out_rows.append(ja_row)

    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Extract complete: {output_csv}")
    print(f"Primary items exported: {len(out_rows)}")
    if warn_no_block_pc:
        print(f"[warn] PC block not found for {len(warn_no_block_pc)} items")
    if warn_no_block_sp:
        print(f"[warn] SP block not found for {len(warn_no_block_sp)} items")
    return 0


def _row_has_edit_data(edit_row: Dict[str, str]) -> bool:
    return any(
        (edit_row.get(k) or "").strip()
        for k in [
            K_P1_CODE,
            K_P1_NAME,
            K_P1_IMG,
            K_P2_CODE,
            K_P2_NAME,
            K_P2_IMG,
        ]
    )


def _build_channel_from_edit(
    edit_row: Dict[str, str], channel_parsed: Optional[ParsedBlock], url_bases: Dict[str, str]
) -> Optional[str]:
    if not channel_parsed:
        return None
    p1_code_new = (edit_row.get(K_P1_CODE) or "").strip()
    p2_code_new = (edit_row.get(K_P2_CODE) or "").strip()
    p1_name_new = (edit_row.get(K_P1_NAME) or "").strip()
    p2_name_new = (edit_row.get(K_P2_NAME) or "").strip()
    p1_img_new = (edit_row.get(K_P1_IMG) or "").strip()
    p2_img_new = (edit_row.get(K_P2_IMG) or "").strip()

    # Partial-edit safe: blank cells keep existing channel values.
    p1_href_raw = _restore_href_for_merge(p1_code_new) if p1_code_new else channel_parsed.p1.href
    p2_href_raw = _restore_href_for_merge(p2_code_new) if p2_code_new else channel_parsed.p2.href
    p1_img_raw = p1_img_new if p1_img_new else channel_parsed.p1.img_src
    p2_img_raw = p2_img_new if p2_img_new else channel_parsed.p2.img_src
    p1_alt_raw = p1_name_new if p1_name_new else channel_parsed.p1.alt
    p2_alt_raw = p2_name_new if p2_name_new else channel_parsed.p2.alt

    p1 = ProductSlot(
        href=_restore_base(p1_href_raw, url_bases["href"]),
        img_src=_restore_base(p1_img_raw, url_bases["img"]),
        alt=p1_alt_raw,
    )
    p2 = ProductSlot(
        href=_restore_base(p2_href_raw, url_bases["href"]),
        img_src=_restore_base(p2_img_raw, url_bases["img"]),
        alt=p2_alt_raw,
    )
    rebuilt = _rebuild_block_preserve_format(channel_parsed.block_html, p1, p2)
    return channel_parsed.prefix + rebuilt + channel_parsed.suffix


def run_merge(input_csv: Path, edit_csv: Path, output_csv: Path) -> int:
    rows, fieldnames, code_col, sp_col, pc_col = read_csv_rows(input_csv)
    primary_map = find_primary_rows(rows, code_col, sp_col, pc_col)
    url_bases = _collect_url_bases(rows, code_col, sp_col, pc_col)

    with edit_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        edit_rows = list(reader)

    edit_map: Dict[str, Dict[str, str]] = {}
    for row in edit_rows:
        norm = normalize_edit_row(row)
        code = (norm.get(K_CODE) or "").strip()
        if code:
            edit_map[code] = norm

    updated = 0
    skipped = 0
    missing_codes: List[str] = []

    for code, edit_row in edit_map.items():
        if code not in primary_map:
            missing_codes.append(code)
            continue

        idx = primary_map[code]
        target = dict(rows[idx])
        changed = False

        if _row_has_edit_data(edit_row):
            pc_parsed = parse_two_product_block(_safe_get(target, pc_col))
            sp_parsed = parse_two_product_block(_safe_get(target, sp_col))

            new_pc = _build_channel_from_edit(edit_row, pc_parsed, url_bases)
            if new_pc is not None:
                target[pc_col] = new_pc
                changed = True

            new_sp = _build_channel_from_edit(edit_row, sp_parsed, url_bases)
            if new_sp is not None:
                target[sp_col] = new_sp
                changed = True

        if changed:
            rows[idx] = target
            updated += 1
        else:
            skipped += 1

    write_csv_rows(output_csv, fieldnames, rows)

    print(f"Merge complete: {output_csv}")
    print(f"Updated items: {updated}")
    print(f"Skipped (no edit data): {skipped}")
    if missing_codes:
        print(f"[warn] Item codes not found in source CSV: {len(missing_codes)}")
        print("       " + ", ".join(missing_codes[:20]) + (" ..." if len(missing_codes) > 20 else ""))
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract and merge Rakuten two-product HTML blocks for bulk Excel editing."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="Extract editable fields from Rakuten CSV.")
    p_extract.add_argument("--input", required=True, type=Path, help="Source Rakuten CSV (e.g. item_mae.csv)")
    p_extract.add_argument("--output", required=True, type=Path, help="Output editable CSV (for Excel)")

    p_merge = sub.add_parser("merge", help="Merge edited CSV back into Rakuten CSV.")
    p_merge.add_argument("--input", required=True, type=Path, help="Original source Rakuten CSV")
    p_merge.add_argument("--edit", required=True, type=Path, help="Edited extract CSV from Excel")
    p_merge.add_argument("--output", required=True, type=Path, help="Merged Rakuten CSV output")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        if args.command == "extract":
            return run_extract(args.input, args.output)
        if args.command == "merge":
            return run_merge(args.input, args.edit, args.output)
        parser.print_help()
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
