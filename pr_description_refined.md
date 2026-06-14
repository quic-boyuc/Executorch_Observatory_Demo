# Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging

> **Abstract:** Observatory is a zero-config workflow coordinator and visual synthesis layer for ExecuTorch debugging. It actively configures the AOT compilation pipeline — forcing `generate_etrecord=True`, managing a structured region tree across `prepare_pt2e`, `convert_pt2e`, and `to_edge_transform_and_lower` stages — and captures intermediate FX graph snapshots at these stages, which are not stored in ETRecord and are therefore invisible to Inspector. Inspector natively handles `debug_handle`-to-graph-node correlation and per-operator AOT-vs-runtime numerical gap analysis as DataFrames; Observatory does not duplicate this. Instead, Observatory synthesizes Inspector's correlated runtime data together with the compile-time intermediate graph snapshots into a portable, server-free HTML report with layered graph overlays, N-way comparison views, and per-node accuracy color gradients. The Lens protocol gives backend teams a formal extension contract: contribute one Python class per debugging concern, and the framework handles session management, archive storage, and report rendering automatically.

## Summary

This PR introduces **Observatory** (`devtools/observatory/`) and **fx_viewer** (`devtools/fx_viewer/`) as shared ExecuTorch debugging infrastructure. Observatory is a zero-config workflow coordinator and visual synthesis layer: it manages the lifecycle of debugging concerns across ExecuTorch's AOT compilation pipeline, wrapping around existing `Inspector` and `ETRecord`/`ETDump` primitives as clients to configure, collect, correlate, and synthesize their outputs into a single interactive report. `fx_viewer` is a standalone, server-free FX-graph renderer with layered overlays that powers Observatory's graph view and is independently usable.

**This PR carries a functional POC implementation located in `~/executorch`.** The code is fully runnable today — pull the branch, install `fast-sugiyama`, run the CLI, and get self-contained HTML reports with interactive graph views, N-way compare, and per-layer accuracy overlays.

**Draft PR:** https://github.com/pytorch/executorch/pull/19288
**RFC:** See the refined `rfc_refined.md` in this repository for the clean, feature-focused proposal and discussion.

---

## Motivation

Two problems compound across backends, artifact types, and teams:

1. **No shared workflow coordination layer around existing capture primitives.** ExecuTorch's `Inspector`, `ETRecord`/`ETDump`, and `debug_handle` are excellent primitives for raw runtime binary capture. The gap is not at the capture layer — it is at the workflow coordination layer: there is no shared contract for *when* to configure Inspector, *when* to collect artifacts across compilation stages, *how* to correlate runtime binary data with the FX graph structure that produced it, and *how* to synthesize outputs from multiple analysis concerns into a single navigable report. Each backend writes its own glue scripts to sequence these steps, with no reuse and no shared output format.

2. **No embeddable, overlay-capable graph viewer for in-workflow debugging.** `devtools/visualization/` is well-suited for post-export structural browsing of a final model. What is missing is a viewer designed for *in-workflow* debugging: one that can be embedded in a shareable report file (no server), that supports layered overlays contributed by different analysis scripts (accuracy, partition assignment, hardware constraints), and that can synchronize N graphs for cross-stage or cross-backend comparison. `fx_viewer` fills this specific gap without competing with `devtools/visualization/`.

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

**Output:** A self-contained HTML file — no server, no login, no external service. Attach to an issue, PR, or email.

Features in the report:
- **Session Dashboard** — per-session metadata, lens-contributed sections
- **Records with change summaries** — time-ordered or tree-view grouped by `region_stack`
- **Interactive FX graph** — pan, zoom, minimap, fuzzy search, N-way synchronized compare
- **Compile-time per-layer accuracy overlay** — PSNR / cosine / MSE as color gradient on graph nodes, computed by simulating intermediate graph snapshots at `prepare_pt2e`, `convert_pt2e`, and `to_edge_transform_and_lower` stages. This is distinct from Inspector's `calculate_numeric_gap()`, which compares AOT vs. actual on-device runtime outputs. Observatory's compile-time simulation covers stages that Inspector cannot access; runtime/delegated accuracy via Inspector integration is a planned follow-up lens.

---

## Architecture Overview

Observatory's architecture follows a three-layer design: Interface → Core → Lenses.

```
╔═════════════════════════════════════════════════════════════════════════════╗
║  INTERFACE LAYER                                                            ║
╠═════════════════════════════════════════════════════════════════════════════╣
║ ┌─ User interface ──────────┐ ┌─ Lens author ──────┐ ┌─ Artifacts ───────┐ ║
║ │ generic CLI               │ │ implements a Lens:  │ │ Report (HTML)     │ ║
║ │ backend CLI               │ │   on_session_start  │ │ Archive (JSON)    │ ║
║ │ `with` block              │ │   on_session_end    │ │ Report (JSON)     │ ║
║ │ @observe_pass decorator   │ │   observe / digest  │ │                   │ ║
║ │ Observatory.collect(...)  │ │   analyze           │ │                   │ ║
║ │                           │ │   html_frontend     │ │                   │ ║
║ │                           │ │   json_frontend     │ │                   │ ║
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
║ │ GraphHub: base graph + extensions    │  │ JS API (browser run-time)    │ ║
║ │ per-Session Frontend.dashboard       │  │ Canvas renderer, no DOM      │ ║
║ └──────────────────────────────────────┘  └───────────────────────────────┘ ║
║                                                                             ║
║ ┌─ Export ─────────────────────────────────────────────────────────────────┐║
║ │ Report (HTML)   — self-contained, for human reviewers                    │║
║ │ Archive (JSON)  — raw sessions[] + records[], CI input, reload           │║
║ │ Report (JSON)   — analyzed output for LLM triage / dashboards            │║
║ └──────────────────────────────────────────────────────────────────────────┘║
╚═════════════════════════════════════════════════════════════════════════════╝
         ▲
         │ registered at CLI-entry; called by Core's lifecycle phases
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

---

## Python vs. JavaScript API Boundaries

`fx_viewer` and Observatory meet at exactly two API surfaces — one in Python (build-time), one in JavaScript (run-time in the browser).

```
   BUILD TIME (Python API)
   ┌─ Observatory ──────────────────┐  calls  ┌─ fx_viewer Python API ────────┐
   │ graph / graph_color /          │ ──────► │ FXGraphExporter               │
   │ per_layer_accuracy lenses      │         │ GraphExtension / ColorRule    │
   │ Observatory core (emit)        │         │ relayout_payload_base         │
   └────────────────┬───────────────┘         │ _load_viewer_js_bundle        │
                    │                         └────────────────┬───────────────┘
                    │ assembles + writes                       │ produces
                    ▼                                          ▼
          ┌─────────────────── report.html ─────────────────────┐
          │   embedded payload (base + extension layers)         │
          │   embedded fx_viewer JS runtime bundle               │
          │   embedded Observatory report shell JS               │
          └──────────────────────────┬──────────────────────────┘
                                     │ opened in browser
                                     ▼
   RUN TIME (JS API, all in browser)
   ┌─ Observatory report shell ─────┐  calls  ┌─ fx_viewer JS API ───────────┐
   │ 03_blocks.js                   │ ──────► │ FXGraphViewer.create({...})  │
   │   (mount viewer per Record)    │         │ FXGraphCompare.create({...}) │
   │ 04_actions.js                  │         │ setLayers / setColorBy /     │
   │   (theme + selection sync)     │         │  setTheme / selection sync   │
   └────────────────────────────────┘         └──────────────────────────────┘
```

### Python API (Build-Time)

| Component | Role |
|-----------|------|
| `FXGraphExporter(gm)` | Extract FX graph structure from a `GraphModule`, compute Sugiyama layout (x, y + edge routing) |
| `GraphExtension` | Declare an overlay layer — per-node data, coloring rules, labels, tooltips |
| `ColorRule` | Define color-mapping logic for numeric per-node values (e.g., PSNR → gradient) |
| `relayout_payload_base(...)` | Incorporate node-set changes from extensions into the final layout |
| `_load_viewer_js_bundle()` | Embed the JS canvas runtime into the HTML |

### JavaScript API (Run-Time)

| Component | Role |
|-----------|------|
| `FXGraphViewer.create({payload, mount, layout, state})` | Mount a single graph viewer on a DOM element |
| `FXGraphCompare.create({viewers, layout, sync})` | Mount N-way compare with cross-graph highlighting |
| `setLayers(layers)` / `setColorBy(key)` / `setTheme(theme)` | Runtime layer/theme mutation |
| Selection sync via `debug_handle` or `from_node` set-intersection | Cross-graph node matching across AOT pipeline stages, even after fusion/decomposition. Uses `from_node` provenance metadata for AOT-stage comparison; uses `debug_handle` values for cross-backend comparison of the same Edge Dialect graph. |

**Standalone usage** (no Observatory dependency):
```python
from executorch.devtools.fx_viewer import FXGraphExporter
FXGraphExporter(graph_module).export_html("my_graph.html")
```

---

## The Lens Protocol

A Lens is the single extension unit — one Python class that owns one debugging concern end-to-end.

### Protocol Methods (fired in lifecycle order)

The Lens protocol defines eight methods across five categories:
- **Identity:** `get_name`
- **Lifecycle hooks:** `on_session_start`, `on_session_end`
- **Collection hooks:** `observe`, `digest`
- **Analysis hook:** `analyze`
- **Presentation hooks:** `html_frontend`, `json_frontend`

```python
class Lens:
    @classmethod
    def get_name(cls) -> str: ...

    @classmethod
    def on_session_start(cls, context: ObservationContext) -> None:
        """Install instrumentation. Fires at outermost enter_context."""

    @classmethod
    def on_session_end(cls, context: ObservationContext) -> None:
        """Restore instrumentation. Guaranteed even on exception."""

    @classmethod
    def observe(cls, artifact: Any, context: ObservationContext):
        """Filter + serialize the lens's take on an artifact. Return None to skip."""

    @classmethod
    def digest(cls, observation, context: ObservationContext):
        """Post-process observation into final Record digest."""

    @classmethod
    def analyze(cls, records, sessions, config, *, pair_records=None, pair_sessions=None):
        """Derive insights across the full Archive at emit time."""

    # Frontend hooks (per-Session at emit):
    # html_frontend(insights) → HTML pieces
    # json_frontend(insights) → structured JSON pieces
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
  analyze(records, sessions, config)  ─► derived insights
        │
        ├── html_frontend(insights)  → Report (HTML)
        └── json_frontend(insights)  → Report (JSON)
```

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

This example demonstrates the full extension surface — a lens that captures device-side logs from ADB without touching Observatory core:

```python
from dataclasses import dataclass
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.interfaces import Lens, ObservationContext
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
```

**Key design patterns demonstrated:**
- Session hooks install/restore instrumentation (monkey-patching)
- `observe()` reads `context.config` at call time — nested `enter_context` overrides work correctly
- Type filtering: lens returns `None` for artifacts it doesn't own
- `collect()` is type-agnostic — multiple lenses coexist without knowing about each other

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

---

## Invocation Surfaces

### 1. CLI (zero-code-change)

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

### 2. Python Context Manager (targeted debugging)

```python
from executorch.devtools.observatory import Observatory

config = {"accuracy": {"dataset": my_small_repro_set}}
with Observatory.enter_context("pass_debug", config=config):
    Observatory.collect("original", gm)
    transformed = my_experimental_pass(gm)
    Observatory.collect("after_my_pass", transformed)

Observatory.export_report_html("pass_debug.html")
Observatory.export_archive("pass_debug.json")
```

### 3. `@observe_pass` Decorator (pass-centric)

```python
from executorch.devtools.observatory import Observatory, observe_pass

@observe_pass
class MyPass(ExportPass):
    def call(self, gm): ...

pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enter_context("pipeline"):
    pm._transform(graph_module)
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
def patched_prepare_pt2e(model, *args, **kwargs):
    with Observatory.enter_context("prepare_pt2e"):
        result = original(model, *args, **kwargs)
        Observatory.collect("Annotated Model", result)
        return result
```

All patches are installed in `on_session_start` and removed in `on_session_end` — the user’s script runs unchanged.

---

## Key Vocabulary

| Term | Definition |
|------|-----------|
| **Region** | Named scope from `enter_context(name)`. Nests. Pure labelling — no lens hooks fire. |
| **Session** | Outermost Region. Lens `on_session_start`/`on_session_end` fire here. |
| **Record** | One `collect(name, artifact)` item. Tagged with `session_id` + `region_stack`. |
| **Archive** | Raw state: `sessions[]` + `records[]`. The only thing persisted. |
| **Report** | Derived output from an Archive via `analyze` + rendering. HTML or JSON. |

---

## POC Implementation Structure (`~/executorch`)

The functional POC is organized as follows:

```
devtools/
├── observatory/
│   ├── __init__.py              # Public API surface
│   ├── observatory.py           # Core: Session manager, Record store
│   ├── interfaces.py            # Lens protocol, Frontend contracts, typed blocks
│   ├── observe_pass.py          # @observe_pass decorator
│   ├── cli.py                   # Generic CLI entry point
│   ├── graph_hub.py             # GraphHub: base graph + extension coordination
│   ├── html_template.py         # Report assembly
│   ├── template_loader.py       # Template loading utilities
│   ├── utils.py                 # Shared utilities
│   ├── lenses/
│   │   ├── graph.py             # Base FX graph extraction + layout
│   │   ├── metadata.py          # Run-wide metadata
│   │   ├── accuracy.py          # Graph-level accuracy metrics
│   │   ├── per_layer_accuracy.py # Per-operator PSNR/cosine/MSE
│   │   ├── pipeline_graph_collector.py  # Auto-collection at pipeline points
│   │   ├── stack_trace.py       # Call stack provenance
│   │   └── graph_color.py       # Partition color overlay
│   ├── templates/
│   │   └── js/
│   │       ├── 03_blocks.js     # Mount viewer per Record graph block
│   │       └── 04_actions.js    # Theme + selection sync logic
│   └── tests/
│
├── fx_viewer/
│   ├── __init__.py              # Public API: FXGraphExporter
│   ├── exporter.py              # Graph extraction, Sugiyama layout, HTML export
│   ├── extension.py             # GraphExtension protocol
│   ├── color_rules.py           # ColorRule definitions
│   ├── models.py                # Data models: GraphNode, GraphEdge, GraphPayload
│   ├── templates/               # JS canvas runtime bundle
│   └── examples/                # Standalone usage examples
│
backends/
├── qualcomm/debugger/observatory/
│   ├── cli.py                   # QNN backend CLI
│   ├── lenses/                  # QNN-specific lenses
│   └── tests/
│
└── xnnpack/debugger/observatory/
    ├── cli.py                   # XNNPACK backend CLI
    └── lenses/                  # XNNPACK-specific lenses
```

---

## Governance and Merge Strategy

### Recommended: Three-PR Stack (Option B)

We recommend splitting into three focused PRs in dependency order:

| PR | Scope | Dependency | Reviewer Focus |
|----|-------|-----------|----------------|
| **PR 1** | `devtools/fx_viewer/` | None | Standalone graph viewer; usable via `FXGraphExporter(gm).export_html(...)` |
| **PR 2** | `devtools/observatory/` | PR 1 | Core framework + 7 common lenses + generic CLI |
| **PR 3** | Backend CLIs | PR 2 | Qualcomm + XNNPACK CLIs with model-matrix validation |

### Ownership Model

- **Core devtools reviewers** → `devtools/observatory/` core, `devtools/fx_viewer/` core, common lenses
- **Backend teams** → `backends/<name>/debugger/observatory/`, backend-specific lenses (no core sign-off needed)
- **Cross-cutting changes** (Lens protocol, `GraphExtension` API, JS runtime, JSON schemas) → core sign-off required

### Public API Surfaces (schema stability)

Two JSON schemas are public contracts:
1. **Archive (JSON)** — raw records + sessions; consumed by CI and `--compare`
2. **Report (JSON)** — analyzed output for LLM triage and dashboards (`--output-report-json`)

Breaking changes to the Lens protocol, `GraphExtension`, or either JSON schema require:
- Same-PR caller fixes (preferred for small scope), or
- Advance announcement + staged migration (for changes affecting downstream consumers)

### Testing Strategy

- **Core infra tests** → `devtools/observatory/tests/` (owned by core)
- **Backend tests** → owned by backend teams
- **CI invariant:** every backend CLI smoke-tests on a representative model

---

## Implemented Capabilities (on the POC Branch Today)

Pull the branch, install dependencies, run the CLI — all of the following are fully implemented and end-to-end runnable on the POC branch:

| Capability | Mechanism | Status |
|------------|-----------|--------|
| Compile-time per-layer accuracy (intermediate stages) | `accuracy` + `per_layer_accuracy` lenses; CPU simulation across `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower` snapshots — stages not stored in ETRecord and not accessible to Inspector's `calculate_numeric_gap()` | ✅ Implemented in POC |
| Graph-state collection at pipeline points (with active ETRecord configuration) | `pipeline_graph_collector` lens patches `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower` (forcing `generate_etrecord=True`), and `ETRecord.add_*`; captures intermediate graph snapshots invisible to Inspector | ✅ Implemented in POC |
| Pass diff (before/after) | `@observe_pass` decorator + `graph` compare mode | ✅ Implemented in POC |
| Collection provenance (stack trace) | `stack_trace` lens | ✅ Implemented in POC |
| Interactive FX graph view | `fx_viewer`: pan, zoom, minimap, fuzzy search, N-way compare | ✅ Implemented in POC |
| Run-metadata dashboard | `metadata` lens: CLI command, env, model | ✅ Implemented in POC |
| Region tree-view toggle | Left panel groups Records by `region_stack`; toggle flat/tree | ✅ Implemented in POC |
| Report (HTML) — self-contained | Single file, no server, attach anywhere | ✅ Implemented in POC |
| Archive (JSON) — raw persistence | `--output-archive`; reload for re-analysis | ✅ Implemented in POC |
| Partition/delegation color overlay | `graph_color` lens | ✅ Implemented in POC |
| ADB log capture (logcat + dmesg) | `AdbLens` via `--lens-recipe adb`; session-hook pattern | ✅ Implemented in POC (Qualcomm backend-specific, not a default core lens) |
| Report (JSON) via `json_frontend` | Structured analysis for LLM triage, CI, dashboards (`--output-report-json`) | ✅ Implemented in POC |
| `--compare` CLI mode | Load 2+ archives with `--label`, emit regression Report | ✅ Implemented in POC |
| Runtime / delegated-graph accuracy | On-device vs CPU comparison via `debug_handle` + `Inspector` | ❌ Follow-up |

> **Note on ADB lens status:** The `AdbLens` (`--lens-recipe adb`) for log capture (stdout, logcat, dmesg) around on-device inference **is implemented** on the branch as a Qualcomm backend-specific extension — it demonstrates the full extensibility pattern but is not a default core lens. The `AdbLogLens` code in the "Worked Example" section above serves as the canonical guide for writing custom backend lenses. The further follow-up is *perf-trace* support (optrace / QHAS profiling), which is not yet implemented.

## Archive vs. Report Data Pipeline

Reviewers should understand the data-flow split: only the Archive is raw; Reports are always derived.

```
  Run (live)                    Persist                    Derive
  ─────────                     ───────                    ──────
  Session hooks fire            Archive (JSON)             Report (HTML)
  collect() → Records           sessions[] + records[]     analyze + html_frontend
  observe/digest per lens       no analysis baked in       per-lens derived insights
        │                              │                          │
        └──────── written at ──────────┘                          │
                  end of run                                      │
                                       │                          │
                                       └─── reload path ──────────┘
                                            (re-analyze with
                                             different config
                                             or combine via
                                             --compare)
```

**Key property:** The same Archive can be re-analyzed with different lens configs without re-running the AOT compile. Multiple archives can be combined for cross-run regression via `--compare` (`observatory compare --input-archive ... --label ...`).

## Implementation Status vs. RFC Text

> **Note:** The RFC document (`rfc_review.md`) was written at an earlier stage and marks Report (JSON) and `--compare` as "not yet implemented." Both have since been implemented on the POC branch. The table below reflects the **actual branch state**.

| Feature | RFC Status | Actual Branch Status |
|---------|-----------|---------------------|
| Report (JSON) via `json_frontend` + `--output-report-json` | "not yet implemented" | ✅ Shipped (`test_json_report.py` exists; lenses implement `json_frontend`) |
| `--compare` CLI mode with `--label` | "not yet implemented" | ✅ Shipped (`observatory compare --input-archive ... --label ...`) |
| Runtime / delegated-graph accuracy lens | Follow-up | ❌ Not yet implemented |

---

## Known Limitations

1. **Per-layer accuracy is compile-time simulation only (runtime integration is a follow-up).** The `per_layer_accuracy` lens runs CPU simulation across intermediate graph snapshots at `prepare_pt2e`, `convert_pt2e`, and `to_edge_transform_and_lower` — stages not stored in ETRecord. It does **not** compare against actual on-device (delegated) execution. Inspector's `calculate_numeric_gap()` already provides AOT-vs-runtime numerical gap analysis as a DataFrame; a follow-up Observatory lens will consume Inspector's runtime output and overlay it on the graph canvas, bridging compile-time and runtime accuracy in a single visual report.
2. **`fast-sugiyama` requires Python ≥ 3.11 (optional dependency).** When `fast-sugiyama` is not installed or the Python version is < 3.11, `fx_viewer` falls back to a pure-Python topological layout. The fallback produces a correct but less aesthetically optimized graph. All `fx_viewer` features (pan, zoom, search, overlays, N-way compare) remain functional in fallback mode. The Sugiyama layout is gated behind `executorch[observatory-layout]` and is never a hard dependency of `executorch[devtools]`.
3. **Runtime / delegated-graph accuracy not yet implemented.** Comparing on-device (delegated) execution against CPU requires a follow-up lens using `debug_handle` + `Inspector`.

## Public API / Schema Compatibility Checklist

The following are public surfaces — downstream consumers depend on them:

| Surface | Stability | Change requires |
|---------|-----------|----------------|
| Lens protocol (6 hooks + `analyze` signature) | Experimental (candidate stable) | Core sign-off |
| `GraphExtension` API | Experimental (candidate stable) | Core sign-off |
| Archive (JSON) schema | Experimental (candidate stable) | Core sign-off |
| Report (JSON) schema | Experimental (candidate stable) | Core sign-off |
| `FXGraphViewer.create` / `FXGraphCompare.create` (JS) | Experimental (candidate stable) | Core sign-off |
| Backend CLI flags (`--output-html`, `--lens-recipe`, etc.) | Experimental (candidate stable) | Core sign-off |

> **Stability note:** All surfaces are currently experimental. The "candidate stable" designation means these surfaces are designed for stability and will be promoted to stable in a follow-up RFC after one release cycle with real external consumers. No stability guarantee is made until that promotion occurs.
| Per-lens config keys (e.g., `accuracy.evaluator`) | Backend-owned | Backend team |
| Backend-specific lenses | Backend-owned | Backend team |

## Open Questions for Reviewers

1. **Core vs. backend ownership boundary** — Is the `devtools/` vs. `backends/` split sufficient, or do we need a middle tier for cross-backend shared lenses?
2. **Lens API stability signal** — Should lenses declare experimental/stable tiers (like `torch.compile` annotations)?
3. **Breaking-change communication** — Issue label sufficient, or do we need a notification channel for backend owners?

---

## Pre-Generated Demo Reports

Reports are available for 30+ models across XNNPACK and Qualcomm backends. Example:

| Backend | Model | Nodes | Report |
|---------|-------|------:|--------|
| xnnpack | `mobilebert` | 2361 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) |
| qualcomm | `inception_v4` | 1541 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v4/observatory_report.html) |
| xnnpack | `resnet50` | 550 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) |
| qualcomm | `mobilenet_v2` | 521 | [HTML](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) |

Full model matrix: see RFC §3.

---

## Dependencies

- `fast-sugiyama[full]` (Python ≥ 3.11, optional) — Sugiyama graph layout algorithm for `fx_viewer`. A pure-Python fallback layout is used when this package is unavailable (e.g., Python 3.10 environments). Gate behind `executorch[observatory-layout]` to avoid raising the project's Python floor.
- No JavaScript framework dependencies for `fx_viewer` — the canvas renderer is pure HTML/JS with no npm dependencies bundled at runtime.
- Observatory is a client of existing ExecuTorch capture primitives (`ETRecord`, `ETDump`, `Inspector`) — lenses invoke them to acquire runtime data, which Observatory then correlates with FX graph structure and synthesizes into reports. Observatory adds no new capture formats and requires no changes to Inspector or ETRecord.
