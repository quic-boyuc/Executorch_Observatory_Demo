# RFC: Observatory — A Unified Debugging Framework for ExecuTorch

**Status:** Draft for review

**Authors:** Qualcomm Innovation Center, Inc.

**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers

**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

**Draft PR:** [PR link]  · **Live demo:** [Demo index link]

---

## 1. Introduction

This RFC proposes two new components under `devtools/`:

- **Observatory** — a framework that captures artifacts produced during compilation and turns them into a single structured, interactive, shareable report.
- **`fx_viewer`** — a standalone, dependency-free, interactive FX-graph renderer that powers Observatory's graph view and is useful on its own.

If you have ever debugged by sprinkling `print(gm.graph)` across a pass — this RFC is for you.

This RFC is aimed at three kinds of reader.

If you are **writing or tuning a compile pass** — adding a new quantizer, debugging a lowering regression, diffing the graph across a transform — Observatory captures the graph between transform passes wherever you ask: wrap your passes with a decorator, or drop manual breakpoints into your own code. What lands on each captured graph — accuracy overlays, partition coloring, node provenance, whatever else matters — is contributed by **Lenses** (Python extensions that implement debugging logic), so one investigation can ask several questions at once.

If you are **running CI or triaging community bugs**, Observatory gives you a zero-code-change CLI that wraps any existing script — AOT export, on-device inference, or a full end-to-end flow — and emits a single HTML file you can attach to an issue, and the same data as JSON for archival and regression comparison.

If you are **a backend owner** and you have felt the friction of writing the same per-layer accuracy, graph-dump, and log-collection scripts that every other backend has written in its own way, Observatory is the shared place to contribute once. The mechanism is a **Lens** — a single Python extension that owns one debugging concern end-to-end: *instrument, configure, export, analyze, visualize*. Your backend defines lenses for different debugging needs; the framework handles the session, the report, and everything in between. `fx_viewer`, a pure-HTML server-free graph renderer, is the visual anchor graph-producing lenses paint on.

**Document map.** §2 states the problem. §3 shows the tool in action. §4 is the architecture (mechanism, lens protocol, runtime-vs-analyzed split, FX viewer). §5 walks through the three invocation surfaces with code. §6 is a worked extensibility example. §7 maps the feature landscape and the roadmap (what's shipped, what's proposed, what's further out). §8 covers review, landing, and maintenance — how the draft PR should merge, how the code should be governed afterward, and the open questions we want reviewer input on.

## 2. The problem

Two frictions, each small on its own, compound across backends, artifact types, and teams.

### 2.1 The whole debugging workflow is fragmented
Debugging is a five-stage workflow: **instrument** the run, **configure** it (which lens, which dataset, which threshold), **export** the captured artifacts into something analyzable, **analyze** them (metrics, diffs, cross-record comparisons), and **visualize** the result for a human reader. ExecuTorch already ships the primitives for the first stage — `debug_handle` survives into delegated graphs, `Inspector` consumes it, `ETRecord` / `ETDump` capture AOT and runtime events. The other four stages are where every backend rebuilds its own wheels.

On Qualcomm, `qnn_intermediate_debugger.py` wires activation and partial export into a per-layer accuracy flow — at the cost of significant manual setup per invocation, and with analysis and visualization living in terminal prints and hand-rolled CSVs. Every backend writes enable-logic, config, export format, comparison logic, and rendering differently.

This fragmentation is worst for artifact types that lack a shared anchor. Graphs are the *easy* case — every backend speaks `GraphModule`, so graph-level debugging has a common data structure to build around. Beyond that — edge-device logs, runtime profiling traces, partition assignments, on-device snapshots — there is no common anchor, so each backend invents its own data model, export format, and analysis.

The fragmentation extends to the output format itself. Debugging results today live in ad-hoc CSVs, printed tables, and screenshots — hard for humans to skim, harder for scripts to process. A unified format would serve both kinds of consumer from one capture: structured **JSON** for querying and programmatic processing, and a standalone **HTML** file for human reading and analysis.

### 2.2 The graph has no viewer built for the workflow

`torch.fx` is the core IR for ExecuTorch lowering, and the graph at each stage is where most of the interesting debugging happens: *did this op get decomposed, did that sequence get fused, which nodes fell out of the delegated region?* The closest tool today, `devtools/visualization/`, forwards an `ExportedProgram` to Google's Model-Explorer via a local web server - not embeddable in standalone documents, not sharable in discussion threads.

The deeper problem is composition with debugging information. A graph is the natural visual anchor for many debugging concerns at once: accuracy as a color gradient, partition assignment as a second overlay, QParams in a node's info panel, profiling numbers on labels. Without a shared viewer that multiple lenses can paint on, each concern ends up in its own dashboard. `fx_viewer` closes this gap — in-pipeline, embeddable, layered, and reusable outside Observatory, with Python API (export time customization) and JS API (frontend interaction).

Observatory and `fx_viewer` together answer both.

## 3. Quick tour — zero-config per-layer accuracy debugging

One command in, one HTML file out.

> **Scope note.** Per-layer accuracy shown here is **compile-time**: the `per_layer_accuracy` lens runs CPU simulation across graph snapshots at different lowering stages and compares against a float anchor. Runtime / delegated-graph accuracy is targeted for a follow-up lens (see §7.2).

```bash
pip3 install 'fast-sugiyama[full]'   # requires python >= 3.11

python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

The XNNPACK CLI (`python -m executorch.backends.xnnpack.debugger.observatory`) takes the same shape — wrap any existing script, no code change.


### What you get

A **self-contained HTML file** — no server, no login, no external service. Attach it to an issue, a PR, or an email.

- **Run dashboard (landing page).** Per-run metadata: command line, environment, input model. Each lens can contribute a section.
- **Captures and change summaries (left panel).** One captured item per collection point (think: breakpoint). Between adjacent captures, a change summary highlights what moved (node-count delta, PSNR change). Click a capture → single view. Click a change summary → 2-capture compare. Click *Select* → N-capture compare.
- **Interactive FX graph.** Pan, zoom, minimap, fuzzy search. N-way synchronized compare: clicking a node in one graph highlights the matching node in every other graph — sync driven by `debug_handle` / `from_node`.
- **Per-layer accuracy as a color overlay.** With `--lens_recipe=accuracy`, per-operator PSNR / cosine / MSE render as a color gradient on the graph. Worst-accuracy operators stand out visually; node click shows full metric breakdown. These numbers are computed by the lens's analyze function at render time, not baked into the capture itself.

[![YOUTUBE THUMBNAIL](https://i9.ytimg.com/vi_webp/NQuj-2LvhAc/mq3.webp?sqp=CNi4_c8G-oaymwEmCMACELQB8quKqQMa8AEB-AH-CYAC0AWKAgwIABABGGUgWChVMA8=&rs=AOn4CLBDJA-8PKvpKJQyD0x0g2yFXyXQ8Q)](https://youtu.be/NQuj-2LvhAc)

Pre-generated reports for a matrix of models are linked from the demo index. Lenses active in this demo: `metadata`, `stack_trace`, `graph`, `accuracy`, `per_layer_accuracy`, `pipeline_graph_collector`, `graph_color`.



## 4. Architecture

Observatory's architecture falls out of the problems in §2. The shape: a lens is the single extension point, a debugging context scopes the lifecycle, captures persist separately from analysis, and a dependency-free graph viewer embeds into the report. This chapter walks through each of these in turn, with two diagrams that carry most of the story.

### 4.1 Three layers at a glance

Observatory has three bands. An **interface layer** covers everything user-facing — the surfaces someone uses to drive a run, the surface a lens author implements, and the reports and JSON files that come out at the end. A backend-agnostic **core** handles the mechanics: session lifecycle, capture bookkeeping, analysis and rendering, and emitting the outputs. A set of **lens implementations** does the actual debugging work — some shipped with the framework, some contributed by each backend. `fx_viewer` sits adjacent to Report Assembly: the Core leans on it for graph layout, but it is a separate module anyone can use on its own.

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  INTERFACE LAYER                                                              ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║ ┌─ User interface ─────────┐ ┌─ Lens author ──────┐ ┌─ Artifacts ───────────┐ ║
║ │ generic CLI              │ │ implements a Lens: │ │ HTML Report           │ ║
║ │ backend CLI              │ │   session hooks    │ │  self-contained,      │ ║
║ │ `with` block             │ │   observe / digest │ │  for reviewers        │ ║
║ │   Observatory.enable_    │ │   analyze          │ │                       │ ║
║ │   context(...)           │ │   html_frontend    │ │ Raw Capture (JSON)    │ ║
║ │ @observe_pass            │ │   json_frontend    │ │  archive + reload,    │ ║
║ │ Observatory.collect(...) │ │                    │ │  CI input             │ ║
║ │                          │ │ registers at       │ │                       │ ║
║ │ reads HTML in browser    │ │ CLI-entry time     │ │ Analyzed Report       │ ║
║ │ or consumes JSON from    │ │                    │ │  (JSON)               │ ║
║ │ CI / LLM / dashboard     │ │                    │ │  LLM triage,          │ ║
║ │                          │ │                    │ │  CI, dashboards       │ ║
║ └──────────────────────────┘ └────────────────────┘ └───────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════════════════════╝
         │                              │                             ▲
         │ drives                       │ registers with              │ emits
         ▼                              ▼                             │
╔═══════════════════════════════════════════════════════════════════════════════╗
║  OBSERVATORY CORE           (backend-agnostic)                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║ ┌─ Session manager ───────────┐    ┌─ Capture store ───────────────────────┐  ║
║ │ debugging context scope     │    │ per-collect fan-out to every lens     │  ║
║ │ nested config stack         │    │ per-lens captures, keyed by name      │  ║
║ │ lens registry               │    │ handles colliding names               │  ║
║ │ lifecycle hook dispatch     │    └───────────────────────────────────────┘  ║
║ └─────────────────────────────┘                                               ║
║                                                                               ║
║ ┌─ Report assembly ─────────────────────────┐   ┌─ fx_viewer ──────────────┐  ║
║ │ per-lens analyze over the full capture    │   │ (leveraged external      │  ║
║ │   set                                     │   │  module)                 │  ║
║ │ per-lens rendering (dashboards and        │   │                          │  ║
║ │   per-capture views)                      │   │ FX graph extraction      │  ║
║ │                                           │   │ Sugiyama layout          │  ║
║ │ ┌─ GraphHub ────────────────────────┐     │   │ extension relayout       │  ║
║ │ │ base graph from the graph lens    │     │   │ canvas JS runtime bundle │  ║
║ │ │ overlay layers from each lens's   │─────┼──►│                          │  ║
║ │ │   analyze phase                   │     │   │                          │  ║
║ │ └───────────────────────────────────┘     │   └──────────────────────────┘  ║
║ └───────────────────────────────────────────┘                                 ║
║                                                                               ║
║ ┌─ Export ──────────────────────────────────────────────────────────────────┐ ║
║ │ HTML Report              analyze + render run on every emit               │ ║
║ │ Raw Capture (JSON)       lens captures + session context (no analysis)    │ ║
║ │ Analyzed Report (JSON)   analyze + JSON render run on every emit          │ ║
║ │                                                                           │ ║
║ │ Reload path: Raw Capture → analyze → HTML or Analyzed Report              │ ║
║ └───────────────────────────────────────────────────────────────────────────┘ ║
╚═══════════════════════════════════════════════════════════════════════════════╝
         ▲
         │ registered at CLI-entry; called by Core's session + capture + report phases
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

Reading the diagram top-to-bottom. The **Interface Layer** is where every human touch-point lives: a user interface for driving a run and for reading its output (HTML in a browser, or JSON consumed by CI, an LLM triage agent, or a dashboard); a lens author surface — the small Lens protocol a framework or backend developer implements to teach Observatory about a new debugging concern; and three artifacts coming out — HTML Report, Raw Capture (JSON), and Analyzed Report (JSON). The three invocation surfaces and direct API are covered in §5.

The **Observatory Core** is the backend-agnostic engine that drives the lifecycle. A session manager owns the debugging context and dispatches lifecycle hooks. A capture store fans each `collect` call out across every registered lens and keeps each lens's take. Report assembly runs each lens's `analyze` over the full capture set, then branches into rendering: the HTML path assembles view pieces into one self-contained file; the JSON path assembles a structured payload. Inside Report Assembly, the GraphHub merges the base graph captured by the `graph` lens with overlay layers contributed by any lens's analyze phase, then hands the combined payload to `fx_viewer` for layout and relayout.

**Lenses** at the bottom are the protocol implementations. The framework ships seven common lenses; each backend contributes its own. From the Core's perspective they are the same kind of object — only their shipping location differs.

### 4.2 Interface layer — invocation surfaces

The Interface Layer is where a run starts. Observatory exposes three invocation surfaces, each matching a different debugging context:

- **CLI** (both generic and backend-specific) — for zero-code-change runs: wrap any existing script (AOT, on-device inference, or end-to-end) and get a full report. Matches QA, CI, and community issue reporting.
- **Python `with`-block** (`Observatory.enable_context(...)`) — for targeted developer debugging: flip the framework on for a scoped block of your own code, passing in custom configs.
- **`@observe_pass` decorator** — for pass-centric debugging: tag any `PassBase` subclass and have its before/after graph captured automatically.

All three enter the same debugging context; the different surfaces only change how that context is opened. A manual entry point (`Observatory.collect(name, artifact)`) is available anywhere inside user code, for moments that aren't at one of the standard pipeline breakpoints. §5 walks through each surface with code recipes.

### 4.3 The Lens

Different backends care about different moments: one wants the graph just before its partitioner runs, another wants the output of a vendor quantizer, a third wants every device-shell command and its log. If the framework itself knew about those moments, it would become a grab-bag of backend-specific code. So both the *capture* logic and the *render* logic live in the extension unit — a **Lens**. A single lens class owns six hooks, fired in a specific order across a run. The diagram below walks the whole life of a lens's data, from capture to report.

```
╔═══════════════════════════════════════════════════════════════════════════════╗
║  A LENS AND WHAT IT TURNS INTO                                                ║
╠═══════════════════════════════════════════════════════════════════════════════╣
║                                                                               ║
║  A lens is one extension unit with six hooks:                                 ║
║                                                                               ║
║     session hooks     bracket the run — install / restore instrumentation     ║
║     observe / digest  per capture — filter + serialize the lens's take        ║
║     analyze           per emit — derive insights across the full capture      ║
║     html_frontend     per emit — emit pieces for the HTML Report              ║
║     json_frontend     per emit — emit pieces for the Analyzed Report          ║
║                                                                               ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  RUNTIME  (debugging context open)                                      │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │   session-start hook         ─► instrumentation installed               │  ║
║  │        │                                                                │  ║
║  │        ▼                                                                │  ║
║  │   for each Observatory.collect(name, artifact):                         │  ║
║  │     each lens: observe → digest  (each lens's own take, serialized)     │  ║
║  │        │                                                                │  ║
║  │        ▼                                                                │  ║
║  │   session-end hook           ─► instrumentation restored                │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                             │                                                 ║
║                             ▼                                                 ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  CAPTURE  (the only thing persisted raw)                                │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │    per-lens captures  +  session context                                │  ║
║  │                                                                         │  ║
║  │            emit as  →  Raw Capture (JSON)                               │  ║
║  │                         archive, reload, CI input                       │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║              │                                                      │         ║
║              │ fresh session                  reloaded from an      │         ║
║              │                                older Raw Capture     │         ║
║              ▼                                                      ▼         ║
║  ┌─────────────────────────────────────────────────────────────────────────┐  ║
║  │  ANALYSIS + RENDERING  (runs on every emit)                             │  ║
║  ├─────────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                         │  ║
║  │    each lens:  analyze(captures, config) → derived insights             │  ║
║  │                                                                         │  ║
║  │    each lens:                                                           │  ║
║  │      ├── html_frontend(insights)    → HTML pieces                       │  ║
║  │      │                                 (tables, formatted blocks,       │  ║
║  │      │                                  interactive graphs, custom)     │  ║
║  │      │                                       │                          │  ║
║  │      │                                       ▼                          │  ║
║  │      │                             self-contained HTML Report           │  ║
║  │      │                                                                  │  ║
║  │      └── json_frontend(insights)    → structured analysis pieces        │  ║
║  │                                       (per-capture summaries,           │  ║
║  │                                        cross-capture findings)          │  ║
║  │                                             │                           │  ║
║  │                                             ▼                           │  ║
║  │                                     Analyzed Report (JSON)              │  ║
║  │                                                                         │  ║
║  └─────────────────────────────────────────────────────────────────────────┘  ║
║                                                                               ║
║  Only the Capture is raw. HTML and Analyzed Report are BOTH derived —         ║
║  each produced by its own frontend hook so the form is native to its          ║
║  consumer: HTML for humans, Analyzed Report JSON for LLMs, CI analytics,      ║
║  and dashboards.                                                              ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
```

A single picture, read top-to-bottom.

**During a run**, each `Observatory.collect(...)` call hands an artifact to every registered lens. Each lens decides whether it cares and, if so, turns its view into a serialized piece. Session hooks bracket the run, giving a lens a place to install and restore any instrumentation it relies on.

**At the end of the run**, the framework has accumulated one thing — a capture: each lens's serialized take, plus the session's lifecycle data. That is the only thing we ever persist raw. It can be written out as **Raw Capture (JSON)** for archival, CI ingestion, or reload later.

**At emit time**, each lens runs `analyze` over the full capture set and derives whatever insights it wants — per-capture metrics, run-wide summaries, graph overlays. It then projects those insights through two frontend hooks: `html_frontend` emits pieces the HTML report assembles into a self-contained file for human reviewers; `json_frontend` emits structured pieces that assemble into an Analyzed Report (JSON) for LLM triage agents, CI analytics jobs, or dashboards. §4.4 explains why this split is load-bearing for the whole architecture.

The six hooks are bound to a scoped Python context. When the context exits — including on exception — every lens's `session_end` fires and unwinds whatever `session_start` installed. Debugging instrumentation never leaks past its intended scope. §5.2 shows how contexts are opened and nested in code; §5.4 walks through the session-hook pattern applied to a concrete pipeline-patching example.

Backends declare which lenses are active in a short entry-point script; the framework core knows nothing about any specific lens. §6 walks through a full extension example.

### 4.4 Runtime captures vs analyzed results

Capturing data during a run is one job. Reasoning about it — computing metrics, diffing across captures, summarizing findings — is a different job. Observatory separates them explicitly: runtime emits raw captures (what each lens saw), and emit-time runs `analyze` over those captures to produce insights.

Three terms keep the split clear:

- **Session** — one runtime period during which lenses are active (a CLI invocation, a `with`-block, a decorated pass pipeline). `observe` and `digest` fire inside a session.
- **Archive** — the raw output of a session: a set of records plus session context. An archive lives briefly in-memory while its session is open, and persists on disk as a **Raw Capture (JSON)** once exported. The shape is the same either way — "in-memory" and "on disk" are just two stages of the same object's life.
- **Record** — one captured item inside an archive, produced by one `Observatory.collect(...)` call.

Every record traces back to some session. The demo in §3 shows the simplest path — a live session whose archive stays in-memory just long enough for the HTML Report to render. Cross-time regression (below) is the same mechanism on longer time horizons — archives written to disk on earlier runs, replayed into a later analyze pass.

The `analyze` phase consumes records. That is the hinge. `analyze(records, cfg)` doesn't care whether the records came from a live in-memory archive or from a JSON file written last week — the same analyze function sees the same records either way.

```
  session X ─► archive X ─► records x1, x2, x3   ┐
  session Y ─► archive Y ─► records y1, y2       │
  session Z ─► archive Z ─► records z1, z2, z3   ├─► analyze(records, cfg)
  …                                              │     one pass — every record
                                                 ┘     in every archive is
                                                        visible to every lens
                                                               │
                                                               ▼
   (each archive is a Raw Capture JSON —                ┌──────┴──────┐
    the in-memory store while its session               ▼             ▼
    is open, or a file on disk for any              html_frontend  json_frontend
    session that has ended)                              │             │
                                                         ▼             ▼
                                                   HTML Report    Analyzed Report (JSON)
                                                   (reviewers)    (LLMs, CI, dashboards)
```

Because `analyze(records, cfg)` takes a *set* of records with no opinion on where they came from, the same analyze function that compared adjacent records within one archive can compare records from multiple archives. Cross-time regression is that idea made concrete: combine two archives' records into one set, run analyze over the union, and each lens sees the two runs as neighboring records it already knows how to diff.

```bash
# Nightly CI — archive just the Raw Capture; HTML not required.
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-json nightly/${DATE}/mv2.json \
    --lens_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize

# Later — regression HTML from two archived Raw Captures.
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html
```

The `--compare` path loads both archives, concatenates their records into one set, and calls each lens's `analyze` exactly once with the combined set. The only thing that doesn't run again is the AOT compile.

The same separation is what lets Observatory emit multiple output forms from one set of records. `html_frontend` renders the analyzed result for human reviewers; `json_frontend` emits the Analyzed Report (JSON) for LLM triage agents, CI analytics, and dashboards. Both are derived by running analyze + frontend over the records; neither touches the raw data. New output forms — a terminal renderer, a chat-ops payload, whatever comes next — slot in the same way, without disturbing runtime or capture.

An archive is the single source of truth for its session. Analysis and rendering are derived — repeatable, retargetable, and composable over the same raw data.

### 4.5 The FX viewer

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

Each graph carries a **base layer** (nodes, edges, default coloring) plus any number of **extension layers** — transparent overlays contributed by lenses: per-node data, coloring rules, labels, tooltips. Users toggle layers in the viewer UI. For compare mode, extension layers can declare a **sync key** so cross-graph highlighting pairs nodes correctly even after fusion or decomposition has renamed them.

`fx_viewer` is not tied to Observatory — any developer with a `torch.fx` graph can drop it into a self-contained HTML file directly via `FXGraphExporter(gm).export_html(...)`.

### 4.6 Boundaries

Observatory is not a replacement for `Inspector`, `ETRecord`/`ETDump` — it *consumes* those primitives through lenses. The shipped report is a post-hoc artifact; a live-dashboard variant built on the same `fx_viewer` foundation is a natural follow-up (§7.3).

## 5. Using Observatory

§4.2 listed the three invocation surfaces. This section walks through each one with a concrete code recipe, and closes with a summary of where collection points come from.

### 5.1 CLI — for QA, CI, and community issue reporting

```bash
# Generic (framework lenses only)
python -m executorch.devtools.observatory \
    --output-html run.html \
    your_script.py --your-args

# Backend-specific with opt-in lens recipe
python -m executorch.backends.xnnpack.debugger.observatory \
    --lens_recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

**Use this when** filing a bug report, reproducing a CI failure, or handing work across teams. Zero code change, single artifact.

### 5.2 Python context manager — for targeted developer debugging

```python
from executorch.devtools.observatory import Observatory

config = {"accuracy": {"dataset": my_small_repro_set}}
with Observatory.enable_context(config=config):
    Observatory.collect("original", gm)
    transformed = my_experimental_pass(gm)
    Observatory.collect("after_my_pass", transformed)

Observatory.export_html_report("pass_debug.html")
Observatory.export_json("pass_debug.json")
```

**Use this when** iterating on a compiler pass with a custom dataset or custom lens config. Any instrumentation the active lenses installed at `session_start` is automatically unwound at the end of the `with`-block — even if the code inside raises.

**Nested contexts — scoping config changes to a phase.** A compile-and-deploy script often moves through phases with very different debugging needs: a cheap preprocess step, an expensive quantization step, a device-inference step. Nested `enable_context` calls let you express those per-phase overrides as block-scoped code instead of imperatively toggling lenses on and off. When an inner `with` exits, its config is popped and the outer config resumes automatically — no cleanup code on your part, no state leaking between phases.

```python
with Observatory.enable_context(config={"per_layer_accuracy": {"enabled": False}}):
    gm = preprocess(model)
    Observatory.collect("preprocessed", gm)

    # Inside this phase only, turn on the expensive lens with a heavy dataset.
    with Observatory.enable_context(
        config={"per_layer_accuracy": {"enabled": True, "dataset": heavy_repro_set}}
    ):
        gm = my_heavy_transform(gm)
        Observatory.collect("after_heavy", gm)

    # Outer config is back in effect here: per_layer_accuracy is off again.
    gm = postprocess(gm)
    Observatory.collect("final", gm)
```

The essence of the mechanism is **temporal scoping of debugging config**: each nested block is a scope inside which some subset of lens configuration is overridden, and the override lifetime is exactly the lifetime of the Python scope. Nothing more is in the programming model — but it turns out to be enough to express every per-phase lens adjustment we have needed so far.

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

with Observatory.enable_context():
    pm._transform(graph_module)
```

**Use this when** building or tuning a pass pipeline and you want every pass's before/after captured automatically.

### 5.4 Where collection points come from

Three mechanisms produce collection points; all three flow into the same `collect(name, artifact)` path:

- **Wrapper patches installed by lenses on `session_start`** — the default `pipeline_graph_collector` lens, for example, replaces `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, and `ETRecord.add_*` with wrappers that forward the call *and* hand the returned object to `collect()`. The patches are removed in `session_end`, so the patched functions are only different while the debugging context is open.
- **`@observe_pass` decorator** — tag any `PassBase` subclass or instance. The decorator captures the graph before and after each decorated pass fires, no further code change required.
- **Manual `Observatory.collect(name, artifact)`** — available anywhere in user code, for moments that aren't at one of the above breakpoints.

Here is what the wrapper pattern actually looks like inside a lens. The lens captures originals on `session_start`, replaces them with forwarding wrappers that also call `collect()`, and restores them on `session_end`:

```python
class PipelineGraphCollector(Lens):
    _originals = {}

    @classmethod
    def on_session_start(cls, context):
        # Save originals, install wrappers that forward + collect.
        import torch.ao.quantization as q
        cls._originals["prepare_pt2e"] = q.prepare_pt2e

        def patched_prepare(model, quantizer, *a, **kw):
            gm = cls._originals["prepare_pt2e"](model, quantizer, *a, **kw)
            Observatory.collect("prepare_pt2e", gm)
            return gm

        q.prepare_pt2e = patched_prepare
        # … same pattern for convert_pt2e, to_edge_transform_and_lower, ETRecord.add_*

    @classmethod
    def on_session_end(cls, context):
        # Restore originals — runs even if user code raised inside the context.
        import torch.ao.quantization as q
        q.prepare_pt2e = cls._originals["prepare_pt2e"]
        # … restore the rest.
```

The shape is the same for any kind of instrumentation a lens wants to install: log-stream taps, device-shell hooks, profiler starts. Whatever goes in on `session_start` comes back out on `session_end` — including on exception — so the user's baseline environment is restored after every debugging context closes. §6 applies this exact pattern to on-device ADB calls.

## 6. Extending with custom lenses

**`collect()` is type-agnostic; lenses self-filter.** The signature is `collect(name: str, artifact: Any)` — no type constraint on the artifact. A graph lens receives a `GraphModule`, a log lens receives a `LogEntry`, a profiling lens receives a timing snapshot. Each lens `isinstance()`-checks inside `observe()` and returns `None` when it doesn't care. Graph, log, and profiling lenses coexist in the same session without knowing about each other.

That is the full extension surface. A new lens decides what it captures, how it filters, how it serializes, how it analyzes, and how it renders. Below is a concrete example: an ADB-log lens that captures `logcat` output from every on-device inference, without touching Observatory core and without any other lens knowing it exists.

```python
from dataclasses import dataclass
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.interfaces import Lens

@dataclass
class AdbLogEntry:
    source: str        # "logcat", "dmesg"
    content: str
    rc: int

class AdbLogLens(Lens):
    _original = None

    @classmethod
    def on_session_start(cls, context):           # install patch
        from executorch.backends.qualcomm.runtime import adb_helper
        cls._original = adb_helper.run_inference

        def patched(cmd, **kw):
            result = cls._original(cmd, **kw)
            logcat = adb_helper.fetch_logcat(since=result.started_at)
            Observatory.collect(
                f"adb_log/{cmd.label}",
                AdbLogEntry("logcat", logcat, result.rc),
            )
            return result

        adb_helper.run_inference = patched

    @classmethod
    def on_session_end(cls, context):             # restore patch
        from executorch.backends.qualcomm.runtime import adb_helper
        adb_helper.run_inference = cls._original
        cls._original = None

    @classmethod
    def observe(cls, artifact, context):          # self-filter
        if not isinstance(artifact, AdbLogEntry):
            return None
        return {"source": artifact.source,
                "lines": artifact.content.splitlines(),
                "rc":    artifact.rc}
```

With `AdbLogLens` registered, every on-device inference produces a log capture automatically. The `graph`, `accuracy`, and `metadata` lenses see the `AdbLogEntry` too and all return `None`.

**Nested contexts scope configuration per phase.** Lens config is stacked — each `enable_context(config=...)` merges and pops on exit:

```python
with Observatory.enable_context(config={"accuracy": {"dataset": my_set}}):
    gm = compile_and_lower(model)
    Observatory.collect("edge", gm)

    # Runtime phase: disable accuracy, enable adb_log
    with Observatory.enable_context(config={
        "accuracy": {"enabled": False},
        "adb_log":  {"enabled": True, "fetch_dmesg": True},
    }):
        run_on_device(edge_program)

    Observatory.collect("post_device", gm)

Observatory.export_html_report("run.html")
```

Any artifact flows through `collect`; lenses pick what they care about; instrumentation attaches/detaches with the context; config nesting shapes which lenses run in which phase.

## 7. Feature landscape and roadmap

Observatory composes with existing ExecuTorch devtools — `Inspector`, `ETRecord` / `ETDump`, `bundled_program`, and `devtools/visualization/` keep doing what they do; Observatory consumes their output through lenses and unifies what every backend used to script by hand. This section maps debugging workflows onto three tiers: shipped on the draft branch, proposed in this RFC, and follow-ups for after this RFC merges.

**Draft branch:** [draft-branch link] — one branch (also called *demo branch*; same thing). Pre-generated reports in §3 come from this branch.

### 7.1 Shipped in the draft branch today

Pull the draft branch, install dependencies (§3), run the CLI — you get the following by default.

- **Compile-time accuracy** — per-operator PSNR / cosine / MSE across lowering stages; replaces per-backend `print` + CSV diffs. Lenses: `accuracy`, `per_layer_accuracy`.
- **Graph-state capture at pipeline breakpoints** — the graph at each standard stage (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_*`); replaces `print(gm.graph)` and per-backend log dumps. Lens: `pipeline_graph_collector` + `graph`.
- **Pass diff** — before/after capture around any decorated pass; replaces text diff and manual side-by-side. Mechanism: `@observe_pass` + `graph` compare mode.
- **Collection provenance** — user-code call stack at each capture point, in the HTML viewer's info panel; replaces manual log annotation. Lens: `stack_trace`.
- **Interactive FX graph view** — pan, zoom, minimap, fuzzy search, N-way compare with cross-graph sync; embedded in the HTML, no server. Component: `fx_viewer`.
- **Run metadata dashboard** — command line, environment, input model, lens-contributed sections; replaces hand-rolled README attachments. Lens: `metadata`.
- **Context sharing** — one HTML + one Raw Capture JSON per run, attach-and-go; replaces zips of logs, CSVs, and screenshots.

### 7.2 Proposed in this RFC, not yet implemented in the draft branch

Two extensions to the Lens protocol / CLI that are part of this RFC's design but not yet implemented in the draft branch. The tag *(not yet implemented)* marks them throughout the doc — they should be reviewed alongside the rest of the RFC.

- **Analyzed Report (JSON) via `json_frontend`** *(not yet implemented; §4.4)* — a second frontend hook on the Lens protocol that emits structured analysis pieces alongside the HTML pieces, plus an emit path that writes the assembled payload as JSON. Most impactful extension for LLM triage, CI analytics, and dashboards.
- **`--compare` CLI mode** *(not yet implemented; §4.4)* — a CLI subcommand that takes two or more archived Raw Captures and emits a regression HTML or Analyzed Report JSON by running a comparison lens over the combined capture set.

### 7.3 Further directions (follow-ups beyond this RFC)

Follow-up work after this RFC merges. None of these are part of what this RFC asks reviewers to approve — we list them so reviewers can flag what's most valuable to pursue next.

- **Runtime / delegated-graph accuracy lens** — port `qnn_intermediate_debugger.py` into a lens that uses `debug_handle` + `Inspector` to compare CPU against on-device execution; replaces the current per-backend manual scripts. Most-requested follow-up.
- **Backend tool ports into lenses** — one lens each for QNN QHAS profiling, XNNProfiler aggregation, QParam audit, delegation info (color layer), `.pte` diff (over archived captures), size analysis. Incrementally replaces existing `devtools/backend_debug/`, `devtools/pte_tool/`, `devtools/size_analysis_tool/` scripts.
- **Runtime lenses on `Inspector` + `ETDump`** — performance, memory, crash-analysis lenses fed by existing runtime-capture primitives.
- **Device-side profiling lens** — ADB capture and on-device perf traces, on the session-hook pattern (§5.4, §6).
- **Non-FX graph formats in `fx_viewer`** — PyTorch graph, QNN graph, TOSA as first-class exporters.
- **Nightly-regression CI recipe** — package the archived-Raw-Capture + `--compare` flow as a reusable CI template.
- **Live debugging dashboard** — `fx_viewer` as foundation for streaming-event dashboards beyond post-hoc reports.

---

The shared mechanism behind all of this is small: a Lens protocol with six hooks plus a per-backend registration point. Every workflow above is one or more lenses; a new backend gets CLI, report shape, compare mode, graph view, and Raw Capture archive for free.

## 8. Review, landing, and maintenance

This section covers two meta-level questions about the draft: how to land it, and how to maintain it.

### 8.1 Review and merge strategy

The draft PR linked in §7 is intentionally monolithic so reviewers can read the RFC alongside running code. For *design review*, that's the right unit. The question is what happens after design review concludes.

We see two reasonable landing options. We recommend **Option B**; reviewer capacity should drive the decision.

**Option A — Land as one PR.** Merge the draft PR as-is. Works if a small reviewer group can handle the full diff in one pass; risks broad-but-shallow review and all-or-nothing reverts.

**Option B — Three-PR stack** *(our recommendation)*. Three focused PRs in dependency order:

1. **`devtools/fx_viewer/`** — standalone; usable on its own via `FXGraphExporter(gm).export_html(...)`.
2. **`devtools/observatory/`** — core framework, seven common lenses, generic CLI. Depends on PR 1.
3. **Backend CLIs** — Qualcomm + XNNPACK together, each with end-to-end model-matrix validation. Depends on PR 2.

Each PR is focused enough for one reviewer to sign off on; `fx_viewer` can be adopted by anyone not using Observatory.

### 8.2 Maintenance and collaboration

Observatory and `fx_viewer` introduce shared infrastructure multiple teams will build on. The ownership rules below keep boundaries clean.

**Ownership.** Mirrors the directory structure:

- **Core devtools reviewers** own `devtools/observatory/` core, `devtools/fx_viewer/` core, and the generic lenses in `devtools/observatory/lenses/`.
- **Backend teams** own `backends/<name>/debugger/observatory/cli.py`, backend-registered patches, and backend-specific lenses. No core sign-off needed.
- **Cross-cutting changes** (Lens protocol, `GraphExtension` API, JSON schema, JS runtime) need core sign-off regardless of directory.

**Testing.** Follows ownership: infra tests (`devtools/observatory/tests/`) are owned by core; backend-specific tests are owned by backend teams. CI invariant: every backend CLI runs a smoke test on a representative model.

**Non-backward-compatible API changes.** The Lens protocol, `GraphExtension`, and the `digest()` / `analyze()` JSON schema are the surfaces most likely to break downstream consumers. A PR that breaks them must either:

1. **Fix every caller in the same PR** — preferred when the blast radius is small and entirely in-tree.
2. **Announce in advance and stage the migration** — preferred when the change affects backend lenses or archived JSON consumers; announcement via issue or RFC update; landing only after migration PRs are ready.

### 8.3 Open questions

Items below are genuinely undecided. We welcome opinions in the draft PR thread or as comments on this RFC.

1. **Core vs backend ownership boundary.** Is "generic lens lives in `devtools/`, backend-specific lens lives in `backends/`" sufficient, or do we need a middle tier (e.g., shared-across-two-backends)? How should a lens that starts backend-specific and becomes generic migrate?
2. **Lens API stability signal.** Should lenses advertise an experimental/stable tier so external contributors know what's safe to depend on, similar to `torch.compile`'s stability annotations?
3. **Breaking-change communication channel.** Is an issue label (`observatory-api-change`) sufficient, or do we need a notification channel (mailing list, tagged GitHub team) to reach known backend owners?
