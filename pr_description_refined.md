# Observatory + fx_viewer — A Visualizer and Debugging Framework for ExecuTorch

> **Abstract:** This PR adds two pieces that work together. **`fx_viewer`** (`devtools/fx_viewer/`) is a lightweight, server-free FX-graph viewer with layered overlays and N-way compare. **`Observatory`** (`devtools/observatory/`) is a debugging framework built on top of it: a maintainer writes one Python class (a **Lens**) per debugging concern, and the framework handles session lifecycle, artifact storage, and report rendering. Observatory does **not** replace `Inspector`, `ETRecord`, or `ETDump` — it coordinates them. The **Lens protocol** (`get_name`, `setup`, `on_session_start`, `observe`, `digest`, `on_session_end`, `clear`, `analyze`, `get_frontend_spec`) is the single extension contract; `get_frontend_spec()` returns a `Frontend` whose `dashboard()` and `record()` methods contribute `TableBlock` and `GraphBlock` views to the report.

This document covers the **feature set, architecture, and API design** with concrete examples and demos. For the higher-level motivation, the fair comparison against Model Explorer, and the open design questions, see the RFC (`rfc_review_real.md`).

## Summary

This PR introduces **`fx_viewer`** (`devtools/fx_viewer/`) and **`Observatory`** (`devtools/observatory/`) as shared ExecuTorch debugging infrastructure:

- **`fx_viewer`** — a standalone, server-free FX-graph renderer (pan / zoom / minimap / search / layered overlays / N-way compare). It powers Observatory's graph view and is independently usable.
- **`Observatory`** — a debugging framework built on top of `fx_viewer`. It captures artifacts across the AOT pipeline (including intermediate FX graph snapshots not stored in ETRecord), runs pluggable Lens analysis, and emits a self-contained report.

**This PR carries a functional proof-of-concept.** Pull the branch, install `fast-sugiyama`, run the CLI, and get self-contained HTML reports with interactive graph views, N-way compare, and per-layer accuracy overlays. The module layout and API framing shown here are concrete but open to discussion — see the RFC's Open Questions.

**Draft PR:** https://github.com/pytorch/executorch/pull/19288
**RFC:** `rfc_review_real.md` in this repository.

---

## Motivation (brief)

ExecuTorch already has strong low-level capture tools (`Inspector`, `ETRecord`/`ETDump`), but no layer to *coordinate* them, and no embeddable, overlay-capable graph viewer for in-pipeline debugging. As a result each backend builds its own glue scripts, and debugging output ends up scattered across console prints, CSVs, and screenshots.

- **`Observatory`** provides the missing coordination + synthesis layer: write one Lens once, get a shareable report.
- **`fx_viewer`** provides the missing viewer: server-free, embeddable in one HTML file, with programmatic overlays and N-way compare.

The full motivation and the fair comparison against Model Explorer / Inspector live in the RFC (`rfc_review_real.md`, §2). This document is about *how it works*.

---

## What You Get

One command in, one HTML file out:

```bash
pip3 install 'fast-sugiyama[full]'   # requires python >= 3.11

python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens-recipe accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

**Output:** a self-contained HTML file — no server, no login, no external service. Attach it to an issue, PR, or email.

Features in the report:
- **Session dashboard** — per-session metadata, lens-contributed sections.
- **Record tree** — captured artifacts, time-ordered or grouped by `region_stack`.
- **Interactive FX graph** — pan, zoom, minimap, fuzzy search, N-way synchronized compare.
- **Per-layer accuracy overlay** — PSNR / cosine / MSE as a color gradient on graph nodes, from CPU simulation across intermediate snapshots at `prepare_pt2e`, `convert_pt2e`, and `to_edge_transform_and_lower` (stages not stored in ETRecord). Runtime/delegated accuracy via `Inspector` is a planned follow-up lens.

Two machine-readable outputs accompany the HTML:
- **Archive (JSON)** — raw `sessions[]` + `records[]`, no analysis baked in; the input for `--compare` and late re-analysis.
- **Report (JSON)** — analyzed summary for CI gates, dashboards, and LLM triage.

---

## Architecture Overview

Observatory follows a three-layer design: Interface → Core → Lenses.

```
╔═════════════════════════════════════════════════════════════════════════════╗
║  INTERFACE LAYER                                                            ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ ┌─ User interface ──────────┐ ┌─ Lens author ──────┐ ┌─ Artifacts ───────┐ ║
║ │ generic CLI               │ │ implements a Lens:  │ │ Report (HTML)     │ ║
║ │ backend CLI               │ │   on_session_start  │ │ Archive (JSON)    │ ║
║ │ `with` block (context)    │ │   on_session_end    │ │ Report (JSON)     │ ║
║ │ @observe_pass decorator   │ │   observe / digest  │ │                   │ ║
║ │ Observatory.collect(...)  │ │   analyze           │ │                   │ ║
║ │                           │ │   get_frontend_spec │ │                   │ ║
║ └───────────────────────────┘ └─────────────────────┘ └───────────────────┘ ║
╚═════════════════════════════════════════════════════════════════════════════╝
         │                              │                          ▲
         │ drives                       │ registers with           │ emits
         ▼                              ▼                          │
╔═════════════════════════════════════════════════════════════════════════════╗
║  OBSERVATORY CORE           (backend-agnostic)                              ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ ┌─ Session manager ──────────┐   ┌─ Record store ─────────────────────┐    ║
║ │ region & config stack      │   │ per-collect fan-out to every lens  │    ║
║ │ Session open/close         │   │ time-ordered records, region_stack │    ║
║ │ lens registry              │   │ tagged with active session_id      │    ║
║ └────────────────────────────┘   └────────────────────────────────────┘    ║
║                                                                             ║
║ ┌─ Report assembly ────────────────────┐  ┌─ fx_viewer ──────────────────┐ ║
║ │ per-lens analyze over Archive        │  │ Python API (build-time)      │ ║
║ │ Frontend.dashboard / .record         │  │ JS API (browser run-time)    │ ║
║ │ base graph + extension overlays      │  │ Canvas renderer, no server   │ ║
║ └──────────────────────────────────────┘  └───────────────────────────────┘ ║
║                                                                             ║
║ ┌─ Export ─────────────────────────────────────────────────────────────────┐║
║ │ Report (HTML)   — self-contained, for human reviewers                    │║
║ │ Archive (JSON)  — raw sessions[] + records[]; CI input; reload/--compare │║
║ │ Report (JSON)   — analyzed output for LLM triage / dashboards            │║
║ └──────────────────────────────────────────────────────────────────────────┘║
╚═════════════════════════════════════════════════════════════════════════════╝
         ▲
         │ registered at CLI entry; called by Core's lifecycle phases
         │
╔═════════════════════════════════════════════════════════════════════════════╗
║  LENSES                     (all implement the Lens protocol)               ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ ┌─ Common lenses ─────────────────────┐ ┌─ Backend-specific lenses ──────┐ ║
║ │ graph, metadata, accuracy           │ │ qualcomm/ — QNN debug lenses   │ ║
║ │ per_layer_accuracy, stack_trace     │ │ xnnpack/  — XNNPACK lenses     │ ║
║ │ pipeline_graph_collector            │ │ arm/      — ARM lenses          │ ║
║ │ graph_color                         │ │                                 │ ║
║ └─────────────────────────────────────┘ └─────────────────────────────────┘ ║
╚═════════════════════════════════════════════════════════════════════════════╝
```

### The Capture / Analysis Split

Observatory keeps **capture** (online, during the run) separate from **analysis** (offline, from the saved Archive). Only the Archive is raw and persisted; Reports are always derived from it.

```
  Run (live)                    Persist                    Derive
  ─────────                     ───────                    ──────
  Session hooks fire            Archive (JSON)             Report (HTML)
  collect() → Records           sessions[] + records[]     analyze + Frontend
  observe/digest per lens       no analysis baked in       per-lens derived views
        │                              │                          │
        └──────── written at ──────────┘                          │
                  end of run                                      │
                                       │                          │
                                       └─── reload path ──────────┘
                                            (re-analyze with new
                                             config, or combine
                                             via --compare)
```

**Key property:** the same Archive can be re-analyzed with different lens configs, or two archives compared via `--compare`, all without re-running the AOT compile.

---

## Python vs. JavaScript API Boundaries

`fx_viewer` and Observatory meet at exactly two API surfaces — one in Python (build-time), one in JavaScript (run-time in the browser).

```
   BUILD TIME (Python API)
   ┌─ Observatory ──────────────────┐  calls  ┌─ fx_viewer Python API ────────┐
   │ graph / graph_color /          │ ──────► │ FXGraphExporter               │
   │ per_layer_accuracy lenses      │         │ GraphExtension / ColorRule    │
   │ Observatory core (emit)        │         └────────────────┬───────────────┘
   └────────────────┬───────────────┘                          │ produces
                    │ assembles + writes                        ▼
                    └──────────────► report.html ◄─────────────┘
                                     (embedded payload + JS runtime bundle)
                                     │ opened in browser
                                     ▼
   RUN TIME (JS API, all in browser)
   ┌─ Observatory report shell ─────┐  calls  ┌─ fx_viewer JS API ───────────┐
   │ 03_blocks.js                   │ ──────► │ FXGraphViewer.create({...})  │
   │   (mount viewer per Record)    │         │ FXGraphCompare.create({...}) │
   │ 04_actions.js                  │         │ setLayers / setColorBy /     │
   │   (theme + selection sync)     │         │  setTheme / selectNode       │
   └────────────────────────────────┘         └──────────────────────────────┘
```

### Python API (Build-Time)

| Component | Role |
|-----------|------|
| `FXGraphExporter(gm)` | Extract FX graph structure from a `GraphModule`, compute Sugiyama layout (x, y + edge routing), export to HTML or JSON |
| `GraphExtension(id, name)` | Declare an overlay layer — per-node data, coloring rules, labels, tooltips |
| `NumericColorRule(attribute, cmap)` | Map a continuous numeric field to a color gradient (`"viridis"`, `"reds"`, `"blues"`, `"greens"`) |
| `CategoricalColorRule(attribute)` | Map discrete string values to deterministic hues |

**Standalone usage** (no Observatory dependency):
```python
from executorch.devtools.fx_viewer import FXGraphExporter
FXGraphExporter(graph_module).export_html("my_graph.html")
```

### JavaScript API (Run-Time)

| Component | Role |
|-----------|------|
| `FXGraphViewer.create(config)` | Mount a single graph viewer on a DOM element |
| `FXGraphCompare.create({viewers, layout, sync})` | Mount N-way compare with cross-graph selection sync |
| `setLayers(ids[])` / `setColorBy(id)` / `setTheme(name)` | Runtime layer/theme mutation |
| Selection sync via `debug_handle` or `from_node` | Cross-graph node matching across AOT pipeline stages, even after fusion/decomposition |

---

## The Lens Protocol

A Lens is the single extension unit — one Python class that owns one debugging concern end-to-end. Implement only the methods you need; the framework ignores the rest.

### Protocol Methods (fired in lifecycle order)

```python
class Lens:
    @classmethod
    def get_name(cls) -> str: ...          # config key: config[get_name()]

    @classmethod
    def setup(cls) -> None: ...            # one-time init at registration

    @classmethod
    def on_session_start(cls, context: ObservationContext) -> None:
        """Install instrumentation (e.g. monkey-patches). Fires at outermost enter_context."""

    @classmethod
    def observe(cls, artifact: Any, context: ObservationContext) -> Any:
        """Filter + transform the artifact at each collect() call. Return None to skip."""

    @classmethod
    def digest(cls, observation: Any, context: ObservationContext) -> Serializable:
        """Convert observation into a JSON-serializable form for the Record."""

    @classmethod
    def on_session_end(cls, context: ObservationContext) -> None:
        """Restore instrumentation. Guaranteed to fire even on exception."""

    @classmethod
    def clear(cls) -> None: ...            # reset state between runs

    @staticmethod
    def analyze(records: List[RecordDigest], config: Dict[str, Any]) -> AnalysisResult:
        """Derive insights across all records at report time (offline)."""

    @staticmethod
    def get_frontend_spec() -> Frontend:
        """Return the Frontend strategy that renders this lens's report blocks."""
```

### Lens Lifecycle Diagram

```
  on_session_start  ─► instrumentation installed
        │
        ▼
  for each Observatory.collect(name, artifact):
    each lens: observe → digest  ─► serialized into Record.digests[lens_name]
        │
        ▼
  on_session_end    ─► instrumentation restored (guaranteed on exception)
        │
        ▼
  ═══ ARCHIVE (raw: sessions[] + records[]) ═══
        │
        ▼
  analyze(records, config)  ─► AnalysisResult
        │
        ▼
  get_frontend_spec() → Frontend
        ├── dashboard(session, records, analysis) → ViewList | None
        │     (session-level blocks: TableBlock, HtmlBlock, ...)
        └── record(digest, analysis, context)     → ViewList | None
              (per-record blocks: TableBlock, GraphBlock, ...)
```

### Frontend and Block Types

`get_frontend_spec()` returns a `Frontend` instance. The framework calls its methods at report-emit time:

| Method | When called | Returns |
|--------|-------------|---------|
| `dashboard(session, records, analysis)` | Once per (Session, lens) pair | `ViewList` of session-level blocks, or `None` |
| `record(digest, analysis, context)` | Once per (Record, lens) pair | `ViewList` of per-record blocks, or `None` |
| `json_report(session, records, analysis)` | Once per (Session, lens) pair | `Dict` for Report (JSON), or `None` |
| `resources()` | Once at report assembly | `{"js": ..., "css": ...}` for shared assets |

Available block types in a `ViewList`:

| Block | Purpose |
|-------|---------|
| `TableBlock` | Key-value or row data; auto side-by-side diff in compare view |
| `HtmlBlock` | Arbitrary HTML fragment |
| `CustomBlock` | Custom JS-rendered widget |
| `GraphBlock` | Interactive FX graph via `fx_viewer`; synchronized N-way compare |

### Shipped Common Lenses

| Lens | Purpose |
|------|---------|
| `graph` | Base FX graph extraction and layout via `FXGraphExporter` |
| `metadata` | Run-wide info: CLI command, env, model |
| `accuracy` | Graph-level accuracy metrics across lowering stages |
| `per_layer_accuracy` | Per-operator PSNR / cosine / MSE color overlay |
| `pipeline_graph_collector` | Auto-collect at `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower` |
| `stack_trace` | User-code call stack provenance at each collection point |
| `graph_color` | Partition/delegation color overlay |


---

## Worked Example: AdbLogLens (Custom Lens)

This example shows the full extension surface — a lens that captures device-side logs from ADB without touching Observatory core:

```python
from dataclasses import dataclass
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.interfaces import (
    Lens, ObservationContext, Frontend, ViewList, TableBlock,
)
from executorch.backends.qualcomm.export_utils import SimpleADB

@dataclass
class AdbLogEntry:
    source: str        # "logcat" or "dmesg"
    cmd_label: str     # which on-device command produced this
    content: str

class AdbLogLens(Lens):
    _original = None

    @classmethod
    def get_name(cls) -> str:
        return "adb_log"

    @classmethod
    def on_session_start(cls, context: ObservationContext) -> None:
        """Patch SimpleADB.execute to capture logcat + dmesg after every call."""
        cls._original = SimpleADB.execute

        def patched(self, *args, **kw):
            cls._original(self, *args, **kw)
            cmd_label = kw.get("custom_runner_cmd") or "executor_runner"
            for source, shell_cmd in [
                ("logcat", "logcat -d"),
                ("dmesg",  "dmesg"),
            ]:
                Observatory.collect(
                    f"adb_log/{cmd_label}/{source}",
                    AdbLogEntry(source, cmd_label,
                                content=_adb_shell(self, shell_cmd)),
                )

        SimpleADB.execute = patched

    @classmethod
    def on_session_end(cls, context: ObservationContext) -> None:
        """Restore original — guaranteed even on exception."""
        SimpleADB.execute = cls._original
        cls._original = None

    @classmethod
    def observe(cls, artifact, context: ObservationContext):
        """Filter by type and live config — reads config per-call for nesting."""
        if not isinstance(artifact, AdbLogEntry):
            return None
        cfg = context.config.get("adb_log", {})
        if not cfg.get("enabled", True):
            return None
        if artifact.source not in cfg.get("sources", ["logcat"]):
            return None
        return {"source": artifact.source,
                "cmd":    artifact.cmd_label,
                "lines":  artifact.content.splitlines()}

    @classmethod
    def digest(cls, observation, context: ObservationContext):
        return observation   # already JSON-serializable

    @staticmethod
    def analyze(records, config):
        return AnalysisResult()   # no cross-record analysis needed

    @staticmethod
    def get_frontend_spec():
        return _AdbFrontend()

class _AdbFrontend(Frontend):
    def record(self, digest, analysis, context):
        if not digest:
            return None
        rows = [{"source": digest["source"], "cmd": digest["cmd"],
                 "lines": len(digest["lines"])}]
        return ViewList(blocks=[TableBlock(id="adb_log", rows=rows)])
```

**Key design patterns demonstrated:**
- Session hooks install/restore instrumentation (monkey-patching).
- `observe()` reads `context.config` at call time — nested `enter_context` overrides work correctly.
- Type filtering: lens returns `None` for artifacts it doesn't own.
- `collect()` is type-agnostic — multiple lenses coexist without knowing about each other.
- `get_frontend_spec()` returns a `Frontend`; `record()` returns a `ViewList` with a `TableBlock`.

### Nested Config Scoping in Practice

```python
with Observatory.enter_context(config={
    "accuracy": {"evaluator": my_evaluator},
    "adb_log":  {"sources": ["logcat"]},          # lightweight default
}):
    run_on_device(probe_cmd)      # only logcat captured
    run_on_device(smoke_cmd)      # only logcat captured

    with Observatory.enter_context(config={
        "accuracy": {"enabled": False},
        "adb_log":  {"sources": ["logcat", "dmesg"]},  # broaden for target
    }):
        device_result = run_on_device(target_cmd)       # logcat + dmesg
        Observatory.collect("post_device", device_result)

    run_on_device(teardown_cmd)   # back to logcat only
```

Config overrides are pushed on `enter_context` entry and popped on exit — even on exception.

---

## Invocation Surfaces

There are two real surfaces: the **CLI** and the **context + collection points** pair. `@observe_pass` is syntactic sugar over the second.

### 1. CLI (zero-code-change)

Observatory parses its own leading flags, then runs your script exactly as written via `runpy`, forwarding all remaining arguments verbatim:

```bash
# Generic (framework lenses only)
python -m executorch.devtools.observatory \
    --output-html run.html \
    your_script.py --your-args

# Backend-specific
python -m executorch.backends.xnnpack.debugger.observatory \
    --lens-recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize

# Archive for CI (no HTML needed at capture time)
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-archive nightly/${DATE}/mv2.json \
    --lens-recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2
```

### 2. Context + Collection Points

Activate the lenses you want, open a session, and mark the points to capture. Lenses are turned on (and tuned) by the `config` dict, keyed by lens name:

```python
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.lenses import PerLayerAccuracyLens

Observatory.register_lens(PerLayerAccuracyLens)

with Observatory.enter_context("quantization",
                               config={"per_layer_accuracy": {"enabled": True}}):
    Observatory.collect("before_quantize", gm)           # capture point 1

    with Observatory.enter_context("fast_passes",
                                   config={"per_layer_accuracy": {"enabled": False}}):
        gm = run_cheap_passes(gm)                        # lens off for this sub-step

    quantized_gm = quantize_model(gm)
    Observatory.collect("after_quantize", quantized_gm)  # capture point 2

# Stage 1 — persist the raw Archive JSON
Observatory.export_json("archive.json")

# Stage 2 — render HTML from the archive, any time, without re-running
Observatory.generate_html_from_json("archive.json", "report.html")
```

### 3. `@observe_pass` Decorator (sugar over context + collect)

`@observe_pass` wraps a pass so its input and output graphs are `collect()`-ed automatically — no manual collection points needed:

```python
from executorch.devtools.observatory import Observatory, observe_pass

@observe_pass
class MyPass(ExportPass):
    def call(self, gm): ...

# Or wrap existing pass instances without modifying their class:
observed_passes = [observe_pass(p) for p in [FoldQDQ(), LayoutTransform()]]

with Observatory.enter_context("pipeline"):
    PassManager(observed_passes)(graph_module)
```

---

## Collection-Point Mechanisms

Three distinct mechanisms produce collection points — all flow into the same `collect(name, artifact)` path:

| Mechanism | How it works | Patch targets / scope |
|-----------|-------------|----------------------|
| **`pipeline_graph_collector` lens patches** | Wraps standard pipeline functions at `on_session_start`; each patch calls `collect()` with the returned object, then restores at `on_session_end` | `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_*` |
| **`@observe_pass` decorator** | Tags any `PassBase` subclass/instance; wraps each pass call in its own Region and collects graph before + after | Any pass: user-defined or framework-provided |
| **Manual `Observatory.collect(name, artifact)`** | Direct call anywhere inside user code | Any artifact type, any moment |

```python
# What a pipeline_graph_collector patch looks like (simplified):
import torchao.quantization.pt2e.quantize_pt2e as qt

_original = qt.convert_pt2e

def _patched(model, *args, **kwargs):
    Observatory.collect("Calibrated Model", model)        # capture input graph
    result = _original(model, *args, **kwargs)            # call the real function
    Observatory.collect("Quantized Model", result)        # capture output graph
    return result

qt.convert_pt2e = _patched
# on_session_end: qt.convert_pt2e = _original  (always restored, even on exception)
```

All patches are installed in `on_session_start` and removed in `on_session_end` — the user's script runs unchanged.

---

## Key Vocabulary

| Term | Definition |
|------|-----------|
| **Region** | Named scope from `enter_context(name)`. Nests. Pure labelling — no lens hooks fire at region boundaries. |
| **Session** | Outermost Region. Lens `on_session_start`/`on_session_end` fire here. |
| **Record** | One `collect(name, artifact)` item. Tagged with `session_id` + `region_stack`. |
| **Archive** | Raw state: `sessions[]` + `records[]`. The only thing persisted. |
| **Report** | Derived output from an Archive via `analyze` + `Frontend`. HTML or JSON. |
| **Lens** | One Python class that owns one debugging concern end-to-end. |
| **Frontend** | The visualization strategy returned by `get_frontend_spec()`; contributes `dashboard()` and `record()` blocks. |


---

## POC Implementation Structure (`~/executorch`)

```
devtools/
├── observatory/
│   ├── __init__.py              # Public API: Observatory, observe_pass
│   ├── observatory.py           # Core: Session manager, Record store, export
│   ├── interfaces.py            # Lens protocol, Frontend, ViewList, block types
│   ├── observe_pass.py          # @observe_pass decorator
│   ├── cli.py                   # Generic CLI entry point
│   ├── html_template.py         # Report HTML assembly
│   ├── lenses/
│   │   ├── graph.py             # Base FX graph extraction + layout
│   │   ├── metadata.py          # Run-wide metadata
│   │   ├── accuracy.py          # Graph-level accuracy metrics
│   │   ├── per_layer_accuracy.py # Per-operator PSNR/cosine/MSE
│   │   ├── pipeline_graph_collector.py  # Auto-collection at pipeline points
│   │   ├── stack_trace.py       # Call stack provenance
│   │   └── graph_color.py       # Partition color overlay
│   ├── templates/js/
│   │   ├── 03_blocks.js         # Mount viewer per Record graph block
│   │   └── 04_actions.js        # Theme + selection sync logic
│   └── tests/
│
├── fx_viewer/
│   ├── __init__.py              # Public API: FXGraphExporter
│   ├── exporter.py              # Graph extraction, Sugiyama layout, HTML/JSON export
│   ├── extension.py             # GraphExtension: add_node_data, set_color_rule, set_sync_key
│   ├── color_rules.py           # NumericColorRule, CategoricalColorRule
│   ├── models.py                # Data models: GraphNode, GraphEdge, GraphPayload
│   ├── templates/               # JS canvas runtime bundle
│   └── examples/                # Standalone usage examples
│
backends/
├── qualcomm/debugger/observatory/
│   ├── cli.py                   # QNN backend CLI
│   ├── lenses/                  # QNN-specific lenses (AdbLens, etc.)
│   └── tests/
│
└── xnnpack/debugger/observatory/
    ├── cli.py                   # XNNPACK backend CLI
    └── lenses/                  # XNNPACK-specific lenses
```

---

## Governance and Merge Strategy

### Recommended: Three-PR Stack

| PR | Scope | Dependency | Reviewer Focus |
|----|-------|-----------|----------------|
| **PR 1** | `devtools/fx_viewer/` | None | Standalone graph viewer; usable via `FXGraphExporter(gm).export_html(...)` |
| **PR 2** | `devtools/observatory/` | PR 1 | Core framework + 7 common lenses + generic CLI |
| **PR 3** | Backend CLIs | PR 2 | Qualcomm + XNNPACK CLIs with model-matrix validation |

### Ownership Model

- **Core devtools reviewers** → `devtools/observatory/` core, `devtools/fx_viewer/` core, common lenses.
- **Backend teams** → `backends/<name>/debugger/observatory/`, backend-specific lenses and backend CLI — no core sign-off needed.
- **Cross-cutting changes** (Lens protocol, `GraphExtension` API, JS runtime, JSON schemas) → core sign-off required.

### Public API Surfaces (schema stability)

| Surface | Stability | Change requires |
|---------|-----------|----------------|
| Lens protocol (9 methods: `get_name`, `setup`, `on_session_start`, `observe`, `digest`, `on_session_end`, `clear`, `analyze`, `get_frontend_spec`) | Experimental (candidate stable) | Core sign-off |
| `Frontend` API (`dashboard`, `record`, `json_report`, `resources`) | Experimental (candidate stable) | Core sign-off |
| `GraphExtension` API (`add_node_data`, `set_color_rule`, `set_sync_key`, `set_label_formatter`) | Experimental (candidate stable) | Core sign-off |
| Archive (JSON) schema (`sessions[]` + `records[]`) | Experimental (candidate stable) | Core sign-off |
| Report (JSON) schema | Experimental (candidate stable) | Core sign-off |
| `FXGraphViewer.create` / `FXGraphCompare.create` (JS) | Experimental (candidate stable) | Core sign-off |
| Backend CLI flags (`--output-html`, `--lens-recipe`, etc.) | Experimental (candidate stable) | Core sign-off |
| Per-lens config keys (e.g., `accuracy.evaluator`) | Backend-owned | Backend team |
| Backend-specific lenses | Backend-owned | Backend team |

> All surfaces are currently experimental. The "candidate stable" designation means they are designed for stability and will be promoted in a follow-up RFC after one release cycle with real external consumers.

### Testing Strategy

- **Core infra tests** → `devtools/observatory/tests/` (owned by core).
- **Backend tests** → owned by backend teams.
- **CI invariant:** every backend CLI smoke-tests on a representative model.

---

## Implemented Capabilities (on the POC Branch Today)

| Capability | Mechanism | Status |
|------------|-----------|--------|
| Compile-time per-layer accuracy (intermediate stages) | `accuracy` + `per_layer_accuracy` lenses; CPU simulation across `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower` snapshots | ✅ Implemented |
| Graph-state collection at pipeline points | `pipeline_graph_collector` lens patches; captures intermediate graph snapshots not stored in ETRecord | ✅ Implemented |
| Pass diff (before/after) | `@observe_pass` decorator + `graph` compare mode | ✅ Implemented |
| Collection provenance (stack trace) | `stack_trace` lens | ✅ Implemented |
| Interactive FX graph view | `fx_viewer`: pan, zoom, minimap, fuzzy search, N-way compare | ✅ Implemented |
| Run-metadata dashboard | `metadata` lens: CLI command, env, model | ✅ Implemented |
| Region tree-view toggle | Left panel groups Records by `region_stack`; toggle flat/tree | ✅ Implemented |
| Report (HTML) — self-contained | Single file, no server, attach anywhere | ✅ Implemented |
| Archive (JSON) — raw persistence | `--output-archive`; reload for re-analysis | ✅ Implemented |
| Report (JSON) via `json_report` | Structured analysis for LLM triage, CI, dashboards (`--output-report-json`) | ✅ Implemented |
| Partition/delegation color overlay | `graph_color` lens | ✅ Implemented |
| `--compare` CLI mode | Load 2+ archives, emit regression Report | ✅ Implemented |
| ADB log capture (logcat + dmesg) | `AdbLens` (Qualcomm backend-specific, not a default core lens) | ✅ Implemented |
| Runtime / delegated-graph accuracy | On-device vs CPU comparison via `debug_handle` + `Inspector` | ❌ Follow-up |

---

## Known Limitations

1. **Per-layer accuracy is compile-time simulation only.** The `per_layer_accuracy` lens runs CPU simulation across intermediate graph snapshots — stages not stored in ETRecord. It does **not** compare against actual on-device (delegated) execution. Runtime/delegated accuracy via `Inspector` integration is a planned follow-up lens.
2. **`fast-sugiyama` requires Python ≥ 3.11 (optional dependency).** When not installed, `fx_viewer` falls back to a pure-Python topological layout. All features (pan, zoom, search, overlays, N-way compare) remain functional. Gate behind `executorch[observatory-layout]` to avoid raising the project's Python floor.
3. **Runtime / delegated-graph accuracy not yet implemented.** Comparing on-device (delegated) execution against CPU requires a follow-up lens using `debug_handle` + `Inspector`.

---

## Pre-Generated Demo Reports

Reports are available for 30+ models across XNNPACK and Qualcomm backends:

| Backend | Model | Nodes | Report |
|---------|-------|------:|--------|
| xnnpack | `mobilebert` | 2361 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) |
| xnnpack | `resnet50` | 550 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) |
| qualcomm | `inception_v4` | 1541 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v4/observatory_report.html) |
| qualcomm | `mobilenet_v2` | 521 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) |

Cross-backend comparisons (XNNPACK vs. Qualcomm QNN):

| Model | Comparison |
|-------|-----------|
| MobileNetV2 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.html) |
| ViT | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/observatory_comparison.html) |

Full model matrix and walkthrough video: see `rfc_review_real.md`, §3.3.

---

## Dependencies

- `fast-sugiyama[full]` (Python ≥ 3.11, optional) — Sugiyama graph layout for `fx_viewer`. A pure-Python fallback layout is used when unavailable. Gate behind `executorch[observatory-layout]`.
- No JavaScript framework dependencies — the canvas renderer is plain HTML/JS with no npm dependencies bundled at runtime.
- Observatory is a client of existing ExecuTorch capture primitives (`ETRecord`, `ETDump`, `Inspector`) — it adds no new capture formats and requires no changes to Inspector or ETRecord.
