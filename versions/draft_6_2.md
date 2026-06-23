### 6.2 Persona B: AOT Pipeline / Pass Author

*   **Goal:** Find which compiler pass in an existing pipeline introduces accuracy loss or graph corruption—without modifying any pass source code.
*   **The Scenario:** You notice accuracy drops after QNN lowering. Instead of adding print statements to 30 passes, wrap the pass list and inspect the HTML report to identify which pass changed the graph unexpectedly.
*   **Zero-Invasive Instrumentation:** The `observe_pass` wrapper acts as an instance wrapper. You can wrap existing third-party or backend-specific passes directly in your pipeline setup script.
*   **Pass-by-Pass Diffs:** The HTML tree-explorer shows each pass as a nested region in the Left Panel. You can click through pass-by-pass before/after graph diffs, tracking metadata and layer metrics stage-by-stage.

**Primary Implementation Example (Instance Wrapper):**

```python
from executorch.backends.qualcomm._passes import FoldQDQ, LayoutTransform, RemoveRedundancy, I64toI32
from executorch.devtools.observatory import observe_pass

# Wrap existing pass instances without modifying their source code
passes = [
    observe_pass(FoldQDQ()),
    observe_pass(LayoutTransform()),
    observe_pass(RemoveRedundancy()),
    observe_pass(I64toI32()),
]

# Run the pipeline as usual; Observatory automatically logs snapshots for each stage
for p in passes:
    graph_module = p(graph_module)
```
