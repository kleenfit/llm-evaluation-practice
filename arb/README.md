# ARB × OpenCompass 全量适配

ARB（Advanced Reasoning Benchmark, [arXiv:2307.13692](https://arxiv.org/abs/2307.13692)）
全部纯文本 subset 接入 OpenCompass：9 个 subset、1049 题、4 种判分方式，
双模型（deepseek-v3.2 / qwen3.5-35b-a3b，千帆 OpenAI 兼容端点）。

含图的 68 题需要 VLM 且图床为三年前外链，论文自身亦未评测，不在本适配范围。

---

## 文件与部署

| 文件 | 用途 | 部署位置 |
|---|---|---|
| `arb.py` | loader + 4 个 evaluator + 后处理 | 覆盖到 `opencompass/datasets/arb.py` |
| `eval_arb_full.py` | 全量 config：9 subset × 双模型 | OpenCompass 根目录 |
| `eval_arb_demo.py` | 四组 demo：每组 15 题 × qwen 单模型 | 同上 |
| `eval_arb_qianfan.py` | 初版 Math Numerical 单 subset（含 LLM 抽取对照实验） | 同上 |
| `download_arb.py` | 官方 REST API 下载（14 subset 路由已核实） | 任意，建议 `tools/` |
| `inspect_arb.py` | 数据结构探查（扩新 subset 前先跑） | 同上 |
| `docs/results/*.csv` | 原始成绩凭据（见下"结果凭据"） | — |


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

### 范例 2：全量（约 3.5 小时，挂机跑）

```bash
caffeinate -i bash -c '
  python run.py eval_arb_full.py -w outputs/arb_full --mode infer &&
  python run.py eval_arb_full.py -w outputs/arb_full --mode eval -r latest
' 2>&1 | tee outputs/arb_full.log
```

`caffeinate -i` 防 macOS 休眠掐掉任务；日志同时落盘，中断可查断点。
中断续跑：`--mode infer -r <时间戳>`，已完成的「模型×subset」自动跳过。

### 范例 3：改了判分代码后重判（分钟级、零 API 费）

推理产物（predictions）与判分产物（results）分离存放。改 `arb.py`
里的判分逻辑后**只需重跑 eval**：

```bash
rm -rf outputs/arb_full/<时间戳>/results        # 不删会静默复用旧结果！
python run.py eval_arb_full.py -w outputs/arb_full --mode eval -r <时间戳>
```

坑：`-r` 是断点续跑，results 存在就跳过，表现为
`Partitioned into 0 tasks` 且表格照常打印（旧数据）。改代码必删 results。

### 范例 4：只补某一个「模型 × subset」

OpenCompass 没有单独指定的开关，用文件系统当断点状态——删谁补谁：

```bash
# 例：只重推 deepseek 的 law（改了它的 max_out_len 之后）
rm -f outputs/arb_full/<时间戳>/predictions/deepseek-v3.2/arb_law_mc* \
      outputs/arb_full/<时间戳>/results/deepseek-v3.2/arb_law_mc.json
python run.py eval_arb_full.py -w outputs/arb_full --mode infer -r <时间戳>
python run.py eval_arb_full.py -w outputs/arb_full --mode eval  -r <时间戳>
```

日志里 `launch OpenICLInfer[deepseek-v3.2/arb_law_mc]` 确认只跑了目标。

### 范例 5：钻取一条判错的样本

```bash
python -c "
import json
d = json.load(open('outputs/arb_full/<时间戳>/results/qwen3.5-35b-a3b/arb_math_numerical.json'))
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
p = json.load(open('outputs/arb_full/<时间戳>/predictions/qwen3.5-35b-a3b/arb_math_numerical.json'))
print(p['24']['prediction'][-500:])     # 看第 24 题结尾
"
```

### 范例 6：新增一个 subset

1. `python tools/inspect_arb.py --subset <名字>` 看字段结构与 Problem Type 分布
2. `download_arb.py` 拉数据
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
| A Numerical | 判对率（`ANSWER:` 抽取 → SymPy → 相对误差<1%） | 直接报 |
| B MC | 判对率（选项字母比对） | 直接报 |
| C Symbolic | **自动可判部分的下界** | 必须连 `manual_review_rate` 一起报，如 "44.1 + 50% 待人工" |
| D Proof | 平均 rubric 得分/10×100（78.0 = 平均 7.8/10 步骤分） | 注明是 rubric 均分，非判对率 |

### 自查指标：区分"模型不行"与"harness 不行"

| 指标 | 非零时先查什么 |
|---|---|
| `no_delimiter_rate` | **max_out_len 截断**：看 predictions 结尾是否断在语法中途（`\sqrt` 后、半个元组里）。断了 = 你的预算问题；完整收尾没写 `ANSWER:` 才是模型不守格式。不要用输出长度判断（token≠字符），也不要信省略号（模型自己也输出 `......`） |
| `parse_fail_rate` | harness 缺陷率。逐条看 details 里的 pred 定性——历史上全部根因都是"模型输出不是纯 LaTeX 单值"（Markdown 加粗、Unicode π、裸 e、arccos 写法、多值答案）。**不追求归零，追求每条可解释**：模型交付未化简的级数被判错，是正确行为 |
| `ref_parse_fail` | 标准答案本身解析失败（条数非比例）。非零先查数据源——已知 physics_numerical 有 1 条 gold 是符号 `c` |
| `judge_fail_rate`（D 组） | 看 eval 日志 `[ARB]` 行：`content 为空` = judge 的 max_tokens 被 thinking 吃光（加大）；429 = 并发过高（降 concurrency）。失败不入缓存，修参后按范例 3 重判只补失败条 |

### 结果文件地图

```
outputs/<work_dir>/<时间戳>/
├── predictions/<模型>/<subset>.json   # 模型原文，key=题号（infer 产物，贵）
├── results/<模型>/<subset>.json       # 逐题判定 details（eval 产物，便宜）
├── summary/summary_<时间>.csv|txt|md  # 汇总表（每次 eval 生成一份，取最新）
└── logs/{infer,eval}/<模型>/<subset>.out
```

---

## 结果凭据（docs/results/）

| 文件 | 内容 |
|---|---|
| `full9_final.csv` | 全量终版（9 subset × 双模型，所有修复后） |
| `var_run1..3.csv` | Math Numerical 三轮独立复跑（方差测量） |
| `demo4.csv` | 四组 demo（qwen） |

关键口径：deepseek 的 math_numerical / law 用 `max_out_len=24576`
（16384 下各存 1 条真截断），其余含 qwen 全部 16384；qwen law 残余
1 条截断（0.16 分上界），依成本收益不重推。deepseek 的 Math Numerical
复跑方差约 ±3 题（52 题规模），该 subset 分数应报区间而非单值。

---

## 已知限制

- 无官方参考实现（TheDuckAI/arb 仅为数据网站），判分自论文第 4/5 节文字反推
- 论文所测模型（gpt-4-0314 等）已全部下线，无法直接对照
- MCAT Reading API 缺陷：仅可获取 78/165 条（val/test 路由返回同一批数据）
- C 组 manual_review 桶混有"记号判不了"与"疑似答错"两类，需人工分拣
- D 组 rubric 为数据集自带、GPT-4 生成（论文 Table 19 流程），非人工 gold；
  论文实测该评分流程与人工 Pearson 相关 0.82

## 引用与许可

数据集 MIT（不入库系尊重作者防污染意图，非授权限制）；prompt 逐字取自
论文附录 Table 13–16/18（复现要求，改写会引入无法归因的差异）；
OpenCompass Apache-2.0（未修改其原有文件）。论文 BibTeX 见 arXiv 页面。