# RFC: Observatory — A Unified Debugging Framework for ExecuTorch

**Status:** Draft for review
**Authors:** Qualcomm Innovation Center, Inc.
**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure
**Draft PR:** [PR link]
**Live demo:** [Demo index link]

---

## TL;DR

Observatory is a unified, extensible debugging framework that turns the scattered debugging artifacts produced by ExecuTorch compilation into a single structured, shareable report. Each kind of analysis — graph capture, per-layer accuracy, stack traces, profiling — is contributed by a **Lens**, a small Python extension that plugs into one shared workflow. Observatory ships with a standalone interactive FX-graph viewer (`fx_viewer`) that powers its graph view. The result: every backend gets the same report shape, the same CLI entry point, and the same place to contribute backend-specific debugging logic, while still emitting a self-contained HTML artifact anyone can open in a browser.

[[MEDIA: hero-gif — record navigation + fx_viewer compare mode, ~8s — shows the unified report in action]]

---

## 1. Background

ExecuTorch already provides the *raw materials* for debugging model compilation and execution:

- **Inspector API, ETRecord, ETDump, bundled_program** — capture intermediate tensors, graphs, runtime events, and calibration data.
- **`devtools/visualization/`** — renders `ExportedProgram` / `EdgeProgramManager` using Google's Model-Explorer for hierarchical structural browsing.
- **Per-backend scripts** — each backend has evolved its own debugging tooling: QNN's `qnn_intermediate_debugger.py`, XNNPACK's `XNNProfiler`, ARM's on-device shell scripts, etc.

What is missing is **workflow glue**: a practical way to capture these artifacts across a compile pipeline, store them coherently, analyze them consistently, present the result as an interactive artifact, and let each backend contribute the pieces only they can write — without each team rebuilding the surrounding framework.

## 2. Problem Statement

1. **Every backend reinvents the same debugging wheels.** Per-layer accuracy comparison exists in QNN as `qnn_intermediate_debugger.py` (Python CPU-vs-QNN simulation, CSV/SVG output) and in XNNPACK as ad-hoc scripts. Graph dumping is scattered across `print(gm.graph)` calls and one-off log formatters. There is no shared place to contribute these tools, so each backend solves them in isolation.

2. **No interactive FX-graph view during the compile pipeline.** `torch.fx` is the core IR for ExecuTorch lowering, but `devtools/visualization/` operates on `ExportedProgram` (post-export) via a Model-Explorer web server — useful for structural browsing, not for inspecting a graph mid-pass, diffing graphs before/after a transform, or embedding graph views inside a broader debugging report.

3. **Debugging artifacts are not shareable as a package.** Captured data ends up as loose log files, CSVs, and SVGs — leftovers from a failed run rather than a coherent artifact that a teammate, reviewer, QA engineer, or external reporter can open and navigate.

## 3. Goals

1. **Shared framework in `devtools/`.** Observatory core, fx_viewer, and generic lenses usable by any backend.
2. **Backend-extensible.** Each backend contributes its own lenses and CLI runner without forking the framework.
3. **One debugging report shape across backends.** Same left panel, same compare mode, same graph view — regardless of the backend producing it.
4. **Standalone self-contained HTML output.** No server, no authentication, no external service. The report is a file.
5. **Foundation for automation.** Structured JSON alongside HTML enables programmatic analysis and AI-assisted triage.

## 4. Non-Goals

- Replacing Inspector / ETRecord / ETDump / bundled_program — Observatory *consumes* these primitives.
- Replacing `devtools/visualization/` — it serves a different purpose (hierarchical post-export browsing). See reference.md §B for the feature comparison.
- Mandating adoption — the framework is opt-in per backend.
- Live / real-time debugging UIs — Observatory produces post-hoc reports, not dashboards.

## 5. Relation to Existing Devtools

Observatory composes with, and does not replace, what is already there:

| Existing devtool | What it provides | Observatory's use of it |
|---|---|---|
| Inspector API | Per-tensor comparison primitives (MSE, SNR, L1) | Consumed by `accuracy` / `per_layer_accuracy` lenses |
| ETRecord / ETDump | Runtime event and tensor capture | Future runtime lenses will consume these |
| bundled_program | Calibration data + model packaging | Used as input source for accuracy lenses |
| `devtools/visualization/` | ExportedProgram structural browser (Model-Explorer) | Complementary; see reference.md §B |

`fx_viewer` is introduced as the component that powers Observatory's `GraphBlock`: a dependency-free, standalone HTML renderer for raw FX graphs with compare mode and a Python extension API. See reference.md §C.

---

## 6. Demo — Zero-Config Per-Layer Accuracy Debugging

This demo shows a **zero-config, auto-collection workflow for per-layer accuracy analysis** that works out-of-the-box on XNNPACK and Qualcomm AOT examples.

### 6.1 Setup

Prepare the standard ExecuTorch dev environment for your target backend, then install the layout engine dependency:

```bash
# requires python >= 3.11
pip3 install 'fast-sugiyama[full]'
```

### 6.2 Command

Any existing AOT script can be wrapped with `observatory.cli` — no code changes. The `--lense_recipe=accuracy` flag opts into the accuracy lenses.

```bash
# XNNPACK — aot_compiler.py auto-detected as module via __init__.py
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2

# Qualcomm
python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lense_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

### 6.3 What You Get — a Standalone HTML Report

Observatory emits a **self-contained HTML file** (no external dependencies beyond a modern browser). Pre-generated reports for a matrix of models are here:

- XNNPACK: [mv2] · [add] · [other models …]
- Qualcomm: [albert] · [bert] · [distilbert] · [eurobert] · [inception_v3] · [inception_v4] · [mobilenet_v2] · [mobilenet_v3] · [roberta] · [torchvision_vit]

*(Links will be populated from `generated_reports/` at submission time.)*

#### Run Dashboard

The landing page shows per-run metadata (command line, environment, input model). Each lens can contribute its own section to this page via the Python API.

[[MEDIA: png — run dashboard, annotated: metadata section, command capture, env]]

#### Records and Diff Labels (Left Panel)

The left panel lists **records** — each corresponds to one Observatory collection point (think: breakpoint). Between adjacent records, **diff labels** summarize what changed (e.g., node count delta, PSNR change). Each lens can insert diff-label content via the Python API.

[[MEDIA: png — left panel showing records + diff labels, annotated]]

- Click a **record** → single-record view in the main area.
- Click a **diff label** → 2-record compare view.
- Click **Select** at the top of the panel → N-record compare view.

[[MEDIA: gif — clicking record in left panel → single view opens, ~4s]]

[[MEDIA: gif — clicking diff label → side-by-side compare view, ~5s]]

[[MEDIA: gif — select-mode → multi-record comparison, ~5s]]

#### Lens Output

Lenses active in this demo:

| Lens | Role |
|---|---|
| `metadata` | Run metadata on the dashboard |
| `stack_trace` | Source location of each graph node |
| `graph` | Interactive FX graph view (powered by fx_viewer) |
| `accuracy` | Overall per-record accuracy metrics |
| `per_layer_accuracy` | Per-operator PSNR / cosine similarity overlaid on the graph |
| `pipeline_graph_collector` | Auto-captures graphs at pipeline hooks (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, …) |
| `graph_color` | Coloring rules contributed to the graph view |

[[MEDIA: gif — graph view with per-layer accuracy color overlay + node selection showing PSNR, ~6s]]

---

## 7. The Unification — One Framework, Many Debugging Workflows

Observatory is not a single tool for a single question. It is a framework for the class of debugging workflows that every backend has, but currently solves in isolation. The table below maps common debugging questions to the scattered state today and the lens that subsumes them:

| Debugging question | What backends do today | Observatory lens |
|---|---|---|
| "Why did accuracy regress after quantization?" | QNN: `backends/qualcomm/debugger/qnn_intermediate_debugger.py` (CPU-vs-QNN simulation, CSV/SVG out). XNNPACK: ad-hoc numeric comparison scripts. | `accuracy` + `per_layer_accuracy` lenses — unified metrics (PSNR, cosine, MSE) overlaid on the graph view. |
| "What did the graph look like at each lowering stage?" | Manual `print(gm.graph)`, scattered log formatters. | `pipeline_graph_collector` lens — auto-captures graphs at standard ExecuTorch hooks. |
| "How does my graph change before/after a custom pass?" | Text diff, manual side-by-side print. | `@observe_pass` decorator + fx_viewer compare mode (synchronized N-way views). |
| "Where in the source did this node come from?" | Manual inspection of `node.meta["stack_trace"]`. | `stack_trace` lens — clickable source mapping in the graph info panel. |
| "Op-level perf hot spots" | QNN: QAIRT QHAS / optrace (external tool). XNNPACK: `backends/xnnpack/runtime/profiling/XNNProfiler.cpp` (C++, on-device). | Future runtime lens — same report shape, fed by ETDump. |
| "Share this debugging context with a teammate / reviewer / QA" | Bundle logs + CSVs + screenshots manually. | Single standalone HTML report + JSON. |

The mechanism that makes all of this one framework is small: a **Lens protocol** with five stages — *setup → observe → digest → analyze → frontend* — plus a registration point per backend. Every debugging tool above can be expressed as one or more lenses. New backends inherit the entire surrounding workflow (CLI, report, compare mode, graph view) for free.

---

## 8. Design Sketch

```
┌──────────────────────────────────────────────────────────┐
│                  devtools/observatory/                    │
│                                                           │
│  Runtime            Lens Protocol         Report Engine   │
│  ┌──────────┐     ┌──────────────┐      ┌─────────────┐  │
│  │ collect  │     │ setup        │      │ HTML / JSON │  │
│  │ analyze  │◄───►│ observe      │      │ export      │  │
│  │ export   │     │ digest       │      └─────────────┘  │
│  └──────────┘     │ analyze      │                        │
│                   │ frontend     │                        │
│                   └──────────────┘                        │
│  Generic Lenses: graph · metadata · accuracy ·            │
│                  per_layer_accuracy · stack_trace ·       │
│                  pipeline_graph_collector · graph_color   │
│                                                           │
│                  devtools/fx_viewer/                      │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Python: exporter · extension API · color rules    │   │
│  │  JS runtime: canvas · minimap · search · compare   │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
┌────────┴────┐    ┌─────────┴──────┐    ┌────────┴──────┐
│ QNN CLI     │    │ XNNPACK CLI    │    │ ARM / …       │
│ QNN lenses  │    │ XNNPACK lenses │    │ backend       │
│ backends/   │    │ backends/      │    │ lenses        │
│ qualcomm/   │    │ xnnpack/       │    │               │
│ debugger/   │    │ debugger/      │    │               │
│ observatory │    │ observatory    │    │               │
└─────────────┘    └────────────────┘    └───────────────┘
```

[[MEDIA: png — same diagram as a polished image if we want to replace the ASCII with a rendered version]]

A **Lens** is a Python class that participates in one or more workflow stages:

- **setup** — one-time initialization.
- **observe** — intercept artifacts during script execution (e.g., wrap `to_edge_transform_and_lower`).
- **digest** — convert observations into JSON-serializable records.
- **analyze** — compute derived data across records (e.g., per-layer accuracy between two snapshots).
- **frontend** — declare the block types (Table / Html / Custom / Graph) that appear in the report.

Each backend registers a small CLI entry point and a set of lenses. Lenses contribute graph overlays through `fx_viewer`'s `GraphExtension` API (info-panel data, labels, coloring, sync keys). The full protocol, extension API, and a worked example are in **reference.md §A–§C**.

---

## 9. Use Cases Driving the Design

Observatory is driven by the workflows it must support, not by a feature list:

1. **Developer debugging and profiling** — engineers need to quickly see what changed, where execution diverged, why a regression happened. Observatory captures the right artifacts, turns them into one inspectable report, and makes findings easy to share without reconstructing context.
2. **QA / CI triage and reproduction** — when CI finds a failure, the handoff should be a single artifact that contains everything the next engineer needs.
3. **Community issue reports** — an external user hitting a bug can attach one HTML file to a GitHub issue instead of transcribing command output.
4. **AI-assisted triage** — structured JSON captured alongside the HTML lets automated pipelines reason about debugging artifacts.

## 10. Adoption Plan

| Phase | Work |
|---|---|
| 1 | Move `fx_viewer` from `backends/qualcomm/utils/` to `devtools/fx_viewer/` |
| 2 | Move Observatory core + generic lenses to `devtools/observatory/` |
| 3 | Split backend-specific patches into `backends/qualcomm/debugger/observatory/` and `backends/xnnpack/debugger/observatory/` |
| 4 | Ship generic CLI (`python -m executorch.devtools.observatory`) and backend CLIs (Qualcomm, XNNPACK) |
| 5 | Update all imports; move tests; delete old paths |

**Breaking changes:** imports move from `executorch.backends.qualcomm.*` to `executorch.devtools.*`. Clean break, no shims. See reference.md §D.

## 11. Future Work

- Runtime-side lenses using Inspector API and ETDump (performance, memory, crash analysis).
- Non-FX graph formats (Pytorch graph, QNN graph, TOSA) as first-class `fx_viewer` exporters.
- Port existing backend tools to the lens protocol (QNN QHAS profiling, XNNProfiler aggregation).
- Device-side profiling lenses (ADB capture, on-device perf traces).

---

## 12. Reference Material

All API and structural detail has been moved to **[reference.md](./reference.md)**:

- §A — Full Lens protocol
- §B — `devtools/visualization/` (Model-Explorer) vs `fx_viewer` feature comparison
- §C — `fx_viewer` extension API (info panel, labels, coloring, sync, full example)
- §D — CLI reference (generic + Qualcomm + XNNPACK)
- §E — Directory structure (matches `~/executorch` at the draft PR)
- §F — Backend extension pattern (patches + custom lenses)
- §G — Alternatives considered
- §H — Risk analysis and test strategy
- §I — Open questions
