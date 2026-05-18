#!/usr/bin/env python3
"""Render index.html for Observatory + fx_viewer demo artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def render_observatory_rows(items: list[dict[str, Any]], repo_root: Path) -> str:
    lines: list[str] = []
    for item in items:
        html_rel = str(item["report_html"])
        log_rel = str(item["log_path"])
        html_exists = (repo_root / html_rel).exists()
        log_exists = (repo_root / log_rel).exists()
        html_cell = f'<a href="{html.escape(html_rel)}">report</a>'
        if not html_exists:
            html_cell = (
                f'<a class="muted" href="{html.escape(html_rel)}">report (pending)</a>'
            )
        log_cell = f'<a href="{html.escape(log_rel)}">log</a>' if log_exists else "-"
        summary_rel = str(item.get("report_summary_json") or "")
        if summary_rel and (repo_root / summary_rel).exists():
            json_cell = f'<a href="{html.escape(summary_rel)}" title="Report (JSON) — lens summaries for CI / LLM triage">json</a>'
        else:
            json_cell = "-"
        lines.append(
            "<tr>"
            f"<td>{html.escape(str(item['name']))}</td>"
            f"<td>{html.escape(str(item['backend']))}</td>"
            f"<td>{html.escape(str(item.get('status', 'unknown')))}</td>"
            f"<td><code>{html.escape(str(item['script']))}</code></td>"
            f"<td>{html_cell}</td>"
            f"<td>{json_cell}</td>"
            f"<td>{log_cell}</td>"
            "</tr>"
        )
    return "\n".join(lines)


def render_comparison_rows(items: list[dict[str, Any]], repo_root: Path) -> str:
    lines: list[str] = []
    for item in items:
        html_rel = str(item["report_html"])
        log_rel = str(item.get("log_path", ""))
        html_exists = (repo_root / html_rel).exists()
        log_exists = (repo_root / log_rel).exists() if log_rel else False
        html_cell = f'<a href="{html.escape(html_rel)}">comparison report</a>'
        if not html_exists:
            html_cell = (
                f'<a class="muted" href="{html.escape(html_rel)}">'
                "comparison (pending)</a>"
            )
        log_cell = f'<a href="{html.escape(log_rel)}">log</a>' if log_exists else "-"
        label = item.get("label") or item.get("name") or ""
        pair = item.get("script", "")
        summary_rel = str(item.get("report_summary_json") or "")
        if summary_rel and (repo_root / summary_rel).exists():
            json_cell = f'<a href="{html.escape(summary_rel)}" title="Report (JSON)">json</a>'
        else:
            json_cell = "-"
        lines.append(
            "<tr>"
            f"<td>{html.escape(str(label))}</td>"
            f"<td>{html.escape(str(item.get('status', 'unknown')))}</td>"
            f"<td><code>{html.escape(str(pair))}</code></td>"
            f"<td>{html_cell}</td>"
            f"<td>{json_cell}</td>"
            f"<td>{log_cell}</td>"
            "</tr>"
        )
    return "\n".join(lines)


def render_fx_rows(items: list[dict[str, Any]], repo_root: Path) -> str:
    lines: list[str] = []
    for item in items:
        html_rel = str(item["artifact_html"])
        log_rel = str(item["log_path"])
        html_exists = (repo_root / html_rel).exists()
        log_exists = (repo_root / log_rel).exists()
        html_cell = f'<a href="{html.escape(html_rel)}">report</a>'
        if not html_exists:
            html_cell = (
                f'<a class="muted" href="{html.escape(html_rel)}">report (pending)</a>'
            )
        log_cell = f'<a href="{html.escape(log_rel)}">log</a>' if log_exists else "-"
        lines.append(
            "<tr>"
            f"<td>{html.escape(str(item['name']))}</td>"
            f"<td>{html.escape(str(item.get('status', 'unknown')))}</td>"
            f"<td>{html.escape(str(item.get('summary', '')))}</td>"
            f"<td>{html.escape(str(item.get('tests', '')))}</td>"
            f"<td><code>{html.escape(str(item['script']))}</code></td>"
            f"<td>{html_cell}</td>"
            f"<td>{log_cell}</td>"
            "</tr>"
        )
    return "\n".join(lines)


def build_fx_section(
    fx_manifest_path: Path,
    repo_root: Path,
) -> str:
    if not fx_manifest_path.exists():
        return """
    <section class="card">
      <h2>fx_viewer Demos</h2>
      <p>
        No fx_viewer demo artifacts found yet. Generate them with
        <code>python scripts/generate_fx_viewer_demos.py</code>.
      </p>
    </section>
"""

    fx_manifest = load_json(fx_manifest_path)
    demos = list(fx_manifest.get("demos", []))
    generated_at = str(fx_manifest.get("generated_at_local", "")).strip()
    generated_line = ""
    if generated_at:
        generated_line = (
            f'<p class="muted">fx_viewer demos generated at: {html.escape(generated_at)}</p>'
        )
    rows = render_fx_rows(demos, repo_root)
    return f"""
    <section class="card">
      <h2>fx_viewer Demos</h2>
      <p>
        Standalone fx_viewer validation artifacts generated from
        <code>backends/qualcomm/utils/fx_viewer/examples</code>.
        These HTML files are tracked in this repo and published on GitHub Pages.
      </p>
      {generated_line}
      <div class="table-wrap">
      <table class="fx-table">
        <thead><tr><th>Demo</th><th>Status</th><th>What It Covers</th><th>Key Tests</th><th>Source Script</th><th>HTML</th><th>Log</th></tr></thead>
        <tbody>
          {rows}
        </tbody>
      </table>
      </div>
    </section>
"""


def render_index(
    observatory_manifest_path: Path,
    fx_manifest_path: Path,
    index_path: Path,
) -> None:
    repo_root = index_path.parent
    manifest = load_json(observatory_manifest_path)
    jobs = list(manifest.get("jobs", []))
    xnn_jobs = [j for j in jobs if j.get("backend") == "xnnpack"]
    qnn_jobs = [j for j in jobs if j.get("backend") == "qualcomm"]
    comp_jobs = [j for j in jobs if j.get("backend") == "comparison"]

    primary = manifest.get("primary_models", {})
    primary_xnn = str(primary.get("xnnpack", "mv2"))
    primary_qnn = str(primary.get("qualcomm", "torchvision_vit"))

    primary_comp = next(
        (j for j in comp_jobs if "mv2" in j.get("id", "") or "MobileNet" in j.get("label", "")),
        comp_jobs[0] if comp_jobs else None,
    )

    def primary_link(backend: str, name: str) -> str:
        for j in jobs:
            if j.get("backend") == backend and j.get("name") == name:
                return str(j.get("report_html", "#"))
        return "#"

    generated_at = str(
        manifest.get(
            "generated_at_local",
            dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
    )

    comparison_section = ""
    if comp_jobs:
        comp_primary_href = (
            str(primary_comp.get("report_html", "#")) if primary_comp else "#"
        )
        comp_primary_label = (
            primary_comp.get("label", "MobileNetV2") if primary_comp else ""
        )
        comparison_section = f"""
    <section class="grid">
      <article class="card" style="grid-column: 1 / -1;">
        <h2>Cross-Backend Comparison (XNNPack vs Qualcomm)</h2>
        <p>
          Compare the same model compiled on two backends &mdash; both archives
          appear in one report, with one collapsible region per backend in the
          tree-view toggle. Use the <strong>🌳 Tree</strong> toggle to switch to
          region-grouped view, then <strong>Select</strong> one record from each
          tree and click <em>Compare</em> for a side-by-side graph diff.
        </p>
        <p><span class="chip">primary comparison</span>
          <a href="{html.escape(comp_primary_href)}">
            Open {html.escape(comp_primary_label)} &mdash; XNNPack vs Qualcomm
          </a>
        </p>
      </article>
    </section>

    <section class="card">
      <h2>Available Cross-Backend Comparisons</h2>
      <div class="table-wrap">
      <table class="cmp-table">
        <thead><tr><th>Model</th><th>Status</th><th>Pair</th><th>Comparison HTML</th><th>JSON</th><th>Log</th></tr></thead>
        <tbody>
          {render_comparison_rows(comp_jobs, repo_root)}
        </tbody>
      </table>
      </div>
    </section>
"""

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ExecuTorch Observatory Demo</title>
  <style>
    :root {{
      --bg: #f4f2ec;
      --card: #fffdf8;
      --ink: #1f1b16;
      --muted: #6b6258;
      --accent: #0a6f68;
      --border: #d8d1c7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: radial-gradient(circle at 10% 0%, #efe7da 0, var(--bg) 40%);
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 2rem 1rem 3rem; }}
    h1, h2 {{ font-family: "Space Grotesk", "Segoe UI", sans-serif; margin: 0 0 .6rem; }}
    p {{ margin: .4rem 0 1rem; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1rem 1.1rem;
      margin-bottom: 1rem;
      box-shadow: 0 6px 18px rgba(31, 27, 22, 0.06);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 0.8rem;
      margin-bottom: 1rem;
    }}
    .chip {{
      display: inline-block;
      border-radius: 999px;
      padding: .15rem .55rem;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: .86rem;
      margin-right: .35rem;
      margin-bottom: .35rem;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .table-wrap {{ width: 100%; overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .95rem; table-layout: fixed; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--border); padding: .5rem .35rem; vertical-align: top; }}
    th {{ font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    code {{ font-size: .86rem; background: #f2ece3; padding: .15rem .35rem; border-radius: 6px; }}
    td code {{ white-space: normal; word-break: break-word; overflow-wrap: anywhere; line-height: 1.35; }}
    .muted {{ color: var(--muted); font-size: .9rem; }}
    .fx-table th:nth-child(1), .fx-table td:nth-child(1) {{ width: 14%; }}
    .fx-table th:nth-child(2), .fx-table td:nth-child(2) {{ width: 8%; }}
    .fx-table th:nth-child(3), .fx-table td:nth-child(3) {{ width: 20%; }}
    .fx-table th:nth-child(4), .fx-table td:nth-child(4) {{ width: 20%; }}
    .fx-table th:nth-child(5), .fx-table td:nth-child(5) {{ width: 24%; }}
    .fx-table th:nth-child(6), .fx-table td:nth-child(6) {{ width: 7%; }}
    .fx-table th:nth-child(7), .fx-table td:nth-child(7) {{ width: 7%; }}
    .obs-table th:nth-child(1), .obs-table td:nth-child(1) {{ width: 12%; }}
    .obs-table th:nth-child(2), .obs-table td:nth-child(2) {{ width: 9%; }}
    .obs-table th:nth-child(3), .obs-table td:nth-child(3) {{ width: 9%; }}
    .obs-table th:nth-child(4), .obs-table td:nth-child(4) {{ width: 38%; }}
    .obs-table th:nth-child(5), .obs-table td:nth-child(5) {{ width: 11%; }}
    .obs-table th:nth-child(6), .obs-table td:nth-child(6) {{ width: 9%; }}
    .obs-table th:nth-child(7), .obs-table td:nth-child(7) {{ width: 12%; }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="card">
      <h1>ExecuTorch Observatory Demo</h1>
      <p>
        <strong>Observatory</strong> is a unified debugging framework for ExecuTorch that captures graph snapshots
        and analysis data across compilation stages, then exports the results as a standalone, shareable HTML report.
      </p>
      <p>
        The workflow: <strong>capture &rarr; store &rarr; analyze &rarr; visualize &rarr; share</strong>.
        Each report contains interactive graph views with color-coded overlays, accuracy metrics at each pipeline stage,
        side-by-side graph comparison, and per-layer analysis. The graph panes are powered by
        <code>fx_viewer</code> (<code>backends/qualcomm/utils/fx_viewer</code>).
      </p>
      <p>
        This page hosts batch-generated reports for XNNPack and Qualcomm backends, plus standalone fx_viewer demo artifacts.
      </p>
      <p class="muted">Generated at: {html.escape(generated_at)}</p>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Primary XNNPack Journey</h2>
        <p><span class="chip">guided first click</span> <strong>{html.escape(primary_xnn)}</strong></p>
        <p><a href="{html.escape(primary_link("xnnpack", primary_xnn))}">Open primary XNNPack report</a></p>
      </article>
      <article class="card">
        <h2>Primary Qualcomm Journey</h2>
        <p><span class="chip">stable starter</span> <strong>{html.escape(primary_qnn)}</strong></p>
        <p><a href="{html.escape(primary_link("qualcomm", primary_qnn))}">Open primary Qualcomm report</a></p>
      </article>
    </section>

    <section class="card">
      <h2>XNNPack Models</h2>
      <div class="table-wrap">
      <table class="obs-table">
        <thead><tr><th>Model</th><th>Backend</th><th>Status</th><th>Script</th><th>HTML</th><th>JSON</th><th>Log</th></tr></thead>
        <tbody>
          {render_observatory_rows(xnn_jobs, repo_root)}
        </tbody>
      </table>
      </div>
    </section>

    <section class="card">
      <h2>Qualcomm Models</h2>
      <div class="table-wrap">
      <table class="obs-table">
        <thead><tr><th>Model</th><th>Backend</th><th>Status</th><th>Script</th><th>HTML</th><th>JSON</th><th>Log</th></tr></thead>
        <tbody>
          {render_observatory_rows(qnn_jobs, repo_root)}
        </tbody>
      </table>
      </div>
    </section>

    {comparison_section}

    {build_fx_section(fx_manifest_path, repo_root)}
  </main>
</body>
</html>
"""
    index_path.write_text(html_doc, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default="generated_reports",
        help="Output root used by observatory/fx manifests.",
    )
    parser.add_argument(
        "--index-path",
        default="index.html",
        help="Path to output index file (repo-relative).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_root = repo_root / args.output_root
    observatory_manifest = output_root / "manifest.json"
    fx_manifest = output_root / "fx_viewer" / "manifest.json"
    index_path = (repo_root / args.index_path).resolve()

    if not observatory_manifest.exists():
        raise FileNotFoundError(
            f"Observatory manifest missing: {observatory_manifest}. "
            "Run scripts/generate_observatory_demo.py first."
        )

    render_index(observatory_manifest, fx_manifest, index_path)
    print(f"Wrote index: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
