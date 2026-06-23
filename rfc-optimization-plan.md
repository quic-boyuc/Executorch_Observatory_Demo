# RFC Optimization Plan

**Target Document:** RFC: Observatory — A Workflow Coordinator and Visual Synthesis Layer for ExecuTorch Debugging  
**Purpose:** Provide an actionable, blueprint-level roadmap to restructure, tighten, and refine the Observatory RFC for a highly technical audience (ExecuTorch maintainers, backend owners, and devtools reviewers).

---

## 1. Consensus Matrix (Highest-Confidence Changes)

All three reviews (Structure, Language, and Philosophy) are highly aligned on several critical organizational, linguistic, and structural issues. These represent the highest-confidence changes that should be executed immediately.

| Consensus Area | Identified Problem | Solution / Actionable Resolution |
| :--- | :--- | :--- |
| **Premature Architecture in Demos** | §4 tries to prove the value of the tool through detailed walkthroughs, screenshots, and report tables *before* the reader has a mental model of the core design (Session, Region, Record, Archive, Report, Lens). | **Move Core Architecture early.** Introduce the "Foundational Split" (§5.1) and Vocabulary (§5.2) *before* detailed walkthroughs. Move the dense pre-generated tables and local paths into an **Appendix**. |
| **Vocabulary Duplication** | Core terms are defined first in an ad-hoc glossary box in §4, then defined again through an execution walk-through in §5.2, and repeated inside §4.1.B. | **Consolidate terminology.** Teach the conceptual vocabulary *exactly once* inside the architecture section (§5.2) using the single-execution-run model. Reduce §4's vocabulary box to a minimal, one-line preview. |
| **Inspector & ETRecord Positioning Redundancy** | The core non-goal—that Observatory does not replace or extend `Inspector`, `ETRecord`, or `ETDump`—is repeated across the Abstract, §1, §2.1, §2.3, and §3. | **Centralize boundaries in §2.3 / §3.** Maintain the detailed boundary comparison in a single, high-trust dedicated section. Condense all other references to a short sentence with an explicit cross-reference. |
| **Inconsistent Tone & Second-Person "You"** | The RFC transitions from a formal, academic tone in §2 to an informal, conversational tutorial tone in §4 and §5, using second-person pronouns ("you change nothing", "you get one shot"). | **Unify to professional third-person.** Eliminate conversational colloquialisms (e.g., "the shape of a lens writes itself") and convert all second-person pronouns to third-person software engineering terms (e.g., "no client script modifications are required"). |
| **`fx_viewer` Under-Allocation** | §6 is only ~250 words. For a core visual component highlighted in the RFC title, it lacks technical specification on coordinate layouts, performance scaling, and extension layers. | **Expand §6 with technical specifications.** Detail how coordinate calculations scale for 10k+ node graphs, specify the Sugiyama algorithm integration, and define the JS/Python API boundary. |
| **Formatting & Markdown Artifacts** | Literal `\n` character escapes and broken bullet lists in §6 and §7 disrupt readability. | **Clean up formatting.** Manually resolve all literal string escapes and ensure tables and lists render cleanly. |

---

## 2. Divergence Resolutions & Judgment Calls

Where the three independent reviews emphasize different paths, the following judgment calls have been made to optimize the RFC's narrative flow and authority.

### Divergence 1: Placement of the Tool-Positioning Comparison Table
*   *Structure Review (GPT-5.5):* Suggests moving the comparison table from §2.3 to §3 (Goals & Non-Goals) or the Appendix to keep §2 purely focused on the problem.
*   *Language Review (Gemini):* Suggests moving the table to §5 or the Appendix to minimize detailed solutions in the front-matter.
*   *Philosophy Review (Opus):* Suggests keeping it under §2 but reframing it as a "reviewer-trust" section.
*   *Judgment Call:* **Move the Tool-Positioning Table to §3, and rename the section to "Goals, Non-Goals, and System Boundaries."**
*   *Reasoning:* §2 (Motivation & Problem Statement) must remain a punchy, highly structured diagnosis of systemic devtools fragmentation. Introducing a massive tool-comparison matrix inside §2 interrupts the "pain" narrative before the reader even knows what Observatory is. Placing this table in §3 provides the perfect logical transition: it anchors the "Non-Goals" with a concrete boundary contract that addresses devtools reviewers' immediate anxieties.

### Divergence 2: Structural Order of User Surfaces (§4.2) and Persona Demos (§4.1)
*   *Structure Review:* Proposes moving §4.2 (CLI, Context Manager, Decorator) *before* the persona-based demos (§4.1), splitting §4 into separate sections.
*   *Philosophy Review:* Recommends putting the architectural model (§5) before the detailed demos.
*   *Judgment Call:* **Adopt a three-step progressive disclosure flow:**
    1.  **§4 User-Facing Surfaces:** The reader learns *how* to invoke Observatory (CLI, Context Manager, Decorator) and the outputs generated (Archive vs. Report).
    2.  **§5 Core Design & Architecture:** The reader learns *why* it works under the hood (the Foundational Split, vocabulary, and Lens Protocol).
    3.  **§6 Persona Walkthroughs & Case Studies:** The reader sees these concepts applied to the three roles (Backend Maintainer, Pass Author, CI Engineer) using highly streamlined narrative flows, with raw logs and large tables pushed to the Appendix.
*   *Reasoning:* This order balances both needs. Reviewers first understand the developer-facing API surfaces, then they learn the architectural engine that makes those surfaces possible, and finally, they see the proof-of-concept use cases that validate the design.

---

## 3. Unified Descriptive Philosophy

To ensure the RFC reads as a single, authoritative, and cohesive engineering proposal, the entire document must be written under **one organizing principle**:

> **Progressive Disclosure Around the Capture/Analyze Split**
> 
> *Start with the transient, compile-time lifecycle stage (Capture), introduce the minimum abstraction that solves it (Archive JSON), explain the offline interpretation protocol (Lenses), and only then reveal the visual presentation layers (`fx_viewer` Reports) and governance structures.*

### Tone, Style, and Structural Directives:
1.  **Objective, Third-Person Perspective:** Eliminate all instances of "you", "your script", and conversational filler. Replace with "developers", "client scripts", or passive technical constructions (e.g., "The CLI executes..." instead of "You can run...").
2.  **No Solutions in the Problem Section:** Keep §2 strictly focused on the diagnostic gaps. Do not mention how Observatory resolves a gap until §3 and §4.
3.  **Proof Follows Abstraction:** Never present a screenshot, a generated report link, or a shell command before defining the architectural concepts that justify them.

---

## 4. Concrete Restructuring Plan (Section-by-Section)

Here is the exact action plan for each section of the RFC, indicating space targets and key structural transformations.

### §2. Motivation & Problem Statement
*   **Action:** **Split & Rewrite**
*   **Key Structural Change:** Extract §2.3 (Boundaries & Comparison Table) and move it to §3. Focus §2.1 and §2.2 entirely on diagnosing the four fragmentation gaps (Lifecycle, Extension, Graph Correlation, Synthesis) and the browser deployment barriers of current viewers.
*   **Space Allocation Target:** **Shrink from ~450 to ~300 words.**
*   **Cross-References to Add:** 
    *   Add forward link at the end of §2.1: *"These four workflow gaps are addressed by the unified lifecycle and Lens protocol specified in §5."*
    *   Add forward link at the end of §2.2: *"The standalone, server-free rendering model to address these deployment barriers is specified in §7."*

### §3. Goals, Non-Goals, and System Boundaries
*   **Action:** **Merge & Keep**
*   **Key Structural Change:** Merge §2.3 (Boundaries & Comparison Table) here. Refamilialize the "Non-Goals" to directly link to the comparison table columns, proving that Observatory sits strictly as an orchestration client above existing capture primitives.
*   **Space Allocation Target:** **Expand from ~250 to ~450 words** (due to the table insertion). Compress non-goal text by cross-referencing the table.
*   **Cross-References to Add:**
    *   Add link in Goals to Surfaces: *"(see §4 for invocation interfaces)"* and Lenses *"(see §5.3 for the Lens protocol)"*.
    *   Add link in Non-Goals: *"As shown in the Tool Positioning Comparison table, Observatory does not replace runtime primitives..."*

### §4. User-Facing Surfaces and Outputs (New Section)
*   **Action:** **Split & Rewrite** (Extracted from old §4.2)
*   **Key Structural Change:** Group the three entry points (CLI, Context Manager, Decorator) and the two output artifacts (Archive JSON vs. Report HTML/JSON) into a single, clean user-interface specification. Replace conversational paragraphs with precise API listings.
*   **Space Allocation Target:** **Target ~350 words.**
*   **Cross-References to Add:**
    *   Add transition sentence at the end: *"The distinction between the raw Archive JSON and the analyzed Report HTML/JSON is enforced by the architectural split detailed in §5."*

### §5. Core Design & Architecture: Capture First, Analyze Later (New Section)
*   **Action:** **Move & Consolidate** (Extracted from old §5)
*   **Key Structural Change:** Move this section *before* the detailed persona walkthroughs. Consolidate the "Vocabulary" (§5.2) here as the canonical definition of Session, Region, Record, Archive, Report, and Lens. Remove the redundant vocabulary glossary box from old §4.
*   **Space Allocation Target:** **Target ~600 words.** 
*   **Cross-References to Add:**
    *   Add back-links to §4: *"This foundational split explains why the Archive JSON generated by the CLI (§4.1) or Context Manager (§4.2) can be late-bound analyzed..."*
    *   Add forward-links in Lens Protocol: *"The hooks defined in the Lens Protocol constitute one of the stable public surfaces governed under §9."*

### §6. Working Demos and Persona Walkthroughs (New Section)
*   **Action:** **Move, Compress & Split** (Extracted from old §4.1)
*   **Key Structural Change:** Streamline the three persona narratives. Compress the "Today" pain bullets to single-sentence summaries that link back to §2. Put shell commands and code walkthroughs here, but move the long tables of pre-generated reports, local OneDrive paths, and raw logs to **Appendix A**.
*   **Space Allocation Target:** **Shrink from ~1000 words to ~500 words.**
*   **Cross-References to Add:**
    *   In Persona A (Backend Maintainer): Link "Today" pain to §2.1.
    *   In Persona B (Pass Author): Link the "Region Tree-Explorer" concept to §5.2's definition of Regions.
    *   In Persona C (CI Engineer): Link the `--compare` architecture back to §5.1's Capture/Analyze split.

### §7. `fx_viewer` — The Layered Graph Visualizer (Old §6)
*   **Action:** **Keep & Expand**
*   **Key Structural Change:** Rewrite the layout algorithm and performance scaling specifications. Fix the spelling of the "Sugiyama layout algorithm". Define the exact JavaScript API hooks for node hovering, selection, and viewport navigation. Frame `fx_viewer` as the primary rendering engine for Observatory's Report HTML.
*   **Space Allocation Target:** **Expand from ~250 words to ~400 words.**
*   **Cross-References to Add:**
    *   Add link at start: *"As described in §4 and §5.1, the human-readable Report HTML embeds graph structures; `fx_viewer` is the portable substrate that renders them."*
    *   Add link to JS/Python API boundaries: *"The coordinate-bound Python export classes and JS runtime components form stable contracts governed under §9."*

### §8. Scope, RFC Acceptance Boundary, and Roadmap (Old §7)
*   **Action:** **Rewrite & Clean**
*   **Key Structural Change:** Clean up all escaped literal `\n` characters in the roadmap matrix. Add a clear preamble explaining that while some "Proposed" features (like `--compare` or Report JSON) exist in the POC branch, they are formally presented in this RFC to seek design approval and establish stable schema contracts.
*   **Space Allocation Target:** **Target ~200 words.**
*   **Cross-References to Add:**
    *   Link the "Proposed" schema-dependent features to the API stability and schema contracts in §9.

### §9. Governance and API Stability (Old §8)
*   **Action:** **Keep & Cross-Link**
*   **Key Structural Change:** Keep the structure intact but add explicit cross-links connecting the four stable public surfaces (Lens Protocol, GraphExtension, Archive Schema, Report Schema) to the corresponding implementation sections (§5.3, §7.2, and §5.1) and the Open Questions (§10).
*   **Space Allocation Target:** **Target ~200 words.**

### §10. Open Questions for Reviewers (Old §9)
*   **Action:** **Rewrite & Reformat**
*   **Key Structural Change:** Reformat the dense prose paragraphs of each question into a highly readable, standardized sub-bullet structure: **Decision Requested**, **Context**, **Trade-offs to Discuss**, and **Starting Recommendation**. This lowers the cognitive barrier for reviewer responses.
*   **Space Allocation Target:** **Target ~400 words.**
*   **Cross-References to Add:**
    *   Link Q1 directly to §9.1 (Ownership Boundaries).
    *   Link Q2 directly to §9.2 (Stability Surfaces).
    *   Link Q3 directly to §9.2 (Announcing breaking changes).

---

## 5. Prioritized Execution Roadmap

The restructuring and refinement tasks are categorized below by their impact-to-effort ratio, allowing the author to execute them in stages.

```
       HIGH  │ ──────────────────────────────────────────────────────────┐
             │ [Quick Win] Clean Formatting & Typos                      │
             │ [Quick Win] Reformat §10 Open Questions                   │
             │ [Medium Effort] Move Tool Table to §3                     │
             │ [Medium Effort] Streamline §6 Persona Demos               │
   I         │ [Major Restructuring] Move Core Architecture Early        │
   M         │ [Major Restructuring] Expand §7 fx_viewer Specification   │
   P         │ ──────────────────────────────────────────────────────────┘
   A   MEDIUM│ ───────────────────────────────────┐
   C         │ [Medium Effort] Unify Tone to      │
   T         │  Professional Third-Person         │
             │ ───────────────────────────────────┘
             │
        LOW  └────────────────────────────────────────────────────────────
                           LOW                        HIGH
                                     E F F O R T
```

### A. Quick Wins (Total Time: ~1 Hour)
*   **Task 1: Clean up Markdown formatting and spelling in §7 & §8 (Roadmap/fx_viewer).**
    *   *Action:* Remove escaped `\n` characters, correct "Sujiyama" to "Sugiyama layout algorithm", and fix table render issues.
    *   *Time:* 15 mins.
*   **Task 2: Reformat §10 (Open Questions) into structured sub-bullets.**
    *   *Action:* Separate the dense paragraphs into "Decision Requested", "Context", "Trade-offs", and "Starting Recommendation" blocks.
    *   *Time:* 25 mins.
*   **Task 3: Refactor terminology references to maintain single vocabulary source.**
    *   *Action:* Replace the verbose glossary box in old §4 with a 2-sentence preview pointing to the canonical walk-through in §5.2.
    *   *Time:* 20 mins.

### B. Medium Effort (Total Time: ~2.5 Hours)
*   **Task 4: Move and reframe the Tool-Positioning Comparison Table.**
    *   *Action:* Shift the table from §2.3 into §3. Edit the surrounding non-goal text to form a coherent boundary contract with devtools reviewers.
    *   *Time:* 45 mins.
*   **Task 5: Rewrite and streamline §6 (Working Demos / Use Cases).**
    *   *Action:* Compact the persona narratives. Replace repeated "Today" pain sentences with links to §2. Move the massive pre-generated tables and local OneDrive paths into **Appendix A**.
    *   *Time:* 1 hour.
*   **Task 6: Unify document tone to professional third-person.**
    *   *Action:* Sweep the entire document to eliminate conversational fillers and second-person pronouns ("you").
    *   *Time:* 45 mins.

### C. Major Restructuring (Total Time: ~4 Hours)
*   **Task 7: Re-order sections to prioritize Core Architecture.**
    *   *Action:* Move the "Foundational Split" (§5.1) and Vocabulary Run (§5.2) before the Demos. Re-index and adjust the narrative flow to reflect the new progressive disclosure order.
    *   *Time:* 2 hours.
*   **Task 8: Expand §7 (`fx_viewer`) technical specifications.**
    *   *Action:* Elaborate on coordinate processing, how build-time layout calculations avoid browser lag for large (10k+ node) models, and define the exact Javascript event APIs for selection-sync.
    *   *Time:* 2 hours.

---

## 6. Proposed Outline (New Table of Contents)

This outline represents the optimized reading flow. The estimated relative lengths represent target budget allocations to prevent bloating of proof or meta-commentary.

| New Section Number & Name | Rel. Length | One-Sentence Reader-Focused Purpose |
| :--- | :---: | :--- |
| **1. Summary** | 10% | Provide a polished, high-level executive summary of Observatory, `fx_viewer`, and the benefits they bring to the three developer roles. |
| **2. Motivation & Problem Statement** | 10% | Diagnose the systemic devtools fragmentation and graph visualization barriers without pre-empting specific solution designs. |
| **3. Goals, Non-Goals, and System Boundaries** | 15% | Establish a high-trust boundary contract with reviewers, explicitly anchoring non-goals to a detailed Tool Positioning Comparison Table. |
| **4. User-Facing Surfaces and Outputs** | 10% | Specify how developers invoke the system (CLI, Context Manager, Decorator) and the physical outputs generated (Archive vs. Report). |
| **5. Core Design & Architecture: Capture First, Analyze Later** | 20% | Explain the "Foundational Split" engine, define terms via a single execution run, and specify the Lens Protocol hooks. |
| **6. Working Demos and Persona Walkthroughs** | 15% | Validate the design with streamlined, real-world case studies for backend maintainers, pass authors, and CI pipelines. |
| **7. `fx_viewer` — The Layered Graph Visualizer** | 10% | Detail the technical design of the server-free, canvas-based renderer, layout coordinate processing, and programmatical JS APIs. |
| **8. Scope, RFC Acceptance Boundary, and Roadmap** | 5% | Explicitly separate the physical POC implementation status from the stable API and schema approvals requested in this RFC. |
| **9. Governance and API Stability** | 5% | Define core vs. backend subdirectory ownership boundaries and designate the four stable public contracts. |
| **10. Open Questions for Reviewers** | 5% | Present three actionable, pre-recommended governance and stability decisions for reviewer approval. |
| **Appendix A. Demo Reports, Videos, and Generated Assets** | (Ext.) | Host the dense, pre-generated comparison tables, OneDrive local paths, walkthrough logs, and mp4 video assets. |

---

## 7. Concrete Linguistic Corrections

Apply these high-precision rewrites directly to the corresponding passages during the editing sweep:

1.  **On PyTorch 2 Export (PT2E) Onboarding:**
    *   *Instead of:* "...captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e`..."
    *   *Use:* "...captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e` (standard PyTorch 2 Export compiler passes that transform the FX graph)..."
2.  **On `debug_handle` Onboarding:**
    *   *Instead of:* "...correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle`..."
    *   *Use:* "...correlates runtime ETDump events with the final Edge Dialect graph via `debug_handle` (a unique ID mapped from Python FX graph nodes to compiled binary operations)..."
3.  **On transient compilation capture:**
    *   *Instead of:* "When a compilation runs, you get one shot."
    *   *Use:* "Because compiler passes and runtime executions are transient, the capture phase must record raw artifacts immediately to prevent data loss."
4.  **On analysis complexity:**
    *   *Instead of:* "Reasoning about that data is the opposite kind of work."
    *   *Use:* "Unlike data capture, post-hoc analysis is computationally expensive, highly iterative, and frequently modified."
5.  **On visual layout rendering:**
    *   *Instead of:* "Sujiyama routing..."
    *   *Use:* "Sugiyama layout algorithm (a standard hierarchical layering layout approach for directed acyclic graphs)..."
