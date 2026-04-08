# ExecuTorch Observatory Demo

This repository hosts batch-generated Observatory reports for ExecuTorch models, served via GitHub Pages.

**Live demo**: https://github.qualcomm.com/pages/boyuc/Executorch_Observatory_Demo/

## What is Observatory?

Observatory is a unified debugging framework for ExecuTorch. It wraps your model export script and automatically captures graph snapshots, accuracy metrics, and per-layer analysis at each compilation stage (export, quantize, lower). The output is a standalone HTML report that anyone can open in a browser to inspect the full compilation pipeline.

The workflow: **capture -> store -> analyze -> visualize -> share**.

Each report contains:
- Interactive graph views with color-coded overlays (accuracy error, op type, per-layer metrics)
- Accuracy metrics at each pipeline stage (PSNR, cosine similarity, MSE, top-k)
- Side-by-side graph comparison with synchronized node selection
- Session-level dashboard with navigation and badges

## What is in this repo

| Path | Purpose |
|------|---------|
| `index.html` | GitHub Pages landing page with report links |
| `scripts/generate_observatory_demo.py` | Batch generator: runs Observatory CLI for each model, writes manifest and index |
| `scripts/generate_fx_viewer_demos.py` | Generates standalone fx_viewer demo HTML artifacts + fx manifest |
| `scripts/render_demo_index.py` | Standalone index renderer (reads observatory + fx manifests) |
| `generated_reports/` | Per-model report directories (HTML, JSON, logs) |
| `generated_reports/manifest.json` | Job metadata (status, paths, timing) |
| `generated_reports/fx_viewer/manifest.json` | fx_viewer demo metadata (status, links, descriptions) |

## Quick start (XNNPack, no device needed)

From your ExecuTorch root:

```bash
source .venv/bin/activate
python -m backends.qualcomm.debugger.observatory.cli \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2
```

Open `/tmp/mv2/observatory_report.html` in a browser.

## Running with Qualcomm backend

Prerequisites:
- ExecuTorch repo with `.venv` activated
- QNN SDK (set `--qnn-sdk-root` or `QNN_SDK_ROOT` env var)
- Datasets: `imagenet-mini-val/` (vision), `wikisent2.txt` (LLM)

```bash
source .venv/bin/activate
source /path/to/qairt/<version>/bin/envsetup.sh

python -m backends.qualcomm.debugger.observatory.cli \
    --report-dir /tmp/obs_vit \
    examples/qualcomm/scripts/torchvision_vit.py \
    -m SM8650 -b ./build-android --dataset imagenet-mini-val/ \
    -H mlgtw-linux -s <device_serial> -a /tmp/obs_vit --seed 1126 --compile_only
```

## Batch generation

Generate reports for all supported models at once.

### Preview what would run (no execution)

```bash
python scripts/generate_observatory_demo.py --plan-only
```

Creates output directories, writes `manifest.json` and `index.html` with all jobs listed as "planned". No scripts are executed.

### Run all jobs

```bash
python scripts/generate_observatory_demo.py \
    --qnn-sdk-root /path/to/qairt/<version>
```

### Re-render HTML from existing JSON (no re-execution)

```bash
python scripts/generate_observatory_demo.py --visualize-only
```

Reads `manifest.json`, calls `cli visualize` for each job that has an existing JSON file, and refreshes `index.html`. Use this after updating Observatory lens code to regenerate all reports without re-running the expensive export scripts.

### Render index only

```bash
python scripts/render_demo_index.py
```

Rebuilds `index.html` from manifests. This is useful when only metadata/artifacts changed.

## fx_viewer standalone demos

Generate and track standalone fx_viewer example artifacts in this repo:

```bash
python scripts/generate_fx_viewer_demos.py \
    --executorch-root ~/executorch
```

This runs:
- `backends/qualcomm/utils/fx_viewer/examples/generate_api_test_harness.py`
- `backends/qualcomm/utils/fx_viewer/examples/demo_3graph_compare.py`

Outputs:
- `generated_reports/fx_viewer/harness/fx_viewer_api_test_harness_portable.html`
- `generated_reports/fx_viewer/harness/fx_viewer_api_test_harness_qualcomm.html`
- `generated_reports/fx_viewer/three_graph_compare/demo_3graph_compare.html`
- `generated_reports/fx_viewer/manifest.json`

Then `index.html` is refreshed via `scripts/render_demo_index.py`.

### Model selectors

```bash
# Only specific XNN models
python scripts/generate_observatory_demo.py --xnn-models mv2,resnet18

# Only specific Qualcomm recipes
python scripts/generate_observatory_demo.py --qualcomm-models torchvision_vit,roberta

# Override primary demo models
python scripts/generate_observatory_demo.py \
    --primary-xnn-model resnet18 \
    --primary-qualcomm-model roberta
```

## Output structure

```
generated_reports/
  manifest.json
  xnnpack/
    mv2/
      observatory_report.html
      observatory_report.json
      run.log
      artifacts/
    resnet18/
      ...
  qualcomm/
    torchvision_vit/
      ...
    roberta/
      ...
index.html
```

## Regenerating HTML from JSON (2-step workflow)

Observatory separates data collection from report generation. This is useful when you want to:
- Collect data in CI and generate reports locally
- Update lens code and re-render without re-running scripts

**Step 1**: Collect data (JSON only)
```bash
python -m backends.qualcomm.debugger.observatory.cli \
    --json-only --report-json /tmp/report.json \
    my_script.py [script_args...]
```

**Step 2**: Generate HTML from JSON
```bash
python -m backends.qualcomm.debugger.observatory.cli visualize \
    --input /tmp/report.json --output /tmp/report.html --title "My Report"
```

## Primary journey defaults

- XNNPack primary: `mv2`
- Qualcomm primary: `torchvision_vit`

These are highlighted in the "Start Here" section of `index.html`.
