# RFC: Observatory — A Unified Debugging Framework for ExecuTorch


**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers

**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

**Draft PR:** [Github PR](https://github.com/pytorch/executorch/pull/19288)


---

# 1. Introduction

This RFC proposes two new components under `devtools/`:

- **Observatory** — a framework that captures artifacts produced during compilation and turns them into a single structured, interactive, shareable report.
- **`fx_viewer`** — a standalone FX-graph renderer that has no dependencies and supports interaction. It powers Observatory's graph view and is useful on its own.

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

Two frictions, each small on its own, compound across backends, artifact types, and teams.

### 2.1 The whole debugging workflow is fragmented
Debugging is a five-stage workflow: **instrument** the run, **configure** it (which lens, which dataset, which threshold), **export** the captured artifacts into something analyzable, **analyze** them (metrics, diffs, cross-record comparisons), and **visualize** the result for a human reader. ExecuTorch's existing devtools cover the **instrument** stage with a uniform interface: `debug_handle` survives into delegated graphs, `ETRecord` / `ETDump` give every ExecuTorch backend (xnnpack, qnn, coreml, vulkan, ...) a runtime capture-and-retrieve container, and `Inspector` reads back regardless of which backend wrote the events. By design, this layer does not try to unify *what* each backend captures — hardware-specific events differ, and they should — it unifies the *API shape* around them, so each backend writes its own per-event schema and parser, and the user gets one read interface. The other four stages have no equivalent — no shared place for a backend writer to plug in configure / export / analyze / visualize logic, and no shared place for a user to drive that logic across backends.

On Qualcomm, `qnn_intermediate_debugger.py` wires activation and partial export into a per-layer accuracy flow — at the cost of significant manual setup per invocation, and with analysis and visualization existing only as terminal prints and hand-written CSVs. Every backend writes the same kind of glue, structured differently: enable-logic, config schema, export format, comparison logic, and rendering all rolled by hand.

The same fragmentation shows up in the output format: results today exist only as ad-hoc CSVs, printed tables, and screenshots — hard for humans to skim, harder for scripts to process. What's missing is one layer up from the data model: a shared **extension framework** for backend writers (install instrumentation, read live config, serialize, analyze, render), a shared **user surface** so a single CLI / Python entry drives any backend's workflow, and a unified output — structured **JSON** for queries, standalone **HTML** for humans — that serves both from one capture. The aim is to modularize each backend's debugging logic, not unify it; backends and users meet on a common surface.

### 2.2 The graph has no viewer built for the workflow

`torch.fx` is the core IR for ExecuTorch lowering, and the graph at each stage is where most of the interesting debugging happens: *did this op get decomposed, did that sequence get fused, which nodes were dropped from the delegated region?* The closest tool today, `devtools/visualization/`, forwards an `ExportedProgram` to Google's Model-Explorer via a local web server - not embeddable in standalone documents, not sharable in discussion threads.

The deeper problem is composition with debugging information. A graph is the natural visual anchor for many debugging concerns at once: accuracy as a color gradient, partition assignment as a second overlay, QParams in a node's info panel, profiling numbers on labels. Without a shared viewer that multiple lenses can paint on, each concern ends up in its own dashboard. `fx_viewer` addresses this gap — in-pipeline, embeddable, layered, and reusable outside Observatory, with Python API (export time customization) and JS API (frontend interaction).

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

### 4.1 Three layers at a glance

Observatory has three layers. The **interface layer** covers everything user-facing: the surfaces someone uses to drive a run, the surface a lens author implements, and the artifacts that come out at the end. The backend-agnostic **core** handles the mechanics: Session lifecycle, Record bookkeeping, analysis and rendering, and emitting the outputs. The **lens implementations** do the actual debugging work — some shipped with the framework, some contributed by each backend. `fx_viewer` sits adjacent to Report Assembly: the Core depends on it for graph layout, but `fx_viewer` is a separate module anyone can use on its own.

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
║ │ per-lens analyze over the Archive         │   │ (leveraged external      │  ║
║ │ per-lens, per-Session Frontend.dashboard  │   │  module)                 │  ║
║ │   (Session Dashboard for each session)    │   │                          │  ║
║ │ per-record views                          │   │ FX graph extraction      │  ║
║ │                                           │   │ Sugiyama layout          │  ║
║ │ ┌─ GraphHub ────────────────────────┐     │   │ extension relayout       │  ║
║ │ │ base graph from the graph lens    │     │   │ canvas JS runtime bundle │  ║
║ │ │ extension layers from each lens's │─────┼──►│                          │  ║
║ │ │   analyze phase                   │     │   │                          │  ║
║ │ └───────────────────────────────────┘     │   └──────────────────────────┘  ║
║ └───────────────────────────────────────────┘                                 ║
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

Reading the diagram top-to-bottom. The **Interface Layer** holds everything a human interacts with. It contains three pieces:

- **a user interface** for driving a run and for reading its output (HTML in a browser, or JSON consumed by CI, an LLM triage agent, or a dashboard);
- **a lens author surface** — the small Lens protocol a framework or backend developer implements to teach Observatory about a new debugging concern;
- **three artifacts** coming out: Report (HTML), Archive (JSON), and Report (JSON).

The three invocation surfaces and direct API are covered in §5.

The **Observatory Core** is the backend-agnostic engine that drives the lifecycle. A session manager owns the debugging context and dispatches lifecycle hooks. A record store broadcasts each `collect` call to every registered lens and keeps each lens's take. Report assembly runs each lens's `analyze` over the full record set, then splits into rendering: the HTML path assembles view pieces into one self-contained file, and the JSON path assembles a structured payload. Inside Report Assembly, the GraphHub merges the base graph (captured by the `graph` lens) with extension layers contributed by any lens's analyze phase, then hands the combined payload to `fx_viewer` for layout and relayout.

**Lenses** at the bottom are the protocol implementations. The framework ships seven common lenses; each backend contributes its own. From the Core's perspective they are the same kind of object — only their shipping location differs.

### 4.2 Interface layer — invocation surfaces

The Interface Layer is where a run starts. Observatory exposes three invocation surfaces, each matching a different debugging context:

- **CLI** (both generic and backend-specific) — for zero-code-change runs: wrap any existing script (AOT, on-device inference, or end-to-end) and get a full report. Matches QA, CI, and community issue reporting.
- **Python `with`-block** (`Observatory.enter_context(...)`) — for targeted developer debugging: flip the framework on for a scoped block of your own code, passing in custom configs.
- **`@observe_pass` decorator** — for pass-centric debugging: tag any `PassBase` subclass and have its before/after graph captured automatically.

All three enter the same debugging context; the different surfaces only change how that context is opened. A manual entry point (`Observatory.collect(name, artifact)`) is available anywhere inside user code, for moments that aren't at one of the standard pipeline breakpoints. §5 walks through each surface with code recipes.

### 4.3 The Lens

Different backends care about different moments: one wants the graph just before its partitioner runs, another wants the output of a vendor quantizer, a third wants every device-shell command and its log. If the framework itself knew about those moments, it would become a mixed pile of backend-specific code. So both the *capture* logic and the *render* logic live in the extension unit — a **Lens**. A single lens class owns six hooks, fired in a specific order across a run. The diagram below walks the whole life of a lens's data, from collection into the Archive to the rendered Report.

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  A LENS AND WHAT IT TURNS INTO                                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  A lens is one extension unit with six hooks:                                 ║
║                                                                               ║
║     session hooks     bracket each Session — install / restore instrumentation║
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
╚═══════════════════════════════════════════════════════════════════════════════╝
```

A single picture, read top-to-bottom.

**During a run**, each `Observatory.collect(...)` call hands an artifact to every registered lens. Each lens decides whether it cares and, if so, turns its view into a serialized piece. Session hooks bracket each Session, giving a lens a place to install and restore any instrumentation it relies on.

**At the end of the run**, the framework has accumulated one thing — an Archive: each lens's per-Record serialized take, plus per-Session lifecycle data. That is the only thing we ever persist raw. It can be written out as **Archive (JSON)** for storage, CI ingestion, or reload later.

**At emit time**, each lens runs `analyze` over the full record set and derives whatever insights it wants — per-record metrics, per-session summaries, graph overlays. It then projects those insights through two frontend hooks. `html_frontend` emits pieces that the HTML renderer assembles into a self-contained file for human reviewers. `json_frontend` emits structured pieces that assemble into a Report (JSON) for LLM triage agents, CI analytics jobs, or dashboards. §4.4 explains why this split is essential to the whole architecture.

The six hooks are bound to a scoped Python context. When the context exits — including on exception — every lens's `session_end` fires and unwinds whatever `session_start` installed. Debugging instrumentation never leaks past its intended scope. §5.2 shows how contexts are opened and nested in code; §5.4 walks through the session-hook pattern applied to a concrete pipeline-patching example.

Backends declare which lenses to enable in a short entry-point script; the framework core knows nothing about any specific lens. §6 walks through a full extension example.

### 4.4 Vocabulary: the Archive and the Report

Capturing data during a run is one job. Reasoning about it — computing metrics, diffing across records, summarizing findings — is a different job. Observatory separates them explicitly: runtime accumulates an Archive (what each lens saw), and emit-time runs `analyze` + rendering over the Archive to produce a Report. The vocabulary below names the five things that show up in every diagram and code path. The runtime-vs-analyzed split is laid out below; the Region/Session structure within an Archive has its own subsection in §4.5.

- **Region** — a *lightweight* named scope opened by `with Observatory.enter_context(region_name, config=None):`. Regions can nest. Records produced inside a Region are tagged with that Region's name in their `region_stack`. **Regions do not trigger lens lifecycle hooks** — they are pure labeling for grouping records in the UI.
- **Session** — the *heavyweight* scope. A Session begins when an **outermost** `enter_context` is entered (no Region currently on the stack) and ends when that outermost `enter_context` exits. Lens `on_session_start` / `on_session_end` fire at Session boundaries. The Session's `name` equals the outermost Region's `region_name`.
- **Record** — one item from `Observatory.collect(name, artifact)`. Carries `name`, `timestamp`, `session_id`, `region_stack: List[str]` (snapshot at collect time), and lens-specific `digests`. Records are stored in collection order.
- **Archive** — one Observatory invocation's full state: a flat list of one or more Sessions plus every Record produced under them. Each record's `session_id` and `region_stack` say where it belongs. An archive is the only thing Observatory persists raw; analysis and rendering are derived. Serializes to a single JSON file via `--output-archive`.
- **Report** — the derived output. `analyze` runs once per archive over all records (with `sessions` metadata, plus `pair_records` / `pair_sessions` in compare mode); rendering produces **Report (HTML)** for human reviewers (`--output-html`) and **Report (JSON)** for LLM triage / CI / dashboards (`--output-report-json`). Each Report is structured per Session — one **Session Dashboard** per session.

The verbs the protocol defines:

| Verb | Where it fires | What it does |
|---|---|---|
| `enter_context(region_name, config=None)` | User code or CLI wrapper | Pushes a Region. If outermost (region stack was empty), opens a Session and fires `on_session_start`. On exit, pops the Region; if it was outermost, closes the Session and fires `on_session_end`. |
| `collect(name, artifact)` | User code or instrumented call site | Hands the artifact to every active lens; produces one Record tagged with the active `session_id` and a snapshot of `region_stack`. No-op if no Region is active. |
| `observe` | Per-record, per-lens | Lens decides whether the artifact is one it cares about. |
| `digest` | Per-record, per-lens | Lens serializes its take into the Record. |
| `on_session_start` | Per Session boundary, per-lens | Lens initializes session-scoped state. Fires only at outermost-region boundaries. |
| `on_session_end` | Per Session boundary, per-lens | Lens finalizes session-scoped state. Guaranteed even on exception. |
| `analyze` | At emit time, per-lens, **once per archive** | Lens derives insights from the full record set; receives `sessions` and (in compare mode) `pair_records` / `pair_sessions`. |
| `Frontend.dashboard` | At emit time, per-lens, **once per session** | Lens renders that session's Session Dashboard ViewList. |
| `setup` | Once at lens registration | Lens initializes archive-scoped state (datasets, float-model refs). |
| `clear` | At `Observatory.clear()` between archive runs | Lens resets cross-archive state. |

Because `analyze(records, sessions, cfg)` takes the full record set with no opinion on where the records came from, the same analyze function that compared adjacent records within one archive can compare records from multiple archives. Cross-time regression is that idea made concrete: combine two archives' records into one set, run analyze over the union, and each lens sees the two runs as neighboring records it already knows how to diff.

```
  archive X ─► sessions X.s1, X.s2 ─► records x1, x2, x3   ┐
  archive Y ─► sessions Y.s1       ─► records y1, y2       │
  archive Z ─► sessions Z.s1, Z.s2 ─► records z1, z2, z3   ├─► analyze(records, sessions, cfg
  …                                                        │       *, pair_records, pair_sessions)
                                                           ┘     one pass — every record in every
                                                                 archive is visible to every lens
                                                                            │
                                                                            ▼
                                                                  ┌─────────┴─────────┐
                                                                  ▼                   ▼
                                                            html_frontend       json_frontend
                                                                  │                   │
                                                                  ▼                   ▼
                                                            Report (HTML)       Report (JSON)
                                                            (reviewers)         (LLMs, CI, dashboards)
```

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

The `--compare` path loads both archives, prefixes session IDs with archive labels (record names stay un-prefixed), exposes `pair_records` / `pair_sessions` to each lens's `analyze`, and renders one Report. The only thing that doesn't run again is the AOT compile.

The same separation is what lets Observatory emit multiple output forms from one Archive. `html_frontend` renders the analyzed result for human reviewers; `json_frontend` emits the Report (JSON) for LLM triage agents, CI analytics, and dashboards. Both are derived by running analyze + frontend over the records; neither modifies the Archive. New output forms (a terminal renderer, a chat-ops payload, or whatever comes next) fit in the same way, without disturbing runtime or persistence.

An Archive is the single source of truth for its run. Analysis and rendering are derived — repeatable, retargetable, and composable over the same data.

### 4.5 Regions and Sessions

§4.4 named the four data-model nouns (Session, Record, Archive, Report) plus Region. This subsection explains how Regions and Sessions compose at runtime — the structure that determines which Records land where, when lens lifecycle hooks fire, and how the left panel groups things in the Report.

#### What you can express

```
  ARCHIVE  (one Observatory invocation, one JSON file)
  └── Session "aot_compiler"               ← outermost region's name == session name
      ├── Session Dashboard (lens contributions for this session)
      └── Records (time-ordered list)
          r1   region_stack = [aot_compiler, preprocess]
          r2   region_stack = [aot_compiler, quantize, prepare]
          r3   region_stack = [aot_compiler, quantize, convert]
          r4   region_stack = [aot_compiler, lower]

  Left-panel default (flat, time-ordered):
        Session "aot_compiler"
          - Session Dashboard
          - r1   r2   r3   r4

  Left-panel tree-view toggle (grouped by region_stack):
        Session "aot_compiler"
          - Session Dashboard
          - preprocess/        · r1
          - quantize/
              · prepare/       · r2
              · convert/       · r3
          - lower/             · r4

  --compare across archives:
        ╔═══ Archive A ═══╗   Session "aot_compiler"   records (un-prefixed names) …
        ╔═══ Archive B ═══╗   Session "aot_compiler"   records (un-prefixed names) …
```

A user — whether a developer running the CLI, a backend writing patches, or a script invoking Observatory directly — works only with `enter_context`. The Region/Session split is what the framework derives from those calls.

#### `enter_context` — one API, two flavors of nesting

```python
@contextmanager
def Observatory.enter_context(region_name: Optional[str] = None,
                              config: Optional[Dict] = None):
    """Push a Region onto the runtime stack. If outermost (region stack empty
    on entry), open a Session and fire on_session_start. On exit, pop the
    Region; close the Session and fire on_session_end if it was the outermost."""
```

Both arguments are optional, and the *outermost-vs-inner* distinction at call time decides what the call does:

- **Outermost** (region stack is empty when entering): if `region_name` is omitted, the framework auto-generates a non-duplicating default (`"default"`, `"default-2"`, …). The Region is pushed and a Session opens with that name.
- **Inner** (region stack is non-empty when entering): if `region_name` is omitted, the call is a **config-only override** — the config frame is pushed but no Region is added to the stack and no Session boundary fires. This recovers the §5.2 nested-config-override pattern without adding visual noise to the tree view.
- **Both** flavors accept `config=...` to override per-lens configuration for the duration of the block.

So: pass `region_name` when you want a labelled Region in the tree view; omit it (and pass only `config=...`) for a transient config override.

#### Algorithm at `collect()`

```python
def active_session_at_collect():
    # Walk runtime stack innermost → outermost; the innermost Region's
    # outermost ancestor is the active Session.
    if not _region_stack:
        return None        # No Region active → collect() is a no-op
    return _region_stack[0]   # outermost == Session (by R2)
```

Each `collect()` call snapshots the live `region_stack` into the Record and tags it with the active `session_id`. Records are appended to the Archive in collection order — that is the order the left panel uses by default. The tree-view toggle uses `region_stack` to group them, but does not reorder them.

#### Worked examples

**Outermost without name** (zero-code-change script):
```python
with Observatory.enter_context():                 # auto-opens Session "default"
    Observatory.collect("foo", gm)                 # session_id="default", region_stack=["default"]
```

**Inner without name** (config-only override — replaces the old §5.2 pattern):
```python
with Observatory.enter_context("aot"):
    Observatory.collect("a", gm)                   # region_stack=["aot"]
    with Observatory.enter_context(config={"per_layer_accuracy": {"enabled": True}}):
        # No region_name → no Region pushed; pure config override.
        Observatory.collect("b", gm)               # region_stack=["aot"]   (unchanged)
    Observatory.collect("c", gm)                   # region_stack=["aot"]
# Tree: aot/ { a, b, c }   (b's per-lens config differs but it's not a separate Region)
```

**Sibling outermost without names** (rare; produces auto-named sibling sessions):
```python
with Observatory.enter_context():                 # Session "default"
    Observatory.collect("a", gm)
with Observatory.enter_context():                 # Session "default-2"
    Observatory.collect("b", gm)
# Archive: 2 sessions, "default" and "default-2".
```

**Nested labelled regions** (typical AOT-stage tree, demoed by `pipeline_graph_collector`):
```python
with Observatory.enter_context("edge"):           # outermost → Session "edge"
    with Observatory.enter_context("prepare_pt2e"):
        Observatory.collect("prepare_pt2e", gm)   # region_stack=["edge","prepare_pt2e"]
    with Observatory.enter_context("convert_pt2e"):
        Observatory.collect("convert_pt2e", gm)
    with Observatory.enter_context("to_edge_transform_and_lower"):
        Observatory.collect("to_edge_transform_and_lower", ep)
    with Observatory.enter_context("etrecord"):
        with Observatory.enter_context("exported_program"):
            Observatory.collect("etrecord/exported_program", ep)
        with Observatory.enter_context("edge_dialect_program"):
            Observatory.collect("etrecord/edge_dialect_program", ep)
```

Lens hooks for this whole pipeline fire **exactly once each** — `on_session_start` at the outer `enter_context("edge")`, `on_session_end` when it exits. Inner Regions are pure labels.

#### Lens-controlled state lifecycle

The framework fires `on_session_start` / `on_session_end` only at Session boundaries (outermost regions). It does **not** auto-reset lens state. The lens decides what's session-scoped vs archive-scoped vs cross-archive:

- **Archive-scoped state** (datasets, float-model references, vendor handles) — set in `Lens.setup()` (called once at lens registration). Untouched in session hooks. Survives across all sessions in the archive.
- **Session-scoped state** (accumulators, monkey-patches, per-session metrics) — install in `on_session_start`, finalize in `on_session_end`.
- **Cross-archive state** — reset in `Lens.clear()` at `Observatory.clear()` between archive runs (relevant in long-running processes).

The framework guarantees `on_session_end` fires for every successful `on_session_start`, including on exception inside the `enter_context` block, so monkey-patch installation/restoration is exception-safe.

#### CLI strategy

The CLI wraps the user's script in **exactly one** `with Observatory.enter_context(<script-derived-name>):` block. That is the outermost Region for the run, so it is also the Session.

- Inside the wrapper: every user `enter_context(...)` is a **Region**, never a new Session, because the Region stack is non-empty when the user script runs.
- Lens hooks fire **once per CLI invocation** — patches install at the start, restore at the end. No churn from labelled phases.
- `--session-name <NAME>` overrides the script-derived name.

For zero-code-change scripts: the script never calls `enter_context`. The CLI's wrapper still opens a Session, and the `pipeline_graph_collector` lens's monkey-patches do the collecting — Records carry `region_stack=[<session-name>, <stage>, ...]`.

For users running a script directly without the CLI: each outermost `enter_context(...)` in the script is its own Session. Sibling outermost contexts produce multiple Sessions in one Archive — each gets its own Session Dashboard and its own pair of `on_session_start`/`on_session_end` hooks.

#### Cross-archive `--compare`

When the framework loads N archives for `--compare`:

- Session IDs are prefixed with the archive label (`A:aot_compiler`, `B:aot_compiler`). **Record names stay un-prefixed.**
- The framework computes, keyed by un-prefixed name:
  - `pair_sessions[name] = [(archive_label, Session), ...]`
  - `pair_records[name] = [(archive_label, RecordDigest), ...]`
- `Lens.analyze(records, sessions, config, *, pair_records=None, pair_sessions=None)` receives the union of records + sessions plus the pair maps. Lenses that don't care about pairing ignore the kw-only args.
- The UI renders the archive label as a section break (`Archive A — nightly_2026-04-20`) above each archive's Sessions. Record names render un-prefixed; only Session-section titles carry the archive label.

A lens that wants per-stage drift (for example, accuracy regression between the same `prepare_pt2e` Record in archive A and archive B) opts into `pair_records` with one line; the framework hands it the matched pair.

### 4.6 The FX viewer

The report is a single HTML file, so the graph viewer must run entirely in the browser — no server, no separate tab. A single report can carry dozens of graphs with thousands of nodes each; dynamic layout in the browser would be slow, and one DOM element per node would be slow. So we do the expensive work at build time: extract graph structure, compute exact `(x, y)` + edge routing with **Sugiyama layout** (via `fast-sugiyama`), embed everything as JSON in the HTML. At view time the JavaScript paints straight to a `<canvas>`. A typical multi-graph HTML report stays around 1 MB.

```
 BUILD TIME                         Observatory lenses (analyze)
 FX GraphModule                            │
        │                                  └─► extension layers
        ├─► extract structure                  (color, labels, sync keys)
        └─► Sugiyama layout (x, y + edges)
                     │                         │
                     └────────────┬────────────┘
                                  ▼
                       [single JSON payload] ──► embedded in report.html

 RUN TIME
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

**Nested contexts — scoping config changes to a phase.** A compile-and-deploy script often moves through phases with very different debugging needs: a cheap preprocess step, an expensive quantization step, a device-inference step. Nested `enter_context` calls let you express those per-phase overrides as block-scoped code instead of manually turning lenses on and off in code. When an inner `with` exits, its config is popped and the outer config resumes automatically — no cleanup code on your part, no state leaking between phases.

```python
with Observatory.enter_context("preprocess", config={"per_layer_accuracy": {"enabled": False}}):
    gm = preprocess(model)
    Observatory.collect("preprocessed", gm)

    # Inside this phase only, turn on the expensive lens with a heavy dataset.
    # No region_name on the inner call — pure config override; tree view still
    # shows records under "preprocess", but per_layer_accuracy uses heavy_repro_set here.
    with Observatory.enter_context(
        config={"per_layer_accuracy": {"enabled": True, "dataset": heavy_repro_set}}
    ):
        gm = my_heavy_transform(gm)
        Observatory.collect("after_heavy", gm)

    # Outer config is back in effect here: per_layer_accuracy is off again.
    gm = postprocess(gm)
    Observatory.collect("final", gm)
```

The essence of the mechanism is **temporal scoping of debugging config**: each nested block is a scope inside which some subset of lens configuration is overridden, and the override lifetime is exactly the lifetime of the Python scope. That is the entire programming model — but it has proven enough to express every per-phase lens adjustment we have needed so far.

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

Here is what the wrapper pattern actually looks like inside a lens. The `pipeline_graph_collector` lens opens one coarse `edge` Region for the whole AOT pipeline at `on_session_start`, wraps each patched function in an inner per-call Region, and lazily opens a nested `etrecord` Region the first time `ETRecord.add_*` fires:

```python
import contextlib

class PipelineGraphCollector(Lens):
    _originals = {}
    _edge_stack = None
    _etrecord_stack = None

    @classmethod
    def on_session_start(cls, ctx):
        # Open the coarse "edge" region for the whole AOT pipeline.
        cls._edge_stack = contextlib.ExitStack()
        cls._edge_stack.enter_context(Observatory.enter_context("edge"))
        cls._install_patches()

    @classmethod
    def on_session_end(cls, ctx):
        cls._restore_patches()
        if cls._etrecord_stack is not None:
            cls._etrecord_stack.close()
            cls._etrecord_stack = None
        if cls._edge_stack is not None:
            cls._edge_stack.close()
            cls._edge_stack = None

    @classmethod
    def _ensure_etrecord_region(cls):
        if cls._etrecord_stack is None:
            cls._etrecord_stack = contextlib.ExitStack()
            cls._etrecord_stack.enter_context(Observatory.enter_context("etrecord"))

    @classmethod
    def _install_patches(cls):
        import torch.ao.quantization as q
        cls._originals["prepare_pt2e"] = q.prepare_pt2e

        def patched_prepare(model, quantizer, *a, **kw):
            with Observatory.enter_context("prepare_pt2e"):
                gm = cls._originals["prepare_pt2e"](model, quantizer, *a, **kw)
                Observatory.collect("prepare_pt2e", gm)
                return gm

        q.prepare_pt2e = patched_prepare
        # … same pattern for convert_pt2e, to_edge_transform_and_lower
        # … ETRecord.add_* patches additionally call _ensure_etrecord_region()
        #   so they nest under "etrecord" inside "edge"

    @classmethod
    def _restore_patches(cls):
        import torch.ao.quantization as q
        q.prepare_pt2e = cls._originals["prepare_pt2e"]
        # … restore the rest.
```

Resulting tree under CLI:

```
Session "<script-name>"
└── edge/
    ├── prepare_pt2e/      └── record  prepare_pt2e
    ├── convert_pt2e/      └── record  convert_pt2e
    ├── to_edge_transform_and_lower/  └── record
    └── etrecord/                              ← lazy
        ├── exported_program/      └── record
        └── edge_dialect_program/  └── record
```

Lens hooks fire **exactly once** per CLI invocation despite the rich Region structure — `on_session_start` once at the outer Session boundary, `on_session_end` once when it exits. Per-call Regions auto-pop with their `with` block; the coarse `edge` and `etrecord` Regions are managed via `contextlib.ExitStack` because they span multiple function calls.

The shape is the same for any kind of instrumentation a lens wants to install: log-stream taps, device-shell hooks, profiler starts. Anything installed on `on_session_start` is removed on `on_session_end` — including on exception — so the user's baseline environment is restored after every Session closes. §6 applies this exact pattern to on-device ADB calls.

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

**Two JSON schemas.** Observatory persists or emits two distinct JSON shapes; both are part of the public surface area downstream consumers depend on:

- **Archive (JSON)** — written by `--output-archive`. Carries `sessions[]` (each Session with `id`, `name`, `start_ts`, `end_ts`, `start_data`, `end_data`) and `records[]` (each Record with `name`, `timestamp`, `session_id`, `region_stack`, and the per-lens `digests` map). Records are stored in collection order. No analysis is included. This is the format CI consumes for nightly storage and that `--compare` reloads.
- **Report (JSON)** — written by `--output-report-json` (§7.2, not yet implemented). Carries the analysis output produced by each lens's `analyze` plus the per-Session `Frontend.dashboard` output. Intended for LLM triage, CI analytics jobs, and dashboards.

**Non-backward-compatible API changes.** The Lens protocol, `GraphExtension`, the Archive (JSON) schema, and the Report (JSON) schema are the surfaces most likely to break downstream consumers. A PR that breaks them must either:

1. **Fix every caller in the same PR** — preferred when the impact is small and limited to this repo.
2. **Announce in advance and stage the migration** — preferred when the change affects backend lenses or archived JSON consumers; announcement via issue or RFC update; landing only after migration PRs are ready.

### 8.3 Open questions

Items below are genuinely undecided. We welcome opinions in the draft PR thread or as comments on this RFC.

1. **Core vs backend ownership boundary.** Is "generic lens lives in `devtools/`, backend-specific lens lives in `backends/`" sufficient, or do we need a middle tier (e.g., shared-across-two-backends)? How should a lens that starts backend-specific and becomes generic migrate?
2. **Lens API stability signal.** Should lenses declare an experimental/stable tier so external contributors know what's safe to depend on, similar to `torch.compile`'s stability annotations?
3. **Breaking-change communication channel.** Is an issue label (`observatory-api-change`) sufficient, or do we need a notification channel (mailing list, tagged GitHub team) to reach known backend owners?