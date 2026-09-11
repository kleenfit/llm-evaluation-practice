> **归档说明 / Archive note（2026-09-11）**：本文是 2026-07-29 第一条交付「ARB Math Numerical 复现」（原目录 `260729arb_numerical复现/`，tag `260729-arb-numerical`）的原 README，因判分实现、指标含义、关键发现、数据集 API 路由、BibTeX 等内容未被全适配版 README 覆盖而整体保留。
> 文中「目录结构」「部署位置」描述的是当时的目录布局；现在的代码以 [`../`](../)（`arb.py`、`eval_arb_qianfan.py`、`tools/download_arb.py`）为准，三轮结果 CSV 在 [`results/var_run1-3.csv`](results/)（与原 `run1-3.csv` 逐字节相同）。
> This is the original README of the 2026-07-29 Math Numerical delivery (archived as-is, Chinese only), kept because its content is not covered by the full-adaptation README; file paths refer to the original layout — the current code lives one level up.

# ARB Math Numerical × OpenCompass

把 ARB（Advanced Reasoning Benchmark, [arXiv:2307.13692](https://arxiv.org/abs/2307.13692)）的
Math Numerical 子集（52 题）接入 OpenCompass，判分口径对齐论文第 4 节。

本仓库同时记录了适配过程中发现的若干评测可复现性问题 —— 见 [关键发现](#关键发现)。
那部分比分数本身更值得看。

---

## 目录结构

```
arb.py                  # dataset loader + evaluator + 后处理
eval_arb_qianfan.py     # 评测配置（千帆 OpenAI 兼容端点）
download_arb.py         # 从官方 REST API 拉数据集
findings.md             # 关键发现的完整记录
docs/results/           # 三轮方差运行的 summary CSV（原始证据）
```

部署位置：

| 文件 | 放到 OpenCompass 的 |
|---|---|
| `arb.py` | `opencompass/datasets/arb.py` |
| `eval_arb_qianfan.py` | 根目录 |
| `download_arb.py` | 任意位置，建议 `tools/` |

---

## 快速开始

```bash
# 1. 拉数据集（不进版本库，见下方"数据集"一节）
python download_arb.py --subset math_numerical --out data/

# 2. 配置 key
export QIANFAN_DEEPSEEK_API_KEY=...
export QIANFAN_QWEN_API_KEY=...
export QIANFAN_JUDGE_API_KEY=...     # 仅在启用 LLM 抽取时需要

# 3. 跑
python run.py eval_arb_qianfan.py -w outputs/arb --mode infer
python run.py eval_arb_qianfan.py -w outputs/arb --mode eval -r latest
```

冒烟测试：把 config 里 `reader_cfg` 的 `test_range='[0:5]'` 取消注释，先跑 5 条打通链路。

**注意 `-r` 是断点续跑**，它会跳过 `predictions/` 和 `results/` 里已存在的产物。
改了判分代码之后重跑 eval 必须先 `rm -rf <exp>/results`，否则会直接汇总旧结果，
表现为 `Partitioned into 0 tasks`。

---

## 判分实现

### 对齐论文的部分

| 项 | 论文规定 | 本实现 |
|---|---|---|
| 答案定位 | 取 `ANSWER:` 之后的文本，找不到分隔符判错 | 同 |
| 单位处理 | 用正则剥单位（针对 physics） | `strip_units`，math 子集默认关闭 |
| 数值解析 | 用数学库解析，解析失败判错 | SymPy，失败判错 |
| 判定 | 相对误差 < 0.01 | 同 |
| Prompt | 附录 Table 14 | 逐字一致 |

`strip_units` 对 math 关闭是有意的：论文的剥单位是为 physics 设计的，
而 `L/N/K/J/W/A/s` 这些字母在数学表达式里可能是有意义的符号，盲目剥离会制造新错误。

### 本实现的补充（论文未规定）

- **绝不退化到"抓第一个数字"**。SymPy 解析失败一律判错。
  用正则抓数字会把 `\sqrt{2}` 截断成 `2.0`、`2^{10}` 截断成 `2.0`，
  制造假阳性 —— 两个无关的值被判成相等，而且极难发现。
- **gold 为 0 时**相对误差无定义，改用绝对误差（`zero_atol`），单独计数。
- **自查指标**：`no_delimiter_rate` / `parse_fail_rate` / `ref_parse_fail`。
  前两个论文有类似对照（论文报了 gpt-3.5-turbo 在 Law 上约 25% 解析失败、
  gpt-4 >99% 成功）；`ref_parse_fail` 是数据完整性检查，非 0 说明连标准答案都读不对，
  此时其他数字全部不可信。
- **LLM 辅助抽取**（可选，默认关闭）：见下。

### 指标含义

| 指标 | 含义 | 性质 |
|---|---|---|
| `accuracy` | 论文口径的正式分数 | **唯一对外汇报的数** |
| `no_delimiter_rate` | 没写 `ANSWER:` 的比例 | 自查 |
| `parse_fail_rate` | 写了但解析不了的比例 | 自查，**是本实现的缺陷率** |
| `ref_parse_fail` | 标准答案解析失败条数 | 自查，非 0 最严重 |
| `accuracy_llm` 等 | LLM 抽取口径，仅诊断 | 默认关闭 |

三类失败互斥，与 `wrong_value`（真算错）加起来 = 总题数。
用这个分解可以判断分数是被模型能力限制还是被 harness 限制。

---

## LLM 辅助抽取（可选，默认关闭）

`llm_extract_cfg` 打开后，用一个外部 API 模型从完整 CoT 里抽取最终数值，
再走**同一套确定性数值比较**判分。`accuracy` 不受影响。

只用 LLM 做抽取、不做判分，是刻意的取舍：判分本身是两个浮点数比大小，
确定性、可审计、零成本，换成 LLM 是纯亏损（论文 Table 8 实测 GPT-3.5 判符号等价
假阴性极多，准确率仅 0.76，会系统性低估）。脆的是抽取那一层。

**我们试了，然后用数据否定了它** —— 见 [关键发现 §5](#5-llm-抽取没有带来收益)。
代码保留，默认关闭。

---

## 结果

三轮独立完整运行（`max_out_len=16384`，52 题）：

| 模型 | run1 | run2 | run3 | 均值 | 极差 |
|---|---|---|---|---|---|
| deepseek-v3.2 | 92.31 | 86.54 | 90.38 | **89.74** | 5.77 |
| qwen3.5-35b-a3b | 92.31 | 92.31 | 92.31 | **92.31** | 0.00 |

三轮的 `no_delimiter_rate`、`ref_parse_fail` 均为 0，`parse_fail_rate` ≤ 3.85。

**这些数字不能与论文直接比较**，原因见下一节。

---

## 关键发现

完整记录见 [findings.md](findings.md)。摘要：

### 1. 四个静默失败，全部伪装成模型能力问题

适配过程中依次暴露出四个问题，共同点是**表现形式都指向"模型不行"，
实际全在 harness 里**：

| 层 | 问题 | 表面现象 | 实际影响 |
|---|---|---|---|
| infer | `max_out_len=4096` 太小 | 27% 样本"不遵守输出格式" | qwen 71.15 → 92.31 |
| 抽取 | 裸 `e` / Markdown `**` / Unicode `π` | "模型算错了" | `parse_fail_rate` 9.62 → 0 |
| 判分调用 | 判分模型并发撞 429 限流 | "抽取器不可靠" | 假的 -11.54 分 gap |
| 抽取输入 | 抽取器输入被静默截断 | 无现象 | 15/104 样本盲判，纯运气没出事 |

最大的一个是 `max_out_len`：**论文没有规定这个参数**，而它在本数据上造成了
21 分的分数偏移，远超常见的 ±5 分复现窗口。也就是说，即使拿到论文的完整评测代码，
只要这个参数不同，分数也复现不了。

### 2. 模型排名会被 harness 配置反转

`max_out_len=4096` 时 deepseek(84.62) 明显强于 qwen(71.15)；
提到 16384 后 qwen(92.31) 反超 deepseek(88.46)。

原因是 qwen 的输出风格反复自我质疑（`Wait, ...`、`Let's double check`），
token 消耗大，27% 的答案在写出 `ANSWER:` 之前就被截断了。
截断的样本全部断在句子中间，可直接验证。

### 3. 2023 年的解析器接不住 2026 年的模型输出

三轮 `parse_fail` 全部源自同一个模式：**模型输出的不是纯 LaTeX**。

- 裸 `e`（欧拉数）→ SymPy 解析成未知符号 `Symbol('e')`
- `**ANSWER: 1**` → Markdown 加粗的 `**` 被当成幂运算符
- `2π` → Unicode 字符而非 `\pi`

三类都表现为"模型答错"，而非"解析器失效"，隐蔽性很高。

### 4. 52 题的规模撑不住 ±5 分的复现要求

一题 = 1.92 分，5 分容差只允许 2.6 题的翻转。
而 deepseek 在三轮中有 **7/52 题（13.5%）判定不稳定**，
极差 5.77 分 —— 翻转方向部分抵消，真实不稳定度比极差显示的更高。

`temperature=0` 不保证 API 侧确定性（服务端 batching、MoE 路由）。
qwen 三轮一题不差，deepseek 则不然 —— 这是模型/服务的属性，不在实现的控制范围内。

**建议报 `mean ± std` 而非单次分数。**

### 5. LLM 抽取没有带来收益

截断问题修复后，strict 抽取已几乎无损（`no_delimiter_rate` ≈ 0）。
此时 LLM 抽取的净贡献：deepseek +1 题，qwen 0 题，
而 qwen 的 `accuracy_llm` 极差 7.69 > `accuracy` 极差 0.00 —— **它增加了方差**。

结论：在这个 subset 上 LLM 抽取应当关闭。代码保留作为对照记录。

### 6. 分数与论文差距过大，污染嫌疑需要正视

论文 Table 3（GPT-4 错误分析，每学科抽样 20–40 题）中，
Math Numerical 的 "Correct answer" 为 **3%**。本次测得 88–92%。

模型进步（2023 年的 GPT-4 无推理链 vs 2026 年的推理模型）能解释一部分，
但三十倍的差距不是常规进步的量级。论文当年刻意只通过 API 分发数据集以防爬取，
到 2026 年这道防线大概率已失效。**这个假设无法在本项目内证实或证伪，
但必须在任何汇报中主动声明。**

---

## 已知限制

- **没有参考实现可对齐。** `TheDuckAI/arb` 仓库只是数据集网站（Next.js + REST API），
  不含任何评测代码。本实现是从论文的文字描述反推的。
- **论文的 numerical 判分是全自动的**（Figure 1 标题即 "automatically scored components"），
  人工判分只用于 symbolic 的困难情形和 proof-like。所以复现在原理上可行，
  但论文的模型（gpt-4-0314、gpt-3.5-turbo-0301、text-davinci-003、claude-v1.3-100k）
  已全部下线，无法直接对照。
- **未化简表达式会被接受。** prompt 明确要求 simplify，但 `to_number` 会对
  `(3 + 2·ln 2)/9` 这类表达式求值后比对。论文的实际口径不明（Figure 1 是图，无精确数值）。
- **LLM 抽取器与被测模型同源。** 判分用 deepseek-v4-flash，与 deepseek-v3.2 同家族。
  实测偏差方向与自偏假设相反（受益的是 qwen），但仍是已知缺陷。
- **三轮样本量不足**以给出可靠的方差估计。

---

## 数据集

**不进版本库。** 论文作者刻意只通过 REST API 分发、不发布到 GitHub/HuggingFace，
目的是降低被爬进训练语料的概率。请用 `download_arb.py` 获取。

官方端点（`TheDuckAI/arb` README 只列了这一个）：

```
https://advanced-reasoning-benchmark.netlify.app/api/
```

这个 URL 既是端点根，也是 API 文档页。路由已对照文档核实：

```
/api/lib/math/{numerical|symbolic|prooflike}
/api/lib/law/
/api/lib/physics/{numerical|symbolic}/{img|noimg}
/api/lib/mcatReading/{val|test}
/api/lib/mcatScience/{val|test}/{img|noimg}
```

任一路径后接 `/{id}` 可取单题。含图的类别通过 `img`/`noimg` 区分，
MCAT 两类另有 `val`/`test` 分割 —— 论文 Table 1 给的是合计，无法与单个 split 直接比对。

数据集本身是 **MIT 协议**，法律上可以再分发 —— 不提交纯粹是为了不破坏
作者防污染的意图，不是授权限制。

该项目 2023 年后基本停止维护，端点可能失效 —— **务必保留本地备份**。

官方导出中混有 `Problem Type` 为空的杂项，dataset loader 按
`Problem Type == 'Numerical'` 过滤，得到与论文 Table 1 一致的 52 题。

---

## 后续方向

按性价比排序：

1. **Physics Numerical（80 题，纯文本）** —— 判分逻辑完全相同，
   只需打开 `strip_units`。一个参数把覆盖从 52 题提到 132 题。
   `_UNIT_RE` 已经为它写好了。
2. **Math Symbolic（34 题）** —— 方法论上最有含量的部分。论文自己承认
   SymPy 判等价"容易出错、只对函数形式的响应有效"，集合记号等复杂答案需人工。
   这是论文留下的真问题。
3. **Law + MCAT（973 题，占全库 80%）** —— 判分最简单（比对选项），
   但需要全新的 evaluator，与当前数值判分无复用关系。
4. **拆分 `llm_extract_fail_rate`** —— 目前把「模型返回 NONE」（被测模型的缺陷）
   与「API 报错 / 输出解析不了」（工具链的缺陷）混在一个数里。
   429 那次事件正说明了这个短板。`_one` 已返回 `(ok, value)`，拆开只需分别计数。

---

## ARB 数据集全貌（论文 Table 1）

| Subject | 答案类型 | 题数 |
|---|---|---|
| Mathematics | Numerical | **52** ← 本项目 |
| | Symbolic | 34 |
| | Proof-like | 19 |
| Physics | Numerical | 80 |
| | Numerical（含图） | 18 |
| | Symbolic | 18 |
| | Symbolic（含图） | 13 |
| Law | Multiple Choice | 627 |
| MCAT (Reading) | Multiple Choice | 165 |
| MCAT (Science) | Multiple Choice | 144 |
| | MC（含图） | 37 |
| **合计** | | **1207** |


---

## 引用与许可

本仓库自身的代码（`arb.py`、config、下载脚本、文档）为原创，可自由使用。
以下是所依赖的第三方内容及其状态：

| 内容 | 来源 | 许可 | 本仓库的处理 |
|---|---|---|---|
| ARB 数据集 | [TheDuckAI/arb](https://github.com/TheDuckAI/arb) | MIT | **不再分发**，仅提供下载脚本 |
| 评测 prompt | 论文附录 Table 14 | 随论文 | 逐字引用，已标注出处 |
| 数据集统计、论文报告的分数 | 论文 Table 1 / Table 3 / Table 8 | 事实性数据 | 引用并标注表号 |
| OpenCompass | [open-compass/opencompass](https://github.com/open-compass/opencompass) | Apache-2.0 | 仅作为宿主框架，未修改其原有文件 |
| 模型输出 | 百度千帆 API | 各模型服务条款 | 仅在 `findings.md` 中引用极短片段用于说明解析失败 |

**关于 prompt 逐字引用**：复现论文结果要求 prompt 完全一致，
任何改写都会引入无法归因的差异。`eval_arb_qianfan.py` 中的
`ARB_SYSTEM` / `ARB_NUMERICAL_USER` 直接取自论文附录 Table 14，
已在代码注释中标注出处。

**关于数据集**：MIT 协议允许再分发，但本仓库刻意不包含数据文件 ——
论文作者只通过 REST API 分发、不发布到 GitHub/HuggingFace，
目的是降低被爬进训练语料的概率。这是尊重作者意图，不是许可证限制。

### 引用论文

```bibtex
@article{sawada2023arb,
  title  = {ARB: Advanced Reasoning Benchmark for Large Language Models},
  author = {Sawada, Tomohiro and Paleka, Daniel and Havrilla, Alexander and
            Tadepalli, Pranav and Vidas, Paula and Kranias, Alexander and
            Nay, John J. and Gupta, Kshitij and Komatsuzaki, Aran},
  journal = {arXiv preprint arXiv:2307.13692},
  year   = {2023}
}
```