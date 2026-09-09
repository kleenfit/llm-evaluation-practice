# MapQA 评测报告

**模型**：qwen3.5-35b-a3b（千帆 API，零样本）  
**数据集**：MapQA，arXiv 2211.08545（Chang et al., NeurIPS 2022 TRL Workshop）  
**评测框架**：VLMEvalKit（本地分支 `fix/redact-credentials-in-logs`，commit `8e1e878`）  
**运行**：`T20260907-193147`，3000 题约 57 分钟；判分口径修正后重打过一次分

---

## 摘要

2026-09-07，用 VLMEvalKit 在 MapQA（arXiv 2211.08545）的三个子集各随机抽 1000 题，
零样本评测 qwen3.5-35b-a3b，指标为论文口径的 Jaccard Index。

1. **retrieval 在三个子集上全部超过监督基线**（+32.0 / +4.5 / +0.5），
   但领先幅度差得极远，U 上是碾压，S 上只是打平。
2. **relational 在三个子集上一律落后**（−8.5 / −11.9 / −3.0），是最稳定的差距。
3. **总分 U 反超 9.8 分，R 落后 4.4 分，S 基本打平（−1.0，在抽样噪声内）**。

结果（Jaccard Index [%]）：

| 子集 | surface | retrieval | relational | All |
|---|---:|---:|---:|---:|
| MapQA-U | 100.00 | 92.70 | 72.45 | **84.25** |
| MapQA-R | 100.00 | 89.07 | 72.00 | **81.36** |
| MapQA-S | 99.11 | 86.82 | 74.89 | **82.30** |
| MapQA (all) | 99.68 | 89.63 | 73.11 | **82.64** |

相对论文 Table 3 `V-MODEQA w/ Tesseract OCR` 的差值：

| 子集 | Srf | Rtr | Rlt | All |
|---|---:|---:|---:|---:|
| MapQA-U | +0.0 | **+32.0** | −8.5 | **+9.8** |
| MapQA-R | +1.3 | +4.5 | **−11.9** | −4.4 |
| MapQA-S | +1.1 | +0.5 | −3.0 | −1.0 |

---

## 一、评测设置

### 1.1 数据来源

MapQA 是分级统计图（choropleth map）问答数据集，约 80 万题 / 6.2 万张地图，分三个子集：

| 子集 | 地图来源 | 特点 |
|---|---|---|
| MapQA-U | Kaiser Family Foundation 真实地图 | 统一风格、统一配色，分辨率偏低 |
| MapQA-R | 用 U 的真实数据重新绘制 | 55 种配色随机，train/val/test 配色不相交 |
| MapQA-S | 合成数据重新绘制 | 数据分布可控，答案偏置最小 |

题目由模板生成，分三类：**surface**（图例是不是连续条、有几个符号、有没有缺失数据）、
**retrieval**（某个州的值是多少、哪些州落在某个区间）、
**relational**（最高/最低值是多少、哪些州最高/最低、邻州范围内比较、两州比较）。

下载自官方 GitHub（OSU-slatelab/MapQA）的 Google Drive 发布包。注意发布包里 R 子集的目录名是
`MapQA_V`，抽样脚本里做了 `V → R` 的别名映射。

### 1.2 抽样方式

三个子集的 `test-QA.json` 各**随机抽 1000 题**（`random.Random(42).sample`，固定 seed），
合计 3000 题，写成 VLMEvalKit 的 TSV：

- 文件：`/Volumes/T7Dev/LMUData/MapQA_TEST3K.tsv`（378 MB）
- 图片直接读原 PNG 做 base64，不过 PIL 重编码（`dump_image` 会把一切转成 PNG，体积膨胀数倍）
- 保留 `subset` / `question_type` / `template_id` / `map_id` 字段，便于按论文口径分组和后续错例分析

论文按图像做 60/20/20 的 train/valid/test 划分。三个子集 test 的实际题数和本次抽样比例：

| 子集 | test 题数 | 本次抽样 | 比例 |
|---|---:|---:|---:|
| MapQA-U | 59795 | 1000 | 1.7% |
| MapQA-R | 51044 | 1000 | 2.0% |
| MapQA-S | 50116 | 1000 | 2.0% |

抽到的题型分布（随机抽样的自然结果，不是人为配比）：

| 子集 | surface | retrieval | relational | 合计 |
|---|---:|---:|---:|---:|
| MapQA-U | 111 | 432 | 457 | 1000 |
| MapQA-R | 94 | 394 | 512 | 1000 |
| MapQA-S | 112 | 394 | 494 | 1000 |

### 1.3 指标定义

对齐论文 §3.3：**Jaccard Index**。MapQA 有大量多答案题（平均每题 4 个答案），
所以按集合算 `|pred ∩ gold| / |pred ∪ gold|`，而不是精确匹配。

模型输出是自由文本，需要先归一化成答案集合：

- 按 `;` / `,` / `and` / `&` / 换行切分
- 去掉 `$` `%`、千分位逗号、首尾标点、冠词，统一小写
- **收缩区间连字符两侧的空格**（`$68- $146` → `68-146`）
- 州名缩写映射成全称（`CA` → `california`）
- 出现 yes/no token 时坍缩成单个 yes/no

按 `subset × question_type` 汇总，对齐论文 Table 3 的排布。**评测全程规则判分，没有用
judge 模型**（命令行里带的 `--judge deepseek-v3.2` 对本数据集不生效）。

第一版判分有两处归一化遗漏（`N/A`、区间里的空格），已修正，本报告全部为修正后数字，
修正前后总分差 +2.65；细节见**附录 A**。

### 1.4 模型与推理参数

| 项 | 值 |
|---|---|
| 模型 | qwen3.5-35b-a3b（千帆 `/v2/chat/completions`，VLMEvalKit `GPT4V` 类） |
| temperature | 0 |
| max_tokens | 512 |
| 图片 | `img_size=-1`（原图不缩放），`img_detail=high` |
| 并发 | `--api-nproc 2`（千帆 RPM=60，3 就 429） |
| 重试 / 超时 | retry=10 / 600s |

prompt 在原题后追加一段格式约束：

```
Answer the question using only the map. Output only the final answer, no explanation.
If there are multiple answers, list all of them separated by semicolons.
Use full state names (e.g. California, not CA).
For yes/no questions, answer "Yes" or "No".
```

3000 题里有 5 题重试耗尽后返回 `Failed to obtain answer via API.`，按 0 分计入，没有剔除。

---

## 二、结果

Jaccard Index [%]：

| 子集 | surface | retrieval | relational | All |
|---|---:|---:|---:|---:|
| MapQA-U | 100.00 | 92.70 | 72.45 | **84.25** |
| MapQA-R | 100.00 | 89.07 | 72.00 | **81.36** |
| MapQA-S | 99.11 | 86.82 | 74.89 | **82.30** |
| MapQA (all) | 99.68 | 89.63 | 73.11 | **82.64** |

抽样带来的 95% 置信区间约为 ±2.0（三个子集分别 ±2.0 / ±2.1 / ±2.0）；
分到 relational 上约 ±3.5，所以子集之间 2~3 分的差距不必当真。

形态很清楚：**surface 基本满分，retrieval 接近九成，relational 是短板**，三个子集一致。
三个子集的总分落在 81~84 的窄带里，U 略高。

---

## 三、与论文对比

对比基准取论文 Table 3 的 `V-MODEQA w/ Tesseract OCR`（论文自己提出的方法 + 真实 OCR，
是"可复现的最强监督基线"），同时列出人类水平。下面三张表按论文的一位小数排版。

**MapQA-U**

| 模型 / 方法 | Srf | Rtr | Rlt | All |
|---|---:|---:|---:|---:|
| V-MODEQA w/ Tesseract OCR（论文） | 100.0 | 60.7 | 81.0 | 74.5 |
| Human（论文） | 100.0 | 99.8 | 93.5 | 97.8 |
| **qwen3.5-35b-a3b（本次，零样本）** | **100.0** | **92.7** | **72.5** | **84.2** |
| Δ vs V-MODEQA | +0.0 | **+32.0** | −8.5 | **+9.8** |
| Δ vs Human | +0.0 | −7.1 | −21.0 | −13.5 |

**MapQA-R**

| 模型 / 方法 | Srf | Rtr | Rlt | All |
|---|---:|---:|---:|---:|
| V-MODEQA w/ Tesseract OCR（论文） | 98.7 | 84.6 | 83.9 | 85.8 |
| Human（论文） | 100.0 | 97.9 | 89.3 | 92.4 |
| **qwen3.5-35b-a3b（本次，零样本）** | **100.0** | **89.1** | **72.0** | **81.4** |
| Δ vs V-MODEQA | +1.3 | +4.5 | **−11.9** | −4.4 |
| Δ vs Human | +0.0 | −8.8 | −17.3 | −11.0 |

**MapQA-S**

| 模型 / 方法 | Srf | Rtr | Rlt | All |
|---|---:|---:|---:|---:|
| V-MODEQA w/ Tesseract OCR（论文） | 98.0 | 86.3 | 77.9 | 83.3 |
| Human（论文） | 87.5 | 98.4 | 85.4 | 89.8 |
| **qwen3.5-35b-a3b（本次，零样本）** | **99.1** | **86.8** | **74.9** | **82.3** |
| Δ vs V-MODEQA | +1.1 | +0.5 | −3.0 | −1.0 |
| Δ vs Human | +11.6 | −11.6 | −10.5 | −7.5 |

三句话概括：

1. **retrieval 在三个子集上全部超过监督基线**（+32.0 / +4.5 / +0.5），
   但领先幅度差得极远，U 上是碾压，S 上只是打平。
2. **relational 在三个子集上一律落后**（−8.5 / −11.9 / −3.0），是最稳定的差距。
3. **总分 U 反超 9.8 分，R 落后 4.4 分，S 基本打平（−1.0，在抽样噪声内）**。

---

## 四、差异归因

### 4.1 retrieval 的领先幅度，和论文 OCR 的短板严格同向

论文的所有模型都不直接读图上的文字，文字信息由一个独立的 OCR 模块给出，
再用字符串匹配把问题里的区间替换成 `legend_1..legend_M` 符号。论文 Table 6 报了
Tesseract 认图例文字的准确率，和我们的 retrieval 领先幅度并排看：

| | MapQA-U | MapQA-R | MapQA-S |
|---|---:|---:|---:|
| Tesseract 图例识别准确率（论文 Table 6） | **48.7** | 92.3 | 94.1 |
| 我们的 retrieval − V-MODEQA | **+32.0** | +4.5 | +0.5 |

两行是同一个故事：U 是 KFF 的真实地图，分辨率相对低，Tesseract 只能认对不到一半的图例文字，
论文在 U 上的 retrieval 就被压到 60.7（换成 Oracle OCR 立刻回到 99.9）；
R / S 的图例是自己画的、清晰，OCR 准确率 92~94，论文的 retrieval 也就上到 84~86，
我们的领先随之收缩到几乎为零。

**所以 retrieval 这一栏真正说明的是"端到端 VLM 不受独立 OCR 模块的瓶颈约束"，
而不是"我们比论文更会读地图"。** 一旦 OCR 不是瓶颈，两边读色块的能力就在同一水平线上。

### 4.2 relational 为什么落后：显式抽表 + 表格问答 vs 一次前向

V-MODEQA 的做法是两段式：先用多输出模型把地图还原成一张"州 → 值"的结构化表，
再在这张表上做表格问答。一旦表抽对了，"哪些州最低"就是一次确定性的
`argmin` + 全表扫描，50 个州一个不漏，也不会多。

我们是让 VLM 一次前向直接给答案，等价于在像素上"心算"这次扫描。
错例分析里能看到这条差距的具体形态：

- **漏答州是第一大错因**（relational 131 题 / retrieval 303 题）。把所有答案是州名集合的题
  放一起看，金标平均 9.30 个州，模型平均只答 8.58 个，平均漏 1.31 个、多 0.58 个——
  颜色接近的色块，模型倾向于少圈几个。
- **yes/no 题有明显的"否认"偏置**。830 道 yes/no 题整体判对 84.5%，但金标是 yes 的
  364 题里错了 118 题（32.4%），金标是 no 的 466 题里只错 11 题（2.4%）。
  "这个州是不是全国最高"拿不准时，模型就答 No。论文在出题时特意平衡了 yes/no 比例
  来防这种偏置，我们正好撞上。
- **相对地，"范围"本身模型是懂的**。用州邻接表和人口普查分区表逐条查，
  预测里出现范围外州份的只有 9 题（占 relational 错例 1.6%）。
  也就是说，模型知道哪些州挨着俄亥俄、哪些州属于中西部，错的是范围内的值比较。

按模板族拆 relational，还能看出第三类问题的分布很不均匀：

| 模板族 | 题数 | MapQA-U | MapQA-R | MapQA-S |
|---|---:|---:|---:|---:|
| 问"哪些州"最高/最低 | 469 | 79.8 | 70.7 | 70.1 |
| 问"最高/最低值是多少" | 401 | **52.4** | 63.9 | 81.9 |
| yes/no 判定 | 593 | 83.0 | 78.5 | 74.4 |

U 上"问值"只有 52.4，是全表最低的一格——原因见 4.3。

### 4.3 U 上的 relational 短板：问"值"答成州名

103 题 relational 错例是"题目问最高/最低**值**是多少（金标是图例区间），模型答了一串州名"，
其中 62 题在 U。这不是推理错误，是把 `What is the highest value` 读成了
`Which states have the highest value`。有意思的是论文里提到人类标注员也犯同一个错。

U 上尤其突出，猜测和 KFF 图例带 `$` `%` 前缀有关——模型倾向于避开数值直接说州名。
这条**大概率能靠 prompt 修掉**：明确要求"问值时原样输出图例上的区间文本"。
如果这 103 题能收回大半，U / R 的 relational 还能再往上走几分。

### 4.4 S 上差距最小

S 是合成数据 + 随机配色，论文的模型没有真实数据的相关性可蹭，V-MODEQA 也只有 83.3。
我们在 S 上 82.3，**−1.0 落在抽样噪声内，不构成差距**。

---

## 五、不可比因素（重要）

这张对比表只能当作"量级参考"，下面几条都会实质影响数字，方向不一。

1. **零样本 vs 监督训练**。V-MODEQA 在 MapQA 各子集约 15~18 万条训练数据上训过，
   答案空间是封闭的分类问题；我们一条 MapQA 训练数据都没用。这一条对我们不利。
2. **1000 题抽样 vs 全量 test**。每子集 2% 左右的随机抽样，95% 置信区间约 ±2.0
   （relational 单项约 ±3.5）。S 上 1.0 分的差距完全在噪声范围内，不能算"确实落后"。
3. **自由生成 + 正则归一化 vs 分类器**。论文把问题里的图例区间替换成 `legend_j`，
   模型输出 `legend_j`，最后用 OCR 结果映射回字符串——**区间字符串怎么写根本不参与打分**。
   我们要求模型逐字符复现 `68-146` 这样的区间，写法不同就判 0。
   已经在归一化里补掉了 `$` `%` 和空格两类差异（见附录 A，共 79 题、总分 +2.65），
   但这条不对称仍然存在：论文那侧的答案空间是封闭的，我们这侧是开放的，
   还可能有没被归一化覆盖到的写法。
4. **人类基线样本极小**。论文的 Human 行是 4 名学生每子集各答 50 题，
   S 上 surface 只有 87.5 就是这么来的（我们 99.1，不代表"超过人类"）。
5. **图像预处理不同**。论文所有模型都把图 padding + resize 到 448×448；
   我们送的是原图（`img_size=-1`, `img_detail=high`），信息量更大。这一条对我们有利。
6. **5 题 API 失败按 0 分计入**，未剔除。影响不到 0.2 分，量级可忽略。

---

## 六、错例分析摘要

完整版见 `notes/mapqa_error_analysis.md`。3000 题里 Jaccard < 1 的 1016 题（33.9%），
surface 只错 1 题。

**relational（565 题错），前 5 类**

| 错误类型 | 数量 | 占比 |
|---|---:|---:|
| 漏答州 | 131 | 23.2% |
| 答非所问：问"值"答成州名 | 103 | 18.2% |
| 多答州 | 103 | 18.2% |
| 大小比较错：全局 / 分区极值判定 | 61 | 10.8% |
| 最高最低找错：极值区间读错 | 36 | 6.4% |

完整分类见 `notes/mapqa_error_analysis.md`。

**retrieval（450 题错）**：漏答州 303、既漏又多 79、色块读错（取到相邻区间）34、
多答州 30、API 调用失败 3、色块判读全错 1。

三个值得单独说的点：

1. **"问值"和"问州"分不清（103 题）** —— 见 4.3，是唯一一条看起来能靠 prompt 直接收回的。
2. **漏答倾向**是系统性的，不是随机的（见 4.2）。retrieval 的错例里三分之二是纯漏答。
3. **范围理解基本没问题**，9 题而已，且都是明确的地理错误
   （把 Delaware / West Virginia 当东北部、把 Oklahoma / Texas 当中西部）。

---

## 七、复现命令

```bash
conda activate vlmeval

# 1) 建 TSV（三个子集各抽 1000 题，seed=42）
python -u scripts/mapqa/make_mapqa_tsv.py \
    --root <MapQA 解压目录> \
    --out  /Volumes/T7Dev/LMUData/MapQA_TEST3K.tsv

# 2) 把 MapQA 数据集注册进 VLMEvalKit（判分口径修正也在这一步装进去）
python -u scripts/mapqa/install_mapqa_dataset.py --vlmeval ../eval_practice/VLMEvalKit

# 3) 推理 + 打分（configs/mapqa_qwen35.json.tpl 里的 __KEY1__ 换成实际 key，data 换成 MapQA_TEST3K）
usekey 1
python -u run.py --config <填好的 config>.json --api-nproc 2 --work-dir ./outputs

# 3') 只重打分（不重新推理）——直接对预测文件调 evaluate()，不要用 --reuse，理由见附录 A
#     依赖 $LMUData 指向 /Volumes/T7Dev/LMUData（conda 环境 hook 已设好）
python -u -c "
from vlmeval.dataset import build_dataset
pred = 'outputs/.../qwen3.5-35b-a3b_MapQA_TEST3K.xlsx'
print(build_dataset('MapQA_TEST3K').evaluate(pred))
"

# 4) 与论文并排
python -u scripts/mapqa/compare_with_paper.py \
    --acc outputs/qwen3.5-35b-a3b/T20260907-193147/qwen3.5-35b-a3b_MapQA_TEST3K_acc.csv \
    --by-subset

# 5) 错例分析
python -u scripts/mapqa/error_analysis.py \
    --score outputs/.../qwen3.5-35b-a3b_MapQA_TEST3K_score.xlsx \
    --pred  outputs/.../qwen3.5-35b-a3b_MapQA_TEST3K.xlsx \
    --out   notes/mapqa_error_analysis.md
```

第 3'、4、5 步这次都跑通了；第 1~3 步是本次结果的来源命令，写报告时没有重跑推理。

---

## 八、待办

- [ ] prompt 里补一句"问值时原样给图例区间"，看 103 题的"答非所问"能收回多少（4.3）
- [ ] 抽查一批仍判 0 的区间答案，确认归一化没有别的没覆盖到的写法（五-3）

---

## 附录 A：判分口径说明

### A.1 修正前 vs 修正后

第一版打分有两处口径问题，都判错在"模型答对了但没拿到分"这一侧，已经修掉并重打了分。
正文全部数字为**修正后**：

1. **`N/A` 被 pandas 读成 NaN — 38 题**。金标 `["N/A"]` 表示该州在地图上缺数据，
   模型也答了 `N/A`，本该满分；但 `evaluate()` 里 `load(eval_file)` 走 pandas 默认的
   `na_values`，预测列的字符串 `N/A` 变成 `NaN`，`astype(str)` 之后成了 `"nan"`，判 0。
   修法：`pd.read_excel(eval_file, keep_default_na=False)`。
2. **区间归一化漏掉空格 — 41 题**（全部在 U）。模型答 `$68- $146`，去掉 `$` `%` 之后剩下
   `68- 146`，与金标 `68-146` 不等，判 0。修法：去符号之后补一步
   `re.sub(r'\s*-\s*', '-', s)`。

| subset | 修正前 | 修正后 | Δ |
|---|---:|---:|---:|
| MapQA-U | 78.90 | 84.25 | +5.35 |
| MapQA-R | 79.76 | 81.36 | +1.60 |
| MapQA-S | 81.30 | 82.30 | +1.00 |
| MapQA (all) | 79.99 | 82.64 | +2.65 |

两处都只改判分、不重新推理。修改在 `scripts/mapqa/install_mapqa_dataset.py` 生成的
`vlmeval/dataset/mapqa.py` 里，离线分析用的 `scripts/mapqa/mapqa_norm.py` 已同步。

### A.2 重打分为什么不能走 `--reuse`

一是 `--reuse --reuse-aux all` 会把源 run 的 `_score.xlsx` / `_acc.csv` 一起拷过来，
可能直接沿用旧分数；二是当预测文件格式发生转换时（xlsx ↔ tsv/csv），
`copy_prediction_file` 会走 `load()` 的 pandas 默认 `na_values`，
把预测里的 `N/A` 读成空值——正是 A.1 第 1 条的坑，只不过挪到了拷贝阶段。
同格式的 reuse 是 `shutil.copy2` 逐字节复制，不会踩到。
最稳的做法是直接对原始预测文件调 `evaluate()`，见复现命令 3'。
