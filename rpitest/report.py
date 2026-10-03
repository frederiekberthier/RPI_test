from __future__ import annotations

import html
import json
import re
from collections import Counter
from pathlib import Path

from .models import Report

_COLORS = {"PASS": "#1a7f37", "WARN": "#9a6700", "FAIL": "#cf222e", "SKIP": "#6e7781", "INCOMPLETE": "#6e7781"}
_OVERALL_TEXT = {
    "PASS": "Geslaagd: alle onderdelen werken",
    "WARN": "Geslaagd met opmerkingen: bekijk de waarschuwingen",
    "FAIL": "Niet geslaagd: er is minstens één defect",
    "INCOMPLETE": "Onvolledig: niet alles kon getest worden",
}
REPORT_NAME = re.compile(r"^report-[A-Za-z0-9._-]+\.(?:html|json)$")


def to_html(report: Report) -> str:
    esc = html.escape
    rows = []
    for r in report.results:
        detail = esc(json.dumps(r.details, indent=2, ensure_ascii=False, default=str)) if r.details else ""
        more = f"<details><summary>details</summary><pre>{detail}</pre></details>" if detail else ""
        rows.append(
            f"<tr><td>{esc(r.name)}</td>"
            f'<td class="st" style="color:{_COLORS[r.status.value]}">{r.status.value}</td>'
            f"<td>{esc(r.summary)}{more}</td></tr>"
        )
    counts = Counter(r.status.value for r in report.results)
    summary = " &middot; ".join(f"{counts[s]} {s}" for s in ("PASS", "WARN", "FAIL", "SKIP") if counts[s])
    client, server = report.client_info, report.server_info
    model = esc(str(client.get("model", "?")))
    serial = esc(str(client.get("serial", "?")))
    revision = esc(str(client.get("revision", "?")))
    ram = esc(str(client.get("ram_mb", "?")))
    overall = report.overall
    return f"""<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pi-testrapport {serial}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:62rem;margin:1.5rem auto;padding:0 1rem;color:#1c1c1c}}
.banner{{border-left:.6rem solid {_COLORS[overall]};background:#f6f8fa;padding:.8rem 1rem;margin:1rem 0}}
.banner h1{{margin:0;font-size:1.6rem;color:{_COLORS[overall]}}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #d0d7de;padding:.4rem .6rem;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}.st{{font-weight:700;white-space:nowrap}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem}}dt{{color:#57606a}}dd{{margin:0}}
pre{{white-space:pre-wrap;word-break:break-word;font-size:.8rem}}
.back{{display:none}}@media screen{{.back.on{{display:inline-block;margin-bottom:.5rem}}}}
@media print{{.back{{display:none!important}}details>summary{{display:none}}details pre{{display:none}}}}
</style></head><body>
<a class="back" id="back" href="/">&larr; terug naar de TEST-SERVER</a>
<script>if(location.protocol.startsWith("http"))document.getElementById("back").classList.add("on")</script>
<div class="banner"><h1>{overall}</h1><div>{_OVERALL_TEXT[overall]}</div><div>{summary}</div></div>
<dl>
<dt>Model</dt><dd>{model}</dd><dt>Serienummer</dt><dd>{serial}</dd>
<dt>Revisie</dt><dd>{revision}</dd><dt>RAM</dt><dd>{ram} MB</dd>
<dt>Getest met</dt><dd>{esc(str(server.get("model", "?")))}</dd>
<dt>Gestart</dt><dd>{esc(report.started)}</dd><dt>Klaar</dt><dd>{esc(report.finished)}</dd>
</dl>
<table><tr><th>Test</th><th>Resultaat</th><th>Toelichting</th></tr>
{"".join(rows)}</table></body></html>"""


def save(report: Report, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    serial = re.sub(r"[^A-Za-z0-9._-]", "_", str(report.client_info.get("serial", "onbekend")))
    stamp = report.started.replace(":", "").replace("-", "")
    base = out_dir / f"report-{serial}-{stamp}"
    counter = 1
    while base.with_suffix(".json").exists() or base.with_suffix(".html").exists():  # twee runs in dezelfde seconde
        counter += 1
        base = out_dir / f"report-{serial}-{stamp}-{counter}"
    json_path, html_path = base.with_suffix(".json"), base.with_suffix(".html")
    json_path.write_text(report.to_json(), encoding="utf-8")
    html_path.write_text(to_html(report), encoding="utf-8")
    return json_path, html_path


def list_history(out_dir: Path, limit: int = 15) -> list[dict]:
    """De laatste opgeslagen rapporten, nieuwste eerst."""
    history = []
    for path in sorted(out_dir.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            history.append({"overall": data["overall"], "started": data["started"],
                            "serial": data["client_info"].get("serial", "?"),
                            "model": data["client_info"].get("model", "?"), "html": path.with_suffix(".html").name})
        except (OSError, ValueError, KeyError):
            continue  # kapot of half geschreven bestand: overslaan
    return history
