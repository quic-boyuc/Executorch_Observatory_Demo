# RFC: Observatory — A Unified Debugging Framework for ExecuTorch


**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers

**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

**Draft PR:** [Github PR](https://github.com/pytorch/executorch/pull/19288)


---

# 1. Introduction

This RFC proposes two new components under `devtools/`:

- **Observatory** — a framework that captures artifacts produced during compilation and turns them into a single interactive report you can share.
- **`fx_viewer`** — a standalone FX-graph renderer that has no dependencies and supports interaction. It exposes a **Python API** (build-time graph extraction, layout, and overlay authoring) and a **JS API** (in-browser canvas, compare-mode sync, runtime layer/theme mutation). Observatory consumes both — Python at build, JS at run; see §4.6 for the two boundaries. `fx_viewer` is also useful on its own outside Observatory.

If you have ever debugged by scattering `print(gm.graph)` across a pass — this RFC is for you.

This RFC is aimed at three kinds of readers.

1. If you are **writing or tuning an AOT pass** — adding a new quantizer, debugging a lowering regression, or diffing the graph across a transform — Observatory captures the graph between transform passes wherever you ask. There are two ways to mark a collection point: wrap your passes with a decorator, or insert manual `Observatory.collect(...)` calls into your own code. The information shown on each recorded graph — accuracy overlays, partition coloring, and so on — is contributed by **Lenses** (Python extensions that implement debugging logic). One investigation can therefore ask several questions at once.

2. If you are **running CI or triaging community bugs**, Observatory gives you a zero-code-change CLI that wraps any existing script — AOT export, on-device inference, or a full end-to-end flow — and emits a single HTML file you can attach to an issue, and the same data as JSON for archival and regression comparison.

3. If you are **a backend owner**, you may have experienced the pain of writing the same per-layer accuracy, graph-dump, and log-collection scripts that every other backend has written in its own way. Observatory is the shared place to contribute once. The mechanism is a **Lens** — a single Python extension that owns one debugging concern end-to-end: *instrument, configure, export, analyze, visualize*. Your backend defines lenses for its specific debugging needs; the framework handles the session, the report, and everything in between. `fx_viewer`, a pure-HTML, server-free graph renderer, is the canvas that graph lenses draw on.

### Document map
- §2 states the problem. 
- §3 shows the tool in action. 
- §4 is the architecture (mechanism, lens protocol, runtime-vs-analyzed split, FX viewer)
- §5 walks through the three invocation surfaces with code. 
- §6 is a worked extensibility example. 
- §7 maps the feature landscape and the roadmap (what's shipped, what's proposed, what's further out). 
- §8 covers review, landing, and maintenance — how the draft PR should merge, how the code should be governed afterward, and the open questions we want reviewer input on.

# 2. The problem

Two small problems compound across backends, artifact types, and teams.

### 2.1 The whole debugging workflow is fragmented
Debugging is a five-stage workflow: **instrument** the run, **configure** it (which lens, which dataset, which threshold), **export** the captured artifacts into something analyzable, **analyze** them (metrics, diffs, cross-record comparisons), and **visualize** the result for a human reader. ExecuTorch's existing devtools cover the **instrument** stage with a uniform interface: `debug_handle` survives into delegated graphs, `ETRecord` / `ETDump` give every ExecuTorch backend (xnnpack, qnn, coreml, vulkan, ...) a runtime capture-and-retrieve container, and `Inspector` reads back regardless of which backend wrote the events. By design, this layer does not try to unify *what* each backend captures — hardware-specific events differ, and they should — it unifies the *API shape* around them, so each backend writes its own per-event schema and parser, and the user gets one read interface. The other four stages have no equivalent — no shared place for a backend writer to plug in configure / export / analyze / visualize logic, and no shared place for a user to drive that logic across backends.

On Qualcomm, `qnn_intermediate_debugger.py` wires activation and partial export into a per-layer accuracy flow — at the cost of significant manual setup per invocation, and with analysis and visualization existing only as terminal prints and hand-written CSVs. Every backend writes the same kind of glue, structured differently: enable-logic, config schema, export format, comparison logic, and rendering all written by hand.

The same fragmentation shows up in the output format: results today exist only as ad-hoc CSVs, printed tables, and screenshots — hard for humans to skim, harder for scripts to process. What's missing is one layer up from the data model: a shared **extension framework** for backend writers (install instrumentation, read live config, serialize, analyze, render), a shared **user surface** so a single CLI / Python entry drives any backend's workflow, and a unified output — structured **JSON** for queries, standalone **HTML** for humans — that serves both from one capture. The aim is to modularize each backend's debugging logic, not unify it; backends and users meet on a common surface.

### 2.2 The graph has no viewer built for the workflow

`torch.fx` is the core IR for ExecuTorch lowering, and the graph at each stage is where most of the interesting debugging happens: *did this op get decomposed, did that sequence get fused, which nodes were dropped from the delegated region?* The closest tool today, `devtools/visualization/`, forwards an `ExportedProgram` to Google's Model-Explorer via a local web server - not embeddable in standalone documents, not sharable in discussion threads.

The deeper problem is that today each debugging concern ends up in its own viewer — there is no shared graph canvas multiple tools can paint on. A graph is the most natural place to attach multiple debugging signals: accuracy as a color gradient, partition assignment as a second overlay, quantization parameters (scale, zero-point) in a node's info panel, profiling numbers on labels. Without a shared viewer that multiple lenses can paint on, each concern ends up in its own dashboard. `fx_viewer` addresses this gap — in-pipeline, embeddable, layered, and reusable outside Observatory. It does so by exposing **two API surfaces**: a **Python API** any AOT pipeline can call to extract a graph, lay it out, and add overlay layers (Observatory uses it from inside its lenses); and a **JS API** any HTML page can call to mount the canvas, switch layers/themes, and drive compare-mode sync (Observatory uses it from its report shell). §4.6 makes those two boundaries explicit.

Observatory and `fx_viewer` together answer both.

# 3. Quick tour — zero-config per-layer accuracy debugging

> **Scope note.** Per-layer accuracy shown here is **compile-time**: the `per_layer_accuracy` lens runs CPU simulation across graph snapshots at different lowering stages and compares against a float anchor. Runtime / delegated-graph accuracy is targeted for a follow-up lens (see §7.3).

https://github.qualcomm.com/user-attachments/assets/fe1b23c3-6586-471a-8c82-b6d2880aa7cb

### Setup
One command in, one HTML file out. Observatory depends on [`fast-sugiyama`](https://github.com/austinorr/fast-sugiyama) for graph layout.


```bash
pip3 install 'fast-sugiyama[full]'   # requires python >= 3.11

python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens-recipe accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

The XNNPACK CLI (`python -m executorch.backends.xnnpack.debugger.observatory`) takes the same shape — wrap any existing script, no code change.


### What you get
A **self-contained HTML file** — no server, no login, no external service. Attach it to an issue, a PR, or an email.

- **Session Dashboard (one per session).** Per-session metadata: command line, environment, input model. Each lens can contribute a section. The `metadata` lens emits run-wide info (CLI command, env, model) and the framework duplicates that block on every Session Dashboard so context is always visible.
- **Records and change summaries (left panel).** One Record per collection point. Records list time-ordered by default; toggle the tree view to group them by `region_stack` (e.g. AOT stages from `pipeline_graph_collector`) into collapsible nodes. Between adjacent Records, a change summary highlights what moved (node-count delta, PSNR change). Click a Record → single view. Click a change summary → 2-record compare. Click *Select* → N-record compare.
- **Interactive FX graph.** Pan, zoom, minimap, fuzzy search. N-way synchronized compare: clicking a node in one graph highlights the matching node in every other graph — sync driven by `debug_handle` / `from_node`.
- **Per-layer accuracy as a color overlay.** With `--lens-recipe accuracy`, per-operator PSNR / cosine / MSE render as a color gradient on the graph. Worst-accuracy operators are visually highlighted; node click shows full metric breakdown.

### Pre-generated reports
One HTML report and one raw run log per model. Node count is the size of the exported float graph (after `torch.export()`, before backend lowering).
 Lenses active in this demo: `metadata`, `stack_trace`, `graph`, `accuracy`, `per_layer_accuracy`, `pipeline_graph_collector`, `graph_color`.

| Backend | Model | Nodes | Report | Log |
|---|---|---:|---|---|
| xnnpack | `mobilebert` | 2361 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/run.log.txt) |
| xnnpack | `ic4` | 1541 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/ic4/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/ic4/run.log.txt) |
| xnnpack | `emformer_transcribe` | 1529 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/emformer_transcribe/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/emformer_transcribe/run.log.txt) |
| xnnpack | `ic3` | 1003 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/ic3/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/ic3/run.log.txt) |
| xnnpack | `dl3` | 638 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/dl3/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/dl3/run.log.txt) |
| xnnpack | `vit` | 584 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/vit/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/vit/run.log.txt) |
| xnnpack | `resnet50` | 550 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet50/run.log.txt) |
| xnnpack | `mv2` | 521 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv2/run.log.txt) |
| xnnpack | `mv3` | 436 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv3/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mv3/run.log.txt) |
| xnnpack | `emformer_join` | 362 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/emformer_join/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/emformer_join/run.log.txt) |
| xnnpack | `resnet18` | 213 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet18/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/resnet18/run.log.txt) |
| xnnpack | `edsr` | 168 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/edsr/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/edsr/run.log.txt) |
| xnnpack | `llama2` | 105 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/llama2/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/llama2/run.log.txt) |
| xnnpack | `w2l` | 51 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/w2l/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/w2l/run.log.txt) |
| xnnpack | `add_mul` | 6 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/add_mul/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/add_mul/run.log.txt) |
| xnnpack | `linear` | 5 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/linear/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/linear/run.log.txt) |
| qualcomm | `inception_v4` | 1541 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v4/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v4/run.log.txt) |
| qualcomm | `swin_v2_t` | 1494 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_v2_t/run.log.txt) |
| qualcomm | `swin_transformer` | 1316 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_transformer/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/swin_transformer/run.log.txt) |
| qualcomm | `cvt` | 1143 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/cvt/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/cvt/run.log.txt) |
| qualcomm | `inception_v3` | 1003 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v3/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/inception_v3/run.log.txt) |
| qualcomm | `eurobert` | 780 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/eurobert/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/eurobert/run.log.txt) |
| qualcomm | `torchvision_vit` | 560 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/torchvision_vit/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/torchvision_vit/run.log.txt) |
| qualcomm | `mobilenet_v2` | 521 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/run.log.txt) |
| qualcomm | `roberta` | 497 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/roberta/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/roberta/run.log.txt) |
| qualcomm | `bert` | 488 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/bert/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/bert/run.log.txt) |
| qualcomm | `mobilenet_v3` | 436 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v3/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v3/run.log.txt) |
| qualcomm | `albert` | 303 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/albert/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/albert/run.log.txt) |
| qualcomm | `distilbert` | 246 | [report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/distilbert/observatory_report.html) | [log](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/distilbert/run.log.txt) |

# 4. Architecture

Observatory's architecture follows from the problems in §2. The shape: a lens is the single extension point, a debugging context scopes the lifecycle, captures persist separately from analysis, and a dependency-free graph viewer embeds into the report. This chapter walks through each of these in turn, with two diagrams that convey most of the design.

### 4.1 The architecture at a glance

**How to read this chapter.** Observatory revolves around one split: *capturing* data during a run is a different job from *reasoning* about it afterward. When a run completes, the framework has accumulated an **Archive** — a flat list of **Records** (one per collection point), grouped into **Sessions** (one per outermost debugging scope). That is the only thing stored raw. At emit time, `analyze` + rendering transforms the Archive into a **Report** — the derived output, in HTML or JSON. The extension unit for all of this is a **Lens**: one Python class that owns one debugging concern end-to-end, from capture to render. **Regions** are lightweight labels that group Records in the UI but do not trigger lens lifecycle hooks.

The diagram below shows the three layers. Read it top-to-bottom:

- **interface layer** — everything user-facing: the ways to start a run, the Lens protocol a lens author implements, and the output artifacts (Report HTML, Archive JSON, Report JSON).
- **core** *(backend-agnostic)* — Session lifecycle, Record bookkeeping, analysis, rendering, and emit.
- **lenses** — the actual debugging work, expressed as Lens implementations: some shipped with the framework, some contributed by each backend.

`fx_viewer` is drawn next to Report Assembly inside the core box. The core consumes it through **two API surfaces** — a Python API at build time (lenses' `analyze` phase calls `FXGraphExporter` and `GraphExtension`; the framework also pulls in fx_viewer's JS runtime bundle here so it ships inside the HTML) and a JS API at run time (Observatory's report shell mounts each graph block via `FXGraphViewer.create` and the compare view via `FXGraphCompare.create`). §4.6 walks through the boundary in detail. fx_viewer has no Observatory dependency in either direction and remains usable standalone via `FXGraphExporter(gm).export_html(...)`.

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  INTERFACE LAYER                                                              ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ ┌─ User interface ─────────┐ ┌─ Lens author ──────┐ ┌─ Artifacts ───────────┐ ║
║ │ generic CLI              │ │ implements a Lens: │ │ Report (HTML)         │ ║
║ │ backend CLI              │ │   on_session_start │ │   self-contained,     │ ║
║ │ `with` block             │ │   on_session_end   │ │   for reviewers       │ ║
║ │   Observatory.           │ │   observe / digest │ │                       │ ║
║ │     enter_context(...)   │ │   analyze          │ │ Archive (JSON)        │ ║
║ │ @observe_pass            │ │   html_frontend    │ │   persist + reload,   │ ║
║ │ Observatory.collect(...) │ │   json_frontend    │ │   CI input            │ ║
║ │                          │ │                    │ │                       │ ║
║ │ reads HTML in browser    │ │ registers at       │ │ Report (JSON)         │ ║
║ │ or consumes JSON from    │ │ CLI-entry time     │ │   LLM triage,         │ ║
║ │ CI / LLM / dashboard     │ │                    │ │   CI, dashboards      │ ║
║ └──────────────────────────┘ └────────────────────┘ └───────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════════════════════╝
         │                              │                             ▲
         │ drives                       │ registers with              │ emits
         ▼                              ▼                             │
╔═══════════════════════════════════════════════════════════════════════════════╗
║  OBSERVATORY CORE           (backend-agnostic)                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║ ┌─ Session manager ───────────┐    ┌─ Record store ────────────────────────┐  ║
║ │ region & config stack       │    │ per-collect fan-out to every lens     │  ║
║ │ Session open/close          │    │ time-ordered records, region_stack    │  ║
║ │ lens registry               │    │ tagged with active session_id         │  ║
║ │ lifecycle hook dispatch     │    └───────────────────────────────────────┘  ║
║ └─────────────────────────────┘                                               ║
║                                                                               ║
║ ┌─ Report assembly ─────────────────────────┐   ┌─ fx_viewer ──────────────┐  ║
║ │ per-lens analyze over the Archive         │   │ Python API (build):      │  ║
║ │ ┌─ GraphHub ────────────────────────┐     │   │  FXGraphExporter         │  ║
║ │ │ base graph from the graph lens    │     │   │  GraphExtension          │  ║
║ │ │ extension layers from each lens's │─────┼──►│  Sugiyama layout         │  ║
║ │ │   analyze phase                   │     │   │  extension relayout      │  ║
║ │ └───────────────────────────────────┘     │   │  + JS bundle in report   │  ║
║ │ per-lens, per-Session Frontend.dashboard  │   │                          │  ║
║ │   (Session Dashboard for each session)    │   │ JS API (run, browser):   │  ║
║ │ per-record views                          │   │  FXGraphViewer.create    │  ║
║ │                                           │   │  FXGraphCompare.create   │  ║
║ └───────────────────────────────────────────┘   └──────────────────────────┘  ║
║                                                                               ║
║ ┌─ Export ──────────────────────────────────────────────────────────────────┐ ║
║ │ Report (HTML)        analyze + render run on every emit                   │ ║
║ │ Archive (JSON)       sessions[] + records[] (no analysis)                 │ ║
║ │ Report (JSON)        analyze + json_frontend run on every emit            │ ║
║ │                                                                           │ ║
║ │ Reload path: Archive (JSON) → analyze → Report (HTML) or Report (JSON)    │ ║
║ └───────────────────────────────────────────────────────────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════════════════════╝
         ▲
         │ registered at CLI-entry; called by Core's session + record + report phases
         │
╔═══════════════════════════════════════════════════════════════════════════════╗
║  LENSES                     (all implement the Lens protocol)                 ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  ┌─ Common lenses ───────────────────────┐  ┌─ Backend-specific lenses ─────┐ ║
║  │ graph                                 │  │ qualcomm/ — QNN debug lenses  │ ║
║  │ metadata                              │  │ xnnpack/  — XNNPACK lenses    │ ║
║  │ accuracy          · per_layer_accuracy│  │ arm/      — ARM lenses        │ ║
║  │ stack_trace                           │  │ …         — registered at     │ ║
║  │ pipeline_graph_collector              │  │             CLI-entry time    │ ║
║  │ graph_color                           │  │                               │ ║
║  │   (shipped with the framework)        │  │                               │ ║
║  └───────────────────────────────────────┘  └───────────────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

### 4.2 The Lens

Different backends care about different moments: one wants the graph just before its partitioner runs, another wants the output of a vendor quantizer, a third wants every device-shell command and its log. If the framework itself knew about those moments, it would become a mixed pile of backend-specific code. So both the *capture* logic and the *render* logic live in the extension unit — a **Lens**. A single lens class owns six hooks, fired in a specific order across a run. A lens's data flows through three stages:

- **During a run** — each `Observatory.collect(...)` call hands an artifact to every registered lens. Each lens decides whether it cares and, if so, serializes its view into the Record. Session hooks run at session start and end, giving a lens a place to install and restore any instrumentation it relies on.
- **End of run → Archive** — the framework has accumulated each lens's per-Record serialized take plus per-Session lifecycle data. That is the only thing persisted raw, written as **Archive (JSON)** for storage, CI ingestion, or reload.
- **At emit time** — each lens runs `analyze` over the full record set and derives insights. Those insights flow to two frontend hooks: `html_frontend` assembles a self-contained HTML file for human reviewers; `json_frontend` assembles a Report (JSON) for LLM triage, CI analytics, and dashboards. §4.4 covers the Archive/Report split in detail.

The diagram below shows the full lifecycle — read it top-to-bottom:

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  A LENS AND WHAT IT TURNS INTO                                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  A lens is one extension unit with six hooks:                                 ║
║                                                                               ║
║     session hooks     run at session start and end — install / restore instrumentation║
║     observe / digest  per Record — filter + serialize the lens's take         ║
║     analyze           per emit — derive insights across the Archive           ║
║     html_frontend     per Session at emit — emit pieces for Report (HTML)     ║
║     json_frontend     per Session at emit — emit pieces for Report (JSON)     ║
║                                                                               ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  RUNTIME  (Session open via outermost enter_context)                    │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │   on_session_start hook      ─► instrumentation installed               │  ║
║  │        │                                                                │  ║
║  │        ▼                                                                │  ║
║  │   for each Observatory.collect(name, artifact):                         │  ║
║  │     each lens: observe → digest  (each lens's own take, serialized      │  ║
║  │                                   into the Record's `digests` map)      │  ║
║  │        │                                                                │  ║
║  │        ▼                                                                │  ║
║  │   on_session_end hook        ─► instrumentation restored                │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                             │                                                 ║
║                             ▼                                                 ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  ARCHIVE  (the only thing persisted raw)                                │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │    sessions[]  +  records[] (each tagged with session_id, region_stack) │  ║
║  │                                                                         │  ║
║  │            emit as  →  Archive (JSON)                                   │  ║
║  │                         persist, reload, CI input                       │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║              │                                                      │         ║
║              │ live in-memory                 reloaded from an      │         ║
║              │                                older Archive (JSON)  │         ║
║              ▼                                                      ▼         ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  ANALYSIS + RENDERING  (runs on every emit)                             │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │    each lens:  analyze(records, sessions, config, *, pair_*)            │  ║
║  │                  → derived insights                                     │  ║
║  │                                                                         │  ║
║  │    each lens, per Session:                                              │  ║
║  │      ├── html_frontend(insights)    → HTML pieces                       │  ║
║  │      │                                 (tables, formatted blocks,       │  ║
║  │      │                                  interactive graphs, custom)     │  ║
║  │      │                                       │                          │  ║
║  │      │                                       ▼                          │  ║
║  │      │                             self-contained Report (HTML)         │  ║
║  │      │                             (one Session Dashboard per session)  │  ║
║  │      │                                                                  │  ║
║  │      └── json_frontend(insights)    → structured analysis pieces        │  ║
║  │                                       (per-record summaries,            │  ║
║  │                                        cross-record findings)           │  ║
║  │                                             │                           │  ║
║  │                                             ▼                           │  ║
║  │                                     Report (JSON)                       │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                                                                               ║
║  Only the Archive is raw. Report (HTML) and Report (JSON) are BOTH derived —  ║
║  each produced by its own frontend hook so the form is native to its          ║
║  consumer: HTML for humans, JSON for LLMs, CI analytics, and dashboards.      ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

Debugging instrumentation never leaks: when the context exits — including on exception — `session_end` fires and unwinds whatever `session_start` installed. §5.4 shows this pattern applied to pipeline patching; §6 applies it to on-device ADB calls.

Backends declare which lenses to enable in a short entry-point script; the framework core knows nothing about any specific lens. §6 walks through a full extension example.

### 4.3 Invocation surfaces

Observatory exposes three invocation surfaces, each matching a different debugging context:

- **CLI** (both generic and backend-specific) — for zero-code-change runs: wrap any existing script (AOT, on-device inference, or end-to-end) and get a full report. Matches QA, CI, and community issue reporting.
- **Python `with`-block** (`Observatory.enter_context(...)`) — for targeted developer debugging: flip the framework on for a scoped block of your own code, passing in custom configs.
- **`@observe_pass` decorator** — for pass-centric debugging: tag any `PassBase` subclass and have its before/after graph captured automatically.

All three enter the same debugging context; the different surfaces only change how that context is opened. A manual entry point (`Observatory.collect(name, artifact)`) is available anywhere inside user code, for moments that aren't at one of the standard pipeline breakpoints. §5 walks through each surface with code recipes.

### 4.4 Vocabulary reference

The five nouns that appear throughout the diagrams and code:

- **Region** — a named scope opened by `enter_context(region_name)`. Regions can nest and label Records in the left-panel tree view. They do **not** trigger lens lifecycle hooks.
- **Session** — the outermost Region. Opens when `enter_context` is called with an empty region stack; closes when that outermost context exits. Lens `on_session_start` / `on_session_end` fire at Session boundaries.
- **Record** — one captured artifact from `Observatory.collect(name, artifact)`. Tagged with the active `session_id` and `region_stack` at collection time.
- **Archive** — one run's complete raw state: all Sessions and Records. The only thing persisted raw; written to a JSON file via `--output-archive`.
- **Report** — the derived output produced from an Archive by running `analyze` + rendering. Available as HTML for humans (`--output-html`) and JSON for CI and LLMs (`--output-report-json`).

The two user-facing entry points:

| Call | What it does |
|---|---|
| `enter_context(region_name, config=None)` | Pushes a Region. If no Region is currently active, also opens a Session and fires `on_session_start`. On exit, pops the Region; if it was the outermost, closes the Session and fires `on_session_end`. |
| `collect(name, artifact)` | Passes the artifact to every registered lens and creates one Record tagged with the active `session_id` and `region_stack`. No-op if no Region is active. |

Lens protocol hooks (`on_session_start`, `on_session_end`, `observe`, `digest`, `analyze`, `html_frontend`, `json_frontend`) are what a Lens implements; covered in §4.2.

**Archive vs. Report — the key split.** An Archive is raw storage; a Report is derived. The same Archive can be re-analyzed with different lens configs. Multiple archives can be combined for cross-run regression:

```bash
# Nightly CI — write just the Archive; HTML not required.
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-archive nightly/${DATE}/mv2.json \
    --lens-recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize

# Later — regression HTML from two archived runs.
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html
```

`--compare` loads both archives, merges their record sets, and exposes `pair_records` / `pair_sessions` to each lens's `analyze`. The AOT compile does not run again.

### 4.5 Regions and Sessions

`enter_context` is the only API for creating Regions and Sessions. The framework derives the session structure from how calls are nested:

- **Outermost call** (region stack empty on entry) → opens a Session and fires `on_session_start`. The Session's name equals the `region_name` passed, or auto-generates `"default"` if omitted.
- **Inner call** (region stack non-empty) → pushes a Region label; no lens hook fires.
- **Call with `config=...` only** (no `region_name`) → pushes a transient config override, no Region added to the tree view.

Each `collect()` call snapshots the live region stack into the Record. The left-panel tree view groups Records by this stack; the default flat view keeps them in collection order.

**Example:**

```python
with Observatory.enter_context("my_pipeline"):    # opens Session
    with Observatory.enter_context("stage_a"):
        Observatory.collect("result_a", gm_a)     # region_stack=["my_pipeline","stage_a"]
    with Observatory.enter_context("stage_b"):
        Observatory.collect("result_b", gm_b)     # region_stack=["my_pipeline","stage_b"]
# on_session_start fired once at entry; on_session_end fires once on exit
```

Left-panel tree view for the run above:

> **[IMAGE PLACEHOLDER — screenshot of the left panel showing the tree view with my_pipeline/stage_a and my_pipeline/stage_b]**

**Lens state lifecycle.** The framework fires `on_session_start` / `on_session_end` only at Session boundaries, not at inner Region boundaries. State that spans multiple Sessions belongs in `Lens.setup()` (called once at registration); state that belongs to one Session goes in the session hooks. `on_session_end` is guaranteed to fire even if an exception is raised inside the context.

**Cross-archive compare.** `--compare` prefixes Session IDs with the archive label (`A:my_pipeline`, `B:my_pipeline`); Record names stay un-prefixed. Lenses receive `pair_records` and `pair_sessions` in `analyze` to diff matching Records across runs.

### 4.6 The FX viewer

The report is a single HTML file, so the graph viewer must run entirely in the browser — no server, no separate tab. A single report can carry dozens of graphs with thousands of nodes each; dynamic layout in the browser would be slow, and one DOM element per node would be slow. So we do the expensive work at build time: extract graph structure, compute exact `(x, y)` + edge routing with **Sugiyama layout** (via `fast-sugiyama`), embed everything as JSON in the HTML. At view time the JavaScript paints straight to a `<canvas>`. A typical multi-graph HTML report stays around 1 MB.

#### Two API boundaries — where Observatory meets fx_viewer

`fx_viewer` and Observatory are deliberately separate components meeting at exactly two API surfaces — one in Python at build time, one in JavaScript at run time. Every Observatory ↔ fx_viewer interaction goes through one of these two:

- **Build-time, Python API.** Observatory's lenses and core import directly from `executorch.devtools.fx_viewer`. The `graph` lens calls `FXGraphExporter(gm)` to extract and lay out each Record's base graph; any other lens (`graph_color`, `per_layer_accuracy`, future ones) authors overlay layers via `GraphExtension` + `ColorRule` and contributes them through `GraphLayerContribution`. At emit time the framework calls `FXGraphExporter.relayout_payload_base(...)` to incorporate node-set changes from extensions, and `FXGraphExporter._load_viewer_js_bundle()` to embed the JS runtime. The output is a single payload (base + extensions) plus the JS bundle, both baked into `report.html`.
- **Run-time, JS API.** When the HTML loads, Observatory's report shell (`templates/js/03_blocks.js`, `04_actions.js`) mounts one viewer per Record graph block via `FXGraphViewer.create({payload, mount, layout, state})` and the compare view via `FXGraphCompare.create({viewers, layout, sync})`. The shell drives layer / colorBy / theme toggles and selection-sync through the JS API; `fx_viewer` owns the canvas, pan/zoom, minimap, search, and the node-match logic (debug-handle set intersection) used in compare mode.

```
   How Observatory talks to fx_viewer — two API boundaries

   BUILD TIME (Python API)
   ┌─ Observatory ───────────────┐  calls  ┌─ fx_viewer Python API ──────┐
   │ graph / graph_color /       │ ──────► │ FXGraphExporter             │
   │ per_layer_accuracy lenses   │         │ GraphExtension / ColorRule  │
   │ Observatory core (emit)     │         │ relayout_payload_base       │
   └──────────────┬──────────────┘         │ _load_viewer_js_bundle      │
                  │                        └──────────────┬──────────────┘
                  │ assembles + writes                    │ produces
                  ▼                                       ▼
        ┌──────────────────── report.html ────────────────────┐
        │   embedded payload (base + extension layers)        │
        │   embedded fx_viewer JS runtime bundle              │
        │   embedded Observatory report shell JS              │
        └──────────────────────────┬──────────────────────────┘
                                   │ opened in browser
                                   ▼
   RUN TIME (JS API, all in browser)
   ┌─ Observatory report shell ──┐  calls  ┌─ fx_viewer JS API ──────────┐
   │ 03_blocks.js                │ ──────► │ FXGraphViewer.create({...}) │
   │   (mount viewer per Record  │         │ FXGraphCompare.create({...})│
   │    graph block)             │         │ setLayers / setColorBy /    │
   │ 04_actions.js               │         │  setTheme / selection sync  │
   │   (theme + selection sync)  │         │  / runtime layer mutation   │
   └─────────────────────────────┘         └─────────────────────────────┘
```

The diagram above answers *who calls what*. The diagram below shows *what `fx_viewer` itself does* at each phase — same Python-then-JS split, zoomed in on `fx_viewer`'s side.

```
 BUILD TIME (Python API)             Observatory lenses (analyze)
 FX GraphModule                            │
        │                                  └─► extension layers
        ├─► extract structure                  (color, labels, sync keys)
        └─► Sugiyama layout (x, y + edges)
                     │                         │
                     └────────────┬────────────┘
                                  ▼
                       [single JSON payload] ──► embedded in report.html

 RUN TIME (JS API)
 report.html (any browser)
        └─► Canvas JS runtime
               ├── pan / zoom / minimap / fuzzy search
               ├── layer toggle (base + N extensions)
               ├── info panel (merged per-node data)
               └── compare mode (N-way sync via sync keys)
```

Each graph carries a **base layer** (nodes, edges, default coloring) plus any number of **extension layers** — additional layers contributed by lenses: per-node data, coloring rules, labels, tooltips. Users toggle layers in the viewer UI. For compare mode, extension layers can declare a **sync key** so cross-graph highlighting pairs nodes correctly even after fusion or decomposition has renamed them.

`fx_viewer` is not tied to Observatory — any developer with a `torch.fx` graph can drop it into a self-contained HTML file directly via `FXGraphExporter(gm).export_html(...)`.

### 4.7 Boundaries

Observatory is not a replacement for `Inspector`, `ETRecord`/`ETDump` — it *consumes* those primitives through lenses. The shipped report is an artifact produced after the run; a live-dashboard variant built on the same `fx_viewer` foundation is a natural follow-up (§7.3).

# 5. Using Observatory

§4.2 listed the three invocation surfaces. This section walks through each one with a concrete code recipe, and closes with a summary of where collection points come from.

### 5.1 CLI — for QA, CI, and community issue reporting

```bash
# Generic (framework lenses only)
python -m executorch.devtools.observatory \
    --output-html run.html \
    your_script.py --your-args

# Backend-specific with opt-in lens recipe
python -m executorch.backends.xnnpack.debugger.observatory \
    --lens-recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

**Use this when** filing a bug report, reproducing a CI failure, or handing work across teams. Zero code change, single artifact.

### 5.2 Python context manager — for targeted developer debugging

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

**Use this when** iterating on a compiler pass with a custom dataset or custom lens config. Any instrumentation the active lenses installed at `on_session_start` is automatically unwound at the end of the `with`-block — even if the code inside raises.

**Pass a `region_name` for a labelled region; omit it for a transient config override.** `enter_context(region_name, config=...)` pushes a Region the tree-view will show as a labelled group. `enter_context(config=...)` *without* a `region_name` is a config-only override — pushed onto the config stack, popped on exit, no Region added to the tree. Use the second form when you only want to retune lens config for a phase without adding visual noise to the left panel.

**Nested contexts — scoping config changes to a phase.** A compile-and-deploy script often moves through phases with different debugging needs. Nested `enter_context` calls let you scope config changes to a block — when the inner `with` exits, the outer config resumes automatically.

```python
with Observatory.enter_context("preprocess", config={"per_layer_accuracy": {"enabled": False}}):
    Observatory.collect("preprocessed", gm)
    with Observatory.enter_context(config={"per_layer_accuracy": {"enabled": True}}):
        Observatory.collect("after_transform", my_transform(gm))
    # per_layer_accuracy is off again here
```

§6 shows a full end-to-end example applying this pattern to on-device phases.

### 5.3 `@observe_pass` decorator — for pass-centric debugging

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.pass_manager import PassManager

@observe_pass
class MyPass(ExportPass):
    def call(self, gm): ...

pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enter_context("pipeline"):
    pm._transform(graph_module)
```

**Use this when** building or tuning a pass pipeline and you want every pass's before/after captured automatically. The decorator wraps each pass invocation in `Observatory.enter_context(<pass_name>)` so each pass shows up as its own Region in the tree view — `pipeline/MyPass`, `pipeline/RemoveGraphAssertsPass`, etc. All under one Session, so lens hooks fire exactly once.

### 5.4 Where collection points come from

Three mechanisms produce collection points; all three flow into the same `collect(name, artifact)` path:

- **Wrapper patches installed by lenses on `on_session_start`** — the default `pipeline_graph_collector` lens, for example, wraps `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, and `ETRecord.add_*` in `enter_context(<stage>)` blocks that forward the call *and* hand the returned object to `collect()`. The patches are removed in `on_session_end`, so the patched functions are only different while the Session is open.
- **`@observe_pass` decorator** — tag any `PassBase` subclass or instance. The decorator wraps each pass call in its own Region and collects the graph before and after the pass fires.
- **Manual `Observatory.collect(name, artifact)`** — available anywhere in user code, for moments that aren't at one of the above breakpoints.

The `pipeline_graph_collector` lens shows this in practice. At `on_session_start` it installs patches on `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, and `ETRecord.add_*`. Each patch wraps its call in a nested `enter_context` region and forwards the captured artifact to `collect()`. All patches are removed in `on_session_end`.

```python
# What each installed patch looks like — simplified:
def patched_prepare_pt2e(model, *args, **kwargs):
    with Observatory.enter_context("prepare_pt2e"):
        result = original(model, *args, **kwargs)
        Observatory.collect("Annotated Model", result)
        return result

# The session hooks install and restore these patches:
def on_session_start(cls, ctx):
    cls._install_patches()    # replaces prepare_pt2e, convert_pt2e, etc.

def on_session_end(cls, ctx):
    cls._restore_patches()    # restores originals — guaranteed even on exception
```

The resulting left-panel tree for a typical AOT run looks like this:

> **[IMAGE PLACEHOLDER — screenshot of the left-panel tree view showing the quantization and edge regions with their nested collection points]**

Lens hooks still fire exactly once per CLI invocation despite the rich region structure — `on_session_start` once at the Session boundary, `on_session_end` once on exit. The region structure comes entirely from the lens's patches; the user's script runs unchanged. §6 applies the same session-hook pattern to on-device ADB calls.


# 6. Extending with custom lenses

**`collect()` is type-agnostic; lenses filter their own input.** The signature is `collect(name: str, artifact: Any)` — no type constraint on the artifact. A graph lens receives a `GraphModule`, a log lens receives a `LogEntry`, a profiling lens receives a timing snapshot. Each lens `isinstance()`-checks inside `observe()` and returns `None` when it doesn't care. Graph, log, and profiling lenses coexist in the same session without knowing about each other.

That is the full extension surface. A new lens decides what it captures, how it filters, how it serializes, how it analyzes, and how it renders. Below is a concrete example: an ADB-log lens that captures device-side log output (`logcat` and `dmesg`) from every on-device inference, without touching Observatory core and without any other lens knowing it exists. The lens follows the framework's standard split: session hooks install always-on instrumentation; per-call filtering happens in `observe()` based on the current config.

```python
from dataclasses import dataclass
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.interfaces import Lens, ObservationContext
from executorch.backends.qualcomm.export_utils import SimpleADB

@dataclass
class AdbLogEntry:
    source: str        # one of "logcat", "dmesg"
    cmd_label: str     # which on-device command produced this entry
    content: str

def _adb_shell(adb: SimpleADB, shell_cmd: str) -> str:
    """Run `adb shell <cmd>` via SimpleADB and return captured stdout."""
    captured = []
    adb._adb(["shell", shell_cmd],
             output_callback=lambda r: captured.append(r.stdout))
    return "".join(captured)

class AdbLogLens(Lens):
    _original = None

    @classmethod
    def get_name(cls) -> str:
        return "adb_log"

    @classmethod
    def on_session_start(cls, context: ObservationContext) -> None:
        # Always-on capture: every SimpleADB.execute call also fetches
        # logcat + dmesg. Per-call filtering happens in observe() below.
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
        SimpleADB.execute = cls._original
        cls._original = None

    @classmethod
    def observe(cls, artifact, context: ObservationContext):
        if not isinstance(artifact, AdbLogEntry):
            return None
        # context.config reflects the CURRENT (possibly nested) config stack.
        # Reading here — not in on_session_start — is what makes nested
        # enter_context work: each call to observe() sees the live config.
        cfg = context.config.get("adb_log", {})
        if not cfg.get("enabled", True):
            return None
        if artifact.source not in cfg.get("sources", ["logcat"]):
            return None                              # filtered out for this phase
        return {"source": artifact.source,
                "cmd":    artifact.cmd_label,
                "lines":  artifact.content.splitlines()}
```

With `AdbLogLens` registered, every on-device inference produces log captures automatically. The `graph`, `accuracy`, and `metadata` lenses see the `AdbLogEntry` too and all return `None`.

**Why config is read in `observe`, not in `on_session_start`.** Session hooks fire once, at the boundary of the outermost debugging context. If the lens snapshotted config in `on_session_start`, it would lock in whatever was set on the outer `with` block — and any nested `enter_context` override would silently have no effect. By reading `context.config` inside `observe` instead, the lens always sees the current top-of-stack config and per-phase overrides work as written. `logcat` is what the user-space inference process said; `dmesg` covers kernel and driver events (NPU/HTP faults, OOM-killer activity, hardware exceptions) that never reach `logcat` — both are fetched every call, but `observe` only keeps the streams the active config asks for.

**Nested contexts scope configuration per phase.** Lens config is stacked — each `enter_context(config=...)` merges and pops on exit. The pattern shines when a session runs several device commands but only some of them deserve a heavy log dump. Below: a probe and a smoke test only need `logcat`, while the inference we actually want to analyze gets both `logcat` and `dmesg`. Two kinds of keys appear: `enabled` is a per-lens convention checked inside each lens's `observe`, and lens-specific keys like `sources` are read by the lens itself.

```python
with Observatory.enter_context(config={
    "accuracy": {"evaluator": my_evaluator},
    "adb_log":  {"sources": ["logcat"]},          # lightweight default
}):
    gm = compile_and_lower(model)
    Observatory.collect("edge", gm)

    # Routine device calls — only need logcat to confirm they ran cleanly.
    run_on_device(probe_cmd)                      # capability probe
    run_on_device(smoke_cmd)                      # quick smoke test

    # The inference we actually want to debug — broaden capture for this
    # phase so we also keep dmesg (kernel/driver events).
    with Observatory.enter_context(config={
        "accuracy": {"enabled": False},           # skip expensive accuracy work
        "adb_log":  {"sources": ["logcat", "dmesg"]},
    }):
        device_result = run_on_device(target_cmd)
        Observatory.collect("post_device", device_result)

    # Outer config back in effect: any further calls only keep logcat.
    run_on_device(teardown_cmd)

Observatory.export_html_report("run.html")
```

Any artifact flows through `collect`; lenses pick what they care about; instrumentation attaches/detaches with the context; config nesting shapes which lenses run in which phase.

# 7. Feature landscape and roadmap

Observatory composes with existing ExecuTorch devtools — `Inspector`, `ETRecord` / `ETDump`, `bundled_program`, and `devtools/visualization/` keep doing what they do; Observatory consumes their output through lenses and unifies what every backend used to script by hand. This section maps debugging workflows onto three tiers: shipped on the draft branch, proposed in this RFC, and follow-ups for after this RFC merges.

**Draft branch:** [Github PR](https://github.com/pytorch/executorch/pull/19288)

### 7.1 Shipped in the draft branch today

Pull the draft branch, install dependencies (§3), run the CLI — you get the following by default.

- **Compile-time accuracy** — per-operator PSNR / cosine / MSE across lowering stages; replaces per-backend `print` + CSV diffs. Lenses: `accuracy`, `per_layer_accuracy`.
- **Graph-state collection at pipeline points** — the graph at each standard stage (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_*`); replaces `print(gm.graph)` and per-backend log dumps. Lens: `pipeline_graph_collector` + `graph`. Each stage shows up as a Region under a coarse `edge` Region in the tree view (§4.5).
- **Pass diff** — before/after Records around any decorated pass; replaces text diff and manual side-by-side. Mechanism: `@observe_pass` + `graph` compare mode.
- **Collection provenance** — user-code call stack at each collection point, in the HTML viewer's info panel; replaces manual log annotation. Lens: `stack_trace`.
- **Interactive FX graph view** — pan, zoom, minimap, fuzzy search, N-way compare with cross-graph sync; embedded in the HTML, no server. Component: `fx_viewer`.
- **Run-metadata block on every Session Dashboard** — command line, environment, input model, lens-contributed sections; replaces hand-written README attachments. Lens: `metadata`.
- **Region tree-view toggle on the left panel** — Records render flat (time-ordered) by default; toggling tree view groups them by `region_stack` into collapsible nodes (e.g. `edge/prepare_pt2e/`, `edge/etrecord/exported_program/`). The toggle is purely visual — record ordering is preserved.
- **Context sharing** — one Report (HTML) + one Archive (JSON) per run, attach-and-go; replaces zips of logs, CSVs, and screenshots.
- **CLI flag rename** — `--lens-recipe` (dash) replaces `--lens_recipe` (underscore). `--output-json` is removed and replaced by `--output-archive` (the Archive — records + sessions, no analysis) and `--output-report-json` (the Report (JSON) — analyzed; §7.2). New `--session-name <NAME>` overrides the script-derived Session name. No deprecation alias — this is the initial RFC and PR. The Qualcomm and XNNPACK CLIs accept multi-select recipes (`--lens-recipe accuracy --lens-recipe adb` or `--lens-recipe accuracy,adb`).
- **Qualcomm ADB lens** (`--lens-recipe adb`) — captures on-device `SimpleADB` activity (push, execute, pull) and surfaces it in the report without any code change to user scripts. Adds three sections: a **Device Info** dashboard block (serial, host, soc model, htp arch, workspace, build path); a compact **Transfer Summary** (one row per push/pull group with file count, bytes, duration, status); and a **left-panel record per inference call** (`adb.execute #N`) showing the full `qnn_executor_runner` command with one-click copy, a scrollable monospace stdout log with error-line highlighting, and collapsible `logcat -d` / `adb shell dmesg` panels (default on for inference, config-gated). Commit: `ac88080805` (`backends/qualcomm/debugger/observatory/lenses/adb.py`, `adb_patches.py`, `tests/`). Verified with 13 unit tests and end-to-end on SM8850.

### 7.2 Proposed in this RFC, not yet implemented in the draft branch

Two extensions to the Lens protocol / CLI that are part of this RFC's design but not yet implemented in the draft branch. The tag *(not yet implemented)* marks them throughout the doc — they should be reviewed alongside the rest of the RFC.

- **Report (JSON) via `json_frontend`** *(not yet implemented; §4.4)* — a second frontend hook on the Lens protocol that emits structured analysis pieces alongside the HTML pieces, plus an emit path that writes the assembled payload as JSON. Most impactful extension for LLM triage, CI analytics, and dashboards.
- **`--compare` CLI mode** *(not yet implemented; §4.4–4.5)* — a CLI subcommand that takes two or more archived runs and emits a regression Report (HTML) or Report (JSON) by running comparison-aware lenses over the combined record set. The framework prefixes session IDs with archive labels and exposes `pair_records` / `pair_sessions` to `Lens.analyze`.

### 7.3 Further directions (follow-ups beyond this RFC)

Follow-up work after this RFC merges. None of these are part of what this RFC asks reviewers to approve — we list them so reviewers can flag what's most valuable to pursue next.

- **Runtime / delegated-graph accuracy lens** — port `qnn_intermediate_debugger.py` into a lens that uses `debug_handle` + `Inspector` to compare CPU against on-device execution; replaces the current per-backend manual scripts. Most-requested follow-up.
- **Backend tool ports into lenses** — one lens each for QNN QHAS profiling, XNNProfiler aggregation, QParam audit, delegation info (color layer), `.pte` diff (over archived runs), size analysis.
- **Runtime lenses on `Inspector` + `ETDump`** — performance, memory, crash-analysis lenses fed by existing runtime-capture primitives.
- **Device-side profiling lens** *(implemented — see §7.1 ADB lens)* — `AdbLens` (`--lens-recipe adb`) covers ADB log capture (stdout, logcat, dmesg) around on-device inference on the session-hook pattern described in §5.4 and §6. Perf-trace support (optrace / QHAS) is a further follow-up.
- **Non-FX graph formats in `fx_viewer`** — PyTorch graph, QNN graph, TOSA as first-class exporters.
- **Nightly-regression CI recipe** — package the archived-Archive + `--compare` flow as a reusable CI template.
- **Live debugging dashboard** — `fx_viewer` as foundation for streaming-event dashboards beyond after-the-fact reports.

---

The shared mechanism behind all of this is small: a Lens protocol with six hooks plus a per-backend registration point. Every workflow above is one or more lenses; a new backend gets CLI, report shape, compare mode, graph view, and Archive output without extra work.

# 8. Review, landing, and maintenance

This section covers two meta-level questions about the draft: how to land it, and how to maintain it.

### 8.1 Review and merge strategy

The draft PR linked in §7 is intentionally monolithic so reviewers can read the RFC alongside running code. For *design review*, that's the right unit. The question is what happens after design review concludes.

We see two reasonable ways to merge. We recommend **Option B**; reviewer capacity should drive the decision.

**Option A — Land as one PR.** Merge the draft PR as-is. Works if a small reviewer group can handle the full diff in one pass; the risk is that review stays broad but shallow, and the change either lands as a whole or has to be reverted as a whole.

**Option B — Three-PR stack** *(our recommendation)*. Three focused PRs in dependency order:

1. **`devtools/fx_viewer/`** — standalone; usable on its own via `FXGraphExporter(gm).export_html(...)`.
2. **`devtools/observatory/`** — core framework, seven common lenses, generic CLI. Depends on PR 1.
3. **Backend CLIs** — Qualcomm + XNNPACK together, each with end-to-end model-matrix validation. Depends on PR 2.

Each PR is focused enough for one reviewer to approve; `fx_viewer` can be adopted by anyone not using Observatory.

### 8.2 Maintenance and collaboration

Observatory and `fx_viewer` introduce shared infrastructure multiple teams will build on. The ownership rules below keep boundaries clean.

**Ownership.** Mirrors the directory structure:

- **Core devtools reviewers** own `devtools/observatory/` core, `devtools/fx_viewer/` core, and the generic lenses in `devtools/observatory/lenses/`.
- **Backend teams** own `backends/<name>/debugger/observatory/cli.py`, backend-registered patches, and backend-specific lenses. No core sign-off needed.
- **Cross-cutting changes** (Lens protocol — including `analyze` and `Frontend.dashboard` signatures and the `pair_records` / `pair_sessions` kw-only args added in §4.5; `GraphExtension` API; JS runtime; the two JSON schemas described below) need core sign-off regardless of directory.

**Testing.** Follows ownership: infra tests (`devtools/observatory/tests/`) are owned by core; backend-specific tests are owned by backend teams. CI invariant: every backend CLI runs a smoke test on a representative model.

**Two JSON schemas** — both are public surfaces downstream consumers depend on: **Archive (JSON)** (`--output-archive`, raw records + sessions, no analysis; consumed by CI and `--compare`) and **Report (JSON)** (`--output-report-json`, analyzed output for LLM triage and dashboards; §7.2, not yet implemented).

**Non-backward-compatible API changes.** The Lens protocol, `GraphExtension`, the Archive (JSON) schema, and the Report (JSON) schema are the surfaces most likely to break downstream consumers. A PR that breaks them must either:

1. **Fix every caller in the same PR** — preferred when the impact is small and limited to this repo.
2. **Announce in advance and stage the migration** — preferred when the change affects backend lenses or archived JSON consumers; announcement via issue or RFC update; landing only after migration PRs are ready.

### 8.3 Open questions

Items below are genuinely undecided. We welcome opinions in the draft PR thread or as comments on this RFC.

1. **Core vs backend ownership boundary.** Is "generic lens lives in `devtools/`, backend-specific lens lives in `backends/`" sufficient, or do we need a middle tier (e.g., shared-across-two-backends)? How should a lens that starts backend-specific and becomes generic migrate?
2. **Lens API stability signal.** Should lenses declare an experimental/stable tier so external contributors know what's safe to depend on, similar to `torch.compile`'s stability annotations?
3. **Breaking-change communication channel.** Is an issue label (`observatory-api-change`) sufficient, or do we need a notification channel (mailing list, tagged GitHub team) to reach known backend owners?