# fx_viewer & Observatory 獨立 API 設計評估（含既有 visualization API 分析）

## 既有 devtools 架構全景

```
executorch/devtools/
├── __init__.py              # 公開 API: ETRecord, Inspector, generate_etrecord, parse_etrecord
├── etrecord/                # AOT graph + debug_handle_map serialize/deserialize
├── etdump/                  # Runtime event trace (flatcc schema)
├── inspector/               # Post-hoc analysis: ETRecord + ETDump → EventBlock → DataFrame
├── visualization/           # Model Explorer integration (visualize(), visualize_with_clusters())
│   └── visualization_utils.py  # 啟動 model-explorer server, 或輸出 JSON 給 ME GUI 開
├── bundled_program/         # .pte bundled test I/O
├── backend_debug/           # Backend debug format helpers
├── debug_format/            # OperatorGraph / OperatorNode schema
├── pte_tool/                # .pte inspection CLI
├── size_analysis_tool/      # Binary size breakdown
├── scripts/                 # Dev scripts
├── fx_viewer/               # [我們的] FX graph viewer (standalone HTML)
└── observatory/             # [我們的] Debugging workflow framework
```

---

## 既有 visualization API 分析（`devtools/visualization/`）

### 現有公開 API

```python
from executorch.devtools.visualization import (
    visualize,                  # ExportedProgram → 起 model-explorer server
    visualize_with_clusters,    # ExportedProgram → ME with partition/cluster grouping
    visualize_graph,            # GraphModule → ME (for post-pass inspection)
)
```

### 設計特徵

| 面向 | 現有 visualization API |
|------|----------------------|
| 依賴 | `model-explorer` package（google-ai-edge 外部維護） |
| 輸出格式 | 啟動 subprocess server + 開瀏覽器，或輸出 ME JSON |
| 使用方式 | blocking（server 佔據 process）或存 JSON + 事後開 server |
| 客製化 | `namespace` grouping（partition/cluster）；color 需手動 import style JSON |
| 多圖比較 | ❌ 不支援（一次看一張） |
| Programmatic overlay | ❌ 只有 namespace-based grouping |
| Standalone 分享 | ❌ JSON 需 server 才能看 |
| 貢獻方式 | 需改 `model-explorer` 上游或寫 adapter package |

### Arm 的新 Extension（`executorch-extension-model-explorer`）

Arm 最近發布的工具在 **同一條 Model Explorer 路線上** 擴展能力：

```
PTE Adapter        → 看 .pte 結構（含 delegate subgraph）
ETRecord Adapter   → 看 .etrecord graph
ETDump Provider    → overlay runtime latency 到 ETRecord graph 上
```

但仍然受限於 Model Explorer 的架構：
- 需起 server
- 2-pane 比較上限
- overlay 只支援其定義的 data provider interface
- 無 standalone HTML 輸出

---

## 問題 1: fx_viewer 如何相對於 `visualization/` 暴露 API？

### 三個選項

#### Option 1: 取代 `visualization/`（❌ 不建議）

把 fx_viewer 變成 `visualization/` 的替代。問題：
- Model Explorer 有其 user base（Arm 積極投入）
- 政治風險極高
- 不是我們的目標

#### Option 2: 擴展 `visualization/`（⚠️ 可考慮但不推薦）

```python
# 假設把 fx_viewer 放進 visualization/ 作為另一個 backend
from executorch.devtools.visualization import visualize_fx  # 新
```

問題：
- `visualization/` 的設計哲學是「薄 wrapper 呼叫外部 Model Explorer」
- fx_viewer 完全不依賴 Model Explorer，硬塞在同一模組下語義不清
- 會讓人以為 fx_viewer 也需要 `model-explorer` package

#### Option 3: fx_viewer 作為獨立的平行模組（✅ 推薦）

```python
from executorch.devtools.fx_viewer import FXGraphExporter, GraphExtension, compare_graphs
from executorch.devtools.visualization import visualize  # 不動
```

理由：
1. **不同的技術棧**：visualization = ME wrapper；fx_viewer = self-contained canvas renderer
2. **不同的輸出模式**：visualization = live server；fx_viewer = static HTML
3. **不同的使用場景**：visualization = general browsing；fx_viewer = compile-pipeline debugging
4. **不打架**：兩者共存，使用者根據需求選擇

### fx_viewer 獨立 API Surface 設計

目前 fx_viewer 已經有完整獨立 API（已實作）：

```python
# === Level 1: 單圖 export ===
from executorch.devtools.fx_viewer import FXGraphExporter, GraphExtension
from executorch.devtools.fx_viewer import NumericColorRule, CategoricalColorRule

exporter = FXGraphExporter(graph_module)       # 從 torch.fx.GraphModule 建構

# 客製 base layer
exporter.set_base_label_formatter(lambda node: node.info.get("target", ""))
exporter.set_base_color_rule(CategoricalColorRule(attribute="op"))

# 疊加 extension overlay
ext = GraphExtension(id="accuracy", name="Per-Layer Accuracy")
ext.add_node_data("conv1", {"psnr_db": 42.5})
ext.set_color_rule(NumericColorRule(attribute="psnr_db", cmap="reds"))
ext.set_label_formatter(lambda data: [f"PSNR: {data['psnr_db']:.1f}"])
ext.set_sync_key("from_node_root")            # 跨圖同步 key
exporter.add_extension(ext)

# 輸出
exporter.export_html("graph.html")            # standalone HTML
exporter.export_json("graph.json")            # raw payload
js_snippet = exporter.export_js("container")  # embeddable JS

# === Level 2: 多圖比較 (需新增的 convenience API) ===
from executorch.devtools.fx_viewer import compare_graphs

compare_graphs(
    graphs={
        "ATen": aten_payload,
        "Quantized": quantized_payload,
        "Edge": edge_payload,
        "Device": device_payload,
    },
    sync_mode="auto",       # auto = from_node_root + debug_handle matching
    output="compare.html",
)

# === Level 3: Payload-only API (不需 GraphModule, 用於重新 layout) ===
relaid = FXGraphExporter.relayout_payload_base(
    base_payload,
    extensions_payload,
    include_layers=["accuracy"],
)

# === JS Runtime API (in-browser, 已存在) ===
# window.fxViewer.selectNode(nodeId)
# window.fxViewer.setActiveExtension(extId)
# window.fxViewer.getSelectedNodeData()
```

### 與既有 `visualization/` API 的對照

| | `visualization/` (Model Explorer) | `fx_viewer` |
|---|---|---|
| Import | `from executorch.devtools.visualization import visualize` | `from executorch.devtools.fx_viewer import FXGraphExporter` |
| 輸入 | `ExportedProgram` | `torch.fx.GraphModule` |
| 輸出 | server session / ME JSON | standalone HTML / JSON payload |
| 客製化 | namespace + style JSON import | programmatic overlay + color rule + label formatter |
| 多圖 | ❌ | N-way compare with auto sync |
| 依賴 | `model-explorer` package | 零外部 dependency（pure Python + 4.5k JS） |
| 使用場景 | Model browsing, deployment check | Compile-pipeline debugging, accuracy triage |

### 結論

**fx_viewer 放在 `devtools/fx_viewer/` 作為獨立平行模組是正確位置。** 與 `visualization/` 共存但不競爭：
- 場景不同（browsing vs. debugging）
- 技術棧不同（ME server vs. static HTML）
- 可在文件中明確說明使用時機

---

## 問題 2: Observatory 應放在哪裡？與 Inspector 的關係

### 現有 Inspector 的角色

```
使用者 workflow:
1. compile → generate ETRecord (graph snapshots + debug_handle_map)
2. runtime → generate ETDump (profiling events + debug outputs)
3. post-hoc: Inspector(etdump, etrecord) → EventBlock → DataFrame → 手動分析
4. optional: visualization.visualize(inspector.get_exported_program()) → Model Explorer
```

Inspector 的 **核心價值**：把 ETDump runtime events 與 ETRecord AOT graph 透過 debug_handle 對應起來。

### Observatory 的角色

```
使用者 workflow:
1. enable Lens → run existing compile script (unchanged)
2. inline capture: Observatory.collect() 在 pipeline 各點抓 graph + 跑分析
3. analyze: Lens 計算 derived metrics
4. output: Archive JSON + Report HTML (含 fx_viewer graph)
```

Observatory 的 **核心價值**：在 compile 過程中即時 capture + modular analysis + unified report。

### 三條路徑重新評估（考慮 visualization API 的存在）

#### Path A: Observatory 併入 Inspector

不推薦（理由同前 + 新增）：
- Inspector 的 `__init__.py` 只暴露 `Inspector, Event, EventBlock, PerfData` — 已經是一個 focused API
- Observatory 的 Lens/Session/Record/ViewList 是完全不同的 abstraction
- Inspector 不管 visualization（它只產 DataFrame）；Observatory 同時管 capture + visualization

#### Path B: Observatory 獨立，位於 `devtools/observatory/`（✅ 推薦）

```
devtools/
├── inspector/          # Post-hoc: ETDump + ETRecord → DataFrame
├── visualization/      # Model Explorer wrapper (general browsing)
├── fx_viewer/          # Standalone graph viewer (pipeline debugging)
└── observatory/        # Debugging workflow framework (Lens-based)
```

**架構一致性分析**：
- `inspector/` = **data extraction** (ETDump + ETRecord → structured data)
- `visualization/` = **graph browsing** (ExportedProgram → Model Explorer)
- `fx_viewer/` = **graph debugging** (GraphModule → standalone HTML with overlay)
- `observatory/` = **workflow orchestration** (Lens lifecycle → capture → analyze → report)

每個模組有明確且不重疊的職責。Observatory 是他們之上的 **coordination layer**：

```
               Observatory (orchestration)
              /        |          \
         Lens A    Lens B      Lens C
            |         |           |
     fx_viewer   Inspector    custom profiler
     (graph)    (ETDump data)   (ADB logs)
```

#### Path C: Observatory 作為 Inspector 的 "上層 client" 正式化

介於 A 和 B 之間：不 merge 進 inspector，但在 `devtools/__init__.py` level 把 Observatory 加入頂層 export：

```python
# devtools/__init__.py (修改後)
from executorch.devtools.inspector import Inspector
from executorch.devtools.etrecord import ETRecord, generate_etrecord, parse_etrecord
from executorch.devtools.observatory import Observatory  # 新增
from executorch.devtools.fx_viewer import FXGraphExporter  # 新增
```

這讓 Observatory 成為 devtools 的 **first-class citizen**，與 Inspector 平行而非附屬。

### 建議：Path B + Path C 的結合

1. Observatory 作為獨立模組 `devtools/observatory/`
2. 在 `devtools/__init__.py` 加入 Observatory 和 FXGraphExporter 作為頂層 export
3. Inspector 不動，Observatory 透過 optional Lens 消費 Inspector data

---

## 合理的 API 暴露方式總結

### devtools 頂層 public API（建議修改後）

```python
# executorch/devtools/__init__.py
from executorch.devtools.etrecord import ETRecord, generate_etrecord, parse_etrecord
from executorch.devtools.inspector import Inspector
from executorch.devtools.fx_viewer import FXGraphExporter, GraphExtension
from executorch.devtools.observatory import Observatory  # 新增

# visualization/ 不加入頂層 — 它是 optional dependency (需 model-explorer package)
```

### 各模組的 API 定位

| 模組 | 核心 API | 輸入 | 輸出 | dependency |
|------|----------|------|------|------------|
| `etrecord` | `generate_etrecord()`, `parse_etrecord()` | compile pipeline state | `.etrecord` file | core |
| `etdump` | flatcc schema | runtime events | `.etdump` file | core |
| `inspector` | `Inspector(etdump, etrecord)` | serialized files | `EventBlock[]`, DataFrame | core |
| `visualization` | `visualize(exported_program)` | `ExportedProgram` | ME server session | optional (`model-explorer`) |
| **`fx_viewer`** | `FXGraphExporter(gm)`, `compare_graphs()` | `GraphModule` / payload dict | standalone HTML, JSON | core (pure Python + JS) |
| **`observatory`** | `Observatory.enter_context()`, `Lens` protocol | compile pipeline | Archive JSON, Report HTML | core (uses fx_viewer for graph blocks) |

### 依賴關係圖

```
                         [使用者]
                        /    |    \
            visualization  fx_viewer  observatory
            (Model Explorer)  |         /    |    \
                   |          |    Lens A  Lens B  Lens C
                   |          |      |       |       |
                   |     GraphExtension  Inspector  custom
                   |          |              |
                   ↓          ↓              ↓
              model-explorer  (standalone)   etrecord + etdump
              (external pkg)
```

### 關鍵設計決策

1. **fx_viewer 零外部依賴** — 不 import model-explorer, 不 import observatory
2. **Observatory import fx_viewer** — 用 `GraphBlock` + `GraphExtensionPayload` 渲染圖
3. **Observatory 不 import Inspector** — 透過 Lens adapter pattern 間接消費
4. **visualization/ 不動** — 保持對 Model Explorer 生態的支援

### 與 Arm Extension 共存策略

```
Arm extension (Model Explorer 路線):
  ETRecord → ME ETRecord Adapter → Model Explorer GUI
  ETDump → ME ETDump Provider → overlay on ME graph

我們的路線:
  GraphModule (runtime) → fx_viewer → standalone HTML
  Observatory Lens → analyze → fx_viewer overlay → HTML report

共存點:
  - 兩者都用 debug_handle 做 node 對應
  - ETRecord 可以同時被 Arm extension 和 Observatory Lens 消費
  - 使用者可以 BOTH: ME 看 deployment artifact + Observatory 看 compile pipeline
```

---

## 最終建議

| 決策 | 建議 |
|------|------|
| fx_viewer 放哪 | `devtools/fx_viewer/` — 獨立平行於 `visualization/` |
| fx_viewer API | 現有 `FXGraphExporter` + `GraphExtension` + 新增 `compare_graphs()` |
| Observatory 放哪 | `devtools/observatory/` — 獨立平行於 `inspector/` |
| Observatory vs Inspector | 獨立模組，透過 Lens adapter 間接消費 Inspector data |
| 頂層 export | 把 `FXGraphExporter` 和 `Observatory` 加入 `devtools/__init__.py` |
| 與 visualization/ 的關係 | 共存不衝突，場景明確分工 |
| 與 Arm extension 的關係 | 互補，不競爭 |
