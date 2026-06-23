### 6.1 Persona A: Backend Debug-Logic Maintainer and Debugging Engineer / Issue Reporter

- **Backend debug-logic maintainer:** write the backend-specific Lens logic once, such as graph capture or accuracy analysis, and let Observatory run it across many models and scripts.
- **What Observatory handles:** session setup, monkey-patching standard APIs (`prepare_pt2e`, `convert_pt2e`, `to_edge_transform_and_lower`), snapshot collection, report generation, and cleanup.
- **Debugging engineer / issue reporter:** run one CLI command around an existing model script; no source edits are required.
- **Key value:** the reporter does not need to understand Lens internals, patching, or Observatory's record format. They only run the wrapper and share the output.

```bash
python -m executorch.backends.qualcomm.debugger.observatory \
    # Observatory wrapper: module path plus Observatory flags. \
    --output-html obs_report.html \
    # Observatory wrapper: "accuracy" is a preset bundle of lenses, \
    # for example graph snapshots plus per-layer accuracy analysis. \
    --lens-recipe accuracy \
    # Original unmodified user script starts here. \
    # Everything below is passed through unchanged to that script. \
    examples/qualcomm/oss_scripts/mobilevit_v2.py \
    --backend htp --model SM8650 -d ./imagenet-mini-val/ \
    -b build-android/ --compile_only
```

- The generated HTML report is self-contained: reviewers can open it locally without rerunning the model or reconstructing loose logs.
- This makes bug reports immediately actionable: attach the HTML to a GitHub issue or PR, and reviewers can inspect the captured graphs, lens outputs, and run context in one file.
