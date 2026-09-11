# ARB × OpenCompass 全量适配

中文在前，[English below](#english)。
由两次交付合并：`260729arb_numerical复现/`（2026-07-29 第一条，tag `260729-arb-numerical`，Math Numerical 单子集）和
`260729arb全适配/`（2026-07-29 第二条，tag `260729-arb-full`，9 个子集，本目录以它为准）。
2026-09-11 与本地 OpenCompass 工作区核对：补入 `arb_math_numerical_gen.py`，`eval_arb_full.py` 换成实际跑出终版成绩的那一份（差异见下「关键口径」）。

ARB（Advanced Reasoning Benchmark, [arXiv:2307.13692](https://arxiv.org/abs/2307.13692)）
全部纯文本 subset 接入 OpenCompass：9 个 subset、1049 题、4 种判分方式，
双模型（deepseek-v3.2 / qwen3.5-35b-a3b，千帆 OpenAI 兼容端点）。

含图的 68 题需要 VLM 且图床为三年前外链，论文自身亦未评测，不在本适配范围。

---

## 文件与部署

针对 OpenCompass 0.5.x（本地 `2a75dea6`，v0.5.3）；框架原有文件一个都不改，以下全部是新增文件。

| 文件 | 用途 | 部署位置（相对 OpenCompass 根目录） |
|---|---|---|
| `arb.py` | loader（`ARBDataset` / `ARBMathNumericalDataset`）+ 4 个 evaluator（Numerical / MC / Symbolic / Proof）+ 后处理 | `opencompass/datasets/arb.py`（配置直接 `from opencompass.datasets.arb import …`，不需要改 `__init__.py`） |
| `eval_arb_full.py` | 全量 config：9 subset × 双模型。**实际跑出 `docs/results/full9_final.csv` 的那份**（所有 subset `max_out_len=24576`，judge `max_tokens=16384`） | 根目录 |
| `eval_arb_demo.py` | 四组 demo：每组 15 题 × qwen 单模型 | 根目录 |
| `eval_arb_qianfan.py` | 初版 Math Numerical 单 subset（含 LLM 抽取对照实验；`docs/results/var_run1-3.csv` 由它跑出） | 根目录 |
| `arb_math_numerical_gen.py` | OpenCompass 风格的 Math Numerical 数据集配置（`read_base()` 用法）。**未被任何评测脚本使用**，evaluator 参数是 7 月 27 日的初版口径（`max_out_len=4096`、`report_lenient=True`），只作参考 | `opencompass/configs/datasets/arb/arb_math_numerical_gen.py` |
| `tools/download_arb.py` | 官方 REST API 下载（14 subset 路由已核实），写 `data/arb_<subset>.json` | `tools/` |
| `tools/inspect_arb.py` | 数据结构探查（扩新 subset 前先跑） | `tools/` |
| `docs/results/*.csv` | 原始成绩凭据（见下「结果凭据」） | — |
| `docs/findings.md` | Math Numerical 适配过程中发现的四个静默失败与三轮方差的完整记录（配置文件注释里的「findings.md §3/§4/§6」指的就是它） | — |
| `docs/README_math_numerical.md` | Math Numerical 单子集交付的原 README：判分实现与论文的逐条对照、指标含义、LLM 抽取取舍、关键发现摘要、数据集 API 路由、论文 Table 1、BibTeX | — |

---

## 环境准备

```bash
# 1. 数据集（不入 git：官方仅 API 分发以降低训练污染，MIT 协议、非授权限制）
for s in math_numerical physics_numerical law math_symbolic physics_symbolic \
         math_prooflike mcat_reading_val mcat_science_val mcat_science_test; do
  python tools/download_arb.py --subset $s --out data/
done
# 预期条数: 69/113/627/52/51/19/78/65/76（前几个含无类型杂项，loader 会过滤）

# 2. 密钥（只进环境变量，不进代码；export 只在当前终端会话有效）
export QIANFAN_DEEPSEEK_API_KEY=...
export QIANFAN_QWEN_API_KEY=...
export QIANFAN_JUDGE_API_KEY=...      # D 组 rubric 打分用，可复用上面任一 key
```

---

## 使用范例

### 范例 1：demo 冒烟（15 分钟，首次必跑）

```bash
python run.py eval_arb_demo.py -w outputs/arb_demo --mode infer
python run.py eval_arb_demo.py -w outputs/arb_demo --mode eval -r latest
```

正常输出长这样（qwen，每组 15 题）：

```
arb_demo_numerical   accuracy            86.67
arb_demo_law_mc      accuracy            73.33
arb_demo_symbolic    accuracy            66.67
arb_demo_symbolic    manual_review_rate  33.33
arb_demo_prooflike   accuracy            78.00
arb_demo_prooflike   judge_fail_rate      0.00
```

验收标准：四组都出数、`judge_fail_rate` 为 0、
`no_delimiter_rate` / `parse_fail_rate` 不超过个位数。

### 范例 2：全量（3～5 小时，挂机跑）

```bash
caffeinate -i bash -c '
  python run.py eval_arb_full.py -w outputs/arb_full9 --mode infer &&
  python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval -r latest
' 2>&1 | tee outputs/arb_full9.log
```

`caffeinate -i` 防 macOS 休眠掐掉任务；日志同时落盘，中断可查断点。
中断续跑：`--mode infer -r <时间戳>`，已完成的「模型×subset」自动跳过。

### 范例 3：改了判分代码后重判（分钟级、零 API 费）

推理产物（predictions）与判分产物（results）分离存放。改 `arb.py`
里的判分逻辑后**只需重跑 eval**：

```bash
rm -rf outputs/arb_full9/<时间戳>/results        # 不删会静默复用旧结果！
python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval -r <时间戳>
```

坑：`-r` 是断点续跑，results 存在就跳过，表现为
`Partitioned into 0 tasks` 且表格照常打印（旧数据）。改代码必删 results。

### 范例 4：只补某一个「模型 × subset」

OpenCompass 没有单独指定的开关，用文件系统当断点状态——删谁补谁：

```bash
# 例：只重推 deepseek 的 law（改了它的 max_out_len 之后）
rm -f outputs/arb_full9/<时间戳>/predictions/deepseek-v3.2/arb_law_mc* \
      outputs/arb_full9/<时间戳>/results/deepseek-v3.2/arb_law_mc.json
python run.py eval_arb_full.py -w outputs/arb_full9 --mode infer -r <时间戳>
python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval  -r <时间戳>
```

日志里 `launch OpenICLInfer[deepseek-v3.2/arb_law_mc]` 确认只跑了目标。

### 范例 5：钻取一条判错的样本

```bash
python -c "
import json
d = json.load(open('outputs/arb_full9/<时间戳>/results/qwen3.5-35b-a3b/arb_math_numerical.json'))
for v in d['details']:
    if not v['correct'][0]:
        print(v['idx'][0], v['reason'][0], '| pred:', repr(v['pred'][0])[:60],
              '| gold:', v['answer_number'][0])
"
```

模型原文在 `predictions/` 同名文件里，key 即 idx：

```bash
python -c "
import json
p = json.load(open('outputs/arb_full9/<时间戳>/predictions/qwen3.5-35b-a3b/arb_math_numerical.json'))
print(p['24']['prediction'][-500:])     # 看第 24 题结尾
"
```

### 范例 6：新增一个 subset

1. `python tools/inspect_arb.py --subset <名字>` 看字段结构与 Problem Type 分布
2. `tools/download_arb.py` 拉数据
3. 判分方式属于现有四类之一 → 只在 config 的 `datasets` 里加一个条目
   （复制同类条目改 abbr/path/problem_type 即可）；不属于 → 才需要在
   `arb.py` 里新写 evaluator（继承 `_ARBEvaluatorBase`，只实现 `_judge`）

注意三个已知数据特例：law 有 1 条缺 `Problem Type`（传 `problem_type=None`
不过滤）；`physics_symbolic_img` 整个字段不存在；MCAT Reading 的 val/test
返回同一批数据，只取其一。

---

## 跑完之后：怎么读结果

### accuracy 的四种语义（不能互相横比）

| 组 | accuracy 含义 | 对外报法 |
|---|---|---|
| A Numerical | 判对率（`ANSWER:` 抽取 → SymPy → 相对误差<1%；gold 为 0 时改用绝对误差 `zero_atol`；解析失败一律判错，绝不退化到「抓第一个数字」） | 直接报 |
| B MC | 判对率（选项字母比对） | 直接报 |
| C Symbolic | **自动可判部分的下界** | 必须连 `manual_review_rate` 一起报，如 "44.1 + 50% 待人工" |
| D Proof | 平均 rubric 得分/10×100（78.0 = 平均 7.8/10 步骤分） | 注明是 rubric 均分，非判对率 |

### 自查指标：区分"模型不行"与"harness 不行"

| 指标 | 非零时先查什么 |
|---|---|
| `no_delimiter_rate` | **max_out_len 截断**：看 predictions 结尾是否断在语法中途（`\sqrt` 后、半个元组里）。断了 = 你的预算问题；完整收尾没写 `ANSWER:` 才是模型不守格式。不要用输出长度判断（token≠字符），也不要信省略号（模型自己也输出 `......`） |
| `parse_fail_rate` | harness 缺陷率。逐条看 details 里的 pred 定性——历史上全部根因都是"模型输出不是纯 LaTeX 单值"（Markdown 加粗、Unicode π、裸 e、arccos 写法、多值答案）。**不追求归零，追求每条可解释**：模型交付未化简的级数被判错，是正确行为 |
| `ref_parse_fail` | 标准答案本身解析失败（条数非比例）。**`eval_arb_full.py` 的 summarizer 没列它，全量 summary 表不显示，只在 `results/*.json` 里；`eval_arb_qianfan.py` 的 summary 会显示**。非零先查数据源——终版结果里 physics_numerical 有 4 条 gold 解析失败：1 条是符号 `c`，3 条带 `\mathrm{C}` / `\mathrm{c}` / `\mathrm{~N}` 单位（`_UNIT_RE` 未覆盖），其中 3 题模型其实答对（见「已知限制」） |
| `judge_fail_rate`（D 组） | 看 eval 日志 `[ARB]` 行：`content 为空` = judge 的 max_tokens 被 thinking 吃光（本配置已设 16384；4096 时 19 题里有 6～7 题失败）；429 = 并发过高（降 concurrency）。失败不入缓存，修参后按范例 3 重判只补失败条 |

### 结果文件地图

```
outputs/<work_dir>/<时间戳>/
├── predictions/<模型>/<subset>.json   # 模型原文，key=题号（infer 产物，贵）
├── results/<模型>/<subset>.json       # 逐题判定 details（eval 产物，便宜）
├── summary/summary_<时间>.csv|txt|md  # 汇总表（每次 eval 生成一份，取最新）
└── logs/{infer,eval}/<模型>/<subset>.out
```

汇总表转 Excel、逐题对账、人工复核：见 [`../excel-export/`](../excel-export/)。

---

## 结果凭据（docs/results/）

| 文件 | 内容 | 产生方式 |
|---|---|---|
| `full9_final.csv` | 全量终版（9 subset × 双模型，所有修复后） | `eval_arb_full.py`（本目录这份），`outputs/arb_full9/20260729_051215` 的最后一次 eval |
| `var_run1..3.csv` | Math Numerical 三轮独立复跑（方差测量） | `eval_arb_qianfan.py`（含 LLM 抽取），7 月 28 日的 evaluator |
| `demo4.csv` | 四组 demo（qwen） | `eval_arb_demo.py` |

### 关键口径

- **max_out_len**：全量最初以 16384 跑完；deepseek 的 math_numerical 和 law 在 16384 下各有 1 条真截断，
  于是把配置整体改成 24576 后**只重推了这两个「模型 × subset」**，其余 16 个预测文件仍是 16384 那一轮的产物；
  最后一次 eval（即 `full9_final.csv`）用的就是这份全 24576 的配置，所以 csv 里的 `version` 哈希对应 24576。
  本目录的 `eval_arb_full.py` 即这份配置；7 月 29 日交付时打包的那份（tag `260729-arb-full`，judge `max_tokens=4096`、只有两个 subset 24576）与实际运行不一致，已替换。
- **judge max_tokens 必须 16384**：4096 时 deepseek-v4-flash 的 thinking 会吃光预算，prooflike 的 `judge_fail_rate` 达 31～37%。
- deepseek law 以 24576 重推是整个 627 题重新生成，accuracy 从 78.63 变为 77.19——「修 1 条截断」的效果与运行间方差混在一起。
- qwen law 残余 1 条截断（0.16 分上界），依成本收益不重推。
- deepseek 的 Math Numerical 复跑方差约 ±3 题（52 题规模），该 subset 分数应报区间而非单值；
  `var_run*.csv` 用的是 7 月 28 日的 evaluator（无元组 / 多值 / gold 不可解析分支），与 `full9_final.csv` 的 math_numerical（88.46）不是同一判分口径，不能直接并表。

---

## 已知限制

- 无官方参考实现（TheDuckAI/arb 仅为数据网站），判分自论文第 4/5 节文字反推
- 论文所测模型（gpt-4-0314 等）已全部下线，无法直接对照
- MCAT Reading API 缺陷：仅可获取 78/165 条（val/test 路由返回同一批数据）
- C 组 manual_review 桶混有"记号判不了"与"疑似答错"两类，需人工分拣（复核页面见 `../excel-export/make_review_html.py`）
- D 组 rubric 为数据集自带、GPT-4 生成（论文 Table 19 流程），非人工 gold；
  论文实测该评分流程与人工 Pearson 相关 0.82
- A 组 `_UNIT_RE` 未覆盖 `\mathrm{C}`、`\mathrm{c}`、`\mathrm{~N}` 这类单位写法：physics_numerical 有 3 条 gold 因此不可解析而把答对的模型判错
  （修正后 deepseek 58.75 → 60.00，qwen 56.25 → 58.75）。待修；修后按范例 3 只重跑 eval 即可
- 未化简表达式会被接受：prompt 要求 simplify，但 `to_number` 会对 `(3 + 2·ln 2)/9` 这类表达式求值后比对
- `llm_extract_fail_rate` 把「模型返回 NONE」与「API 报错 / 输出解析不了」混在一个数里，未拆分

## 引用与许可

数据集 MIT（不入库系尊重作者防污染意图，非授权限制）；prompt 逐字取自
论文附录 Table 13–16/18（复现要求，改写会引入无法归因的差异）；
OpenCompass Apache-2.0（未修改其原有文件）。完整的第三方内容清单与 BibTeX 见 [`docs/README_math_numerical.md`](docs/README_math_numerical.md)。

---

## English

Merged from two deliveries: `260729arb_numerical复现/` (first of 2026-07-29, tag `260729-arb-numerical`, Math Numerical only) and
`260729arb全适配/` (second of 2026-07-29, tag `260729-arb-full`, all 9 subsets — the base of this directory).
Reconciled with the local OpenCompass working tree on 2026-09-11: `arb_math_numerical_gen.py` added; `eval_arb_full.py` replaced by the config that actually produced the final scores (see "Scoring conventions").

ARB (Advanced Reasoning Benchmark, [arXiv:2307.13692](https://arxiv.org/abs/2307.13692)), all text-only subsets in OpenCompass:
9 subsets, 1049 questions, 4 scoring modes, two models (deepseek-v3.2 / qwen3.5-35b-a3b via the Qianfan OpenAI-compatible endpoint).
The 68 image questions need a VLM and their image host is a three-year-old external link; the paper did not evaluate them either — out of scope.

### Files and deployment

Target: OpenCompass 0.5.x (local `2a75dea6`, v0.5.3). No original framework file is modified; everything below is an added file.

| File | Purpose | Deploy to (relative to the OpenCompass root) |
|---|---|---|
| `arb.py` | loader (`ARBDataset` / `ARBMathNumericalDataset`) + 4 evaluators (Numerical / MC / Symbolic / Proof) + post-processing | `opencompass/datasets/arb.py` (configs import `opencompass.datasets.arb` directly; no `__init__.py` change) |
| `eval_arb_full.py` | full config, 9 subsets × 2 models — **the config that produced `docs/results/full9_final.csv`** (`max_out_len=24576` everywhere, judge `max_tokens=16384`) | root |
| `eval_arb_demo.py` | four demo groups, 15 questions each, qwen only | root |
| `eval_arb_qianfan.py` | first Math Numerical single-subset config (with the LLM-extraction comparison; produced `docs/results/var_run1-3.csv`) | root |
| `arb_math_numerical_gen.py` | OpenCompass-style dataset config for Math Numerical (`read_base()` usage). **Not used by any eval script**; its evaluator parameters are the 2026-07-27 first-pass settings (`max_out_len=4096`, `report_lenient=True`) — reference only | `opencompass/configs/datasets/arb/arb_math_numerical_gen.py` |
| `tools/download_arb.py` | official REST API downloader (14 subset routes verified), writes `data/arb_<subset>.json` | `tools/` |
| `tools/inspect_arb.py` | data-structure probe (run before adding a subset) | `tools/` |
| `docs/results/*.csv` | score evidence (see below) | — |
| `docs/findings.md` | full record of the four silent failures and the three variance runs found while adapting Math Numerical (the "findings.md §3/§4/§6" comments in the configs point here) | — |
| `docs/README_math_numerical.md` | original README of the Math Numerical delivery: scoring vs paper alignment table, metric semantics, LLM-extraction trade-off, findings summary, dataset API routes, paper Table 1, BibTeX | — |

### Setup and run

```bash
# data (never committed; the authors distribute via API only, MIT licence)
for s in math_numerical physics_numerical law math_symbolic physics_symbolic \
         math_prooflike mcat_reading_val mcat_science_val mcat_science_test; do
  python tools/download_arb.py --subset $s --out data/
done
export QIANFAN_DEEPSEEK_API_KEY=... QIANFAN_QWEN_API_KEY=... QIANFAN_JUDGE_API_KEY=...

# smoke test (~15 min): four groups must produce numbers, judge_fail_rate 0, no_delimiter/parse_fail single digits
python run.py eval_arb_demo.py -w outputs/arb_demo --mode infer
python run.py eval_arb_demo.py -w outputs/arb_demo --mode eval -r latest

# full run (3–5 h)
python run.py eval_arb_full.py -w outputs/arb_full9 --mode infer
python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval -r latest

# re-score only after changing arb.py (delete results/ first — with -r existing results are silently reused)
rm -rf outputs/arb_full9/<timestamp>/results
python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval -r <timestamp>
```

Outputs: `predictions/<model>/<subset>.json` (model text, keyed by idx), `results/<model>/<subset>.json` (per-question details), `summary/summary_<time>.csv|txt|md`. Excel export, reconciliation and manual review: see [`../excel-export/`](../excel-export/).

### Reading the numbers

`accuracy` has four meanings that must not be compared across groups: A Numerical = exact-match rate (`ANSWER:` extraction → SymPy → relative error < 1%, absolute `zero_atol` when gold is 0, parse failure = wrong, never falls back to "first number in the text"); B MC = option-letter match rate; C Symbolic = **lower bound** of the automatically decidable part, always reported together with `manual_review_rate`; D Proof = mean rubric score / 10 × 100.
Self-check metrics: `no_delimiter_rate` (check `max_out_len` truncation first), `parse_fail_rate` (harness defect rate; every case should be explainable), `ref_parse_fail` (gold unparsable; not listed by `eval_arb_full.py`'s summarizer, so absent from the full-run summary and only in `results/*.json`; `eval_arb_qianfan.py`'s summary does show it), `judge_fail_rate` (D group; empty content = judge `max_tokens` eaten by thinking — 16384 in this config, 4096 fails 6–7 of 19; 429 = lower concurrency).

### Score evidence and conventions

- `full9_final.csv`: final full run, produced by this directory's `eval_arb_full.py` (last eval of `outputs/arb_full9/20260729_051215`). `var_run1..3.csv`: three independent Math Numerical runs from `eval_arb_qianfan.py` with the 07-28 evaluator (not the same scoring code as `full9_final.csv`, so 89.74 vs 88.46 are not directly comparable). `demo4.csv`: the four demo groups.
- `max_out_len`: the full run was first completed at 16384; deepseek's math_numerical and law each had one true truncation, so the config was switched to 24576 everywhere and **only those two model × subset pairs were re-inferred**; the other 16 prediction files come from the 16384 pass. The final eval used the all-24576 config, hence the `version` hashes in the csv. The config packaged on 2026-07-29 (tag `260729-arb-full`: judge `max_tokens=4096`, only two subsets at 24576) did not match the run and has been replaced.
- Judge `max_tokens` must be 16384. Re-inferring deepseek law regenerated all 627 answers and moved accuracy 78.63 → 77.19 (run-to-run variance confounded with the truncation fix). One qwen law truncation remains (0.16-point upper bound). deepseek Math Numerical varies by about ±3 questions between runs — report a range, not a point.

### Known limits

No official reference implementation (scoring is inferred from the paper text); the paper's models are offline; MCAT Reading API returns 78/165 items; C-group manual_review mixes notation failures with genuine errors (use `../excel-export/make_review_html.py`); D-group rubrics are GPT-4-generated (paper: Pearson 0.82 vs humans); `_UNIT_RE` misses `\mathrm{C}` / `\mathrm{c}` / `\mathrm{~N}`, so 3 correct physics_numerical answers are scored wrong (fixed scores would be deepseek 60.00, qwen 58.75) — to be fixed, then re-run eval only; unsimplified expressions are accepted; `llm_extract_fail_rate` does not separate "model returned NONE" from API errors.

### Licence

Dataset MIT (not redistributed, out of respect for the authors' anti-contamination intent); prompts verbatim from the paper's appendix Tables 13–16/18; OpenCompass Apache-2.0 (no original file modified). Full third-party list and BibTeX in [`docs/README_math_numerical.md`](docs/README_math_numerical.md).
