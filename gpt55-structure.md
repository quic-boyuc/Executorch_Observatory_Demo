# Organization & Structure Review — ExecuTorch Observatory RFC

Role: Organization & Structure Specialist  
Reviewer model: first-time community reviewer with ~30 minutes to understand the proposal  
Source: `/home/boyucwsl/Executorch_Observatory_Demo/rfc_review.md`

---

## Executive Structural Assessment

Sections 1 and the Abstract now give a clear top-level promise: Observatory is a workflow coordination layer, lenses are the extension model, and `fx_viewer` is the visual synthesis layer. The remaining sections are conceptually complete, but the reader's attention is spent inefficiently because the RFC currently alternates between four modes:

1. problem framing,
2. user demos,
3. architectural explanation,
4. governance/API stability.

The biggest structural issue is that §4 is doing too much. It introduces vocabulary, proves real-world value, documents CLI surfaces, embeds demo assets, repeats motivation from §2, and partially explains architecture that §5 later explains more cleanly. A first-time reviewer will likely skim the demo tables and screenshots before reaching the design model in §5, even though §5 is the section that makes the proposal reviewable.

Recommended structural goal: make the reader move through **Problem → Boundaries → User surfaces → Architecture → Viewer → Stability → Review questions**, with demos treated as evidence rather than the main exposition.

---

## 1. Reading Flow Diagnosis

### 1.1 Current section ordering and reader experience

Current order:

| Section | Current role | First-time reviewer experience |
|---|---|---|
| Abstract | Compact proposal summary | Clear and useful. Establishes positioning, lenses, CLI, CI. |
| §1 Summary | Polished high-level overview | Clear. Introduces CLI/decorator/context manager, lens lifecycle, personas, `fx_viewer`, and forward references. |
| §2 Motivation & Problem Statement | Pain, boundaries, comparison table | Mostly useful, but dense. §2.1 and §2.3 repeat the Inspector/ETRecord positioning several times. |
| §3 Goals and Non-Goals | Scope statement | Correct but slightly late: some non-goals would help before the detailed tool comparison or early in §2. |
| §4 Proposed User-Facing Capabilities & Working Demos | Personas, demos, screenshots, CLI, concept glossary, artifact kinds | Overloaded. It mixes demo evidence with architectural concepts and repeats pain statements. A 30-minute reviewer may get trapped in links/tables before understanding the design. |
| §5 How It Works | Capture/analyze split, vocabulary, Lens protocol | Strongest design section. Should be reached earlier or referenced more aggressively from §4. |
| §6 `fx_viewer` | Viewer requirements and APIs | Concise and useful, but some `fx_viewer` value was already explained in §1 and §2.2. |
| §7 Scope & Roadmap | Phase table | Good placement after architecture, but formatting contains literal `\n` artifacts that interrupt reading. |
| §8 Governance and API Stability | Ownership and stable surfaces | Good content; should cross-link to §9 questions and §5 Lens protocol. |
| §9 Open Questions | Review prompts | Strong. Questions are actionable, but each prompt paragraph is too dense and should be split into Prompt / Trade-off / Starting recommendation bullets. |

### 1.2 Where the reader may get lost

#### A. §4 introduces vocabulary before the architecture section, then §5 reintroduces it

In §4, the RFC says:

> "To assist first-time readers in skimming this section, here are the core concepts of the Observatory architecture (fully defined in **§5.1**):"

Then it defines Session, Region, Record, Archive, Report, and Lens. §5.2 later explains the same vocabulary through a run:

> "Rather than defining terms in isolation, watch one compilation flow through the system — the vocabulary builds itself."

This creates a flow conflict. §4 says “here is the glossary so you can read the demos”; §5 says “do not define terms in isolation; learn them through execution.” The §5 explanation is more effective and should be the primary definition. §4 should either contain a tiny “terminology preview” or move after §5.

#### B. §4.1 persona demos repeat §2 pain statements before the architecture is available

Example from §4.1.A:

> "ExecuTorch's `Inspector` provides `calculate_numeric_gap()` for AOT-vs-runtime comparison, but using it requires writing manual Python scripts. Furthermore, Inspector's analysis is limited to the final Edge Dialect graph stored in `ETRecord` — it cannot see or compare accuracy across intermediate AOT compile-time stages..."

This duplicates §2.1 and §2.3. At this point, the reader needs to know what the user can do, not re-read the full problem statement. Recommend compressing persona “Today” bullets to one sentence each and cross-reference §2.

#### C. Demo assets interrupt the conceptual path

§4.1.A includes:

- a zero-config CLI walkthrough,
- video links,
- screenshots,
- a pre-generated single-run demo report table.

Then §4.1.B introduces region concepts and code. Then §4.1.C includes architecture ASCII art, another CLI, cross-backend screenshot, and a long comparison report table.

A 30-minute reviewer will likely skim or skip this whole section. The demos are valuable, but they should be structured as evidence after the core surface is understood. Right now, they delay §5, where the actual design is explained.

#### D. §4.2 repeats user surfaces already presented in §1

§1 already says:

> "How engineers invoke debugging — three entry points, from easiest to most flexible: CLI, Decorator, Context manager"

§4.2 repeats the same three entry points in longer form:

> "ExecuTorch developers enter the debugging workflow from three different places — and Observatory exposes one surface for each..."

This is acceptable if §4.2 is the canonical detailed surface section, but §4.1 has already shown CLI, context manager, and decorator in demos. The flow would be cleaner if §4.2 came before §4.1, so the reader learns the surfaces once, then sees them applied in personas.

#### E. §5 contains the strongest architecture explanation but arrives late

The design hinge is:

> "Observatory revolves around one architectural principle: **capturing data during a run is a different job from reasoning about it afterward.**"

This is the key idea needed to understand Archive JSON, Report HTML/JSON, `--compare`, CI, and lens lifecycle. It appears after several pages of demos. A reviewer may not have enough attention left. Consider moving a shortened version earlier or making §4 explicitly depend on §5.

#### F. §7 has formatting artifacts that break scanability

§7 contains literal escaped newlines:

> "... client-side caching.*"

and:

> "| Live streaming-telemetry dashboard |\n\n*Note: **Report (JSON)** via `json_frontend`..."

These are likely markdown formatting bugs. They make the RFC look less polished and can cause a reviewer to question whether the roadmap table is final.

---

## 2. Cross-Reference & Linking Plan for §2–§9

### 2.1 Add cross-references where later sections depend on earlier definitions

| Location | Current issue | Recommended cross-reference / edit |
|---|---|---|
| §2.1 opening | Defines five-stage workflow: "**instrument**, **configure**, **export**, **analyze**, and **visualize**". §1 uses four lifecycle stages: Instrument, Serialize, Analyze, Visualize. | Either align terminology or add: "These map to the Lens lifecycle described in §5.3; `configure` is handled by session/lens config, while `export` becomes Archive serialization." |
| §2.1 bullets | Repeats Inspector/ETRecord limitations later in §2.3 and §4.1.A. | End §2.1 with: "§2.3 clarifies how this sits above `Inspector`/`ETRecord`; §5 explains the Archive/Lens design that addresses it." |
| §2.2 | Introduces viewer need but not the dedicated viewer section. | Add: "The concrete `fx_viewer` API and server-free rendering model are specified in §6." |
| §2.3 | Strong boundary explanation but duplicates non-goal content. | Add forward link: "This boundary is codified as a non-goal in §3 and as stable ownership/API boundaries in §8." Then shorten §3 non-goal. |
| §3 Goals | Mentions Lens, invocation surfaces, output formats, `fx_viewer`. | Add parenthetical links: Lens protocol (§5.3), invocation surfaces (§4.2), output split (§5.1), viewer boundaries (§6.2). |
| §3 Non-Goals | "Replacing or Extending Inspector/ETRecord" repeats §2.3. | Compress to a short bullet and link back: "See §2.3 for the full relationship with existing tools." |
| §4 preamble | Mentions architecture concepts and glossary before §5. | Replace glossary with: "Terms used below — Session, Region, Record, Archive, Report, Lens — are defined through an example run in §5.2. Briefly: ..." Keep only one-line preview. |
| §4.1.A Today | Repeats §2.3 Inspector limitation. | Change to: "Today: the fragmentation described in §2.1/§2.3 appears as per-backend scripts and disconnected CSV/log outputs." Then focus on demo. |
| §4.1.B Region Concept | Defines Region again. | Link to §5.2: "Region is defined in §5.2; this demo shows what it looks like in the report tree." |
| §4.1.C CI architecture | Re-explains Archive vs Report, which §5.1 explains. | Move ASCII diagram to §5.1 or replace with: "This is the capture/analyze split from §5.1 applied to CI." |
| §4.2 final sentence | "The split between raw capture and derived analysis isn't cosmetic — it's the central design decision, and it's what §5 explains." | Good. If §4.2 is moved before §4.1, keep this as transition into §5. |
| §5.1 | Explains Archive/Report split. | Add back-links: "This is why the CI flow in §4.1.C can compare old Archive files and why the public schemas in §8.2 matter." |
| §5.3 | Defines Lens protocol. | Add forward link to governance: "The hook signatures are one of the stable public surfaces listed in §8.2." |
| §6.1 | Contains requirements already introduced in §2.2. | Start with: "§2.2 motivates why ExecuTorch needs a workflow-aware viewer; this section defines the concrete boundaries." |
| §7 | Roadmap mentions Report JSON and `--compare` implemented but proposed. | Link to §8.2: "Because these imply stable schemas, they remain proposed until the compatibility contract in §8.2 is accepted." |
| §8.1 | Ownership boundaries relate directly to Q1. | Add: "Q1 in §9 asks whether this binary split is sufficient." |
| §8.2 | Stability surfaces relate directly to Q2/Q3. | Add: "Q2 and Q3 in §9 ask reviewers to validate the stability tiering and announcement mechanism." |
| §9 Q1 | References §8.2 only in recommendation. | Add explicit links to §8.1 and §5.3 in prompt. |
| §9 Q2 | References §8.2. | Also link to §7 roadmap because proposed features depend on schema stability. |
| §9 Q3 | References §8.2. | Good; split paragraph for readability. |

### 2.2 Places where content should be moved instead of cross-linked

1. **Move §4 glossary into §5.2 or reduce to a one-line preview.**  
   The full concept definitions belong in §5.2, where they are already explained through a run.

2. **Move §4.1.C ASCII architecture diagram into §5.1 or convert it into a CI-specific example after §5.1.**  
   It explains Session → Archive → Report, which is core architecture, not merely a demo.

3. **Move the long demo report tables into an appendix or collapsible “Demo evidence” subsection.**  
   The tables are useful for validation but not for first-pass comprehension.

4. **Move the detailed `fx_viewer` value bullets from §1/§2.2 into §6 if §1 should stay concise.**  
   Since §1 is polished, do not edit unless necessary; instead ensure §2.2 only motivates and §6 specifies.

5. **Move the “Note on Demo Scope” closer to §7 roadmap or keep it in §4.1.A but shorten.**  
   The note is important, but its current placement interrupts the maintainer persona walkthrough.

---

## 3. Paragraph-Length Audit — 5 Worst Offenders

### Offender 1 — §2.1, Inspector/devtools primitive paragraph + bullet sequence

Quoted start:

> "ExecuTorch’s existing devtools provide excellent primitives for raw capture. In particular, the `Inspector` and `ETRecord`/`ETDump` APIs offer a great primitive interface for dumping arbitrary runtime binary blobs..."

Why it is hard to read:

- It contains the setup plus four dense bullets.
- The first bullet, "No Shared Lifecycle Contract," is itself a mini-section.
- It combines tool praise, current gap, examples, lifecycle sequencing, extension model, graph correlation, and output synthesis in one block.

One key claim:

> Existing tools capture raw data well, but ExecuTorch lacks a shared workflow layer that coordinates lifecycle, backend analysis, graph correlation, and synthesized outputs.

Recommended restructure:

- Keep the opening paragraph to 2–3 sentences.
- Convert the four bullets into a table with columns: **Gap**, **Current workaround**, **Why it matters**.
- Move detailed Inspector correlation language to §2.3.
- Add cross-reference to §5: "The shared lifecycle contract proposed in §5 addresses these four gaps."

Suggested structure:

```markdown
ExecuTorch already has strong raw-capture primitives: `ETRecord`, `ETDump`, and `Inspector`. The missing layer is not another binary trace format; it is the workflow around those primitives.

| Gap | Current workaround | Consequence |
|---|---|---|
| Shared lifecycle | Per-backend wrapper scripts | No reuse across backends |
| Extension common ground | Backend-private analysis scripts | Analysis logic cannot compose |
| Graph-anchored correlation | DataFrame interpretation scripts | Hard to review visually |
| Multi-concern synthesis | CSVs/logs/screenshots | Hard to share or parse in CI |
```

### Offender 2 — §4.1.A, Backend Debug-Logic Maintainer “Today” bullet

Quote:

> "**Today (The Pain):** ExecuTorch's `Inspector` provides `calculate_numeric_gap()` for AOT-vs-runtime comparison, but using it requires writing manual Python scripts. Furthermore, Inspector's analysis is limited to the final Edge Dialect graph stored in `ETRecord` — it cannot see or compare accuracy across intermediate AOT compile-time stages (like `prepare_pt2e` and `convert_pt2e`) because those graph states are not stored in `ETRecord`. Each backend team must write its own wrapper scripts (e.g., Qualcomm's `qnn_intermediate_debugger.py`), ending up with disconnected CSVs and console logs rather than a unified visual report."

Why it is hard to read:

- It repeats §2.1/§2.3 problem framing.
- It embeds multiple distinctions: AOT-vs-runtime, final Edge graph, intermediate compile stages, wrapper scripts, output formats.
- In a persona section, the reader expects a quick use case, not detailed tool boundary analysis.

One key claim:

> Backend maintainers need reusable per-layer accuracy logic that can cover intermediate compile-time stages and produce one report instead of backend-specific scripts and disconnected outputs.

Recommended restructure:

```markdown
* **Today:** The fragmentation described in §2.1/§2.3 appears here as backend-specific accuracy scripts and disconnected CSV/log outputs.
* **Missing capability:** Inspector can analyze final ETRecord/ETDump correlations, but intermediate AOT stages such as `prepare_pt2e` and `convert_pt2e` need a separate capture/synthesis layer.
* **With Observatory:** A backend owner writes one Lens; Observatory handles lifecycle, snapshots, and report generation.
```

### Offender 3 — §4 concept glossary block

Quoted start:

> "**💡 Key Vocabulary & Mental Models**  
> To assist first-time readers in skimming this section, here are the core concepts of the Observatory architecture (fully defined in **§5.1**):"

Why it is hard to read:

- It defines six terms before the architecture section.
- It duplicates §5.2, which is better because it explains the vocabulary through a run.
- It includes a disambiguation note about Observatory Record vs ETRecord, which also appears again in §5.2.

One key claim:

> The reader needs a minimal vocabulary preview before the demos.

Recommended restructure:

Keep only a compact preview and link forward:

```markdown
> **Vocabulary preview:** The demos below use the terms Session, Region, Record, Archive, Report, and Lens. §5.2 defines them through a concrete run. In short: a Session contains Regions; Regions contain Records; Records are serialized into an Archive; lenses analyze an Archive into HTML/JSON Reports.
```

Move the detailed definitions and ETRecord disambiguation fully to §5.2.

### Offender 4 — §5.3, concrete Accuracy lens example numbered list

Quoted start:

> "1. `on_session_start` — prepares a small calibration dataset and installs pipeline patches.  
> 2. `observe` — watches for `GraphModule` artifacts at each collection point; returns `None` for non-graph records.  
> 3. `digest` — runs both the float-reference and quantized graphs on the calibration batch, serializes per-operator PSNR/cosine/MSE into the Record. *(This executes online because live Python graph objects are not serializable — the raw measurements must be materialized at capture time.)*"

Why it is hard to read:

- The list is useful, but item 3 is much denser than the others and carries a crucial architectural exception: `digest` can perform online reduction even though analysis is offline.
- The parenthetical is important enough to be a note, not buried inside a list item.

One key claim:

> The Accuracy lens demonstrates why capture-time digesting is sometimes necessary: live graph objects cannot be persisted, so reduced metrics must be materialized online.

Recommended restructure:

- Keep the lifecycle list, but make `digest` shorter.
- Add a separate note immediately after the list.

```markdown
3. `digest` — materializes per-operator PSNR/cosine/MSE into the Record.

> **Why digest runs online:** Live Python graph objects are not serializable. The lens does not persist the raw graph execution state; it persists reduced measurements that offline analysis can later rank and render.
```

### Offender 5 — §9 Open Questions, each question paragraph block

Example quote from Q1:

> "**Prompt for reviewers:** Today the rule is binary — generic lenses live in `devtools/observatory/lenses/`, backend-specific lenses live in `backends/<name>/...`. (1) Is a binary split enough, or do we need a recognized *middle tier* for lenses shared by two-or-more backends but not truly universal..."

Why it is hard to read:

- The section is good, but each question is a wall of prompt/trade-off/recommendation prose.
- Reviewers need to respond quickly; dense paragraphs slow that down.
- The questions are already structured conceptually, so they should be visually structured too.

One key claim:

> Each open question asks reviewers to accept, amend, or reject a concrete governance recommendation.

Recommended restructure:

Use the same sub-bullets for each Q:

```markdown
### Q1 — Where is the line between core and backend ownership?

**Decision requested:** Keep binary core/backend split for v1, or add a middle tier?

**Context:** Generic lenses live in ...; backend-specific lenses live in ... (§8.1).

**Trade-off:**
- Middle tier: less duplication, more ownership ambiguity.
- Binary split: simpler governance, possible copy-paste.

**Starting recommendation:** Keep binary split for v1...
```

---

## 4. Section Reordering Proposal

### 4.1 Recommended order for a 30-minute reviewer

Recommended structure:

1. Abstract
2. §1 Summary
3. §2 Motivation & Problem Statement
4. §3 Goals, Non-Goals, and Boundaries
5. §4 User-Facing Surfaces
6. §5 Architecture: Capture First, Analyze Later
7. §6 Working Demos / Use Cases
8. §7 `fx_viewer`
9. §8 Scope & Roadmap
10. §9 Governance and API Stability
11. §10 Open Questions for Reviewers
12. Appendix: Demo links, generated reports, videos

This is not a full rewrite; it is mostly a split and reorder of current §4–§9.

### 4.2 Specific changes

#### Change 1 — Split current §4 into “Surfaces” and “Demos”

Current §4 title:

> "Proposed User-Facing Capabilities & Working Demos"

Problem: it mixes reviewable API surface with evidence and demo assets.

Proposal:

- New §4: **User-Facing Surfaces and Output Types**
  - Move current §4.2 here.
  - Include CLI, context manager, decorator.
  - Include Human/Machine output kinds.
  - End with transition: "The split between raw capture and derived analysis is the central design decision; §5 explains it."

- New §6 or Appendix: **Working Demos and Persona Walkthroughs**
  - Move current §4.1 here.
  - Compress “Today” pain bullets using links to §2.
  - Keep screenshots and links as evidence.
  - Move long report tables to appendix.

Cognitive-load justification: reviewers first learn the stable surfaces they are being asked to accept; demos then validate that those surfaces solve real workflows.

#### Change 2 — Move architecture before detailed demos

Current order puts demos before §5. Proposal puts §5 before detailed demos.

Why: The reader needs the capture/analyze split before understanding Archive JSON, Report JSON, `--compare`, and CI late-bound analysis. Without §5, §4.1.C’s CI flow is mechanically understandable but architecturally under-motivated.

#### Change 3 — Merge §2.3 and §3 Non-Goals more tightly

Current §2.3 says:

> "Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them."

Current §3 Non-Goals says:

> "**Replacing or Extending Inspector/ETRecord:** Observatory defines no new binary capture formats, no new runtime instrumentation hooks, and no new ETDump/ETRecord schemas."

These are the same boundary, expressed twice. Options:

- Keep §2.3 as the detailed boundary and shorten §3 Non-Goals to a concise checklist with cross-link.
- Or rename §3 to **Goals, Non-Goals, and Boundaries** and move §2.3 under §3.

Recommendation: keep §2 focused on pain and comparison; move the boundary detail into §3. That makes §3 more useful as the contract section.

#### Change 4 — Keep §6 `fx_viewer`, but ensure it follows architecture or demos consistently

Two viable placements:

- If §6 remains after architecture: good, because `fx_viewer` is one implementation component of report rendering.
- If demos remain before architecture: `fx_viewer` will continue to feel like a late explanation of an already-used concept.

Recommendation: place `fx_viewer` after architecture and before roadmap.

#### Change 5 — Rename §7 to clarify status semantics

Current title:

> "Scope & Roadmap"

Problem: table columns include "Shipped in Draft Branch," "Proposed in This RFC," and "Future Work," then the note says some proposed items are already implemented in POC. This is subtle and can confuse reviewers.

Recommended title:

> "Scope, RFC Acceptance Boundary, and Roadmap"

Add one lead sentence:

> "This table separates implementation existence from API stability: some POC features exist in the draft branch but remain proposed until their schemas and contracts are accepted."

#### Change 6 — Consider promoting governance before roadmap only if reviewers are API-focused

Current §7 Roadmap before §8 Governance is acceptable. However, because §7’s proposed items depend on schema stability, governance could come first:

- §7 Governance and API Stability
- §8 Scope, RFC Acceptance Boundary, and Roadmap
- §9 Open Questions

Recommendation: keep roadmap before governance unless the target reviewers are primarily API owners. Add cross-links instead.

---

## 5. Redundancy Map

### 5.1 Observatory is not replacing Inspector/ETRecord

Instances:

1. Top positioning note:
   > "Observatory is not a replacement for `ETRecord`, `ETDump`, `Inspector`. It is a coordination layer that sits above them."

2. §2.3:
   > "Observatory does not replace existing ExecuTorch runtime capture or analysis primitives — it is a client of them."

3. §2.3 table row:
   > "Replaces any of the above? ... **No**"

4. §3 Non-Goals:
   > "**Replacing or Extending Inspector/ETRecord:** Observatory defines no new binary capture formats, no new runtime instrumentation hooks, and no new ETDump/ETRecord schemas."

Recommendation:

- Keep the top positioning note and §2.3 detailed explanation.
- Keep the comparison table row because it is scan-friendly.
- Compress §3 Non-Goal to one line: "Does not replace or extend Inspector/ETRecord schemas; see §2.3."

### 5.2 Inspector final-graph limitation vs intermediate compile-time snapshots

Instances:

1. §2.1:
   > "captures the intermediate FX graph states at `prepare_pt2e` and `convert_pt2e` — stages that are not stored in ETRecord and are invisible to Inspector"

2. §2.3:
   > "capturing intermediate compile-time graph snapshots (pre-ETRecord stages invisible to Inspector)"

3. §4.1.A:
   > "Inspector's analysis is limited to the final Edge Dialect graph stored in `ETRecord` — it cannot see or compare accuracy across intermediate AOT compile-time stages..."

Recommendation:

- Keep the precise boundary in §2.3.
- Shorten §2.1 to problem symptom.
- Replace §4.1.A detail with a cross-reference to §2.3.

### 5.3 Lenses as self-contained debugging concerns

Instances:

1. Abstract:
   > "A lens is a self-contained debugging concern — it handles both capturing data during the run and analyzing it afterward."

2. §1:
   > "A lens is a self-contained debugging concern — it includes callbacks for both capturing data during the run and analyzing it afterward."

3. §3 Goals:
   > "Define a lightweight protocol (**Lens**) allowing backend teams to encapsulate one debugging concern..."

4. §4 glossary:
   > "**Lens:** A plug-in class that handles a single debugging concern..."

5. §5.3:
   > "A lens needs to do two things at two different times: react during capture... and reason offline..."

Recommendation:

- Keep Abstract and §1 because they are summary surfaces.
- Keep §5.3 as canonical definition.
- In §3, shorten to "Define the Lens protocol (§5.3)."
- In §4 glossary, replace with one-line preview or remove.

### 5.4 Three invocation surfaces: CLI, context manager, decorator

Instances:

1. §1 detailed bullet list:
   > "CLI — run your existing model script... Decorator — add `@observe_pass`... Context manager — wrap a `with Observatory.enter_context(...)` block..."

2. §3 Goals:
   > "Support zero-code-change CLI execution, nested Python context managers, and pass-level decorators."

3. §4.1.A CLI walkthrough.

4. §4.1.B decorator/context manager code walkthrough.

5. §4.2 full surface descriptions.

Recommendation:

- Keep §1 summary list.
- Keep §4.2 as canonical detailed surface section.
- In §3, cross-link to §4.2.
- In §4.1 demos, avoid re-explaining the surfaces; simply show usage.

### 5.5 Archive JSON vs Report HTML/JSON split

Instances:

1. Abstract:
   > "For CI: the same command produces a structured JSON report..."

2. §4 glossary:
   > "**Archive (JSON):** The raw, persisted, unrendered data file... **Report (HTML / JSON):** The derived, analyzed output..."

3. §4.1.C:
   > "Nightly pipelines save only a lightweight, raw `Archive JSON` file... Later... generate a synchronized comparative HTML Report or a machine-readable Report JSON summary..."

4. §4.2:
   > "Human: A self-contained Report HTML... Machine: A raw Archive JSON... and a derived Report JSON..."

5. §5.1:
   > "That file is the **Archive**... From it, Observatory derives the **Report**..."

6. §7 roadmap table: Report JSON and `--compare`.

Recommendation:

- Keep §5.1 as canonical explanation.
- Keep §4.2 as user-facing output summary.
- Compress §4 glossary and §4.1.C architecture description into links to §5.1.
- §7 should refer to "the Archive/Report split from §5.1."

### 5.6 Region / Record tree concept

Instances:

1. §4 glossary:
   > "**Region:** A named, logical scope used to group and nest captures..."

2. §4.1.B:
   > "A **Region** is a logical execution scope opened by `enter_context(region_name)`. It supports nesting and configuration inheritance."

3. §5.2:
   > "Regions are pure labels: nested named scopes (stored as a `region_stack` list)..."

Recommendation:

- Keep §5.2 as canonical definition.
- Keep §4.1.B as UI/demo explanation but start with "As defined in §5.2..."
- Remove detailed Region definition from §4 glossary.

### 5.7 `fx_viewer` server-free, embeddable, layered graph viewer

Instances:

1. §1:
   > "`fx_viewer` is a Python and JavaScript library for embedding interactive FX graph views into any HTML page..."

2. §2.2:
   > "The `torch.fx` graph module is the core IR... developers have no easy way to interact with it in-pipeline"

3. §2.2 conclusion:
   > "server-free, layered graph renderer"

4. §6:
   > "standalone, server-free, canvas-based graph visualizer"

Recommendation:

- Keep §1 summary and §6 detailed spec.
- Make §2.2 purely motivational and add "specified in §6."
- Avoid repeating detailed features in §2.2 if they are already in §6.

### 5.8 CI / comparison flow

Instances:

1. §1 CI persona:
   > "CI pipelines run the same command and consume a structured JSON report..."

2. §4.1.C:
   > "Compare execution runs across branches, dates, or backends..."

3. §5.1:
   > "Regression comparison: Two archives from different commits diff directly via `--compare`..."

4. §7 roadmap table:
   > "`--compare` CLI Mode"

Recommendation:

- Keep §1 as summary.
- Keep §5.1 as architecture reason.
- Keep §4.1.C as demo/application but shorten architecture explanation.
- §7 should only state status, not re-explain flow.

### 5.9 Ownership: core vs backend lenses

Instances:

1. Abstract:
   > "Backend teams write and maintain their own lenses for backend-specific analysis."

2. §8.1:
   > "Core devtools reviewers own... Backend teams own..."

3. §9 Q1:
   > "Today the rule is binary — generic lenses live in `devtools/observatory/lenses/`, backend-specific lenses live in `backends/<name>/...`."

Recommendation:

- Keep Abstract and §8.1.
- In §9 Q1, explicitly reference §8.1 instead of restating the full rule in prose.

### 5.10 Stability surfaces and schemas

Instances:

1. §7 note:
   > "presented in this RFC as 'Proposed' to seek active design reviews and establish stable API and schema contracts..."

2. §8.2:
   > "four public surfaces are designated as **stable contracts**"

3. §9 Q2:
   > "Should each lens ... declare an experimental / stable tier..."

Recommendation:

- Keep §8.2 as canonical.
- Keep §9 Q2 as decision request.
- Add a cross-reference in §7 note to §8.2; do not explain stability twice.

---

## 6. Practical Revision Plan

If editing time is limited, prioritize these changes in order:

1. **Split current §4:** put §4.2 before persona demos; move long demo tables to appendix.
2. **Make §5 arrive earlier or transition to it faster:** the capture/analyze split is the core design.
3. **Compress repeated Inspector/ETRecord boundary language:** keep §2.3 canonical; shorten §3 and §4 references.
4. **Reduce §4 glossary to a preview:** keep full vocabulary in §5.2.
5. **Reformat §9 questions into scannable bullets:** same content, lower reviewer friction.
6. **Fix markdown artifacts in §6/§7:** remove literal `\n` sequences and ensure bullets/table/note render correctly.

---

## 7. Suggested Revised Table of Contents

```markdown
## 1. Summary
## 2. Motivation & Problem Statement
  ### 2.1 Fragmented Debugging Workflow
  ### 2.2 Missing Workflow-Aware Graph Viewer
  ### 2.3 Relationship to Existing ExecuTorch Tools
## 3. Goals, Non-Goals, and Boundaries
## 4. User-Facing Surfaces and Outputs
  ### 4.1 CLI
  ### 4.2 Python Context Manager
  ### 4.3 Pass Decorator
  ### 4.4 Output Types: Archive JSON, Report HTML, Report JSON
## 5. How It Works: Capture First, Analyze Later
  ### 5.1 Foundational Split
  ### 5.2 Vocabulary, Built From a Run
  ### 5.3 Lens Protocol
## 6. Working Demos and Persona Walkthroughs
  ### 6.1 Backend Debug-Logic Maintainer
  ### 6.2 AOT Pipeline / Pass Author
  ### 6.3 CI / Nightly Regression / Cross-Backend Triage
## 7. `fx_viewer` — Layered Graph Visualizer
## 8. Scope, RFC Acceptance Boundary, and Roadmap
## 9. Governance and API Stability
## 10. Open Questions for Reviewers
## Appendix A. Demo Reports, Videos, and Generated Assets
```

This order optimizes for a first-time reviewer: understand the problem, verify boundaries, learn the surfaces, understand the architecture, then inspect demos and governance decisions.
