# RFC Reference — Observatory & fx_viewer

> Companion to [rfc.md](./rfc.md). This document holds the API surface, structural detail, lens catalog, and collaboration policy. Read rfc.md first for the motivation, demo, and proposal.

---

## §A — Lens Protocol

### A.0 JSON as the Canonical Report Format

Observatory's data model is **JSON-first by design**. The Lens protocol's stages are shaped around JSON as the contract between them:

- `digest()` returns JSON-serializable data — this is the canonical representation of a lens's observation for a single record.
- `analyze()` takes the collected JSON records as input and produces derived JSON (cross-record comparisons, per-layer tables, regression deltas, etc.).
- `frontend()` consumes the JSON produced by `analyze()` and declares report blocks; the HTML renderer transforms that JSON into the final standalone HTML.

```
                           ┌─► stored JSON (archive, DB, AI consumer)
observe ─► digest (JSON) ──┤
                           └─► analyze (JSON in) ─► frontend (JSON → HTML)
```

Direct consequences:

1. `Observatory.export_json()` is **not a debug dump**; it is the canonical report. The HTML is a rendering of it.
2. HTML can be regenerated from stored JSON without re-running observation — useful when a template update, a styling change, or a new version of a lens's `frontend()` ships.
3. Cross-time regression analysis is a first-class use case: a comparison lens consumes N archived JSON files and emits a regression HTML, with no re-observation needed. See rfc.md §8.2 for a worked example.
4. Machine and AI triage consumers read the JSON directly — no HTML scraping required.

The protocol below is shaped by this data flow.

### A.1 Class Contract

A **Lens** is a Python class that participates in stages of the Observatory workflow. A minimal lens implements only the stages it needs; the framework ignores the rest.

```python
class Lens:
    # ── Registration ──────────────────────────────────────────
    @classmethod
    def setup(cls) -> None:
        """One-time initialization at lens registration (before any session)."""

    # ── Session lifecycle (context-manager hooks) ────────────
    @classmethod
    def on_session_start(cls, context) -> None:
        """Called when an Observatory context is entered.
        Primary place for installing monkey patches that intercept
        framework functions during the debugging session."""

    @classmethod
    def on_session_end(cls, context) -> None:
        """Called when the Observatory context exits.
        Restore any installed patches and clear per-session state."""

    # ── Per-collection ───────────────────────────────────────
    @classmethod
    def observe(cls, artifact, context) -> Any:
        """Capture: intercept artifacts at each Observatory.collect() call."""

    @classmethod
    def digest(cls, observation, context) -> Serializable:
        """Store: convert observation into JSON-serializable form."""

    # ── Report generation ────────────────────────────────────
    @staticmethod
    def analyze(records, config) -> AnalysisResult:
        """Analyze: compute derived data across records (at export time)."""

    @staticmethod
    def get_frontend_spec() -> Frontend:
        """Visualize: declare report blocks (Table / Html / Custom / Graph)
        contributed by this lens, including record-view and compare-view semantics."""
```

### A.2 Workflow and Session Lifecycle

1. **Registration** — `setup()` runs once per process when the lens is registered. One-time initialization such as loading reference data or registering helpers.
2. **Session start** — `on_session_start()` runs when the user enters the Observatory context (CLI bootstrap, `with Observatory.enable_context():`, or first use of `@observe_pass`). **Monkey patches must be installed here**, not at module import time, so they are scoped to a single debugging session. `pipeline_graph_collector` uses this hook to patch `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_exported_program`, `ETRecord.add_edge_dialect_program`, and any backend-registered patches.
3. **Per-collection** — `observe()` / `digest()` run at each `Observatory.collect()` call.
4. **Analyze** — `analyze()` runs once at report export, over all collected records.
5. **Frontend** — `get_frontend_spec()` is consumed by the report engine to produce the HTML and JSON.
6. **Session end** — `on_session_end()` runs on context exit (even on exception). **All patches installed in `on_session_start` must be undone here**, and per-session class state cleared. This guarantees that Observatory sessions are reentrant and non-leaky.

Lenses that do not monkey-patch anything can omit `on_session_start` / `on_session_end` entirely.

### A.3 Frontend Block Types

| Block | Purpose | Single-record view | Compare view |
|---|---|---|---|
| `TableBlock` | Key-value data | 2-column table | Auto side-by-side diff |
| `HtmlBlock` | Arbitrary HTML fragment | Inline render | Auto side-by-side |
| `CustomBlock` | Custom JS-rendered widget | Lens-provided JS | Lens-provided JS or auto |
| `GraphBlock` | FX graph, via `fx_viewer` | Interactive single graph | Synchronized N-way compare |

### A.4 How Lenses Contribute to the Graph View

`GraphBlock` is powered by `fx_viewer`. A lens contributes a graph *overlay* by producing a `GraphExtension` (§C) in `analyze` and returning it via `AnalysisResult.graph_layers`. Extensions become toggleable layers in the viewer — same graph, multiple coloring / labeling / sync semantics at the same time.

---

## §B — `devtools/visualization/` vs `fx_viewer`

The two tools are complementary, not competing. They differ in input form, rendering backend, dependency footprint, and intended use stage. The key limitation of `devtools/visualization/` from Observatory's perspective is the **lack of HTML embed ability and the lack of an API for integrating arbitrary debugger-contributed data into the view** — both essential for a report-centric, end-to-end debugging workflow.

| Aspect | `devtools/visualization/` | `devtools/fx_viewer/` |
|---|---|---|
| Input | `ExportedProgram` / `EdgeProgramManager` / `ExecutorchProgramManager` | `torch.fx.GraphModule` (any FX graph, any dialect) |
| Rendering | Launches Google Model-Explorer (web server + browser tab) | Renders to a **standalone HTML file**, embeddable in any page |
| Embed in a larger report | Not supported — opens its own tab / server | First-class — Observatory's `GraphBlock` embeds the viewer |
| Debugger-info integration API | Limited — `add_node_data()` + regex style JSON; no typed extension model, no sync-key mechanism, no lens-driven overlay layers | `GraphExtension` with color rules, label formatters, tooltip formatters, sync keys, info-panel data; consumed by lenses |
| Dependencies | `ai-edge-model-explorer>=0.1.16` (heavy; known `numpy<2` vs ExecuTorch's `numpy>=2` conflict) | `fast-sugiyama` (pure Python layout) — nothing else |
| Invocation | Python API only (`Tester(model).export().visualize()`) | Python API + file output; consumed by Observatory's `GraphBlock` |
| Compare / diff | Not supported | N-way synchronized compare with `debug_handle` / `from_node` sync |
| Native FX-graph support | No (requires export step) | Yes (any `GraphModule`, any dialect) |
| Hierarchical / module collapse | Yes (Model-Explorer built-in) | Flat view + search (module hierarchy not yet supported) |
| Intended use stage | Post-export structural browsing | In-workflow debugging of FX graphs during compile passes |
| Output shareability | Server-backed; JSON save for deferred viewing | Single self-contained HTML — attachable to issues, email, chat |

**When to use which**

- `visualization/` — "I want to browse the final structure of my exported model with module hierarchy, hosted in Model-Explorer."
- `fx_viewer` — "I want to see the raw FX graph at each stage of a compile pipeline, diff it across passes, annotate nodes with custom lens analysis, and embed the result in a shareable report."

---

## §C — fx_viewer Extension API

`GraphExtension` is the unit of customization. Each extension becomes a togglable layer in the viewer. Lenses create extensions during their `analyze` phase to overlay per-node data, labels, colors, and cross-graph sync keys onto the graph view.

### §C.1 Info-Panel Data (per-node key-value)

```python
from executorch.devtools.fx_viewer.extension import GraphExtension

accuracy_ext = GraphExtension(id="per_layer_accuracy", name="Per-Layer Accuracy")

for node_id, metrics in per_node_results.items():
    accuracy_ext.add_node_data(node_id, {
        "psnr_db": f"{metrics['psnr']:.2f}",
        "cosine_similarity": f"{metrics['cosine']:.4f}",
        "mse": f"{metrics['mse']:.6f}",
        "sample_index": metrics["worst_sample_idx"],
    })
```

Info panel on selection:

```
── Base ──
op: call_function
target: aten::conv2d.default
tensor_shape: [1, 64, 224, 224]

── Per-Layer Accuracy ──
psnr_db: 42.31
cosine_similarity: 0.9987
mse: 0.000012
sample_index: 7
```

### §C.2 Custom Labels and Tooltips

```python
accuracy_ext.set_label_formatter(
    lambda node_data: [f"PSNR: {node_data.get('psnr_db', 'N/A')}"]
)

accuracy_ext.set_tooltip_formatter(
    lambda node_data: [
        f"PSNR: {node_data.get('psnr_db', 'N/A')} dB",
        f"Cosine: {node_data.get('cosine_similarity', 'N/A')}",
        f"Worst sample: #{node_data.get('sample_index', '?')}",
    ]
)
```

Rendered node:

```
┌──────────────────┐
│    conv2d        │  ← base label
│  PSNR: 42.31     │  ← extension label
└──────────────────┘
```

### §C.3 Custom Coloring

`ColorRule` subclasses define how nodes are colored when the user picks a layer as the active color-by view.

- **`NumericColorRule`** — maps a continuous metric to a gradient (viridis, reds, blues, greens). Ideal for accuracy / perf metrics.
- **`CategoricalColorRule`** — maps discrete values to deterministic hues via MD5→HSV. Ideal for op types, backend assignments, partitions.

```python
from executorch.devtools.fx_viewer.color_rules import NumericColorRule, CategoricalColorRule

accuracy_ext.set_color_rule(NumericColorRule(
    field="psnr_db",
    palette="reds_reversed",   # low = dark red, high = light
    label="PSNR (dB)",
))

backend_ext = GraphExtension(id="backend", name="Backend Assignment")
backend_ext.set_color_rule(CategoricalColorRule(field="backend"))
```

### §C.4 Sync Keys (Compare Mode)

```python
# Match nodes across graphs by their original source node reference
accuracy_ext.set_sync_key("from_node")
```

Clicking a node in Graph A auto-selects the matching node in Graph B, even if node IDs differ after fusion or decomposition.

### §C.5 Full Example — Per-Layer Accuracy Lens

```python
from executorch.devtools.fx_viewer.extension import GraphExtension
from executorch.devtools.fx_viewer.color_rules import NumericColorRule
from executorch.devtools.observatory.interfaces import (
    AnalysisResult, RecordAnalysis, GraphLayerContribution,
)

class PerLayerAccuracyLens(Lens):
    @staticmethod
    def analyze(records, config) -> AnalysisResult:
        result = AnalysisResult()

        for record_name, record in records.items():
            ext = GraphExtension(id="per_layer_accuracy", name="Per-Layer Accuracy")

            # (1) Per-node info panel data
            for node_id, metrics in compute_metrics(record).items():
                ext.add_node_data(node_id, {
                    "psnr_db": f"{metrics['psnr']:.2f}",
                    "cosine": f"{metrics['cosine']:.4f}",
                })

            # (2) Labels
            ext.set_label_formatter(lambda d: [f"PSNR: {d.get('psnr_db', '')}"])

            # (3) Coloring
            ext.set_color_rule(NumericColorRule(
                field="psnr_db", palette="reds_reversed", label="PSNR (dB)"
            ))

            # (4) Cross-graph sync for compare mode
            ext.set_sync_key("from_node")

            # (5) Contribute the layer
            result.per_record[record_name] = RecordAnalysis(
                graph_layers=[GraphLayerContribution(extension=ext)]
            )

        return result
```

One extension produces: colored nodes, PSNR labels, info-panel metrics, cross-graph sync — all from Python, no JavaScript.

---

## §D — CLI Reference

### D.1 Generic CLI (framework lenses only)

```bash
python -m executorch.devtools.observatory \
    --output-html OUT.html \
    SCRIPT [ARGS...]
```

Default lenses: `metadata`, `stack_trace`, `graph`, `pipeline_graph_collector`, `graph_color`.

### D.2 Manual (Python API)

```python
from executorch.devtools.observatory import Observatory

model = MyModel().eval()
graph = torch.fx.symbolic_trace(model)

with Observatory.enable_context():
    Observatory.collect("original", graph)
    transformed = my_pass(graph)
    Observatory.collect("after_my_pass", transformed)

Observatory.export_html_report("pass_debug.html")
Observatory.export_json("pass_debug.json")
```

### D.3 Pass Decorator

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.pass_base import ExportPass
from executorch.exir.pass_manager import PassManager
from executorch.exir.passes.remove_graph_asserts_pass import RemoveGraphAssertsPass

@observe_pass
class MyPass(ExportPass):
    def call(self, gm):
        return gm

pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enable_context():
    pm._transform(graph_module)

Observatory.export_html_report("pass_debug.html")
```

### D.4 Auto-Hooks

`pipeline_graph_collector` (active by default) installs monkey patches in its `on_session_start` hook and restores them in `on_session_end`. The patched entry points:

- `prepare_pt2e`
- `convert_pt2e`
- `to_edge_transform_and_lower`
- `ETRecord.add_exported_program`
- `ETRecord.add_edge_dialect_program`
- backend-specific patches registered via `PipelineGraphCollectorLens.register_backend_patches(...)`

### D.5 Backend CLIs

**Qualcomm**

```bash
# Default (graph collection only)
python -m executorch.backends.qualcomm.debugger.observatory SCRIPT [ARGS...]

# With accuracy lenses
python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lense_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

**XNNPACK**

> Note: `examples/xnnpack/aot_compiler.py` uses relative imports (`from . import ...`), so it must be run as a module. The Observatory CLI auto-detects this when a file path is passed and its directory contains `__init__.py`.

```bash
# File path (auto-detected as module)
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2

# Equivalent: explicit dotted module name
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples.xnnpack.aot_compiler \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2
```

---

## §E — Directory Structure

Derived from the current draft PR state in `~/executorch/`.

```
devtools/
├── fx_viewer/
│   ├── README.md
│   ├── API_IMPLEMENTATION_STATUS.md
│   ├── __init__.py
│   ├── color_rules.py
│   ├── exporter.py
│   ├── extension.py
│   ├── models.py
│   ├── examples/
│   │   ├── FX_VIEWER_API_TESTCASES.md
│   │   ├── PYTHON_API_TUTORIAL.md
│   │   ├── demo_3graph_compare.py
│   │   ├── demo_fx_viewer_extensions.py
│   │   ├── demo_per_layer_accuracy_fx.py
│   │   ├── generate_api_test_harness.py
│   │   ├── harness_template.html
│   │   └── harness_testcases.py
│   └── templates/
│       ├── README.md
│       ├── canvas_renderer.js
│       ├── compare.js
│       ├── fx_graph_viewer.js
│       ├── graph_data_store.js
│       ├── minimap_renderer.js
│       ├── runtime.js
│       ├── search_engine.js
│       ├── ui_manager.js
│       └── view_controller.js
│
└── observatory/
    ├── README.md
    ├── REFERENCE.md
    ├── USAGE.md
    ├── __init__.py
    ├── __main__.py
    ├── cli.py
    ├── graph_hub.py
    ├── html_template.py
    ├── interfaces.py
    ├── observatory.py
    ├── observe_pass.py
    ├── template_loader.py
    ├── utils.py
    ├── lenses/
    │   ├── LENSES.md
    │   ├── __init__.py
    │   ├── accuracy.py
    │   ├── graph.py
    │   ├── graph_color.py
    │   ├── metadata.py
    │   ├── per_layer_accuracy.py
    │   ├── pipeline_graph_collector.py
    │   └── stack_trace.py
    ├── templates/
    │   ├── css/main.css
    │   └── js/
    │       ├── 00_state.js
    │       ├── 01_utils.js
    │       ├── 02_layout.js
    │       ├── 03_blocks.js
    │       ├── 04_actions.js
    │       └── 05_bootstrap_api.js
    └── tests/
        ├── test_graph_hub.py
        ├── test_graph_payload_relayout.py
        ├── test_observatory_smoke.py
        ├── test_observe_pass.py
        └── test_per_layer_accuracy_lens.py

backends/qualcomm/debugger/observatory/
├── README.md
├── __init__.py
├── __main__.py
├── cli.py
└── lenses/
    ├── __init__.py
    ├── qnn_dataset_patches.py
    └── qnn_patches.py

backends/xnnpack/debugger/observatory/
├── README.md
├── __init__.py
├── __main__.py
├── cli.py
└── lenses/
    ├── __init__.py
    └── xnnpack_patches.py
```

Layout-engine dependency for `fx_viewer`: `pip install 'fast-sugiyama[full]'` (Python ≥ 3.11).

---

## §F — Backend Extension Pattern

A backend integrates with Observatory in two ways:

### F.1 Backend Patches — Hook Into Shared Lenses

When a shared lens needs backend-specific interception (e.g., to capture a graph at a backend-owned lowering entry point), the backend registers patches that the shared lens invokes during `on_session_start`.

```python
# backends/qualcomm/debugger/observatory/cli.py
from executorch.devtools.observatory.lenses.pipeline_graph_collector import (
    PipelineGraphCollectorLens,
)
from .lenses.qnn_patches import install_qnn_patches

PipelineGraphCollectorLens.register_backend_patches(install_qnn_patches)
```

Backend patches are installed *after* framework patches on `on_session_start` and uninstalled in reverse order on `on_session_end`, avoiding import-order alias issues.

### F.2 Custom Lenses — Backend-Specific Analysis

For analysis that only makes sense on one backend, the backend implements a lens subclass and registers it in its CLI.

```python
# backends/arm/debugger/observatory/lenses/ethos_u_profiling.py
from executorch.devtools.observatory.interfaces import Lens

class EthosUProfilingLens(Lens):
    @classmethod
    def get_name(cls) -> str:
        return "ethos_u_profiling"

    @classmethod
    def on_session_start(cls, context): ...
    @classmethod
    def observe(cls, artifact, context): ...
    @staticmethod
    def analyze(records, config): ...
    @staticmethod
    def get_frontend_spec(): ...
    @classmethod
    def on_session_end(cls, context): ...
```

### F.3 CLI Composition

Each backend CLI is a thin wrapper (~80 lines in the Qualcomm reference) that:

1. Registers patches for any shared lenses it needs.
2. Declares a mapping from `--lense_recipe` values to lens sets.
3. Delegates to the generic Observatory runner.

See `backends/qualcomm/debugger/observatory/cli.py` as the reference implementation.

---

## §G — Lens Catalog

The generic lenses shipped in `devtools/observatory/lenses/`. Fuller descriptions live in `devtools/observatory/lenses/LENSES.md`; this section summarizes them for the RFC reader.

Lenses are grouped as **main-section** (produce top-level report blocks) and **supporting** (contribute overlays or orchestration to other lenses).

### G.1 `metadata` — Main section

**What it does.** Captures each collected artifact's type (`GraphModule`, `ExportedProgram`, etc.), node count, and execution environment metadata; surfaces it on the run dashboard and on per-record views.

**How it works.** Implements `observe()` only. On each `Observatory.collect()`, inspects the artifact and records framework, shape, node count. No patches, no session state.

**Config.** None.

**Output.** `TableBlock` per record; aggregated summary on the run dashboard.

### G.2 `graph` — Main section

**What it does.** Renders an interactive FX graph for every collected artifact, powered by `fx_viewer`.

**How it works.** `observe()` receives graph artifacts and stores them. `analyze()` invokes `fx_viewer`'s exporter to produce layout JSON plus extension layers contributed by other lenses (`graph_color`, `per_layer_accuracy`, …).

**Config.** User selects active color-by layer in the viewer UI.

**Output.** `GraphBlock` per record; compare mode synchronizes N graphs.

### G.3 `stack_trace` — Main section

**What it does.** Captures the repo-local Python stack at each collection point, so users can see which line in their script produced each graph snapshot.

**How it works.** `observe()` extracts the current call stack, filters to repo-local frames, stores `(file, line, func)` tuples.

**Config.** None.

**Output.** Metadata entries surfaced in the record detail panel and graph node info panel where applicable.

### G.4 `pipeline_graph_collector` — Supporting (orchestrator)

**What it does.** Automatically collects graph snapshots at ExecuTorch's standard pipeline entry points by monkey-patching them for the session's lifetime. Enables the zero-config workflow.

**How it works.** `on_session_start()` installs patches on `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_exported_program`, `ETRecord.add_edge_dialect_program`, plus any backend-registered patches. Each patch invokes `Observatory.collect()` before delegating to the original. `on_session_end()` restores all originals in reverse order. Also owns `_last_calibration_dataset` as a fallback input for accuracy lenses.

**Config.** Backend patches registered via `register_backend_patches()`.

**Output.** None directly — provides the records other lenses consume.

**Dependencies.** Must run first in session start. Backend patches install after framework patches to avoid import-order aliases.

### G.5 `accuracy` — Main section

**What it does.** Evaluates model accuracy at each pipeline stage using a calibration/validation dataset and standard metrics (PSNR, TopK, MaskedTokenAccuracy, CosineSimilarity, MSE, AbsErr); reports mean + min/max per metric + worst-sample indices.

**How it works.** Lazy-initializes on the "Exported Float" record: extracts the float model, auto-detects task type (classification vs. MLM), post-processing (logits extraction, tuple unpacking), and metric set; then runs evaluation on every subsequent record. Exposes worst-sample indices via class state `_worst_indices` for downstream lenses.

**Config.** `config["accuracy"]["dataset"]` (defaults to the dataset captured by `pipeline_graph_collector._last_calibration_dataset`); optional custom evaluator via `config["accuracy"]["evaluator"]`.

**Output.** Three `TableBlock`s: `accuracy_table` (means), `accuracy_stats_table` (per-metric min/max), `accuracy_worst_idx_table` (worst-sample indices).

**Dependencies.** Registers after `pipeline_graph_collector` (reads its dataset fallback). Must register before `per_layer_accuracy` (provides `_worst_indices`).

### G.6 `per_layer_accuracy` — Supporting (overlay + table)

**What it does.** Computes sparse per-operator metrics (PSNR, Cosine, MSE, AbsErr) between an anchor graph (default: "Exported Float") and each collected graph; overlays them on the graph view as color layers and renders a merged per-layer metrics table.

**How it works.** `observe()` pairs nodes across graphs using a sparse key map (`root:<from_node_root>` or `id:<node_name>`), selects a sample via config or `AccuracyLens._worst_indices`, runs per-node inference, and emits layer names `per_layer_accuracy/{metric}` for graph coloring. `analyze()` produces a merged table with column-specific coloring (low PSNR/cosine = red, high MSE/AbsErr = red).

**Config.** `config["per_layer_accuracy"]["anchor_record_name"]` (default `"Exported Float"`), optional `sample_index`, optional `worst_metric_priority` list.

**Output.** `GraphExtension` layers in the `graph` lens's view; `TableBlock` (`per_layer_accuracy_table`).

**Dependencies.** Requires `graph` lens (viewer) and `accuracy` lens (worst-indices). Anchor record must be captured by `pipeline_graph_collector`.

### G.7 `graph_color` — Supporting (overlay)

**What it does.** Contributes baseline coloring rules to the `graph` lens's viewer (e.g., color-by op type, color-by dtype, color-by backend-assigned partition).

**How it works.** Declares a set of `GraphExtension` layers via `analyze()`, each with a `CategoricalColorRule`. No session patches.

**Config.** None (can be disabled via the lens config).

**Output.** Toggleable color-by layers in every `GraphBlock`.

---

## §H — Maintenance and Collaboration Strategy

Observatory and `fx_viewer` introduce infrastructure that multiple teams will build on. Clear ownership reduces friction.

### H.1 Proposed ownership model (community-driven with a shared infra core)

- **Core devtools reviewers own the infrastructure:** `devtools/observatory/` core (`observatory.py`, `interfaces.py`, `graph_hub.py`, `cli.py`, templates/runtime JS), `devtools/fx_viewer/` core (exporter, extension API, color rules, JS runtime), and the generic lenses that live in `devtools/observatory/lenses/`.
- **Each backend team owns their backend-specific surface:** `backends/<name>/debugger/observatory/cli.py`, backend-registered patches, and backend-specific lenses. Changes there do not require core-reviewer sign-off beyond normal backend review.
- **Cross-cutting changes** (Lens protocol, `GraphExtension` API, JSON schema, template runtime) require core-reviewer sign-off.

### H.2 Testing responsibility

- **Infra tests** (`devtools/observatory/tests/`, `devtools/fx_viewer/examples/`): owned by core reviewers. Cover lens protocol, session lifecycle, graph payload round-tripping, CLI smoke.
- **Backend-specific tests** (`backends/<name>/debugger/observatory/tests/`): owned by backend teams. Cover backend patches, backend lenses, and at least one end-to-end report generation per backend.
- **CI invariants**: every backend-specific CLI runs a smoke test on a representative small model in CI.

### H.3 Policy for non-backward-compatible API changes

When a PR modifies `Lens`, `GraphExtension`, or the **JSON schema** emitted by `digest()` / `analyze()` in a non-backward-compatible way, the PR must **either**:

1. Enumerate every existing caller and consumer (shared lenses, backend lenses, archived JSON readers, examples, tests) and include the fix in the same PR; **or**
2. Announce the breakage in advance through an issue or RFC update, give backend owners and downstream JSON consumers a window to migrate, and land the change only after the migration PRs are ready.

Option (1) is preferred when the blast radius is small and the maintainer has context to fix all callers. Option (2) is preferred when the change affects backend-specific lenses, archived JSON consumers (CI systems, dashboards), or third parties the core team cannot test directly.

### H.4 Alternatives briefly considered

- **Core-owns-everything.** Every backend lens reviewed by core. Rejected: bottleneck; discourages backend teams from contributing specialized lenses.
- **Backend-owns-everything (infra too).** No shared maintainer for the core. Rejected: infra drifts; the unified report shape erodes.
- **Deprecation-shim period (semver-style stability tiers).** Could be adopted on top of the current policy if the protocol stabilizes and breaking changes become common enough to warrant the extra surface area. Worth revisiting after one release cycle.
- **Plugin entry-point auto-discovery.** Could replace explicit registration in backend CLIs. Deferred: explicit registration is simpler to reason about; entry-point discovery can be added later without breaking existing CLIs.

---

## §I — Open Questions

Infrastructure and collaboration:

1. **Core vs. backend ownership boundary.** Is "generic lens lives in `devtools/`, backend-specific lens lives in `backends/`" sufficient, or do we need a middle tier (e.g., shared-across-two-backends)? How do we handle a lens that starts backend-specific and becomes generic?
2. **Lens API stability signal.** Should lenses advertise an experimental/stable tier so external contributors know what's safe to depend on, similar to `torch.compile`'s stability annotations?
3. **Breaking-change communication channel.** Is an issue label (`observatory-api-change`) sufficient, or do we need a mailing-list-style notification to known backend owners?
4. **Review policy.** Should generic lenses in `devtools/observatory/lenses/` require two core reviewers (given they become part of the shared experience), while backend lenses follow backend review norms?

Runtime and integration:

5. **Auto-discovery.** Should the generic CLI (`python -m executorch.devtools.observatory`) auto-discover backend patches when a backend package is importable, or always require explicit backend-CLI usage?
6. **Inspector API coupling.** Should Observatory integrate directly with Inspector's capture points, or remain a parallel layer that consumes Inspector outputs?
7. **Runtime lens split.** When runtime-side lenses land (ETDump-consuming), do they live in `devtools/observatory/lenses/` or a sibling `devtools/observatory/runtime_lenses/`?

UI and scope:

8. **Recipe granularity.** Is `--lense_recipe=accuracy` the right granularity for backend CLIs, or should recipes be multi-valued / composable (`--lense=accuracy --lense=stack_trace`)?
9. **Module hierarchy.** Should `fx_viewer` grow the module-hierarchy collapse feature that `devtools/visualization/` has, or keep the flat + search model as a deliberate simplicity choice?
10. **Config schema.** Lens configs (`config["accuracy"]["dataset"]`, etc.) are dict-shaped today. Is there value in typed config schemas (dataclasses, Pydantic) as the lens library grows?

Philosophy:

11. **Opt-in vs. encouraged adoption.** Do we want to actively encourage every backend to ship a CLI, or treat adoption as purely opt-in without signal either way?
12. **JSON schema versioning strategy.** JSON is committed as a stable consumer contract (§A.0). What versioning approach do we adopt? Options: (a) a single semver'd top-level `schema_version` field that consumers check; (b) per-lens schema versions, since different lenses evolve at different rates; (c) additive-only by convention, deprecate fields rather than remove them; (d) some combination. This matters most for CI-archive and AI-consumer use cases where JSON from older Observatory versions must stay readable.
13. **Regression / compare lens scope.** Should the nightly-JSON comparison capability (rfc.md §11) ship as a dedicated built-in lens (`regression`), as a generic N-way compare mode of the existing lenses, or as a separate CLI subcommand (`observatory compare`)?
