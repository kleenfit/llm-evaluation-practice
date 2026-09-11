# 更新日志 / Changelog

中文在前，[English below](#english)。按交付日期倒序；每条列出交付内容、现在所在目录、对应的 git tag（tag 名即交付日期 `YYMMDD`，同一天两条加后缀区分）。
VLM 侧（VLMEvalKit）的三次交付已于 2026-09-11 迁至
[vlm-evaluation-practice](https://github.com/kleenfit/vlm-evaluation-practice)，本仓库只保留其历史 commit 与 tag。

## 2026-09-11 — 仓库重组（tag 由作者提交后自行添加）

- 移除三个 VLM 目录（`260710vlmevalkit-autoverse工具/`、`260713vlmevalkit指定列输出/`、`260909_MapQA/`），内容已原样迁入 vlm-evaluation-practice；历史 commit 与 tag `260710`、`260713`、`260909` 仍在本仓库。
- 其余目录按功能重组，`git mv` 保留历史：
  - `260730oc转Excel拓展:人工复测脚本/` + `260708opencompass结果处理工具/` → `excel-export/`
    （以 07-30 版为准；07-08 的通用导出脚本 `export_to_excel.py` 功能不重叠，作为独立脚本一并保留，其 README 并入组件 README）
  - `260729arb全适配/` + `260729arb_numerical复现/` → `arb/`
    （以「全适配」为准；numerical 版独有的 `findings.md`、README 移到 `arb/docs/`；其 `download_arb.py`、`docs/results/run1-3.csv` 与全适配版逐字节相同，`eval_arb_qianfan.py` 只差末尾换行，`arb.py` 是早期版本、功能被全适配版完整覆盖，均不再单独保留）
- `arb/` 与本地 OpenCompass 工作区核对后的两处补齐：
  - 补入 `arb_math_numerical_gen.py`：`opencompass/configs/datasets/arb/` 下的 ARB Math Numerical 数据集配置（`read_base()` 用法，未被评测脚本使用），此前未进仓库；
  - `eval_arb_full.py` 换成实际跑出 `docs/results/full9_final.csv` 的那一份（所有 subset `max_out_len=24576`、judge `max_tokens=16384`）；7 月 29 日打包的版本（judge 4096、仅两个 subset 24576）与实际运行不一致，仍可在 tag `260729-arb-full` 取到。
- 两个组件 README 在原 README 基础上重写为中英双语并修正与代码不符之处；根 README 重写；本 CHANGELOG 新建；`.gitignore` 增加 tsv/xlsx/csv/outputs/预测结果/data/status.json/.bak/.env 规则（只影响以后新增文件）。

## 2026-09-09 — MapQA 数据集适配与评测报告（tag `260909`，已迁出）

- 交付内容：MapQA 三个子集各 1000 题，VLMEvalKit 上零样本评测 qwen3.5-35b-a3b；报告（md + pdf）、错例分析、4 个结果文件。
- 现在位置：vlm-evaluation-practice `mapqa/`
- commit `8c54bfb`（`mapqa适配与评测报告`）。

## 2026-07-30 — OpenCompass 结果导出 Excel 扩展与人工复测页面（tag `260730`）

- 交付内容：`export_eval_excel.py`（总览 / 明细 / BadCase 三张表，逐题重算并与官方指标强制对账）、
  `make_review_html.py`（符号等价性人工复核的自包含 HTML 页面）。
- 现在位置：`excel-export/`
- commit `84d2a87`（`Excel脚本功能扩展`）。

## 2026-07-29 — ARB 全部纯文本子集适配（tag `260729-arb-full`）

- 交付内容：ARB 9 个纯文本 subset（1049 题、4 种判分方式）接入 OpenCompass：`arb.py`（loader + 4 个 evaluator）、
  全量 / demo / 单子集三份配置、下载与探查脚本、成绩凭据 csv。
- 现在位置：`arb/`
- commit `1093982`（`arb全文本subset适配`，当天第二条）。

## 2026-07-29 — ARB Math Numerical 子集复现（tag `260729-arb-numerical`）

- 交付内容：ARB Math Numerical（52 题）接入 OpenCompass 与三轮方差复跑；`findings.md` 记录适配过程中发现的四个静默失败。
- 现在位置：`arb/`（代码被全适配版包含；`findings.md` 与原 README 在 `arb/docs/`）
- commit `74824c1`（`numerical的demo和适配`，当天第一条）。

## 2026-07-13 — VLMEvalKit run.py 集成版 Excel 导出（tag `260713`，已迁出）

- 交付内容：修改 `run.py` + 新增 `vlmeval/utils/eval_excel.py`，评测后自动导出 Excel。
- 现在位置：vlm-evaluation-practice `excel-export-runpy/`
- commit `d00c0f9`（`feat: add Excel export support to run.py`）。

## 2026-07-10 — VLMEvalKit AutoVerse 外挂式 Excel 导出（tag `260710`，已迁出）

- 交付内容：`autoverse_v2.py`，不改框架源码的结果后处理 / 选列导出工具。
- 现在位置：vlm-evaluation-practice `excel-export-autoverse/`
- commit `b7e7c90`（`tools for vlmevalkit`，提交日期 2026-07-13，交付日期按目录名 07-10）。

## 2026-07-08 — OpenCompass 结果导出 Excel 工具（tag `260708`）

- 交付内容：`export_to_excel.py`，把一次 OpenCompass 运行目录的 `summary/*.md`、`results/`、`predictions/` 整理成 summary + details 两张表的 Excel。
- 现在位置：`excel-export/`
- commit `642354c`（`add OpenCompass result export tool`）。

---

## English

Newest first. Each entry lists what was delivered, where it lives now and the git tag (tag names are delivery dates `YYMMDD`; two deliveries on the same day get a suffix).
The three VLM-side (VLMEvalKit) deliveries were migrated to
[vlm-evaluation-practice](https://github.com/kleenfit/vlm-evaluation-practice) on 2026-09-11; this repo keeps only their historical commits and tags.

### 2026-09-11 — Repository restructure (tag to be added by the author after committing)

- Removed the three VLM directories (`260710vlmevalkit-autoverse工具/`, `260713vlmevalkit指定列输出/`, `260909_MapQA/`); their content moved unchanged to vlm-evaluation-practice. The historical commits and tags `260710`, `260713`, `260909` remain here.
- Regrouped the rest by function with `git mv` (history preserved):
  - `260730oc转Excel拓展:人工复测脚本/` + `260708opencompass结果处理工具/` → `excel-export/`
    (07-30 version is the base; the generic 07-08 exporter `export_to_excel.py` does not overlap in function and is kept as a separate script, its README merged into the component README)
  - `260729arb全适配/` + `260729arb_numerical复现/` → `arb/`
    (the full adaptation is the base; the numerical-only `findings.md` and README moved to `arb/docs/`; its `download_arb.py` and `docs/results/run1-3.csv` are byte-identical to the full version, `eval_arb_qianfan.py` differs only by a trailing newline, and `arb.py` is an earlier version whose functionality the full version covers completely — none is kept separately)
- Two additions to `arb/` after reconciling with the local OpenCompass working tree:
  - `arb_math_numerical_gen.py`: the ARB Math Numerical dataset config under `opencompass/configs/datasets/arb/` (`read_base()` style, unused by the eval scripts), never committed before;
  - `eval_arb_full.py` replaced by the config that actually produced `docs/results/full9_final.csv` (`max_out_len=24576` for every subset, judge `max_tokens=16384`); the version packaged on 2026-07-29 (judge 4096, only two subsets at 24576) did not match the run and remains available at tag `260729-arb-full`.
- Both component READMEs rewritten bilingually on top of the originals with code-mismatches corrected; root README rewritten; this CHANGELOG created; `.gitignore` now blocks tsv/xlsx/csv/outputs/预测结果/data/status.json/.bak/.env (affects only files added from now on).

### 2026-09-09 — MapQA dataset adaptation and evaluation report (tag `260909`, migrated out)

- Delivered: 1000 questions per MapQA subset, zero-shot evaluation of qwen3.5-35b-a3b with VLMEvalKit; report (md + pdf), error analysis, four result files.
- Now in: vlm-evaluation-practice `mapqa/`
- commit `8c54bfb`.

### 2026-07-30 — OpenCompass Excel export extension and manual-review page (tag `260730`)

- Delivered: `export_eval_excel.py` (overview / detail / BadCase sheets, per-question recomputation reconciled against the official metrics) and
  `make_review_html.py` (self-contained HTML page for manual symbolic-equivalence review).
- Now in: `excel-export/`
- commit `84d2a87`.

### 2026-07-29 — ARB full text-only subsets adaptation (tag `260729-arb-full`)

- Delivered: all 9 text-only ARB subsets (1049 questions, 4 scoring modes) in OpenCompass: `arb.py` (loader + 4 evaluators),
  full / demo / single-subset configs, download and inspection scripts, result csv evidence.
- Now in: `arb/`
- commit `1093982` (second of the day).

### 2026-07-29 — ARB Math Numerical subset reproduction (tag `260729-arb-numerical`)

- Delivered: ARB Math Numerical (52 questions) in OpenCompass with three variance runs; `findings.md` documents four silent failures found during adaptation.
- Now in: `arb/` (code contained in the full version; `findings.md` and the original README under `arb/docs/`)
- commit `74824c1` (first of the day).

### 2026-07-13 — VLMEvalKit run.py-integrated Excel export (tag `260713`, migrated out)

- Delivered: modified `run.py` + new `vlmeval/utils/eval_excel.py`, automatic Excel export after evaluation.
- Now in: vlm-evaluation-practice `excel-export-runpy/`
- commit `d00c0f9`.

### 2026-07-10 — VLMEvalKit AutoVerse standalone Excel export (tag `260710`, migrated out)

- Delivered: `autoverse_v2.py`, a post-processing / column-selection export tool that leaves the framework source untouched.
- Now in: vlm-evaluation-practice `excel-export-autoverse/`
- commit `b7e7c90` (committed 2026-07-13; delivery date 07-10 per the directory name).

### 2026-07-08 — OpenCompass result-to-Excel export tool (tag `260708`)

- Delivered: `export_to_excel.py`, turns one OpenCompass run directory (`summary/*.md`, `results/`, `predictions/`) into a two-sheet (summary + details) Excel workbook.
- Now in: `excel-export/`
- commit `642354c`.
