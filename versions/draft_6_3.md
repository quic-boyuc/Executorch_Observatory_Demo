### 6.3 Persona C: CI / Nightly-Regression / Cross-Backend Triage

* **Goal:** Make CI failures self-contained: not only pass/fail, but the debugging context needed to triage the failure.
* **Today:** CI says “accuracy dropped 2%.” The engineer must reproduce locally, add instrumentation, re-run the model, and search for where the drop happened.
* **With Observatory:** CI captures intermediate graphs, per-layer accuracy metrics, stack traces, and metadata into the same run artifact.
* When a regression fires, the engineer opens the HTML artifact and immediately sees which pass introduced the accuracy drop and which operators are affected.
* For most regressions, this removes the “reproduce locally” step: the CI report is the reproduction.
* The same report that a human opens in a browser can be parsed by an LLM triage bot — both consume the same structured data.

```bash
# Step 1: CI captures everything into one lightweight Archive JSON:
# graphs, per-layer metrics, stack traces, run metadata, and lens records.
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-archive nightly/2026-04-20/mv2.json \
    --lens-recipe=accuracy,graph,stack_trace \
    examples/xnnpack/aot_compiler.py --model_name=mv2 --delegate --quantize

# Step 2: On regression detection, compare two archives to generate a report
# that shows exactly what changed: passes, graph diffs, metrics, and operators.
python -m executorch.devtools.observatory \
    --compare nightly/2026-04-20/mv2.json nightly/2026-04-23/mv2.json \
    --output-html regression.html \
    --output-report-json regression.summary.json
```

* This same flow works across branches, dates, and backends because the comparison runs over archived structured records, not over a re-executed local model.
