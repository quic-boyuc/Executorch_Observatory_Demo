# RFC: Observatory — A Unified Debugging Framework for ExecuTorch

**Status:** Draft for review
**Authors:** Qualcomm Innovation Center, Inc.
**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure
**Draft PR:** [PR link]
**Live demo:** [Demo index link]

---

## 1. TL;DR

Observatory is a unified, extensible debugging framework that turns the scattered debugging artifacts produced by ExecuTorch compilation into a single structured, shareable report. Each kind of analysis — graph capture, per-layer accuracy, stack traces, profiling — is contributed by a **Lens**, a small Python extension that plugs into one shared workflow. Observatory ships with a standalone interactive FX-graph viewer (`fx_viewer`) that powers its graph view. Every backend gets the same report shape, the same CLI entry point, and the same place to contribute backend-specific debugging logic. The canonical output is a **JSON report** — friendly to databases, CI archives, and AI consumers — from which a self-contained HTML is rendered for human reviewers.

## 2. Goals

1. **Shared framework in `devtools/`.** Observatory core, `fx_viewer`, and generic lenses usable by any backend.
2. **Backend-extensible.** Each backend contributes its own lenses and CLI runner without forking the framework.
3. **One debugging report shape across backends.** Same left panel, same compare mode, same graph view — regardless of the backend producing it.
4. **Standalone self-contained HTML output.** No server, no authentication, no external service.
5. **JSON as a first-class format.** Machine-readable canonical output for CI archives, database storage, and AI-assisted triage; HTML is a rendering of it.

**Non-goals:** replacing Inspector / ETRecord / ETDump / bundled_program (Observatory *consumes* them); replacing `devtools/visualization/` (different purpose; see reference.md §B); mandating adoption (opt-in per backend); live real-time debugging UIs (post-hoc reports, not dashboards).

## 3. Feature Highlights

A narrative preview of the experience. Each bullet builds on the previous one: *how to run it → what you get → what's inside → what the advanced lenses add.*

**1. Zero-config command — wrap any AOT script.** Default lenses (metadata, stack trace, graph, pipeline-hook capture) are active out of the box. Opt-in deeper analysis such as accuracy via a single flag.

```bash
# Defaults — metadata, graphs at each lowering stage
python -m executorch.backends.xnnpack.debugger.observatory \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize

# Add per-layer accuracy debugging with one flag
python -m executorch.backends.xnnpack.debugger.observatory \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

[[MEDIA: png — side-by-side terminal: default run vs `--lense_recipe=accuracy`]]

**2. Single self-contained HTML — easy to share.** One file. No server, no login, no external service. Opens in any modern browser; attachable to issues, PRs, and email.

[[MEDIA: png — the generated HTML file being opened in a browser, run dashboard visible]]

**3. Graphs + metadata inside.** Interactive FX graphs at each pipeline stage, run metadata, and an N-way synchronized compare view for any pair of records. Click a node in one graph; the corresponding node highlights in every compared graph.

[[MEDIA: gif — navigating records in the left panel → compare mode with cross-graph node sync, ~8s]]

**4. Per-layer accuracy — overlay on the graph + merged table.** Opting into accuracy lenses adds per-operator PSNR / cosine / MSE as a color overlay on the graph, plus a merged per-layer metrics table. Worst-accuracy nodes stand out visually; click any node to see its full metric breakdown in the info panel.

[[MEDIA: gif — graph with per-layer PSNR color overlay + node selection → info-panel metrics, ~6s]]

## 4. Problem Statement

1. **Every backend reinvents the same debugging wheels.** Per-layer accuracy comparison exists in QNN as `backends/qualcomm/debugger/qnn_intermediate_debugger.py` (Python CPU-vs-QNN simulation, CSV/SVG output) and in XNNPACK as ad-hoc scripts. Graph dumping is scattered across `print(gm.graph)` calls and one-off log formatters. There is no shared place to contribute these tools, so each backend solves them in isolation.

2. **No interactive FX-graph view during the compile pipeline.** `torch.fx` is the core IR for ExecuTorch lowering, but `devtools/visualization/` operates on `ExportedProgram` (post-export) via a Model-Explorer web server — useful for structural browsing, not for inspecting a graph mid-pass, diffing graphs before/after a transform, or embedding graph views inside a broader debugging report.

3. **Debugging artifacts are not shareable as a package.** Captured data ends up as loose log files, CSVs, and SVGs — leftovers from a failed run rather than a coherent artifact that a teammate, reviewer, QA engineer, or external reporter can open and navigate.

## 5. Where Observatory Is Useful

Observatory is driven by the workflows it must support, not by a feature list:

1. **Developer debugging and profiling** — engineers need to quickly see what changed, where execution diverged, why a regression happened. Observatory captures the right artifacts, turns them into one inspectable report, and makes findings easy to share without reconstructing context.
2. **QA / CI triage and reproduction** — when CI finds a failure, the handoff should be a single artifact containing everything the next engineer needs.
3. **Community issue reports** — an external user hitting a bug can attach one HTML file to a GitHub issue instead of transcribing command output.
4. **AI-assisted triage** — structured JSON captured alongside the HTML lets automated pipelines reason about debugging artifacts.

## 6. Existing Devtools and Where Observatory Fits

ExecuTorch already provides the *raw materials* for debugging compilation and execution — Observatory composes with them rather than replacing any of them.

| Existing devtool | What it provides | How Observatory relates |
|---|---|---|
| Inspector API | Per-tensor comparison primitives (MSE, SNR, L1) | Consumed by `accuracy` / `per_layer_accuracy` lenses |
| ETRecord / ETDump | Runtime event and tensor capture | Future runtime lenses will consume these |
| bundled_program | Calibration data + model packaging | Used as input source for accuracy lenses |
| `devtools/visualization/` | `ExportedProgram` structural browser (Model-Explorer, web server) | Complementary — serves post-export hierarchy browsing, not in-workflow FX graphs; no HTML embed, no debugger-info API. See reference.md §B |
| Per-backend scripts (QNN debugger, XNNProfiler, ARM shell scripts) | Backend-specific accuracy / profiling / graph dumping | Subsumed, where applicable, as lenses; see §7 |

`fx_viewer` is introduced as the component that powers Observatory's `GraphBlock`: a dependency-free, standalone HTML renderer for raw FX graphs with compare mode and a Python extension API (reference.md §C).

## 7. Unification — One Framework, Many Debugging Workflows

Observatory is not a single tool for a single question. It is a framework for the class of debugging workflows that every backend has, but currently solves in isolation. The table below maps common debugging questions to the scattered state today and the lens that subsumes them:

| Debugging question | What backends do today | Observatory lens |
|---|---|---|
| "Why did accuracy regress after quantization?" | QNN: `backends/qualcomm/debugger/qnn_intermediate_debugger.py` (CPU-vs-QNN simulation, CSV/SVG). XNNPACK: ad-hoc numeric comparison scripts. | `accuracy` + `per_layer_accuracy` lenses — unified metrics (PSNR, cosine, MSE) overlaid on the graph view. |
| "What did the graph look like at each lowering stage?" | Manual `print(gm.graph)`, scattered log formatters. | `pipeline_graph_collector` lens — auto-captures graphs at standard ExecuTorch hooks. |
| "How does my graph change before/after a custom pass?" | Text diff, manual side-by-side print. | `@observe_pass` decorator + `fx_viewer` compare mode (synchronized N-way views). |
| "Where in the source did this node come from?" | Manual inspection of `node.meta["stack_trace"]`. | `stack_trace` lens — clickable source mapping in the graph info panel. |
| "Op-level perf hot spots" | QNN: QAIRT QHAS / optrace (external tool). XNNPACK: `backends/xnnpack/runtime/profiling/XNNProfiler.cpp` (C++, on-device). | Future runtime lens — same report shape, fed by ETDump. |
| "Share this debugging context with a teammate / reviewer / QA" | Bundle logs + CSVs + screenshots manually. | Single standalone HTML + JSON. |

The mechanism that makes all of this one framework is small: a **Lens protocol** with context-manager hooks and five stages — *setup → session_start → observe → digest → analyze → frontend → session_end* — plus a registration point per backend. Every debugging tool above can be expressed as one or more lenses. New backends inherit the entire surrounding workflow (CLI, report, compare mode, graph view) for free.

## 8. Demo — Zero-Config Per-Layer Accuracy Debugging

This demo shows a **zero-config, auto-collection workflow for per-layer accuracy analysis** that works out-of-the-box on XNNPACK and Qualcomm AOT examples.

### 8.1 Setup

```bash
# requires python >= 3.11
pip3 install 'fast-sugiyama[full]'
```

### 8.2 Command

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

### 8.3 What You Get — a Standalone HTML Report

Observatory emits a **self-contained HTML file** (no external dependencies beyond a modern browser). Pre-generated reports for a matrix of models:

- XNNPACK: [mv2] · [add] · [other models …]
- Qualcomm: [albert] · [bert] · [distilbert] · [eurobert] · [inception_v3] · [inception_v4] · [mobilenet_v2] · [mobilenet_v3] · [roberta] · [torchvision_vit]

*(Links populated from `generated_reports/` at submission time.)*

#### Run Dashboard

The landing page shows per-run metadata (command line, environment, input model). Each lens can contribute its own section to this page.

[[MEDIA: png — run dashboard, annotated: metadata section, command capture, env]]

#### Records and Diff Labels (Left Panel)

The left panel lists **records** — each corresponds to one Observatory collection point (think: breakpoint). Between adjacent records, **diff labels** summarize what changed (e.g., node count delta, PSNR change). Each lens can insert diff-label content via the Python API.

[[MEDIA: png — left panel showing records + diff labels, annotated]]

- Click a **record** → single-record view.
- Click a **diff label** → 2-record compare view.
- Click **Select** → N-record compare view.

[[MEDIA: gif — clicking record in left panel → single view opens, ~4s]]

[[MEDIA: gif — clicking diff label → side-by-side compare view, ~5s]]

[[MEDIA: gif — select-mode → multi-record comparison, ~5s]]

#### Lens Output

Lenses active in this demo (full descriptions in reference.md §G):

| Lens | Role |
|---|---|
| `metadata` | Run metadata on the dashboard |
| `stack_trace` | Source location of each graph node |
| `graph` | Interactive FX graph view (powered by `fx_viewer`) |
| `accuracy` | Overall per-record accuracy metrics |
| `per_layer_accuracy` | Per-operator PSNR / cosine similarity overlaid on the graph |
| `pipeline_graph_collector` | Auto-captures graphs at pipeline hooks during a session |
| `graph_color` | Coloring rules contributed to the graph view |

[[MEDIA: gif — graph view with per-layer accuracy color overlay + node selection showing PSNR, ~6s]]

## 9. Interface Design — Three Ways to Use Observatory

Observatory exposes the same framework through three invocation surfaces. Each surface matches a different debugging context.

### 9.1 CLI — for QA, CI, and community issue reporting

The CLI wraps any existing AOT script. No code change is required; default lenses (metadata, stack_trace, graph, pipeline_graph_collector) are active out of the box.

```bash
# Generic (framework lenses only)
python -m executorch.devtools.observatory \
    --output-html run.html \
    your_script.py --your-args

# Backend-specific with opt-in lens recipe
python -m executorch.backends.xnnpack.debugger.observatory \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

**Use when:** filing a bug report, reproducing a CI failure, handing work off across teams. Output is a single HTML file that anyone can open.

### 9.2 Manual Context — for targeted developer debugging

When a developer is debugging a specific pass or pipeline step, the CLI's zero-config mode is too coarse. The Python context manager lets you choose collection points, custom lens configs, and a reduced lens set precisely.

```python
from executorch.devtools.observatory import Observatory

config = {"accuracy": {"dataset": my_small_repro_set}}
with Observatory.enable_context(config=config):
    Observatory.collect("original", gm)
    transformed = my_experimental_pass(gm)
    Observatory.collect("after_my_pass", transformed)

Observatory.export_html_report("pass_debug.html")
Observatory.export_json("pass_debug.json")
```

**Use when:** iterating on a compiler pass, comparing graph states around a specific transform, running with a custom dataset or custom lens configuration. Monkey patches installed by lenses live only for the `with`-block's lifetime (via `on_session_start` / `on_session_end` hooks, see reference.md §A).

### 9.3 `@observe_pass` Decorator — for pass-centric debugging

When you want every pass in a manager to be automatically captured before-and-after, wrap the passes once.

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.pass_base import ExportPass
from executorch.exir.pass_manager import PassManager

@observe_pass
class MyPass(ExportPass):
    def call(self, gm):
        ...

pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enable_context():
    pm._transform(graph_module)

Observatory.export_html_report("pass_debug.html")
```

**Use when:** building or tuning a pass pipeline, measuring the effect of each pass in isolation.

### 9.4 Collection Points

Regardless of invocation surface, collection points come from three sources:

- **Automatic pipeline hooks** (via `pipeline_graph_collector` lens): standard ExecuTorch entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_exported_program`, `ETRecord.add_edge_dialect_program`) are monkey-patched for the duration of the Observatory session.
- **Pass decorator** (`@observe_pass`): wraps any `PassBase` subclass or instance.
- **Manual** (`Observatory.collect(name, artifact)`): explicit call anywhere.

Patch installation happens in `Lens.on_session_start`; patch restoration happens in `Lens.on_session_end`. The patches exist only during an active Observatory context.

## 10. Design Sketch

```
┌──────────────────────────────────────────────────────────┐
│                  devtools/observatory/                    │
│                                                           │
│  Runtime            Lens Protocol         Report Engine   │
│  ┌──────────┐     ┌──────────────────┐  ┌─────────────┐  │
│  │ collect  │     │ setup            │  │ HTML / JSON │  │
│  │ analyze  │◄───►│ on_session_start │  │ export      │  │
│  │ export   │     │ observe          │  └─────────────┘  │
│  └──────────┘     │ digest           │                    │
│                   │ analyze          │                    │
│                   │ frontend         │                    │
│                   │ on_session_end   │                    │
│                   └──────────────────┘                    │
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

[[MEDIA: png — rendered version of the diagram above]]

A **Lens** is a Python class whose methods hook into a fixed set of stages. Two of those stages (`on_session_start`, `on_session_end`) run at context entry/exit and are the canonical place for installing and removing monkey patches — which is how `pipeline_graph_collector` instruments the pipeline without mutating user code. The other stages (`observe`, `digest`, `analyze`, `frontend`) produce and render the lens's data. Lenses contribute graph overlays through `fx_viewer`'s `GraphExtension` API (info-panel data, labels, coloring, sync keys). The full protocol, extension API, and a worked example are in **reference.md §A–§C**.

## 11. Core Design Principle — JSON as the First-Class Report Format

Observatory treats **JSON as the canonical report format**. The HTML is a *rendering* of the JSON, not the other way around. This is reflected directly in the Lens protocol: `digest()` returns JSON-serializable data, `analyze()` takes JSON-shaped records as input, and `frontend()` produces HTML blocks from that JSON.

```
                           ┌─► stored JSON (archive, DB, AI consumer)
observe ─► digest (JSON) ──┤
                           └─► analyze (JSON in) ─► frontend (JSON → HTML)
```

Direct consequences of this design:

- **Machine- and AI-friendly by default.** A stored JSON report is queryable, diff-able, and embeddable into databases or dashboards. Automated triage pipelines do not need to scrape HTML or re-run the compile pipeline.
- **Rendering without re-execution.** `analyze()` and `frontend()` run off the stored JSON. Regenerating the HTML after a template change, a styling update, or a new version of a lens does not require re-running the AOT compile or the accuracy evaluation.
- **Cross-time regression analysis as a first-class use case.** A CI system can run Observatory nightly on a fixed model set and archive each run's JSON. A comparison lens can then take the JSONs from *two nightlies* and produce a regression HTML showing exactly what changed — without re-running either.

### Example: nightly JSON archive + on-demand regression report

```bash
# Nightly CI job — archive the JSON, HTML not required
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-json nightly/${DATE}/mv2.json \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize

# Later — produce a regression HTML from two archived JSONs,
# without re-running the compile or accuracy eval
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html
```

Because each lens's digest is structured JSON, the comparison lens reasons about specific fields — PSNR deltas, node count changes, partition differences — without parsing logs or HTML.

## 12. Future Work

- Runtime-side lenses using Inspector API and ETDump (performance, memory, crash analysis).
- Non-FX graph formats (Pytorch graph, QNN graph, TOSA) as first-class `fx_viewer` exporters.
- Port existing backend tools to the lens protocol (QNN QHAS profiling, XNNProfiler aggregation).
- Device-side profiling lenses (ADB capture, on-device perf traces).

## 13. Reference Material

All API and structural detail lives in **[reference.md](./reference.md)**:

- §A — Lens protocol (full)
- §B — `devtools/visualization/` (Model-Explorer) vs `fx_viewer` feature comparison
- §C — `fx_viewer` extension API (info panel, labels, coloring, sync, full example)
- §D — CLI reference (generic + Qualcomm + XNNPACK)
- §E — Directory structure (matches `~/executorch` at the draft PR)
- §F — Backend extension pattern (patches + custom lenses)
- §G — Lens catalog (shipped lenses)
- §H — Maintenance and collaboration strategy
- §I — Open questions
