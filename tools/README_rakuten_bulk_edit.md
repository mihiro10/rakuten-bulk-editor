# Rakuten CSV Bulk HTML Editor

This tool supports your workflow:

1. Input `item_mae.csv`
2. Export editable CSV for Excel
3. Edit in Excel
4. Merge edited CSV back
5. Output upload-ready CSV (for example `item_ato.csv`)

## Files

- `tools/rakuten_html_bulk_editor.py` ? CLI
- `tools/rakuten_bulk_web.py` ? local web UI (browser)
- `tools/rakuten_web_ja.py` ? Japanese UI strings for the web UI

## Requirements

- Python 3.9+ (standard library only; no extra packages)

## Web UI (browser)

The web UI is in **Japanese**. Edit `tools/rakuten_web_ja.py` to change wording (strings use `\\u` escapes for safe encoding).

Start:

```bash
python tools/rakuten_bulk_web.py
```

Open:

- http://127.0.0.1:8787

UI flow:

1. **Extract**: upload your source Rakuten CSV. The next page shows a **table preview** of `mae_edit.csv` and a **Download** button (browser download folder; no path to type).
2. Edit the downloaded CSV in Excel, save as CSV.
3. **Merge**: upload the **original** source CSV and your **edited** CSV. The next page previews `item_ato.csv` and offers **Download** the same way.

Outputs are kept in memory for about an hour (for preview/download links). Restarting the server clears them.

## CLI: extract editable sheet

```bash
python tools/rakuten_html_bulk_editor.py extract \
  --input item_mae.csv \
  --output mae_edit.csv
```

Output columns:

- `???i??????`
- `pc_prefix`, `pc_product1_href`, `pc_product1_img_src`, `pc_product1_alt`, `pc_product2_href`, `pc_product2_img_src`, `pc_product2_alt`, `pc_suffix`
- `sp_prefix`, `sp_product1_href`, `sp_product1_img_src`, `sp_product1_alt`, `sp_product2_href`, `sp_product2_img_src`, `sp_product2_alt`, `sp_suffix`

Open `mae_edit.csv` in Excel, edit values, and save as CSV (UTF-8).

## CLI: merge edited sheet back

```bash
python tools/rakuten_html_bulk_editor.py merge \
  --input item_mae.csv \
  --edit mae_edit.csv \
  --output item_ato.csv
```

## Matching and update rules

- Matching key: `???i???????i???iURL?j`
- Only the first (primary) row with non-empty PC/SP HTML for each item code is updated.
- SKU continuation rows are preserved.
- Rows in edited CSV not found in source are reported as warnings.

## Notes

- The tool targets the two-product table block: one `<tr>`, two `<td width="50%">`, each with `a[href]` and `img[src]` (+ optional `alt`).
- If no block is found in a channel, extract leaves that channel empty and reports a warning.
