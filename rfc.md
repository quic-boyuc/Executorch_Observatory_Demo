# RFC for Observatory and FX Viewer


## Introduction

In this RFC I want to propose 2 components in devtool that amplifies the value of each other.

Draft implementation of the components are presented in [PR](PR link)
Link for demo is provided in next section.

1. Observatory (`devtools/observatory`) : A unified, extensible debugging utility for Executorch. This framework is called observaotry because it aims to support debugging of intermediate graphs and other runtime attributes (Currently only aot workflow is supported, runtime analysis can be supported with inspection API and  etdump).  Backend maintainers and users can contribute backend-specific debugging script and analysis logic through observatory extension, these extensions are called "Lenses". Lenses behavior can be defined by arbitrary python code and control how the debugging information will be visualized in the final HTML report. Activation and behavior of individual lensese can be futher customized and controlled by configs in observatory context.

[An image showing lense architecture and workflow steps and unified report and setting]

2. FX Viewr (`devtools/fx_viewer`):  A simple HTML viewer for visualizing fx_graph supporting both Aten dialect and Edge dialect. This visualization library consists of 4k lines of vallina JS with no dependency except from standard browser API). The library support instant rendering of more than 10k nodes, support minimap natigation , smart search bar, n-graph comparison side-by-side with view syncing (using `node.meta['from_node']`). Further more, the fx_viewer is easily customizable with python API that can be leveraged in observatory's Lense API, allowing the lense debugging logic to contribute customized coloring rule, node data, and label highlights, and even cross-graph syncing rule.

[An architecture image showing extension python API + JS frontend]

[A GIF showing single view + minimap]

[A GIF showing compare view]

To actually **feels** how *observatory* and *fx_viewer* amplifies each other's value in debugging workflow please see the demo in next section.

## Demo
This demo implemented a **zero-config (auto collection) workflow of per-layer accuracy analysis**, that works on all xnnpack and qualcomm aot examples.

### 1. Setup 
- Prepare standard executorch dev environment for your target backend.

- Install [fast-sugiyama](https://github.com/austinorr/fast-sugiyama) package
```bash
# requires python version >= 3.11
pip3 install fast-sugiyama[full]
```

### 2. Command
Simply use observaotry.cli to invoke ordinary aot script. Use `--lense_recipe=accuracy` to enable accuracy Lenses.

```bash
 python -m executorch.backends.xnnpack.debugger.observatory \
        --output-html output.html \
        --lense_recipe=accuracy \
        {original xnnpack command and args}
        
# for example (aot_compiler.py auto-detected as module via __init__.py)
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2

# or pass the dotted module name explicitly
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lense_recipe=accuracy \
    examples.xnnpack.aot_compiler \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/mv2

```

### 3. HTML Report
HTML report for xnnpack and qualcomm models are available in 
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)
[Demo link](demo_links)

Observatory produce a **standalone HTML report** (no dependency other than standard browser API).

#### 3.1 **Run Dashboard**
The inital page is **run dashboard**, this page shows per-run information, in this demo, *metadata lense* provide infomation about the command and os. Each *lense* can add their own section with python API.

[PNG shoing run dash board]

#### 3.2 **Records (Left Panels)**: 

**Left Panel & Records** in HTML report consists of multiple **records**, each record corresponding to a observatory collection (breakpoint). We can see listing of records in the left panel.

**Diff Label** is area between adjacent records in left panel, each *lense* can insert *diff-label* with python API, in this demo, the *graph lense* and *accuracy* will insert differences in number of nodes and accuray metrices between records.

**Compare Mode** can be entered by clicking **`select`** button in the top of *left panel* 


[PNG showing records and diff label area]

Clicking *record* in *left panel* opens the **single record view** in the main area.

[GIF showing clicking records in left panels ](xxx.gif)

Clicking *diff label* in *left panel* opens the **2-record compare view** in the main area

[GIF showing clicking diff label in left panels ](xxx.gif)

Clicking *select* in *left panel* will enter **n-record compare view** in the main area.

[GIF showing clicking select and select-all in left panels ](xxx.gif)


#### 3.3 **Lense Data**

Here we explain the **Lenses** (debugging extension) activated in this demo:

##### Lenses that produce main section

- **Stack Trace** `observatory/lenses/stack_trace.py`
  - What does it do?
  - How does it works?
 
- **Meta Data** `observatory/lenses/metadata.py` 
  - What does it do?
  - How does it works?
 
- **Graph** `observatory/lenses/graph.py`
  - What does it do?
  - How does it works?
 
- **Accuracy** `observatory/lenses/accuracy.py`
  - What does it do?
  - How does it works?
 
- **Per-Layer Acc** `observatory/lenses/per_layer_accuracy.py`
  - What does it do?
  - How does it works?

##### Lenses that doesn't produce main section

- **Pipieline Graph Collector** `observatory/lenses/pipeline_graph_collector.py`
  - What does it do?
  - How does it works?
  
- **Graph Color** `observatory/lenses/graph_color.py`
  - What does it do?
  - How does it works?
 
 
## Use Case and Motivation

This project is not driven only by features.
It is driven by the workflows we need to support.
The expected use case of the utility is as follows

1. Developer debugging and profiling
Developers need to quickly see what changed, where execution diverged, why performance regressed, and which parts of the graph or runtime look suspicious. Observatory supports this by capturing the right artifacts, turning them into an inspectable report with automated analysis, and making findings easy to share without reconstructing context.

2. QA/CI issue triage and reproduce
When QA/CI finds a failure and needs to hand it off in a form that is reproducible and actionable.

3. Community issue report and reproduction
An external user or collaborator needs to report a problem in a way that others can inspect and reproduce.

4. AI issue analysis and triage
Structured debugging artifacts can automated workflow also become inputs for future automated analysis.

## Detail Interface Design
### General Invokation
**How to activate Observatory?**
1. **CLI**: Use `devtools/observatory` to invoke any script.
The default observatory setup we will collect meta datas, stack trace, graphs in different stages

```bash
 python -m executorch.devtools.observatory \
        --output-html output.html \
        {any executorch e2e script and args}
```
2. **Manual**: Modify your script to enable observatory context.

```python
from executorch.devtools.observatory import Observatory

model = MyModel().eval()
graph = torch.fx.symbolic_trace(model)

with Observatory.enable_context():
    Observatory.collect("original", graph)
    # Apply a pass
    transformed = my_pass(graph)
    Observatory.collect("after_my_pass", transformed)

Observatory.export_html_report("pass_debug.html")
Observatory.export_json("pass_debug.json")

```

**How to set observatory collection point?**
1. **Automatic** : Standard executorch API wrapped by a default lense in `observatory/lenses/pipeline_graph_collector.py`, for example 
    - `prepare_pt2e`
    - `convert_pt2e`, 
    - `to_edge_transform_and_lower`
    - `ETRecord.add_exported_program`
    - `ETRecord.add_edge_dialect_program`

2. **Pass Decorator** : Use `observe_pass` to automatically collect graphs before and after a pass. Wrap any `PassBase` subclass instance, callable, or use it as a class decorator:

```python
from executorch.devtools.observatory import Observatory, observe_pass
from executorch.exir.pass_manager import PassManager
from executorch.exir.passes.remove_graph_asserts_pass import RemoveGraphAssertsPass

# Decorator wrap all pass instances
from executorch.exir.pass_base import ExportPass, PassResult
@observe_pass
class MyPass(ExportPass):
    def call(self, gm):
        # process graph_module here
        return graph_module


pm = PassManager()
# Wrap pass instances — default collects both input and output graphs
pm.add_pass(observe_pass(RemoveGraphAssertsPass()))
pm.add_pass(MyPass())

with Observatory.enable_context():
    pm._transform(graph_module)
    
Observatory.export_html_report("pass_debug.html")
```

3. **Manual** : 
You can insert `Observatory.collect()` calls anywhere in your code to capture
intermediate graph states. This is useful for debugging pass transforms or
custom lowering steps.


### Backend Specific CLI and Lenses
Use backend specific observaotry.cli to invoke ordinary aot script.
Backend can implement custom lenses and cli options, for example, use `--lens_recipe=accuracy` to enable accuracy Lenses.

**XNNPack**

> **Note**: `examples/xnnpack/aot_compiler.py` uses relative imports (`from . import ...`), so it
> must be run as a Python module. The Observatory CLI auto-detects this when a file path is passed
> and its directory contains `__init__.py`. Alternatively, pass the dotted module name directly.

```bash
# File path (auto-detected as module due to __init__.py in examples/xnnpack/)
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lens_recipe=accuracy \
    examples/xnnpack/aot_compiler.py \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/

# Equivalent: explicit dotted module name
python -m executorch.backends.xnnpack.debugger.observatory \
    --output-html /tmp/mv2/obs_report.html \
    --lens_recipe=accuracy \
    examples.xnnpack.aot_compiler \
    --model_name=mv2 --delegate --quantize --output_dir /tmp/
```

**Qualcomm**

```bash
python -m executorch.backends.qualcomm.debugger.observatory \
    --output-html obs_report.html \
    --lens_recipe=accuracy \
    examples/qualcomm/oss_scripts/mobilevit_v2.py --backend htp --model SM8650 -d ./imagenet-mini-val/ -b build-android/ --compile_only
```


## Maintainance and Collaboration

### Backend Agnostic Frameworks
We propose `observatory` and `fx_viewer` lives inside `devtools`, jointly maintained by community.

```txt
devtools/
├── fx_viewer
│   ├── README.md
│   ├── color_rules.py
│   ├── exporter.py
│   ├── extension.py
│   ├── models.py
│   └── templates
│       ├── README.md
│       ├── canvas_renderer.js
│       ├── compare.js
│       ├── fx_graph_viewer.js
│       ├── graph_data_store.js
│       ├── minimap_renderer.js
│       ├── runtime.js
│       ├── search_engine.js
│       ├── ui_manager.js
│       └── view_controller.js
└── observatory
    ├── README.md
    ├── REFERENCE.md
    ├── USAGE.md
    ├── cli.py
    ├── graph_hub.py
    ├── html_template.py
    ├── interfaces.py
    ├── observatory.py
    ├── observe_pass.py
    ├── template_loader.py
    ├── lenses
    │   ├── LENSES.md
    │   ├── __init__.py
    │   ├── accuracy.py
    │   ├── graph.py
    │   ├── graph_color.py
    │   ├── metadata.py
    │   ├── per_layer_accuracy.py
    │   ├── pipeline_graph_collector.py
    │   └── stack_trace.py
    ├── templates
    │   ├── css
    │   │   └── main.css
    │   └── js
    │       ├── 00_state.js
    │       ├── 01_utils.js
    │       ├── 02_layout.js
    │       ├── 03_blocks.js
    │       ├── 04_actions.js
    │       └── 05_bootstrap_api.js
    ├── tests
    └── utils.py
```
### Backend Specific Lenses and debugging CLI



## Future Plan

- Leverage Inspection API and support more debugging scenarios (e.g. runtime issue, performance, memory)
- Support more graph formats other than *fx graph* (e.g. Pytorch graph, QNN graph)
- Rewrite and automate backend-specific debugging into observatory *lense* (e.g. QNN QHAS performance profiling)
- More device-specific profiler and debugger integration (e.g. ADB lense, performance profiling lense)

