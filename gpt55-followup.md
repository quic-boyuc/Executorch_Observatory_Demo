# Follow-up Structure Review — Section 1 Edits

1. **Do these changes affect the proposed section reordering plan?**

No. The original reordering recommendation still stands: the RFC should move through **Problem → Boundaries → User surfaces → Architecture → Viewer → Stability → Review questions**, with demos as supporting evidence. The Section 1 edits improve polish and reduce over-specificity, but they do not change the main structural issue: §4 still does too much before §5 explains the architecture.

2. **Does removing the roadmap paragraph change how §2–§9 should introduce themselves?**

Slightly, yes. Removing “The rest of this RFC develops these claims...” makes §1 less meta, which is good, but it increases the burden on later sections to provide their own transitions. Recommended implication: each major section should open with a one-sentence role statement, e.g.:

- §2: “This section explains the workflow gaps Observatory addresses.”
- §3: “This section defines what the proposal does and does not own.”
- §4: “This section shows the user-facing surfaces and demos.”
- §5: “This section defines the core architecture behind those surfaces.”
- §6: “This section specifies the viewer layer used by reports.”

3. **Does “task-specific” vs “backend-specific” create cross-reference issues with §2–§9?**

Potentially. “Task-specific logic” is more general and fits generic lenses, CI lenses, and future non-backend debugging concerns. But §2–§9 still often frame the extension need as **backend-specific analysis**. To avoid drift, use a consistent hierarchy:

- Observatory supports **task-specific lenses**.
- Some lenses are **backend-specific**.
- Others are generic or workflow-specific.

Sections §2.1, §3 Goals, §5 Lens protocol, and §8 ownership should explicitly reflect that hierarchy.

4. **Other structural implications**

- The CI edit strengthens the Archive/Report split; §5.1 should emphasize that HTML can be regenerated from archived JSON.
- Reordering `fx_viewer` bullets is structurally better: extensibility before performance matches the RFC’s central “layered report” argument.
- The compressed three-role summary is an improvement, but §4 should avoid re-expanding those roles into repeated problem statements.
