# OpenCompass 结果导出 Excel 与人工复测

中文在前，[English below](#english)。
由两次交付合并：`260708opencompass结果处理工具/`（2026-07-08，tag `260708`，`export_to_excel.py`）和
`260730oc转Excel拓展:人工复测脚本/`（2026-07-30，tag `260730`，`export_eval_excel.py` + `make_review_html.py`）。三个脚本互不依赖，各自独立运行。

> 本目录的脚本都是基于 OpenCompass 输出文件格式编写的独立工具，只读取本地已生成的评测结果，不包含、不修改 OpenCompass 源代码，也不会重新评分。

## 三个脚本，一条链

```
outputs/<exp>/<时间戳>/            export_to_excel.py        <模型>-<数据集>-<时间戳>.xlsx   （summary / details 两张表，单模型快速人工检查）
  ├── summary/summary_*.md
  ├── results/<模型>/<数据集>.json  export_eval_excel.py      <时间戳>_analysis.xlsx        （总览 / 明细 / BadCase，多模型，逐题重算并对账）
  └── predictions/<模型>/<数据集>.json                                 │
                                                        make_review_html.py ──▶ manual_review.html ──▶ 人工判定 CSV
```

| 场景 | 用哪个 |
|---|---|
| 一次单模型评测，想连 summary 表一起看，逐题检查模型输出 | `export_to_excel.py` |
| 多模型 × 多子集，有部分得分（rubric），要出能进报告的数字 | `export_eval_excel.py`（带强制对账） |
| `export_eval_excel.py` 的 BadCase 里有 `reason == manual_review`（SymPy 判不动的符号答案） | `make_review_html.py` |

## 前置条件

- OpenCompass 0.5.x（本地 `2a75dea6`，v0.5.3）的输出结构：`<work_dir>/<YYYYmmdd_HHMMSS>/{summary,results,predictions}`，其中 `results/` 与 `predictions/` 下按 `<模型 abbr>/<数据集 abbr>.json` 存放。
  `-w outputs/arb_full9` 跑出来的目录是 `outputs/arb_full9/<时间戳>/`。
- `results/*.json` 必须带 `details`（`--dump-eval-details`，此版本默认开启），且是 evaluator 自己返回逐题字段的形式（每题一条，字段值被 OpenCompass 包成单元素列表）。
  evaluator 不返回 details 时 OpenCompass 写的是另一种 `{'type': 'GEN', '0': {...}}` 形式，两个导出脚本都不支持；多次重复采样（n > 1）也不支持。
- 依赖：`openpyxl`（两个导出脚本）、`pandas`（复核页面）；复核页面打开时从 cdnjs 加载 MathJax，离线不渲染公式但判定功能可用。
- 脚本放哪里都能跑（路径参数相对当前目录解析）；README 里的 `tools/` 是建议放置位置。只有 `export_to_excel.py` 不带 `--input` 的自动查找要求在 OpenCompass 根目录执行。

## export_to_excel.py — 通用导出（summary + details）

```bash
python tools/export_to_excel.py                                   # 自动找 outputs/default 下最新一次运行
python tools/export_to_excel.py --input outputs/default/20260707_155019
python tools/export_to_excel.py -i outputs/default/20260707_155019 -o result.xlsx
```

- `--input`：一次运行的**时间戳目录**（须含 `results/`，`summary/*.md` 取文件名最新的一份）。省略时递归查找 `outputs/default` 下同时含 `summary/` 与 `results/` 的最新目录；`-w` 指定到别处的运行不会被自动找到，需要显式 `--input`。
- `--output`：省略时命名为 `<模型>-<数据集>-<时间戳目录名>.xlsx`（模型取 summary 表头第一个模型列，数据集为表中各行用 `+` 连接），存到 input 目录下。
- 两张表：`summary`（summary md 表格原样写入）和 `details`：

| 列名 | 含义 |
|---|---|
| 题号 | `example_abbr`；目录里有多个 result json 时加数据集名前缀 |
| 是否正确 | OpenCompass 判定的 `correct` 字段（接受 bool / 0-1 / "true" / "是" 等写法） |
| 模型结果 | `predictions` 里的完整 `prediction`；缺失时退回 `results` 的 `pred` |
| 原始题目 | 从 `origin_prompt` 里取最后一个 `Question:` / `问题:` / `题目:` / `Q:` 之后的题，避免把 few-shot 示例写进去 |
| 标准答案 | `results` 的 `answer`，缺失时退回 `predictions` 的 `gold` |
| 回答是否为空 | 模型输出为空时标黄 |

- 样式：表头样式、冻结首行、自动筛选、自动换行、边框、固定行高，正确 / 错误着色。
- 已知限制：只适合**单模型**运行（多模型目录下预测文件按文件名匹配，可能配错模型，题号也会重复）；没有 `correct` 字段的数据集（rubric 分、`is_correct`）整列为 FALSE；prompt 里没有 `Question:` 一类标记时「原始题目」会落到第一个 few-shot 示例；`origin_prompt` 为角色列表（API 模型带 meta_template）时按 `str()` 写入。
- 出错一律打印 `[export_to_excel] …` 后以退出码 1 结束。

## export_eval_excel.py — 结果导出与对账

```bash
python tools/export_eval_excel.py outputs/arb_full9
python tools/export_eval_excel.py outputs/arb_full9 --out docs/results/arb_full9_analysis.xlsx
python tools/export_eval_excel.py outputs/arb_full9 --dataset arb_math_prooflike
```

- `work_dir` 传 `outputs/<exp>` 或具体时间戳目录均可；同目录下有多个运行时自动取最新并打印提醒。`--dataset` 按数据集 abbr 精确过滤。`--out` 默认 `<时间戳目录>/<时间戳>_analysis.xlsx`。
- 三张表：
  - **总览**：每个模型 × 子集一行。题数、官方指标、逐题重算、**对账**、单题权重、判分方式、失分题数、三个自查指标（空输出 / 缺 ANSWER 分隔符 / 疑似截断）、以及 `reason` 字段每个取值的计数（ARB evaluator 会给出 wrong_value / manual_review / parse_fail / no_delimiter / gold_unparseable 等）。
  - **明细**：逐题全量，含模型、子集、题号、判定、得分、满分、模型最终答案、标准答案、题干、完整模型输出、诊断列，以及 details 里出现的所有其它字段（未知字段自动追加成列，不会丢）。
  - **BadCase**：明细中判定不是「正确」的行（含部分得分与无判分），已开筛选，按「子集」或「reason」一筛即归因。

### 对账（重要）

脚本对每个子集用逐题得分反推指标，并与 results JSON 的官方指标比对（容差 0.01）：总览「对账」列逐行标 OK / 不一致；
任一子集不一致时打印告警并以**非零退出码**结束（工作簿已经写出，但不得用于报告）。

这道对账不是装饰。历史版本曾因 OpenCompass 把 details 字段包成单元素列表（`correct=[False]`，非空列表做真值判断恒为真）
而把全部 496 条失分静默记成满分——表内看起来毫无异常，只有与官方指标对账才能暴露（44.12 vs 100.00）。
当前版本所有判分取值统一经 `_unwrap()` 拆包，且 `correct` 非布尔时直接硬报错，不做兜底。

### 判分口径

| details 字段 | 处理 |
|---|---|
| `score` / `rubric_score` / `pred_score` | 部分得分。子集内出现非 0/1 分值时满分按 10 计（prooflike 的 rubric 分） |
| `correct`（布尔） | 二值判分。非布尔（含整数 0/1）→ 硬报错 |
| 两者皆无 | 判定「无判分」，不计入得分但仍计入分母，因此该子集对账必然不一致 |

官方指标只认 `accuracy` / `score` / `rubric_score`，其它指标名记为「无官方指标」并按对账失败处理。
「题干」按 ARB 的 prompt 结构截取（`Question:` 到 `Now it is time to`），「缺 ANSWER 分隔符」「疑似截断」按 ARB 的 `ANSWER:` 约定判断——用在别的数据集上这几列只是参考。

## make_review_html.py — 符号等价性人工复核页面

读 BadCase 表中 `reason == manual_review` 的行，生成一个自包含 HTML，浏览器打开即用，无需服务器：

- 左右并排 MathJax 渲染模型答案与标准答案，下方附原始 LaTeX；
- **模型答案取自「完整输出」中最后一个 `ANSWER:` 之后的全文**——results JSON 的 pred 字段是截断过的，直接用会看不到答案后半段；取「最后一个」同时规避模型自我怀疑循环产生的重复 ANSWER 行；
- 键盘判定：`1` 等价 · `2` 不等价 · `3` 存疑 · `J/K`（或上下箭头）上下，判完自动跳下一条；
- 底部实时显示每个判定对子集分数的影响（等价 = 判回一题；按二值判分估算）；
- 题干与模型输出结尾默认折叠（`--tail-chars`，默认 3000 字），长输出可展开全文；
- 「导出 CSV」得到逐条判定记录（模型、子集、题号、人工判定、理由）；页面无自动保存，中断前用「复制进度」，回来「载入进度」粘回。

```bash
python tools/make_review_html.py docs/results/arb_full9_analysis.xlsx --out docs/results/manual_review.html
```

输入工作簿必须有 `总览`、`BadCase` 两张表和 `reason` 列（即 `export_eval_excel.py` 的输出）；没有 `manual_review` 行时直接退出。

### 复核规则

- 默认不等价，由「等价」承担举证责任；判不准就存疑，存疑按不等价计分并单独披露；
- 只判数学等价，不看格式：LaTeX 环境不同、变量名不同、多解顺序不同、自然语言表述（"and its permutations"）均可等价；
- 盯紧实质差异：区间开闭与端点、参数范围（ℤ vs ℕ）、求和上下限、多问题目是否只答了部分；
- 复核产出的 CSV 是报告中修正分数的唯一依据，连同判定理由一并入库。

## 已知限制 / 待办

- 两个导出脚本都不支持 OpenCompass 的 `format_details` 字典形式和 n > 1 重复采样。
- `export_to_excel.py`：多模型目录会配错预测文件；应改为按 `predictions/<模型>/<数据集>.json` 配对并加模型列。
- `export_eval_excel.py`：「无官方指标」和整数型 `correct` 直接判失败，对非 ARB 数据集偏严；题干 / ANSWER 相关启发式应做成开关。

---

## English

Merged from two deliveries: `260708opencompass结果处理工具/` (2026-07-08, tag `260708`, `export_to_excel.py`) and
`260730oc转Excel拓展:人工复测脚本/` (2026-07-30, tag `260730`, `export_eval_excel.py` + `make_review_html.py`). The three scripts are independent of each other.

> Standalone tools written against the OpenCompass output format. They only read locally generated results; they do not include or modify OpenCompass source and never re-score.

### Three scripts, one chain

```
outputs/<exp>/<timestamp>/          export_to_excel.py       <model>-<dataset>-<timestamp>.xlsx   (summary / details sheets; single-model quick check)
  ├── summary/summary_*.md
  ├── results/<model>/<dataset>.json export_eval_excel.py     <timestamp>_analysis.xlsx           (总览 / 明细 / BadCase; multi-model, recomputed and reconciled)
  └── predictions/<model>/<dataset>.json                                │
                                                       make_review_html.py ──▶ manual_review.html ──▶ verdict CSV
```

| Situation | Use |
|---|---|
| One single-model run; want the summary table plus per-question model output for human checking | `export_to_excel.py` |
| Several models × subsets, partial (rubric) scores, numbers that go into a report | `export_eval_excel.py` (forced reconciliation) |
| `export_eval_excel.py`'s BadCase has rows with `reason == manual_review` (symbolic answers SymPy could not decide) | `make_review_html.py` |

### Prerequisites

- OpenCompass 0.5.x (local `2a75dea6`, v0.5.3) layout: `<work_dir>/<YYYYmmdd_HHMMSS>/{summary,results,predictions}` with `results/` and `predictions/` organised as `<model abbr>/<dataset abbr>.json`. A run started with `-w outputs/arb_full9` lands in `outputs/arb_full9/<timestamp>/`.
- `results/*.json` must contain `details` (`--dump-eval-details`, on by default in this version) in the per-question form returned by the evaluator (OpenCompass wraps each field in a single-element list).
  The `{'type': 'GEN', '0': {...}}` form written when an evaluator returns no details is not supported by either exporter; neither are repeated samples (n > 1).
- Dependencies: `openpyxl` (both exporters), `pandas` (review page); the review page loads MathJax from cdnjs when opened — offline, formulas do not render but verdicts still work.
- The scripts run from anywhere (path arguments are resolved relative to the current directory); `tools/` in the examples is the suggested location. Only `export_to_excel.py` without `--input` (auto-discovery) needs the OpenCompass root as current directory.

### export_to_excel.py — generic export (summary + details)

```bash
python tools/export_to_excel.py                                   # newest run under outputs/default
python tools/export_to_excel.py --input outputs/default/20260707_155019
python tools/export_to_excel.py -i outputs/default/20260707_155019 -o result.xlsx
```

- `--input`: the **timestamp directory** of one run (must contain `results/`; the newest `summary/*.md` by name is used). When omitted, the newest directory under `outputs/default` containing both `summary/` and `results/` is used; runs placed elsewhere with `-w` need an explicit `--input`.
- `--output`: default `<model>-<dataset>-<timestamp dir>.xlsx` inside the input directory (model = first model column of the summary header, datasets = the table rows joined with `+`).
- Two sheets: `summary` (the markdown summary table) and `details` with columns 题号 (example_abbr, dataset-prefixed when several result files exist), 是否正确 (`correct`; bool / 0-1 / "true" / "是" accepted), 模型结果 (full `prediction`, falling back to `pred`), 原始题目 (the last `Question:` / `问题:` / `题目:` / `Q:` block of `origin_prompt`, so few-shot examples are left out), 标准答案 (`answer`, falling back to `gold`), 回答是否为空 (empty output highlighted).
- Styling: header style, frozen first row, autofilter, wrapping, borders, fixed row height, colour for correct / wrong.
- Known limits: **single-model** runs only (in multi-model directories prediction files are matched by file name and may belong to another model; 题号 may repeat); datasets without `correct` (rubric scores, `is_correct`) show FALSE throughout; prompts without a `Question:`-style marker put the first few-shot example into 原始题目; a role-list `origin_prompt` (API models with meta_template) is written via `str()`.
- Every failure prints `[export_to_excel] …` and exits with code 1.

### export_eval_excel.py — export with reconciliation

```bash
python tools/export_eval_excel.py outputs/arb_full9
python tools/export_eval_excel.py outputs/arb_full9 --out docs/results/arb_full9_analysis.xlsx
python tools/export_eval_excel.py outputs/arb_full9 --dataset arb_math_prooflike
```

- `work_dir` may be `outputs/<exp>` (newest timestamp chosen, notice printed) or a timestamp directory. `--dataset` filters by exact dataset abbr. `--out` defaults to `<timestamp dir>/<timestamp>_analysis.xlsx`.
- Three sheets: **总览** (one row per model × subset: count, official metric, recomputed metric, **对账**, per-question weight, scoring mode, lost questions, three self-check counts — empty output / missing ANSWER delimiter / suspected truncation — and a count per distinct `reason` value), **明细** (every question: model, subset, id, verdict, score, full mark, final answer, gold, question, full output, diagnostics, plus every other details field as extra columns), **BadCase** (rows whose verdict is not 正确, including partial and unscored rows; filter by 子集 or reason).
- Reconciliation: the metric is recomputed from per-question scores and compared with the official metric in the results JSON (tolerance 0.01). Any mismatch prints a warning and exits non-zero (the workbook is still written but must not be used for a report). This check once exposed a bug where OpenCompass's single-element list wrapping (`correct=[False]` is truthy) turned all 496 lost questions into full marks (44.12 vs 100.00); every value now goes through `_unwrap()` and a non-bool `correct` is a hard error.
- Scoring: `score` / `rubric_score` / `pred_score` = partial score (full mark 10 when non-binary values occur); boolean `correct` = binary (non-bool, including int 0/1, aborts); neither = 无判分, excluded from the numerator but still in the denominator, so such a subset always fails reconciliation. Only `accuracy` / `score` / `rubric_score` are recognised as the official metric; anything else is 无官方指标 and counts as a failed reconciliation. 题干 extraction (`Question:` … `Now it is time to`) and the ANSWER-delimiter / truncation heuristics follow ARB's prompt convention and are only indicative on other datasets.

### make_review_html.py — manual symbolic-equivalence review page

Reads the BadCase rows with `reason == manual_review` and writes a self-contained HTML page (no server): side-by-side MathJax rendering of model and gold answers with the raw LaTeX; the model answer is the text after the **last** `ANSWER:` of the full output (the results-JSON `pred` is truncated; taking the last one also skips repeated ANSWER lines from self-doubt loops); keyboard verdicts `1` equivalent · `2` not equivalent · `3` unsure · `J/K` or arrows to move; live score impact per subset (binary-scoring estimate); question and output tails collapsed by default (`--tail-chars`, default 3000); CSV export (model, subset, id, verdict, note); no autosave — use "copy progress" / "load progress".

```bash
python tools/make_review_html.py docs/results/arb_full9_analysis.xlsx --out docs/results/manual_review.html
```

The workbook must have the `总览` and `BadCase` sheets and a `reason` column (i.e. the output of `export_eval_excel.py`); with no `manual_review` rows the script exits.

Review rules: not-equivalent by default, "equivalent" carries the burden of proof; when unsure mark unsure (scored as not equivalent and disclosed separately); judge mathematical equivalence only, not formatting; watch interval endpoints, parameter domains (ℤ vs ℕ), summation limits and partially answered multi-part questions; the CSV is the sole basis for corrected scores in a report.

### Known limits / TODO

- Neither exporter supports OpenCompass's `format_details` dict form or repeated samples (n > 1).
- `export_to_excel.py`: mismatched prediction files in multi-model directories; should pair by `predictions/<model>/<dataset>.json` and add a model column.
- `export_eval_excel.py`: 无官方指标 and integer `correct` are treated as failures, strict for non-ARB datasets; the question / ANSWER heuristics should become switches.
