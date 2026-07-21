# RFC: `fx_viewer` — A Lightweight FX Graph Viewer for Compile-Pipeline Debugging

> **Status:** Draft for review  
> **Related:** Observatory RFC (RFC-B), Draft PR [#19288](https://github.com/pytorch/executorch/pull/19288)  
> **Demo reports (Observatory):** [xnnpack/mobilebert](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/xnnpack/mobilebert/observatory_report.html) · [qualcomm/mobilenet_v2](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/qualcomm/mobilenet_v2/observatory_report.html) · [cross-backend compare](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/comparisons/xnn_mv2_vs_qnn_mobilenet_v2/observatory_comparison.html)  
> **Demo reports (fx_viewer standalone):** [MV2 XNNPACK ETRecord compare (2-pane)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_xnnpack/mv2_etrecord_compare_xnnpack.html) · [MV2 QNN ETRecord compare (3-pane)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_qnn/mv2_etrecord_compare_qnn.html) · [3-graph sync demo](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/three_graph_compare/demo_3graph_compare.html)  
> **Walkthrough video:** [https://youtu.be/NQuj-2LvhAc](https://youtu.be/NQuj-2LvhAc)

---

## 1. Summary

We propose adding `executorch/devtools/fx_viewer/` — a small, self-contained FX graph viewer that produces **standalone HTML files** with no server required.

Its primary job is one that the existing visualization tools do not cover well: **debugging a model across multiple compile stages at the same time** — viewing ATen IR, quantized graph, Edge IR, and device graph side by side, with automatic cross-graph node synchronization and programmatic analysis overlays.

`fx_viewer` is **complementary** to Model Explorer, not a replacement. Each tool has a clear best-fit scenario, described in §3.

A working proof-of-concept is available in draft PR [#19288](https://github.com/pytorch/executorch/pull/19288). All demo HTML files linked above were generated from that implementation.

---

## 2. Motivation: What the Existing Tools Cannot Do

ExecuTorch already ships two visualization paths:

- **`devtools/visualization/`** — wraps Model Explorer (ME) for general model browsing.
- **`model-explorer` raw API** — the upstream Python API from `google-ai-edge`.

Both are good at browsing a single model's structure. But when debugging a compile pipeline, developers run into four concrete gaps.

---

### Gap 1 — You cannot view more than 2 graphs at once

**What you need:** When debugging quantization, you typically need to look at 4 stages together — float model, calibrated model, quantized model, and edge/device graph. Seeing only 2 at a time means you lose context.

**What ME provides:** A fixed 2-pane split view. You can load multiple models, but the compare UI only shows 2 at a time.

**What `fx_viewer` provides:** An N-way grid. Any number of graphs in one view, in one HTML file.

```python
from executorch.devtools.fx_viewer import FXGraphCompareExporter, FXGraphExporter
from collections import OrderedDict

FXGraphCompareExporter(
    OrderedDict([
        ("Float",     FXGraphExporter(float_gm)),
        ("Quantized", FXGraphExporter(quantized_gm)),
        ("Edge IR",   FXGraphExporter(edge_gm)),
        ("Device",    FXGraphExporter(device_gm)),
    ]),
    sync_mode="auto",
    title="Quantization Pipeline",
).export_html("pipeline_compare.html")
```

![N-way compare screenshot](demo_material/compare_graphs.png)

**Live demo:** [3-graph sync demo](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/three_graph_compare/demo_3graph_compare.html) — shows reference vs. decomposed (1→many) vs. fused (many→1) sync behavior.

---

### Gap 2 — Cross-graph node sync requires manual work

**What you need:** Click a node in the quantized graph → the corresponding node in the float graph highlights automatically. This is essential for tracing where accuracy degrades.

**What ME provides:**
- Mode 1: "Match node id" — node ids can change after quantization or lowering passes, and the matching does not handle many-to-many transformations (e.g. one ATen op decomposing into multiple quantized ops).
- Mode 2: Generate and upload a mapping JSON file — you need to produce this file separately and upload it through the GUI for cross-graph sync to work. For large models this is impractical.

**What `fx_viewer` provides:** Automatic many-to-many sync — no mapping file needed.

- PyTorch's `Interpreter` base class (used by `ExportPass` and all ExecuTorch `PassBase` subclasses) records node provenance in `fx_node.meta["from_node"]` as each pass executes. This is a linked list of `NodeSource` entries tracing back to the original node.
- `FXGraphExporter` walks this chain to extract `from_node_root` — the name of the original ancestor node before any passes ran.
- The JS compare engine tries sync in order: `from_node_root` → `debug_handle` set-intersection → node id. This handles 1-to-many (decomposition), many-to-1 (fusion), and many-to-many cases automatically.

```
Click "quantized_conv2d_1" in Quantized graph
  → auto-highlights "conv2d_1" in Float graph
  → auto-highlights "conv2d_1" in Edge IR graph
  → auto-highlights "conv2d_1_lowered" in Device graph
```

**Live demo:** [MV2 XNNPACK ETRecord compare](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_xnnpack/mv2_etrecord_compare_xnnpack.html) — click any node in the Aten pane and watch the Edge dialect pane sync automatically.

> **Future work:** We plan to add support for QNN backend graph format (the device-side graph produced after QNN compilation) as an additional pane. This would enable end-to-end node sync from ATen IR all the way through to the on-device execution graph, covering the full compile-to-deploy pipeline in a single view.

---

### Gap 3 — You cannot overlay your own analysis results on the graph

**What you need:** After computing per-layer accuracy (PSNR, MSE, cosine similarity), you want to see which nodes are "red" (bad) directly on the graph — not in a separate table.

**What ME provides:**
- The raw ME API has a `node_data_builder` that supports per-node numeric overlays.
- **Limitation 1:** ME's ETRecord adapter (including Arm's `etrecord-adapter-model-explorer`) extracts only the **edge dialect graph** — a single flattened graph of op nodes. Placeholder, output, and get_attr nodes are collapsed into synthetic "Graph Inputs" / "Graph Outputs" boundary nodes and are not individually addressable for overlay. The overlay API therefore covers the same set of nodes that the adapter exposes.
- **Limitation 2:** The workflow requires: (1) build a `ModelNodeData` object, (2) save it to a JSON file, (3) start the ME server, (4) upload the JSON through the GUI.
- **Limitation 3:** The `devtools/visualization/` wrapper (`visualize_with_clusters`) only exposes `namespace` grouping — it does not expose the `node_data_builder` API at all.
- **Limitation 4:** Overlay data is scoped to a single graph. ME has no mechanism to attach the same overlay across multiple graphs simultaneously.

**What `fx_viewer` provides:** Programmatic overlay on any node type, baked into the HTML at export time.

```python
from executorch.devtools.fx_viewer import GraphExtension, NumericColorRule

ext = GraphExtension(id="accuracy", name="Per-Layer Accuracy")

for node_id, metrics in per_layer_results.items():
    ext.add_node_data(node_id, {
        "severity_score": metrics["severity"],
        "max_abs_err":    metrics["max_abs"],
        "cosine_sim":     metrics["cosine"],
    })

# Color nodes red-to-green by severity
ext.set_color_rule(NumericColorRule(attribute="severity_score", cmap="reds"))

# Show key metrics as labels on each node
ext.set_label_formatter(lambda d: [
    f"sev={d['severity_score']:.2e}",
    f"max={d['max_abs_err']:.2e}",
])

# Show full details in the tooltip panel
ext.set_tooltip_formatter(lambda d: [
    f"cosine_sim: {d['cosine_sim']:.4f}",
    f"max_abs_err: {d['max_abs_err']:.6e}",
])

exporter.add_extension(ext)
exporter.export_html("accuracy_overlay.html")
```

> **Note:** The overlay API is not limited to compile-time data. Runtime artifacts such as ETDump profiling results (latency, event counts) can be parsed and attached as a `GraphExtension` in exactly the same way — see §3 for a comparison with Arm's ETDump overlay approach.

![Color-by overlay screenshot](demo_material/color-by.png)
![Node info panel screenshot](demo_material/node-info.png)

Multiple overlay layers can be stacked and toggled independently:

```python
exporter.add_extension(partition_ext)   # which backend owns each op
exporter.add_extension(accuracy_ext)    # per-layer accuracy
exporter.add_extension(latency_ext)     # profiling data
exporter.export_html("multi_layer.html")
# → user can toggle each layer on/off in the HTML
```

---

### Gap 4 — The output requires a server to view or share

**What you need:** Attach a graph view to a GitHub issue, send it in an email, or upload it as a CI artifact. The recipient should be able to open it without installing anything.

**What ME provides:** Either a live server session (blocking subprocess), or a JSON file that still requires a running ME server to open. There is no standalone output.

**What `fx_viewer` provides:** A single `.html` file. Open in any browser, no server, no installation.

```python
exporter.export_html("debug_report.html")
# → one file, works offline, shareable anywhere
```

This also makes `fx_viewer` CI-friendly: the HTML can be uploaded as a build artifact and opened directly from the CI dashboard.

---

### Gap 5 — The viewer cannot be modified by ExecuTorch contributors

**What you need:** Add a new overlay type, change the layout algorithm, or support a new backend-specific node attribute. This should be a normal ExecuTorch PR.

**What ME provides:** ME is maintained by an external team (`google-ai-edge`). ExecuTorch cannot land viewer changes directly. Any feature request requires an upstream PR and waits for their release cycle.

**What `fx_viewer` provides:** Lives in `executorch/devtools/fx_viewer/`. The frontend is ~4,500 lines of plain JavaScript on HTML5 Canvas — no framework, no build step. Any backend team can read and modify it directly.

| | Model Explorer | `fx_viewer` |
|---|---|---|
| Frontend stack | Angular + three.js + d3 (~50k LoC) | Plain JS on Canvas (~4.5k LoC) |
| Ownership | External (`google-ai-edge`) | In-tree (`devtools/fx_viewer/`) |
| To add a feature | Open upstream PR, wait for release | Normal ExecuTorch PR |
| Layout computation | Browser-side (slow on large graphs) | Python pre-computed, baked into HTML |

---

## 3. Positioning: Complementary, Not a Replacement

`fx_viewer` and Model Explorer serve different jobs. The table below shows when to use each.

| Scenario | Use Model Explorer | Use `fx_viewer` |
|---|---|---|
| "What does my model look like?" | ✅ Rich module hierarchy, collapsible layers | — |
| "Which ops belong to which nn.Module?" | ✅ Namespace grouping | — |
| "What changed between ATen and Edge IR?" | — | ✅ N-way compare, auto sync |
| "Which layer lost accuracy after quantization?" | — | ✅ Accuracy overlay, color-by severity |
| "I need to attach this to a GitHub issue" | — | ✅ Standalone HTML |
| "CI needs to check for graph regressions" | — | ✅ HTML artifact, no server |
| "I need to extend the viewer for my backend" | — | ✅ In-tree, small codebase |

### Why not extend Model Explorer instead?

We considered pushing these features upstream into ME. The blockers are architectural:

- **N-way compare** requires redesigning ME's split-pane UI (currently hardcoded to 2 panes).
- **Automatic node sync** requires ExecuTorch-specific knowledge (`from_node` meta, `debug_handle`) that does not belong in a general-purpose viewer.
- **Standalone HTML** requires removing ME's server dependency, which is a fundamental architectural change.
- **In-tree extensibility** is the point — backend teams need to iterate quickly without waiting for an external team's release cycle.

### Relationship to Arm's `executorch-extension-model-explorer`

Arm recently released `executorch-extension-model-explorer`. Based on the source code, it provides:

- **ETRecord adapter** — extracts the **edge dialect graph only** (via `gen_graphs_from_etrecord` → `EDGE_DIALECT_GRAPH_KEY`), renders it in ME with delegate namespace grouping and node metadata.
- **ETDump data provider** — overlays **runtime latency metrics** (avg/p50/min/max ms, event count) onto the edge dialect graph by matching `debug_handle` values from the ETDump.
- **PTE adapter** — visualizes `.pte` program files.

The same capabilities are achievable with `fx_viewer`:

```python
# ETRecord → multi-pane compare (Aten + edge dialect + backend overlay)
export_etrecord_to_html("mv2.etrecord", "mv2_compare.html")

# ETDump latency overlay — parse ETDump, attach as GraphExtension
from executorch.devtools import Inspector
inspector = Inspector(etdump_path="out.etdump", etrecord="mv2.etrecord")
latency_ext = GraphExtension(id="latency", name="Runtime Latency")
for event in inspector.event_blocks[0].events:
    if event.debug_handles:
        latency_ext.add_node_data(
            event.name, {"avg_ms": event.perf_data.avg}
        )
latency_ext.set_color_rule(NumericColorRule(attribute="avg_ms", cmap="reds"))
```

Key differences:
- Arm's extension shows **one graph** (edge dialect only); `fx_viewer` shows **N graphs** (Aten + intermediate + edge) in one view with automatic cross-pane sync.
- Arm's ETDump overlay is limited to the ME node data API (op nodes in the edge graph); `fx_viewer`'s `GraphExtension` overlay works on any node in any graph, and is not limited to compile-time data — runtime artifacts like ETDump can be overlaid in the same way.
- Arm's extension requires the ME server; `fx_viewer` produces standalone HTML.

The two tools are complementary. Arm's extension is well-suited for deployment artifact inspection within the ME ecosystem. `fx_viewer` is better suited for multi-stage compile pipeline debugging and shareable standalone reports.

---

## 4. Feature Comparison Matrix

| Feature | `devtools/visualization/` (ME wrapper) | Raw ME API | `fx_viewer` |
|---|:---:|:---:|:---:|
| Single graph view | ✅ | ✅ | ✅ |
| GraphModule as direct input | ✅ | ✅ | ✅ |
| ETRecord as direct input | ❌ | ❌ | ✅ (one-liner) |
| Per-node custom data overlay | ❌ (not exposed) | ✅ (edge graph, op nodes) | ✅ (any graph, any node) |
| Programmatic color mapping | ❌ | ✅ | ✅ |
| Minimap for large graph navigation | ❌ | ❌ | ✅ |
| Multiple overlay layers (toggle) | ❌ | ✅ | ✅ |
| Runtime artifact overlay (e.g. ETDump) | ❌ | ✅ (edge graph only) | ✅ (any graph) |
| Multi-graph compare | ❌ | ✅ (2 graphs) | ✅ (N graphs) |
| Cross-graph node sync | ❌ | ✅ (manual mapping file) | ✅ (automatic) |
| Many-to-many node mapping | ❌ | ✅ (manual mapping file) | ✅ (automatic) |
| Backend assignment overlay | ❌ | ❌ | ✅ (from ETRecord) |
| Standalone HTML output | ❌ | ❌ | ✅ |
| No server required | ❌ | ❌ | ✅ |
| CI-friendly artifact | ❌ | ❌ | ✅ |
| Module hierarchy / collapsible layers | ❌ | ✅ | ❌ |
| In-tree, modifiable by ExecuTorch | ❌ | ❌ | ✅ |
| External Python dependency | `model-explorer` | `model-explorer` | `fast-sugiyama` (see §5) |
| Python pre-computed layout | ❌ | ❌ | ✅ |

---

## 5. API Reference

### 5.1 Single-graph export

```python
from executorch.devtools.fx_viewer import (
    FXGraphExporter,
    GraphExtension,
    NumericColorRule,
    CategoricalColorRule,
)

# Build exporter from any GraphModule in the compile pipeline
exporter = FXGraphExporter(graph_module)

# Optional: customize the base layer
exporter.set_base_label_formatter(lambda node: node.info.get("target", ""))
exporter.set_base_color_rule(CategoricalColorRule(attribute="op"))

# Add one or more overlay extensions
ext = GraphExtension(id="my_analysis", name="My Analysis")
ext.add_node_data("node_name", {"metric": 0.95, "status": "pass"})
ext.set_color_rule(NumericColorRule(attribute="metric", cmap="red_green"))
ext.set_label_formatter(lambda d: [f"metric={d['metric']:.2f}"])
ext.set_sync_key("debug_handle")   # enables cross-graph sync on this field
exporter.add_extension(ext)

# Export
exporter.export_html("graph.html")       # standalone HTML
exporter.export_json("graph.json")       # raw JSON payload
js = exporter.export_js("container-id") # embeddable JS snippet
```

### 5.2 Multi-graph compare: `FXGraphCompareExporter`

The new `FXGraphCompareExporter` class renders N `FXGraphExporter` instances into one standalone HTML page. Column order follows insertion order.

```python
from executorch.devtools.fx_viewer import FXGraphCompareExporter, FXGraphExporter
from collections import OrderedDict

viewers = OrderedDict([
    ("ATen IR",   FXGraphExporter(aten_gm)),
    ("Quantized", FXGraphExporter(quantized_gm)),
    ("Edge IR",   FXGraphExporter(edge_gm)),
])

FXGraphCompareExporter(
    viewers,
    title="Quantization Pipeline Compare",
    sync_mode="auto",            # from_node_root → debug_handle → id
    active_extensions=["accuracy"],
    color_by="accuracy",
).export_html("compare.html")
```

**Sync modes:**
- `"auto"` (default) — tries `from_node_root` first, then `debug_handle` set-intersection, falls back to node id.
- `"id"` — node id match only.
- `"layer"` — match by a specific extension field (requires `sync_layer` + `sync_field`).
- `"none"` — no propagation.

### 5.3 ETRecord → compare HTML (new)

The new `etrecord_adapter` module turns an `.etrecord` bundle into a compare view with a single function call. This is the primary entry point for users who already use the ETRecord workflow.

```python
from executorch.devtools.fx_viewer import export_etrecord_to_html

# One-liner: path or in-memory ETRecord → standalone HTML
export_etrecord_to_html("mv2.etrecord", "mv2_compare.html")
```

Panes are added automatically based on what the bundle contains:

1. **Aten** — from `rec.exported_program`. If `from_node` / `debug_handle` are missing (common for bundles produced by `torch.export.export`), the adapter re-runs `run_decompositions({})` and `DebugHandleGeneratorPass` automatically.
2. **Extra stored programs** — one pane per entry in `rec.graph_map`. For example, the QNN pipeline writes `graph_map["edge_after_transform/forward"]` when `to_edge_transform_and_lower_to_qnn` is used — this becomes a third pane automatically.
3. **Edge dialect** — from `rec.edge_dialect_program`, with a `backend` overlay derived from `_debug_handle_map × _delegate_map` when the bundle names a backend.

**Live demos:**
- [MV2 XNNPACK (2 panes: Aten → Edge)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_xnnpack/mv2_etrecord_compare_xnnpack.html) — backend overlay shows which nodes are delegated to XnnpackBackend.
- [MV2 QNN (3 panes: Aten → Edge After Transform → Edge)](https://quic-boyuc.github.io/Executorch_Observatory_Demo/generated_reports/fx_viewer/etrecord_compare_qnn/mv2_etrecord_compare_qnn.html) — the middle pane shows the graph after QNN's transform passes, making the pass pipeline visible.

For callers who want to attach extra extensions or override settings before writing:

```python
from executorch.devtools.fx_viewer import build_compare_from_etrecord

# Returns FXGraphCompareExporter — attach more extensions before export
exporter = build_compare_from_etrecord("mv2.etrecord", title="My Compare")
exporter.export_html("mv2_compare.html")
```

### 5.4 Inspector integration (new)

When an `Inspector` is already available with an ETRecord attached, a single method produces the compare HTML:

```python
from executorch.devtools import Inspector

inspector = Inspector(etdump_path="out.etdump", etrecord="mv2.etrecord")

# One-liner: same pane layout as export_etrecord_to_html
inspector.export_fx_viewer_html("mv2_compare.html")
```

This keeps the ETRecord-based workflow intact — users who already use `Inspector` get `fx_viewer` output without changing their setup.

### 5.5 Payload-level relayout (no GraphModule needed)

```python
# Re-render a previously exported payload with updated extension layers
# Useful for re-analysis without re-running the compiler
relaid = FXGraphExporter.relayout_payload_base(
    base_payload,
    extensions_payload,
    include_layers=["accuracy"],
)
```

### 5.6 Stable API surface

The following are proposed as stable, change-controlled contracts:

| API | Description |
|-----|-------------|
| `FXGraphExporter` | Single-graph export |
| `FXGraphCompareExporter` | N-graph compare export |
| `export_etrecord_to_html()` | ETRecord → compare HTML one-liner |
| `build_compare_from_etrecord()` | ETRecord → `FXGraphCompareExporter` (for customization) |
| `Inspector.export_fx_viewer_html()` | Inspector hook for ETRecord-based users |
| `GraphExtension` | Overlay layer definition |
| `ColorRule` subclasses | Color mapping rules |
| `GraphPayload` / `GraphExtensionPayload` | JSON wire format (used by Observatory) |

---

## 6. Future Work

The following items are planned but out of scope for this RFC:

- **QNN backend graph format support** — Add a pane for the device-side graph produced after QNN compilation, enabling end-to-end node sync from ATen IR through to the on-device execution graph.
- **Non-FX graph formats** — Support for TOSA, JIT, and delegated subgraph formats as additional pane types.
- **Pure-Python layout engine** — Replace `fast-sugiyama` with a dependency-free implementation to eliminate the external package requirement and fix known layout bugs.
- **Live streaming telemetry dashboard** — Stream runtime events into the viewer in real time rather than from a static ETDump file.
- **Nightly CI regression templates** — Pre-built compare workflows for automated graph regression detection across nightly builds.
- **Runtime delegated accuracy** — Per-layer accuracy comparison for delegated (on-device) execution, not just compile-time simulation.

---

## 7. Open Questions

**Q1 — Should `fx_viewer` live in `devtools/fx_viewer/` or somewhere else?**  
Current proposal: `devtools/fx_viewer/` as a sibling to `devtools/visualization/`. The two serve different jobs and have different dependencies. Alternative: nest under `devtools/visualization/` as a second backend. We prefer the sibling layout for clarity.

**Q2 — Should `fx_viewer` provide an extension surface for additional graph formats?**  
Currently `fx_viewer` only accepts `torch.fx.GraphModule` and ETRecord bundles. Backend teams may want to visualize other graph representations — for example, the QNN backend graph (post-compilation device graph), `nn.Module` hierarchy, or TOSA IR. Should we define a formal `GraphFormatAdapter` protocol that third parties can implement to add new pane types, or keep the input surface narrow and add formats case-by-case?

**Q3 — Should single/multi-GraphModule visualization be added to the `Inspector` API?**  
The current `Inspector.export_fx_viewer_html()` hook only works when an ETRecord is attached (it reads the full bundle). Users who have individual `GraphModule` objects — for example, from a custom pass pipeline — cannot use this path. Should `Inspector` gain a method like `Inspector.export_fx_viewer_html_from_graphs({"Aten": gm1, "Edge": gm2})`, or should users call `FXGraphCompareExporter` directly?

**Q4 — Should the JSON payload format be exposed as a stable public API?**  
`GraphPayload` and `GraphExtensionPayload` are currently internal to `fx_viewer`. Exposing them as a stable schema would allow users to export JSON once and re-render HTML later without re-running the compiler, and would enable third-party tooling to consume the format. The cost is schema versioning and backward-compatibility maintenance. Should we expose the JSON format as a stable API, or keep it internal and only support HTML as the stable output?
