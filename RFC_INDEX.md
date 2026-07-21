# RFC Document Index

This repository contains multiple RFC drafts and supporting analysis documents
produced across several revision cycles. This index maps each file to its role
and status so reviewers can go directly to the current material.

---

## ✅ Current / Active Documents

These are the files to read for the latest state of the proposal.

| File | What it is |
|------|-----------|
| **[rfc_fx_viewer_draft.md](./rfc_fx_viewer_draft.md)** | **RFC-A (latest)** — `fx_viewer` proposal. Gap analysis vs. Model Explorer, full API reference including `FXGraphCompareExporter` and ETRecord adapter, live demo links. Start here for the viewer RFC. |
| **[rfc_split_strategy.md](./rfc_split_strategy.md)** | **RFC-B outline** — Observatory proposal in bullet form (zh-TW). Motivation, benefit comparison vs. Inspector + ETRecord, Joint Demo section, and writing notes for both RFCs. |
| **[rfc_api_comparison.md](./rfc_api_comparison.md)** | **Detailed comparison tables** — Side-by-side API surface and benefit analysis for both RFCs: `fx_viewer` vs. ME, Observatory vs. Inspector. Includes code snippets and per-benefit breakdowns. |
| **[rfc_api_design_eval.md](./rfc_api_design_eval.md)** | **API placement analysis** — Evaluates where `fx_viewer` and Observatory should live in the `devtools/` tree, and whether Observatory should be part of the Inspector API (conclusion: no). |
| **[rfc_fx_viewer_comparison.md](./rfc_fx_viewer_comparison.md)** | **fx_viewer vs. ME deep-dive** — Structured 6-dimension comparison verified against the actual ME API docs and wiki. Covers node data, multi-graph compare, sync modes, output format, maintainability, and dependencies. |
| **[reference.md](./reference.md)** | **API reference companion** — Detailed Lens protocol, stable surface definitions, and collaboration policy. Companion to the original combined RFC. |

---

## 📜 Legacy / Revision History

These files are earlier drafts kept for reference. They are **not** the current proposal.

| File | What it is | Superseded by |
|------|-----------|---------------|
| [rfc_review_real.md](./rfc_review_real.md) | The combined RFC submitted to pytorch/executorch #20618. The version that received the "please split" comment. | `rfc_fx_viewer_draft.md` + `rfc_split_strategy.md` |
| [pr_description_refined.md](./pr_description_refined.md) | PR description for draft PR #19288. Covers the full Lens protocol and worked examples in detail. Still accurate as implementation reference. | — (still useful as impl detail) |
| [rfc_review.md](./rfc_review.md) | Earlier combined RFC revision (pre-#20618 submission). Multiple editing passes visible in git history. | `rfc_review_real.md` |
| [rfc_review_old.md](./rfc_review_old.md) | Even earlier combined RFC draft. | `rfc_review.md` |
| [rfc_sections_4.2_5.3_revised.md](./rfc_sections_4.2_5.3_revised.md) | Standalone revision of §4.2–§5.3 from `rfc_review.md`. | Merged into `rfc_review_real.md` |
| [rfc.md](./rfc.md) | Original combined RFC skeleton. | `rfc_review_real.md` |
| [rfc_concise.md](./rfc_concise.md) | Condensed single-page version of the combined RFC. | `rfc_fx_viewer_draft.md` + `rfc_split_strategy.md` |
| [rfc_draft_ai.md](./rfc_draft_ai.md) | Early AI-assisted draft. | `rfc_review.md` |
| [rfc_ppt_summary.md](./rfc_ppt_summary.md) | Condensed summary table for presentation slides. | — (still useful for slides) |

---

## 🔧 Implementation & Planning

| File | What it is |
|------|-----------|
| [observatory_todo_list.md](./observatory_todo_list.md) | Implementation hardening checklist for Observatory and fx_viewer. Tracks open tasks. |
| [progress.md](./progress.md) | Session progress notes. |

---

## Reading Order for Reviewers

**If you are reviewing RFC-A (`fx_viewer`) only:**
1. [`rfc_fx_viewer_draft.md`](./rfc_fx_viewer_draft.md) — the full RFC
2. [`rfc_fx_viewer_comparison.md`](./rfc_fx_viewer_comparison.md) — deeper ME comparison if needed

**If you are reviewing RFC-B (Observatory) only:**
1. [`rfc_split_strategy.md`](./rfc_split_strategy.md) — outline and motivation
2. [`rfc_api_comparison.md`](./rfc_api_comparison.md) — Observatory vs. Inspector benefit table

**If you are reviewing both:**
1. [`rfc_fx_viewer_draft.md`](./rfc_fx_viewer_draft.md)
2. [`rfc_split_strategy.md`](./rfc_split_strategy.md)
3. [`rfc_api_comparison.md`](./rfc_api_comparison.md) — unified comparison for both
4. [`rfc_api_design_eval.md`](./rfc_api_design_eval.md) — API placement rationale

**For implementation detail** (Lens protocol, stable surfaces):
- [`pr_description_refined.md`](./pr_description_refined.md)
- [`reference.md`](./reference.md)
