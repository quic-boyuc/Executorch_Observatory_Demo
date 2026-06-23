# RFC: Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging

**Status:** Proposed / Under Discussion  
**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers  
**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

> **Positioning note for reviewers:** Observatory is not a replacement for `ETRecord`, `ETDump`, `Inspector`. It is a coordination layer that sits above them.

> **Abstract:** Today, debugging an ExecuTorch model run means writing custom scripts that mix instrumentation, data capture, and analysis. Every backend team rebuilds these scripts independently. Observatory replaces them with a shared coordination layer and a pluggable extension model called *lenses*. A lens is a self-contained debugging concern — it handles both capturing data during the run and analyzing it afterward. Generic lenses work across all backends because they depend only on shared ExecuTorch APIs. Backend teams write and maintain their own lenses for backend-specific analysis. Multiple lenses compose in a single debugging session to produce one integrated report. For a debugging engineer or issue reporter: one zero-config CLI command wraps an existing model script and produces a self-contained HTML report to attach to a PR or an issue. For CI: the same command produces a structured JSON report for regression gates and automated triage.

---

## 1. Summary

Debugging ExecuTorch backend issues often means collecting many things by hand. An engineer may save graph dumps, logs, and accuracy numbers in separate files. The resulting setup and artifacts are hard to reproduce and share meaningfully across community contributors.

This RFC proposes two new components under `devtools/` to address this.

---

**Observatory** replaces fragmented debug scripts with one modularized debugging surface. It standardizes two things:

**How engineers invoke debugging — three entry points, from easiest to most flexible:**

- **CLI** — run your existing model script through Observatory CLI. Your script does not change; Observatory records the whole run from outside.
- **Decorator** — add `@observe_pass` above a compiler pass class, or wrap existing pass instances with `observe_pass(instance)`. Observatory records the FX graph before and after each time the pass runs — without modifying the pass logic or the surrounding pipeline.
- **Context manager** — wrap a `with Observatory.enter_context(...)` block around the code you want to inspect, and call `Observatory.collect(name, artifact)` for the objects you want recorded. This is the manual surface when you need exact control; the CLI and decorator are built on top of it.

**Where task-specific logic attaches — lenses hook into four lifecycle stages:**

- **Instrument** — patch compilation and runtime to collect evidence.
- **Serialize** — write that evidence into a portable archive.
- **Analyze** — run analysis logic over the collected data.
- **Visualize** — render results for humans and machines.

Observatory handles the lifecycle orchestration so that backend teams only write the analysis logic. That logic lives in pluggable modules called *lenses*. A lens is a self-contained debugging concern — it includes callbacks for both capturing data during the run and analyzing it afterward. Generic lenses work on any backend because they only depend on shared ExecuTorch APIs; backend-specific lenses are maintained by each backend team inside its own debugging workflow. Multiple lenses compose in a single debugging session to produce one integrated report.

Concretely, three roles benefit:

- **A backend debug-logic maintainer** writes a Lens once (e.g., per-layer accuracy analysis) and Observatory handles session orchestration, data collection, and report generation.
- **A debugging engineer or issue reporter** runs an Observatory CLI command over an existing model script and gets a self-contained HTML report to attach to a PR or an issue — open it in any browser.
- **CI pipelines** run an Observatory CLI command and consume a structured JSON report for regression gates and automated triage. HTML reports can be generated on demand from the JSON archive.

---

**`fx_viewer`** is a Python and JavaScript library for embedding interactive FX graph views into any HTML page or debugging report. It embeds graph layout and debugging data as JSON layers in a single HTML file — each Observatory Lens can contribute its own overlay, and the result opens instantly in any browser without a server.

- **Embeddable** — drop into any HTML page or `<div>`; graph data is compressed and embedded as JSON in the file. The JavaScript API allows external control of node hovering, selection, and viewport actions.
- **Extensible data layers** — any debugging signal can be overlaid directly on graph nodes: accuracy gradients, partition boundaries, profiling numbers, quantization parameters. Each layer is added via the Python extension API (`GraphExtension`) and rendered independently, so multiple tools can paint on the same graph without conflict.
- **Simplicity** — ~4k lines of plain JavaScript, no framework dependencies. Easy to read, modify, or embed anywhere.
- **Instant rendering** — layout is computed in Python before export. Other tools calculate layout in the browser on load, which is slow for large graphs. `fx_viewer` opens a 10k-node graph instantly.


---

## 2. Motivation & Problem Statement

As ExecuTorch backend compilation pipelines grow in complexity, debugging compiler passes and hardware-specific lowerings has become increasingly painful. Two primary frictions compound across backends, artifact types, and development teams.

### 2.1 The Debugging Workflow is Fragmented

Debugging is a five-stage workflow: **instrument** the run, **configure** it, **export** captured artifacts, **analyze** metrics/differences, and **visualize** the results.

ExecuTorch’s existing devtools provide excellent primitives for raw capture. In particular, the `Inspector` and `ETRecord`/`ETDump` APIs offer a great primitive interface for dumping arbitrary runtime binary blobs, leaving the backend and developer to design their own interpretation logic in Python scripts. However, because there is no common framework to manage the execution scripts, configuration, and data-synthesis workflow *around* these Inspector outputs, the tooling landscape remains fragmented:

*   **No Shared Lifecycle Contract:** Because there is no common session model, backends must build bespoke wrapper scripts (e.g., `qnn_intermediate_debugger.py` on Qualcomm, and separate equivalents for XNNPACK) that manually sequence: configure Inspector, invoke the compiler, collect raw activation blobs at the right pipeline stages, run accuracy simulations, and parse binary data. Each script reinvents the same lifecycle logic — when to start, when to collect, when to stop, how to clean up — with no shared contract and no reuse across backends.
*   **No Extension Common Ground:** There is no shared place for a backend team to plug in specialized analysis logic, meaning the code that interprets Inspector raw data cannot be reused across different backends.
*   **No Graph-Anchored Visual Correlation:** Inspector natively correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle` (a unique ID mapped from Python FX graph nodes to compiled binary operations), and exposes this as pandas DataFrames. However, there is no shared layer that (a) captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e` (standard PyTorch 2 Export compiler passes that transform the FX graph) — stages that are not stored in ETRecord and are invisible to Inspector — and (b) synthesizes Inspector's runtime correlation data together with these compile-time snapshots into a single visual, interactive report. Developers are left to write Python scripts to interpret DataFrames, with no graph-anchored visual representation.
*   **No Multi-Concern Synthesis:** Even when individual analyses succeed, their outputs remain in disconnected formats — console prints, ad-hoc CSVs, static screenshots. There is no shared layer that combines accuracy data, partition assignments, stack trace provenance, and graph structure into a single navigable view for human review or systematic CI parsing.

These four workflow gaps are addressed by the unified lifecycle and Lens protocol specified in §5.

### 2.2 The Graph Has No Workflow-Aware Viewer

The `torch.fx` graph module is the core IR for ExecuTorch lowering, yet developers have no easy way to interact with it in-pipeline:

*   **Deployment Barriers:** The current visualization tool (`devtools/visualization/` using Model Explorer) requires launching a blocking local web server and opening a dedicated browser tab. This prevents embedding graph views in standalone files, attaching them to issue threads, or running visualization in CI. While Model Explorer supports saving a JSON file for later viewing, rendering still requires launching its server.
*   **Visual Signal Isolation:** Model Explorer visualizes module hierarchy and supports QDQ cluster/partition highlighting, but it has no extension model for overlaying arbitrary debugging signals (accuracy loss, profiling data, stack traces) on the same graph. Developers must use separate dashboards or custom scripts to correlate these signals.

The standalone, server-free rendering model that addresses these deployment barriers is specified in §7.

---

## 3. Goals, Non-Goals, and System Boundaries

### Goals

*   **Shared Lifecycle and Extension Contract:** Define a lightweight protocol (**Lens**) allowing backend teams to encapsulate one debugging concern — including how to configure existing `Inspector`/`ETRecord` primitives, when to collect artifacts, how to analyze the results, and how to render them — once, and have the framework handle session management, archive storage, and report assembly automatically (see §5.3 for the Lens protocol).
*   **Unified Invocation:** Support zero-code-change CLI execution, nested Python context managers, and pass-level decorators (see §4 for invocation interfaces).
*   **Portable Outputs:** Produce a single, self-contained, server-free HTML file for human review, and a structured Archive JSON for archival and regression comparison (see §5.1 for the capture/analyze split).
*   **Layered Graph Visualizations:** Embed an interactive, canvas-based FX graph renderer (`fx_viewer`) supporting dynamic overlays and synchronized multi-graph comparison views (see §7).

### Non-Goals

*   **Replacing or Extending Inspector/ETRecord:** Observatory defines no new binary capture formats, no new runtime instrumentation hooks, and no new ETDump/ETRecord schemas. All raw data capture continues to flow through `ETRecord`, `ETDump`, and `Inspector` exactly as today. Observatory's only new code is the coordination and synthesis logic that sits above these primitives, consuming them as clients through lenses. The capture primitives remain owned and governed by their existing maintainers.
*   **Unifying Hardware Schemas:** It does not force backends into a single runtime trace schema. Backends define their own data representations inside their respective lenses.
*   **Live Profiling Stream:** The focus is on offline, post-run report generation and CI/regression comparison rather than real-time streaming telemetry.

### Boundaries and Relationship with Existing Tools

Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them. It is a **workflow lifecycle coordinator and visual synthesis layer** that wraps around them:

*   **`ETRecord` / `ETDump` / `Inspector`:** Inspector natively correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle` (a unique ID mapped from Python FX graph nodes to compiled binary operations) and exposes this as DataFrames. Observatory lenses can consume Inspector's correlated output and synthesize it — together with intermediate compile-time graph snapshots that Inspector cannot access — into visual, interactive overlays on the FX graph canvas.
*   **Complementary and Non-Overlapping Scope:** Inspector specializes in *runtime event capture, `debug_handle`-to-graph-node correlation, and per-operator numerical gap analysis* — all exposed as DataFrames for programmatic use. Observatory specializes in three areas Inspector does not address: *capturing intermediate compile-time graph snapshots* (pre-ETRecord stages invisible to Inspector), *active zero-config workflow coordination* (forcing `generate_etrecord=True`, managing pipeline region structure), and *visual synthesis* (transforming DataFrames and graph snapshots into a portable, interactive HTML report).

#### Tool Positioning Comparison

| Feature / Property | `ETRecord` / `ETDump` | `Inspector` | `devtools/visualization/` | **Observatory** + **fx_viewer** |
|---|---|---|---|---|
| **Primary role** | AOT artifact storage; runtime trace capture | Post-hoc analysis of ETDump + ETRecord files | Interactive model structure browser (Model Explorer) | Live workflow coordinator + visual synthesis layer |
| **Lifecycle** | During export / during runtime | After the run (file-based) | Call server in python; blocks until closed | Collect artifacts during compilation; export reports offline |
| **Input** | ExportedProgram, runtime binary blobs | ETDump file + ETRecord file | ExportedProgram | Any artifact type via `collect()` |
| **Output** | Binary files (`.etrecord`, `.etdump`) | DataFrames, tabular text, numeric gap | Blocking web server + browser tab; or JSON file requiring server to view | Self-contained HTML/JSON Report + JSON Archive |
| **Extension model** | None | `delegate_metadata_parser` callback | Style JSON + `get_node_partition_name` callbacks | Lens protocol (8 methods, full lifecycle) |
| **Embeddable in report** | No | No | No (opens own tab) | Yes (first-class) |
| **Cross-stage comparison** | No | AOT vs. runtime (single pair) | No | N-way, any stages, any backends |
| **CI-friendly output** | Binary blobs | DataFrames (not CI-native) | Not supported | Archive JSON + Report JSON (structured, diffable) |
| **Replaces any of the above?** | — | No | No | **No** |

---

## 4. User-Facing Surfaces and Outputs

A debugging tool is only useful if it meets developers where they already are. ExecuTorch developers enter the debugging workflow from three different places — and Observatory exposes one surface for each, all funnelling into the same capture machinery.

> **Vocabulary preview:** Observatory uses the terms **Session**, **Region**, **Record**, **Archive**, **Report**, and **Lens** throughout the rest of this RFC. These terms are defined once through a concrete run walkthrough in §5.2.

### 4.1 CLI

The CLI wraps an existing export or compile script with zero code changes:

```bash
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html report.html --lens-recipe accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

No client script modifications are required. Lenses install scoped monkey-patches on standard pipeline entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`) during their `on_session_start` hook. These patches transparently call `Observatory.collect()` at the right moments, and all originals are unconditionally restored when the session closes, even on exceptions. This is the surface CI and issue-reproduction workflows use.

> **How it works (simplified):** The built-in `pipeline_graph_collector` lens patches `convert_pt2e` to capture the graph before and after quantization:
> ```python
> # Inside the lens — not user code:
> original_convert = torchao.quantization.pt2e.quantize_pt2e.convert_pt2e
>
> def patched_convert_pt2e(model, *args, **kwargs):
>     Observatory.collect("Calibrated Model", model)       # capture input
>     result = original_convert(model, *args, **kwargs)    # call original
>     Observatory.collect("Quantized Model", result)       # capture output
>     return result
>
> torchao.quantization.pt2e.quantize_pt2e.convert_pt2e = patched_convert_pt2e
> # Restored on session end.
> ```
> The same pattern applies to `prepare_pt2e` and `to_edge_transform_and_lower`. See §5.3 for the full Lens lifecycle.

### 4.2 Context Manager

The context manager scopes capture to a block from inside Python. The full lifecycle — capture, export archive, and generate report — is shown below:

```python
import torch
from executorch.devtools.observatory import Observatory

Observatory.clear()  # Start a fresh in-process state.
gm = export_model(model)
with Observatory.enter_context("quantization"):  # Outermost region opens a session.
    Observatory.collect("before_quantize", gm)  # Capture stage 1.
    quantized_gm = quantize_model(gm)
    Observatory.collect("after_quantize", quantized_gm)  # Capture stage 2.

# Archive JSON: raw sessions/records for CI storage or replay.
Observatory.export_json("archive.json")
# HTML report: interactive dashboard from the current session.
Observatory.export_html_report("report.html", title="Quantization debug")
# Late binding: regenerate HTML from a saved archive without rerunning.
Observatory.generate_html_from_json("archive.json", "report_v2.html")
```

Nested `enter_context` calls push config overrides that are popped on exit — enabling per-phase lens tuning without touching the surrounding code. Observatory records only the artifacts explicitly passed to it. Each call to `Observatory.collect(name, artifact)` passes that object to every registered Lens, and each Lens decides what to extract.

### 4.3 `@observe_pass` Decorator

The `@observe_pass` decorator is for pass authors. It automatically captures the FX graph before and after the pass runs. The pass logic itself requires zero modifications.

**As a class decorator** — define a new pass with built-in tracing:

```python
import operator
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.passes import ExportPass, PassManager
from torch.fx.passes.infra.pass_base import PassResult

@observe_pass(name="fold_add_zero")  # Captures graph before and after.
class FoldAddZeroPass(ExportPass):
    def call(self, gm):
        # Ordinary pass logic — no Observatory calls needed.
        for node in list(gm.graph.nodes):
            if node.target is operator.add and node.args[1] == 0:
                node.replace_all_uses_with(node.args[0])
                gm.graph.erase_node(node)
        gm.graph.lint(); gm.recompile()
        return PassResult(gm, True)

Observatory.clear()
with Observatory.enter_context("pre_lowering_passes"):
    PassManager([FoldAddZeroPass()])(export_model(model))
Observatory.export_html_report("pass_trace.html")  # Includes before/after graphs.
```

**As an instance wrapper** — wrap existing pass instances in an established pipeline (e.g., `QnnPassManager`) without modifying their class definitions:

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.backends.qualcomm._passes import FoldQDQ, LayoutTransform, RemoveRedundancy
from executorch.exir.pass_manager import PassManager

# Existing pass instances — no source changes needed.
passes = [FoldQDQ(), LayoutTransform(), RemoveRedundancy()]

# Wrap each instance to capture its input/output graphs.
observed_passes = [observe_pass(p) for p in passes]

Observatory.clear()
with Observatory.enter_context("qnn_capture_program"):
    PassManager(observed_passes)(graph_module)
Observatory.export_html_report("qnn_passes.html")  # One report with all pass diffs.
```

### 4.4 Output Artifacts

All three surfaces can produce outputs for **two audiences**:

*   **Human:** A self-contained **Report HTML** — server-free, attachable to any issue or PR thread.
*   **Machine:** A raw **Archive JSON** (captured state, no analysis baked in) and a derived **Report JSON** (analyzed findings for CI gates, dashboards, and LLM triage).

The distinction between raw Archive JSON and analyzed Report HTML/JSON is enforced by the architectural split detailed in §5.

---

## 5. Core Design & Architecture: Capture First, Analyze Later

### 5.1 The Foundational Split

Observatory revolves around one architectural principle: **capturing data during a run is a different job from reasoning about it afterward.**

Because compiler passes and runtime executions are transient, the capture phase must record raw artifacts immediately to prevent data loss. So the capture phase has one job — write everything down, as cheaply as possible, and stop.

Unlike data capture, post-hoc analysis is computationally expensive, highly iterative, and frequently modified. Analysis should be repeatable without re-running the model. Observatory keeps the two phases on opposite sides of a hard boundary, with a file between them.

That file is the **Archive**: the raw, neutral record of what happened — `sessions[]` and `records[]` in JSON, with no analysis baked in. From it, Observatory derives the **Report**: an opinionated rendering of what it means. Think of the Archive as a structured event log and the Report as a dashboard rendered from it. Any dashboard can be rebuilt from the log — and new dashboards, with new questions, can be built weeks later. The log cannot be rebuilt from a dashboard.

This split explains why the Archive JSON generated by the CLI (§4.1) or Context Manager (§4.2) can be late-bound analyzed. It makes three workflows possible:

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

Rather than defining terms in isolation, one compilation flow through the system builds the vocabulary. All scopes are created through a single API: `Observatory.enter_context(name, config)`.

A run starts by opening a **Session** — the outermost scope, identified by a `session_id`. This is the only boundary where lens lifecycle hooks fire (`on_session_start`, `on_session_end`). There is one session per Observatory invocation.

Inside the session, the compiler enters a pass — say, `quantize_pass`. Decorated with `@observe_pass`, it opens a **Region**. Regions are pure labels: nested named scopes (stored as a `region_stack` list) that say "the current capture is inside quantization." They fire no lens hooks and run no analysis code. They exist so that later, in the report's tree view, reviewers know *where* in the pipeline each piece of data came from.

Each `enter_context` can carry a **config** dict that merges into the parent's config on entry and pops on exit. This lets authors toggle lens behavior per-region (e.g., disable expensive accuracy simulation for a fast sub-pipeline) without touching surrounding code.

Inside that region, the pass calls `Observatory.collect("graph_after_qdq", fx_graph)`. That produces a **Record** — one observation tagged with the current `session_id` and the full `region_stack` at the moment of capture. Records are the atoms of the Archive.

When the session closes, Observatory serializes session metadata and all records into the **Archive**. That is the entire output of the capture phase; nothing has been interpreted yet.

The analysis phase then loads the Archive, runs the configured lenses over it, and emits the **Report** — HTML for humans, JSON for machines. Same Archive, different lenses, different reports. Re-runnable indefinitely.

```
         PYTHON CODE                              RESULTING STRUCTURE
───────────────────────────────────────    ─────────────────────────────────────────

with enter_context("mv2_debug",          Session: "mv2_debug"
    config={accuracy: {enabled: True}}):   config: {accuracy: {enabled: True}}
                                           🔔 on_session_start (patches installed)
  │
  │ with enter_context("quant",            ├─ Region: "quant"
  │     config={accuracy:                  │    config: +{sim_batch: 8}
  │       {sim_batch: 8}}):                │
  │   collect("Quantized", gm)             │    └─ Record₁  ["quant"]
  │                                        │
  │ with enter_context("lowering"):        ├─ Region: "lowering"  (config: inherited)
  │   │                                    │
  │   │ with enter_context("pass_1"):      │    ├─ Region: "pass_1"
  │   │   collect("before", gm)            │    │    ├─ Record₂  ["lowering", "pass_1"]
  │   │   collect("after", out)            │    │    └─ Record₃  ["lowering", "pass_1"]
  │   │                                    │    │
  │   │ with enter_context("pass_2"):      │    ├─ Region: "pass_2"
  │   │   collect("before", gm)            │    │    ├─ Record₄  ["lowering", "pass_2"]
  │   │   collect("after", out)            │    │    └─ Record₅  ["lowering", "pass_2"]
  │   │                                    │    │
  │   │ collect("final", gm)               │    └─ Record₆  ["lowering"]
  │                                        │
  (exit outermost)                         🔔 on_session_end (patches restored)
                                           serialize → archive.json

═══════════════════════════════ offline boundary ═══════════════════════════════

                    analyze(records, config) + get_frontend_spec()
                              │
                              ▼
                    [Report HTML] + [Report JSON]
```

> **Disambiguation:** An Observatory **Record** is an in-memory observation tagged with `session_id` and `region_stack`. ExecuTorch's existing **`ETRecord`** is an entirely separate on-disk artifact produced by the developer-tools serialization workflow. The names collide; the concepts do not. Observatory may consume `ETRecord` data as an input source through a future lens, but the two are architecturally independent.

### 5.3 The Lens Protocol: How Backends Plug In

Once the capture/analysis split is accepted, a lens needs to do two things at two different times: react during capture by recording what matters, and reason offline by interpreting what was recorded. The framework defines a protocol of lifecycle hooks that any backend can implement:

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

The lens never decides *when* to fire, *where* it is in the pipeline, or *what* the Archive schema is. The framework owns those. The lens owns only the question it answers. The hooks defined in the Lens Protocol constitute one of the stable public surfaces governed under §9.

---

## 6. Working Demos and Persona Walkthroughs

Observatory connects raw data capture and visual analysis. This section walks through three real developer roles, with live compilation and triage demos for each. Demo report links, raw logs, and local video paths are collected in Appendix A.

### 6.1 Backend Debug-Logic Maintainer

*   **Goal:** Ship per-layer accuracy debugging logic once, and have it work uniformly across all backends.
*   **Today:** ExecuTorch's `Inspector` provides `calculate_numeric_gap()` for AOT-vs-runtime comparison, but using it requires manual Python scripts and is limited to the final Edge Dialect graph stored in `ETRecord` (see §2.1 for the broader workflow gap).
*   **With Observatory:** A backend owner writes a single `Lens` class to intercept and analyze intermediate stages. The framework automatically coordinates session lifecycles, collects snapshots, and generates reports. The CLI execution command is unified across backends.

> **⚠️ Note on Demo Scope:** The walkthrough video and current draft PR demonstrate **compile-time AOT accuracy simulation** (CPU-simulated metrics over AOT FX graph stages like `prepare_pt2e` and `convert_pt2e`). Real on-device runtime execution accuracy (which maps ETDump binary data on the device back onto the final Edge Dialect graph using `debug_handle` + `Inspector`) is a planned, targeted scope in the post-RFC roadmap and is not shown in this specific compile-time demo.

**Zero-Config CLI Walkthrough:**

Observatory can run with zero code changes over any existing compiler or model script. For instance, to capture compiler stages and accuracy simulation on Qualcomm's HTP backend:

```bash
pip3 install 'fast-sugiyama[full]'   # Python >= 3.11

python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens-recipe accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

*Note: A `lens-recipe` is a named preset bundle of active lenses. For example, `accuracy` enables the per-layer accuracy lens plus its core dependencies.*

To run the equivalent command for XNNPACK, use `python -m executorch.backends.xnnpack.debugger.observatory` and swap the script and flags. The CLI structure remains identical.

**Interactive HTML Output Elements:**

*   **Session Dashboard:** Displays metadata of the run (command line arguments, active environment, models, and registered lenses).

    ![Session Dashboard](demo_material/session_dashboard.png)

*   **Interactive Layered Graph:** Click any stage to inspect nodes, pan, zoom, or search. Click any node to instantly view compiler metadata, stack trace provenance, and simulated per-operator execution metrics (cosine similarity, PSNR, MSE) visualized as a color gradient directly on the canvas.

    ![Interactive FX Graph](demo_material/interactive_graph.png)

### 6.2 AOT Pipeline / Pass Author

*   **Goal:** Easily diff FX graphs across compiler passes without modifying existing pass logic.
*   **Today:** Developers must manually sprinkle `print(gm.graph)` statements inside pass code, redirect verbose console logs, and eyeball structural differences side-by-side in separate terminal windows.
*   **With Observatory:** A pass author decorates any pass class with `@observe_pass` or wraps a compiler phase in a `with Observatory.enter_context(region_name)` block. Each compiler phase automatically saves graph snapshots as nested Records in the Left Panel tree. Click on any Record to view its isolated graph, or select two stages to view a synchronized, node-mapped visual comparison.

**The Region Concept & Tree Structure:**

A **Region** is a logical execution scope opened by `enter_context(region_name)`. As defined in §5.2, it supports nesting and configuration inheritance. As the compilation pipeline executes, Observatory constructs a hierarchical region stack (e.g., `preprocess/` -> `edge/` -> `edge/etrecord/`).

In the Left Panel of the generated HTML report, a **Record Tree-Explorer** allows developers to toggle between a flat time-ordered list and a directory-like folders tree view, keeping compile-time snapshots structured exactly like the compiler's passes.

![Record Tree Explorer](demo_material/records_explorer.png)

**Code Walkthrough (with nesting and config overrides):**

Lenses observe and capture metadata when `Observatory.collect()` is called, or when patched functions run. The context manager config is stacked: configuration overrides are merged on entry and popped on exit. This lets authors dynamically adjust lens behavior (e.g., bypass expensive CPU simulation) for specific sub-pipelines or passes:

```python
from executorch.devtools.observatory import Observatory, observe_pass

# 1. Zero-effort pass tracking via decorators
@observe_pass
class MyOptimizationPass(ExportPass):
    def call(self, gm):
        # Modify the graphmodule...
        return gm

# 2. Managing nested regions & configuration stack
pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyOptimizationPass())

# Disable accuracy lens for fast preprocessing, then enable it only for transformation
Observatory.clear()
with Observatory.enter_context("preprocess",
                               config={"per_layer_accuracy": {"enabled": False}}):

    Observatory.collect("raw_input", graph_module)

    # Nest another context with config overrides
    # The string "lowering_stage" becomes the Region name in the tree view
    with Observatory.enter_context("lowering_stage",
                                   config={"per_layer_accuracy": {"enabled": True}}):
        # Inside here, the per_layer_accuracy lens is active and simulates intermediate errors
        processed_gm = pm._transform(graph_module)
        Observatory.collect("transformed_output", processed_gm)

    # per_layer_accuracy is automatically disabled again here on exit

# Export: the tree-explorer in the HTML report reflects the nested region structure.
Observatory.export_html_report("pass_diff_report.html")
```

### 6.3 CI / Nightly-Regression / Cross-Backend Triage

*   **Goal:** Compare execution runs across branches, dates, or backends, and serve the results programmatically to humans or CI/LLM gates.
*   **Today:** High-throughput CI runs dump large zip bundles containing fragmented CSVs, console logs, and static screenshots. These must be manually downloaded and inspected, making automated regression tracking and LLM triaging impossible.
*   **With Observatory:** Nightly pipelines save only a lightweight, raw `Archive JSON` file (excluding expensive HTML rendering). Later, developers or CI gates can compare any two Archive files (even across backends or branches) via `--compare` to generate a synchronized comparative HTML Report or a machine-readable Report JSON summary, without ever re-running the compiler. This follows the capture/analyze split defined in §5.1.

**Automated CI Workflow & Architecture:**

The relationship between Session (live execution), Archive JSON (persisted raw data), and derived Report payloads (HTML / JSON) is illustrated below:

```
             AOT Run in CI Pipeline (e.g. Nightly)
                   ┌──────────────────┐
                   │   AOT Compiler   │ (Forced generate_etrecord=True)
                   └────────┬─────────┘
                            │
                  ┌─────────▼─────────┐
                  │  Observatory Core │ (Intercepts standard entry points)
                  └────────┬─────────┘
                            │
                  ┌─────────▼─────────┐
                  │   ARCHIVE JSON    │ (sessions[] + records[], no rendering)
                  │  (nightly/mv2.json)│ (Persisted raw state, lightweight)
                  └────────┬──────────┘
                           │
          ┌────────────────┴────────────────┐
          │ Late-bound Analysis             │ CI / Automated Triage
          ▼                                 ▼
 ┌─────────────────┐               ┌─────────────────┐
 │   Report HTML   │               │   Report JSON   │
 │  (Interactive,  │               │   (Key metrics, │
 │  for reviewers) │               │   for LLMs / CI)│
 └─────────────────┘               └─────────────────┘
   --output-html                    --output-report-json
```

**CLI Execution Interface:**

The same Archive JSON is late-bound re-analyzed or compared without re-running the expensive compiler or simulator:

```bash
# 1. CI / Nightly run: captures the execution state into a raw Archive JSON
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-archive nightly/2026-04-20/mv2.json \
    --lens-recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize

# 2. Later: compare two archives to generate a comparative HTML and a summary JSON
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html \
    --output-report-json regression.summary.json
```

**Cross-Backend Triage & N-way Node Selection Sync:**

The same `--compare` flow powers cross-backend triage. Clicking a node in XNNPACK's graph automatically highlights, centers, and maps the corresponding node in Qualcomm's graph, allowing developers to visually compare lowering, fusion, and accuracy boundaries side-by-side.

![Cross-Backend Compare](demo_material/cross_backend_compare.png)

---

## 7. `fx_viewer` — The Layered Graph Visualizer

As described in §4 and §5.1, the human-readable Report HTML embeds graph structures; `fx_viewer` is the portable substrate that renders them. To support complex compiler debugging, `fx_viewer` is designed as a standalone, server-free, canvas-based graph visualizer.

### 7.1 Key Requirements

*   **Zero Local Servers:** The viewer runs entirely in-browser. This avoids the networking and port-binding issues of traditional server-backed visualization tools.
*   **Build-Time Layout:** Graph extraction and coordinate layout are performed at build-time in Python. The HTML report carries pre-computed coordinates, allowing instantaneous canvas painting on load.
*   **Sugiyama Layout Algorithm:** Coordinates are pre-computed in Python using `fast-sugiyama` (a standard hierarchical layering layout approach for directed acyclic graphs, requiring Python >= 3.11). For 10k+ node graphs, doing this work before export avoids browser startup lag and keeps report opening fast. For older Python environments or environments wishing to avoid layout dependencies, pre-computed layouts can be skipped, falling back to basic rendering or client-side caching.
*   **Layered Design:** The viewer separates the structural **Base Layer** (nodes, structural edges) from custom **Extension Layers** contributed by lenses (such as accuracy colors, profiling statistics, or quantization bounds).
*   **Embeddable API:** The viewer can be mounted into any HTML page or `<div>` and controlled by the surrounding report shell.

### 7.2 Python and JS API Boundaries

`fx_viewer` maintains a strict separation from Observatory via two clean public boundaries:

```
  BUILD-TIME (Python API)                RUN-TIME (JS API, Browser)
┌─────────────────────────┐            ┌────────────────────────────┐
│ • FXGraphExporter       │  produces  │ • FXGraphViewer.create     │
│ • GraphExtension        │ ─────────► │ • FXGraphCompare.create    │
│ • Extension Layers      │            │ • Layer / ColorBy Mutators │
└─────────────────────────┘            └────────────────────────────┘
```

1.  **Build-Time (Python API):** Lenses import `fx_viewer` to convert FX `GraphModule`s into coordinate-bound payloads and register custom `GraphExtension` layers.
2.  **Run-Time (JS API):** Observatory’s report shell consumes the compiled JS bundle of `fx_viewer` to mount active viewers, trigger theme/layer changes, and drive selection-synchronization in comparison mode.

The JavaScript API allows the surrounding report to:

*   create a single graph viewer with `FXGraphViewer.create(...)`;
*   create synchronized comparison views with `FXGraphCompare.create(...)`;
*   control node hovering and selection from outside the canvas;
*   center, zoom, and pan the viewport to a selected node or region;
*   enable or disable extension layers without changing the base graph payload.

The coordinate-bound Python export classes and JS runtime components form stable contracts governed under §9.

---

## 8. Scope, RFC Acceptance Boundary, and Roadmap

Observatory’s features are organized into three clear phases. Some items listed as **Proposed in This RFC** already exist in the accompanying POC branch in `devtools/observatory/` for validation purposes. They are still presented as proposed here to seek design review and establish stable API and schema contracts before they are promoted to production-ready devtools features (see §9).

| Feature Area | Shipped in Draft Branch | Proposed in This RFC | Future Work (Follow-ups) |
|:---|:---:|:---:|:---:|
| **Core Infrastructure** | Python Context Manager, `@observe_pass`, Region Tree View, Core Session Lifecycle | Standardized Archive JSON Reloading, Stable Lens Protocol Hooks | Automated Nightly CI regression templates |
| **Lenses (Debugging Concerns)** | Compile-Time Accuracy, FX Graph Capture, Stack-Trace Provenance, Run Metadata, Pipeline Step Patches | **Report JSON via `json_frontend`** (structured machine summary) | Runtime/Delegated Accuracy, QNN QHAS profiling, XNNProfiler aggregation, QParam Audit |
| **`fx_viewer` (Visuals)** | Pan/Zoom/Minimap, Fuzzy Search, N-Way Node-Selection Sync, Multi-Layer Overlays | Stable Build-Time Python & Run-Time JS Boundaries | Support for non-FX graph formats (TOSA, PyTorch JIT, delegated graphs) |
| **CLI Capabilities** | Backend-specific & generic CLI wrappers | **`--compare` CLI Mode** (Archive-to-Regression report generation) | Live streaming-telemetry dashboard |

*Note: **Report (JSON)** via `json_frontend` and the **`--compare` CLI mode** are already fully implemented and tested inside the accompanying POC branch in `devtools/observatory/` for validation purposes. However, they are presented in this RFC as 'Proposed' to seek active design reviews and establish stable API and schema contracts before they are promoted to stable, production-ready devtools features.*

---

## 9. Governance and API Stability

As a shared infrastructure component used by core devtools and various backend teams (Qualcomm, XNNPACK, ARM, etc.), Observatory establishes clear boundaries of ownership and stability.

### 9.1 Ownership Boundaries

*   **Core devtools reviewers** own `devtools/observatory/` core, `devtools/fx_viewer/` core, the Lens Protocol contract (§5.3), and the generic lenses (graph, metadata, compile-time accuracy).
*   **Backend teams** own their respective backend subdirectories (e.g., `backends/qualcomm/debugger/observatory/` and `backends/xnnpack/debugger/observatory/`), including backend-registered patches and custom backend lenses. No core sign-off is needed for backend-private lenses.

### 9.2 Public Surfaces and Compatibility

To prevent breaking downstream tooling, CI systems, or automated dashboards, four public surfaces are designated as **stable contracts**:

1.  **The Lens Protocol Interface:** Signature of the lifecycle hooks, including context passing and analysis argument shapes (§5.3).
2.  **`GraphExtension` Python API:** Method names and parameters used to build overlays (§7.2).
3.  **Archive JSON Schema:** The structured format for raw session/record serializations (§5.1).
4.  **Report JSON Schema (Proposed):** The structured format for derived analytical results (§5.1 and §8).

Any non-backward-compatible change to these four contracts must follow a staged migration process: announce in advance via issue/RFC, and keep backward-compatibility aliases where feasible. The related reviewer questions are listed in §10.

---

## 10. Open Questions for Reviewers

We are seeking active feedback on the following design decisions, along with concrete initial recommendations to facilitate review.

### Q1 — Where is the line between core and backend ownership, and how does a lens cross it?

*   **Decision Requested:** Confirm whether the binary ownership split in §9.1 is enough, or whether Observatory needs a recognized middle tier for lenses shared by two-or-more backends but not truly universal.
*   **Context:** Today the rule is binary — generic lenses live in `devtools/observatory/lenses/`, backend-specific lenses live in `backends/<name>/...`. Examples of possible shared-but-not-universal lenses include a quantization-accuracy lens used by both XNNPACK and Qualcomm.
*   **Trade-offs to Discuss:** A middle tier reduces duplication but adds an ownership grey zone and a third CODEOWNERS bucket. A strict binary split is simpler to govern but may push shared logic into copy-paste.
*   **Starting Recommendation:** Keep the binary split for v1; treat "shared-by-two-backends" as a *core* lens that the two backends opt into via their recipe, and define promotion as a normal core-owned PR that (a) moves the file, (b) leaves a one-release import shim, and (c) is announced per §9.2's breaking-change policy.

### Q2 — Should lenses carry an explicit stability tier?

*   **Decision Requested:** Decide whether each lens, and the Lens protocol itself, should declare an **experimental / stable** tier.
*   **Context:** External contributors need to know what is safe to depend on. A backend owner should be able to tell whether building on `per_layer_accuracy` today risks a breaking change tomorrow.
*   **Trade-offs to Discuss:** Stability tiers give downstream consumers a real contract and let core evolve experimental lenses freely. They also add annotation overhead and the obligation to honor "stable." Without tiers, everything is implicitly experimental, which slows external adoption.
*   **Starting Recommendation:** Annotate at two levels — the **Lens protocol + the two JSON schemas** (Archive, Report) as the stable, change-controlled surface (§9.2 already treats them as such), and individual lenses default to *experimental* until a maintainer promotes them. Mark `graph`, `metadata`, and the Archive schema as the first *stable* set since the demo matrix already depends on them.

### Q3 — What channel announces breaking changes to known backend owners?

*   **Decision Requested:** Decide whether a GitHub **issue label** (`observatory-api-change`) is enough discovery, or whether an active push channel is required.
*   **Context:** §9.2 requires breaking changes to the Lens protocol / `GraphExtension` / the two JSON schemas to be either fixed in the same PR or announced and staged. Backend owners should be notified rather than expected to discover changes by accident.
*   **Trade-offs to Discuss:** A label is zero-infrastructure but relies on people subscribing. An active channel guarantees reach but needs an owner and a keep-the-list-current process.
*   **Starting Recommendation:** Do both with low cost — require the `observatory-api-change` label *and* a CODEOWNERS entry on the protocol/schema files so any breaking PR auto-requests the core + registered backend teams. Revisit a mailing list only if the backend-owner set grows beyond what CODEOWNERS handles cleanly.

> **Coordinator note:** All three prompts are deliberately phrased to invite a decision, not just opinion — each ends with a concrete recommendation reviewers can accept, amend, or reject. That tends to move RFC threads faster than fully-open questions.

---

## Appendix A. Demo Reports, Videos, and Generated Assets

This appendix keeps large proof artifacts out of the main reading path while preserving all demo links and local paths from the draft.

### A.1 Demonstration Videos

*   **Video 1 (Walkthrough):** A video walkthrough of the zero-config script, complete observatory report entries, and interactive `fx_viewer` features is available in this repository at: [walkthrough_from_issue.mp4](demo_material/walkthrough_from_issue.mp4).
*   **Video 2 (Local High-Resolution Master):** A high-resolution copy of this video is also hosted locally on the supervisor's system at: `C:\Users\boyuc\OneDrive - Qualcomm\Desktop\Observatory_Final1_x264_12fps.mp4` (accessible on WSL at `/mnt/c/Users/boyuc/OneDrive - Qualcomm/Desktop/Observatory_Final1_x264_12fps.mp4`).

### A.2 Pre-Generated Single-Run Demo Reports

These reports showcase individual, backend-specific runs. Lenses active here include `metadata`, `stack_trace`, `graph`, `accuracy`, and `per_layer_accuracy` (compile-time simulation). These are backend-specific because they demonstrate individual backend executions and, where applicable, backend-owned workflow integrations.

| Backend | Model | Nodes | Report | JSON Summary | Log |
|---|---|---:|---|---|---|
| xnnpack | `mobilebert` | 2361 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/run.log.txt) |
| xnnpack | `resnet50` | 550 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/run.log.txt) |
| xnnpack | `mv2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/run.log.txt) |
| qualcomm | `swin_v2_t` | 1494 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/run.log.txt) |
| qualcomm | `mobilenet_v2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/run.log.txt) |

### A.3 Pre-Generated Cross-Backend Comparison Demo Reports (XNNPACK vs. Qualcomm QNN)

These comparison matrices evaluate end-to-end differences in structure, partition boundaries, and numerical accuracy for the **same model** compiled across different backends (XNNPACK vs. Qualcomm's HTP backend), demonstrating how the `--compare` flow serves as a visual and programmatic triage engine.

| Model | Backend Pair | Comparison HTML | JSON Summary | Raw Log |
|---|---|---|---|---|
| MobileNetV2 | `xnnpack/mv2` vs `qualcomm/mobilenet_v2` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/comparison.log.txt) |
| MobileNetV3 | `xnnpack/mv3` vs `qualcomm/mobilenet_v3` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/comparison.log.txt) |
| InceptionV3 | `xnnpack/ic3` vs `qualcomm/inception_v3` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/comparison.log.txt) |
| InceptionV4 | `xnnpack/ic4` vs `qualcomm/inception_v4` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/comparison.log.txt) |
| ViT | `xnnpack/vit` vs `qualcomm/torchvision_vit` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/comparison.log.txt) |
