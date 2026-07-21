---
marp: true
theme: default
paginate: true
title: "fx_viewer RFC — Key Concepts"
---

# `fx_viewer` — Lightweight FX Graph Viewer for Compile-Pipeline Debugging

**RFC Overview Presentation**

ExecuTorch `devtools/fx_viewer/`

---

## Agenda

1. Problem: 5 Gaps in Existing Visualization
2. Solution: What `fx_viewer` Provides
3. Positioning: Complementary to Model Explorer
4. Feature Comparison Matrix
5. Live Demos
6. Future Work & Open Questions
7. **Appendix:** Observatory (RFC-B) — Motivation & Direction

---

## 1. The Problem — 5 Gaps

When debugging a compile pipeline (quantization, lowering, delegation), developers need:

| # | Gap | Impact |
|---|-----|--------|
| 1 | Cannot view more than 2 graphs at once | Lose context across 3+ compile stages |
| 2 | Cross-graph node sync requires manual mapping file | Tedious, error-prone for large models |
| 3 | Cannot overlay custom analysis on the graph | Results stuck in separate tables |
| 4 | Output requires a server to view/share | Cannot attach to GitHub issues or CI |
| 5 | Viewer cannot be modified by ExecuTorch contributors | Feature requests wait for external release |

---

## Gap 1 — N-Way Graph Compare

**Need:** View float → calibrated → quantized → edge → device graphs simultaneously

**Model Explorer:** Fixed 2-pane split view

**fx_viewer:** N-way grid in one HTML file

```python
FXGraphCompareExporter(OrderedDict([
    ("Float",     FXGraphExporter(float_gm)),
    ("Quantized", FXGraphExporter(quantized_gm)),
    ("Edge IR",   FXGraphExporter(edge_gm)),
    ("Device",    FXGraphExporter(device_gm)),
])).export_html("pipeline_compare.html")
```

---

## Gap 2 — Automatic Cross-Graph Node Sync

**Need:** Click a node in quantized graph → corresponding node highlights in float graph

**Model Explorer:** Manual mapping JSON file OR node-id match (breaks after passes)

**fx_viewer:** Automatic many-to-many sync using `from_node` metadata

```
Click "quantized_conv2d_1" in Quantized graph
  → auto-highlights "conv2d_1" in Float graph
  → auto-highlights "conv2d_1" in Edge IR graph
  → auto-highlights "conv2d_1_lowered" in Device graph
```

Sync order: `from_node_root` → `debug_handle` intersection → node id

---

## Gap 3 — Programmatic Analysis Overlay

**Need:** Color nodes by accuracy score, show metrics as labels directly on graph

**Model Explorer:** `node_data_builder` exists but limited:
- Only covers nodes exposed by the adapter (edge dialect graph)
- Requires separate JSON file + GUI upload
- Not exposed by `devtools/visualization/` wrapper
- Scoped to single graph only

**fx_viewer:** Overlay on any node, any graph, baked into HTML at export

---

## Gap 4 — Standalone HTML, No Server

| | Model Explorer | fx_viewer |
|---|---|---|
| Output | Live server session or JSON (needs server to open) | Single `.html` file |
| Sharing | Recipient must install ME | Open in any browser |
| CI integration | ❌ | ✅ Upload as artifact |
| Embeddable | ❌ | ✅ `export_js(container_id)` mounts into any DOM element |

---

## Gap 5 — In-Tree, Modifiable by ExecuTorch

| | Model Explorer | fx_viewer |
|---|---|---|
| Frontend | Angular + three.js + d3 (~50k LoC) | Plain JS on Canvas (~4.5k LoC) |
| Ownership | External (`google-ai-edge`) | In-tree (`devtools/fx_viewer/`) |
| To add a feature | Open upstream PR, wait for release | Normal ExecuTorch PR |
| Layout | Browser-side (slow on large graphs) | Python pre-computed, baked into HTML |

---

## 2. Solution Summary

`fx_viewer` fills these gaps with:

- **N-way graph grid** — any number of compile stages side by side
- **Automatic node sync** — leverages PyTorch's `from_node` metadata chain
- **`GraphExtension` overlay API** — color rules, labels, tooltips, toggleable layers
- **Standalone HTML** — one file, works offline, CI-friendly, embeddable
- **Small in-tree codebase** — ~4.5k LoC JS, no framework, no build step

---

## 3. Positioning — Complementary, Not a Replacement

| Scenario | Model Explorer | fx_viewer |
|---|---|---|
| "What does my model look like?" | ✅ | — |
| "Which ops belong to which nn.Module?" | ✅ | — |
| "What changed between ATen and Edge IR?" | — | ✅ |
| "Which layer lost accuracy after quantization?" | ⚠️ (limited) | ✅ |
| "Attach graph to GitHub issue" | — | ✅ |
| "CI graph regression check" | — | ✅ |
| "Extend viewer for my backend" | — | ✅ |

**Rule of thumb:** Model Explorer for browsing structure; `fx_viewer` for debugging across compile stages.

---

## Relationship to Arm's `executorch-extension-model-explorer`

| Dimension | Arm Extension | fx_viewer |
|---|---|---|
| Target | Deployment artifact inspection (`.pte`, ETDump latency) | Compile-time pipeline debugging |
| Graphs | Edge dialect only (single graph) | N graphs (Aten + intermediate + edge) |
| Overlay | Runtime latency from ETDump | Any data (accuracy, partition, latency) |
| Output | Requires ME server | Standalone HTML |
| Sync | N/A (single graph) | Automatic cross-pane sync |

**Complementary:** Arm extension for runtime profiling; `fx_viewer` for compile-time debugging.

---

## 4. Feature Comparison Matrix

| Feature | `devtools/visualization/` | Raw ME API | fx_viewer |
|---|:---:|:---:|:---:|
| Single graph view | ✅ | ✅ | ✅ |
| ETRecord as direct input | ❌ | ❌ | ✅ |
| Multi-graph compare | ❌ | ✅ (2) | ✅ (N) |
| Cross-graph node sync | ❌ | ✅ (manual) | ✅ (auto) |
| Per-node custom overlay | ❌ | ✅ (edge, op nodes) | ✅ (any) |
| Standalone HTML output | ❌ | ❌ | ✅ |
| No server required | ❌ | ❌ | ✅ |
| Embeddable JS API | ❌ | ❌ | ✅ |
| In-tree, modifiable | ❌ | ❌ | ✅ |
| Module hierarchy / layers | ❌ | ✅ | ❌ |
| External dependency | `model-explorer` | `model-explorer` | `fast-sugiyama` |

---

## 5. Live Demos

All demos are standalone HTML — open in any browser, no installation:

- **[MV2 XNNPACK ETRecord (2-pane)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_xnnpack/mv2_etrecord_compare_xnnpack.html)**
  Aten → Edge with backend overlay. Click any node to see sync.

- **[MV2 QNN ETRecord (3-pane)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_qnn/mv2_etrecord_compare_qnn.html)**
  Aten → Edge After Transform → Edge. Shows intermediate pass results.

- **[3-Graph Sync Demo](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/three_graph_compare/demo_3graph_compare.html)**
  Decomposition (1→many) and fusion (many→1) sync behavior.

---

## 6. Future Work & Open Questions

### Future Work
- QNN backend graph format as additional pane
- Pure-Python layout engine (replace `fast-sugiyama`)
- Runtime delegated accuracy (on-device, not just compile-time simulation)

### Key Open Questions
- Q1: Module location (`devtools/fx_viewer/` vs. nested under `visualization/`)
- Q2: Extension surface for non-FX graph formats (QNN device graph, TOSA)?
- Q3: Expose `Inspector.export_fx_viewer_html_from_graphs(...)` for standalone GraphModules?
- Q4: Stable JSON payload schema as public API?
- Q5: Formalize JS embedding API (`FXGraphViewer.create`) as stable contract?

---

<!-- _class: lead -->

# Appendix: Observatory (RFC-B)

## Modular Debugging Workflow Framework

---

## Observatory — The Problem

Backend debugging needs are **diverse and fragmented**:

| Backend team says... | Current reality |
|---|---|
| "I need per-layer accuracy analysis" | Write a custom script, results in console/CSV |
| "I need to overlay HTP profiler data" | Separate tool, separate tutorial |
| "I need to compare two runs for regression" | Re-run compiler, diff manually |
| "I need ADB logs correlated with graph nodes" | Copy-paste between terminals |

**No standard interface** → each tool is a one-off script.
**No unified output** → results scattered across console, CSV, screenshots.

---

## Observatory — Motivation vs. Existing Tools

| Need | ETRecord + Inspector API | Observatory |
|---|---|---|
| Multi-backend debug tool integration | Each backend writes its own scripts | Unified Lens interface → unified report |
| Custom analysis (accuracy, profiler, logs) | Hack Inspector API or standalone scripts | Lens defines capture/analyze/visualize |
| Cross-run comparison (regression) | Re-run compiler | Archive JSON → offline re-analyze & compare |
| Setup complexity | ETRecord + RuntimeConfig + Inspector + Visualizer | `enable Lens` → run → report generated |
| Backend-specific tool fragmentation | Independent tutorials per tool | One Lens per tool, shared interface |
| Pressure on core API | Every new need extends Inspector | Lens is opt-in plugin, core API unchanged |

---

## Observatory — Key Design Principles

1. **Does not replace ETRecord / ETDump / Inspector**
   - Uses them as data sources, does not modify their formats
   - Extra analysis results go through Lens → Archive JSON (separate schema)

2. **Lens = Plugin, not Core**
   - Backend teams own their Lenses (e.g. `backends/qualcomm/debugger/observatory/`)
   - Adding a new debug capability = adding a Lens file, not modifying core APIs

3. **Offline re-analysis**
   - Archive JSON separates raw captures from analysis results
   - Same archive can be re-analyzed with different Lens configurations

---

## Observatory — Architecture (High-Level)

```
┌─────────────────────────────────────────────────────┐
│ Observatory (coordination layer)                     │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐           │
│  │ Lens A  │  │ Lens B  │  │ Lens C   │  ...      │
│  │accuracy │  │profiler │  │ADB logs  │           │
│  └────┬────┘  └────┬────┘  └────┬─────┘           │
│       │             │             │                  │
│       ▼             ▼             ▼                  │
│  ┌──────────────────────────────────────────────┐   │
│  │ Archive JSON → Report HTML (standalone)      │   │
│  │              → with embedded fx_viewer graphs │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
       ▲ uses as data source (does not replace)
       │
┌──────┴──────────────────────────────┐
│ ETRecord / ETDump / Inspector API   │
│ (unchanged, well-specified role)    │
└─────────────────────────────────────┘
```

---

## Observatory — Where fx_viewer Fits In

When a Lens produces **graph-level** analysis (e.g. per-node accuracy scores):

1. Lens computes results during `analyze()`
2. Results are contributed as `GraphExtension` overlays
3. Observatory report engine calls `fx_viewer` to render the graph with overlays
4. Final HTML report contains interactive graph viewer embedded via JS API

**fx_viewer works standalone** — Observatory is one consumer of its embedding API.
**Observatory works standalone** — reports can contain tables/charts without graphs.

Together: Lens analysis → graph overlay → interactive standalone HTML report.

---

## Observatory — End-to-End Value (Joint Demo)

**Scenario:** Qualcomm backend, MobileNet V2, per-layer accuracy analysis

```bash
observatory run --lens accuracy examples/qualcomm/mobilenet_v2.py
```

**What happens:**
1. Observatory patches pipeline → captures graphs at each stage
2. Accuracy Lens computes per-node PSNR/MSE/cosine
3. fx_viewer renders 4-way graph grid with accuracy color overlay
4. One standalone HTML: navigate across compile stages + see which nodes lost accuracy

**Demo:** [qualcomm/mobilenet_v2 report](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html)

---

## Summary — Two Independent, Complementary RFCs

| | RFC-A: fx_viewer | RFC-B: Observatory |
|---|---|---|
| **What** | FX graph viewer | Debugging workflow framework |
| **Core value** | N-way compare + auto sync + overlay + standalone HTML | Unified Lens interface + archive + report |
| **Independent?** | ✅ Standalone Python API | ✅ Works with tables/charts only |
| **Together** | Observatory embeds fx_viewer graphs with Lens-produced overlays |
| **Does not replace** | Model Explorer | ETRecord / Inspector API |

---

## Thank You

- **RFC-A (fx_viewer):** [GitHub Issue #21068](https://github.com/pytorch/executorch/issues/21068)
- **Video walkthrough:** [https://youtu.be/NQuj-2LvhAc](https://youtu.be/NQuj-2LvhAc) (start at 0:21)
- **Live demos:** Open in any browser — links in RFC

Questions & feedback welcome!
