### 4.1 Python API Examples: Capture to Output

The Python APIs are easiest to understand as a full lifecycle: open an Observatory session, capture one or more named artifacts while the compiler pipeline runs, then explicitly export the captured archive or a derived report. The examples below intentionally end at the files a user receives: Archive JSON for raw captured sessions and records, HTML for a shareable human report, and late-bound HTML regenerated from a saved Archive JSON without rerunning the model pipeline. The toy `export_model` and `quantize_model` helpers are minimal stand-ins for the same steps in a real ExecuTorch pipeline.

#### Context manager: manual capture and explicit exports

```python
import torch
from executorch.devtools.observatory import Observatory

class ToyModel(torch.nn.Module):
    def forward(self, x): return torch.relu(x + 1)

def export_model(model): return torch.fx.symbolic_trace(model.eval())
def quantize_model(gm): gm.graph.lint(); gm.recompile(); return gm

Observatory.clear()  # Start a fresh in-process archive.
gm = export_model(ToyModel())
with Observatory.enter_context("quantization"):  # Outermost region opens a session.
    Observatory.collect("before_quantize", gm)  # Capture stage 1.
    quantized_gm = quantize_model(gm)
    Observatory.collect("after_quantize", quantized_gm)  # Capture stage 2.

# Archive JSON: raw captured sessions/records for CI, archival, or replay.
Observatory.export_json("toy_quant_archive.json")
# HTML report: human-readable dashboard generated from the current archive.
Observatory.export_html_report("toy_quant_report.html", title="Toy quantization")
# Late binding: regenerate HTML later from Archive JSON, without rerunning.
Observatory.generate_html_from_json("toy_quant_archive.json", "toy_quant_late.html", title="Toy quantization")
```

#### `@observe_pass`: pass-level capture and report export

```python
import operator, torch
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.passes import ExportPass, PassManager
from torch.fx.passes.infra.pass_base import PassResult

class ToyModel(torch.nn.Module):
    def forward(self, x): return torch.relu(x + 0)

export_model = lambda model: torch.fx.symbolic_trace(model.eval())

@observe_pass(name="fold_add_zero", collect_input=True, collect_output=True)
class FoldAddZeroPass(ExportPass):
    def call(self, gm):
        # Ordinary pass logic: no Observatory calls are needed here.
        for node in list(gm.graph.nodes):
            if node.op == "call_function" and node.target is operator.add and node.args[1] == 0:
                node.replace_all_uses_with(node.args[0]); gm.graph.erase_node(node)
        gm.graph.lint(); gm.recompile(); return PassResult(gm, True)

Observatory.clear(); pipeline = PassManager([FoldAddZeroPass()])
with Observatory.enter_context("pre_lowering_passes"):
    pipeline(export_model(ToyModel()))
# HTML report: includes the decorator-captured pass input and output graphs.
Observatory.export_html_report("fold_add_zero_report.html", title="Pass trace")
```

These export calls produce the physical formats described next: raw Archive JSON for replay and automation, and derived Report HTML/JSON for human or machine consumption.
