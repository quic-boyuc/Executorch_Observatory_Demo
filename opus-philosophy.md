# Observatory RFC — Philosophy & Narrative Strategy Review
*Reviewer: Claude-Opus-4.7 (Philosophy & Narrative Specialist)*
*Scope: §2–§9, with §1/Abstract treated as fixed.*

---

## 1. The RFC's Implicit Philosophy

**The deeper argument is this:** *debugging infrastructure should be designed like an event-sourcing system, not like a dashboard.* The act of observing a compilation is irreversible and expensive, but the act of interpreting it is cheap, iterative, and opinion-laden — so the tool's job is to capture a complete, neutral, replayable record and then let many independent interpreters (lenses) reason over it later, possibly weeks later, possibly across runs.

The corollary the RFC implicitly defends: **a debugging tool's value is measured by what it lets you ask *after* the run, not by what it shows you *during* it.** Every architectural choice — Archive vs. Report, the eight-method Lens protocol, `--compare`, the JSON frontend, the server-free HTML — falls out of that single commitment to separating "what happened" from "what it means."

This is the principle the RFC is really arguing for, but it states it only once, late, and almost in passing (§5.1). Everything before §5 reads like product marketing for a feature; §5.1 is where the RFC finally *thinks*.

---

## 2. Narrative Arc Assessment

A healthy RFC arc: **pain → insight → solution → proof → adoption path.**

Current mapping:

| Arc beat | Where it lives | Verdict |
|---|---|---|
| Pain | §2.1, §2.2 | Present, but bureaucratic. Reads like a four-bullet audit, not a story. |
| Insight | §5.1 ("capture is a different job from analysis") | **Buried.** This is the thesis of the whole RFC and it appears on page 8. |
| Solution | §4 (surfaces, demos) + §5 (architecture) + §6 (fx_viewer) | Inverted: §4 shows the solution *before* the insight that justifies it. |
| Proof | §4.1 demos, comparison tables, hosted reports | Strong, but front-loaded — proof arrives before the reader knows what's being proven. |
| Adoption path | §7 (roadmap), §8 (governance), §9 (open questions) | Solid and well-structured. The only part of the RFC where pacing is right. |

**Where the arc breaks:**

1. **Insight is buried behind solution.** §4 spends ~150 lines walking through CLI flags, decorators, video links, and demo tables before §5.1 finally explains *why* any of this is shaped the way it is. A first-time reader experiences §4 as "here is a tool with a lot of features"; only at §5.1 does it become "here is a principle, and the features are consequences of it."

2. **Pain is fragmented across three loci.** §2.1 lists four sub-pains, §2.2 adds two more, §2.3 then *retracts territory* ("Observatory is not a replacement…"). By the time the reader reaches §3 Goals, the pain has been re-stated, qualified, and bounded so many times that emotional momentum is gone. The pain should hit once, sharply.

3. **Momentum dies between §4 and §5.** §4.2 ("Surfaces") is essentially a recap of §1 in long form, then §5.1 restarts the architectural argument from scratch. The reader pays the cognitive cost of two openings.

4. **§6 is a structural orphan.** It's introduced as if it were a co-equal proposal, but the rest of the RFC treats `fx_viewer` as Observatory's rendering substrate. The reader can't tell whether `fx_viewer` is a peer system, a dependency, or an implementation detail.

5. **§9 is the strongest section but reads as an afterthought.** The "Starting recommendation to react to" framing is excellent RFC craft — it's the only section that respects the reviewer's time by pre-committing to an opinion. The rest of the RFC should be calibrated to this voice.

---

## 3. Reader Persona Analysis

The RFC declares three personas (Backend Maintainer, Pass Author, CI Engineer) and uses them as the spine of §4.1. **The structure over-serves the Backend Maintainer and under-serves the other two.**


**Evidence:**

- **Backend Maintainer (Persona A):** Receives the longest walkthrough, the full CLI example, the demo videos, the entire pre-generated reports matrix (5 single-run reports), the explanation of `lens-recipe`, and is implicitly the protagonist of §5.3 (the Lens protocol). Word-count dominance: ~45% of §4.
- **Pass Author (Persona B):** Gets a single code snippet about decorators and nested contexts. The walkthrough never actually shows a *graph diff* — the headline feature for this persona. The Region tree is shown, but the "select two stages → synchronized comparison" workflow is told, not demoed.
- **CI Engineer (Persona C):** Gets an ASCII architecture diagram, a two-step CLI example, and a cross-backend comparison matrix. But the actual *CI integration story* — how does this slot into GitHub Actions? what does a failing gate look like? what does the LLM consume? — is absent. The persona is named but not served.

**The accidental over-service:** Persona A's content effectively serves as the architectural exposition for the whole RFC. A backend maintainer reading §4.A learns about lens-recipes, intermediate stages, ETRecord boundaries, AOT vs. runtime scope — content that is really *architectural framing*, not persona-specific. This conflates "introducing the architecture" with "serving persona A," and the other personas pay the cost.

**Diagnostic question for each persona:** *Could this reader, after reading the RFC, write the first hundred lines of their own integration?*
- Persona A: yes (lens skeleton in §5.3 is sufficient).
- Persona B: no (no concrete diff example, no decorator semantics around exceptions / re-entrancy).
- Persona C: no (no example of programmatically reading Report JSON, no schema, no exit-code convention).

---

## 4. The "So What" Test — One-Sentence Takeaways

For each section §2–§9, the takeaway the reader *should* leave with, and whether the section actually delivers it efficiently:

| § | Intended takeaway (one sentence) | Delivered? | Diagnosis |
|---|---|---|---|
| §2 | "Every backend rebuilds the same five-stage debug script, and there is no shared place for the analysis logic to live." | ⚠️ Partially | The takeaway is there but split across §2.1 (four bullets), §2.2 (two bullets), §2.3 (a retraction + a table). Reader has to assemble it. The comparison table belongs in §5, not §2. |
| §3 | "Observatory adds a coordination layer; it does not replace any existing capture primitive." | ✅ Yes | This section is the right length and the Non-Goals are sharp. Keep as-is. |
| §4 | "Three personas, three entry points, two artifact kinds — all funnelling into the same capture machinery." | ❌ Buried | The headline (§4.2's last line: "the split between raw capture and derived analysis is the central design decision") is the actual takeaway, but it appears as a transition sentence at the end. §4 is structured as a feature tour, not as evidence for a thesis. |
| §5 | "Capture and analysis are different jobs separated by an Archive file; the Lens protocol is the API to both sides of that boundary." | ✅ Yes (§5.1) / ⚠️ §5.2 dilutes | §5.1 nails it. §5.2's "vocabulary built from a run" is a *good* device but it re-teaches material §1 and §4 already covered. §5.3 is sharp. |
| §6 | "fx_viewer is the rendering substrate; it has a clean Python/JS boundary and is independently usable." | ⚠️ Partially | Section is too short and too late. Reader has been told 'interactive graph' eight times by now without knowing what makes it independent of Observatory. |
| §7 | "Here's what already works, what this RFC is asking you to ratify, and what comes later." | ✅ Yes | Roadmap table is excellent — the clearest section in the document. |
| §8 | "Core owns the protocol and schemas; backends own their lenses; four surfaces are stable contracts." | ✅ Yes | Crisp and correctly scoped. |
| §9 | "Three concrete decisions need a yes/no from reviewers, and here's our recommended yes for each." | ✅ Yes | Best-written section. The "starting recommendation to react to" pattern should retrofit into earlier sections. |

**Pattern:** The sections that *commit to an opinion* (§3, §7, §8, §9) deliver their takeaway efficiently. The sections that *tour features* (§2, §4, §6) bury their takeaway under enumeration.

---

## 5. Descriptive Strategy Recommendation

**The unified organizing principle should be: *Principle → Mechanism → Evidence.***

That is: every section in §2–§9 should open with a one-paragraph claim about a principle or boundary, then describe the mechanism that enforces it, then point to concrete evidence (code, demo link, table) that the mechanism works. Today the RFC uses three different rhetorical modes interchangeably — feature catalog (§4), bullet-list pain audit (§2), narrative exposition (§5.1, §5.2) — and the inconsistency makes the document feel longer than it is.

Why *Principle → Mechanism → Evidence* fits this RFC specifically:

1. **The RFC's core argument is itself a principle** (capture ≠ analysis). The document should model the structure it's advocating: state the principle first, then show how the architecture is a faithful implementation of it.
2. **Reviewers triage by principle.** A core-devtools reviewer reading §5 doesn't need the demo videos; they need the protocol contract. A backend owner reading §4 doesn't need the JSON schema; they need to see that their workflow is supported. Opening each section with its principle lets readers self-route in three seconds.
3. **It forces every demo to earn its place.** Right now, demos appear because they exist. Under Principle → Mechanism → Evidence, a demo is included only when it provides evidence for a specific claim — which prunes the long pre-generated-reports table from §4 down to the two or three reports that prove a stated claim.

**Rejected alternatives:**

- *Problem-Solution Pairs:* Tempting because §2 is a pain enumeration, but it would force each pain into a 1:1 mapping with a feature, which mis-describes the actual architecture (one principle → many features).
- *Progressive Disclosure:* Already partially in use (§1 → §4 → §5), but the disclosure ordering today is wrong: features before principles. Progressive disclosure works only when each layer adds depth to the *same* idea; the current draft adds breadth instead.
- *Definition-First Then Example:* Works for §5.2's vocabulary, but applied globally it would make §2's pain section read like a glossary.

---

## 6. Top 5 Structural Changes — Ranked by Impact

### #1 — Promote §5.1 ("Capture First, Analyze Later") to immediately after §3 Goals.

**Impact:** Maximum. This is the RFC's actual thesis and it is currently in position 7 of the document. Moving it forward means every subsequent section — surfaces, personas, lens protocol, fx_viewer, governance — reads as a *consequence* of a stated principle rather than as a parade of features. The current §4 demos become evidence for the thesis, not a substitute for it.

Concretely: rename the new section "§4. Design Principle: Capture and Analysis Are Different Jobs," keep its diagram, and let the rest of the RFC renumber. The current §4 (personas + surfaces) moves to §5 and is reframed as "Three Ways the Principle Shows Up in the Workflow."

### #2 — Collapse §2.1, §2.2, §2.3 into a single, sharp §2 that hits the pain *once*.

**Impact:** High. Today §2 has four sub-pains, two graph-pains, a retraction, and a comparison table — the pain dissipates across half a page. Replace with: (a) one paragraph naming the workflow (instrument → configure → export → analyze → visualize), (b) one paragraph naming the cost (every backend rebuilds it; analysis logic has no home), (c) the comparison table moves to §5 where it belongs as architectural positioning, not pain evidence. Cut the "Boundaries and Relationship with Existing Tools" subsection — its content belongs in §3's Non-Goals (which already says it) and §5's positioning.

### #3 — Restructure §4 around the *split*, not around personas.

**Impact:** High. The persona structure is rhetorically appealing but produces three parallel feature tours that re-cover the same architecture three times. Instead: open §4 with the capture/analysis split (post-move from §5.1), then show *one* unified walkthrough that touches all three personas — capture happens once (CLI), analysis runs many times (HTML for reviewer A, JSON for CI engineer C, decorator/region tree for pass author B). The personas become *roles in one story* rather than three separate stories. This also fixes the persona-imbalance problem (§3 above) by giving each persona equal screen time within one narrative.

### #4 — Demote the pre-generated-reports tables from inline §4 to an Appendix.

**Impact:** Medium-high. The two large tables (5 single-run reports + 5 cross-backend comparisons) are *evidence*, not exposition. They interrupt the narrative at exactly the moment the reader is trying to absorb the architecture. Move both tables to "Appendix A: Demo Report Index" with a single inline link from §4 ("Ten worked examples — five single-run, five cross-backend comparisons — are listed in Appendix A"). Keep one or two screenshots inline as illustration; everything else goes to the appendix. This alone reclaims ~60 lines of vertical space in the most-skimmed section.

### #5 — Rewrite every section opener to follow the §9 pattern: *claim → mechanism → recommendation/evidence.*

**Impact:** Medium, but compounding. §9's "Prompt → Trade-off → Starting recommendation" is the best rhetorical pattern in the document because it pre-commits to an opinion the reviewer can accept, amend, or reject. Retrofit a lighter version of this pattern as the opening 2–3 sentences of every section in §2–§8: state the claim, name the mechanism, point at the evidence. This is the operational form of the Principle → Mechanism → Evidence strategy from §5 above, and it converts a feature-tour document into an argument-shaped document without rewriting any content — only re-ordering and re-framing.

---

## Closing Note

The RFC's content is strong; its *ordering* fights its own argument. Today a reader meets the features before they meet the principle the features serve, and meets three personas before they meet the one architectural split that unifies them. The fix is not more writing — it is moving §5.1 forward, collapsing §2's redundancy, and letting the capture/analysis split (the RFC's actual thesis) carry the narrative weight it has earned but not yet been given.

The §9 "starting recommendation" voice is the voice the rest of the RFC should adopt. It respects the reviewer's time, it commits to a position, and it invites disagreement on specific terms. Everything else is a craft question downstream of those three structural moves.
