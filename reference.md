# RFC Reference — Observatory & fx_viewer

> Companion to [rfc.md](./rfc.md). This document holds the API surface, structural detail, and decision log. Read rfc.md first for the motivation, demo, and proposal.

---

## §A — Lens Protocol

A **Lens** is a Python class that participates in one or more stages of the Observatory workflow. A minimal lens implements only the stages it needs; the framework ignores the rest.

```python
class Lens:
    @classmethod
    def setup(cls) -> None:
        """One-time initialization (e.g., register patches, load reference data)."""

    @classmethod
    def observe(cls, artifact, context) -> Any:
        """Capture: intercept artifacts during script execution.
        Called by Observatory hooks or pass decorators."""

    @classmethod
    def digest(cls, observation, context) -> Serializable:
        """Store: convert captured observation into JSON-serializable form."""

    @staticmethod
    def analyze(records, config) -> AnalysisResult:
        """Analyze: compute derived data across records
        (e.g., per-layer metric deltas between two snapshots)."""

    @staticmethod
    def get_frontend_spec() -> Frontend:
        """Visualize: declare the report blocks (Table / Html / Custom / Graph)
        contributed by this lens, including record-view and compare-view semantics."""
```

### Workflow

1. **Setup** runs once at Observatory context entry.
2. **Observe / digest** run at each `Observatory.collect()` call (manual, auto-hooked, or via `@observe_pass`).
3. **Analyze** runs once at report export, over all collected records.
4. **Frontend spec** is consumed by the report engine to generate the final HTML and JSON.

### Frontend Block Types

| Block | Purpose | Single-record view | Compare view |
|---|---|---|---|
| `TableBlock` | Key-value data | Rendered as a 2-column table | Auto side-by-side diff |
| `HtmlBlock` | Arbitrary HTML fragment | Rendered inline | Auto side-by-side |
| `CustomBlock` | Custom JS-rendered widget | Lens-provided JS | Lens-provided JS or auto |
| `GraphBlock` | FX graph, via `fx_viewer` | Interactive single graph | Synchronized N-way compare |

### How Lenses Contribute to the Graph View

`GraphBlock` is powered by `fx_viewer`. A lens contributes a graph *overlay* by producing a `GraphExtension` (see §C) in its `analyze` stage, and returning it in `AnalysisResult.graph_layers`. Extensions become toggleable layers in the viewer — same graph, multiple coloring / labeling / sync semantics at the same time.

---

## §B — `devtools/visualization/` vs `fx_viewer`

The two tools are complementary, not competing. They differ in input form, rendering backend, dependency footprint, and intended use stage.

| Aspect | `devtools/visualization/` | `devtools/fx_viewer/` |
|---|---|---|
| Input | `ExportedProgram`, `EdgeProgramManager`, `ExecutorchProgramManager` | `torch.fx.GraphModule` (any FX graph, any dialect) |
| Rendering | Launches Google Model-Explorer (web server + browser tab) | Renders to a **standalone HTML file** (no server, no external deps beyond a browser) |
| Dependencies | `ai-edge-model-explorer>=0.1.16` (heavy; known `numpy<2` vs ExecuTorch's `numpy>=2` conflict) | `fast-sugiyama` (pure Python layout) — nothing else |
| Invocation | Python API only (`Tester(model).export().visualize()`) | Python API + file output; consumed by Observatory's `GraphBlock` |
| Comparison / diff | Not supported | N-way synchronized compare with `debug_handle`/`from_node` sync |
| Native FX-graph support | No (requires export step) | Yes (any `GraphModule`, any dialect) |
| Custom overlays | `add_node_data()` + regex-based style JSON | `GraphExtension` with color rules, label formatters, sync keys, info-panel data |
| Hierarchical / module collapse | Yes (Model-Explorer built-in) | Flat view + search (module hierarchy not yet supported) |
| Intended use stage | Post-export structural browsing | In-workflow debugging of FX graphs during compile passes |
| Output shareability | Server-backed; JSON save for deferred viewing | Single self-contained HTML — attachable to issues, email, chat |

**When to use which**

- `visualization/` — "I want to browse the final structure of my exported model with module hierarchy, hosted in Model-Explorer."
- `fx_viewer` — "I want to see the raw FX graph at each stage of a compile pipeline, diff it across passes, annotate nodes with custom analysis, and send the result as a single file."

---

## §C — fx_viewer Extension API

`GraphExtension` is the unit of customization. Each extension becomes a togglable layer in the viewer. Lenses create extensions during their `analyze` phase to overlay per-node data, labels, colors, and cross-graph sync keys onto the graph view.

### §C.1 Info-Panel Data (per-node key-value)

When a node is selected, each active extension contributes a section to the info panel, prefixed by the extension name.

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

Label formatters append lines below the base node label. Tooltip formatters produce hover text. Both receive the node's extension data.

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

In N-way compare, extensions can declare a **sync key** — the field used to match corresponding nodes across different graphs. Essential when node IDs diverge after fusion or decomposition.

```python
# Match nodes across graphs by their original source node reference
accuracy_ext.set_sync_key("from_node")
```

Clicking a node in Graph A auto-selects the matching node in Graph B, even if the node IDs differ.

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

`pipeline_graph_collector` (active by default) wraps standard ExecuTorch entry points and inserts collection points automatically:

- `prepare_pt2e`
- `convert_pt2e`
- `to_edge_transform_and_lower`
- `ETRecord.add_exported_program`
- `ETRecord.add_edge_dialect_program`

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

> Note: `examples/xnnpack/aot_compiler.py` uses relative imports (`from . import ...`), so it must be run as a module. The Observatory CLI auto-detects this when a file path is passed and its directory contains `__init__.py`. Equivalent dotted-module form is also accepted.

```bash
# File path (auto-detected as module due to __init__.py)
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

Layout-engine dependency for `fx_viewer`: `pip install 'fast-sugiyama[full]'` (Python >= 3.11).

---

## §F — Backend Extension Pattern

A backend integrates with Observatory in two ways:

### F.1 Backend Patches — Hook Into Shared Lenses

When a shared lens needs backend-specific interception (e.g., to capture a graph at a backend-owned lowering entry point), the backend registers patches that the shared lens invokes during `setup`.

```python
# backends/qualcomm/debugger/observatory/cli.py
from executorch.devtools.observatory.lenses.pipeline_graph_collector import (
    PipelineGraphCollectorLens,
)
from .lenses.qnn_patches import install_qnn_patches

PipelineGraphCollectorLens.register_backend_patches(install_qnn_patches)
```

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
    def observe(cls, artifact, context): ...
    @staticmethod
    def analyze(records, config): ...
    @staticmethod
    def get_frontend_spec(): ...
```

### F.3 CLI Composition

Each backend CLI is a thin wrapper that:

1. Registers patches for any shared lenses it needs.
2. Declares a mapping from `--lense_recipe` values to lens sets.
3. Delegates to the generic Observatory runner.

See `backends/qualcomm/debugger/observatory/cli.py` (~80 lines) as the reference implementation.

---

## §G — Alternatives Considered

**G.1 Keep everything under `backends/qualcomm/` and have other backends depend on it.**
Rejected. Creates an artificial dependency on Qualcomm for generic debugging. Violates the principle that shared tools live in shared locations.

**G.2 Move to a new top-level `tools/` or `debugging/` directory.**
Rejected. `devtools/` is the established home for shared developer tools (Inspector, ETDump, ETRecord, visualization). Adding a sibling is worse than joining the existing one.

**G.3 Use Python entry points for automatic lens discovery.**
Rejected for now. Explicit registration via `Observatory.register_lens()` is simpler and predictable. Entry-point discovery can be added later without changing the runtime.

**G.4 Backward-compatibility shims at old import paths.**
Rejected. Adds maintenance burden and delays migration. A clean break is simpler.

**G.5 Reuse `devtools/visualization/` for graph views instead of shipping `fx_viewer`.**
Rejected. `visualization/` operates on `ExportedProgram`, requires Model-Explorer (heavy dep with a `numpy` version conflict), has no compare mode, and is server-backed rather than file-backed. None of these match Observatory's requirements for in-pipeline FX graphs and shareable standalone reports. See §B.

---

## §H — Risk Analysis and Test Strategy

### Risks

| Risk | Mitigation |
|---|---|
| `__file__`-relative template paths break after the move | Templates move with their code; covered by import tests |
| Cross-lens state sharing breaks | State is class-level and import-path independent (`_worst_indices`, `_last_calibration_dataset`) |
| `fast-sugiyama` license concerns | Vendored with its LICENSE; verified compatible |
| Backend teams unfamiliar with Lens protocol | Reference implementations (QNN, XNNPACK) + `USAGE.md` + `LENSES.md` |

### Test Strategy

1. Import verification for every new public path.
2. Existing Observatory unit tests migrated to `devtools/observatory/tests/` and passing.
3. End-to-end report generation via each backend CLI (already captured in `generated_reports/` in the demo repo).
4. Grep verification that no old import path (`executorch.backends.qualcomm.utils.fx_viewer`, `executorch.backends.qualcomm.debugger.observatory`) remains in `devtools/`.

---

## §I — Open Questions

1. Should the generic CLI (`python -m executorch.devtools.observatory`) auto-discover backend patches when the backend package is importable, or always require explicit backend-CLI usage?
2. Should Observatory integrate with the Inspector API's existing capture points, or remain a parallel layer that composes with them?
3. For backend CLIs, is the `--lense_recipe=accuracy` flag the right granularity, or should we allow multi-value / per-lens toggles (`--lense=accuracy --lense=stack_trace`)?
4. Should `fx_viewer` eventually grow module-hierarchy collapse (the feature that `visualization/` has but we don't), or stay flat-first?
