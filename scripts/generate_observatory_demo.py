#!/usr/bin/env python3
"""Batch-generate Observatory reports and refresh GitHub Pages index."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import shlex
import subprocess
import time
from pathlib import Path

XNN_MODELS_ALL = [
    "add",
    "add_mul",
    "dl3",
    "edsr",
    "emformer_join",
    "emformer_predict",
    "emformer_transcribe",
    "ic3",
    "ic4",
    "linear",
    "llama2",
    "mobilebert",
    "mv2",
    "mv3",
    "resnet18",
    "resnet50",
    "vit",
    "w2l",
]

QUALCOMM_RECIPES = {
    "torchvision_vit": {
        "script": "examples/qualcomm/scripts/torchvision_vit.py",
        "dataset_kind": "imagenet",
    },
    "mobilenet_v2": {
        "script": "examples/qualcomm/scripts/mobilenet_v2.py",
        "dataset_kind": "imagenet",
    },
    "mobilenet_v3": {
        "script": "examples/qualcomm/scripts/mobilenet_v3.py",
        "dataset_kind": "imagenet",
    },
    "inception_v3": {
        "script": "examples/qualcomm/scripts/inception_v3.py",
        "dataset_kind": "imagenet",
    },
    "inception_v4": {
        "script": "examples/qualcomm/scripts/inception_v4.py",
        "dataset_kind": "imagenet",
    },
    "roberta": {
        "script": "examples/qualcomm/oss_scripts/roberta.py",
        "dataset_kind": "wiki",
    },
    "bert": {
        "script": "examples/qualcomm/oss_scripts/bert.py",
        "dataset_kind": "wiki",
    },
    "albert": {
        "script": "examples/qualcomm/oss_scripts/albert.py",
        "dataset_kind": "wiki",
    },
    "distilbert": {
        "script": "examples/qualcomm/oss_scripts/distilbert.py",
        "dataset_kind": "wiki",
    },
    "eurobert": {
        "script": "examples/qualcomm/oss_scripts/eurobert.py",
        "dataset_kind": "wiki",
    },
}

QUALCOMM_DEFAULT = [
    "torchvision_vit",
    "mobilenet_v2",
    "mobilenet_v3",
    "inception_v3",
    "inception_v4",
    "roberta",
    "bert",
    "albert",
    "distilbert",
    "eurobert",
]


def parse_model_selector(selector: str, all_values: list[str]) -> list[str]:
    if selector == "all":
        return list(all_values)
    if selector == "all-except-mv2":
        return [m for m in all_values if m != "mv2"]
    chosen = [x.strip() for x in selector.split(",") if x.strip()]
    unknown = sorted(set(chosen) - set(all_values))
    if unknown:
        raise ValueError(f"Unknown models in selector: {', '.join(unknown)}")
    return chosen


def parse_qualcomm_selector(selector: str) -> list[str]:
    if selector == "default":
        return list(QUALCOMM_DEFAULT)
    if selector == "all":
        return sorted(QUALCOMM_RECIPES.keys())
    chosen = [x.strip() for x in selector.split(",") if x.strip()]
    unknown = sorted(set(chosen) - set(QUALCOMM_RECIPES))
    if unknown:
        raise ValueError(f"Unknown Qualcomm recipes: {', '.join(unknown)}")
    return chosen


def relpath(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def build_xnn_jobs(args: argparse.Namespace, reports_root: Path) -> list[dict]:
    jobs: list[dict] = []
    for model in args.xnn_models:
        model_dir = reports_root / "xnnpack" / model
        artifact_dir = model_dir / "artifacts"
        html_path = model_dir / "observatory_report.html"
        json_path = model_dir / "observatory_report.json"
        log_path = model_dir / "run.log"
        cmd = [
            "python",
            "-m",
            "backends.qualcomm.debugger.observatory.cli",
            "--report-html",
            str(html_path),
            "--report-json",
            str(json_path),
            "--report-title",
            f"XNNPack Observatory - {model}",
            "examples/xnnpack/aot_compiler.py",
            f"--model_name={model}",
            "--delegate",
            "--quantize",
            "--output_dir",
            str(artifact_dir),
        ]
        jobs.append(
            {
                "id": f"xnnpack:{model}",
                "backend": "xnnpack",
                "name": model,
                "script": "examples/xnnpack/aot_compiler.py",
                "command": cmd,
                "report_html": html_path,
                "report_json": json_path,
                "artifact_dir": artifact_dir,
                "log_path": log_path,
            }
        )
    return jobs


def build_qualcomm_jobs(args: argparse.Namespace, reports_root: Path) -> list[dict]:
    jobs: list[dict] = []
    for name in args.qualcomm_models:
        recipe = QUALCOMM_RECIPES[name]
        dataset = args.imagenet_dataset
        if recipe["dataset_kind"] == "wiki":
            dataset = args.wiki_dataset

        model_dir = reports_root / "qualcomm" / name
        artifact_dir = model_dir / "artifacts"
        html_path = model_dir / "observatory_report.html"
        json_path = model_dir / "observatory_report.json"
        log_path = model_dir / "run.log"

        cmd = [
            "python",
            "-m",
            "backends.qualcomm.debugger.observatory.cli",
            "--report-html",
            str(html_path),
            "--report-json",
            str(json_path),
            "--report-title",
            f"Qualcomm Observatory - {name}",
            recipe["script"],
            "-m",
            args.soc_model,
            "-b",
            args.build_folder,
            "--dataset",
            dataset,
            "-H",
            args.host,
            "-s",
            args.device,
            "-a",
            str(artifact_dir),
            "--seed",
            str(args.seed),
            "--compile_only",
        ]

        jobs.append(
            {
                "id": f"qualcomm:{name}",
                "backend": "qualcomm",
                "name": name,
                "script": recipe["script"],
                "command": cmd,
                "qnn_envsetup": str(args.qnn_envsetup),
                "report_html": html_path,
                "report_json": json_path,
                "artifact_dir": artifact_dir,
                "log_path": log_path,
            }
        )
    return jobs


def run_job(job: dict, cwd: Path, plan_only: bool) -> dict:
    job["started_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    job["return_code"] = None
    job["status"] = "planned"
    job["duration_sec"] = 0.0

    job["report_html"].parent.mkdir(parents=True, exist_ok=True)
    job["artifact_dir"].mkdir(parents=True, exist_ok=True)

    if plan_only:
        print(f"[plan]  {job['id']}")
        return job

    print(f"[start] {job['id']}")
    start = time.time()
    cmd_text = " ".join(shlex.quote(token) for token in job["command"])
    with job["log_path"].open("w", encoding="utf-8") as log_file:
        if job["backend"] == "qualcomm":
            shell_cmd = f"source {shlex.quote(job['qnn_envsetup'])} && {cmd_text}"
            log_file.write(f"$ bash -lc {shlex.quote(shell_cmd)}\n\n")
            proc = subprocess.run(
                ["bash", "-lc", shell_cmd],
                cwd=str(cwd),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        else:
            log_file.write(f"$ {cmd_text}\n\n")
            proc = subprocess.run(
                job["command"],
                cwd=str(cwd),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
    job["duration_sec"] = round(time.time() - start, 3)
    job["return_code"] = proc.returncode
    if proc.returncode == 0 and job["report_html"].exists():
        job["status"] = "success"
    else:
        job["status"] = "failed"
    status_tag = "ok  " if job["status"] == "success" else "FAIL"
    print(f"[{status_tag}] {job['id']}  ({job['duration_sec']:.1f}s)")
    return job


def render_rows(items: list[dict], repo_root: Path) -> str:
    lines = []
    for item in items:
        html_rel = relpath(item["report_html"], repo_root)
        log_rel = relpath(item["log_path"], repo_root)
        status = html.escape(item["status"])
        name = html.escape(item["name"])
        script = html.escape(item["script"])
        html_cell = f'<a href="{html_rel}">report</a>'
        if not item["report_html"].exists():
            html_cell = f'<a class="muted" href="{html_rel}">report (pending)</a>'
        log_cell = f'<a href="{log_rel}">log</a>' if item["log_path"].exists() else "-"
        lines.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{html.escape(item['backend'])}</td>"
            f"<td>{status}</td>"
            f"<td><code>{script}</code></td>"
            f"<td>{html_cell}</td>"
            f"<td>{log_cell}</td>"
            "</tr>"
        )
    return "\n".join(lines)


def write_index(manifest: dict, repo_root: Path) -> None:
    jobs = manifest["jobs"]
    xnn_jobs = [j for j in jobs if j["backend"] == "xnnpack"]
    qnn_jobs = [j for j in jobs if j["backend"] == "qualcomm"]

    primary_xnn = manifest["primary_models"]["xnnpack"]
    primary_qnn = manifest["primary_models"]["qualcomm"]

    def primary_link(backend: str, name: str) -> str:
        for j in jobs:
            if j["backend"] == backend and j["name"] == name:
                if j["report_html"].exists():
                    return relpath(j["report_html"], repo_root)
                return relpath(j["report_html"], repo_root)
        return "#"

    xnn_primary_href = primary_link("xnnpack", primary_xnn)
    qnn_primary_href = primary_link("qualcomm", primary_qnn)

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
    table {{ width: 100%; border-collapse: collapse; font-size: .95rem; }}
    th, td {{ text-align: left; border-bottom: 1px solid var(--border); padding: .5rem .35rem; vertical-align: top; }}
    th {{ font-size: .82rem; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    code {{ font-size: .86rem; background: #f2ece3; padding: .15rem .35rem; border-radius: 6px; }}
    .muted {{ color: var(--muted); font-size: .9rem; }}
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
        This page hosts batch-generated reports for XNNPack and Qualcomm backends.
        Pick a model below to explore its compilation pipeline, or start with the guided path.
      </p>
      <p class="muted">Generated at: {html.escape(manifest["generated_at_local"])}</p>
    </section>

    <section class="card">
      <h2>Start Here</h2>
      <p>Use these two links first for the guided demo path:</p>
      <p><strong>XNNPack primary:</strong> <a href="{html.escape(xnn_primary_href)}">{html.escape(primary_xnn)}</a></p>
      <p><strong>Qualcomm primary:</strong> <a href="{html.escape(qnn_primary_href)}">{html.escape(primary_qnn)}</a></p>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Primary XNNPack Journey</h2>
        <p><span class="chip">guided first click</span> <strong>{html.escape(primary_xnn)}</strong></p>
        <p><a href="{html.escape(xnn_primary_href)}">Open primary XNNPack report</a></p>
      </article>
      <article class="card">
        <h2>Primary Qualcomm Journey</h2>
        <p><span class="chip">stable starter</span> <strong>{html.escape(primary_qnn)}</strong></p>
        <p><a href="{html.escape(qnn_primary_href)}">Open primary Qualcomm report</a></p>
      </article>
    </section>

    <section class="card">
      <h2>XNNPack Models</h2>
      <table>
        <thead><tr><th>Model</th><th>Backend</th><th>Status</th><th>Script</th><th>HTML</th><th>Log</th></tr></thead>
        <tbody>
          {render_rows(xnn_jobs, repo_root)}
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>Qualcomm Models</h2>
      <table>
        <thead><tr><th>Model</th><th>Backend</th><th>Status</th><th>Script</th><th>HTML</th><th>Log</th></tr></thead>
        <tbody>
          {render_rows(qnn_jobs, repo_root)}
        </tbody>
      </table>
    </section>

    <section class="card">
      <h2>fx_viewer Notes</h2>
      <p>
        The graph panes in Observatory reports are powered by <code>backends/qualcomm/utils/fx_viewer</code>.
        For standalone viewer API examples, run the fx_viewer demos in the ExecuTorch repo and add generated HTML under this repo if desired.
      </p>
    </section>
  </main>
</body>
</html>
"""
    (repo_root / "index.html").write_text(html_doc, encoding="utf-8")


def normalize_for_json(job: dict, repo_root: Path) -> dict:
    data = {
        "id": job["id"],
        "backend": job["backend"],
        "name": job["name"],
        "script": job["script"],
        "status": job["status"],
        "return_code": job["return_code"],
        "duration_sec": job["duration_sec"],
        "started_at": job["started_at"],
        "command": job["command"],
        "report_html": relpath(job["report_html"], repo_root),
        "report_json": relpath(job["report_json"], repo_root),
        "artifact_dir": relpath(job["artifact_dir"], repo_root),
        "log_path": relpath(job["log_path"], repo_root),
    }
    if "qnn_envsetup" in job:
        data["qnn_envsetup"] = job["qnn_envsetup"]
    return data


def resolve_qnn_envsetup(qnn_sdk_root: str, needs_qualcomm: bool) -> Path | None:
    raw = (qnn_sdk_root or "").strip() or os.getenv("QNN_SDK_ROOT", "").strip()
    if not needs_qualcomm and not raw:
        return None
    if not raw:
        raise ValueError(
            "Qualcomm jobs selected but QNN SDK is not configured. "
            "Set --qnn-sdk-root or export QNN_SDK_ROOT."
        )
    sdk_root = Path(raw).expanduser().resolve()
    envsetup = sdk_root / "bin" / "envsetup.sh"
    if not envsetup.exists():
        raise FileNotFoundError(f"Missing QNN envsetup script: {envsetup}")
    return envsetup


def order_jobs(jobs: list[dict], primary_xnn: str, primary_qnn: str) -> list[dict]:
    def rank(job: dict) -> tuple[int, str]:
        if job["backend"] == "xnnpack" and job["name"] == primary_xnn:
            return (0, job["id"])
        if job["backend"] == "qualcomm" and job["name"] == primary_qnn:
            return (1, job["id"])
        return (2, job["id"])

    return sorted(jobs, key=rank)


def run_visualize_only(manifest_path: Path, executorch_root: Path) -> int:
    """Regenerate HTML from existing JSON for all jobs listed in manifest.json."""
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=__import__("sys").stderr)
        print(
            "Run without --visualize-only first to generate the manifest.",
            file=__import__("sys").stderr,
        )
        return 1

    import sys as _sys

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_root = manifest_path.parent.parent

    jobs = data.get("jobs", [])
    if not jobs:
        print("No jobs found in manifest.", file=_sys.stderr)
        return 1

    failed = 0
    for job in jobs:
        json_path = repo_root / job["report_json"]
        html_path = repo_root / job["report_html"]
        title = f"{job['backend'].capitalize()} Observatory - {job['name']}"

        if not json_path.exists():
            print(f"[skip]  {job['id']}: JSON not found at {json_path}", file=_sys.stderr)
            failed += 1
            continue

        cmd = [
            "python",
            "-m",
            "backends.qualcomm.debugger.observatory.cli",
            "visualize",
            "--input",
            str(json_path),
            "--output",
            str(html_path),
            "--title",
            title,
        ]
        print(f"[vis]   {job['id']}: {json_path.name} -> {html_path.name}")
        result = subprocess.run(
            cmd,
            cwd=str(executorch_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"  FAILED (rc={result.returncode}): {result.stderr.strip()}",
                file=_sys.stderr,
            )
            failed += 1
        else:
            print(f"  -> {html_path}")

    # Reconstruct rich job dicts (with Path objects) for write_index
    manifest_jobs_rich = []
    for job in jobs:
        rich = dict(job)
        rich["report_html"] = repo_root / job["report_html"]
        rich["report_json"] = repo_root / job["report_json"]
        rich["log_path"] = repo_root / job["log_path"]
        rich["artifact_dir"] = repo_root / job["artifact_dir"]
        manifest_jobs_rich.append(rich)

    write_index({**data, "jobs": manifest_jobs_rich}, repo_root=repo_root)
    index_path = repo_root / "index.html"
    print(f"Refreshed index: {index_path}")
    ok = len(jobs) - failed
    print(f"Done. {ok}/{len(jobs)} jobs visualized successfully.")
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--executorch-root",
        default="~/executorch",
        help="Path to the ExecuTorch repo root. Commands are run from this directory.",
    )
    parser.add_argument(
        "--output-root",
        default="generated_reports",
        help="Output directory inside this demo repo (relative path; created if missing).",
    )
    parser.add_argument(
        "--xnn-models",
        default="all",
        help=(
            "XNN model selector: all | all-except-mv2 | comma-separated list. "
            f"Valid names: {', '.join(XNN_MODELS_ALL)}."
        ),
    )
    parser.add_argument(
        "--qualcomm-models",
        default="default",
        help=(
            "Qualcomm selector: default | all | comma-separated list. "
            f"Valid recipes: {', '.join(sorted(QUALCOMM_RECIPES))}."
        ),
    )
    parser.add_argument("--primary-seed", type=int, default=1126)
    parser.add_argument(
        "--primary-xnn-model",
        default="mv2",
        help="Primary XNN model for the Start Here card. Use 'random' for seeded random pick from selected models.",
    )
    parser.add_argument("--primary-qualcomm-model", default="torchvision_vit")
    parser.add_argument("--soc-model", default="SM8650")
    parser.add_argument("--build-folder", default="./build-android")
    parser.add_argument("--host", default="mlgtw-linux")
    parser.add_argument("--device", default="bebcca9b")
    parser.add_argument("--seed", type=int, default=1126)
    parser.add_argument("--imagenet-dataset", default="imagenet-mini-val/")
    parser.add_argument("--wiki-dataset", default="wikisent2.txt")
    parser.add_argument(
        "--qnn-sdk-root",
        default="",
        help="QNN SDK root path. Also read from $QNN_SDK_ROOT if unset. envsetup.sh at <root>/bin/envsetup.sh is sourced before each Qualcomm command.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help=(
            "Register all jobs in manifest.json and index.html without executing them. "
            "Output directories are created and job status is set to 'planned'."
        ),
    )
    parser.add_argument(
        "--visualize-only",
        action="store_true",
        help=(
            "Re-generate HTML reports from existing JSON files listed in manifest.json. "
            "Does not re-run any export scripts. Requires a prior non-plan-only run."
        ),
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    executorch_root = Path(args.executorch_root).expanduser().resolve()
    if not (executorch_root / "examples").exists():
        raise FileNotFoundError(f"Not an ExecuTorch root: {executorch_root}")

    if args.visualize_only:
        manifest_path = repo_root / args.output_root / "manifest.json"
        return run_visualize_only(manifest_path, executorch_root)

    xnn_models = parse_model_selector(args.xnn_models, XNN_MODELS_ALL)
    qualcomm_models = parse_qualcomm_selector(args.qualcomm_models)

    if args.primary_xnn_model == "random":
        primary_xnn = random.Random(args.primary_seed).choice(xnn_models)
    else:
        primary_xnn = args.primary_xnn_model

    if args.primary_qualcomm_model not in qualcomm_models:
        qualcomm_models = [args.primary_qualcomm_model] + qualcomm_models
    if primary_xnn not in xnn_models:
        xnn_models = [primary_xnn] + xnn_models
    primary_qnn = args.primary_qualcomm_model

    args.xnn_models = list(dict.fromkeys(xnn_models))
    args.qualcomm_models = list(dict.fromkeys(qualcomm_models))
    args.qnn_envsetup = resolve_qnn_envsetup(
        qnn_sdk_root=args.qnn_sdk_root,
        needs_qualcomm=bool(args.qualcomm_models),
    )

    reports_root = repo_root / args.output_root
    reports_root.mkdir(parents=True, exist_ok=True)

    jobs = build_xnn_jobs(args, reports_root) + build_qualcomm_jobs(args, reports_root)
    jobs = order_jobs(jobs, primary_xnn, primary_qnn)
    for job in jobs:
        run_job(job, cwd=executorch_root, plan_only=args.plan_only)

    manifest = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_at_local": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "executorch_root": str(executorch_root),
        "plan_only": args.plan_only,
        "primary_models": {
            "xnnpack": primary_xnn,
            "qualcomm": primary_qnn,
        },
        "jobs": [normalize_for_json(j, repo_root) for j in jobs],
    }
    manifest_path = reports_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # For index rendering, reuse rich in-memory paths.
    write_index(
        {
            **manifest,
            "jobs": jobs,
        },
        repo_root=repo_root,
    )
    print(f"Wrote manifest: {manifest_path}")
    print(f"Wrote index: {repo_root / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
