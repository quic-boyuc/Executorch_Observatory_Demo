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

Given those three frictions, here is what we want the framework to do:

1. **Live in `devtools/` as a shared framework.** Observatory core, `fx_viewer`, and the generic lenses usable by any backend.
2. **Be backend-extensible without forking the framework.** Each backend contributes its own lenses and CLI runner.
3. **Give every backend the same report shape.** Same left panel, same compare mode, same graph view — regardless of who produced the report.
4. **Emit a single self-contained HTML file.** No server, no authentication, no external service. The artifact *is* the report.
5. **Treat JSON as a first-class format.** Machine-readable canonical output for CI archives, database storage, and AI-assisted triage. The HTML is a rendering of the JSON.

**And what we're explicitly not trying to do.** We are not trying to replace Inspector / ETRecord / ETDump / bundled_program — Observatory *consumes* those primitives. We are not trying to replace `devtools/visualization/`; it serves a different purpose (see §7 and reference.md §B). We are not mandating adoption — this is opt-in per backend. The Observatory *report* shipped in this PR is a post-hoc artifact rather than a live dashboard; a live-dashboard application built on the same `fx_viewer` foundation is a natural future direction (see §9), not a non-goal.

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

Now let's look at the mechanism behind all of this. There are really just two ideas: a small Python protocol that lenses implement, and a data-flow decision that makes JSON the canonical format rather than HTML.

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
