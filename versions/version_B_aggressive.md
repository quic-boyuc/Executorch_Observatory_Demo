# RFC: Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging

**Status:** Proposed / Under Discussion  
**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers  
**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

> **Positioning note for reviewers:** Observatory is not a replacement for `ETRecord`, `ETDump`, `Inspector`. It is a coordination layer that sits above them.

> **Abstract:** Today, debugging an ExecuTorch model run means writing custom scripts that mix instrumentation, data capture, and analysis. Every backend team rebuilds these scripts independently. Observatory replaces them with a shared coordination layer and a pluggable extension model called *lenses*. A lens is a self-contained debugging concern — it handles both capturing data during the run and analyzing it afterward. Generic lenses work across all backends because they depend only on shared ExecuTorch APIs. Backend teams write and maintain their own lenses for backend-specific analysis. Multiple lenses compose in a single debugging session to produce one integrated report. For a debugging engineer or issue reporter: one zero-config CLI command wraps an existing model script and produces a self-contained HTML report to attach to a PR or an issue. For CI: the same command produces a structured JSON report for regression gates and automated triage.

---

## 1. Summary

This section provides a high-level executive summary of the Observatory framework, the fx_viewer component, and the benefits they deliver to backend developers, compiler pass authors, and CI pipelines.

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

This section diagnoses the key systemic frictions and tool fragmentation in current ExecuTorch backend debugging and visualization workflows.

As ExecuTorch backend compilation pipelines grow in complexity, debugging compiler passes and hardware-specific lowerings has become increasingly painful. Two primary frictions compound across backends, artifact types, and development teams:

### 2.1 The Debugging Workflow is Fragmented
Debugging is a five-stage workflow involving instrumenting the run, configuring the environment, exporting captured artifacts, analyzing metrics/differences, and visualizing the results.

ExecuTorch's existing devtools provide excellent primitives for raw capture. In particular, the `Inspector` and `ETRecord`/`ETDump` APIs offer a great primitive interface for dumping arbitrary runtime binary blobs, leaving the backend and developer to design their own interpretation logic in Python scripts. However, because there is no common framework to manage the execution scripts, configuration, and data-synthesis workflow around these Inspector outputs, we see a fragmented tooling landscape with several distinct issues:
* **No Shared Lifecycle Contract:** Because there is no common session model, backends must build bespoke wrapper scripts (e.g., `qnn_intermediate_debugger.py` on Qualcomm, and separate equivalents for XNNPACK) that manually sequence: configure Inspector, invoke the compiler, collect raw activation blobs at the right pipeline stages, run accuracy simulations, and parse binary data. Each script reinvents the same lifecycle logic — when to start, when to collect, when to stop, how to clean up — with no shared contract and no reuse across backends.
* **No Extension Common Ground:** There is no shared place for a backend team to plug in specialized analysis logic, meaning the code that interprets Inspector raw data cannot be reused across different backends.
* **No Graph-Anchored Visual Correlation:** Inspector natively correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle` (a unique ID mapped from Python FX graph nodes to compiled binary operations), and exposes this as pandas DataFrames. However, there is no shared layer that (a) captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e` (standard PyTorch 2 Export compiler passes that transform the FX graph) — stages that are not stored in ETRecord and are invisible to Inspector — and (b) synthesizes Inspector's runtime correlation data together with these compile-time snapshots into a single visual, interactive report. Developers are left to write Python scripts to interpret DataFrames, with no graph-anchored visual representation.
* **No Multi-Concern Synthesis:** Even when individual analyses succeed, their outputs remain in disconnected formats — console prints, ad-hoc CSVs, static screenshots. There is no shared layer that combines accuracy data, partition assignments, stack trace provenance, and graph structure into a single navigable view for human review or systematic CI parsing.

These four workflow gaps are addressed by the unified lifecycle and Lens protocol specified in §5.

### 2.2 The Graph Has No Workflow-Aware Viewer
The `torch.fx` graph module is the core IR for ExecuTorch lowering, yet developers have no easy way to interact with it in-pipeline:
* **Deployment Barriers:** The current visualization tool (`devtools/visualization/` using Model Explorer) requires launching a blocking local web server and opening a dedicated browser tab. This prevents embedding graph views in standalone files, attaching them to issue threads, or running visualization in CI. While Model Explorer supports saving a JSON file for later viewing, rendering still requires launching its server.
* **Visual Signal Isolation:** Model Explorer visualizes module hierarchy and supports QDQ cluster/partition highlighting, but it has no extension model for overlaying arbitrary debugging signals (accuracy loss, profiling data, stack traces) on the same graph. Developers must use separate dashboards or custom scripts to correlate these signals.

The standalone, server-free rendering model to address these deployment barriers is specified in §7.


---

## 3. Goals, Non-Goals, and System Boundaries

This section establishes the explicit goals and non-goals of the Observatory framework, defining its system boundaries via a comparative positioning analysis against existing ExecuTorch devtools.

### 3.1 Goals
* **Shared Lifecycle and Extension Contract:** Define a lightweight protocol (**Lens**) allowing backend teams to encapsulate one task-specific debugging concern (see §5.3 for the Lens protocol) — including how to configure existing `Inspector`/`ETRecord` primitives, when to collect artifacts, how to analyze the results, and how to render them — once, and have the framework handle session management, archive storage, and report assembly automatically.
* **Unified Invocation:** Support zero-code-change CLI execution, nested Python context managers, and pass-level decorators (see §4 for invocation interfaces).
* **Portable Outputs:** Produce a single, self-contained, server-free HTML file for human review, and a structured Archive JSON for archival and regression comparison.
* **Layered Graph Visualizations:** Embed an interactive, canvas-based FX graph renderer (`fx_viewer`) supporting dynamic overlays and synchronized multi-graph comparison views (see §7).

### 3.2 Non-Goals
* **Replacing or Extending Inspector/ETRecord:** Observatory defines no new binary capture formats, no new runtime instrumentation hooks, and no new ETDump/ETRecord schemas. All raw data capture continues to flow through `ETRecord`, `ETDump`, and `Inspector` exactly as today. Observatory's only new code is the coordination and synthesis logic that sits above these primitives, consuming them as clients through lenses. As shown in the Tool Positioning Comparison table, Observatory does not replace runtime primitives — they remain owned and governed by their existing maintainers.
* **Unifying Hardware Schemas:** Observatory does not force backends into a single runtime trace schema. Backends define their own data representations inside their respective task-specific lenses.
* **Live Profiling Stream:** The focus is on offline, post-run report generation and CI/regression comparison rather than real-time streaming telemetry.

### 3.3 Tool Positioning Comparison

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

This section defines the three entry points for invoking Observatory and specifies the two physical formats of debugging output generated by the framework.

### 4.1 Three Entry Points
A debugging framework must integrate seamlessly with existing development workflows. Observatory provides three distinct invocation surfaces to accommodate different integration levels:

* **The CLI (Zero Code-Change Wrapper):** Executes an existing model compilation or export script from the command line. No script modifications are required because lenses install scoped monkey-patches on standard pipeline functions (such as `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`) during their `on_session_start` hook. These patches transparently call `Observatory.collect()` at the right moments, and all originals are restored when the session ends.
  ```bash
  python -m executorch.backends.xnnpack.debugger.observatory \
      --output-html report.html \
      --lens-recipe accuracy \
      examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
  ```
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
* **The Context Manager (Fine-Grained Block Scope):** Wraps specific blocks of Python compiler code to capture and record target artifacts programmatically. The full lifecycle — capture, export archive, and generate report — is shown below:
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
  Nested `enter_context` calls push configuration overrides that are popped on exit, enabling per-phase lens tuning.

* **The `@observe_pass` Decorator (Pass-Level Trace):** Decorates individual compiler transform classes to automatically capture the input and output FX graphs. The pass logic itself requires zero modifications.

  As a **class decorator** — define a new pass with built-in tracing:
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

  As an **instance wrapper** — wrap existing pass instances in an existing pipeline without modifying their class definitions. This is the primary use case for debugging passes inside an established pass manager (e.g., `QnnPassManager`):
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

### 4.2 Two Output Formats
Observatory separates raw execution state from its final visual and analytical representations, generating two distinct artifact types:
* **Archive JSON (Raw Execution Store):** A neutral, structured, and lightweight JSON serialization containing the recorded raw data and session metadata (`sessions[]` and `records[]`). It contains no baked-in analysis or HTML styling, making it highly efficient for CI storage.
* **Report HTML/JSON (Derived Analysis Payloads):**
  * *Report HTML (Human Dashboard):* A single, portable, and server-free HTML file containing interactive graphs and performance summaries. It can be shared directly via email, attached to PR comments, or reviewed in any browser.
  * *Report JSON (Machine Summary):* A structured JSON file summarizing critical metrics and flagged regressions, optimized for automated CI gates, dashboard parsing, and LLM triage.

The distinction between the raw Archive JSON and the analyzed Report HTML/JSON is enforced by the architectural split detailed in §5.

---

## 5. Core Design & Architecture: Capture First, Analyze Later

This section details the core architectural split between raw data capture and offline analysis, defines the core execution vocabulary, and specifies the stable Lens Protocol.

### 5.1 The Foundational Split
The Observatory architecture is governed by a fundamental separation of concerns: online data capture during compilation must be decoupled from offline analysis and visualization.

Because compiler passes and runtime executions are transient, the capture phase must record raw artifacts immediately to prevent data loss. The capture phase is designed to be highly lightweight and fast, minimizing runtime intrusion. Conversely, unlike data capture, post-hoc analysis is computationally expensive, highly iterative, and frequently modified. 

To resolve this tension, Observatory captures raw compiler states into a neutral, unrendered **Archive JSON** file. Downstream analysis and visualization are late-bound operations that process the Archive JSON to produce the human-readable **Report HTML** or machine-readable **Report JSON**. This split enables developers to re-analyze historical compilation runs with newly written lenses without re-running the expensive compiler or simulation pipeline.

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

This foundational split explains why the Archive JSON generated by the CLI (§4.1) or Context Manager (§4.1) can be late-bound analyzed or compared across runs without executing the compiler again.

### 5.2 Vocabulary, Built From a Run
The primary abstractions of the Observatory framework are defined through the life cycle of a single model compilation:

1. **Session:** The global lifecycle container representing a single, complete debugging execution run. It is initialized upon compiler entry, identified by a unique `session_id`, and triggers global lens setup and teardown hooks.
2. **Region:** A named, logical compilation scope. Regions can be nested (e.g., `preprocess/` -> `quantization/`) to form a hierarchical stack, which maps directly to the tree-explorer panel in the final HTML report. Regions do not capture data; they provide structural context.
3. **Record:** An individual observation captured within a Region. It is generated when `Observatory.collect(name, artifact)` is called, containing the artifact's serialized representation (the digest) and metadata, stamped with the current `session_id` and the active `region_stack` path.
4. **Archive:** The raw, unrendered JSON file containing all captured Sessions and Records.
5. **Report:** The derived analytical payload generated by parsing the Archive. This can be an interactive HTML dashboard or a structured JSON summary.
6. **Lens:** A modular, task-specific plugin that encapsulates both capture-time recording logic and post-hoc analysis/visualization behaviors.

```
Session ─────────────────────────────────────────────────────────────────────────
│  on_session_start                                              on_session_end │
│                                                                              │
│  Region: "quantize_pass"                                                     │
│  ├─ collect("before_qdq") → Record₁ {region_stack: ["quantize_pass"]}        │
│  └─ collect("after_qdq")  → Record₂ {region_stack: ["quantize_pass"]}        │
│                                                                              │
│  Region: "lowering"                                                          │
│  └─ collect("lowered")    → Record₃ {region_stack: ["lowering"]}             │
│                                                                              │
└──────────────── serialize ──► [Archive JSON: sessions[] + records[]]          │
                                        │                                      │
                                        ▼  (offline, later)                    │
                                 analyze + get_frontend_spec()                  │
                                        │                                      │
                                        ▼                                      │
                                 [Report HTML] + [Report JSON]                 │
```

> **Disambiguation:** An Observatory **Record** is an in-memory or JSON-persisted compile-time observation tagged with session and region info. It is entirely independent of ExecuTorch's existing **`ETRecord`** file, which is a serialized compilation package used by runtime tools.


### 5.3 The Lens Protocol: How Task-Specific Logic Plugs In
Observatory uses a pluggable extension architecture. Developers implement a unified, task-specific **Lens** protocol to encapsulate both compile-time collection and offline analysis logic.

The framework manages session lifecycles and file serialization, while the Lens focuses entirely on a specific debugging concern. The Lens Protocol is defined by eight lifecycle methods:

| Phase | Method | Trigger | Purpose |
|:---|:---|:---|:---|
| Registration | `setup()` | Framework initialization | Performs one-time setup upon lens registration. |
| **Capture (online)** | `on_session_start(context)` | Session initialization | Prepares state, installs necessary compiler patches, or initializes calibration datasets. |
| | `observe(artifact, context)` | `Observatory.collect()` call | Evaluates the captured artifact; returns `None` to skip non-matching types. |
| | `digest(observation, context)` | Immediately after `observe` | Serializes raw observations into the Record's digest map before writing to disk. |
| | `on_session_end(context)` | Session termination | Uninstalls active patches, restores global state, and finalizes live state. |
| **Analysis (offline)** | `analyze(records, config)` | Report generation | Processes all captured Records across the Session to compute derived insights. |
| | `get_frontend_spec()` | Visualization generation | Returns a `Frontend` schema with dashboard-level and record-level rendering callbacks. |
| Cleanup | `clear()` | Core session reset | Resets any thread-local or global state to ensure clean successive runs. |

#### Walkthrough of the Accuracy Lens
To illustrate the flow of the Lens Protocol, consider the execution of the standard compile-time Accuracy lens:
1. `on_session_start` prepares a calibration dataset and installs temporary execution patches.
2. `observe` filters incoming artifacts, reacting only to PyTorch `GraphModule` types while ignoring other metadata objects.
3. `digest` executes the model on the calibration dataset to calculate and serialize per-operator PSNR, cosine similarity, and mean-squared error (MSE). This execution is performed online because Python graph objects are transient and cannot be serialized directly.
4. `on_session_end` restores all monkey-patched compiler functions to their original states.
5. `analyze` processes the compiled digests across all records, ranking operations by accuracy loss and flagging operators that violate configurable thresholds.
6. `get_frontend_spec` supplies two visual targets: `Frontend.dashboard()` outputs a session-wide accuracy summary, and `Frontend.record()` registers a `GraphExtension` overlay layer that colors the `fx_viewer` nodes on a green-to-red gradient based on accuracy loss.

The hooks defined in the Lens Protocol constitute one of the stable public surfaces governed under §9.

---

## 6. Working Demos and Persona Walkthroughs

This section validates the Observatory architecture through three real-world developer personas, detailing their workflows, CLI invocations, and code-level integrations.

### 6.1 Persona A: Backend Debug-Logic Maintainer
* **Goal:** Implement and deploy per-layer accuracy debugging logic once, running it uniformly across multiple ExecuTorch backends.
* **Today's Pain (Diagnosis):** Devtools lack a unified lifecycle contract to configure and collect raw activation data across intermediate compilation stages (e.g., `prepare_pt2e` and `convert_pt2e`), forcing maintainers to write duplicate, vendor-SDK bespoke scripts that output fragmented console text and CSVs ([see §2.1](#21-the-debugging-workflow-is-fragmented)).
* **With Observatory:** The maintainer implements the logic within a single `Lens` subclass. The CLI coordinates the compilation session, executes the compiler, and outputs a self-contained HTML report displaying compile-time simulation metrics.
  ```bash
  python -m executorch.backends.qualcomm.debugger.observatory \
      --output-html obs_report.html \
      --lens-recipe accuracy \
      examples/qualcomm/oss_scripts/mobilevit_v2.py \
      --backend htp --model SM8650 -d ./imagenet-mini-val/ \
      -b build-android/ --compile_only
  ```
* **Evidence:** Pre-generated single-run HTML reports and walkthrough videos are hosted in [Appendix A.1](#appendix-a1-pre-generated-single-run-reports-and-walkthrough-videos).

### 6.2 Persona B: AOT Pipeline / Pass Author
* **Goal:** Inspect and compare PyTorch FX graph structural differences before and after custom compiler passes without modifying the core pipeline code.
* **Today's Pain (Diagnosis):** Authors must manually inject verbose print statements inside pass classes, redirect terminal outputs, and visually compare large, flat text representations of FX graphs side-by-side ([see §2.1](#21-the-debugging-workflow-is-fragmented)).
* **With Observatory:** The author annotates the pass using the `@observe_pass` decorator or wraps compiler phases inside a nested `enter_context` block to generate a structured, hierarchical tree of captured graph states ([see §5.2's definition of Regions](#52-vocabulary-built-from-a-run)).
  ```python
  from executorch.devtools.observatory import Observatory, observe_pass

  @observe_pass
  class MyOptimizationPass(ExportPass):
      def call(self, gm):
          return gm

  Observatory.clear()
  with Observatory.enter_context("preprocess", config={"per_layer_accuracy": {"enabled": False}}):
      Observatory.collect("raw_input", graph_module)
      with Observatory.enter_context("lowering_stage", config={"per_layer_accuracy": {"enabled": True}}):
          processed_gm = MyOptimizationPass()(graph_module)
          Observatory.collect("transformed_output", processed_gm)
  # Export: the tree-explorer in the HTML report reflects the nested region structure.
  Observatory.export_html_report("pass_diff_report.html")
  ```
* **Evidence:** Visual screenshots of the hierarchical Record Tree-Explorer panel are available in [Appendix A.2](#appendix-a2-record-tree-explorer-visuals).

### 6.3 Persona C: CI / Nightly-Regression / Cross-Backend Triage
* **Goal:** Compare compilation runs across distinct git commits, branches, or backends to automate regression detection and programmatic triage.
* **Today's Pain (Diagnosis):** Regression suites generate large archives of binary artifacts and static logs that require manual download and manual correlation, blocking automated regression gates and LLM-based triage ([see §2.1](#21-the-debugging-workflow-is-fragmented) and [§2.2](#22-the-graph-has-no-workflow-aware-viewer)).
* **With Observatory:** Nightly pipelines save a lightweight Archive JSON containing the raw compile state without rendering overhead; downstream tools run `--compare` to late-bound generate comparative reports without re-executing the model ([see §5.1's Capture/Analyze split](#51-the-foundational-split)).
  ```bash
  # 1. CI Capture Phase (saves raw Archive JSON)
  python -m executorch.backends.xnnpack.debugger.observatory \
      --output-archive nightly/2026-04-20/mv2.json \
      --lens-recipe=accuracy \
      examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize

  # 2. Programmatic Compare Phase (compares runs and outputs reports)
  python -m executorch.devtools.observatory \
      --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
      --output-html regression.html \
      --output-report-json regression.summary.json
  ```
* **Evidence:** Cross-backend comparison matrices and machine-readable JSON summaries are cataloged in [Appendix A.3](#appendix-a3-cross-backend-comparison-reports).


---

## 7. `fx_viewer` — The Layered Graph Visualizer

This section describes the technical design, layout performance, and programming interfaces of the server-free interactive graph visualizer.

As described in §4 and §5.1, the human-readable Report HTML embeds graph structures; `fx_viewer` is the portable substrate that renders them.

### 7.1 Standalone and Server-Free Design
Conventional graph visualization tools require running a local web server (such as Model Explorer) to compute layouts or serve assets. This layout model creates significant deployment barriers when sharing reports across isolated environments or embedding them directly inside CI dashboards and PR threads. 

To bypass these friction points, `fx_viewer` runs entirely on client-side browser technology. Graph structures and coordinates are fully computed at build-time in Python. The output HTML carries pre-packaged CSS and JS alongside compressed, layout-bound JSON data, allowing instant, interactive rendering on any device without a background server.

### 7.2 Python and JavaScript API Boundaries
To maintain a strict separation of concerns, the visualizer exposes two public API surfaces:

```
  BUILD-TIME (Python API)                RUN-TIME (JS API, Browser)
┌─────────────────────────┐            ┌────────────────────────────┐
│ • FXGraphExporter       │  produces  │ • FXGraphViewer.create     │
│ • GraphExtension        │ ─────────► │ • FXGraphCompare.create    │
│ • Extension Layers      │            │ • Layer / ColorBy Mutators │
└─────────────────────────┘            └────────────────────────────┘
```

* **Python API (Build-Time):** Used by lenses to export `GraphModule` objects. The `FXGraphExporter` processes structural graphs, while `GraphExtension` allows lenses to overlay custom data structures on graph nodes.
* **JavaScript API (Run-Time):** Consumed by the Report HTML shell to render the graph canvas. It provides constructor functions (`FXGraphViewer.create` for single views, `FXGraphCompare.create` for synchronized side-by-side views) and exposes mutator event hooks for external control of node hovering, selection, and viewport actions.

### 7.3 Performance Scaling and Layout Processing
Computing node placement in the browser is slow and resource-heavy for large models. To address this scaling limit, `fx_viewer` offloads layout calculations to the compile-time Python stage.

Coordinates are pre-computed using the Sugiyama layout algorithm (a standard hierarchical layering layout approach for directed acyclic graphs). This pre-computation utilizes the `fast-sugiyama` layout library (requiring Python >= 3.11). If the build environment lacks this dependency or uses older Python versions, coordinates are bypassed, falling back to standard tree layouts or client-side layout caching.

Because the HTML payload contains final rendering coordinates, `fx_viewer` opens a 10,000-node graph instantaneously, bypassing browser-side computational bottlenecks.

### 7.4 Layered Overlay Architecture
The visualizer separates the structural graph model from analytical overlays:
* **The Base Layer:** Renders immutable graph elements, including operations, inputs, outputs, and their structural dataflow edges.
* **Extension Layers:** Registered by individual Lenses (such as quantization boundaries, operator profile timings, or accuracy loss). Multiple lenses can paint overlays on the same Base Layer without structural interference, enabling unified visualization of independent compiler concerns.

The coordinate-bound Python export classes and JS runtime components form stable contracts governed under §9.

---

## 8. Scope, RFC Acceptance Boundary, and Roadmap

This section outlines the implementation phases of the proposed capabilities and defines the boundary of formal RFC acceptance.

### 8.1 Scope and Acceptance Boundary
While several of the "Proposed" features (such as Report JSON and `--compare` mode) have been implemented as proof-of-concept components in `devtools/observatory/` for validation, they are formally presented in this RFC to seek design approval. RFC acceptance establishes stable API contracts, serialization schemas, and core directory layouts before these features are promoted to production.

### 8.2 Execution Roadmap

| Feature Area | Shipped in Draft Branch | Proposed in This RFC | Future Work (Follow-ups) |
|:---|:---:|:---:|:---:|
| **Core Infrastructure** | Python Context Manager, `@observe_pass`, Region Tree View, Core Session Lifecycle | Standardized Archive JSON Reloading, Stable Lens Protocol Hooks | Automated Nightly CI regression templates |
| **Lenses (Debugging Concerns)** | Compile-Time Accuracy, FX Graph Capture, Stack-Trace Provenance, Run Metadata, Pipeline Step Patches | Report JSON via `json_frontend` (structured machine summary) | Runtime/Delegated Accuracy, QNN QHAS profiling, XNNProfiler aggregation, QParam Audit |
| **`fx_viewer` (Visuals)** | Pan/Zoom/Minimap, Fuzzy Search, N-Way Node-Selection Sync, Multi-Layer Overlays | Stable Build-Time Python & Run-Time JS Boundaries | Support for non-FX graph formats (TOSA, PyTorch JIT, delegated graphs) |
| **CLI Capabilities** | Backend-specific & generic CLI wrappers | `--compare` CLI Mode (Archive-to-Regression report generation) | Live streaming-telemetry dashboard |

The proposed schema-dependent features listed above are integrated directly with the API stability and schema contracts governed under §9.


---

## 9. Governance and API Stability

This section defines ownership boundaries and establishes stability contracts for core APIs and serialization schemas.

### 9.1 Ownership Boundaries
To manage development across multiple backends, Observatory enforces clear repository and subdirectory boundaries (see [Q1 in §10](#q1--where-is-the-line-between-core-and-backend-ownership-and-how-does-a-lens-cross-it)):
* **Core Devtools Reviewers:** Own the core orchestration logic under `devtools/observatory/` and `devtools/fx_viewer/`, the core Lens Protocol contract, and generic, backend-agnostic lenses (e.g., standard metadata, graph capture, and compile-time accuracy).
* **Backend Teams:** Own their respective backend debugger directories (e.g., `backends/qualcomm/debugger/observatory/` or `backends/xnnpack/debugger/observatory/`), including all vendor-SDK custom patches and backend-specific lenses. No core devtools sign-off is required for backend-specific lens modifications.

### 9.2 Stable Public Surfaces
To protect downstream automated pipelines, four public surfaces are designated as stable, change-controlled contracts (see [Q2](#q2--should-lenses-carry-an-explicit-stability-tier) and [Q3 in §10](#q3--what-channel-announces-breaking-changes-to-known-backend-owners)):
1. **The Lens Protocol Interface:** The lifecycle hook signatures specified in [§5.3](#53-the-lens-protocol-how-task-specific-logic-plugs-in).
2. **`GraphExtension` Python API:** The methods and formats used to construct visual overlays in [§7.2](#72-python-and-javascript-api-boundaries).
3. **Archive JSON Schema:** The raw serialization structure defined in [§5.1](#51-the-foundational-split).
4. **Report JSON Schema (Proposed):** The machine-readable summary output format described in [§5.1](#51-the-foundational-split).

Breaking changes to these contracts require a structured migration path, including deprecation warnings and backward-compatibility aliases where feasible.

---

## 10. Open Questions for Reviewers

This section presents critical design and governance decisions requested from reviewers, complete with trade-off analysis and recommended paths.

### Q1 — Where is the line between core and backend ownership, and how does a lens cross it?
* **Decision Requested:** Define the governance and directory path structure when a lens evolves from backend-specific to shared or generic (see [§9.1](#91-ownership-boundaries)).
* **Context:** Currently, lenses are split binary: generic lenses live in `devtools/observatory/lenses/` and backend-specific lenses live in `backends/<backend_name>/`. It is unclear if a third, middle-tier directory is required for lenses shared by a subset of backends, or what the exact approval process is when "promoting" a lens from a backend directory to core devtools.
* **Trade-offs:** 
  * *Option A (Middle-Tier Directory):* Keeps code DRY but introduces ownership grey zones and complicates `CODEOWNERS` configurations.
  * *Option B (Strict Binary Split):* Simpler to manage but leads to temporary code duplication between active backends.
* **Starting Recommendation:** Maintain the binary directory split for v1. Treat lenses shared by multiple backends as core devtools lenses that backends opt into. Promote a backend-specific lens to core via a standard pull request that relocates the file, leaves a backward-compatibility import shim, and is announced to relevant backend owners.

### Q2 — Should lenses carry an explicit stability tier?
* **Decision Requested:** Determine whether to annotate lenses with stability indicators to guide external tool developers (see [§9.2](#stable-public-surfaces)).
* **Context:** Developers building tooling on top of Observatory's outputs need to understand which lenses are safe to depend on. It is proposed to declare lenses as either *experimental* or *stable*, similar to annotations used in PyTorch core APIs.
* **Trade-offs:** 
  * *Option A (Explicit Annotations):* Provides clear expectations and contracts for users but increases maintenance overhead and limits rapid internal refactoring.
  * *Option B (Implicit Tiers):* Maximizes velocity for core development but slows down adoption by external backend teams fearing breaking changes.
* **Starting Recommendation:** Annotate stability at two boundaries: designate the base Lens Protocol and the two schemas (Archive, Report) as stable. Default individual lenses to *experimental* until they undergo a stabilization review. Mark the core `graph` and `metadata` lenses as the first stable lens implementations.

### Q3 — What channel announces breaking changes to known backend owners?
* **Decision Requested:** Establish a reliable, low-overhead communication channel to notify backend owners of breaking changes to core schemas or protocol hooks (see [§9.2](#stable-public-surfaces)).
* **Context:** High-trust development requires that backend teams are actively alerted when API changes impact their specific custom lenses.
* **Trade-offs:** 
  * *Option A (GitHub Issue Labels):* Requires zero infrastructure but relies on developers manually subscribing to and monitoring labels.
  * *Option B (Active Notification Channel):* Guarantees delivery and proactive response but requires list curation and manual maintenance.
* **Starting Recommendation:** Implement a low-cost, automated solution: require an `observatory-api-change` label on breaking PRs, and map protocol/schema files in `CODEOWNERS` to automatically request reviews from registered backend maintainers whenever those files are modified.

---

## Appendix A. Demo Reports, Videos, and Generated Assets

This appendix aggregates external walk-through assets, pre-generated comparison reports, raw execution logs, and supervisor machine file paths.

### A.1 Pre-Generated Single-Run Reports and Walkthrough Videos
Single-run reports capture individual backend compilations. Lenses active in these reports include `metadata`, `stack_trace`, `graph`, and `per_layer_accuracy` (compile-time simulation).

* **Demonstration Videos:**
  * *Video 1 (Walkthrough):* A walkthrough showing the CLI execution, report navigation, and interactive `fx_viewer` is hosted in this repository at: [walkthrough_from_issue.mp4](demo_material/walkthrough_from_issue.mp4)
  * *Video 2 (Local Master Copy):* A high-resolution local copy is stored on the supervisor’s workstation at: `C:\Users\boyuc\OneDrive - Qualcomm\Desktop\Observatory_Final1_x264_12fps.mp4` (WSL link: `/mnt/c/Users/boyuc/OneDrive - Qualcomm/Desktop/Observatory_Final1_x264_12fps.mp4`)

* **Single-Run Report Catalog:**

| Backend | Model | Nodes | HTML Report | Summary JSON | Raw Execution Log |
|---|---|---:|---|---|---|
| xnnpack | `mobilebert` | 2361 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/run.log.txt) |
| xnnpack | `resnet50` | 550 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/run.log.txt) |
| xnnpack | `mv2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/run.log.txt) |
| qualcomm | `swin_v2_t` | 1494 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/run.log.txt) |
| qualcomm | `mobilenet_v2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/run.log.txt) |

### A.2 Record Tree-Explorer Visuals
The context and region nesting structures described in [§4.1](#41-three-entry-points) generate hierarchical tree layouts inside the HTML viewer. Below are the key dashboard elements:

* **Session Dashboard:** Shows critical run configuration and execution metadata.
  
  ![Session Dashboard](demo_material/session_dashboard.png)

* **Record Tree Explorer Panel:** Organizes captured records according to their logical pipeline regions.
  
  ![Record Tree Explorer](demo_material/records_explorer.png)

* **Layered Overlays:** Visualizes compiler metadata and accuracy gradients directly on graph nodes.
  
  ![Interactive FX Graph](demo_material/interactive_graph.png)

### A.3 Cross-Backend Comparison Reports
These comparison matrices evaluate end-to-end differences in structure, partition boundaries, and numerical accuracy for the same model compiled across different backends (XNNPACK vs. Qualcomm QNN HTP), proving how the `--compare` flow serves as a visual and programmatic triage engine.

* **Cross-Backend Node Alignment:** Node-selection synchronization maintains layout context across side-by-side backend graphs.
  
  ![Cross-Backend Compare](demo_material/cross_backend_compare.png)

* **Comparative Report Catalog:**

| Model | Backend Pair | Comparison HTML | JSON Summary | Comparison Log |
|---|---|---|---|---|
| MobileNetV2 | `xnnpack/mv2` vs `qualcomm/mobilenet_v2` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/comparison.log.txt) |
| MobileNetV3 | `xnnpack/mv3` vs `qualcomm/mobilenet_v3` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv3_vs_qnn_mobilenet_v3/comparison.log.txt) |
| InceptionV3 | `xnnpack/ic3` vs `qualcomm/inception_v3` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic3_vs_qnn_inception_v3/comparison.log.txt) |
| InceptionV4 | `xnnpack/ic4` vs `qualcomm/inception_v4` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_ic4_vs_qnn_inception_v4/comparison.log.txt) |
| ViT | `xnnpack/vit` vs `qualcomm/torchvision_vit` | [HTML Comparison](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/observatory_comparison.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/observatory_comparison.summary.json) | [Comparison Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_vit_vs_qnn_torchvision_vit/comparison.log.txt) |
