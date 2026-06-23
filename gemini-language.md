# Language & Precision Audit: ExecuTorch Observatory RFC
**Role:** Language & Precision Specialist  
**Target Document:** RFC: Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging  
**Scope:** Sections 2 through 9

---

## 1. Verbosity Diagnosis (Top 10 Passages)

The following 10 passages are unnecessarily wordy or syntactically inefficient. Each quote is accompanied by a tighter, high-precision rewrite that preserves original technical intent while reducing the reader's cognitive load.

### Passage 1 (Section 2.1 - Intro)
*   **Original Quote:** 
    > "ExecuTorch’s existing devtools provide excellent primitives for raw capture. In particular, the `Inspector` and `ETRecord`/`ETDump` APIs offer a great primitive interface for dumping arbitrary runtime binary blobs, leaving the backend and developer to design their own interpretation logic in Python scripts." (39 words)
*   **Tighter Proposed Rewrite:** 
    > "ExecuTorch's devtools—such as `Inspector` and `ETRecord`/`ETDump`—provide robust primitives for capturing raw runtime binary blobs. However, they leave interpretation logic to custom, backend-specific Python scripts." (27 words, 30% reduction)

### Passage 2 (Section 2.1 - "No Shared Lifecycle Contract")
*   **Original Quote:** 
    > "Because there is no common session model, backends must build bespoke wrapper scripts (e.g., `qnn_intermediate_debugger.py` on Qualcomm, and separate equivalents for XNNPACK) that manually sequence: configure Inspector, invoke the compiler, collect raw activation blobs at the right pipeline stages, run accuracy simulations, and parse binary data." (48 words)
*   **Tighter Proposed Rewrite:** 
    > "Lacking a shared session model, backends build bespoke wrappers (e.g., Qualcomm's `qnn_intermediate_debugger.py` or XNNPACK equivalents) to manually configure Inspector, compile, collect activation blobs, simulate accuracy, and parse binary data." (32 words, 33% reduction)

### Passage 3 (Section 2.1 - "No Extension Common Ground")
*   **Original Quote:** 
    > "There is no shared place for a backend team to plug in specialized analysis logic, meaning the code that interprets Inspector raw data cannot be reused across different backends." (29 words)
*   **Tighter Proposed Rewrite:** 
    > "The absence of a shared extension layer prevents reusing backend-specific analysis logic across different platforms." (15 words, 48% reduction)

### Passage 4 (Section 2.1 - "No Graph-Anchored Visual Correlation")
*   **Original Quote:** 
    > "Inspector natively correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle`, and exposes this as pandas DataFrames. However, there is no shared layer that (a) captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e` — stages that are not stored in ETRecord and are invisible to Inspector — and (b) synthesizes Inspector's runtime correlation data together with these compile-time snapshots into a single visual, interactive report." (73 words)
*   **Tighter Proposed Rewrite:** 
    > "While Inspector maps runtime ETDump events to the final Edge Dialect graph using pandas DataFrames, it cannot access intermediate compile-time graph states (like `prepare_pt2e` or `convert_pt2e`). No shared tool synthesizes these compile-time snapshots with runtime correlation data into an interactive report." (44 words, 40% reduction)

### Passage 5 (Section 2.1 - "No Multi-Concern Synthesis")
*   **Original Quote:** 
    > "Even when individual analyses succeed, their outputs remain in disconnected formats — console prints, ad-hoc CSVs, static screenshots. There is no shared layer that combines accuracy data, partition assignments, stack trace provenance, and graph structure into a single navigable view for human review or systematic CI parsing." (44 words)
*   **Tighter Proposed Rewrite:** 
    > "Successful analyses remain isolated in disconnected console logs, CSVs, or screenshots. No shared interface aggregates accuracy, partitioning, stack traces, and graph structure into a unified format for human review or CI ingestion." (31 words, 30% reduction)

### Passage 6 (Section 2.3 - Boundaries)
*   **Original Quote:** 
    > "Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them. It is a **workflow lifecycle coordinator and visual synthesis layer** that wraps around them:" (31 words)
*   **Tighter Proposed Rewrite:** 
    > "Observatory does not replace existing runtime capture primitives; it acts as a client workflow coordinator and visual synthesis layer wrapped around them:" (23 words, 26% reduction)

### Passage 7 (Section 4.2 - CLI)
*   **Original Quote:** 
    > "You change nothing about your script. Observatory shims standard pipeline entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`) via scoped monkey-patching — patches are installed when the session opens and unconditionally restored when it closes, even on exceptions." (38 words)
*   **Tighter Proposed Rewrite:** 
    > "Without modifying scripts, Observatory monkey-patches standard pipeline entry points (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`) on session start and unconditionally restores them on session close, even during exceptions." (28 words, 26% reduction)

### Passage 8 (Section 5.1 - "The Foundational Split")
*   **Original Quote:** 
    > "When a compilation runs, you get one shot. Whatever the tool fails to record at that moment is gone forever. So the capture phase has one job — write everything down, as cheaply as possible, and stop." (37 words)
*   **Tighter Proposed Rewrite:** 
    > "Because compilation is transient, the capture phase must efficiently record all required data immediately to avoid data loss." (18 words, 51% reduction)

### Passage 9 (Section 5.1 - "The Foundational Split")
*   **Original Quote:** 
    > "Reasoning about that data is the opposite kind of work. It's slow, opinionated, sometimes wrong, and you want to redo it without re-running the model. Observatory keeps the two phases on opposite sides of a hard boundary, with a file between them." (41 words)
*   **Tighter Proposed Rewrite:** 
    > "In contrast, analyzing this data is an iterative, offline process. Observatory decouples these phases by placing a standardized file boundary between capture and analysis." (25 words, 39% reduction)

### Passage 10 (Section 5.3 - "The Lens Protocol")
*   **Original Quote:** 
    > "Once you accept the capture/analysis split, the shape of a lens writes itself. A lens needs to do two things at two different times: react during capture (recording what matters), and reason offline (interpreting what was recorded). The framework defines a protocol of lifecycle hooks that any backend can implement:" (52 words)
*   **Tighter Proposed Rewrite:** 
    > "Following the capture/analysis split, a lens implements hooks to record data during execution and interpret it offline. The backend protocol defines these lifecycle entry points:" (25 words, 52% reduction)

---

## 2. Jargon & Onboarding Audit

A first-time reader, especially one not intimately familiar with PyTorch 2.0 Export (`PT2E`) or backend-specific instrumentation, will encounter several unexplained terms. The following concepts are used before they are formally defined or contextualized:

1.  **`PT2E` (`prepare_pt2e`, `convert_pt2e`)** (Section 2.1)
    *   *Confusion:* Introduced under "No Graph-Anchored Visual Correlation" without explanation. A general developer will not understand that these are PyTorch 2 Export compiler passes that transform the FX graph.
    *   *Correction:* Provide a brief footnote or vocabulary box explaining that these are standard PyTorch 2 Export graph transformation stages.
2.  **`debug_handle`** (Section 2.1 & 2.3)
    *   *Confusion:* Mentioned as the mechanism correlating runtime events to the final graph. The reader does not know what a `debug_handle` actually is (a unique identifier assigned to compiler graph nodes to track them into executed binary instructions).
    *   *Correction:* Define `debug_handle` at its first occurrence as "a unique ID mapped from Python FX graph nodes to compiled binary operations."
3.  **`ExportedProgram` and `EdgeProgramManager`** (Section 2.3 - Comparison Table)
    *   *Confusion:* Listed as inputs under the comparison table without context or definition.
    *   *Correction:* Add a quick parenthetical noting that these are core PyTorch/ExecuTorch IR container classes.
4.  **`Sujiyama routing`** (Section 6.1)
    *   *Confusion:* This is both a technical jargon term and a misspelling of the **Sugiyama layout algorithm** (a hierarchical graph drawing framework). A reader will be confused by "Sujiyama routing" if they try to search for the layout dependency.
    *   *Correction:* Fix the spelling to "Sugiyama layout algorithm" and explain that it is a standard hierarchical layering layout approach for directed acyclic graphs.
5.  **`delegate_metadata_parser` callback** (Section 2.3 - Comparison Table)
    *   *Confusion:* Introduced in the "Extension model" comparison row without prior context.
    *   *Correction:* Clarify that this is an existing Inspector hook for parsing backend-specific metadata.
6.  **`QNN QHAS profiling`, `XNNProfiler aggregation`, `QParam Audit`** (Section 7)
    *   *Confusion:* Backend-specific profiling terms are introduced in the Roadmap matrix without explanation of what they evaluate.
    *   *Correction:* Add a brief legend or glossary to define these backend-specific diagnostic concerns.

---

## 3. Descriptive Strategy Critique

The RFC currently mixes four distinct writing modes:
1.  **Expository/Architectural:** Deep explanations of design principles (e.g., §2 Motivation, §5.1 Core Split).
2.  **Narrative/Tutorial-Style Walkthrough:** Conversational walkthroughs of developer personas with CLI commands (e.g., §4.1).
3.  **Technical/API Reference:** Direct specification of programming interfaces (e.g., §5.3 Lens Protocol Table, §6.2 API Boundaries).
4.  **Structured Tabular Comparisons:** Visual data matrices (e.g., §2.3 Tool Table, §7 Scope Table).

### Key Issues & Jarring Mode Switches:
*   **The Problem of Premature Walkthroughs:** Section 4.1 immediately plunges the reader into highly specific Qualcomm and XNNPACK shell commands (`pip3 install`, specific model scripts) and links to external `.mp4` walkthroughs *before* the document has defined any core architectural concepts (Session, Region, Record, Archive, Lens). The reader is forced to digest a demo's output without understanding the underlying engine.
*   **Inconsistent Tone (Formal vs. Conversational):** Section 2 maintains a highly professional, academic tone diagnosing systemic tooling fragmentation. In contrast, Section 4.2 and Section 5.1 adopt a highly conversational "narrative" tone, using second person pronouns ("You change nothing...", "you get one shot...", "you want to redo it..."). This shift diminishes the formal authority of the design document.
*   **API Tables Embedded in Conversational Prose:** Section 5.3 defines a rigorous architectural protocol (the 8 lifecycle methods) but precedes it with conversational phrases like "the shape of a lens writes itself."

### Recommendations for a Consistent Mode:
*   **Structural Re-ordering:** Move the high-level expository architecture and vocabulary definitions (§5.1 & §5.2) *before* the narrative persona walkthroughs (§4.1). A reader must understand what a Session, Region, and Record are before they can interpret the Record Tree-Explorer screenshot or a nested Python context manager.
*   **Unify the Tone:** Eliminate second-person perspective ("you") and conversational colloquialisms. Replace them with objective, passive, or third-person software engineering terms (e.g., "Developers change nothing..." -> "No client script modifications are required...").
*   **Isolate Walkthroughs:** Push detailed command-line arguments and file path tables (e.g., the pre-generated reports table in 4.1) to an Appendix or a user-guide companion document to keep the core RFC focused strictly on design, APIs, and schema contracts.

---

## 4. Space Allocation Analysis

The table below estimates the word count allocation for each section across four operational categories:
*   **(a) Problem:** Defining frictions, limitations, and pain points.
*   **(b) Solution:** Describing the design, mechanics, and APIs.
*   **(c) Examples/Demos:** Showing code snippets, terminal commands, or output screenshots.
*   **(d) Meta-Commentary:** Positioning, non-goals, governance, and organizational alignment.

| Section | (a) Problem | (b) Solution | (c) Examples/Demos | (d) Meta-Commentary | Word Count Est. |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **§2 Motivation & Problem Statement** | 65% | 15% | 0% | 20% | ~450 words |
| **§3 Goals and Non-Goals** | 5% | 40% | 0% | 55% | ~250 words |
| **§4 Proposed Capabilities & Demos** | 20% | 20% | 50% | 10% | ~1000 words |
| **§5 How It Works (Core Split)** | 10% | 70% | 10% | 10% | ~700 words |
| **§6 `fx_viewer` Visualizer** | 10% | 80% | 0% | 10% | ~250 words |
| **§7 Scope & Roadmap** | 0% | 50% | 0% | 50% | ~180 words |
| **§8 Governance & API Stability** | 5% | 60% | 0% | 35% | ~200 words |
| **§9 Open Questions for Reviewers** | 25% | 15% | 0% | 60% | ~400 words |

### Allocation Critique & Flawed Balances:
*   **§2 Motivation & Problem Statement:** Generally well-balanced. However, the Comparison Table in §2.3 is highly analytical and detailed. Moving it to §5 or an appendix would keep §2 focused purely on the problem statement.
*   **§3 Goals and Non-Goals:** Heavily weighted towards positioning and meta-commentary (55%). While addressing reviewer pushback is vital, the section spends too much space explaining what Observatory is *not* rather than defining the primary objective criteria.
*   **§4 Proposed Capabilities & Demos:** Extremely bloated with demo material (50%). It includes specific local file paths (`C:\Users\boyuc...`), links to generated HTML outputs, and walkthrough logs. This makes the RFC read like a validation report rather than a design proposal. This section needs to be compacted, pushing the pre-generated report links and local path references to an Appendix.
*   **§6 `fx_viewer` — The Layered Graph Visualizer:** Severely under-allocated. For a core visual component, 250 words is insufficient. The layout algorithm (`fast-sugiyama`), coordinates processing, performance scaling for large graphs (e.g., 10k nodes), and layer merging deserve a more thorough technical solution writeup.

---

## 5. Sentence-Level Precision Issues

Here are 8 sentences from the RFC that suffer from ambiguity, passive voice, or vague engineering claims, along with precise, professional rewrites.

### Sentence 1 (Section 2.1 - Intro)
*   **Original:** 
    > "Debugging is a five-stage workflow: **instrument** the run, **configure** it, **export** captured artifacts, **analyze** metrics/differences, and **visualize** the results."
*   **Issue:** Mixing descriptive noun phrases with imperative verbs ("instrument", "configure") creates grammatical inconsistency.
*   **Rewrite:** 
    > "Debugging involves five sequential stages: instrumentation, configuration, artifact export, metrics analysis, and visualization."

### Sentence 2 (Section 2.2)
*   **Original:** 
    > "Current visualization tools (such as Model Explorer integrations) often require a local web server, preventing easy embedding in standalone files or sharing in discussion threads."
*   **Issue:** Vague claim ("preventing easy embedding..."). It does not clarify *why* a web server requirement impacts portability.
*   **Rewrite:** 
    > "Existing visualization tools (such as Model Explorer) require an active local web server, which prevents developers from embedding graphs in static, portable HTML reports or attaching them to issue trackers."

### Sentence 3 (Section 2.3)
*   **Original:** 
    > "Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them."
*   **Issue:** "is a client of them" is technically colloquial and vague.
*   **Rewrite:** 
    > "Observatory does not replace existing ExecuTorch runtime capture primitives; instead, it consumes their output as an orchestration client."

### Sentence 4 (Section 4.2)
*   **Original:** 
    > "A debugging tool is only useful if it meets you where you already are."
*   **Issue:** Highly subjective, informal, and conversational.
*   **Rewrite:** 
    > "To ensure developer adoption, Observatory integrates directly with existing compilation and execution scripts without requiring codebase modifications."

### Sentence 5 (Section 5.1)
*   **Original:** 
    > "When a compilation runs, you get one shot."
*   **Issue:** Conversational, uses second person, and lacks professional precision.
*   **Rewrite:** 
    > "Because compiler passes and runtime executions are transient, the capture phase must record raw artifacts immediately to prevent data loss."

### Sentence 6 (Section 5.1)
*   **Original:** 
    > "Reasoning about that data is the opposite kind of work."
*   **Issue:** Extremely vague and informal ("the opposite kind of work").
*   **Rewrite:** 
    > "Unlike data capture, post-hoc analysis is computationally expensive and highly iterative."

### Sentence 7 (Section 1 and 6)
*   **Original:** 
    > "The JavaScript API allows external control of node hovering, selection, and viewport actions."
*   **Issue:** Weak, passive phrasing ("allows external control of").
*   **Rewrite:** 
    > "The JavaScript API exposes hooks for client applications to programmatically control node hovering, node selection, and viewport navigation."

### Sentence 8 (Section 6.1)
*   **Original:** 
    > "Coordinates are pre-computed in Python using `fast-sugiyama` (layout library requiring Python >= 3.11)."
*   **Issue:** Passive layout assignment leaves ownership of the layout work unclear.
*   **Rewrite:** 
    > "The Python component of `fx_viewer` pre-computes node coordinates using the `fast-sugiyama` library (requiring Python >= 3.11)."
