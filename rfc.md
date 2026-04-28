# RFC: Observatory — A Unified Debugging Framework for ExecuTorch

<!-- separate each entry by an empty line to avoid format issue --> 
**Status:** Draft for review

**Authors:** Qualcomm Innovation Center, Inc.

**Audience:** ExecuTorch maintainers, backend owners, devtools reviewers

**Scope:** Add `devtools/observatory/` and `devtools/fx_viewer/` as shared ExecuTorch debugging infrastructure

**Draft PR:** [PR link]

**Live demo:** [Demo index link]

---

## 1. Introduction

This RFC proposes adding two components to `devtools/` as shared ExecuTorch debugging infrastructure:

- **Observatory** — a framework that captures the artifacts produced during compilation and turns them into a single structured, interactive, shareable report.
- **`fx_viewer`** — a standalone, dependency-free, interactive FX-graph renderer that powers Observatory's graph view and is also useful on its own.

If you have ever debugged a quantization regression by sprinkling `print(gm.graph)` across a pass, written a CSV parser to diff two per-layer accuracy dumps, or zipped logs into a tarball to attach to a GitHub issue — this RFC is for you. We have been writing those scripts too, and we think there is a better shape for them.

The short version: every ExecuTorch backend faces the same class of debugging questions — *what did the graph look like at this stage? why did accuracy drop after quantization? where did this node come from? what changed between yesterday's nightly and today's?* Today each backend answers those questions with its own bespoke scripts. Observatory treats each kind of analysis as a **Lens**, a small Python extension that plugs into one shared workflow. Every backend gets the same report shape, the same CLI entry point, and the same JSON-first output — machine-readable for CI and AI consumers, and rendered into a self-contained HTML for human reviewers.

**Who Observatory is designed for.** Four kinds of engineer sit behind the design decisions in this document:

1. *Developers debugging or profiling a pass or lowering step*, who need to see what changed and where execution diverged without reconstructing context by hand.
2. *QA and CI engineers* who need a failure handoff that is actually self-contained.
3. *Community users* filing bug reports who would rather attach one HTML file than transcribe command output.
4. *Anyone writing automated triage* — dashboards, regression trackers, AI-assisted analysis — who needs a stable machine-readable report format.

**How to read the rest of this document.** Section 2 describes the problem we keep running into. Section 3 states the goals. Sections 4–5 show what the tool looks like in practice — an end-to-end demo, then the three invocation surfaces you'd actually use day-to-day. Section 6 opens the hood on the Lens protocol and the JSON-first design choice. Sections 7 and 8 zoom out to how Observatory fits with `devtools/visualization/`, Inspector, ETRecord, and the per-backend debugging tooling that already exists. Section 9 is where we see this going. Reference material lives in [reference.md](./reference.md).

## 2. The problem we keep running into

Three frictions, each one small on its own, but compounding across backends and teams.

**1. Every backend reinvents the same debugging wheels.** The primitives for per-layer accuracy debugging already exist in ExecuTorch — `debug_handle` is a cross-backend mechanism that survives into delegated graphs, and `devtools/inspector/` consumes it. What is missing is a *unified, automated way to activate these primitives end-to-end*. On Qualcomm, `backends/qualcomm/debugger/qnn_intermediate_debugger.py` wires the pieces together into a working per-layer accuracy flow, but at the cost of significant manual setup per invocation. On XNNPACK there is no equivalent wrapper and no accuracy-debugging guidance in the docs. Graph dumping, provenance tracking, and artifact export follow the same pattern: the infrastructure is there, but each backend either writes its own activation glue or does without. There is no shared place to contribute these tools, so each backend solves the activation problem in isolation.

**2. There is no interactive FX-graph view during the compile pipeline.** `torch.fx` is the core IR for ExecuTorch lowering, and `devtools/visualization/` already exists — but it operates on `ExportedProgram` (post-export) and launches Google's Model-Explorer as a separate web server. That is great for browsing a model's module hierarchy. It is *not* what you want when you are halfway through a sequence of passes and you need to diff the graph before and after a transform, or embed a graph view inside a broader debugging report. There is no FX-native, compile-time, embeddable graph viewer today.

**3. Debugging artifacts are not shareable as a package.** When something goes wrong, what ends up in the bug report is usually a zip of logs, a couple of CSVs, and two or three screenshots. The person on the receiving end has to reconstruct context by hand. Nothing about this is a coherent *artifact* — it's the leftovers of a failed run.

These are the three things we kept running into. Observatory exists to answer all three.

## 3. What we're aiming for

The previous section laid out three recurring problems (§2). Every backend ends up writing its own activation glue for primitives ExecuTorch already has — there's no shared place to contribute the workflow once, so each team solves the same problem in isolation. No interactive graph view lives inside the compile pipeline, so when a developer wants to watch the graph change across three lowering passes they're still dropping `print(gm.graph)` calls and comparing output in a terminal. And what usually gets attached to a bug report is a zip of loose files — logs, a couple of CSVs, two screenshots — not a single coherent artefact the person on the other end can open in one step.

Ask what a framework answering all three would have to do, and the shape falls out quickly. It would need to be shared and extensible, so that every backend plugs into the same core in the same way — no forks, no reinvention. It would need a graph viewer that embeds inside a broader debugging report rather than launching its own browser tab or requiring a separate server behind it. And it would need to produce a single file the recipient can open, not a folder they have to reconstruct.

Those three are the requirements. They narrow the design space sharply; what follows is the narrowing, a step at a time. We start with the bluntest thing that could work and let each unmet constraint force the next feature. By the time we run out of constraints, the architecture is assembled. Each step closes with a small picture; each picture is the previous one plus one new piece; the final picture is the whole system at a glance. A later chapter revisits each commitment and shows how it's wired in code (§6).

*A zero-friction way in for existing scripts.*

Most backends already have working scripts that do the export, quantisation, and lowering they care about. Forcing a contributor to edit those scripts before they can debug them would be the first of the three problems — backends writing their own glue — sneaking right back in. But sometimes a developer does need precise control: two specific collection points, a custom calibration dataset, only one analysis enabled. So we give the framework two ways in. The first is a **command-line wrapper** that sits in front of any existing script with no code change: you prefix the script invocation with `python -m executorch.devtools.observatory`, pass through your script's arguments, and the debugger does the rest. The second is a **Python `with`-block** — Python's scoped-setup construct that runs setup code when a block is entered and teardown code when it's exited — which lets a developer flip the debugger on for a few lines of their own code and off again afterwards. Both paths enter the same scope, which we'll call the **debugging context**.

```
 user's script (unchanged) ──► [CLI wrapper] ─┐
                                              ├──► [Debugging Context]
 python `with Observatory.enable_context():` ─┘
```

*Flipping debugging on for a scope, then off again cleanly.*

Inside that scope, we want to capture the graph at every standard point in the ExecuTorch pipeline — the functions that prepare a model for quantisation (`prepare_pt2e`), convert it (`convert_pt2e`), lower it to the edge dialect (`to_edge_transform_and_lower`), and record programs for later inspection (the `ETRecord.add_*` family) — and we want this to happen without the user annotating any of those calls. The technique is called **monkey-patching**: we temporarily replace those pipeline functions with wrappers of our own that (a) forward the call to the original, and (b) quietly hand the returned or passed-through object to the debugger for recording. When the debugging scope ends, we restore the originals. That restoration is important: if anything goes wrong inside the scope — an exception, an early exit — the scope's exit handler still runs, the originals still come back, and the next caller of those functions sees them behaving exactly as before. We also expose one manual entry point, a single function call named `Observatory.collect(name, artifact)` that any user code can make to hand a named Python object directly to the debugger for recording — useful when the interesting moment isn't at one of the standard pipeline functions.

```
 [CLI wrapper] / [`with` block]
               │
               ▼
 [Debugging Context]
   on_enter  ──► install patches ─► prepare_pt2e, convert_pt2e,
                                    to_edge_transform_and_lower,
                                    ETRecord.add_*
   on_exit   ──► restore originals

 Observatory.collect(name, artifact)  ──┐  (manual path)
 patched entry points                  ──┴──► record artifact
```

*Patching and collecting are the backend's problem, not the framework's.*

Different backends care about different moments. One wants to capture the graph just before its delegate partitioner runs; another wants the output of a vendor-specific quantiser; a third wants to snapshot every device-shell command and its log. If the framework itself knew about all of those moments, we'd be right back in the first problem — the framework would be a grab-bag of backend-specific code, and adding a new backend would mean forking it. So we push both the patching logic and the collecting logic out into an extension unit. We call each extension unit a **lens** — a small Python class that knows how to capture one kind of debugging data (a graph, a log line, a profiling measurement) and how to turn it into something the final report can show. Each lens implements two lifecycle hooks — one that installs its patches when the debugging context opens, one that restores them when it closes — and one capture hook that receives each recorded object and decides whether it cares. Backends declare which lenses they want active in a short entry-point script; nothing about a backend's lens has to be understood by the framework's core.

```
 [Debugging Context]
       │
       ├── on_enter  ─► each Lens.on_session_start → installs its patches
       └── on_exit   ─► each Lens.on_session_end   → restores its patches

 captured artefact ─► Lens.observe(artefact)  (each lens filters by type)
```

*The framework doesn't care what a captured thing is; it only cares that the lens can turn it into JSON.*

What flows between the lens and the framework? A captured object — we'll call it an **artefact**, meaning any Python object the debugger might want to look at: a `GraphModule` (PyTorch's data structure for a network represented as a walkable graph of operations), a log entry, a profiling measurement, an on-device snapshot. And the consumers of the captured material aren't only human reviewers — they're CI systems that archive every nightly run, regression trackers that diff two archives, AI triage pipelines that want to read the captured material programmatically. So we make two commitments. The `collect` function is deliberately **type-agnostic**: its signature is `collect(name, artifact)` with no constraint on the artefact's type. Each lens decides whether it cares by type-checking the artefact inside its capture hook and returning nothing for the kinds it doesn't recognise. And each lens converts whatever it captured — its raw observation — into a **JSON-serialisable record**: a shape that can be written out as plain-text JSON and read back later by any consumer, without re-running the compile pipeline. JSON becomes the canonical representation of the run.

```
 Observatory.collect(name, artifact: Any)
       │
       ▼
 each Lens:  observe(artifact) ─► digest(obs) ─► JSON record
       │                                          │
       ▼                                          ▼
                               [JSON record store: R1, R2, R3, ...]
```

*Debugging doesn't stop at writing things to disk.*

Capturing and storing records is the start of a debugging workflow, not the end. The questions a developer actually asks are *what changed between these two snapshots?*, *which operator lost the most accuracy after quantisation?*, *which line in the device log matches the error we saw last week?*, *did last night's nightly regress against the one from three nights ago?* — and all of those run over records that have already been captured. We name this split explicitly: four things the framework has to do well, which we call the **four pillars — collect, store, analyse, visualise** — grouped into a **runtime stage** (collect + store, which happens live while the debugging context is open) and an **offline stage** (analyse + visualise, which can run anywhere, anytime, over either a freshly captured set of records or a JSON archive from a previous run). A regression view of last week's CI result against tonight's is just the offline stage running over two archived record sets — no re-observation required.

```
 ── RUNTIME STAGE ─────────────│── OFFLINE STAGE ──────────────
  Collect   ─►   Store         │   Analyse   ─►   Visualise
  observe        digest (JSON) │   analyse        frontend
                               │   (records,       (blocks)
                               │    config)
                               │
 ... or load archived JSON ────┤ (re-analyse / regression compare
                               │  without re-observation)
```

*The offline stage sees every record at once and produces both overlays and summaries.*

To cover the questions above, the offline stage of a lens has to receive every captured record from the run, not one at a time. A lens implements an `analyse` hook that takes the entire set of records (optionally drawn from more than one run) together with its own configuration, and returns a structured result that combines three kinds of output: a global summary that spans the run, per-record overlays that attach to individual captured artefacts, and cross-record comparisons that pair records up. And because the rendered output is heterogeneous — some lenses want to show a table of numbers, others a fragment of pre-formatted HTML, others an interactive graph, others a custom JavaScript widget — the lens ends by declaring which display pieces it wants using a short vocabulary: a **table block**, an **HTML block**, a **graph block**, or a **custom block**. A single-HTML renderer reads those declarations and turns them into the final report; the same declarations serialise directly into JSON for consumers that don't need rendered output.

```
 [JSON records: R1, R2, R3, ...]
       │
       ▼
 Lens.analyse(records, config) ─► AnalysisResult
       │                           ├── global summary
       │                           ├── per-record overlays
       │                           └── cross-record comparisons
       ▼
 Lens.get_frontend_spec() ─► [TableBlock | HtmlBlock | GraphBlock | CustomBlock]
                               │
                               ├──► self-contained HTML (reviewer)
                               └──► canonical JSON        (CI / AI / archive)
```

*Put the six steps together and this is Observatory.*

```
┌────────────────────────────────────────────────────────────────────────┐
│  ENTRY                                                                  │
│   [CLI wrapper]    ─┐                         [`with` block]  ─┐        │
└─────────────────────┼──────────────────────────────────────────┼───────┘
                      ▼                                          ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       [Debugging Context]                               │
│   on_enter ─► Lens.on_session_start × N  ─► install patches             │
│               (pipeline entry points + backend-registered patches)      │
│   on_exit  ─► Lens.on_session_end   × N  ─► restore originals           │
└─────────────┬──────────────────────────────────────────────────────────┘
              │                                               ▲
              ▼  (runtime stage: Collect + Store)             │
   Observatory.collect(name, artifact: Any)  ◄── manual path ─┘
              │
              ▼
   each Lens:  observe(artifact) ─► digest(obs) ─► JSON record
              │
              ▼
   [JSON record store: R1, R2, R3, ...]   ◄── (or: load archived JSON)
              │
              ▼  (offline stage: Analyse + Visualise)
   Lens.analyse(records, config)  ─►  AnalysisResult
              │
              ▼
   Lens.get_frontend_spec() ─► [TableBlock | HtmlBlock | GraphBlock | CustomBlock]
              │
              ├──►  self-contained HTML   (reviewer / community / issue attachment)
              └──►  canonical JSON        (CI archive / AI triage / regression input)
```

Every element of that picture was put there by one of the three requirements. The shared entry surface and the lens-based extension model are the *shared and extensible* requirement. The context-scoped patching and the type-agnostic `collect` fall out of *no code change to existing scripts*. And the JSON-first data flow with single-file HTML rendering is what *one file the recipient can open* becomes in practice.

*One piece we haven't assembled yet: the graph view.*

Every Observatory report has an interactive graph view at its centre — it's where per-operator accuracy overlays live, it's what the **compare mode** (two captured graphs side by side with linked highlighting across them) stacks next to each other, it's the piece a reviewer spends the longest on. That viewer is its own small system with its own constraints. We built it the same way: start with the bluntest thing that could work, let each unmet constraint force the next feature. The viewer lives alongside Observatory in the devtools tree, but it's not tied to it — it's usable by anyone working with `torch.fx` graphs. We call it `fx_viewer`.

*The viewer has to live inside a single HTML file with no server behind it.*

The report Observatory produces is a single HTML file that someone attaches to an email, drops into a chat thread, or uploads to an issue tracker — so the viewer that renders each captured graph has to run entirely in the browser with no process alongside it. There's already an alternative in the devtools tree: `devtools/visualization/`, which forwards graphs to Google's interactive graph-browsing tool (Model-Explorer) by launching a local web server and opening a browser tab against it. That model is fine for post-export structural browsing but doesn't embed into a broader report — the viewer needs its own tab and its own process. For a debugging report that lives as a single file, the viewer has to be pure client-side. Everything it needs to render lives inside the HTML; the only build-time dependency we require is a pure-Python graph-layout library called `fast-sugiyama`, which brings nothing else with it.

```
 report.html (self-contained, single file)
     │
     ▼
 opens in any browser ─► viewer renders inline (no server, no auth)
```

*Making a large graph render instantly means doing most of the work at build time.*

A single report can carry dozens of graphs, each with thousands of nodes. If the viewer tried to lay the graph out dynamically when the reader opens the file, it would have to pull in a JavaScript layout library — slow to download, slow to run — and then build one DOM element per node — slow to render. So we do the expensive work ahead of time, during the report's build step, rather than in the browser. We extract the graph (nodes, edges, input/output shapes, metadata), and we use a classic graph-drawing algorithm called **Sugiyama layout** — the one that produces clean, layered, top-down diagrams — to compute exact `(x, y)` coordinates for every node and an explicit routing for every edge. That information is written into the JSON payload that ships inside the HTML. At view time, the JavaScript reads the payload and paints straight onto the browser's pixel-drawing surface, the `<canvas>` element — fast enough to draw thousands of nodes per frame, with no DOM element per node and no layout computation. A typical multi-graph report stays under roughly a megabyte after gzip.

```
 BUILD TIME:  FX GraphModule
                   │
                   ├── extract: nodes, edges, shapes, metadata
                   └── compute: Sugiyama layout (x, y + edge routing)
                   │
                   ▼
          [JSON payload]  ─────────► embedded into report.html

 RUN TIME:   report.html ─► JS reads embedded JSON ─► Canvas draw
                                                     (pan, zoom, minimap, search)
```

*Every lens gets its own transparent overlay on top of the base graph.*

A lens that measures per-operator accuracy wants to paint each node a shade that corresponds to its accuracy score. A lens that records which operator went to which backend partition wants to paint nodes by partition label. A profiling lens wants to show a timing number next to each node. None of those lenses should need the viewer to know about them. So the graph payload carries a **base layer** — nodes, edges, default colouring — plus any number of **extension layers**. An extension layer is an optional transparent overlay contributed by a lens: its own per-node data, its own colouring rule, its own node labels and tooltips, stacked on top of the base graph. The reader can toggle layers on and off in the viewer UI. And when two captured graphs are shown side by side in compare mode — the viewer's paired-graph view, where clicking a node in one graph highlights the same node in every other graph being shown — each extension layer can declare a **sync key**: a piece of metadata saying *"this node before the pass and this node after the pass are the same node"*, so the cross-graph highlighting knows how to pair them even after fusion or decomposition has renamed the nodes.

```
 [JSON payload]
       │
       ├── base layer         (nodes, edges, default coloring)
       ├── extension layer 1  (e.g. per_layer_accuracy — color + labels + sync key)
       ├── extension layer 2  (e.g. partition assignment)
       └── ... N layers

 Canvas runtime:
       ├── toggle layers on/off
       ├── info-panel merges per-node data across active layers
       └── compare mode: N-way sync via extension sync keys
```

*The viewer is independent of Observatory; Observatory is just its first consumer.*

`fx_viewer` is useful on its own. Any developer working with `torch.fx` graphs benefits from a dependency-free raw-graph renderer they can drop into a self-contained HTML file. So we ship it as an independent subpackage inside `devtools/`, with its own Python API for exporting a graph and its own JavaScript API for rendering and extending. Observatory's graph-rendering lens is one consumer of `fx_viewer` among potentially many; a developer who wants to throw any `GraphModule` into an HTML file and email it to a colleague can use `fx_viewer` directly without ever touching Observatory.

```
 devtools/fx_viewer/          (standalone, reusable)
      │
      ├── FXGraphExporter (Python)
      ├── GraphExtension  (Python)
      └── templates/      (JS: canvas, compare, search, minimap)
      │
      ├────────► Observatory's `graph` lens / GraphBlock
      │
      └────────► external user: `FXGraphExporter(gm).export_html(...)`
```

*Put the four steps together and this is `fx_viewer`.*

```
 BUILD TIME
 ──────────
 FX GraphModule                      Observatory lenses (analyse stage)
        │                                      │
        ├─► extract structure                  └─► contribute extension layers
        ├─► compute Sugiyama layout              (color rules, node data, sync keys)
        │                                      │
        └────────────┬──────────────────────────┘
                     ▼
          [single JSON payload] ──► embedded into report.html

 RUN TIME
 ────────
 report.html (opened in any browser)
        │
        ▼
 Canvas-based JS runtime (fx_viewer/templates/)
        ├── pan / zoom / minimap / fuzzy search
        ├── layer toggle  (base + N extensions)
        ├── info-panel    (merged per-node data across active layers)
        └── compare mode  (N-way cross-graph sync via extension sync keys)
```

The viewer's architecture — embed-everything JSON, pre-computed layout, Canvas runtime, extension-layer overlays, standalone reuse — follows directly from the three constraints it has to meet: it has to fit inside a single HTML file that travels on its own, it has to render very large graphs without feeling slow, and it has to carry overlays contributed by lenses the viewer itself knows nothing about.

*And here is the boundary we keep.*

A few things Observatory deliberately does not try to be. It is not a replacement for the existing inspection primitives in the devtools tree — the `Inspector` API, the on-device capture infrastructure (`ETRecord` / `ETDump`), the calibration-and-packaging format (`bundled_program`) — Observatory *consumes* those primitives through its lenses rather than reimplementing them. It is not a replacement for `devtools/visualization/`, which serves a different job: browsing the structure of an exported model with module-hierarchy collapse, powered by Model-Explorer as an external app. A later chapter on how Observatory sits alongside existing devtools walks through the differences case by case (§7), and a companion reference document has the feature-by-feature comparison. Observatory adoption is not a mandate; each backend decides whether and when to ship its own debugger entry point. And the shipped Observatory report in this proposal is deliberately a *post-hoc artefact* — the run finishes, the file is produced, the reviewer opens it later — rather than a live dashboard updating in real time. A live-dashboard variant built on the same `fx_viewer` foundation is a natural next step rather than a position we're staking out against (§9).

## 4. A demo — zero-config per-layer accuracy debugging

Before we dig into how it works, let's walk through a full end-to-end example on a real model. One command in, one HTML file out — and everything interesting about Observatory and `fx_viewer` visible inside.

> **Scope note.** The per-layer accuracy shown here is **compile-time**: the `per_layer_accuracy` lens runs CPU simulation across graph snapshots captured at different lowering stages and compares them against a float anchor. Runtime / delegated-graph accuracy (the question `qnn_intermediate_debugger.py` answers — comparing CPU against the actual on-device execution inside a delegate) is out of scope for this PR and targeted for a follow-up lens (see §9).

### 4.1 Setup

```bash
# requires python >= 3.11
pip3 install 'fast-sugiyama[full]'
```

### 4.2 The command — zero-config, one flag for deeper analysis

Wrap any existing AOT script with the backend-specific Observatory CLI. No code change to your script. The default lenses (metadata, stack trace, graph, pipeline-hook capture) are always active; opt into per-layer accuracy with a single flag.

```bash
# XNNPACK — aot_compiler.py auto-detected as module via __init__.py
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2

# Qualcomm
python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lense_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

[[MEDIA: png — side-by-side terminal: default run vs `--lense_recipe=accuracy`]]

Pre-generated reports from running this exact flow on a matrix of models:

- XNNPACK: [mv2] · [add] · [other models …]
- Qualcomm: [albert] · [bert] · [distilbert] · [eurobert] · [inception_v3] · [inception_v4] · [mobilenet_v2] · [mobilenet_v3] · [roberta] · [torchvision_vit]

*(Links populated from `generated_reports/` at submission time.)*

### 4.3 What you get — a standalone HTML report

Observatory emits a **self-contained HTML file** — one file, no server, no login, no external service. It opens in any modern browser; you can attach it to an issue, a PR, or an email.

[[MEDIA: png — the generated HTML file being opened in a browser, run dashboard visible]]

Here is what is inside.

**Run dashboard (landing page).** Per-run metadata — command line, environment, input model. Each lens can contribute its own section to this page.

[[MEDIA: png — run dashboard, annotated: metadata section, command capture, env]]

**Records and diff labels (left panel).** The left panel lists **records** — one per Observatory collection point (think: breakpoint). Between adjacent records, **diff labels** summarize what changed (node-count delta, PSNR change). Each lens can insert its own diff-label content.

[[MEDIA: png — left panel showing records + diff labels, annotated]]

- Click a **record** → single-record view opens in the main area.
- Click a **diff label** → 2-record compare view.
- Click **Select** → N-record compare view.

[[MEDIA: gif — clicking record in left panel → single view opens, ~4s]]

[[MEDIA: gif — clicking diff label → side-by-side compare view, ~5s]]

[[MEDIA: gif — select-mode → multi-record comparison, ~5s]]

**The interactive FX graph — the core of `fx_viewer`.** The main area renders the FX graph for the current record with pan, zoom, minimap, and fuzzy search. N-way synchronized compare means clicking a node in one graph highlights the matching node in every other graph being compared — sync driven by `debug_handle` / `from_node`.

[[MEDIA: gif — compare mode with cross-graph node sync, ~8s]]

**Per-layer accuracy as a color overlay.** With `--lense_recipe=accuracy`, per-operator PSNR / cosine / MSE are computed and rendered as a color gradient on the graph. Worst-accuracy operators stand out visually; click any node to see its full metric breakdown in the info panel. A merged per-layer metrics table sits alongside the graph.

[[MEDIA: gif — graph with per-layer PSNR color overlay + node selection → info-panel metrics, ~6s]]

**Lenses active in this demo.** Full descriptions in reference.md §G.

| Lens | Role |
|---|---|
| `metadata` | Run metadata on the dashboard |
| `stack_trace` | User call stack at each collection point |
| `graph` | Interactive FX graph view (powered by `fx_viewer`) |
| `accuracy` | Overall per-record accuracy metrics |
| `per_layer_accuracy` | Per-operator PSNR / cosine similarity overlaid on the graph |
| `pipeline_graph_collector` | Auto-captures graphs at pipeline hooks during a session |
| `graph_color` | Coloring rules contributed to the graph view |

That's the whole end-to-end flow from one command. Next we'll look at the other two ways you can invoke Observatory — for when the CLI is too coarse for what you want.

## 5. Three ways to use it

The CLI in the demo is the zero-code-change path. It is the right tool for a particular kind of debugging, but not for every kind. Observatory exposes the same framework through three invocation surfaces — each one matches a different debugging context.

### 5.1 The CLI — for QA, CI, and community issue reporting

You've just seen this one. You wrap an existing AOT script, default lenses are active out of the box, and you get a single HTML file at the end.

```bash
# Generic (framework lenses only)
python -m executorch.devtools.observatory \
    --output-html run.html \
    your_script.py --your-args

# Backend-specific with opt-in lens recipe
python -m executorch.backends.xnnpack.debugger.observatory \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize
```

**Use this when** you are filing a bug report, reproducing a CI failure, or handing work off across teams. The CLI costs nothing to adopt — no code change to your script — and produces a single artifact that anyone can open.

### 5.2 The Python context manager — for targeted developer debugging

Now imagine a different situation. You are deep in a compiler pass you are writing yourself. You want to compare graphs at exactly three points, with exactly one lens enabled, using your own small reproducer dataset. The CLI's zero-config mode is too coarse. What you want is direct control of collection points and lens config.

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

**Use this when** you are iterating on a compiler pass, comparing graph states around a specific transform, running with a custom dataset, or passing custom configs into a lens. Monkey patches installed by lenses live only for the `with`-block's lifetime (see §6 and reference.md §A for why that matters).

### 5.3 The `@observe_pass` decorator — for pass-centric debugging

And one more variation. If you are tuning a whole pass pipeline and you want every pass's before-and-after graph captured automatically, wrap the passes once with a decorator.

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.pass_base import ExportPass
from executorch.exir.pass_manager import PassManager

@observe_pass
class MyPass(ExportPass):
    def call(self, gm):
        ...

pm = PassManager()
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enable_context():
    pm._transform(graph_module)

Observatory.export_html_report("pass_debug.html")
```

**Use this when** you are building or tuning a pass pipeline and you want to measure the effect of each pass in isolation.

### 5.4 Where collection points come from

Regardless of which surface you use, the collection points that end up in your report come from three sources:

- **Automatic pipeline hooks** (via the `pipeline_graph_collector` lens): standard ExecuTorch entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`, `ETRecord.add_exported_program`, `ETRecord.add_edge_dialect_program`) are monkey-patched for the duration of the Observatory session.
- **The pass decorator** (`@observe_pass`): wraps any `PassBase` subclass or instance.
- **Manual calls** (`Observatory.collect(name, artifact)`): explicit collection anywhere in your code.

The patches exist only during an active Observatory context. They are installed in `Lens.on_session_start` and restored in `Lens.on_session_end` — which brings us to how the framework actually works.

## 6. Under the hood

The previous chapter walked through the architecture one step at a time. This chapter revisits each commitment and shows how it is wired in code — the Lens protocol that carries both the monkey-patch logic and the collection logic, the JSON-as-canonical data flow that splits runtime from offline work, and the generalisation pattern that lets new artefact types (logs, profiles, on-device snapshots) slot in without touching the core.

### 6.1 Architecture

Here is the shape of the system.

```
┌──────────────────────────────────────────────────────────┐
│                  devtools/observatory/                    │
│                                                           │
│  Runtime            Lens Protocol         Report Engine   │
│  ┌──────────┐     ┌──────────────────┐  ┌─────────────┐  │
│  │ collect  │     │ setup            │  │ HTML / JSON │  │
│  │ analyze  │◄───►│ on_session_start │  │ export      │  │
│  │ export   │     │ observe          │  └─────────────┘  │
│  └──────────┘     │ digest           │                    │
│                   │ analyze          │                    │
│                   │ frontend         │                    │
│                   │ on_session_end   │                    │
│                   └──────────────────┘                    │
│  Generic Lenses: graph · metadata · accuracy ·            │
│                  per_layer_accuracy · stack_trace ·       │
│                  pipeline_graph_collector · graph_color   │
│                                                           │
│                  devtools/fx_viewer/                      │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Python: exporter · extension API · color rules    │   │
│  │  JS runtime: canvas · minimap · search · compare   │   │
│  └────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
┌────────┴────┐    ┌─────────┴──────┐    ┌────────┴──────┐
│ QNN CLI     │    │ XNNPACK CLI    │    │ ARM / …       │
│ QNN lenses  │    │ XNNPACK lenses │    │ backend       │
│ backends/   │    │ backends/      │    │ lenses        │
│ qualcomm/   │    │ xnnpack/       │    │               │
│ debugger/   │    │ debugger/      │    │               │
│ observatory │    │ observatory    │    │               │
└─────────────┘    └────────────────┘    └───────────────┘
```

[[MEDIA: png — rendered version of the diagram above]]

A **Lens** is a Python class whose methods hook into a fixed set of stages. Two of those stages, `on_session_start` and `on_session_end`, run at context entry and exit — they are the canonical place for installing and removing monkey patches. This is how `pipeline_graph_collector` instruments the ExecuTorch pipeline without mutating anyone's source code: it patches `prepare_pt2e`, `convert_pt2e`, and friends when you enter an Observatory context, and unpatches them on the way out. The other stages (`observe`, `digest`, `analyze`, `frontend`) produce and render the lens's data. Lenses contribute graph overlays through `fx_viewer`'s `GraphExtension` API — per-node info data, labels, coloring, sync keys. The full protocol, extension API, and a worked example are in **reference.md §A–§C**.

### 6.2 JSON as the canonical format

The second idea is a data-flow decision. Observatory treats **JSON as the canonical report format**. The HTML is a *rendering* of the JSON, not the other way around. This is reflected directly in the Lens protocol: `digest()` returns JSON-serializable data, `analyze()` takes JSON-shaped records as input, and `frontend()` produces HTML blocks from that JSON.

```
                           ┌─► stored JSON (archive, DB, AI consumer)
observe ─► digest (JSON) ──┤
                           └─► analyze (JSON in) ─► frontend (JSON → HTML)
```

Three consequences fall out of this.

- **Machine- and AI-friendly by default.** A stored JSON report is queryable, diff-able, and embeddable into databases or dashboards. An automated triage pipeline does not have to scrape HTML or re-run the compile pipeline — it reads JSON.
- **Rendering without re-execution.** `analyze()` and `frontend()` run off the stored JSON. Regenerating the HTML after a template change, a styling update, or a new version of a lens does not require re-running the AOT compile or the accuracy evaluation.
- **Cross-time regression analysis falls out for free.** Imagine a CI system running Observatory nightly on a fixed set of models, archiving each run's JSON. When a regression signal fires, a comparison lens can take the JSONs from *two* nightlies and produce a regression HTML showing what changed — without re-running either nightly.

That last one is worth spelling out concretely.

```bash
# Nightly CI job — archive the JSON, HTML not required
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-json nightly/${DATE}/mv2.json \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize

# Later — produce a regression HTML from two archived JSONs,
# without re-running the compile or accuracy eval
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html
```

Because each lens's digest is structured JSON, the comparison lens reasons about specific fields — PSNR deltas, node-count changes, partition differences — without parsing logs or HTML.

### 6.3 Extending beyond graphs — an ADB-log lens sketch

The demo in §4 captures FX graphs, but Observatory is deliberately artifact-agnostic. `Observatory.collect(name, artifact)` accepts any Python object, and each lens decides whether it cares. This is how a backend could add, say, an ADB-log lens — or a QParam dump, or an ETDump snapshot — without touching Observatory core. The same protocol that handles a `GraphModule` handles a `LogEntry`.

Four design ideas make this work, and all four are in the shipped framework today.

**1. `collect()` accepts any Python object.** The signature is `collect(name: str, artifact: Any)` — no type constraint. Graph lenses receive a `GraphModule`, a log lens receives a `LogEntry`, a profiling lens receives a timing snapshot. The framework itself never introspects the artifact.

**2. Each lens self-filters on type.** Lenses `isinstance()`-check the artifact in `observe()` and return `None` when they don't care. This is exactly what `GraphLens` already does in `devtools/observatory/lenses/graph.py` — it returns `None` unless the artifact is a `GraphModule` or an `ExportedProgram`. A log lens filters on its own type. The two lenses coexist in the same session without knowing about each other.

**3. Monkey-patching in `on_session_start` / `on_session_end`.** A lens that wants to auto-collect without user code changes patches the relevant helper on context entry and restores it on exit. `pipeline_graph_collector` does this for `prepare_pt2e`, `to_edge_transform_and_lower`, and `ETRecord.add_*`. An ADB-log lens would do the same for the ADB helper.

Put those three together and a log-collecting lens looks like this:

```python
from dataclasses import dataclass
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.interfaces import Lens

# The lens defines its own artifact shape — Observatory doesn't care what it is.
@dataclass
class AdbLogEntry:
    source: str        # e.g., "logcat", "dmesg"
    content: str
    rc: int

class AdbLogLens(Lens):
    _original = None

    @classmethod
    def on_session_start(cls, context):             # idea 3 — install patch
        from executorch.backends.qualcomm.runtime import adb_helper
        cls._original = adb_helper.run_inference

        def patched(cmd, **kw):
            result = cls._original(cmd, **kw)
            logcat = adb_helper.fetch_logcat(since=result.started_at)
            Observatory.collect(                     # idea 1 — any Python object
                f"adb_log/{cmd.label}",
                AdbLogEntry("logcat", logcat, result.rc),
            )
            return result

        adb_helper.run_inference = patched

    @classmethod
    def on_session_end(cls, context):               # idea 3 — restore patch
        from executorch.backends.qualcomm.runtime import adb_helper
        adb_helper.run_inference = cls._original
        cls._original = None

    @classmethod
    def observe(cls, artifact, context):             # idea 2 — self-filter
        if not isinstance(artifact, AdbLogEntry):
            return None
        return {"source": artifact.source,
                "lines": artifact.content.splitlines(),
                "rc":    artifact.rc}
```

With `AdbLogLens` registered, the user writes no ADB-specific code — the patch fires inside any Observatory context, every on-device inference produces a log record, and `graph`, `accuracy`, and `metadata` all see the `AdbLogEntry` too and all return `None`. One protocol, many artifact shapes.

**4. Nested contexts scope configuration per phase.** Lens config is stacked: each `Observatory.enable_context(config=...)` merges into the outer config and is popped on exit. This lets the user say "for *this* phase, flip which lenses are active, or change their settings".

```python
with Observatory.enable_context(config={"accuracy": {"dataset": my_set}}):
    # Compile-time phase: graph + accuracy lenses work as in §4.
    gm = compile_and_lower(model)
    Observatory.collect("edge", gm)

    # Runtime phase: disable accuracy (not relevant on device), enable adb_log.
    with Observatory.enable_context(config={
        "accuracy": {"enabled": False},
        "adb_log":  {"enabled": True, "fetch_dmesg": True},
    }):
        run_on_device(edge_program)     # AdbLogLens patch fires automatically

    # Outer context resumes — accuracy re-enabled, adb_log reverts to outer.
    Observatory.collect("post_device", gm)

Observatory.export_html_report("run.html")
```

The four ideas compose cleanly: any artifact can flow through `collect`, lenses pick what they care about, instrumentation attaches and detaches with the context, and config nesting lets users shape exactly which lenses are active in which phase. The framework never had to learn about `AdbLogEntry` — and the same is true for future lenses collecting QParam dumps, ETDump snapshots, or size breakdowns.

With the framework in hand, let's zoom back out to see how it sits next to what's already there.

## 7. Where it fits with the devtools you already have

Observatory is not trying to displace anything in `devtools/`. It composes with the raw materials that already exist. Here is how each existing piece relates.

| Existing devtool | What it provides | How Observatory relates |
|---|---|---|
| Inspector API | Per-tensor comparison primitives (MSE, SNR, L1) | Consumed by `accuracy` / `per_layer_accuracy` lenses |
| ETRecord / ETDump | Runtime event and tensor capture | Future runtime lenses will consume these |
| bundled_program | Calibration data + model packaging | Used as input source for accuracy lenses |
| `devtools/visualization/` | `ExportedProgram` structural browser (Model-Explorer, web server) | Complementary — post-export hierarchy browsing, not in-workflow FX graphs; no HTML embed, no debugger-info API. See reference.md §B |
| `devtools/backend_debug/delegation_info.py` | Prints delegate partition assignment | Candidate input for a future `partition` color layer on `graph` |
| `devtools/pte_tool/diff_pte.py` | `.pte` file diff | Candidate future `pte_diff` lens, operating on archived JSON |
| `devtools/size_analysis_tool/` | Model size breakdown | Candidate future `size` lens |
| Per-backend scripts (QNN debugger, `XNNProfiler.cpp`, ARM shell scripts, TOSA notebook) | Backend-specific accuracy / profiling / graph dumping | Subsumed, where applicable, as lenses — see §8 |

`fx_viewer` is the new piece we are introducing alongside Observatory. It is the component that powers Observatory's graph block — a dependency-free, standalone, embeddable HTML renderer for raw FX graphs with compare mode and a Python extension API. Reference.md §C has the details.

## 8. The bigger picture — one framework, many debugging workflows

Now let's take a step back. The strongest argument for Observatory isn't any one feature — it's that the *same* framework covers debugging workflows every backend currently solves in isolation. The table below walks through the common workflows: the left column is a keyword plus a one-line description of the question, the middle is what engineers do today across backends, and the right is how Observatory answers it. Entries tagged *shipped* are in the draft PR; *future* entries are naturally enabled by the lens protocol and are a matter of writing the lens.

| Workflow | Today's state | Observatory path |
|---|---|---|
| **Compile-time accuracy** — PSNR / cosine / MSE across lowering stages (CPU simulation) | Manual `print` + ad-hoc numeric comparison across stages; no unified flow on any backend | `accuracy` + `per_layer_accuracy` *(shipped)* |
| **Runtime / delegated accuracy** — CPU vs on-device inside a delegate | QNN `backends/qualcomm/debugger/qnn_intermediate_debugger.py` (works, but significant manual setup); no XNNPACK equivalent; `debug_handle` + `devtools/inspector/` primitives available but not wired up end-to-end | Future lens — port `qnn_intermediate_debugger` logic into an Observatory lens |
| **Graph-state capture** — snapshots at each pipeline stage | `print(gm.graph)`; per-backend log dumps; ARM `backends/arm/scripts/TOSA_minimal_example.ipynb` | `pipeline_graph_collector` + `graph` *(shipped)* |
| **Pass diff** — before / after any compile pass | Text diff; manual side-by-side print | `@observe_pass` + `graph` compare mode *(shipped)* |
| **Collection provenance** — which user call site produced this record | Manual log annotation | `stack_trace` — captures the user's Python call stack at each `Observatory.collect()` *(shipped)* |
| **Delegate partition inspection** — which ops went to which backend | `devtools/backend_debug/delegation_info.py`; per-backend printouts | Future `partition` color layer on `graph` |
| **Quantization parameter audit** — per-node QParams | Manual `node.meta` inspection; per-backend quantizer scripts | Future `qparams` lens (info-panel + color layer) |
| **Artifact diff** — comparing two `.pte` files | `devtools/pte_tool/diff_pte.py` | Future `pte_diff` lens — operates on archived JSON |
| **Size / memory breakdown** — per-layer, per-partition | `devtools/size_analysis_tool/` | Future `size` lens |
| **Op-level runtime profiling** | QNN QAIRT QHAS / optrace; XNNPACK `backends/xnnpack/runtime/profiling/XNNProfiler.cpp` (C++, on-device) | Future runtime lens, fed by ETDump |
| **Context sharing** — reviewer, QA, community | Zip logs + CSVs + screenshots | One HTML + one JSON |

The mechanism that makes this one framework is genuinely small: a Lens protocol with context-manager hooks and four content stages (`observe → digest → analyze → frontend`), plus a registration point per backend. Every workflow above can be expressed as one or more lenses. A new backend gets the surrounding infrastructure — CLI, report shape, compare mode, graph view, JSON archive — for free.

## 9. Where we go from here

The draft PR ships the core framework, `fx_viewer`, the seven shipped lenses listed above, and backend CLIs for Qualcomm and XNNPACK. All accuracy work in the demo is **compile-time** (CPU simulation across lowering stages). Beyond that, here is what we think comes next.

- **Runtime / delegated-graph accuracy lens** — port the logic in `backends/qualcomm/debugger/qnn_intermediate_debugger.py` into an Observatory lens that uses `debug_handle` + `devtools/inspector/` primitives to compare CPU output against on-device execution inside a delegate, with zero manual wiring. This is the single most-requested follow-up and the natural extension of §4's compile-time flow.
- **Runtime-side lenses** using Inspector API and ETDump (performance, memory, crash analysis).
- **Non-FX graph formats** (PyTorch graph, QNN graph, TOSA) as first-class `fx_viewer` exporters.
- **Porting existing backend tools to the lens protocol** — QNN QHAS profiling, XNNProfiler aggregation, QParams audit, delegation info as a color layer, `.pte` diff as a JSON-consuming lens.
- **Device-side profiling lenses** — ADB capture, on-device perf traces.
- **Nightly-regression CI integration** — the archived-JSON + `observatory --compare` flow from §6.2, formalized as a devtools CI recipe.
- **Live debugging dashboard powered by `fx_viewer`** — the viewer's standalone HTML, JSON-driven state, and Python + JS extension APIs make it a natural foundation for a live dashboard, not just a post-hoc report. A future mode could stream collection events from a running Observatory session into a long-lived `fx_viewer` instance for real-time inspection — useful for iterative pass development and long-running compile pipelines.

Some of these are natural next PRs. Others depend on how the protocol stabilizes and who in the community picks them up — which is, in the end, the real question this RFC is asking.

## 10. Reference material

Everything structural, API-level, or policy-level lives in **[reference.md](./reference.md)**:

- §A — Lens protocol (full), including the JSON-as-canonical-format contract
- §B — `devtools/visualization/` (Model-Explorer) vs `fx_viewer` feature comparison
- §C — `fx_viewer` extension API (info panel, labels, coloring, sync, full example)
- §D — CLI reference (generic + Qualcomm + XNNPACK)
- §E — Directory structure (matches `~/executorch` at the draft PR)
- §F — Backend extension pattern (patches + custom lenses)
- §G — Lens catalog (shipped lenses, one-by-one)
- §H — Maintenance and collaboration strategy
- §I — Open questions
