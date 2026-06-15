### 4.2 Surfaces: Three Entry Points, Two Artifact Kinds

A debugging tool is only useful if it meets you where you already are. ExecuTorch developers enter the debugging workflow from three different places — and Observatory exposes one surface for each, all funnelling into the same capture machinery.

**The CLI** wraps an existing export or compile script with zero code changes:

```bash
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html report.html --lens-recipe accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

You change nothing about your script. Observatory shims standard pipeline entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`) via scoped monkey-patching — patches are installed when the session opens and unconditionally restored when it closes, even on exceptions. This is the surface CI and issue-reproduction workflows use.

**The context manager** scopes capture to a block from inside Python:

```python
from executorch.devtools.observatory import Observatory

with Observatory.enter_context("my_debug_run", config={"accuracy": {"enabled": True}}):
    gm = export_model(model)
    Observatory.collect("exported_graph", gm)
```

Same machinery, finer control. Nested `enter_context` calls push config overrides that are popped on exit — enabling per-phase lens tuning without touching the surrounding code.

**The `@observe_pass` decorator** is for pass authors. Annotate a transform and it gets its own scope automatically — capturing the FX graph before and after, with no edits to the surrounding pipeline:

```python
@observe_pass
class MyQuantPass(ExportPass):
    def call(self, gm): ...
```

All three surfaces can produce outputs for **two audiences**:
*   **Human:** A self-contained **Report HTML** — server-free, attachable to any issue or PR thread.
*   **Machine:** A raw **Archive JSON** (captured state, no analysis baked in) and a derived **Report JSON** (analyzed findings for CI gates, dashboards, and LLM triage).

The split between raw capture and derived analysis isn't cosmetic — it's the central design decision, and it's what §5 explains.

---

## 5. How It Works: Capture First, Analyze Later

### 5.1 The Foundational Split

Observatory revolves around one architectural principle: **capturing data during a run is a different job from reasoning about it afterward.**

When a compilation runs, you get one shot. Whatever the tool fails to record at that moment is gone forever. So the capture phase has one job — write everything down, as cheaply as possible, and stop.

Reasoning about that data is the opposite kind of work. It's slow, opinionated, sometimes wrong, and you want to redo it without re-running the model. Observatory keeps the two phases on opposite sides of a hard boundary, with a file between them.

That file is the **Archive**: the raw, neutral record of what happened — `sessions[]` and `records[]` in JSON, with no analysis baked in. From it, Observatory derives the **Report**: an opinionated rendering of what it means. Think of the Archive as a structured event log and the Report as a dashboard rendered from it. You can rebuild any dashboard from the log — and build new ones, with new questions, weeks later. You cannot rebuild the log from a dashboard.

This split makes three workflows possible:
*   **CI efficiency:** Nightly pipelines write only the lightweight Archive JSON — no rendering overhead.
*   **Late-bound analysis:** Engineers re-analyze old archives with new lenses weeks later, without re-running the compiler.
*   **Regression comparison:** Two archives from different commits diff directly via `--compare`, producing a comparative report without re-executing either run.

```
── CAPTURE (online, during the run) ──────│── ANALYSIS (offline, from the Archive) ──
                                          │
  Observatory.enter_context(...)          │  Lens.analyze(records, config)
  Observatory.collect(name, artifact)     │         │
         │                                │         ▼
         ▼                                │  get_frontend_spec() → Frontend
  [Archive JSON]  ────────────────────────┼──►  dashboard() / record()
  sessions[] + records[]                  │         │
  (raw, no analysis)                      │         ▼
                                          │  [Report HTML]  +  [Report JSON]
```

### 5.2 Vocabulary, Built From a Run

Rather than defining terms in isolation, watch one compilation flow through the system — the vocabulary builds itself.

You start a run. That opens a **Session** — the outermost scope, identified by a `session_id`. This is the only boundary where lens lifecycle hooks fire (`on_session_start`, `on_session_end`). One session per Observatory invocation.

Inside the session, the compiler enters a pass — say, `quantize_pass`. Decorated with `@observe_pass`, it opens a **Region**. Regions are pure labels: nested named scopes (stored as a `region_stack` list) that say "we are now inside quantization." They fire no lens hooks and run no analysis code. They exist so that later, in the report's tree view, you know *where* in the pipeline each piece of data came from.

Inside that region, the pass calls `Observatory.collect("graph_after_qdq", fx_graph)`. That produces a **Record** — one observation tagged with the current `session_id` and the full `region_stack` at the moment of capture. Records are the atoms of the Archive.

When the session closes, Observatory serializes session metadata and all records into the **Archive**. That's the entire output of the capture phase; nothing has been interpreted yet.

The analysis phase then loads the Archive, runs the configured lenses over it, and emits the **Report** — HTML for humans, JSON for machines. Same Archive, different lenses, different reports. Re-runnable indefinitely.

> **Disambiguation:** An Observatory **Record** is an in-memory observation tagged with `session_id` and `region_stack`. ExecuTorch's existing **`ETRecord`** is an entirely separate on-disk artifact produced by the developer-tools serialization workflow. The names collide; the concepts do not. Observatory may consume `ETRecord` data as an input source through a future lens, but the two are architecturally independent.

### 5.3 The Lens Protocol: How Backends Plug In

Once you accept the capture/analysis split, the shape of a lens writes itself. A lens needs to do two things at two different times: react during capture (recording what matters), and reason offline (interpreting what was recorded). The framework defines a protocol of lifecycle hooks that any backend can implement:

| Phase | Method | Fires when |
|:---|:---|:---|
| Registration | `setup()` | One-time, at lens registration |
| **Capture (online)** | `on_session_start(context)` | Session opens — install instrumentation, prepare calibration data |
| | `observe(artifact, context)` | Each `Observatory.collect()` — filter; return `None` to skip |
| | `digest(observation, context)` | Immediately after `observe` — serialize into the Record's digest map |
| | `on_session_end(context)` | Session closes — restore patches, finalize live state |
| **Analysis (offline)** | `analyze(records, config)` | At emit time — compute derived insights across all records → `AnalysisResult` |
| | `get_frontend_spec()` | Returns a `Frontend` strategy with `dashboard()` and `record()` callbacks |
| Cleanup | `clear()` | Reset global state between runs |

Note that `digest` fires **online**, immediately paired with `observe`. This is deliberate: a lens that only needs a reduction (e.g., a per-node histogram) never has to persist the raw artifact into the Archive — it persists only its own reduced state. The boundary between capture and analysis is defined by *what gets persisted*, not by what code runs when.

**Concrete example — the Accuracy lens:**

1. `on_session_start` — prepares a small calibration dataset and installs pipeline patches.
2. `observe` — watches for `GraphModule` artifacts at each collection point; returns `None` for non-graph records.
3. `digest` — runs both the float-reference and quantized graphs on the calibration batch, serializes per-operator PSNR/cosine/MSE into the Record. *(This executes online because live Python graph objects are not serializable — the raw measurements must be materialized at capture time.)*
4. `on_session_end` — restores all monkey-patches.
5. `analyze` — ranks operators by accuracy degradation across all collected records; flags those below a configurable threshold.
6. `get_frontend_spec()` → `Frontend.dashboard()` renders a session-level accuracy summary table; `Frontend.record()` contributes a `GraphExtension` color-overlay layer so the `fx_viewer` canvas paints a green-to-red gradient on the worst-performing nodes.

Notice what the lens never does: it never decides *when* to fire, *where* it is in the pipeline, or *what* the Archive schema is. The framework owns those. The lens owns only the question it's answering.
