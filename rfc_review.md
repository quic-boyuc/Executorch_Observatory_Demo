# RFC: Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging

**Status:** Proposed / Under Discussion  
**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers  
**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

> **Positioning note for reviewers:** Observatory is not a replacement for `ETRecord`, `ETDump`, `Inspector`, or `devtools/visualization/`. Each of those tools is excellent at its specific job. Observatory is the missing coordination layer that sits *above* them: it intercepts standard pipeline entry points during compilation to collect graph snapshots, manages the lifecycle of backend analysis scripts (Lenses), calls `Inspector` to retrieve runtime data for cross-stage correlation, and synthesizes everything into a single portable report. The only new code is the coordination and synthesis logic that every backend team was previously writing by hand, in isolation, in structurally identical but unshared scripts.

> **Abstract:** Observatory is a zero-config workflow coordinator and visual synthesis layer for ExecuTorch debugging. It manages the lifecycle of debugging concerns across the AOT compilation pipeline — configuring when and how existing `Inspector` and `ETRecord`/`ETDump` primitives are invoked, collecting FX graph snapshots at pass boundaries, correlating runtime binary data with graph structure via `debug_handle`, and synthesizing outputs from multiple analysis concerns into a single portable, server-free HTML report. The Lens protocol gives backend teams a formal extension contract: contribute one Python class per debugging concern, and the framework handles session management, archive storage, and report rendering automatically. Observatory adds no new capture formats and requires no changes to Inspector or ETRecord.

---

## 1. Summary

This RFC proposes two new components under `devtools/`:

*   **Observatory:** A zero-config workflow coordinator and visual synthesis layer that manages the lifecycle of debugging concerns across ExecuTorch's AOT compilation pipeline. It wraps around existing `Inspector` and `ETRecord`/`ETDump` primitives as clients — configuring, collecting, correlating, and synthesizing their outputs into a single, structured, interactive, and shareable debugging report — without replacing or duplicating them.
*   **`fx_viewer`:** A standalone, embeddable FX-graph visualizer that powers Observatory's graph view and operates independently outside of it. Graph layout uses `fast-sugiyama` (optional, Python ≥ 3.11); a pure-Python fallback layout is available for older environments.

If you have ever debugged by sprinkling `print(gm.graph)` across a transform pass, or by manually correlating Inspector output with a graph dump in a separate terminal, this RFC is for you. Observatory is the shared coordination layer that eliminates that duplication — without touching `ETRecord`, `ETDump`, or `Inspector`. This proposal focuses on three things: providing a shared lifecycle contract that coordinates *when* and *how* existing capture primitives are invoked; enabling layered, graph-anchored visualization that correlates runtime data with FX graph structure; and establishing a formal extension protocol (Lens) so backend teams contribute specialized analysis logic once rather than rebuilding it per-backend.

---

## 2. Motivation & Problem Statement

As ExecuTorch backend compilation pipelines grow in complexity, debugging compiler passes and hardware-specific lowerings has become increasingly painful. Two primary frictions compound across backends, artifact types, and development teams:

### 2.1 The Debugging Workflow is Fragmented
Debugging is a five-stage workflow: **instrument** the run, **configure** it, **export** captured artifacts, **analyze** metrics/differences, and **visualize** the results.

ExecuTorch’s existing devtools provide excellent primitives for raw capture. In particular, the `Inspector` and `ETRecord`/`ETDump` APIs offer a great primitive interface for dumping arbitrary runtime binary blobs, leaving the backend and developer to design their own interpretation logic in Python scripts. However, because there is no common framework to manage the execution scripts, configuration, and data-synthesis workflow *around* these Inspector outputs, we see a fragmented tooling landscape:
*   **No Shared Lifecycle Contract:** Because there is no common session model, backends must build bespoke wrapper scripts (e.g., `qnn_intermediate_debugger.py` on Qualcomm, and separate equivalents for XNNPACK) that manually sequence: configure Inspector, invoke the compiler, collect raw activation blobs at the right pipeline stages, run accuracy simulations, and parse binary data. Each script reinvents the same lifecycle logic — when to start, when to collect, when to stop, how to clean up — with no shared contract and no reuse across backends.
*   **No Extension Common Ground:** There is no shared place for a backend team to plug in specialized analysis logic, meaning the code that interprets Inspector raw data cannot be reused across different backends.
*   **No Graph-Anchored Correlation:** Runtime binary data from Inspector is tagged with `debug_handle`, but there is no shared layer that maps those handles back to the FX graph nodes that produced them. Developers must manually cross-reference Inspector output with a separate graph dump, making it nearly impossible to answer "which operator caused this accuracy drop?" without significant manual effort.
*   **No Multi-Concern Synthesis:** Even when individual analyses succeed, their outputs remain in disconnected formats — console prints, ad-hoc CSVs, static screenshots. There is no shared layer that combines accuracy data, partition assignments, stack trace provenance, and graph structure into a single navigable view for human review or systematic CI parsing.

### 2.2 The Graph Has No Workflow-Aware Viewer
The `torch.fx` graph module is the core IR for ExecuTorch lowering, yet developers have no easy way to interact with it in-pipeline:
*   **Deployment Barriers:** Current visualization tools (such as Model Explorer integrations) often require a local web server, preventing easy embedding in standalone files or sharing in discussion threads.
*   **Visual Signal Isolation:** Graphs are the most natural visual anchor for debugging information. However, without a shared, layered viewer, developers must look at different dashboards to see accuracy loss, partition assignments, and hardware constraints. 

Observatory and `fx_viewer` address these gaps by providing a unified user surface, a shared extension protocol (**Lenses**), and a server-free, layered graph renderer.

### 2.3 Boundaries and Relationship with Existing Tools
Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them. It is a **workflow lifecycle coordinator and visual synthesis layer** that wraps around them:
*   **`ETRecord` / `ETDump` / `Inspector`:** These tools own raw binary capture at runtime. Observatory lenses invoke them as clients — configuring what gets captured, retrieving the results, and mapping them back onto the FX graph structure via `debug_handle` correlation.
*   **Complementary and Non-Overlapping Scope:** `Inspector` is a post-hoc analysis tool: it is constructed after the run, taking ETDump and ETRecord file paths as arguments. Observatory is a live session coordinator: it operates *during* compilation, intercepting standard pipeline entry points to collect graph snapshots as they are produced. These are different lifecycles. Observatory calls `Inspector` (through a formal bridge) to retrieve runtime data for cross-stage correlation — it does not reimplement Inspector's analysis capabilities.

#### Tool Positioning Comparison

| Feature / Property | `ETRecord` / `ETDump` | `Inspector` | `devtools/visualization/` | **Observatory** |
|---|---|---|---|---|
| **Primary role** | AOT artifact storage; runtime trace capture | Post-hoc analysis of ETDump + ETRecord files | Interactive model structure browser | Live workflow coordinator + visual synthesis layer |
| **Lifecycle** | During export / during runtime | After the run (file-based constructor) | After export | During compilation (live session) |
| **Input** | ExportedProgram, runtime binary blobs | ETDump file + ETRecord file | ExportedProgram / EdgeProgramManager | Any artifact type via `collect()` |
| **Output** | Binary files (`.etrecord`, `.etdump`) | DataFrames, tabular text, numeric gap | Web server + browser tab | Self-contained HTML + Archive JSON + Report JSON |
| **Extension model** | None | `delegate_metadata_parser` callback | `add_node_data()` + regex JSON | Lens protocol (8 methods, full lifecycle) |
| **Embeddable in report** | No | No | No (opens own tab) | Yes (first-class) |
| **Cross-stage comparison** | No | AOT vs. runtime (single pair) | No | N-way, any stages, any backends |
| **CI-friendly output** | Binary blobs | DataFrames (not CI-native) | Not supported | Archive JSON + Report JSON (structured, diffable) |
| **Replaces any of the above?** | — | No | No | **No** |

---

## 3. Goals and Non-Goals

### Goals
*   **Shared Lifecycle and Extension Contract:** Define a lightweight protocol (**Lens**) allowing backend teams to encapsulate one debugging concern — including how to configure existing `Inspector`/`ETRecord` primitives, when to collect artifacts, how to analyze the results, and how to render them — once, and have the framework handle session management, archive storage, and report assembly automatically.
*   **Unified Invocation:** Support zero-code-change CLI execution, nested Python context managers, and pass-level decorators.
*   **Portable Outputs:** Produce a single, self-contained, server-free HTML file for human review, and a structured Archive JSON for archival and regression comparison.
*   **Layered Graph Visualizations:** Embed an interactive, canvas-based FX graph renderer (`fx_viewer`) supporting dynamic overlays and synchronized multi-graph comparison views.

### Non-Goals
*   **Replacing or Extending Inspector/ETRecord:** Observatory defines no new binary capture formats, no new runtime instrumentation hooks, and no new ETDump/ETRecord schemas. All raw data capture continues to flow through `ETRecord`, `ETDump`, and `Inspector` exactly as today. Observatory's only new code is the coordination and synthesis logic that sits above these primitives, consuming them as clients through lenses. The capture primitives remain owned and governed by their existing maintainers.
*   **Unifying Hardware Schemas:** It does not force backends into a single runtime trace schema. Backends define their own data representations inside their respective lenses.
*   **Live Profiling Stream:** The focus is on offline, post-run report generation and CI/regression comparison rather than real-time streaming telemetry.

---

## 4. Proposed User-Facing Capabilities & Working Demos

Observatory bridges the gap between raw data collection and visual analysis by framing its capabilities around three primary use cases and their respective personas, supported by real-world compilation and triage demos.

---

### 4.1 Three Real-World Use Cases & Walkthrough Demos

#### A. Backend Debug-Logic Maintainer — "Ship per-layer accuracy once, for every backend"
**The Pain Today:** Each backend team writes their own enabling, configuring, serializing, and rendering scripts. For example, Qualcomm maintainers write `qnn_intermediate_debugger.py` to wire activation exporting and calculate per-layer accuracy by hand; XNNPACK maintainers write their own ad-hoc equivalent. The same code structure is rewritten repeatedly, ending up in disconnected zips, CSVs, or console printouts.

**With Observatory:** A backend owner contributes exactly one `Lens` to address a specific concern (e.g., per-layer accuracy, partition mapping, or hardware logs). The framework owns the session, raw archive storage, and report presentation. The CLI command structure is entirely unified across backends.

* **Zero-Config CLI Walkthrough:** 
  You can run Observatory with zero code changes over any existing compiler or model script. For instance, to capture compiler stages and accuracy simulation on Qualcomm's HTP backend:

  ```bash
  pip3 install 'fast-sugiyama[full]'   # Python >= 3.11

  python -m executorch.backends.qualcomm.debugger.observatory \
      --output-html obs_report.html \
      --lens-recipe accuracy \
      examples/qualcomm/oss_scripts/mobilevit_v2.py \
      --backend htp --model SM8650 -d ./imagenet-mini-val/ \
      -b build-android/ --compile_only
  ```

  To run the equivalent command for XNNPACK, simply use `python -m executorch.backends.xnnpack.debugger.observatory` and swap the script and flags. The CLI structure remains identical.

* **Demonstration Videos:**
  * **Video 1 (Walkthrough):** A video walkthrough of the zero-config script, complete observatory report entries, and interactive `fx_viewer` features is available in this repository at: [walkthrough_from_issue.mp4](demo_material/walkthrough_from_issue.mp4).
  * **Video 2 (Local High-Resolution Master):** A high-resolution copy of this video is also hosted locally on the supervisor's system at: `C:\Users\boyuc\OneDrive - Qualcomm\Desktop\Observatory_Final1_x264_12fps.mp4` (accessible on WSL at `/mnt/c/Users/boyuc/OneDrive - Qualcomm/Desktop/Observatory_Final1_x264_12fps.mp4`).

* **Interactive HTML Output Elements:**
  * **Session Dashboard:** Displays metadata of the run (command line arguments, active environment, models, and registered lenses).
    
    ![Session Dashboard](demo_material/session_dashboard.png)

  * **Record Tree-Explorer:** Groups individual captured artifacts (such as FX graphs) dynamically into logical compiler phases (Regions) like `edge/prepare_pt2e/` or `edge/convert_pt2e/`.
    
    ![Record Explorer](demo_material/records_explorer.png)

  * **Interactive Layered Graph:** Click any stage to inspect nodes, pan, zoom, or search. Click any node to instantly view compiler metadata, stack trace provenance, and simulated per-operator execution metrics (cosine similarity, PSNR, MSE) visualized as a color gradient directly on the canvas.
    
    ![Interactive FX Graph](demo_material/interactive_graph.png)

#### B. AOT Pipeline / Pass Author — "Diff a graph across passes without touching pass code"
**The Pain Today:** Developers must sprinkle `print(gm.graph)` across passes, dump the text, and eyeball structural differences side-by-side in two separate terminals.

**With Observatory:** Decorate any pass class with `@observe_pass` or wrap a phase in `Observatory.enter_context(...)`. Each compiler phase automatically records graph snapshots as separate Records nested in the tree-view. Click on any record to view its isolated graph, or select two stages to view a synchronized, node-mapped comparison view.

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

Observatory.export_report_html("pass_debug.html")
```

#### C. CI / Nightly-Regression / Cross-Backend Triage — "Compare two runs, serve the result to a human or an LLM"
**The Pain Today:** Large zip archives containing fragmented CSVs, console logs, and screenshots must be inspected manually, making automated regression detection or LLM triaging impossible.

**With Observatory:** CI pipelines run the compilation and save only the lightweight `Archive JSON` without rendering. At a later point, developers can compare any two runs (e.g., across branches, nightly dates, or even different backends) to generate a regression report without re-running the compiler.

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

* **Cross-Backend Triage View:** Side-by-side FX graphs from different backends. Clicking a node in one backend's graph automatically highlights, centers, and maps the corresponding node in the other backend's graph via shared `debug_handle` correlation.
  
  ![Cross-Backend Compare](demo_material/cross_backend_compare.png)

* **Pre-Generated Demo Reports:**
  
  | Backend | Model | Nodes | Report | JSON Summary | Log |
  |---|---|---:|---|---|---|
  | xnnpack | `mobilebert` | 2361 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/run.log.txt) |
  | xnnpack | `resnet50` | 550 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/run.log.txt) |
  | xnnpack | `mv2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/run.log.txt) |
  | qualcomm | `swin_v2_t` | 1494 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/run.log.txt) |
  | qualcomm | `mobilenet_v2` | 521 | [HTML Report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) | [Summary JSON](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.summary.json) | [Raw Log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/run.log.txt) |

---

### 4.2 Invocation Surfaces (API Concept)
Observatory supports three unified user-facing invocation surfaces:
1. **CLI Wrappers:** For zero-code-change command-line instrumentation.
2. **Context Managers (`enter_context`):** For phase-scoped, nested configurations.
3. **Pass Decorators (`@observe_pass`):** For zero-effort tracking of graph changes at pass boundaries.

---

### 4.3 Standardized Twin Outputs
Observatory emits two distinct deliverables to support human-facing and machine-facing workflows:
1. **Report HTML (Interactive Dashboard):** A fully self-contained, server-free, interactive dashboard containing the record explorer, `fx_viewer`, overlays, and comparison capabilities.
2. **Archive JSON & Report JSON (Structured Payload):** Machine-readable formats that preserve raw sessions and summarize key findings, regressions, and accuracy deltas for consumption by automated CI gates or LLM triage systems.

## 5. Core Concepts & Public API Shape

To support backend-agnostic orchestration, Observatory introduces a clean conceptual model:

```
+───────────────────────────────────────────────────────────────────+
│                        CONCEPTUAL VOCABULARY                      │
+───────────────────────────────────────────────────────────────────+
│                                                                   │
│   Session: Outermost execution context (lifecycle boundary)       │
│      │                                                            │
│      ├── Region: Labelled nesting scope (e.g., "AOT", "Lowering")  │
│      │                                                            │
│      └── Record: Individual captured artifact (e.g., FX graph)    │
│            │                                                      │
│            └── Digests: Lens-specific serialized states           │
│                                                                   │
│   Archive: Raw persisted captures (JSON)                          │
│                                                                   │
│   Report: Analyzed derived output (HTML / JSON)                   │
│                                                                   │
+───────────────────────────────────────────────────────────────────+
```

### 5.1 Public Vocabulary
*   **Session:** The outermost debugging scope. Standardized lifecycle hooks for active lenses fire only at Session boundaries.
*   **Region:** A named, logical label to group and nest captures in the explorer interface. Regions support configuration nesting and stack inheritance.
*   **Record:** A single collected debugging artifact. Contains a timestamp, name, active region stack, and a map of lens-specific serialized data (Digests).
*   **Archive:** The complete, raw, unanalyzed state of a Session and its Records.
*   **Report:** The derived, analyzed presentation produced by running analytical passes over an Archive.

### 5.2 The Archive-vs-Report Split
Separating raw capture (**Archive**) from analytical presentation (**Report**) is a core design contract:
*   **CI Efficiency:** High-throughput CI pipelines write only the lightweight Archive JSON, skipping expensive HTML rendering.
*   **Late-Bound Analysis:** Archives can be reloaded and analyzed long after the run using different lens configurations, threshold parameters, or regression algorithms without re-running the compiler.
*   **Regression Comparison (`--compare`):** Multiple Archive JSON files from different days or branches can be merged to generate a single comparative regression report.

### 5.3 The Lens Protocol (Extension Model)
A **Lens** is the single extension unit in Observatory. It is a Python class that encapsulates a specific debugging concern. Rather than letting instrumentation code bleed into core compiler scripts, a lens implements public lifecycle hooks:

| Hook Name | Lifecycle Phase | Responsibility |
|:---|:---|:---|
| `on_session_start` | Session Boundary | Installs temporary instrumentation, mocks, or global listeners. |
| `on_session_end` | Session Boundary | Restores original states, ensuring cleanup even on exceptions. |
| `observe` | Collection Point | Filters incoming artifacts and determines relevance to this lens. |
| `digest` | Collection Point | Serializes the relevant artifact state into the Record. |
| `analyze` | Emit / Report Time | Runs post-processing algorithms across all collected records. |
| `html_frontend` | Emit / Report Time | Generates interactive components (tables, CSS, overlays) for HTML. |
| `json_frontend` | Emit / Report Time | Generates structured analysis key-values for Report JSON. |

---

## 6. `fx_viewer` — The Layered Graph Visualizer

To support complex compiler debugging, `fx_viewer` is designed as a standalone, server-free, canvas-based graph visualizer.

### 6.1 Key Requirements
*   **Zero Local Servers:** The viewer runs entirely in-browser. This avoids the networking and port-binding issues of traditional server-backed visualization tools.
*   **Build-Time Layout:** Graph extraction and coordinate layout (Sujiyama routing) are performed at build-time in Python. The HTML report carries pre-computed coordinates, allowing instantaneous canvas painting on load.\n* **Layout Dependency:** Coordinates are pre-computed in Python using `fast-sugiyama` (layout library requiring Python >= 3.11). For older Python environments or environments wishing to avoid layout dependencies, pre-computed layouts can be skipped, falling back to basic rendering or client-side caching.*
*   **Layered Design:** The viewer separates the structural **Base Layer** (nodes, structural edges) from custom **Extension Layers** contributed by lenses (such as accuracy colors, profiling statistics, or quantization bounds).

### 6.2 Python and JS API Boundaries
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

---

## 7. Scope & Roadmap

Observatory’s features are organized into three clear phases:

| Feature Area | Shipped in Draft Branch | Proposed in This RFC | Future Work (Follow-ups) |
|:---|:---:|:---:|:---:|
| **Core Infrastructure** | Python Context Manager, `@observe_pass`, Region Tree View, Core Session Lifecycle | Standardized Archive JSON Reloading, Stable Lens Protocol Hooks | Automated Nightly CI regression templates |
| **Lenses (Debugging Concerns)** | Compile-Time Accuracy, FX Graph Capture, Stack-Trace Provenance, Run Metadata, Pipeline Step Patches | **Report JSON via `json_frontend`** (structured machine summary) | Runtime/Delegated Accuracy, QNN QHAS profiling, XNNProfiler aggregation, QParam Audit |
| **`fx_viewer` (Visuals)** | Pan/Zoom/Minimap, Fuzzy Search, N-Way Node-Selection Sync, Multi-Layer Overlays | Stable Build-Time Python & Run-Time JS Boundaries | Support for non-FX graph formats (TOSA, PyTorch JIT, delegated graphs) |
| **CLI Capabilities** | Backend-specific & generic CLI wrappers | **`--compare` CLI Mode** (Archive-to-Regression report generation) | Live streaming-telemetry dashboard |\n\n*Note: **Report (JSON)** via `json_frontend` and the **`--compare` CLI mode** are already fully implemented and tested inside the accompanying POC branch in `devtools/observatory/` for validation purposes. However, they are presented in this RFC as 'Proposed' to seek active design reviews and establish stable API and schema contracts before they are promoted to stable, production-ready devtools features.*\n

---

## 8. Governance and API Stability

As a shared infrastructure component used by core devtools and various backend teams (Qualcomm, XNNPACK, ARM, etc.), Observatory establishes clear boundaries of ownership and stability:

### 8.1 Ownership Boundaries
*   **Core devtools reviewers** own `devtools/observatory/` core, `devtools/fx_viewer/` core, the Lens Protocol contract, and the generic lenses (graph, metadata, compile-time accuracy).
*   **Backend teams** own their respective backend subdirectories (e.g., `backends/qualcomm/debugger/observatory/` and `backends/xnnpack/debugger/observatory/`), including backend-registered patches and custom backend lenses. No core sign-off is needed for backend-private lenses.

### 8.2 Public Surfaces and Compatibility
To prevent breaking downstream tooling, CI systems, or automated dashboards, four public surfaces are designated as **stable contracts**:
1.  **The Lens Protocol Interface:** Signature of the lifecycle hooks, including context passing and analysis argument shapes.
2.  **`GraphExtension` Python API:** Method names and parameters used to build overlays.
3.  **Archive JSON Schema:** The structured format for raw session/record serializations.
4.  **Report JSON Schema (Proposed):** The structured format for derived analytical results.

Any non-backward-compatible change to these four contracts must follow a staged migration process: announce in advance via issue/RFC, and keep backward-compatibility aliases where feasible.

---

## 9. Open Questions for Reviewers

We are seeking active feedback on the following design decisions, along with concrete initial recommendations to facilitate review:

### Q1 — Where is the line between core and backend ownership, and how does a lens cross it?
**Prompt for reviewers:** Today the rule is binary — generic lenses live in `devtools/observatory/lenses/`, backend-specific lenses live in `backends/<name>/...`. (1) Is a binary split enough, or do we need a recognized *middle tier* for lenses shared by two-or-more backends but not truly universal (e.g., a quantization-accuracy lens used by both XNNPACK and Qualcomm)? (2) When a lens that started backend-specific proves generally useful, what is the *promotion path* — who approves the move, does the import path change, and how do we avoid breaking the originating backend's CLI during the move?
**Trade-off to discuss:** A middle tier reduces duplication but adds an ownership grey zone and a third CODEOWNERS bucket; a strict binary split is simpler to govern but pushes shared logic into copy-paste.
**Starting recommendation to react to:** Keep the binary split for v1; treat "shared-by-two-backends" as a *core* lens that the two backends opt into via their recipe, and define promotion as a normal core-owned PR that (a) moves the file, (b) leaves a one-release import shim, (c) is announced per §8.2's breaking-change policy.

### Q2 — Should lenses carry an explicit stability tier?
**Prompt for reviewers:** External contributors need to know what is safe to depend on. Should each lens (and the Lens protocol itself) declare an **experimental / stable** tier, analogous to `torch.compile`'s stability annotations, so a backend owner can tell whether building on `per_layer_accuracy` today risks a breaking change tomorrow? If yes, at what granularity — per lens, per hook, or per JSON-schema field?
**Trade-off to discuss:** Stability tiers give downstream consumers a real contract and let core evolve experimental lenses freely; they also add annotation overhead and the obligation to actually honor "stable." Without tiers, everything is implicitly experimental, which slows external adoption.
**Starting recommendation to react to:** Annotate at two levels — the **Lens protocol + the two JSON schemas** (Archive, Report) as the stable, change-controlled surface (§8.2 already treats them as such), and individual lenses default to *experimental* until a maintainer promotes them. Mark `graph`, `metadata`, and the Archive schema as the first *stable* set since the demo matrix already depends on them.

### Q3 — What channel announces breaking changes to known backend owners?
**Prompt for reviewers:** §8.2 requires breaking changes to the Lens protocol / `GraphExtension` / the two JSON schemas to be either fixed-in-the-same-PR or announced-and-staged. Is a GitHub **issue label** (`observatory-api-change`) enough discovery, or do we need an active push channel (a tagged GitHub team / mailing list / CODEOWNERS auto-request) so backend owners are *notified* rather than expected to watch a label?
**Trade-off to discuss:** A label is zero-infrastructure but relies on people subscribing; an active channel guarantees reach but needs an owner and a keep-the-list-current process.
**Starting recommendation to react to:** Do both with low cost — require the `observatory-api-change` label *and* a CODEOWNERS entry on the protocol/schema files so any breaking PR auto-requests the core + registered backend teams. Revisit a mailing list only if the backend-owner set grows beyond what CODEOWNERS handles cleanly.

> **Coordinator note:** All three prompts are deliberately phrased to invite a decision, not just opinion — each ends with a concrete recommendation reviewers can accept, amend, or reject. That tends to move RFC threads faster than fully-open questions.

---