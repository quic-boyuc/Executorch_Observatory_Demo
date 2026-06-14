# Observatory & fx_viewer Implementation Hardening Checklist
# 除錯基礎設施維護與架構強化待辦清單 (TODO List)

本文件彙整了跨模型同儕審查（GPT-5.5、Gemini-3.5、Claude-4.6、Claude-4.8）針對 `rfc_review.md` 與 `pr_description_refined.md` 所指出的所有架構缺陷、安全隱憂、依賴風險與治理問題。此清單作為後續開發與上游合併前（Pre-merge）的工程強化指引。

---

## 🟥 1. 合併前硬性阻擋點 (Pre-merge Blockers) — 優先度：高

### 1.1 軟體供應鏈安全：`fast-sugiyama` 依賴去風險化
- [ ] **可選依賴化 (Optional Extras Gate)：** 修改安裝檔，將 `fast-sugiyama` 移出 base `devtools` 依賴。僅列於 `executorch[observatory-layout]` 或 `fast-sugiyama[full]` 中。
- [ ] **優雅降級路徑 (Graceful Fallback Layout)：** 實作純 Python 計算的網格（Grid）佈局，或基本拓撲拓寬，在 Python < 3.11 或 `fast-sugiyama` 載入失敗（Lazy Import）時，報告仍可成功生成並優雅渲染。
- [ ] **安全與來源稽核 (Security Audit & Provenance)：** 對 `austinorr/fast-sugiyama` 的 Rust 原始碼與二進位安全進行合規稽核。長期評估是否 fork 或將 layout 算法移植為 pure-Python 版本，收歸 `pytorch/` 管轄。

### 1.2 介面穩定度防禦：發布 Schema 與版本機制
- [ ] **回歸先標 Experimental：** 在所有模組 docstring 與 CLI banner 中加註 Experimental 警告。承諾在經歷一個完整的 release cycle 之前，暫不將 API 宣告為 "Stable"。
- [ ] **正式發布 JSON Schemas：** 在 `devtools/observatory/schemas/` 目錄下，釋出具體的 JSON Schema（draft-07+）定義檔，定義 Archive JSON 與 Report JSON 的欄位規範。
- [ ] **加入 `schema_version` 版本欄位：** 自 v1 起，Archive 和 Report JSON 格式必須內含 `schema_version` 欄位（採單調遞增主版本與相容次版本規範）。

---

## 🟨 2. 核心架構與穩定性強化 (Architecture & Stability) — 優先度：中

### 2.1 Monkey-Patching 補丁機制安全網
- [ ] **建立 LIFO `PatchManager`：** 取代目前類變數（如 `cls._original`）的不安全暫存。支援巢狀（nested）、重入（reentrant）以及執行緒安全的 patch 恢復棧（LIFO Stack）。
- [ ] **Fail-Fast 目標校驗：** 在 Session 初始化安裝 Patch 時，若目標函式（如 `prepare_pt2e`）不存在，應立刻拋出明確錯誤，杜絕 silent no-op。
- [ ] **`atexit` 異常還原機制：** 加入全域 `atexit` 註冊，保障在編譯程序因 `KeyboardInterrupt` 或 `SystemExit` 異常中斷時，能強行還原猴子補丁，防止污染全域 Python Process 狀態。

### 2.2 跨 Lens 耦合與後端耦合解耦 (Decoupling Layering Violations)
- [ ] **設計 `context.shared_state` 通道：** 消除 `per_layer_accuracy` 與 `accuracy` 之間的私下類變數調用（Cross-Lens coupling），將跨 Lens 依賴與數據共享改為顯式且有序的 protocol 接口。
- [ ] **後端 Patch 註冊實例化：** 消除後端對核心靜態 Lens 類別直接突變的耦合，將 Patch 註冊改由 `ObservationContext` 或 Session 設定動態帶入。
- [ ] **支援多實例 Session：** 將 `Observatory.collect()` 全域單例 API 改為底層由 `ThreadLocal` 實例託管，保留 class method 作為語意糖，以支援單一進程內的多個獨立除錯 Session。

---

## 🟨 3. 安全性、效能與測試防護 (Security, Perf & Tests) — 優先度：中

### 3.1 渲染端安全性 (XSS Prevention)
- [ ] **沙盒化 Lens 自訂 HTML：** 對 Lens 提供的 `HtmlBlock` 內容實施白名單清理（Sanitizer），或將 Lens 導出的 HTML 置於 `data:` URI + iframe 沙盒中運行，防止 DOM 注入型跨站腳本攻擊 (XSS)。
- [ ] **限制大圖尺寸：** 限制單一 HTML 的 size，在大模型（如 MobileBERT/LLaMA）節點破千時，提供節點折疊或分頁渲染選項，保障 shareable HTML 可經由 Email/Slack 正常傳輸。

### 3.2 測試覆蓋率與 CI 整合
- [ ] **Patch 運作正確性測試：** 補上單元測試，確實驗證「安裝 Patch ➡️ 函數執行 ➡️ Telemetry 成功捕獲 ➡️ Patch 還原」的完整 lifecycle。
- [ ] **Schema 飄移回歸測試：** 建立 CI 測試，利用預設 JSON Schema 驗證每次生成的 Archive JSON，格式若有不相容飄移時立刻阻擋（Break CI）。
- [ ] **Browser 渲染自動化測試：** 引入 Playwright / Puppeteer，針對 `fx_viewer` 在不同瀏覽器（Chrome, Firefox, Safari）下的畫布交互與 pan/zoom 行為進行 headless 自動化冒煙測試。

---

## 🟦 4. 長期演進方向 (Future Roadmap / Alternatives) — 優先度：低

### 4.1 核心機制轉移：推動 PyTorch 顯式 Observer Pattern
- [ ] 在上游 PyTorch/ExecuTorch 關鍵編譯節點推動內建的觀察者模式（Observer Pattern），即在 compiler 關鍵管道埋設官方的 `notify_observers(event, context)` hooks。一旦該底層機制完備，Observatory 將全面由 Monkey-Patching 遷移至官方 Observer 鉤子，根除補丁脆弱性。

### 4.2 運行時與設備端精度 Lenses
- [ ] 將 CPU simulation 精度分析（Compile-Time Accuracy Lens）作為 baseline。
- [ ] 開發 Phase 2：結合 `ETRecord`、設備執行（Device Runner）與 `Inspector` 資料，引入真正的「實機運算精度 Lens」，實現真正的 AOT-to-Device 數據對比。
