#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv
import html
import io
import os
import re
import secrets
import sys
import tempfile
import threading
import time
import urllib.parse
from email import message_from_bytes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import rakuten_web_ja as J
from rakuten_html_bulk_editor import run_extract, run_merge

_OUT_STORE: dict[str, tuple[str, bytes, float]] = {}
_STORE_LOCK = threading.Lock()
_STORE_TTL_SEC = 3600
_MAX_PREVIEW_CHARS = 120_000
_PREVIEW_MAX_ROWS = 300
_MAX_CELL_DISPLAY_CHARS = 500
_IMAGE_PREVIEW_BASE = os.environ.get(
    "RAKUTEN_IMAGE_PREVIEW_BASE", "https://image.rakuten.co.jp/chikuya/cabinet/"
)
_IMAGE_PATH_HEADERS = {
    "商品1_画像パス",
    "商品2_画像パス",
    "PC_商品1_画像URL",
    "PC_商品2_画像URL",
    "スマホ_商品1_画像URL",
    "スマホ_商品2_画像URL",
}

TABLE_CSS = """
    .table-wrap { overflow: auto; max-height: 70vh; border: 1px solid #ccc; border-radius: 6px; }
    table.preview { border-collapse: collapse; width: max-content; min-width: 100%; font-size: 12px; }
    table.preview thead th { background: #e3f2fd; color: #0d47a1; font-weight: 600; text-align: left;
      padding: 8px 10px; border: 1px solid #90caf9; position: sticky; top: 0; z-index: 1; white-space: nowrap; }
    table.preview tbody td { padding: 6px 10px; border: 1px solid #e0e0e0; vertical-align: top; }
    table.preview tbody tr:nth-child(even) { background: #fafafa; }
    table.preview tbody tr:hover { background: #f1f8e9; }
    table.preview .cell { max-width: 28rem; max-height: 8rem; overflow: auto; white-space: pre-wrap; word-break: break-word; font-family: system-ui, sans-serif; }
    .thumb-wrap { display: grid; gap: 6px; }
    .thumb-wrap img.thumb { max-width: 140px; max-height: 90px; border: 1px solid #ddd; border-radius: 4px; object-fit: contain; background: #fff; }
    .thumb-wrap .thumb-link { font-size: 11px; color: #1565c0; text-decoration: underline; }
    .thumb-wrap .thumb-miss { display: none; color: #b71c1c; font-size: 11px; }
    .preview-note { color: #666; font-size: 13px; margin: 0 0 8px 0; }
    pre.fallback { background: #f6f6f6; border: 1px solid #eee; padding: 12px; overflow: auto; max-height: 70vh; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
"""

PAGE_HTML = f"""
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{J.PAGE_TITLE}</title>
  <style>
    body {{ font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", sans-serif; margin: 24px; line-height: 1.6; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
    h1 {{ margin-top: 0; font-size: 1.35rem; }}
    h2 {{ margin-bottom: 8px; font-size: 1.1rem; }}
    .row {{ margin-bottom: 8px; }}
    .hint {{ color: #555; font-size: 14px; }}
    button {{ padding: 8px 12px; cursor: pointer; }}
    .error {{ color: #b00020; white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>{J.PAGE_TITLE}</h1>
  <p class="hint">{J.HINT_MAIN}</p>
  __ERROR_BLOCK__
  __RESULT_BLOCK__

  <div class="card">
    <h2>{J.H2_EXTRACT}</h2>
    <p class="hint">{J.HINT_EXTRACT}</p>
    <form method="post" action="/extract" enctype="multipart/form-data">
      <div class="row">
        <label>{J.LABEL_SOURCE}</label><br>
        <input type="file" name="source_csv" accept=".csv" required>
      </div>
      <button type="submit">{J.BTN_EXTRACT}</button>
    </form>
  </div>

  <div class="card">
    <h2>{J.H2_MERGE}</h2>
    <p class="hint">{J.HINT_MERGE}</p>
    <form method="post" action="/merge" enctype="multipart/form-data">
      <div class="row">
        <label>{J.LABEL_ORIG}</label><br>
        <input type="file" name="source_csv" accept=".csv" required>
      </div>
      <div class="row">
        <label>{J.LABEL_EDITED}</label><br>
        <input type="file" name="edited_csv" accept=".csv" required>
      </div>
      <button type="submit">{J.BTN_MERGE}</button>
    </form>
  </div>
</body>
</html>
"""


def _prune_store() -> None:
    now = time.time()
    with _STORE_LOCK:
        dead = [k for k, (_, __, t) in _OUT_STORE.items() if now - t > _STORE_TTL_SEC]
        for k in dead:
            del _OUT_STORE[k]


def _store_output(filename: str, data: bytes) -> str:
    _prune_store()
    token = secrets.token_urlsafe(24)
    with _STORE_LOCK:
        _OUT_STORE[token] = (filename, data, time.time())
    return token


def _get_output(token: str) -> Optional[Tuple[str, bytes]]:
    _prune_store()
    with _STORE_LOCK:
        rec = _OUT_STORE.get(token)
    if not rec:
        return None
    return rec[0], rec[1]


def _parse_multipart_form(body: bytes, content_type: str) -> dict[str, bytes]:
    if "multipart/form-data" not in content_type.lower():
        return {}
    raw = b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    msg = message_from_bytes(raw)
    if not msg.is_multipart():
        return {}
    out: dict[str, bytes] = {}
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disp = part.get("Content-Disposition") or ""
        m = re.search(r'name="([^"]+)"', disp)
        if not m:
            continue
        name = m.group(1)
        payload = part.get_payload(decode=True)
        if payload is None:
            pl = part.get_payload()
            payload = pl.encode("utf-8", errors="replace") if isinstance(pl, str) else b""
        out[name] = payload
    return out


def _preview_text(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    if len(text) > _MAX_PREVIEW_CHARS:
        text = text[:_MAX_PREVIEW_CHARS] + "\n\n" + J.TRUNC_PREVIEW + "\n"
    return text


def _shorten_cell(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if len(s) > _MAX_CELL_DISPLAY_CHARS:
        return s[:_MAX_CELL_DISPLAY_CHARS] + "\n" + J.TRUNC_CELL
    return s


def _looks_absolute_url(s: str) -> bool:
    s_low = s.lower()
    return s_low.startswith("http://") or s_low.startswith("https://") or s_low.startswith("//")


def _join_url(base: str, rel: str) -> str:
    if not base:
        return rel
    return base.rstrip("/") + "/" + rel.lstrip("/")


def _render_preview_cell(header: str, value: str) -> str:
    text = html.escape(_shorten_cell(value))
    raw = (value or "").strip()
    if header not in _IMAGE_PATH_HEADERS or not raw:
        return f'<td><div class="cell">{text}</div></td>'

    img_url = raw if _looks_absolute_url(raw) else _join_url(_IMAGE_PREVIEW_BASE, raw)
    safe_img = html.escape(img_url, quote=True)
    miss_id = f"miss-{abs(hash((header, raw))) % 10_000_000}"
    return (
        "<td><div class=\"cell thumb-wrap\">"
        f"<div>{text}</div>"
        f"<a class=\"thumb-link\" href=\"{safe_img}\" target=\"_blank\" rel=\"noopener noreferrer\">open image</a>"
        f"<img class=\"thumb\" src=\"{safe_img}\" alt=\"preview\" loading=\"lazy\" "
        f"onerror=\"this.style.display='none';document.getElementById('{miss_id}').style.display='block'\">"
        f"<div id=\"{miss_id}\" class=\"thumb-miss\">image not found</div>"
        "</div></td>"
    )


def _build_csv_table_html(data: bytes) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    if len(text) > 8_000_000:
        frag = text[:500_000] + J.HUGE_FRAG_TAIL
        return f'<p class="preview-note">{J.NOTE_HUGE}</p><pre class="fallback">{html.escape(frag)}</pre>'

    try:
        reader = csv.reader(io.StringIO(text))
        rows: list[list[str]] = []
        more_rows = False
        for i, row in enumerate(reader):
            if i > _PREVIEW_MAX_ROWS:
                more_rows = True
                break
            rows.append(row)
    except csv.Error:
        return (
            f'<p class="preview-note">{J.NOTE_CSV_ERR}</p>'
            f'<pre class="fallback">{html.escape(_preview_text(data))}</pre>'
        )

    if not rows:
        return f'<p class="preview-note">{J.NOTE_EMPTY}</p>'

    ncols = max((len(r) for r in rows), default=0)
    for r in rows:
        while len(r) < ncols:
            r.append("")

    header = rows[0]
    body = rows[1:]

    if more_rows:
        note = (
            f'<p class="preview-note">{J.FM1}<strong>{len(body)}</strong>{J.FM2}'
            f'<strong>{J.CSV_BOLD}</strong>{J.FM3}<strong>{ncols}</strong>{J.FM4}</p>'
        )
    else:
        note = (
            f'<p class="preview-note">{J.ALL1}<strong>{len(body)}</strong>{J.ALL2}'
            f'<strong>{ncols}</strong>{J.ALL3}</p>'
        )

    th_parts = [f'<th scope="col">{html.escape(_shorten_cell(h))}</th>' for h in header]
    thead = "<thead><tr>" + "".join(th_parts) + "</tr></thead>"

    trs = []
    for r in body:
        cells = []
        for i, c in enumerate(r):
            col_name = header[i] if i < len(header) else ""
            cells.append(_render_preview_cell(col_name, c))
        trs.append("<tr>" + "".join(cells) + "</tr>")
    tbody = "<tbody>" + "".join(trs) + "</tbody>"

    return (
        f"{note}"
        f'<div class="table-wrap"><table class="preview" aria-label="{J.ARIA_CSV}">{thead}{tbody}</table></div>'
    )


def _result_page(
    title: str,
    filename: str,
    token: str,
    success_msg: str,
    data: bytes,
) -> str:
    preview_url = f"/view?token={urllib.parse.quote(token, safe='')}"
    download_url = f"/download?token={urllib.parse.quote(token, safe='')}"
    preview = _build_csv_table_html(data)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic UI", "Meiryo", sans-serif; margin: 24px; line-height: 1.6; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin-bottom: 16px; }}
{TABLE_CSS}
    a.btn {{ display: inline-block; padding: 10px 16px; background: #1976d2; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600; }}
    a.btn:hover {{ background: #1565c0; }}
  </style>
</head>
<body>
  <div class="card">
    <p><strong>{html.escape(success_msg)}</strong></p>
    <p>{J.RES_FILE_LABEL} <code>{html.escape(filename)}</code></p>
    <p>
      <a class="btn" href="{html.escape(download_url)}" download>{html.escape(filename)}{J.RES_DL}</a>
    </p>
    <p><a href="/">{J.TOP}</a> {J.LINK_SEP} <a href="{html.escape(preview_url)}">{J.PREVIEW_FULL}</a></p>
  </div>
  <div class="card">
    <h2>{J.H2_TABLE}</h2>
    {preview}
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send_html(self, body: str, status: int = HTTPStatus.OK) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _render_index(self, error: str = "", result: str = "") -> bytes:
        if error:
            err = f'<div class="card"><div class="error">{html.escape(error)}</div></div>'
        else:
            err = ""
        if result:
            res = f'<div class="card"><div>{html.escape(result)}</div></div>'
        else:
            res = ""
        body = PAGE_HTML.replace("__ERROR_BLOCK__", err)
        body = body.replace("__RESULT_BLOCK__", res)
        return body.encode("utf-8")

    def _send_page(self, status: int = HTTPStatus.OK, error: str = "", result: str = "") -> None:
        content = self._render_index(error, result)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/":
            self._send_page()
            return

        if parsed.path == "/view":
            token = (q.get("token") or [""])[0]
            if not token:
                self._send_page(HTTPStatus.BAD_REQUEST, J.ERR_NO_TOKEN)
                return
            rec = _get_output(token)
            if not rec:
                self._send_page(HTTPStatus.NOT_FOUND, J.ERR_EXPIRED)
                return
            name, data = rec
            table = _build_csv_table_html(data)
            body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{J.TITLE_VIEW}</title>
<style>
body{{font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic UI","Meiryo",sans-serif;margin:24px;line-height:1.6;}}
{TABLE_CSS}
a{{color:#1565c0;}}
</style>
</head><body>
<p><a href="/download?token={urllib.parse.quote(token, safe='')}" download>{html.escape(name)}{J.RES_DL}</a> {J.LINK_SEP} <a href="/">{J.TOP}</a></p>
{table}
</body></html>"""
            self._send_html(body)
            return

        if parsed.path == "/download":
            token = (q.get("token") or [""])[0]
            if not token:
                self.send_error(HTTPStatus.BAD_REQUEST, J.ERR_TOKEN_S)
                return
            rec = _get_output(token)
            if not rec:
                self.send_error(HTTPStatus.NOT_FOUND, J.ERR_BAD_DL)
                return
            name, data = rec
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            ctype = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ctype.lower():
                self._send_page(HTTPStatus.BAD_REQUEST, J.POST_NEED_MP)
                return
            clen = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(clen)
            parts = _parse_multipart_form(body, ctype)

            if parsed.path == "/extract":
                src = parts.get("source_csv")
                if not src:
                    self._send_page(HTTPStatus.BAD_REQUEST, J.POST_NEED_SRC)
                    return
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    src_p = tmp_path / "source.csv"
                    out_p = tmp_path / "mae_edit.csv"
                    src_p.write_bytes(src)
                    run_extract(src_p, out_p)
                    out_data = out_p.read_bytes()
                token = _store_output("mae_edit.csv", out_data)
                page = _result_page(
                    J.OK_EXTRACT_TITLE,
                    "mae_edit.csv",
                    token,
                    J.OK_EXTRACT_MSG,
                    out_data,
                )
                self._send_html(page)
                return

            if parsed.path == "/merge":
                src = parts.get("source_csv")
                edited = parts.get("edited_csv")
                if not src or not edited:
                    self._send_page(HTTPStatus.BAD_REQUEST, J.POST_NEED_BOTH)
                    return
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    src_p = tmp_path / "source.csv"
                    edit_p = tmp_path / "edited.csv"
                    out_p = tmp_path / "item_ato.csv"
                    src_p.write_bytes(src)
                    edit_p.write_bytes(edited)
                    run_merge(src_p, edit_p, out_p)
                    out_data = out_p.read_bytes()
                token = _store_output("item_ato.csv", out_data)
                page = _result_page(
                    J.OK_MERGE_TITLE,
                    "item_ato.csv",
                    token,
                    J.OK_MERGE_MSG,
                    out_data,
                )
                self._send_html(page)
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_page(HTTPStatus.INTERNAL_SERVER_ERROR, J.ERR_PROC + str(exc))


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8787"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"{J.SERVER_START} ({host}:{port})")
    server.serve_forever()


if __name__ == "__main__":
    main()
