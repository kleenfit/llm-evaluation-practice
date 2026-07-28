# 适配过程中的发现

按发现顺序记录。每条包含：现象 → 定位方法 → 根因 → 影响。
留下定位方法是为了让同类问题下次能更快被抓到。

---

## 1. lenient 分数低于 strict（`strict_lenient_gap = -20`）

**现象**：qwen 的 `accuracy` 40，`accuracy_lenient` 20。

**为什么这是 bug**：lenient 按定义是 strict 的超集（更宽松的抽取口径），
接受的答案集合只能更大，所以 `gap ≥ 0` 恒成立。负值必然是实现错误。

> 这条约束本身就是这个指标最大的价值：它是一个内建断言。
> 下面两个 bug 都是被这个负值暴露出来的，否则可能一直不会被发现。

**根因（两个叠加）**：

1. `pred_postprocessor` 在上游就把答案抽干净了，evaluator 里的 lenient
   分支拿到的已经是 strict 的结果，结构上不可能更宽松。
2. `lenient_ok` 独立计算，没有以 `strict_ok` 打底。

还有一处死代码：evaluator 试图从 `test_set['origin_prediction']` 取原始输出，
但 OpenCompass 不提供这一列，该分支恒不执行。

**修复**：postprocessor 改为透传原文，strict 抽取移入 `score()`，
`lenient_ok = ok or self._close(...)`。

---

## 2. `parse_fail` — 模型输出不是纯 LaTeX

**定位方法**：

```bash
python -c "
import json
d = json.load(open('<exp>/results/<model>/arb_math_numerical.json'))
for v in d['details']:
    if v['reason'][0] == 'parse_fail':
        print(v['idx'][0], repr(v['pred'][0])[:150])
"
```

**三轮发现的样本**：

| 轮次 | 样本 | 根因 |
|---|---|---|
| 1 | `\(\pi(1 - 1/e)\)`、`e^{1/3}`、`e`、`(e-3)/2` | 裸 `e` 被 SymPy 解析成 `Symbol('e')`，`free_symbols` 非空 → 拒绝。欧拉数在 SymPy 里是大写 `E` |
| 1 | `1**` | 模型写的是 `**ANSWER: 1**`，Markdown 加粗的收尾 `**` 被当成幂运算符，缺指数 |
| 3 | `2π` | Unicode π 而非 `\pi`，`_GREEK` 表只覆盖了 LaTeX 命令形式 |

**共同点**：三类都表现为「模型算错了」，而不是「解析器失效」。
`to_number` 返回 `None` → `_close` 判错 → 计入错误率，没有任何信号指向解析层。

**修复**（均在 `latex_to_expr` / `to_number`）：

```python
# 裸 e -> 欧拉数（避开 exp、theta、1.6e-19）
s = re.sub(r'(?<![A-Za-z0-9_.])e(?![A-Za-z0-9_])', 'E', s)

# Unicode 数学符号
for k, v in _UNICODE_MATH.items():
    s = s.replace(k, v)
s = re.sub(r'√\s*\(([^()]*)\)', r'sqrt(\1)', s)

# 剥首尾 Markdown 标记（只动首尾，表达式内部运算符不受影响）
expr_str = latex_to_expr(cand).strip('*` ').rstrip('.;,: ')
```

**影响**：`parse_fail_rate` 从 9.62 / 7.69 降到 0。

---

## 3. `max_out_len=4096` — 最大的一个

**现象**：qwen 有 26.92% 的样本被判 `no_delimiter`（没写 `ANSWER:`），
一度被解读为「模型不遵守输出格式」。

**定位方法** —— 检查缺少分隔符的样本**结尾**：

```bash
python -c "
import json
p = json.load(open('<exp>/predictions/<model>/arb_math_numerical.json'))
for k, v in p.items():
    if 'ANSWER:' not in v['prediction']:
        print('%3s len=%6d  ...%s' % (k, len(v['prediction']), repr(v['prediction'][-60:])))
"
```

**结果**：15 条（deepseek 1 + qwen 14）**全部断在句子或 LaTeX 表达式中间**：

```
qwen 2   →  $y_8 = \sqrt
qwen 11  →  \log_{
qwen 44  →  \text{lcm}(9,
qwen 49  →  r^{-
```

模型自然写完不会停在 `\sqrt` 后面。根因是输出长度上限，不是格式遵循。

> **一个失败的判据**：最初想用「长度是否顶在同一个值」来判断截断，
> 这是错的 —— `max_out_len` 限的是 token 不是字符，LaTeX 密集文本
> 每 token 约 2 字符、纯英文约 4 字符，所以同样 4096 token 对应
> 8600–15000 字符，两组长度会大幅重叠。**看结尾才是可靠判据。**

**修复**：`max_out_len` 4096 → 16384（`max_seq_len=32768` 装得下）。

**影响**：

| | 4096 | 16384 |
|---|---|---|
| deepseek | 84.62 | 88.46 |
| qwen | **71.15** | **92.31** |
| qwen `no_delimiter_rate` | 26.92 | 0.00 |

**排名反转**：4096 下 deepseek 领先 13.5 分，16384 下 qwen 反超。
差距的主体不是数学能力，是输出长度预算。

**这是本项目最重要的发现**：论文没有规定 `max_out_len`，
而它造成了 21 分的分数偏移，远超常见的 ±5 分复现窗口。
即使拿到论文的完整评测代码，只要这个参数不同，分数也复现不了。

---

## 4. 判分模型 429 限流伪装成「抽取器不可靠」

**现象**：qwen 的 `llm_gap = -11.54`，`llm_extract_fail_rate = 13.46`，
看起来像 LLM 抽取器质量差。

**定位方法**：

```bash
grep -A5 "ARB" <exp>/logs/eval/<model>/arb_math_numerical.out
```

```
RateLimitError: Error code: 429 - {'code': 'rpm_rate_limit_exceeded', ...}
```

**根因**：OpenCompass 把两个模型的 eval 任务放在**两个独立子进程**里并行跑，
每个进程各开 `concurrency=8` 线程打向同一个判分端点 → 瞬时 16 并发，
超过千帆的 RPM 配额。

> 同一个坑在 infer 阶段也存在：`query_per_second` 是每进程独立的令牌桶，
> 不跨进程共享。两个模型并行时实际速率是配置值的两倍。

**修复**：`concurrency` 8 → 2。修复后 `llm_gap` 从 -11.54 收敛到 0.00。

**顺带修的实现缺陷**（都在 `LLMAnswerExtractor`）：

- 失败结果被写进缓存 → 一次网络抖动后每次重跑都命中缓存，永远修不好。
  改为区分 `(ok, value)`：API 失败不缓存，只缓存有效结论。
- 异常被完全吞掉 → 100% 失败时没有任何诊断信息。改为记录前 3 条并打印。
- `content` 为空被当作「模型说没有答案」缓存下来 → 带 thinking 的模型
  把 `max_tokens` 烧光时会命中这条路径。改为按失败处理。

---

## 5. 抽取器输入被静默截断

**现象**：无。这条是主动排查出来的，没有任何外部症状。

**根因**：`max_input_chars=12000` 是硬编码的，与 infer 阶段的 `max_out_len` 完全脱钩。
`max_out_len` 从 4096 提到 16384 后，prediction 最长达 40220 字符，
抽取器只看到末尾 30%。

**实测触发范围**：

```
deepseek  最长 14170   超 12000 的 3/52
qwen      最长 40220   超 12000 的 12/52
```

15 条被截断。结果没出错（答案在结尾，末尾窗口够用）—— **但那是运气，不是设计保证**。

**修复**：默认 `max_input_chars=None`（不截断）；显式设值且真的触发时计数、
打印警告，并输出 `llm_input_truncated_rate` 指标。

> 这与 §3 是同一类问题的不同层：**一个静默的截断参数，触发时没有任何信号**。
> 通用教训：任何会丢弃数据的参数都必须在触发时留痕。

---

## 6. 方差：52 题撑不住 ±5 分

**方法**：同一配置连跑三轮完整流程（infer + eval），各约 28 分钟。

| | run1 | run2 | run3 | 均值 | 极差 |
|---|---|---|---|---|---|
| deepseek `accuracy` | 92.31 | 86.54 | 90.38 | 89.74 | **5.77** |
| qwen `accuracy` | 92.31 | 92.31 | 92.31 | 92.31 | **0.00** |
| qwen `accuracy_llm` | 86.54 | 92.31 | 84.62 | 87.82 | 7.69 |

**逐题分析**（比极差更有信息量）：

```bash
python -c "
import json, glob
runs = {}
for i in (1,2,3):
    f = glob.glob(f'outputs/arb_var/run{i}/*/results/deepseek-v3.2/arb_math_numerical.json')[0]
    runs[i] = {v['idx'][0]: v['correct'][0] for v in json.load(open(f))['details']}
flip = [i for i in sorted(runs[1]) if len({runs[r][i] for r in (1,2,3)}) > 1]
print('翻转的题:', flip)
"
```

deepseek 有 **7/52 题（13.5%）判定不稳定**（idx 0, 4, 11, 25, 35, 39, 41）。
极差只有 5.77 是因为翻转方向部分抵消 —— 真实不稳定度高于极差显示的值，
**三轮不足以刻画分布**。

三轮的 `no_delimiter_rate` 和 `parse_fail_rate` 基本为 0，
说明翻转不来自 harness，而是模型本身在 `temperature=0` 下仍不确定
（服务端 batching、MoE 路由等）。

**结论**：一题 = 1.92 分，±5 分只允许 2.6 题翻转。
在 52 题规模 + API 模型的组合下，这个复现标准很难稳定满足。
建议报 `mean ± std` 并注明不稳定题数。

> 一个被数据推翻的预期：曾预计 LLM 抽取能降低方差（消除格式遵循这个变量）。
> 实测相反 —— qwen 的 `accuracy_llm` 极差 7.69 > `accuracy` 极差 0.00。
> 截断修复后 strict 抽取已几乎无损，LLM 抽取只剩下噪声贡献。

---

## 7. 分数与论文的差距

论文 Table 3（GPT-4 错误分析，每学科抽样 20–40 题）中
Math Numerical 的 "Correct answer" 为 **3%**。本次测得 88–92%。

可能的解释：

1. **模型进步** —— 2023 年的 GPT-4 无显式推理链，本次两个模型都是推理模型。
   能解释一部分，但三十倍不是常规进步的量级。
2. **数据污染** —— 论文当年刻意只通过 REST API 分发数据集、不发布到
   GitHub/HuggingFace，明确目的是防止被爬进训练语料。到 2026 年这道防线
   大概率已失效。
3. **判分口径偏松** —— 例如接受未化简的表达式（`(3 + 2·ln 2)/9` 求值后比对）。
   论文 Figure 1 是图，无精确数值，实际口径无法核对。

无法在本项目内证实或证伪，但必须在汇报中主动声明。

---

## 附：与论文的对照要点

- **没有官方参考实现**。`TheDuckAI/arb` 只是数据集网站（Next.js + REST API）。
  本实现从论文第 4 节的文字描述反推。
- **Table 1** = 数据集清单（全部 subset 的题数）；
  **Table 2** = 仅 symbolic 的人工判分结果；
  **Figure 1** = 自动判分部分（numerical + 选择题）。三者作用范围不同。
- **numerical 是全自动判分的**，人工只用于 symbolic 困难情形和 proof-like。
  所以复现在原理上可行。
- **论文的模型已全部下线**（gpt-4-0314、gpt-3.5-turbo-0301、text-davinci-003、
  claude-v1.3-100k），无法直接对照。
