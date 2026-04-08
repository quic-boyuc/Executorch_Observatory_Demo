#!/usr/bin/env python3
"""Generate fx_viewer example artifacts and manifest in this demo repo."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any


def relpath(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def run_logged(command: list[str], cwd: Path, log_path: Path) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_text = " ".join(shlex.quote(x) for x in command)
    with log_path.open("w", encoding="utf-8") as f:
        f.write(f"$ {cmd_text}\n\n")
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return proc.returncode


def make_demo(
    *,
    repo_root: Path,
    demo_id: str,
    name: str,
    status: str,
    summary: str,
    tests: str,
    script: str,
    artifact_html: Path,
    log_path: Path,
    rc: int,
) -> dict[str, Any]:
    return {
        "id": demo_id,
        "name": name,
        "status": status,
        "summary": summary,
        "tests": tests,
        "script": script,
        "return_code": rc,
        "artifact_html": relpath(artifact_html, repo_root),
        "log_path": relpath(log_path, repo_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executorch-root", default="~/executorch")
    parser.add_argument(
        "--output-root",
        default="generated_reports/fx_viewer",
        help="Repo-relative output root for fx_viewer artifacts.",
    )
    parser.add_argument("--seed", type=int, default=1126)
    parser.add_argument("--num-samples", type=int, default=6)
    parser.add_argument("--calibration-steps", type=int, default=3)
    parser.add_argument("--soc-model", default="SM8650")
    parser.add_argument("--backend", choices=["htp", "gpu"], default="htp")
    parser.add_argument(
        "--skip-index-refresh",
        action="store_true",
        help="Do not re-render root index after generating fx_viewer artifacts.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    executorch_root = Path(args.executorch_root).expanduser().resolve()
    if not (executorch_root / "backends" / "qualcomm" / "utils" / "fx_viewer").exists():
        raise FileNotFoundError(f"Invalid ExecuTorch root: {executorch_root}")

    output_root = (repo_root / args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    fx_examples = (
        executorch_root
        / "backends"
        / "qualcomm"
        / "utils"
        / "fx_viewer"
        / "examples"
    )
    harness_dir = output_root / "harness"
    compare_dir = output_root / "three_graph_compare"
    harness_dir.mkdir(parents=True, exist_ok=True)
    compare_dir.mkdir(parents=True, exist_ok=True)

    harness_script = fx_examples / "generate_api_test_harness.py"
    harness_log = harness_dir / "run.log.txt"
    harness_cmd = [
        "python",
        str(harness_script),
        "--output-dir",
        str(harness_dir),
        "--seed",
        str(args.seed),
        "--num-samples",
        str(args.num_samples),
        "--calibration-steps",
        str(args.calibration_steps),
        "--soc-model",
        args.soc_model,
        "--backend",
        args.backend,
    ]
    harness_rc = run_logged(harness_cmd, cwd=executorch_root, log_path=harness_log)

    portable_html = harness_dir / "fx_viewer_api_test_harness_portable.html"
    qualcomm_html = harness_dir / "fx_viewer_api_test_harness_qualcomm.html"

    compare_script = fx_examples / "demo_3graph_compare.py"
    compare_log = compare_dir / "run.log.txt"
    compare_cmd = ["python", str(compare_script)]
    compare_rc = run_logged(compare_cmd, cwd=executorch_root, log_path=compare_log)

    produced_compare = executorch_root / "demo_3graph_compare.html"
    compare_html = compare_dir / "demo_3graph_compare.html"
    if produced_compare.exists():
        shutil.copy2(produced_compare, compare_html)

    demos = [
        make_demo(
            repo_root=repo_root,
            demo_id="harness_portable",
            name="API Harness (Portable)",
            status="success" if portable_html.exists() else "failed",
            summary=(
                "Unified fx_viewer API harness without Qualcomm SDK requirements."
            ),
            tests=(
                "js_01..js_08, adv_01..adv_04, js_99 (portable tutorial sequence)."
            ),
            script="backends/qualcomm/utils/fx_viewer/examples/generate_api_test_harness.py",
            artifact_html=portable_html,
            log_path=harness_log,
            rc=harness_rc,
        ),
        make_demo(
            repo_root=repo_root,
            demo_id="harness_qualcomm",
            name="API Harness (Qualcomm)",
            status="success" if qualcomm_html.exists() else "failed",
            summary=(
                "Harness with Qualcomm PTQ path and Qualcomm metadata testcase."
            ),
            tests=(
                "All tutorial cases plus qualcomm_metadata when env is available."
            ),
            script="backends/qualcomm/utils/fx_viewer/examples/generate_api_test_harness.py",
            artifact_html=qualcomm_html,
            log_path=harness_log,
            rc=harness_rc,
        ),
        make_demo(
            repo_root=repo_root,
            demo_id="three_graph_compare",
            name="3-Graph Compare Demo",
            status="success" if compare_html.exists() else "failed",
            summary=(
                "Reference vs decomposed (1->many) vs fused (many->1) sync behavior."
            ),
            tests=(
                "Auto sync order from_node_root -> debug_handle -> id; highlight/clear demo."
            ),
            script="backends/qualcomm/utils/fx_viewer/examples/demo_3graph_compare.py",
            artifact_html=compare_html,
            log_path=compare_log,
            rc=compare_rc,
        ),
    ]

    manifest = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "generated_at_local": dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "executorch_root": str(executorch_root),
        "output_root": relpath(output_root, repo_root),
        "demos": demos,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote fx manifest: {manifest_path}")

    if not args.skip_index_refresh:
        render_cmd = ["python", str(repo_root / "scripts" / "render_demo_index.py")]
        result = subprocess.run(render_cmd, cwd=str(repo_root), check=False)
        if result.returncode != 0:
            return result.returncode

    failed = sum(1 for d in demos if d["status"] != "success")
    print(f"fx_viewer demos done: {len(demos) - failed}/{len(demos)} successful.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
