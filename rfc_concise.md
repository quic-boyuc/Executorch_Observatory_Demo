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

If you have ever debugged by sprinkling `print(gm.graph)` across a pass, written a CSV parser to diff two per-layer accuracy dumps, or zipped logs into a tarball for a GitHub issue — this RFC is for you.

This RFC is aimed at three kinds of reader.

If you are **writing or tuning a compile pass** — adding a new quantizer, debugging a lowering regression, diffing the graph across a transform — Observatory captures the graph between transform passes wherever you ask: wrap your passes with a decorator, or drop manual breakpoints into your own code. What lands on each captured graph — accuracy overlays, partition coloring, node provenance, whatever else matters — is contributed by **Lenses** (Python extensions that implement debugging logic), so one investigation can ask several questions at once.

If you are **running CI or triaging community bugs**, Observatory gives you a zero-code-change CLI that wraps any AOT script and emits a single HTML file you can attach to an issue, and the same data as JSON for archival and regression comparison.

If you are **a backend owner** and you have felt the friction of writing the same per-layer accuracy, graph-dump, and log-collection scripts that every other backend has written in its own way, Observatory is the shared place to contribute once. The mechanism is a **Lens** — a single Python extension that owns one debugging concern end-to-end: *enable, configure, export, analyze, visualize*. Your backend define lenses for differenct debugging needs; the framework handles the session, the report, and everything in between. `fx_viewer`, a pure-HTML server-free graph renderer, is the visual anchor graph-producing lenses paint on.

**Document map.** §2 states the problem. §3 shows the tool in action. §4 explains the design ideas. §5 is the architecture. §6 covers the three invocation surfaces. §7 is a worked extensibility example. §8 positions Observatory against existing devtools. §9 is the roadmap. Reference material lives in [reference.md](./reference.md).

## 2. The problem

Two frictions, small on their own, compound across backends, artifact types, and teams.

### 2.1 The whole debugging workflow is fragmented
ExecuTorch has provided primitives for enabling instrumentation — `debug_handle` survives into delegated graphs, `Inspector` consumes it, `ETRecord` / `ETDump` capture aot and runtime events. What's missing is shared infrastructure for the rest of a debugging session: **configuring** the run (which lens, which dataset, which threshold), **exporting** the captured artifacts into something analyzable, **analyzing** them (metrics, diffs, cross-record comparisons), and **visualizing** the result for a human reader. Debugging is a five-stage workflow, and today each backend rebuilds four of those stages by hand.

On Qualcomm, `qnn_intermediate_debugger.py` wires activation and partial export into a per-layer accuracy flow — at the cost of significant manual setup per invocation, and with analysis and visualization living in terminal prints and hand-rolled CSVs. Every backend writes enable-logic, config, export format, comparison logic, and rendering differently.

And graph debugging is the *easy* case — it's the one artifact type where a shared data structure (`GraphModule`) gives the workflow a common anchor. For edge-device logs, runtime profiling traces, partition assignments, and on-device snapshots, each backend needs to define their own data model, their own export format, and their own analysis.

The fragmentation extends to the output format itself. Debugging results today live in ad-hoc CSVs, printed tables, and screenshots — hard for humans to skim, harder for scripts to process. A unified format would serve both kinds of consumer from one capture: structured **JSON** for querying and programmatic processing, and a standalone **HTML** file for human reading and analysis.

### 2.2 The graph has no viewer built for the workflow

`torch.fx` is the core IR for ExecuTorch lowering, and the graph at each stage is where most of the interesting debugging happens: *did this op get decomposed, did that sequence get fused, which nodes fell out of the delegated region?* The closest tool today, `devtools/visualization/`, forwards an `ExportedProgram` to Google's Model-Explorer via a local web server - not embeddable in standalone documents, not sharable in discussion threads.

The deeper problem is composition with debugging information. A graph is the natural visual anchor for many debugging concerns at once: accuracy as a color gradient, partition assignment as a second overlay, QParams in a node's info panel, profiling numbers on labels. Without a shared viewer that multiple lenses can paint on, each concern ends up in its own dashboard. `fx_viewer` closes this gap — in-pipeline, embeddable, layered, and reusable outside Observatory, with Python API (export time customization) and JS API (frontend interaction).

Observatory and `fx_viewer` together answer both.

## 3. Quick tour — zero-config per-layer accuracy debugging

One command in, one HTML file out.

> **Scope note.** Per-layer accuracy shown here is **compile-time**: the `per_layer_accuracy` lens runs CPU simulation across graph snapshots at different lowering stages and compares against a float anchor. Runtime / delegated-graph accuracy is targeted for a follow-up lens (see §9).

```bash
pip3 install 'fast-sugiyama[full]'   # requires python >= 3.11

python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

The XNNPACK CLI (`python -m executorch.backends.xnnpack.debugger.observatory`) takes the same shape — wrap any existing AOT script, no code change.

[[MEDIA: png — side-by-side terminal: default run vs `--lens_recipe=accuracy`]]

### What you get

A **self-contained HTML file** — no server, no login, no external service. Attach it to an issue, a PR, or an email.

- **Run dashboard (landing page).** Per-run metadata: command line, environment, input model. Each lens can contribute a section.
- **Captures and change summaries (left panel).** One captured item per collection point (think: breakpoint). Between adjacent captures, a change summary highlights what moved (node-count delta, PSNR change). Click a capture → single view. Click a change summary → 2-capture compare. Click *Select* → N-capture compare.
- **Interactive FX graph.** Pan, zoom, minimap, fuzzy search. N-way synchronized compare: clicking a node in one graph highlights the matching node in every other graph — sync driven by `debug_handle` / `from_node`.
- **Per-layer accuracy as a color overlay.** With `--lens_recipe=accuracy`, per-operator PSNR / cosine / MSE render as a color gradient on the graph. Worst-accuracy operators stand out visually; node click shows full metric breakdown.

[[MEDIA: gifs — capture open, change-summary compare, multi-capture select, cross-graph sync, PSNR overlay]]

Pre-generated reports for a matrix of models are linked from the demo index. Lenses active in this demo: `metadata`, `stack_trace`, `graph`, `accuracy`, `per_layer_accuracy`, `pipeline_graph_collector`, `graph_color`. Full descriptions in [reference.md §G](./reference.md).

## 4. Design ideas

The problems in §2 narrow the design space sharply: shared and extensible (one place to contribute), in-pipeline graph view (no separate server), single-file output (one thing the recipient opens). Five ideas fall out.

### 4.1 A Lens protocol carries both instrumentation and rendering

Different backends care about different moments: one wants the graph just before its partitioner runs, another wants the output of a vendor quantizer, a third wants every device-shell command and its log. If the framework itself knew about those moments, it would become a grab-bag of backend-specific code. So both the *capture* logic and the *render* logic live in the extension unit — a **Lens**. Each lens implements a small protocol: session start/end hooks bracket a run; `observe / digest` runs per capture; `analyze` runs over the full capture set at emit time; and two frontend hooks (`html_frontend` and `json_frontend`) project the analysis into renderable pieces for the HTML and JSON reports respectively (§4.4). Backends declare which lenses are active in a short entry-point script; the framework core knows nothing about any specific lens.

### 4.2 A debugging context scopes monkey-patching

Inside the context, standard pipeline functions (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_*`) are temporarily replaced with wrappers that forward the call and hand the returned object to the registered lenses. On exit — including on exception — originals are restored. One manual entry point, `Observatory.collect(name, artifact)`, covers cases where the interesting moment is not at a standard pipeline function.

### 4.3 `collect()` is type-agnostic; lenses self-filter

The signature is `collect(name: str, artifact: Any)` — no type constraint. A graph lens receives a `GraphModule`, a log lens receives a `LogEntry`, a profiling lens receives a timing snapshot. Each lens `isinstance()`-checks inside `observe()` and returns `None` when it doesn't care. Graph, log, and profiling lenses coexist in the same session without knowing about each other. This is the hinge that makes Observatory extensible beyond graphs (§7).

### 4.4 Two kinds of JSON, for two kinds of consumer

Once a lens has captured something, an HTML report is one kind of thing you might want to emit — not the only one. An archival CI job wants the *raw capture* and nothing else, so it can stash a run and reload it later. An LLM-assisted triage agent wants the *analyzed result* in a structured shape, so it can reason about insights without scraping HTML. Those are two different outputs, produced at two different points in the flow.

So we separate them:

- **Raw Capture (JSON)** — each lens's serialized record of what it saw, plus the session's lifecycle data. Produced at the end of the run; reloadable any time later.
- **Analyzed Report (JSON)** — the structured output of running `analyze` over a capture. Same information the HTML report carries, in JSON form. Produced by the lens protocol's second frontend hook, which emits machine-friendly pieces alongside the HTML-friendly ones.

The HTML report is a third output: a human-friendly render of the same analyzed data. HTML and Analyzed Report are both *derived* — recomputed on every emit by running the current lens code over the raw capture. The only thing ever persisted raw is the capture itself.

### 4.5 `fx_viewer` is pure client-side, with pre-computed layout and extension layers

The report is a single HTML file, so the graph viewer must run entirely in the browser — no server, no separate tab. A single report can carry dozens of graphs with thousands of nodes each; dynamic layout in the browser would be slow, and one DOM element per node would be slow. So we do the expensive work at build time: extract graph structure, compute exact `(x, y)` + edge routing with **Sugiyama layout** (via `fast-sugiyama`), embed everything as JSON in the HTML. At view time the JavaScript paints straight to a `<canvas>`. A typical multi-graph report stays under ~1 MB.

Each graph carries a **base layer** (nodes, edges, default coloring) plus any number of **extension layers** — transparent overlays contributed by lenses: per-node data, coloring rules, labels, tooltips. Users toggle layers in the viewer UI. For compare mode, extension layers can declare a **sync key** so cross-graph highlighting pairs nodes correctly even after fusion or decomposition has renamed them.

`fx_viewer` is not tied to Observatory — any developer with a `torch.fx` graph can drop it into a self-contained HTML file directly via `FXGraphExporter(gm).export_html(...)`.

### 4.6 Boundaries

Observatory is not a replacement for `Inspector`, `ETRecord`/`ETDump` — it *consumes* those primitives through lenses. The shipped report is a post-hoc artifact; a live-dashboard variant built on the same `fx_viewer` foundation is a natural follow-up (§9).

These six ideas assemble into a small concrete system. §5 renders it in two diagrams: how a backend plugs into the core, and what a single lens does at every stage of a run.

## 5. Architecture

This chapter presents the system in two diagrams. **§5.1** (Graph 1) shows the architectural layers and their responsibilities — interface, core, lenses — with `fx_viewer` placed where it actually sits in the code: as an external module leveraged by the Core's `GraphHub`. **§5.2** (Graph 2) zooms in on the Lens contract: what a lens author implements, when each hook fires, and what actually crosses the JSON persistence boundary vs what is always recomputed. §5.3 and §5.4 then cover two concrete scenarios the architecture supports — cross-time regression, and the `fx_viewer` build-time/run-time split.


### 5.1 Architectural layers

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

Reading the diagram top-to-bottom. The **Interface Layer** is where every human touch-point lives. A *user interface* for driving a run (a generic CLI, per-backend CLIs, a `with`-block or `@observe_pass` decorator, or a direct `Observatory.collect(...)` call) and for reading its output (HTML in a browser, or JSON consumed by CI, an LLM triage agent, or a dashboard). A *lens author* surface — the small Lens protocol that a framework or backend developer implements to teach Observatory about a new debugging concern. Three *artifacts* come out: an HTML Report for human reviewers, a **Raw Capture (JSON)** for archival and later reload, and an **Analyzed Report (JSON)** for machine consumers.

The **Observatory Core** is the backend-agnostic engine that drives the lifecycle. A session manager owns the debugging context and dispatches lifecycle hooks. A capture store fans each `collect` call out across every registered lens and keeps each lens's take. Report assembly runs each lens's `analyze` over the full capture set, then branches into rendering: the HTML path assembles view pieces into one self-contained file; the JSON path assembles a structured payload. Inside Report Assembly, the GraphHub merges the base graph captured by the `graph` lens with overlay layers contributed by any lens's analyze phase, then hands the combined payload to `fx_viewer` for layout and relayout.

The *Export* sub-panel is where the two-JSONs-plus-HTML design becomes concrete. The Raw Capture is the only thing ever emitted without analysis — it is a snapshot of the raw serialized run. HTML and Analyzed Report both pass through `analyze` first, and both can be produced from a fresh session or from a reloaded Raw Capture — with whatever the current lens code happens to be.

**Lenses** at the bottom are the protocol implementations. The framework ships seven common lenses; each backend contributes its own. From the Core's perspective they are the same kind of object — only their shipping location differs.

### 5.2 A lens and the two reports it produces

The protocol a lens implements is small on purpose — six hooks, each one doing one thing. Half of them run live while a run is happening (the session bookends and the per-capture pair `observe / digest`); the other half run at emit time (`analyze` and the two frontend hooks). The diagram below walks the whole life of a lens's data, from capture to report.

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

**At emit time**, each lens runs `analyze` over the full capture set and derives whatever insights it wants — per-capture metrics, run-wide summaries, graph overlays. It then projects those insights through two frontend hooks:

- `html_frontend` emits pieces the HTML report assembles into a self-contained file for human reviewers.
- `json_frontend` emits structured pieces that assemble into an **Analyzed Report (JSON)** — same information the HTML carries, shaped for an LLM triage agent, a CI analytics job, or a dashboard to consume directly.

Two consequences worth stating explicitly:

- **The archive survives lens-code changes.** A Raw Capture written a month ago can be re-analyzed and re-rendered today with whatever the lens code has become. The only raw-persisted thing is the capture itself.
- **Each consumer gets a form native to it.** Humans get HTML; machines get Analyzed Report JSON. Nobody has to scrape the other's format.

### 5.3 Cross-time regression in practice

A useful thing falls out of the capture-and-derive split. If the Raw Capture is small and analysis is cheap, then archiving a Raw Capture from every nightly CI run costs almost nothing — and when a metric regresses, you can re-render any two archives side by side without recompiling the model.

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

A comparison lens reads both captures, runs a full `analyze` over them together, and produces a regression report that shows exactly what moved (PSNR deltas, node-count changes, partition shifts) — emitted as HTML for a human reviewer, or as an Analyzed Report (JSON) for automated triage. What it skips is the AOT compile; everything else still runs.

### 5.4 `fx_viewer` — build-time vs run-time split

```
 BUILD TIME                         Observatory lenses (analyse)
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

Full Lens protocol in [reference.md §A](./reference.md); `fx_viewer` extension API in [reference.md §C](./reference.md).

## 6. Three ways to use it

Same framework, three invocation surfaces — each matches a different debugging context.

### 6.1 CLI — for QA, CI, and community issue reporting

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

### 6.2 Python context manager — for targeted developer debugging

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

**Use this when** iterating on a compiler pass with a custom dataset or custom lens config. Monkey patches live only for the `with`-block's lifetime.

### 6.3 `@observe_pass` decorator — for pass-centric debugging

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

### 6.4 Where collection points come from

- **Wrapper patches by lenses during session** — E.g. The default lense `pipeline_graph_collector` — patches `prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_*` for the session.
- **Pass decorator** — `@observe_pass` on any `PassBase` subclass or instance.
- **Manual** — `Observatory.collect(name, artifact)` anywhere.

All patches are installed in `Lens.on_session_start` and restored in `Lens.on_session_end`.

## 7. Extending beyond graphs — an ADB-log lens sketch

The §3 demo captures FX graphs, but `collect()` takes any Python object. A backend can add an ADB-log lens (or a QParam dump, or an ETDump snapshot) without touching Observatory core. The same four ideas from §4 make this work — the framework never learns about `AdbLogEntry`.

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

## 8. Where it fits — and what's newly unlocked

Observatory composes with existing `devtools/` primitives rather than replacing them. The same framework covers workflows every backend currently solves in isolation.

| Workflow | Existing primitive / tool | Observatory path |
|---|---|---|
| **Compile-time accuracy** (PSNR / cosine / MSE across lowering stages) | Manual `print` + ad-hoc comparison; no unified flow | `accuracy` + `per_layer_accuracy` |
| **Runtime / delegated accuracy** (CPU vs on-device inside delegate) | `backends/qualcomm/debugger/qnn_intermediate_debugger.py` (manual setup); no XNNPACK equivalent; `debug_handle` + Inspector primitives available but not wired | Port QNN logic into an Observatory lens |
| **Graph-state capture** at each pipeline stage | `print(gm.graph)`; per-backend log dumps; ARM `TOSA_minimal_example.ipynb` | `pipeline_graph_collector` + `graph` |
| **Pass diff** (before/after any pass) | Text diff; manual side-by-side | `@observe_pass` + `graph` compare mode |
| **Collection provenance** (which call site produced this capture) | Manual log annotation | `stack_trace` |
| **Delegate partition inspection** | `devtools/backend_debug/delegation_info.py` | `partition` color layer on `graph` |
| **QParam audit** | Manual `node.meta` inspection | `qparams` lens |
| **`.pte` file diff** | `devtools/pte_tool/diff_pte.py` | `pte_diff` lens over archived Raw Capture |
| **Size / memory breakdown** | `devtools/size_analysis_tool/` | `size` lens |
| **Op-level runtime profiling** | QNN QAIRT QHAS / optrace; `XNNProfiler.cpp` | Lens fed by ETDump |
| **Cross-time regression** (diff two archived runs) | Manual script + scraping logs | `--compare` CLI mode over two Raw Captures (see §5.3) |
| **LLM / auto-triage ingestion** (structured analyzed output) | None — today only raw JSON or scraped HTML | `json_frontend` + Analyzed Report (JSON) (see §5.2) |
| **Module-hierarchy browsing** (post-export) | `devtools/visualization/` (Model-Explorer, web server) | Complementary — different job; no HTML embed, no debugger-info API. See [reference.md §B](./reference.md) |
| **Context sharing** (reviewer, QA, community) | Zip logs + CSVs + screenshots | One HTML + one JSON |

The shared mechanism is small — a lens protocol with two lifecycle hooks, a per-capture pair, an analyze phase, and two frontends — plus a per-backend registration point. Every workflow above is one or more lenses. A new backend gets CLI, report shape, compare mode, graph view, and Raw Capture archive for free. For which rows are shipped today vs tracked on the draft branch, see §9.

## 9. Where we go from here

This section is the canonical status reference: every feature described inline throughout the RFC is treated as first-class API; this is the single place that tracks what ships in the demo branch vs what is on the draft branch.

**Draft branch for proposed features:** [draft-branch link]  ·  **Demo branch:** [demo-branch link]

**What the demo branch ships today.** The core framework, `fx_viewer`, the seven common lenses listed in §3, backend CLIs for Qualcomm and XNNPACK, HTML Report export, Raw Capture (JSON) export, and a `visualize` CLI mode that re-renders HTML from an archived Raw Capture.

**What the RFC proposes but is not yet in the demo branch.** Every item below is part of this design and has a natural landing point in the Lens protocol or the CLI. Each is tracked on the draft branch linked above; the tag `*(not yet in demo)*` marks items that have not yet been written into the reference POC.

- **Analyzed Report (JSON) via `json_frontend`** *(not yet in demo; §4.4, §5.2)* — extend the Lens API with a second frontend hook that emits structured pieces alongside the HTML pieces, and wire an emit path that writes the assembled analyzed payload as JSON. The single most impactful extension for LLM-assisted triage, CI analytics, and automated dashboards.
- **`--compare` CLI mode** *(not yet in demo; §5.3)* — a CLI subcommand that takes two (or more) archived Raw Captures and emits a regression HTML or Analyzed Report JSON by running a comparison lens over both capture sets.
- **Runtime / delegated-graph accuracy lens** *(not yet in demo)* — port `qnn_intermediate_debugger.py` logic into a lens that uses `debug_handle` + Inspector to compare CPU vs on-device execution, zero manual wiring. Most-requested follow-up.
- **Runtime lenses on Inspector + ETDump** *(not yet in demo)* — performance, memory, and crash-analysis lenses fed by the existing runtime-capture primitives.
- **Port existing backend tools into lenses** *(not yet in demo)* — QNN QHAS profiling, XNNProfiler aggregation, QParam audit, delegation-info as a color layer, `.pte` diff as a lens over archived captures.
- **Device-side profiling** *(not yet in demo)* — ADB capture, on-device perf traces.
- **Non-FX graph formats in `fx_viewer`** *(not yet in demo)* — PyTorch graph, QNN graph, TOSA as first-class exporters, so the viewer serves more than FX.
- **Nightly-regression CI recipe** *(not yet in demo)* — package the archived-Raw-Capture + `--compare` flow from §5.3 as a reusable CI template.
- **Live debugging dashboard** *(not yet in demo)* — `fx_viewer`'s self-contained HTML, JSON-driven state, and extension APIs are a natural foundation for streaming-event dashboards beyond post-hoc reports.

Some are natural next PRs. Others depend on how the protocol stabilizes and who in the community picks them up — which is, in the end, the question this RFC is asking.

## 10. Reference material

Structural, API-level, and policy material lives in **[reference.md](./reference.md)**:

- §A — Lens protocol
- §B — `devtools/visualization/` vs `fx_viewer` feature comparison
- §C — `fx_viewer` extension API (info panel, labels, coloring, sync, full example)
- §D — CLI reference (generic + Qualcomm + XNNPACK)
- §E — Directory structure
- §F — Backend extension pattern (patches + custom lenses)
- §G — Lens catalog
- §H — Maintenance and collaboration strategy
- §I — Open questions
