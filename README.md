# ExecuTorch Observatory Demo

Live demo:
https://github.qualcomm.com/pages/boyuc/Executorch_Observatory_Demo/

This repo is a demo host for Observatory HTML reports generated from:

- XNNPack export flow (`examples/xnnpack/aot_compiler.py`)
- Qualcomm backend export flow (`examples/qualcomm/scripts/...`)
- Qualcomm LLM flow (`examples/qualcomm/oss_scripts/roberta.py`)

It also documents how this relates to `fx_viewer`:
`backends/qualcomm/utils/fx_viewer` in your ExecuTorch workspace, which powers the graph panes inside Observatory reports.

## What is included

- `index.html`: GitHub Pages entry page with project intro and report links.
- `scripts/generate_observatory_demo.py`: batch generator + manifest writer + index updater.
- `generated_reports/manifest.json`: generated job/report metadata.

## Important CLI fix (implemented)

Observatory CLI in ExecuTorch was patched here:
`backends/qualcomm/debugger/observatory/cli.py`

Changes:

- Added explicit output flags: `--report-dir`, `--report-html`, `--report-json`
- Observatory flags are now parsed only before `SCRIPT`, so script args no longer get accidentally consumed
- Default report-dir inference supports both `-a/--artifact` and `-o/--output_dir`

This addresses the report-path/arg-mixing issue for XNNPack-style commands.

## Prerequisites

Run commands in your ExecuTorch root directory (the generator enforces this via `--executorch-root`).
For Qualcomm jobs, set QNN SDK root via `--qnn-sdk-root` (or `QNN_SDK_ROOT` env var).

Typical environment setup:

```bash
cd /path/to/executorch
source .venv/bin/activate
source qairt/2.37.0.250724/bin/envsetup.sh
export PYTHONPATH=~/:$PYTHONPATH
```

Datasets expected by default:

- ImageNet mini val: `imagenet-mini-val/`
- Wiki sentences: `wikisent2.txt`

## Single-command examples

XNNPack (switch model with `--model_name=...`, defaults here are demo-style and quantized):

```bash
cd /path/to/executorch
python -m backends.qualcomm.debugger.observatory.cli \
  --report-dir /tmp/obs_xnn_ic4 \
  examples/xnnpack/aot_compiler.py \
  --model_name=ic4 --delegate --quantize
```

Qualcomm vision (`torchvision_vit.py`, compile only):

```bash
cd /path/to/executorch
python -m backends.qualcomm.debugger.observatory.cli \
  --report-dir /tmp/obs_qnn_vit \
  examples/qualcomm/scripts/torchvision_vit.py \
  -m SM8650 -b ./build-android --dataset imagenet-mini-val/ \
  -H mlgtw-linux -s bebcca9b -a TorchVision_Lanai --seed 1126 --compile_only
```

Qualcomm LLM (your requested RoBERTa wiki command, compile only):

```bash
cd /path/to/executorch
python -m backends.qualcomm.debugger.observatory.cli \
  --report-dir /tmp/obs_qnn_roberta \
  examples/qualcomm/oss_scripts/roberta.py \
  -m SM8650 -b ./build-android --dataset wikisent2.txt \
  -H mlgtw-linux -s bebcca9b -a Roberta_Lanai --seed 1126 --compile_only
```

Additional wiki-text LLM scripts included in batch mode:

- `examples/qualcomm/oss_scripts/bert.py`
- `examples/qualcomm/oss_scripts/albert.py`
- `examples/qualcomm/oss_scripts/distilbert.py`
- `examples/qualcomm/oss_scripts/eurobert.py`

## Batch generation

From this demo repo:

```bash
cd /path/to/Executorch_Observatory_Demo
python scripts/generate_observatory_demo.py --dry-run
```

Real generation:

```bash
python scripts/generate_observatory_demo.py --qnn-sdk-root /path/to/qairt/<version>
```

Current default behavior:

- Includes all XNN models (including `mv2`)
- Includes Qualcomm vision + wiki-text LLM models (`roberta`, `bert`, `albert`, `distilbert`, `eurobert`)
- Primary demo models are explicit:
  - XNNPack: `mv2`
  - Qualcomm: `torchvision_vit`

Useful selectors:

```bash
# Include all XNN models (including mv2)
python scripts/generate_observatory_demo.py --xnn-models all

# Run only selected Qualcomm recipes
python scripts/generate_observatory_demo.py --qualcomm-models torchvision_vit,roberta
```

QNN SDK setup behavior:

- For every Qualcomm job, the generator runs:
  - `source <qnn-sdk-root>/bin/envsetup.sh`
  - then executes the observatory command
- This avoids Qualcomm backend failures caused by missing QNN runtime environment.

Outputs:

- Reports under `generated_reports/xnnpack/...` and `generated_reports/qualcomm/...`
- Per-model logs under `generated_reports/**/run.log`
- Manifest in `generated_reports/manifest.json`
- `index.html` auto-refreshed with current links/status

## Primary journey defaults

- Primary XNN model defaults to `mv2`.
- Primary Qualcomm model defaults to `torchvision_vit`.

You can override:

```bash
python scripts/generate_observatory_demo.py \
  --primary-xnn-model resnet18 \
  --primary-qualcomm-model roberta
```

Use seeded random primary selection:

```bash
python scripts/generate_observatory_demo.py --primary-xnn-model random --primary-seed 1126
```
