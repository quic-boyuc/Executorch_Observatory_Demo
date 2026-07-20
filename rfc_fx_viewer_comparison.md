# RFC-A: fx_viewer — API Surface & Comparison with Model Explorer

> 本文件為 RFC-A 的核心 comparison section 草稿，供 review 後轉成英文正式內容。
> 目標：結構對齊、逐維度比較、論述嚴謹、結論明確。

---

## 1. 框架：兩個工具的設計目標

在逐項比較之前，先確立兩個工具的 **設計目標**，這決定了所有後續比較的解讀方式。

| | Model Explorer (`devtools/visualization/`) | `fx_viewer` (`devtools/fx_viewer/`) |
|---|---|---|
| **設計目標** | 通用模型結構瀏覽器：讓使用者探索任意 ML 模型的 graph 結構、layer hierarchy、op 屬性 | Compile-pipeline debugging viewer：讓開發者在 compile 過程中比較多個 intermediate graph，並將分析結果直接疊加在 graph 上 |
| **主要使用者** | 模型開發者、部署工程師（想了解模型結構） | Backend 開發者、量化工程師（想 debug compile pipeline） |
| **核心問題** | "這個模型長什麼樣？" | "這個 pass 做了什麼？哪個 node 的精度掉了？" |

這個目標差異是所有後續比較的根本原因。**兩者不競爭，各有最佳場景。**

---

## 2. API Surface 對照

### 2.1 Model Explorer API（完整）

```python
# === 基本視覺化 ===
import model_explorer

# 從檔案
model_explorer.visualize('/path/to/model.pt2')

# 從 ExportedProgram（PyTorch 模型）
model_explorer.visualize_pytorch('model_name', exported_program=ep)

# 多模型同時載入
cfg = model_explorer.config()
cfg.add_model_from_path('/path/to/a.pt2')
cfg.add_model_from_pytorch('model_b', exported_program=ep_b)
model_explorer.visualize_from_config(config=cfg)

# ExecuTorch wrapper（devtools/visualization/）
from executorch.devtools.visualization import (
    visualize,                  # ExportedProgram | EdgeProgramManager | ExecutorchProgramManager
    visualize_with_clusters,    # + partition/cluster namespace grouping
    visualize_graph,            # GraphModule + ExportedProgram（pass 後）
)

# === Custom Node Data（per-node 數值 overlay）===
from model_explorer import node_data_builder as ndb

results = {'node_id1': ndb.NodeDataResult(value=42.5)}
gradient = [ndb.GradientItem(stop=0, bgColor='yellow'),
            ndb.GradientItem(stop=1, bgColor='red')]
graph_data = ndb.GraphNodeData(results=results, gradient=gradient)
model_data = ndb.ModelNodeData(graphsData={'main': graph_data})
model_data.save_to_file('node_data.json')

cfg.add_node_data('my data', model_data)  # 或 add_node_data_from_path(...)
model_explorer.visualize_from_config(config=cfg)

# === 多圖比較（Split-pane）===
# 在 GUI 中手動點擊 split-pane 按鈕
# 同步模式：
#   1. "Match node id"：exact id match
#   2. "Upload mapping from computer"：上傳 JSON 定義 mapping
#      支援 1:1, 1:many, many:1, many:many（mappingEntries 格式）
```

### 2.2 fx_viewer API（完整）

```python
# === 基本視覺化 ===
from executorch.devtools.fx_viewer import FXGraphExporter, GraphExtension
from executorch.devtools.fx_viewer import NumericColorRule, CategoricalColorRule

# 從 GraphModule（compile pipeline 中任何時刻）
exporter = FXGraphExporter(graph_module)
exporter.export_html("graph.html")      # standalone HTML，無需 server
exporter.export_json("graph.json")      # JSON payload
js = exporter.export_js("container-id") # embeddable JS snippet

# === Custom Node Data（per-node 數值 overlay）===
ext = GraphExtension(id="accuracy", name="Per-Layer Accuracy")
ext.add_node_data("conv1", {"psnr_db": 42.5, "mse": 0.003})
ext.set_color_rule(NumericColorRule(attribute="psnr_db", cmap="red_green"))
ext.set_label_formatter(lambda d: [f"PSNR: {d['psnr_db']:.1f}"])
ext.set_tooltip_formatter(lambda d: [f"MSE: {d['mse']:.4f}"])
ext.set_sync_key("from_node_root")   # 跨圖同步 key
exporter.add_extension(ext)
exporter.export_html("graph_with_overlay.html")

# 多個 overlay 層（可 toggle）
exporter.add_extension(partition_ext)
exporter.add_extension(accuracy_ext)
exporter.add_extension(latency_ext)
exporter.export_html("multi_overlay.html")

# === 多圖比較（N-way）===
from executorch.devtools.fx_viewer import compare_graphs

compare_graphs(
    graphs={
        "ATen IR":      aten_payload,
        "Quantized":    quantized_payload,
        "Edge IR":      edge_payload,
        "Device Graph": device_payload,
    },
    sync_mode="auto",   # from_node_root + debug_handle set-intersection
    output="compare.html",
)
# → 單一 HTML，4 張圖 side-by-side，點擊任一 node → 其餘圖自動 highlight

# === Payload-level 操作（不需 GraphModule）===
relaid = FXGraphExporter.relayout_payload_base(
    base_payload, extensions_payload, include_layers=["accuracy"]
)
```

---

## 3. 逐維度比較

以下按 **使用者操作流程** 的順序排列，每個維度先描述 ME 的做法，再描述 fx_viewer 的做法，最後說明差異的實際影響。

### 維度 1：Graph 資料來源

| | Model Explorer | fx_viewer |
|---|---|---|
| **接受的輸入** | `ExportedProgram`（需完整 EP 物件）；`visualize_graph()` 接受 `GraphModule` 但仍需一個 EP 做 verifier override | `torch.fx.GraphModule`（compile pipeline 中任何時刻都有） |
| **資料轉換** | 透過 `PytorchExportedProgramAdapterImpl` 轉成 ME 內部格式（`graphs_list` JSON）；轉換過程可能丟失 backend-specific meta | 直接從 `fx_node.meta` 逐欄位抽取；所有 meta 都在 |
| **Serialize gap 風險** | 有：ME adapter 只轉換它認識的欄位；Qualcomm `LayoutTransform` 等 backend-specific meta 不在 adapter 的轉換範圍內 | 無：直接讀 in-memory GraphModule，不經 serialize/deserialize |

**影響**：對 backend-specific debugging（如 Qualcomm layout transform 後的 graph 狀態），ME 可能顯示不完整的資訊；fx_viewer 顯示的是 compile 當下的完整狀態。

> **注意**：`visualize_graph(graph_module, exported_program)` 確實接受 GraphModule，但它的實作是把 GM 塞回 EP 的 `graph_module` 欄位後再走 ME adapter，所以 adapter 的轉換限制仍然存在。

### 維度 2：Custom Node Data（per-node 數值 overlay）

兩個工具都支援 per-node 數值 overlay，但 **API 設計哲學不同**：

| | Model Explorer | fx_viewer |
|---|---|---|
| **API 風格** | 資料與圖分離：先建 `ModelNodeData` JSON，再 `add_node_data()` 掛上去 | 資料與圖綁定：`GraphExtension` 直接附著在 `FXGraphExporter` 上，一起 export |
| **Color mapping** | `gradient`（連續）或 `thresholds`（離散）；在 `GraphNodeData` 建構時指定 | `NumericColorRule` / `CategoricalColorRule`；`set_color_rule()` 一行 |
| **Node label 顯示** | 透過 "View on node" 選單手動選擇要顯示的欄位 | `set_label_formatter(lambda d: [...])` programmatic，export 時 bake in |
| **Tooltip** | 固定格式（side panel 顯示） | `set_tooltip_formatter()` 自訂 |
| **支援的 node 類型** | **只有 op nodes**（文件明確說明："The custom data is only for op nodes, not layer nodes"） | 所有 node（包含 placeholder、output、get_attr） |
| **多個 overlay 層** | 可上傳多個 JSON 檔，GUI 用 "eye" icon toggle | 多個 `GraphExtension`，export 時全部 bake in，HTML 內 toggle |
| **Workflow** | 需要：(1) 建 JSON (2) 起 server (3) 在 GUI 上傳 JSON (4) 選擇顯示 | 需要：(1) `add_extension()` (2) `export_html()` |

**影響**：ME 的 node data workflow 需要 server 和手動 GUI 操作，不適合 CI 或自動化 pipeline；fx_viewer 的 overlay 是 programmatic 且 bake-in，適合自動化。

### 維度 3：多圖比較（Multi-graph Comparison）

這是兩個工具差異最大的維度。

| | Model Explorer | fx_viewer |
|---|---|---|
| **最多幾張圖** | **2**（split-pane 是固定的兩格） | **N**（任意數量，grid layout） |
| **開啟方式** | GUI 手動點擊 split-pane 按鈕；每張圖需分別從 model graph selector 選取 | `compare_graphs(graphs={...})` 一行 Python call |
| **圖的來源** | 需要先把每張圖存成獨立的 JSON 或 .pt2 檔，分別載入 ME | 直接傳入 payload dict（`FXGraphExporter.generate_json_payload()` 的輸出） |
| **Node 同步模式** | (1) "Match node id"：exact id match；(2) 上傳 mapping JSON（支援 1:1, 1:many, many:many） | `sync_mode="auto"`：自動用 `from_node_root` lineage + `debug_handle` set-intersection 建立 mapping |
| **Mapping 建立方式** | **手動**：需要使用者自己寫 mapping JSON，格式為 `{"type": "sync_navigation", "mappingEntries": [...]}` | **自動**：`FXGraphExporter` 在 export 時從 `fx_node.meta["from_node"]` 抽取 `from_node_root`，JS runtime 做 set-intersection matching |
| **Many-to-many 支援** | 支援（`mappingEntries` 格式），但需手動寫 JSON | 支援，且自動（不需手動 mapping） |
| **輸出格式** | 需要 server 才能看 split-pane | 單一 standalone HTML |

**影響（具體場景）**：

**場景：Debug quantization pipeline（ATen → Quantized → Edge → Device，4 張圖）**

ME 做法：
```
1. 跑 compile，在 4 個時間點各存一份 ExportedProgram
2. 用 visualize_with_clusters() 各存一份 JSON（4 個 JSON 檔）
3. 起 ME server，載入 4 個 JSON
4. 手動在 GUI 開 split-pane（只能看 2 張）
5. 手動寫 mapping JSON（quantized node id → ATen node id）
6. 上傳 mapping JSON
7. 在兩張圖之間切換（第 3、4 張圖需要另開 split-pane）
```

fx_viewer 做法：
```python
# 在 compile script 中
aten_payload = FXGraphExporter(aten_gm).generate_json_payload()
quantized_payload = FXGraphExporter(quantized_gm).generate_json_payload()
edge_payload = FXGraphExporter(edge_gm).generate_json_payload()
device_payload = FXGraphExporter(device_gm).generate_json_payload()

compare_graphs(
    graphs={"ATen": aten_payload, "Quantized": quantized_payload,
            "Edge": edge_payload, "Device": device_payload},
    sync_mode="auto",
    output="compare.html",
)
# → 一個 HTML，4 張圖，自動 sync，點擊即跳轉
```

### 維度 4：輸出格式與分享

| | Model Explorer | fx_viewer |
|---|---|---|
| **輸出格式** | (1) Live server session（blocking subprocess）；(2) JSON 檔（需 server 才能開） | (1) Standalone HTML（瀏覽器直開）；(2) JSON payload；(3) Embeddable JS snippet |
| **分享方式** | 需要對方也有 ME server；JSON 無法直接分享（需 server） | HTML 直接貼 PR comment / email / CI artifact |
| **CI 整合** | ❌ 不適合（需 server，blocking） | ✅ 適合（HTML artifact，可直接 upload） |
| **Permalink** | 支援（但只在 local server 有效，換機器失效） | HTML 本身就是 permalink（任何瀏覽器都能開） |
| **Colab 支援** | ✅（embedded iFrame） | ✅（`export_js()` 可嵌入任何 HTML） |

### 維度 5：可維護性與可擴展性

| | Model Explorer | fx_viewer |
|---|---|---|
| **Codebase 大小** | Angular + three.js + d3，~50k LoC frontend | Plain JS on HTML5 Canvas，~4.5k LoC |
| **Ownership** | google-ai-edge 外部團隊維護；ExecuTorch 無法直接 land viewer 修改 | 在 `executorch/devtools/fx_viewer/` 內；任何 backend team 可直接改 |
| **新增 feature** | 需向 ME 上游提 PR，等待 review 和 release | 直接在 in-tree 改，走正常 ExecuTorch PR 流程 |
| **Layout 計算** | 瀏覽器端計算（大圖 layout 慢，影響開啟速度） | Python 預計算，bake into HTML（開啟即渲染） |
| **Backend-specific 擴展** | 需寫 ME adapter package（外部 repo，需懂 Angular） | 寫 `GraphExtension`（in-tree，~20 LoC Python） |

### 維度 6：Dependencies

| | Model Explorer | fx_viewer |
|---|---|---|
| **Python dependency** | `ai-edge-model-explorer` package（需額外安裝） | 零（pure Python stdlib + torch） |
| **安裝** | `devtools/install_requirements.sh` | 隨 ExecuTorch 一起安裝 |
| **Frontend dependency** | Angular, three.js, d3（browser-side） | 零（inline JS，無 CDN 依賴） |
| **Server** | 需要（subprocess） | 不需要 |

---

## 4. 功能矩陣總覽

| 功能 | Model Explorer | fx_viewer | 備註 |
|------|:--------------:|:---------:|------|
| 單圖視覺化 | ✅ | ✅ | |
| GraphModule 輸入 | ⚠️ | ✅ | ME 需包裝成 EP；fx_viewer 直接接受 |
| Per-node custom data overlay | ✅ | ✅ | |
| Overlay color mapping | ✅ | ✅ | |
| Overlay label on node | ⚠️ | ✅ | ME 需 GUI 手動選；fx_viewer programmatic |
| 只支援 op nodes | ⚠️ | ✅ | ME 文件明確：only op nodes |
| 多個 overlay 層 toggle | ✅ | ✅ | |
| 多圖比較 | ✅（2 張） | ✅（N 張） | |
| 跨圖 node 同步 | ✅（手動 mapping JSON） | ✅（自動 from_node_root） | |
| Many-to-many node mapping | ✅（手動） | ✅（自動） | |
| Standalone HTML 輸出 | ❌ | ✅ | |
| CI-friendly artifact | ❌ | ✅ | |
| 無 server 依賴 | ❌ | ✅ | |
| Layer hierarchy 展開 | ✅ | ❌ | ME 的強項；fx_viewer 不做 |
| Module-level grouping | ✅ | ❌ | ME 的強項 |
| In-tree 可修改 | ❌ | ✅ | |
| 零 external dependency | ❌ | ✅ | |
| Python 預計算 layout | ❌ | ✅ | |

---

## 5. 結論：互補定位，各有最佳場景

### 選 Model Explorer 的場景
- 想探索模型的 **module hierarchy**（哪些 op 屬於哪個 nn.Module）
- 想看 **deployment artifact**（.pte, .etrecord）的結構
- 需要 **layer-level 展開/收合** 的互動式瀏覽
- 已有 ME 環境，做一次性的模型結構確認

### 選 fx_viewer 的場景
- 需要比較 **3 張以上** intermediate graph（ATen → Quantized → Edge → Device）
- 需要 **自動跨圖 node 追溯**（點擊 quantized node → 自動找到 ATen 對應 node）
- 需要把 **分析結果（accuracy, partition, custom metrics）programmatically overlay** 在 graph 上
- 需要 **CI-friendly** 的 artifact（standalone HTML，無需 server）
- 需要 **backend-specific** 的 viewer 擴展（in-tree，不依賴外部 team）
- 需要 **分享** debugging 結果（HTML 直接貼 PR）

### 為什麼不直接擴展 Model Explorer？

1. **架構限制**：ME 的 split-pane 是 2-pane 固定設計，N-way compare 需要重構 UI
2. **Ownership**：ME 是外部 team 維護，ExecuTorch 無法直接 land 修改
3. **Sync mapping**：ME 的 sync 需要手動 JSON；自動 `from_node_root` matching 需要 ExecuTorch-specific knowledge，不適合放在通用 ME 裡
4. **Standalone HTML**：ME 的架構是 server-based，改成 standalone 需要重大重構
5. **Serialize gap**：ME adapter 的轉換邏輯是固定的，backend-specific meta 的支援需要每個 backend 各自寫 adapter

---

## 6. RFC 中的 Positioning Statement（建議用語）

> `fx_viewer` is **complementary** to Model Explorer, not a replacement. Model Explorer excels at general model browsing with its rich layer hierarchy and module grouping. `fx_viewer` fills a gap that Model Explorer's architecture does not cover well: **debugging a model across multiple compile stages simultaneously**, with automatic cross-graph node synchronization and programmatic analysis overlays, in a server-free, CI-friendly format.
>
> The two coexist in `devtools/`: `visualization/` wraps Model Explorer for general browsing; `fx_viewer/` provides compile-pipeline debugging. Users choose based on their task, not their toolchain.
