# Observatory + fx_viewer — Condensed Summary (PPT)

## `fx_viewer` vs. Model Explorer

> Complementary, not a replacement: Model Explorer = general model browsing; `fx_viewer` = in-pipeline, multi-stage compiler debugging.

| Need | Model Explorer (ExecuTorch integration) | `fx_viewer` |
|---|---|---|
| **Compare many graphs** | 2 graphs (split-pane) | N-way (3+); auto many-to-many node sync |
| **Data on the graph** | Namespace grouping only; other values need a separate JSON, op-nodes only | Programmatic colors / labels / per-node data, in one payload |
| **Share the result** | Local server + browser tab; not shareable as-is | One standalone HTML file, no server |
| **Small & extensible** | Angular + three.js + d3 (~50k LoC), external team | Plain JS on Canvas (~4.5k LoC), in ExecuTorch devtools |

## `Observatory` — Problem → Solution

> A coordination layer above `Inspector` / `ETRecord` / `ETDump` (it does not replace them).

| Problem today | How `Observatory` solves it |
|---|---|
| **Each backend rebuilds its own glue** (start / collect / analyze / stop) | A **Lens** holds one debugging concern once; the framework runs the lifecycle, storage, and report |
| **Output is scattered** (prints, CSVs, screenshots) | One self-contained **HTML** report for people + structured **JSON** for CI |
| **Can't re-analyze or compare past runs** without re-running | Capture split from analysis: lightweight **Archive JSON** enables late re-analysis and `--compare` |
