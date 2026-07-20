# RFC Proposal: API Surface 對照 & Benefit Analysis

> 本文件為兩份拆分 RFC 的核心 comparison material，用中文快速 review 後轉成英文正式內容。

---

# Part 1: fx_viewer API vs. 既有 Visualization API (Model Explorer)

## 既有 API Surface（`devtools/visualization/`）

```python
from executorch.devtools.visualization import visualize, visualize_with_clusters, visualize_graph

# API 1: 基本視覺化
visualize(
    exported_program,          # ExportedProgram | EdgeProgramManager | ExecutorchProgramManager
    reuse_server=True,         # 重用已開的 ME server
    no_open_in_browser=False,
)
# → 啟動 model-explorer subprocess, 開瀏覽器 tab

# API 2: QDQ cluster + partition 分群高亮
visualize_with_clusters(
    exported_program,
    json_file_name=None,                    # 若提供 → 存 JSON 不起 server
    get_node_partition_name=lambda n: ...,   # 自訂 partition 分群邏輯
    get_node_qdq_cluster_name=lambda n: ..., # 自訂 cluster 分群邏輯
)
# → server 或 JSON file

# API 3: pass 後的 GraphModule 視覺化
visualize_graph(
    graph_module,              # torch.fx.GraphModule (pass 後)
    exported_program,          # 需要原始 EP 做 verifier override
)
# → 同 visualize()
```

## 提議的 fx_viewer API Surface（`devtools/fx_viewer/`）

```python
from executorch.devtools.fx_viewer import (
    FXGraphExporter,
    GraphExtension,
    NumericColorRule,
    CategoricalColorRule,
    compare_graphs,         # 新增 convenience function
)

# === API 1: 單圖 export ===
exporter = FXGraphExporter(graph_module)  # 直接吃 GraphModule，不需 ExportedProgram

# 客製 base layer（每個 node 的 label / color）
exporter.set_base_label_formatter(lambda node: node.info.get("target", ""))
exporter.set_base_color_rule(CategoricalColorRule(attribute="op"))

# 疊加 extension overlay（任意數量）
ext = GraphExtension(id="accuracy", name="Per-Layer Accuracy")
ext.add_node_data("conv1", {"psnr_db": 42.5, "mse": 0.003})
ext.set_color_rule(NumericColorRule(attribute="psnr_db", cmap="red_green"))
ext.set_label_formatter(lambda data: [f"PSNR: {data['psnr_db']:.1f} dB"])
ext.set_tooltip_formatter(lambda data: [f"MSE: {data['mse']:.4f}"])
ext.set_sync_key("from_node_root")  # 跨圖同步用
exporter.add_extension(ext)

# 輸出
exporter.export_html("graph.html")      # → 單一 standalone HTML，瀏覽器直開
exporter.export_json("graph.json")      # → JSON payload (可用於 re-render/embed)
js_code = exporter.export_js("div-id")  # → embeddable JS snippet

# === API 2: N-way 多圖比較 ===
compare_graphs(
    graphs={
        "ATen IR": aten_payload,
        "Quantized": quantized_payload,
        "Edge IR": edge_payload,
        "Device Graph": device_payload,
    },
    sync_mode="auto",  # auto: from_node_root + debug_handle set-intersection
    output="compare.html",
)
# → 一個 HTML，4 張圖 side-by-side，點擊任一 node → 其餘圖自動 highlight 對應 nodes

# === API 3: Payload-level 操作 (不需 GraphModule) ===
relaid = FXGraphExporter.relayout_payload_base(
    base_payload,           # 之前 export 的 JSON dict
    extensions_payload,     # extension layers
    include_layers=["accuracy"],  # 指定哪些 layer 參與 layout sizing
)
# → 純 dict 操作，可用於 re-analysis without re-running compile
```

## API 對照表

| 面向 | 既有 `visualization/` API | 提議 `fx_viewer` API |
|------|--------------------------|---------------------|
| **輸入型別** | `ExportedProgram` (需完整 EP 物件) | `torch.fx.GraphModule` (pipeline 中任何時刻都有) |
| **輸出** | Live server session (blocking) 或 ME JSON | Standalone HTML / JSON / embeddable JS |
| **external dependency** | `model-explorer` package + subprocess | 零 (pure Python + inline JS) |
| **客製化能力** | `namespace` grouping + manual style JSON import | Programmatic: `ColorRule` / `label_formatter` / `tooltip_formatter` / per-node data |
| **Overlay 層** | ❌ 無 (只有 grouping) | 任意多層 `GraphExtension`，可 toggle |
| **多圖比較** | ❌ 不支援 | `compare_graphs()`: N-way grid + auto sync |
| **跨圖 node 對應** | 手寫 mapping JSON，最多 2-pane | 自動 `from_node_root` / `debug_handle` many-to-many |
| **分享方式** | 需 server 開 JSON | HTML 直接貼 PR / email / CI artifact |
| **layout 計算** | 瀏覽器端 (大圖卡) | Python 預計算 + bake into HTML (秒開) |
| **可修改性** | 外部團隊 (Angular + three.js, ~50k LoC) | In-tree, plain JS ~4.5k LoC |
| **Color-by** | 手動 import style rule JSON via GUI | `set_color_rule(NumericColorRule(...))` 一行 |

## fx_viewer 的具體 Benefit（相對既有 API）

### Benefit 1: 解決 compile-pipeline multi-stage debugging 的剛需

**現有 API 做不到的場景**：
- 我在看 quantized graph 的某個 conv node，想知道它對應 ATen IR 的哪些 ops → 需手動查 debug_handle
- 現有 workflow: 存兩個 JSON → 起兩個 ME tab → 手動在兩張圖裡找 → 完全靠記憶比對

**fx_viewer 解法**：
```python
# 點擊 quantized graph 的 node → 自動在 ATen/Edge/Device graph highlight 對應 nodes
# 原理: from_node_root meta 建立了 node lineage chain
compare_graphs({"ATen": p1, "Quantized": p2, "Edge": p3}, sync_mode="auto")
```

### Benefit 2: 解決 ETRecord serialize gap 問題

**現有問題**：
- Qualcomm 的 `LayoutTransform` pass 修改的 meta info 可能不在 ETRecord serialize 範圍內
- 結果：ME 顯示的 graph 缺少部分 backend-specific info → debugging 時看到的不是完整狀態

**fx_viewer 解法**：
- 直接從 **runtime GraphModule** 擷取 → 所有 meta info 都在
- 需要 persist 的是 **分析結果**（小且 well-defined），不是整個 graph snapshot
- 分析結果走 `GraphExtensionPayload` JSON schema → 可重現

### Benefit 3: 自訂分析結果直接顯示在 graph 上

**現有 API 做不到**：
- 我算完 per-layer PSNR 想顯示在 graph node 上 → Model Explorer 不支援 programmatic overlay
- QHAS chart / ADB log 的分析結果 → 完全無法整合進 graph view

**fx_viewer 解法**：
```python
ext = GraphExtension(id="qhas", name="QHAS Analysis")
for node_id, score in qhas_results.items():
    ext.add_node_data(node_id, {"score": score, "status": "pass" if score > 0.9 else "fail"})
ext.set_color_rule(NumericColorRule(attribute="score", cmap="red_green"))
# → 所有 node 依 QHAS score 著色，一眼看出問題 node
```

### Benefit 4: CI / 團隊協作友善

**現有問題**：
- ME JSON 需要起 server 才能看 → CI artifact 無法直接預覽
- Bug report 裡附 ME JSON → reviewer 需要自己 clone repo + 起 server

**fx_viewer 解法**：
- 一個 `.html` 檔案，瀏覽器直接開
- CI 產出 → 直接上傳為 artifact → 任何人點開即看
- GitHub Pages 可直接 host（我們的 demo 就是這樣）

---

# Part 2: Observatory vs. 既有 Inspector + ETRecord Workflow

## 既有 Debugging Workflow

```python
# Step 1: Compile time — 產生 ETRecord
exported = torch.export.export(model, inputs)
edge = to_edge_transform_and_lower(exported, generate_etrecord=True)
et_program = edge.to_executorch()
etrecord = et_program.get_etrecord()
# → .etrecord 檔案 (serialized graph snapshots + debug_handle_map)

# Step 2: Runtime — 設定 runtime config 產生 ETDump
# (需修改 runtime config 啟用 profiling/debug output)
# → .etdump 檔案 (runtime events + optional intermediate outputs)

# Step 3: Post-hoc analysis — Inspector
from executorch.devtools import Inspector
inspector = Inspector(etdump_path="out.etdump", etrecord="out.etrecord")
df = inspector.to_dataframe()
inspector.print_data_tabular()

# Step 4: Visualization (optional, 手動)
from executorch.devtools.visualization import visualize
visualize(inspector.get_exported_program())
# → 起 ME server 看圖（但無法看到 Step 3 的分析結果 overlay）
```

## 提議的 Observatory Workflow

```python
# === Zero-code-change CLI 模式 ===
# python -m executorch.backends.qualcomm.debugger.observatory \
#     --lens-recipe accuracy \
#     --output-html report.html \
#     examples/qualcomm/aot_compiler.py --model mobilenet_v2

# === In-code 模式 ===
from executorch.devtools.observatory import Observatory
from executorch.devtools.observatory.lenses import PerLayerAccuracyLens

Observatory.register_lens(PerLayerAccuracyLens)

with Observatory.enter_context("quantization",
                               config={"per_layer_accuracy": {"enabled": True}}):
    Observatory.collect("Original Model", float_model)
    quantized = quantize(float_model)
    Observatory.collect("Quantized Model", quantized)
    edge = to_edge(quantized)
    Observatory.collect("Edge IR", edge)

# 輸出
Observatory.export_json("archive.json")   # raw capture (可重新分析)
Observatory.generate_html("report.html")  # → 含 fx_viewer graph 的完整 report
```

## 設計選擇 → 能力 → Benefit 對照表

| 設計選擇 | Inspector + ETRecord | Observatory | 導致的差異 |
|---------|---------------------|-------------|-----------|
| **資料擷取時機** | Post-hoc: compile 結束後從 serialized file 讀取 | Inline: compile 過程中即時從 runtime GraphModule 擷取 | Observatory 不受 serialize/deserialize 資料遺失影響 |
| **Graph 資料來源** | ETRecord (序列化的 ExportedProgram snapshots) | Runtime `torch.fx.GraphModule` (in-memory) | Observatory 可看到所有 pass 的完整 meta (含 backend-specific transforms) |
| **擴展分析能力的方式** | 修改 Inspector API / 擴展 ETRecord 格式 | 寫一個 Lens plugin (50-100 LoC, opt-in) | Observatory 不污染核心 API，backend team 可獨立維護 |
| **支援的資料類型** | ETDump events (profiling + debug output) + ETRecord graphs | 任意: GraphModule, ADB logs, profiler output, custom metrics | Observatory 天然支援異質 debug data source |
| **Runtime config 需求** | 需修改 runtime config 啟用 profiling mode | 不需 (compile-time capture 不需 runtime 配合) | Observatory 的 compile-time debugging 不需 device |
| **多張圖之間的 op 對應** | debug_handle (int) 做 1:1 matching | from_node_root + debug_handle 做 many-to-many matching | Observatory 可追溯 quantized → ATen 的 node 爆開/合併 |
| **分析結果與 graph 的關聯** | Inspector 產出 DataFrame; 需手動對應回 graph | Lens analyze 直接產出 GraphExtension overlay | Observatory 的分析結果天然附著在 graph node 上 |
| **Workflow 步驟數** | 4+ 步 (generate ETRecord → config runtime → run → generate ETDump → Inspector → optional ME) | 1-2 步 (enable Lens → run script → report) | Observatory 大幅簡化 debug workflow |
| **離線重新分析** | 需重新跑 compile (ETRecord 不保存分析結果) | Archive JSON 保存 raw capture → 可用不同 Lens recipe 重新 analyze | Observatory 支援 re-analysis without re-compile |
| **比較兩次 run** | 需手動比對兩份 DataFrame | `compare` subcommand: 兩份 archive → diff report | Observatory 原生支援 regression detection |
| **輸出格式** | DataFrame (print / TSV) + optional ME server | Unified HTML report + JSON (CI-friendly) | Observatory 產出可直接分享、CI 可 consume |
| **Backend-specific 工具整合** | 需各 backend 自建 wrapper script | 各 backend 寫 Lens，統一 interface + report format | Observatory 解決 backend debugging 碎片化 |

## 詳細 Benefit 分析

### Benefit 1: Inline Capture 消除 Serialization Gap

**問題場景**（你提到的 Point 4）：
```
Qualcomm backend 的 LayoutTransform pass 會修改 tensor meta 和 node attributes。
這些修改發生在 compile 中間階段。
ETRecord 的 serialize 不一定涵蓋這些 backend-specific meta。
結果：用 Inspector + ME 看到的 graph 可能缺少關鍵 debug info。
```

**Inspector 路線的限制**：
- ETRecord serialize 時機是固定的（`generate_etrecord=True` 時 snapshot）
- Serialize 範圍由 `_etrecord.py` 的 `_process_edge_dialect_program()` 決定
- Backend-specific meta 如果不在 serialize 邏輯內 → 就遺失了
- 要解決就得修改 ETRecord 格式 → 格式膨脹 + 相容性問題

**Observatory 解法**：
- `Observatory.collect("After LayoutTransform", graph_module)` → 直接從 in-memory GM 抓
- 所有 `fx_node.meta` 都在，包括 backend-specific attributes
- 需要 persist 的是 **分析結果**（由 Lens digest 產出的 JSON-serializable data），不是原始圖
- 原始圖在 compile time 就在 memory 中，不需要 serialize 後再 deserialize

### Benefit 2: 多圖對應 + 跨圖追溯（你提到的 Point 3）

**問題場景**：
```
看到 quantized graph 的 quantized_conv2d node 有精度問題。
想知道它對應 ATen graph 的哪些 original ops。
但 quantize 過程中一個 ATen conv2d 可能對應多個 quantized nodes (Q + conv + DQ)。
```

**Inspector 路線的限制**：
- `debug_handle` 是 1:1 int mapping
- 不支援 one-to-many 或 many-to-many 的跨階段 node 追溯
- ETRecord 的 `_debug_handle_map` 只記錄 `Dict[int, Union[int, List[int]]]` → 單層 mapping
- Model Explorer 的 compare 最多 2-pane，需手動上傳 mapping JSON

**Observatory + fx_viewer 解法**：
- 利用 `fx_node.meta["from_node"]` 的 linked list 結構追溯到 root node
- `FXGraphExporter` 自動抽取 `from_node_root` 寫入每個 node 的 info
- `compare.js` 的 `mode: 'auto'` 用 set-intersection 做 many-to-many matching
- 點擊 quantized graph node → 自動 highlight ATen + Edge + Device 的所有對應 nodes

### Benefit 3: 不需修改核心 API 即可擴展 Debug 能力（你提到的 Point 5）

**問題場景**：
```
Backend A 需要 ADB log 分析
Backend B 需要 HTP profiler overlay  
Backend C 需要 Windows debugger integration
Backend D 需要 LPAI memory profiler

如果每個都要 extend Inspector API → Inspector 變成 God class
如果每個都是獨立 example script → 使用者體驗碎片化
```

**Inspector 路線的限制**：
- 要支援新 data source → 需擴展 `EventBlock` / `ETDump schema` / `Inspector.__init__` 的參數
- 或者各 backend 自建完全獨立的 script（現狀：碎片化）
- Inspector 的設計不是 plugin-based → 沒有 "opt-in 分析模組" 的概念

**Observatory 解法**：
```python
# Backend team 自己寫 Lens, 50-100 LoC, 放在 backends/<name>/debugger/observatory/
class HTPProfilerLens(Lens):
    @classmethod
    def get_name(cls): return "htp_profiler"
    
    @classmethod
    def observe(cls, artifact, ctx):
        # 從 artifact 抓取 HTP profiling data
        return extract_htp_metrics(artifact)
    
    @staticmethod
    def get_frontend_spec():
        # 定義 UI: table + graph overlay
        return HTPFrontend()

# 使用者只需:
# python -m executorch.backends.qualcomm.debugger.observatory --lens-recipe htp ...
```

- Lens 是 **opt-in plugin**：不改 core API，不改 ETRecord 格式
- Backend team **獨立維護**：不需 Meta devtools team review
- 統一 interface：所有 backend 的 debug 結果都在同一份 HTML report 裡

### Benefit 4: Workflow 從多步驟簡化成一行（你提到的 Point 5）

**既有 workflow 的步驟數**：

| Step | 動作 | 需要的知識 |
|------|------|-----------|
| 1 | 修改 compile script 加入 `generate_etrecord=True` | 知道 API 參數 |
| 2 | 設定 RuntimeConfig 啟用 profiling | 知道 runtime config schema |
| 3 | 跑 compile + runtime | - |
| 4 | 拿到 .etrecord + .etdump | 知道 output 位置 |
| 5 | 寫 Python script 用 Inspector 分析 | 知道 Inspector API |
| 6 | Optional: 用 visualize() 看圖 | 知道 visualization API |
| 7 | 手動對照 DataFrame + graph | 人工勞動 |

**Observatory workflow 的步驟數**：

| Step | 動作 | 需要的知識 |
|------|------|-----------|
| 1 | 跑 CLI（原始 script 不需修改） | 知道 lens-recipe name |
| 2 | 開 report.html | - |

**差異**：
- 不需修改 compile script（zero-code-change CLI wrapper）
- 不需設定 runtime config（compile-time capture 不需 device）
- 不需手動寫分析 script（Lens 封裝好了）
- 不需手動對照 DataFrame 和 graph（分析結果直接 overlay 在 graph 上）

### Benefit 5: 統一 Report 整合異質 Debug 結果（你提到的 Point 1）

**問題場景**：
```
我做了一次 debug session，結果散落在：
- console print 的 accuracy table
- 一份 CSV 的 per-layer latency
- ADB 拉回來的 log file
- 一張 QHAS 的 screenshot
- ME 開的一個 server tab

想把這些結果集中給同事看 → 需要手動整理成 Google Doc
```

**Observatory 解法**：
- 所有 Lens 的輸出統一進一份 HTML report：
  - `TableBlock` → 結構化數據表格
  - `HtmlBlock` → 自訂 HTML (QHAS chart, custom visualization)
  - `GraphBlock` → 互動式 fx_viewer graph with overlays
  - `CustomBlock` → 任意 JS rendering
- 一個 `.html` 檔案包含所有 debug 結果
- 同時產出 Report JSON → CI 自動化 regression gate 可消費

### Benefit 6: 離線重新分析 + 跨 Run 比較

**問題場景**：
```
上週跑了一個 debug session，這週想用新的分析邏輯看同一份 data。
或者想比較兩次 nightly 的 compile 結果有沒有 regression。
```

**Inspector 路線的限制**：
- ETRecord + ETDump 是 raw data → 每次想問新問題都要重新寫 script
- 兩次 run 的比較需要手動寫 diff 邏輯

**Observatory 解法**：
```bash
# 離線重新分析 (不需重新 compile)
python -m observatory visualize --archive archive.json --lens-recipe new_recipe -o new_report.html

# 跨 run 比較
python -m observatory compare \
    --archives run1/archive.json run2/archive.json \
    --labels "nightly-0718" "nightly-0719" \
    -o comparison.html
```

---

## 兩條路線的定位總結

```
┌────────────────────────────────────────────────────────────────┐
│                     使用者選擇指南                               │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  "我需要看 deployment 後的 runtime profiling"                    │
│  → Inspector + ETDump + Arm ME Extension                       │
│    (post-hoc, runtime data, latency overlay)                   │
│                                                                │
│  "我需要 debug compile pipeline 的 accuracy/correctness"        │
│  → Observatory + fx_viewer                                     │
│    (inline, compile-time, multi-stage graph diff)              │
│                                                                │
│  "我只想快速看一下 model 結構"                                    │
│  → visualization/ (Model Explorer)                             │
│    (general browsing, collapsible modules)                     │
│                                                                │
│  三者共存，各有最佳場景，不互斥                                    │
└────────────────────────────────────────────────────────────────┘
```

### 不互斥的具體證據

| 場景 | 用什麼 |
|------|--------|
| "模型結構長什麼樣？" | `visualize(exported_program)` → Model Explorer |
| "quantize 後哪些 op 精度掉了？" | Observatory + PerLayerAccuracyLens → fx_viewer overlay |
| "runtime 跑起來哪個 op 最慢？" | Inspector + ETDump → DataFrame / Arm ME overlay |
| "兩次 nightly build 的 partition 有沒有變？" | Observatory compare mode → side-by-side graph diff |
| "backend pass 做了什麼 layout 變換？" | Observatory collect + fx_viewer N-way compare |

---

## 與 Arm `executorch-extension-model-explorer` 的精確對照

| | Arm Extension | fx_viewer + Observatory |
|---|---|---|
| **技術基底** | Model Explorer adapters (Angular GUI) | Self-contained HTML (Canvas JS) |
| **資料來源** | Serialized files (.pte, .etrecord, .etdump) | Runtime GraphModule (in-memory) |
| **比較能力** | 2-pane (ME 限制) | N-way grid + auto sync |
| **Overlay 能力** | ETDump latency only (via data provider) | 任意 Lens 產出 (accuracy, custom metrics, ...) |
| **Output** | 需 ME server | Standalone HTML |
| **擴展方式** | 寫 ME adapter (外部 repo, 需懂 Angular) | 寫 Lens (in-tree, ~50 LoC Python) |
| **Node 對應** | debug_handle 1:1 | from_node_root many-to-many + debug_handle |
| **目標場景** | Deployment artifact inspection | Compile-time pipeline debugging |
| **可共存** | ✅ 是 | ✅ 是 |

---

## RFC 引用方式建議

### 在 fx_viewer RFC 中：

> **Positioning relative to existing visualization API:**
> 
> ExecuTorch ships `devtools/visualization/` which wraps Model Explorer for general model browsing. `fx_viewer` is complementary — it targets a different job: compile-pipeline debugging across multiple stages. The key differences are: [引用上方 API 對照表].
> 
> The two coexist: `visualization/` for "what does my model look like?", `fx_viewer` for "where did my accuracy degrade during quantization?"

### 在 Observatory RFC 中：

> **Positioning relative to Inspector + ETRecord:**
>
> Inspector is ExecuTorch's post-hoc analysis tool — it reads serialized ETRecord + ETDump files after compile and runtime complete. Observatory is complementary — it captures data inline during compile, enabling analysis that Inspector cannot provide: [引用上方設計選擇表].
>
> Observatory does not replace Inspector; it can consume Inspector's output as one of many data sources via a Lens adapter. The two serve different stages of the debugging lifecycle.
