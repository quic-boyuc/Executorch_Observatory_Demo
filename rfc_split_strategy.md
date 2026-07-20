# RFC 拆分策略草稿

## 背景

原始 RFC (#20618) 被要求拆成兩個 sub-proposal（rascani 的 comment）。此外 Arm 剛發布了他們的 Model Explorer extension (`executorch-extension-model-explorer`)，強化了 ETRecord + ETDump + Model Explorer 這條既有路線的能力。我們需要更清楚地論述我們的 proposal 相對既有工具鏈（以及 Arm 的新工具）的 **差異化價值**。

---

## 拆分原則

兩個 RFC 各自 **獨立可接受**，但在 "Joint Demo" 小節互相引用對方，展示合作時的額外價值。

---

# RFC-A: `fx_viewer` — 輕量級、可嵌入的 FX Graph Debugging Viewer

## 一句話定位

> 一個專為 compile-pipeline debugging 設計的 FX graph viewer，不取代 Model Explorer，而是填補它無法覆蓋的 in-pipeline multi-stage debugging 場景。

## Motivation（相對既有工具的差異化）

| 需求 | ETRecord + Model Explorer (含 Arm extension) | `fx_viewer` |
|------|----------------------------------------------|-------------|
| **N-way graph 比較** | 最多 2-pane split；Arm extension 同樣限制 | N-way grid，3+ graphs 同時顯示 |
| **跨圖 node 同步** | 僅 exact node-id match；需手寫 mapping JSON | 自動 many-to-many sync (from_node lineage + debug_handle) |
| **點擊 quantized node → 自動跳轉 aten/edge 對應 node** | ❌ 不支援 | ✅ 原生支援，利用 from_node_root 追溯 |
| **自訂分析結果疊加在 graph 上** | 僅 namespace grouping + 有限 node-data JSON（只支援 op nodes） | 任意 per-node data、color rule、label，programmatic API |
| **客製化視覺化（QHAS 圖表、ADB logs、HTML graphs）** | ❌ 無法嵌入非 Model Explorer 格式 | ✅ 同一 HTML report 內可混合 table / HTML block / graph |
| **分享方式** | 需起 local server；JSON 需 server 才能開 | 單一 standalone HTML，可貼 PR / email / CI artifact |
| **Serialization 資訊遺失風險** | ETRecord serialize/deserialize 可能漏失 backend-specific meta (如 Qualcomm layout transform) | 直接從 runtime graph module 擷取，不經 serialize → 不遺失 |
| **可貢獻性** | Model Explorer 是外部團隊維護（Angular + three.js + d3, ~50k LoC）；ExecuTorch 無法直接 land 修改 | 在 ExecuTorch devtools 內，plain JS ~4.5k LoC，任何 backend team 可直接改 |
| **Layout 效能** | 瀏覽器端計算 layout，大圖慢 | Python 預計算 layout，開啟即渲染 |

### 核心論述

1. **ETRecord serialize/deserialize 的資訊缺失問題**
   - Qualcomm 的 layout transform 等 backend-specific pass 資訊在 serialize 過程可能遺失
   - 依賴 ETRecord 匯出 → Model Explorer 顯示的 workflow，對 debugging 來說有 data loss 風險
   - fx_viewer 直接從 runtime `GraphModule` 擷取資訊 → 不存在 serialize gap
   - 需要被 persist 的是 **分析結果**，不是原始 graph（原始 graph 在 compile time 就在 memory 中）

2. **Multi-graph node 對應是 compile-debugging 的剛需**
   - Debugging quantization: 需要看 calibrated → quantized → edge → device graph 之間的 node 對應
   - Model Explorer 只能比較兩張圖，且不支援自動 many-to-many mapping
   - fx_viewer 原生用 `from_node` metadata 建立跨圖追溯鏈

3. **可維護性 & 可擴展性**
   - ExecuTorch 的 viewer 需求不斷演化（新 overlay、新 backend-specific 資訊）
   - 依賴外部團隊的 Model Explorer 意味著每個 feature request 都要走外部 PR
   - fx_viewer codebase 小、無框架依賴，backend team 可自行擴展

### 與 Arm Extension 的關係

Arm 的 `executorch-extension-model-explorer` 強化了 ETRecord/ETDump + Model Explorer 路線：
- PTE adapter: 看 .pte 結構
- ETRecord adapter: 看 graph structure
- ETDump overlay: runtime latency overlay

**fx_viewer 不衝突**，因為：
- Arm extension 仍受限於 Model Explorer 的 2-pane 限制、server 依賴、無法嵌入自訂 HTML
- fx_viewer 解決的是 **compile-time multi-stage debugging** 場景，Arm extension 主要解決 **runtime profiling overlay** 場景
- 兩者可共存：fx_viewer 看 compile pipeline graph diff + accuracy overlay；Arm extension 看 deployment-time latency

### Scope

- N-way graph grid + auto node sync
- GraphExtension overlay API (color, label, per-node data)
- Standalone HTML output
- Python layout engine
- Search, minimap, detail panel

### 與 Observatory 的協作（Cross-reference to RFC-B）

> fx_viewer 可以獨立使用（直接呼叫 Python API 產生 HTML），但當配合 Observatory 的 Lens framework 時，分析邏輯的可維護性和可重用性大幅提升。具體 demo 見 [Joint Demo section]。

---

# RFC-B: `Observatory` — 模組化 Debugging Workflow Framework

## 一句話定位

> 一個 debugging workflow 協調層，用 Lens 模式標準化 capture → analyze → visualize 流程，讓各 backend 的多元 debug 需求以 plug-in 方式提供，不污染既有 ETRecord/ETDump 格式與 Inspection API。

## Motivation（相對既有工具的差異化）

| 需求 | 既有 workflow (ETRecord + Inspector API + example scripts) | Observatory |
|------|----------------------------------------------------------|-------------|
| **多元 backend debugging 工具整合** | 各 backend 各寫各的 script，結果散落 console/CSV/screenshot | 統一 Lens interface → 統一 HTML/JSON report |
| **Custom 分析結果（QHAS/ADB logs/profiler）** | 需 hack Inspection API 或自建 script；無標準化輸出 | Lens 自由定義 capture/analyze/visualize；report 統一 |
| **跨 run 比較 (regression detection)** | 需重新跑 compiler | Archive JSON 保存 → 離線 re-analyze / compare |
| **Setup 複雜度** | 需組合 ETRecord + RuntimeConfig + Inspector API + Visualizer API | `enable Lens + CLI runner` 一行指令 |
| **Backend-specific tool 碎片化** | e.g. Qualcomm 有 Windows debugger / HTP profiler / LPAI tools，各自獨立 tutorial | Lens 模組化，各工具一個 Lens，統一 interface & report format |
| **擴展 Inspection API 的壓力** | 每個新 debug 需求都要 extend Inspector API → 污染核心 | Lens 是 opt-in plugin，不需改動 core API |
| **ETRecord/ETDump 格式穩定性** | 把非標準資料塞入 ETRecord/ETDump → 格式 pollution | Observatory 保持 ETRecord/ETDump 角色不變，extra info 走 Lens → Archive JSON |

### 核心論述

1. **Backend debugging 需求多元化問題**
   - 以 Qualcomm 為例：Windows debugger、HTP profiler、LPAI profiler、QNN graph analysis 都是獨立工具
   - 如果每個都是獨立 example script + tutorial step → 使用者體驗碎片化
   - Observatory 提供統一的 Lens 介面 → 這些工具各自維護一個 Lens module → 使用者只需 `enable` 即可
   - Lens format + Lens recipe 比 example script 更 **portable**、更 **低門檻**

2. **不污染既有核心工具**
   - ETRecord/ETDump 有其 well-defined role（graph structure + runtime event trace）
   - 各種 backend-specific debug info（accuracy delta、custom profiler output、ADB log）不應該塞進這些格式
   - Observatory 是一個 **complementary 協調層**：它使用 ETRecord/ETDump 作為 data source 之一，但額外的分析結果走自己的 Archive JSON schema
   - 這比 extend Inspection API to cover all future needs 更 maintainable

3. **Workflow 簡化**
   - 既有 workflow：`generate ETRecord` → `configure runtime options` → `run` → `generate ETDump` → `Inspector API` → `Model Explorer`
   - Observatory workflow：`enable Lens` → `run script (unchanged)` → `report generated`
   - 對於需要 zero-code-change debugging 的場景（CI、bug repro），差異顯著

4. **離線 re-analysis & comparison**
   - Archive JSON 把 raw capture 與 analysis 分離
   - 可以同一份 archive 用不同 Lens recipe 重新 analyze
   - `compare` subcommand 可比較兩次 run 的 archive → CI regression detection

### 與既有工具的定位

```
┌─────────────────────────────────────────────────────┐
│ Observatory (coordination layer)                     │
│  ┌────────┐  ┌────────┐  ┌──────────┐  ┌────────┐ │
│  │ Lens A │  │ Lens B │  │ Lens C   │  │ Lens D │ │
│  │accuracy│  │ADB log │  │HTP prof  │  │ custom │ │
│  └───┬────┘  └───┬────┘  └────┬─────┘  └───┬────┘ │
│      │           │             │             │      │
│      ▼           ▼             ▼             ▼      │
│  ┌──────────────────────────────────────────────┐   │
│  │ Archive JSON → Report HTML / Report JSON     │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
       ▲ uses as data source (not replaces)
       │
┌──────┴──────────────────────────────┐
│ ETRecord / ETDump / Inspector API   │
│ (unchanged, well-specified role)    │
└─────────────────────────────────────┘
```

### Scope

- Session lifecycle (context manager + collect points)
- Lens protocol (observe/digest/analyze/visualize)
- CLI wrapper (zero-code-change 模式)
- Archive JSON schema (capture ↔ analysis 分離)
- Report HTML / Report JSON generation
- Compare subcommand
- Backend-owned Lens directory (`backends/<name>/debugger/observatory/`)

### 與 fx_viewer 的協作（Cross-reference to RFC-A）

> Observatory 的 Lens 可以 output 任何 visualization block (table, HTML, custom chart)。當 Lens 需要 graph-level visualization 時，它透過 `GraphBlock` + `GraphExtension` API 把結果交給 fx_viewer 渲染。這是兩個 RFC 合作的主要接點。見 [Joint Demo section]。

---

# Joint Demo Section（兩份 RFC 各自包含一份簡短版）

## 合作時的 End-to-End 價值

**場景**：Qualcomm backend, mobilenet_v2, 逐層精度分析

1. 使用者執行：
   ```bash
   python -m executorch.backends.qualcomm.debugger.observatory \
       --lens-recipe accuracy \
       examples/qualcomm/aot_compiler.py --model mobilenet_v2
   ```

2. **Observatory** (RFC-B) 驅動：
   - 自動 patch pipeline entry points → capture calibrated/quantized/edge/device graphs
   - PerLayerAccuracyLens 計算每個 node 的 PSNR
   - 產出 Archive JSON + 觸發 report generation

3. **fx_viewer** (RFC-A) 渲染：
   - 4-way graph grid (calibrated → quantized → edge → device)
   - 點擊 quantized graph node → 自動 highlight 對應的 aten/edge/device nodes
   - Accuracy overlay: nodes 依 PSNR 著色（綠 → 紅）
   - 全部在一個 standalone HTML 裡

4. **整合的額外價值**（只有兩者同時存在才有）：
   - Lens 的分析結果自動成為 graph overlay → 不需手動寫 node-data JSON
   - Compare mode: 比較兩次 run 的 archive，graph 上直接 diff 顯示 accuracy 退化的 nodes
   - Backend team 寫一次 Lens，所有 model 都能用 → 比 per-model example script 維護成本低得多

---

# 與 Arm `executorch-extension-model-explorer` 的差異總結

| 維度 | Arm Extension (Model Explorer) | fx_viewer + Observatory |
|------|-------------------------------|------------------------|
| **目標場景** | Deployment artifact inspection (.pte / .etrecord / .etdump) | Compile-time pipeline debugging & multi-stage graph diff |
| **Graph 來源** | Serialized files (ETRecord) | Runtime GraphModule (no serialize gap) |
| **比較能力** | 2-pane (Model Explorer 限制) | N-way grid + automatic sync |
| **自訂分析 overlay** | 限 ETDump latency data | 任意 Lens-produced data (accuracy, partition, custom) |
| **Output format** | 需 Model Explorer server | Standalone HTML |
| **擴展方式** | 寫 Model Explorer adapter (外部 project) | 寫 Lens (in-tree, ~50 LoC) |
| **關係** | 互補：Arm extension 強在 runtime profiling | 互補：fx_viewer/Observatory 強在 compile-time debugging |

---

# 寫作注意事項

1. **各 RFC 獨立成立**：即使只接受其中一個，價值依然明確
   - fx_viewer 獨立使用：直接呼叫 Python API，不需 Observatory
   - Observatory 獨立使用：report 可以只含 table/HTML blocks，不一定要有 fx_viewer graph
2. **Cross-reference 但不依賴**：Joint Demo 展示合作價值，但各 RFC 的 motivation 和 scope 自足
3. **不攻擊 Model Explorer**：定位為 complementary，解決不同場景
4. **強調 "不污染既有工具" 的設計哲學**：ETRecord/ETDump/Inspector 角色不變，Observatory 是 additive
5. **用 Qualcomm backend 碎片化問題作為具體 motivation example**
6. **Demo links 兩份都附**：讓 reviewer 直接體驗
