# llm-evaluation-practice — OpenCompass 评测工具与数据集适配

中文在前，[English below](#english)。

本仓库收录基于 [OpenCompass](https://github.com/open-compass/opencompass) 做的评测辅助工具和数据集适配，按功能分目录，每个目录只保留最新可用版本；
历次交付的日期、内容和对应的 git tag 见 [CHANGELOG.md](CHANGELOG.md)。
VLM 侧（VLMEvalKit）的工具在姊妹仓库 [vlm-evaluation-practice](https://github.com/kleenfit/vlm-evaluation-practice)；两边刻意不合并（各自还有内置数据集要继续用）。

OpenCompass 框架本身的代码不改结构：这里的东西要么是「放回去」的文件（数据集类覆盖到 `opencompass/datasets/`、配置放到根目录或 `opencompass/configs/`），要么是只读取输出目录的独立脚本。

## 目录一览

| 目录 | 是什么 | 针对的 OpenCompass 版本 | 放回框架的位置 | 原交付目录 |
|---|---|---|---|---|
| [`excel-export/`](excel-export/) | **结果导出 Excel + 人工复测**。三个独立脚本，只读 `outputs/` 不改框架：`export_to_excel.py`（通用：summary + 逐题 details 两张表）、`export_eval_excel.py`（总览 / 明细 / BadCase 三张表，逐题重算并与官方指标强制对账）、`make_review_html.py`（符号答案等价性人工复核页面，浏览器打开即用）。 | 0.5.x（本地 `2a75dea6`，v0.5.3）的 `outputs/<exp>/<时间戳>/{summary,results,predictions}` 结构 | 放到 OpenCompass 根目录的 `tools/` 下，按 README 里的命令运行 | `260708opencompass结果处理工具/`（2026-07-08）+ `260730oc转Excel拓展:人工复测脚本/`（2026-07-30） |
| [`arb/`](arb/) | **ARB 数据集适配**（Advanced Reasoning Benchmark，arXiv:2307.13692）：9 个纯文本 subset、1049 题、4 种判分方式接入 OpenCompass；`arb.py`（loader + evaluator + 后处理）、全量 / demo / 单子集三份评测配置、数据集配置、下载与探查脚本、成绩凭据 csv、Math Numerical 复现过程的发现记录。 | 0.5.x（本地 `2a75dea6`，v0.5.3） | `arb.py` → `opencompass/datasets/arb.py`；`arb_math_numerical_gen.py` → `opencompass/configs/datasets/arb/`；`eval_arb_*.py` → OpenCompass 根目录；`tools/*.py` → `tools/` | `260729arb全适配/` + `260729arb_numerical复现/`（2026-07-29） |

两个目录各自有 README，写了完整的参数说明、判分口径、输出格式和运行范例。

## 快速开始

下面的命令都在 OpenCompass 根目录执行，密钥一律走环境变量，不要写进配置或命令历史。

```bash
# 1) 导出一次评测结果为 Excel（通用版；不带参数时自动找 outputs/default 下最新一次运行）
python tools/export_to_excel.py
python tools/export_to_excel.py --input outputs/default/20260707_155019 --output result.xlsx

# 2) ARB：拉数据 → 冒烟 → 全量（详见 arb/README.md）
export QIANFAN_DEEPSEEK_API_KEY=... QIANFAN_QWEN_API_KEY=... QIANFAN_JUDGE_API_KEY=...
python tools/download_arb.py --subset math_numerical --out data/
python run.py eval_arb_demo.py -w outputs/arb_demo --mode infer
python run.py eval_arb_demo.py -w outputs/arb_demo --mode eval -r latest

# 3) ARB 结果对账导出 + 人工复核页面
python tools/export_eval_excel.py outputs/arb_full9 --out docs/results/arb_full9_analysis.xlsx
python tools/make_review_html.py docs/results/arb_full9_analysis.xlsx --out docs/results/manual_review.html
```

## 约定

- **密钥**：代码和文档里只出现环境变量名（`QIANFAN_*_API_KEY`）或占位符；不会有真实 key。
- **数据与结果不入库**：ARB 数据集只通过 `tools/download_arb.py` 从官方 API 获取，不提交；`.gitignore` 挡住 `*.tsv` / `*.xlsx` / `*.csv` / `outputs/` / `预测结果/` / `data/` / `status.json` / `.env`。
  `arb/docs/results/` 下已跟踪的几份 summary csv 是当时交付的成绩凭据，保留；以后新的结果文件默认不进仓库。
- **版本与日期**：目录名不带日期；每次交付打一个以日期命名的 tag（`YYMMDD`，同一天两条加后缀），明细见 [CHANGELOG.md](CHANGELOG.md)。
- **框架版本**：本地 OpenCompass 为 `2a75dea6`（`[Feature] Add ELBench (#2495)`，v0.5.3）；框架原有文件未修改，ARB 相关文件在框架里以新增文件形式存在。

---

## English

This repository collects evaluation helpers and dataset adaptations built on [OpenCompass](https://github.com/open-compass/opencompass),
one directory per function, each holding only the latest working version. Delivery dates, contents and git tags are in [CHANGELOG.md](CHANGELOG.md).
The VLM-side (VLMEvalKit) tools live in the sibling repo [vlm-evaluation-practice](https://github.com/kleenfit/vlm-evaluation-practice); the two are intentionally kept separate (each side keeps using its own built-in datasets).

The OpenCompass framework itself is not restructured: everything here is either a file to drop back into the framework (dataset class into `opencompass/datasets/`, configs into the root or `opencompass/configs/`) or a standalone script that only reads the output directory.

### Directories

| Directory | What it is | Target OpenCompass version | Where it goes in the framework | Original delivery dir |
|---|---|---|---|---|
| [`excel-export/`](excel-export/) | **Result export to Excel + manual review**. Three standalone scripts that read `outputs/` and change nothing in the framework: `export_to_excel.py` (generic: summary + per-question details), `export_eval_excel.py` (overview / detail / BadCase sheets, per-question recomputation reconciled against the official metrics), `make_review_html.py` (self-contained page for manual symbolic-equivalence review). | 0.5.x (local `2a75dea6`, v0.5.3) output layout `outputs/<exp>/<timestamp>/{summary,results,predictions}` | Put under `tools/` in the OpenCompass root and run as shown in the README | `260708opencompass结果处理工具/` (2026-07-08) + `260730oc转Excel拓展:人工复测脚本/` (2026-07-30) |
| [`arb/`](arb/) | **ARB dataset adaptation** (Advanced Reasoning Benchmark, arXiv:2307.13692): 9 text-only subsets, 1049 questions, 4 scoring modes in OpenCompass; `arb.py` (loader + evaluators + post-processing), full / demo / single-subset eval configs, dataset config, download and inspection scripts, result csv evidence, findings from the Math Numerical reproduction. | 0.5.x (local `2a75dea6`, v0.5.3) | `arb.py` → `opencompass/datasets/arb.py`; `arb_math_numerical_gen.py` → `opencompass/configs/datasets/arb/`; `eval_arb_*.py` → OpenCompass root; `tools/*.py` → `tools/` | `260729arb全适配/` + `260729arb_numerical复现/` (2026-07-29) |

Each directory has its own README with full option reference, scoring rules, output format and examples.

### Quick start

All commands run from the OpenCompass root; API keys come from environment variables and never go into config files or shell history.

```bash
# 1) Export one evaluation run to Excel (generic; with no arguments it picks the newest run under outputs/default)
python tools/export_to_excel.py
python tools/export_to_excel.py --input outputs/default/20260707_155019 --output result.xlsx

# 2) ARB: download → smoke test → full run (see arb/README.md)
export QIANFAN_DEEPSEEK_API_KEY=... QIANFAN_QWEN_API_KEY=... QIANFAN_JUDGE_API_KEY=...
python tools/download_arb.py --subset math_numerical --out data/
python run.py eval_arb_demo.py -w outputs/arb_demo --mode infer
python run.py eval_arb_demo.py -w outputs/arb_demo --mode eval -r latest

# 3) ARB reconciled export + manual-review page
python tools/export_eval_excel.py outputs/arb_full9 --out docs/results/arb_full9_analysis.xlsx
python tools/make_review_html.py docs/results/arb_full9_analysis.xlsx --out docs/results/manual_review.html
```

### Conventions

- **Keys**: only environment-variable names (`QIANFAN_*_API_KEY`) or placeholders appear in code and docs; no real key anywhere.
- **Data and results stay out of git**: the ARB dataset is fetched from the official API with `tools/download_arb.py` and never committed; `.gitignore` blocks `*.tsv` / `*.xlsx` / `*.csv` / `outputs/` / `预测结果/` / `data/` / `status.json` / `.env`.
  The tracked summary csv files under `arb/docs/results/` are the score evidence of past deliveries and are kept; new result files are not committed by default.
- **Versions and dates**: directory names carry no date; every delivery gets a date-named tag (`YYMMDD`, suffixed when two land on the same day), details in [CHANGELOG.md](CHANGELOG.md).
- **Framework version**: local OpenCompass is `2a75dea6` (`[Feature] Add ELBench (#2495)`, v0.5.3); no original framework file is modified — the ARB files exist in the framework as additions only.
