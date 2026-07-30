# ARB 评测结果分析工具

两个脚本,覆盖从 OpenCompass 落盘结果到人工复核的完整分析链:

```
outputs/<exp>/           export_eval_excel.py          make_review_html.py
  results/*.json    ──────────────────────▶  分析.xlsx ─────────────────▶ 复核.html
  predictions/*.json     (含强制对账)         (总览/明细/BadCase)          (浏览器判定,导出 CSV)
```

## export_eval_excel.py — 结果导出与对账

把一次完整评测(2 模型 × 9 子集)导出为一个工作簿,三张表:

- **总览**:每个模型 × 子集一行。官方指标、逐题重算、**对账**、单题权重、
  判分方式、失分题数、四个自查指标(空输出 / 缺 ANSWER 分隔符 / 疑似截断)、
  reason 分类计数(wrong_value / manual_review / parse_fail / no_delimiter /
  gold_unparseable)。
- **明细**:逐题全量(1049 × 2 行),含判定、得分、题干、完整模型输出、
  以及 details 里出现的所有诊断字段(未知字段自动追加成列,不会丢)。
- **BadCase**:明细中的失分子集,已开筛选,按「子集」或「reason」一筛即归因。

```bash
python tools/export_eval_excel.py outputs/arb_full9
python tools/export_eval_excel.py outputs/arb_full9 --out docs/results/arb_full9_analysis_v4.xlsx
python tools/export_eval_excel.py outputs/arb_full9 --dataset arb_math_prooflike
```

work_dir 传 `outputs/arb_full9` 或具体时间戳目录均可;同目录下有多个运行时
自动取最新并打印提醒。

### 对账(重要)

脚本对每个子集用逐题得分反推指标,并与 results JSON 的官方指标比对:

- 总览「对账」列逐行标 OK / 不一致;
- 任一子集不一致时打印告警并以**非零退出码**结束,该表不得用于报告。

这道对账不是装饰。历史版本曾因 OpenCompass 把 details 字段包成单元素列表
(`correct=[False]`,非空列表做真值判断恒为真)而把全部 496 条失分静默记成
满分——失分题数整列为 0、自查指标全 0,**表内看起来毫无异常**,只有与官方
指标对账才能暴露(44.12 vs 100.00)。当前版本所有判分取值统一经 `_unwrap()`
拆包,且 `correct` 非布尔时直接硬报错,不做兜底。

### 判分口径

| details 字段 | 处理 |
|---|---|
| `score` / `rubric_score` / `pred_score` | 部分得分。子集内出现非 0/1 分值时满分按 10 计(prooflike 的 rubric 分) |
| `correct`(布尔) | 二值判分。非布尔 → 硬报错 |
| 两者皆无 | 判定「无判分」,不计入重算 |

## make_review_html.py — 符号等价性人工复核页面

读 BadCase 表中 `reason == manual_review` 的行(SymPy 判不动、按失分计的
符号答案),生成一个自包含 HTML,浏览器打开即用,无需服务器:

- 左右并排 MathJax 渲染模型答案与标准答案,下方附原始 LaTeX;
- **模型答案取自「完整输出」中最后一个 `ANSWER:` 之后的全文**——results
  JSON 的 pred 字段是截断过的,直接用会看不到答案后半段;取"最后一个"
  同时规避模型自我怀疑循环产生的重复 ANSWER 行;
- 键盘判定:`1` 等价 · `2` 不等价 · `3` 存疑 · `J/K` 上下,判完自动跳下一条;
- 底部实时显示每个判定对子集分数的影响(等价 = 判回一题);
- 题干与模型输出结尾默认折叠,长输出可展开全文;
- 「导出 CSV」得到逐条判定记录;页面无自动保存,中断前用「复制进度」,
  回来「载入进度」粘回。

```bash
python tools/make_review_html.py docs/results/arb_full9_analysis_v4.xlsx \
    --out docs/results/manual_review.html
```

### 复核规则(与报告 §2.1 一致)

- 默认不等价,由「等价」承担举证责任;判不准就存疑,存疑按不等价计分
  并单独披露;
- 只判数学等价,不看格式:LaTeX 环境不同、变量名不同、多解顺序不同、
  自然语言表述("and its permutations")均可等价;
- 盯紧实质差异:区间开闭与端点、参数范围(ℤ vs ℕ)、求和上下限、
  多问题目是否只答了部分;
- 复核产出的 CSV 是报告中 C 组修正分数的唯一依据,连同判定理由一并入库。

## 依赖

`pandas` · `openpyxl`。复核页面另需联网加载 MathJax CDN
(cdnjs.cloudflare.com);离线环境公式不渲染,但原始 LaTeX 仍可读,判定
功能不受影响。
