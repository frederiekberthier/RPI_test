from __future__ import annotations

import html
import json
from pathlib import Path

from .models import Report

_COLORS = {"PASS": "#1a7f37", "WARN": "#9a6700", "FAIL": "#cf222e", "SKIP": "#6e7781", "INCOMPLETE": "#6e7781"}


def to_html(report: Report) -> str:
    esc = html.escape
    rows = []
    for r in report.results:
        detail = esc(json.dumps(r.details, indent=2, ensure_ascii=False)) if r.details else ""
        more = f"<details><summary>details</summary><pre>{detail}</pre></details>" if detail else ""
        rows.append(
            f"<tr><td>{esc(r.name)}</td>"
            f'<td style="color:{_COLORS[r.status.value]};font-weight:bold">{r.status.value}</td>'
            f"<td>{esc(r.summary)}{more}</td></tr>"
        )
    dut = report.dut_info
    model = esc(str(dut.get("model", "?")))
    serial = esc(str(dut.get("serial", "?")))
    ram = esc(str(dut.get("ram_mb", "?")))
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>Pi-testrapport</title>
<style>body{{font-family:sans-serif;max-width:60rem;margin:2rem auto}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.4rem;text-align:left;vertical-align:top}}</style>
</head><body>
<h1>Pi-testrapport: <span style="color:{_COLORS[report.overall]}">{report.overall}</span></h1>
<p>Model: {model} &middot; Serienummer: {serial} &middot; RAM: {ram} MB<br>
Gestart: {esc(report.started)} &middot; Klaar: {esc(report.finished)}</p>
<table><tr><th>Test</th><th>Resultaat</th><th>Toelichting</th></tr>
{"".join(rows)}</table></body></html>"""


def save(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    serial = str(report.dut_info.get("serial", "onbekend"))
    stamp = report.started.replace(":", "").replace("-", "")
    base = out_dir / f"report-{serial}-{stamp}"
    json_path, html_path = base.with_suffix(".json"), base.with_suffix(".html")
    json_path.write_text(report.to_json(), encoding="utf-8")
    html_path.write_text(to_html(report), encoding="utf-8")
    return json_path, html_path
