# MapQA 错例分析 — qwen3.5-35b-a3b

- 数据：`qwen3.5-35b-a3b_MapQA_TEST3K_score.xlsx + qwen3.5-35b-a3b_MapQA_TEST3K.xlsx`
- 样本：MapQA-U / R / S 各 1000 题，共 3000 题；Jaccard < 1 的 1016 题（33.9%）
- surface 只错 1 题，不单列
- 分类互斥，判定优先级：先看答案形态（yes/no、州名、图例区间），再看范围约束（邻州集合 / 人口普查分区），最后看集合关系（子集 / 超集 / 不相交）
- 「范围外」判定是保守的：只有当预测里的州既不在硬编码的邻接表 / 分区表里，也从未在同一锚点的任何金标答案中出现过，才算范围理解错
- 复现：`python -u scripts/mapqa/error_analysis.py --score … --pred … --out notes/mapqa_error_analysis.md`

## relational（主分析）

共 1463 题，Jaccard < 1 的 565 题（38.6%）。

| 错误类型 | 数量 | 占错例 |
|---|---:|---:|
| 漏答州 | 131 | 23.2% |
| 答非所问：问「值」答成州名 | 103 | 18.2% |
| 多答州 | 103 | 18.2% |
| 大小比较错：全局 / 分区极值判定 | 61 | 10.8% |
| 最高最低找错：极值区间读错 | 36 | 6.4% |
| 大小比较错：两州直接比较 | 34 | 6.0% |
| 既漏又多 | 34 | 6.0% |
| 大小比较错：邻州范围内的极值判定 | 33 | 5.8% |
| 最高最低找错：选中完全不同的州 | 18 | 3.2% |
| 边界州 / 分区范围理解错 | 9 | 1.6% |
| 其他：API 调用失败，没有拿到答案 | 2 | 0.4% |
| 答非所问：问「州」答成数值 / 区间 | 1 | 0.2% |
| **合计** | **565** | **100.0%** |

按子集拆开：

| 错误类型 | MapQA-R | MapQA-S | MapQA-U |
|---|---|---|---|
| 漏答州 | 43 | 57 | 31 |
| 答非所问：问「值」答成州名 | 27 | 14 | 62 |
| 多答州 | 44 | 35 | 24 |
| 大小比较错：全局 / 分区极值判定 | 21 | 24 | 16 |
| 最高最低找错：极值区间读错 | 20 | 9 | 7 |
| 大小比较错：两州直接比较 | 7 | 18 | 9 |
| 既漏又多 | 11 | 17 | 6 |
| 大小比较错：邻州范围内的极值判定 | 15 | 12 | 6 |
| 最高最低找错：选中完全不同的州 | 8 | 7 | 3 |
| 边界州 / 分区范围理解错 | 4 | 0 | 5 |
| 其他：API 调用失败，没有拿到答案 | 2 | 0 | 0 |
| 答非所问：问「州」答成数值 / 区间 | 1 | 0 | 0 |

### 漏答州（131 题）

- **[MapQA-S / relational_4]** Among the states that border Oregon , which have the lowest value ?
  - 金标：`california; idaho; washington`
  - 模型：`California; Idaho` → Jaccard 0.67（漏 1 个）
- **[MapQA-U / relational_2]** Which states have the lowest value in the South ?
  - 金标：`arkansas; delaware; kentucky; mississippi; oklahoma; west virginia`
  - 模型：`West Virginia; Kentucky; Mississippi; Arkansas; Oklahoma` → Jaccard 0.83（漏 1 个）

### 答非所问：问「值」答成州名（103 题）

- **[MapQA-U / relational_9]** What is the highest value in the West  ?
  - 金标：`2620000-6091600`
  - 模型：`California` → Jaccard 0.00
- **[MapQA-R / relational_8]** What is the lowest value in the MidWest ?
  - 金标：`2.6-6.8`
  - 模型：`Minnesota; Iowa; Wisconsin` → Jaccard 0.00

### 多答州（103 题）

- **[MapQA-R / relational_0]** Which states have the lowest value in the USA ?
  - 金标：`utah`
  - 模型：`Utah; North Dakota` → Jaccard 0.50（多 1 个）
- **[MapQA-R / relational_0]** Which states have the lowest value in the USA ?
  - 金标：`north dakota`
  - 模型：`Wyoming; North Dakota` → Jaccard 0.50（多 1 个）

### 大小比较错：全局 / 分区极值判定（61 题）

- **[MapQA-R / relational_12]** Does Wyoming have the lowest value in the USA ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00
- **[MapQA-S / relational_14]** Does Maryland have the lowest value in the South ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00

### 最高最低找错：极值区间读错（36 题）

- **[MapQA-R / relational_11]** What is the highest value in states that border Washington ?
  - 金标：`881500-1937000`
  - 模型：`117,400-804,400` → Jaccard 0.00
- **[MapQA-R / relational_11]** What is the highest value in states that border North Carolina ?
  - 金标：`17.1-24.8`
  - 模型：`13.4%-16.8%` → Jaccard 0.00

### 大小比较错：两州直接比较（34 题）

- **[MapQA-R / relational_20]** Does Tennessee have the same value as Nevada ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00
- **[MapQA-S / relational_19]** Does Massachusetts have a lower value than Minnesota ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00

### 既漏又多（34 题）

- **[MapQA-S / relational_4]** Among the states that border New Jersey , which have the lowest value ?
  - 金标：`new york; pennsylvania`
  - 模型：`New York; Delaware` → Jaccard 0.33（漏 1 个 / 多 1 个）
- **[MapQA-S / relational_0]** Which states have the lowest value in the USA ?
  - 金标：`arkansas; colorado; connecticut; florida; hawaii; idaho; iowa; kentucky; louisiana; maine; maryland; massachusetts; mic…`
  - 模型：`Texas; Florida; North Carolina; South Carolina; Georgia; Alabama; Mississippi; Louisiana; Arkansas; Missouri; Iowa; Min…` → Jaccard 0.65（漏 1 个 / 多 16 个）

### 大小比较错：邻州范围内的极值判定（33 题）

- **[MapQA-R / relational_16]** Among the states that border Iowa , does Missouri have the lowest value ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00
- **[MapQA-S / relational_16]** Among the states that border Minnesota , does Wisconsin have the lowest value ?
  - 金标：`yes`
  - 模型：`No` → Jaccard 0.00

### 最高最低找错：选中完全不同的州（18 题）

- **[MapQA-R / relational_5]** Among the states that border Montana , which have the highest value ?
  - 金标：`idaho`
  - 模型：`North Dakota; South Dakota; Wyoming` → Jaccard 0.00
- **[MapQA-S / relational_4]** Among the states that border Georgia , which have the lowest value ?
  - 金标：`north carolina`
  - 模型：`Florida; Alabama` → Jaccard 0.00

### 边界州 / 分区范围理解错（9 题）

- **[MapQA-U / relational_5]** Among the states that border Minnesota , which have the highest value ?
  - 金标：`wisconsin`
  - 模型：`Wisconsin; Michigan` → Jaccard 0.50（范围外：michigan）
- **[MapQA-U / relational_2]** Which states have the lowest value in the Northeast ?
  - 金标：`connecticut; maine; new hampshire; rhode island; vermont`
  - 模型：`Maine; New Hampshire; Rhode Island; Connecticut; Delaware; West Virginia` → Jaccard 0.57（范围外：delaware、west virginia）

### 其他：API 调用失败，没有拿到答案（2 题）

- **[MapQA-R / relational_8]** What is the lowest value in the South ?
  - 金标：`16-18`
  - 模型：`Failed to obtain answer via API.` → Jaccard 0.00
- **[MapQA-R / relational_0]** Which states have the lowest value in the USA ?
  - 金标：`alaska; arkansas; delaware; hawaii; idaho; iowa; kansas; maine; mississippi; montana; nebraska; new hampshire; north da…`
  - 模型：`Failed to obtain answer via API.` → Jaccard 0.00

### 答非所问：问「州」答成数值 / 区间（1 题）

- **[MapQA-R / relational_3]** Which states hav the highest value in the South ?
  - 金标：`florida; texas`
  - 模型：`No states in the South have the highest value (5-11). The highest values are in Arizona, New Mexico, Utah, Michigan, an…` → Jaccard 0.00

## retrieval（简略）

共 1220 题，Jaccard < 1 的 450 题（36.9%）。

| 错误类型 | 数量 | 占错例 |
|---|---:|---:|
| 漏答州 | 303 | 67.3% |
| 既漏又多 | 79 | 17.6% |
| 色块读错：取到相邻的图例区间 | 34 | 7.6% |
| 多答州 | 30 | 6.7% |
| 其他：API 调用失败，没有拿到答案 | 3 | 0.7% |
| 色块判读全错：与金标完全不重合 | 1 | 0.2% |
| **合计** | **450** | **100.0%** |

按子集拆开：

| 错误类型 | MapQA-R | MapQA-S | MapQA-U |
|---|---|---|---|
| 漏答州 | 103 | 96 | 104 |
| 既漏又多 | 27 | 38 | 14 |
| 色块读错：取到相邻的图例区间 | 10 | 18 | 6 |
| 多答州 | 9 | 9 | 12 |
| 其他：API 调用失败，没有拿到答案 | 3 | 0 | 0 |
| 色块判读全错：与金标完全不重合 | 0 | 1 | 0 |

### 漏答州（303 题）

- **[MapQA-U / retrieval_1]** Name the states that have a value in the range 4.5%-6.3% ?
  - 金标：`alabama; arizona; california; colorado; delaware; idaho; illinois; kansas; kentucky; maryland; mississippi; missouri; n…`
  - 模型：`Washington; Idaho; California; Utah; Colorado; New Mexico; Kansas; Missouri; Illinois; Wisconsin; Kentucky; Tennessee; …` → Jaccard 0.76（漏 6 个）
- **[MapQA-U / retrieval_1]** Name the states that have a value in the range 32.9%-35.2% ?
  - 金标：`delaware; idaho; maine; maryland; mississippi; missouri; nevada; new hampshire; new mexico; north carolina; ohio; oklah…`
  - 模型：`Washington; Idaho; Nevada; Utah; New Mexico; Texas; Oklahoma; Missouri; Tennessee; North Carolina; South Carolina; West…` → Jaccard 0.86（漏 3 个）

### 既漏又多（79 题）

- **[MapQA-S / retrieval_1]** Name the states that have a value in the range 47.6%-61.0% ?
  - 金标：`colorado; georgia; idaho; kansas; louisiana; massachusetts; michigan; montana; nebraska; north carolina; oregon; south …`
  - 模型：`Washington; Oregon; Montana; North Dakota; Nebraska; Kansas; Oklahoma; Louisiana; Michigan; South Carolina; North Carol…` → Jaccard 0.67（漏 2 个 / 多 3 个）
- **[MapQA-R / retrieval_1]** Name the states that have a value in the range 1,225-55,651 ?
  - 金标：`alaska; arkansas; connecticut; delaware; hawaii; idaho; kansas; maine; minnesota; missouri; montana; nebraska; nevada; …`
  - 模型：`Maine; New Hampshire; Vermont; Connecticut; Delaware; West Virginia; Arkansas; Missouri; Minnesota; Iowa; Kansas; Nebra…` → Jaccard 0.83（漏 3 个 / 多 1 个）

### 色块读错：取到相邻的图例区间（34 题）

- **[MapQA-R / retrieval_0]** What is the value of Oklahoma ?
  - 金标：`940-1310`
  - 模型：`730-930` → Jaccard 0.00
- **[MapQA-S / retrieval_0]** What is the value of Iowa ?
  - 金标：`50.9-56.9`
  - 模型：`44.8%-50.3%` → Jaccard 0.00

### 多答州（30 题）

- **[MapQA-S / retrieval_1]** Name the states that have a value in the range 45.4%-60.5% ?
  - 金标：`arizona; arkansas; delaware; florida; missouri; nevada; new jersey; new mexico; oregon; south dakota; virginia; wiscons…`
  - 模型：`Washington; Oregon; Nevada; Arizona; New Mexico; South Dakota; Wisconsin; Missouri; Arkansas; Florida; Virginia; New Je…` → Jaccard 0.86（多 2 个）
- **[MapQA-R / retrieval_1]** Name the states that have a value in the range 11.2%-13.9% ?
  - 金标：`alaska; colorado; connecticut; delaware; hawaii; maryland; massachusetts; minnesota; new hampshire; new jersey; rhode i…`
  - 模型：`Washington; Colorado; Minnesota; Virginia; Maryland; Delaware; New Jersey; Connecticut; Massachusetts; Rhode Island; Ne…` → Jaccard 0.93（多 1 个）

### 其他：API 调用失败，没有拿到答案（3 题）

- **[MapQA-R / retrieval_0]** What is the value of Alabama ?
  - 金标：`n/a`
  - 模型：`Failed to obtain answer via API.` → Jaccard 0.00
- **[MapQA-R / retrieval_0]** What is the value of Wyoming ?
  - 金标：`2.5-5.0`
  - 模型：`Failed to obtain answer via API.` → Jaccard 0.00

### 色块判读全错：与金标完全不重合（1 题）

- **[MapQA-S / retrieval_1]** Name the states that have a value in the range 73.7%-73.7% ?
  - 金标：`georgia; new hampshire`
  - 模型：`Utah; Massachusetts` → Jaccard 0.00

## yes/no 题的答案偏置

830 道 yes/no 题，整体判对率 84.5%。混淆矩阵：

| 金标 \ 模型 | no | yes |
|---|---|---|
| no | 455 | 11 |
| yes | 118 | 246 |

金标 yes 的 364 题里答错 118 题（32.4%），金标 no 的 466 题里只答错 11 题（2.4%）——模型倾向于否认，"这个州是不是最高/最低" 拿不准时就答 No。论文在生成时特意平衡了 yes/no 的比例来防这种偏置。

## 多答案题的漏答倾向

把答案是州名集合的题（retrieval_1 + relational_0~5，共 1078 题）放一起看：金标平均 9.30 个州，模型平均答 8.58 个；平均漏 1.31 个、多 0.58 个。漏答是主要失分方向，说明模型在颜色接近的色块上倾向于少圈几个州。

## 判分口径：修正前 vs 修正后

第一版打分有两处口径问题，都已修在 `vlmeval/dataset/mapqa.py` 里（`scripts/mapqa/install_mapqa_dataset.py` 生成），本文件的数字是修正后的。两处都只改判分，不重新推理。

**1. N/A 被 pandas 读成 NaN — 影响 38 题**

金标是 `["N/A"]`（该州在地图上缺数据），模型也答了 `N/A`，本该满分。但 `evaluate()` 里 `load(eval_file)` 走 pandas 默认的 `na_values`，预测列里的字符串 `N/A` 被读成 `NaN`，`astype(str)` 之后变成 `"nan"`，判 0 分。修法：`pd.read_excel(eval_file, keep_default_na=False)`。

**2. 区间归一化漏掉空格 — 影响 41 题**

模型答 `$68- $146`，`_norm_token` 去掉 `$` / `%` 之后剩下 `68- 146`，与金标 `68-146` 不等，判 0 分。修法：在去掉 `$` / `%` 之后加一步 `re.sub(r"\s*-\s*", "-", s)`。

| subset | question_type | 修正前 | 修正后 | Δ |
|---|---|---:|---:|---:|
| MapQA-R | surface | 100.00 | 100.00 | +0.00 |
| MapQA-R | retrieval | 85.01 | 89.07 | +4.06 |
| MapQA-R | relational | 72.00 | 72.00 | +0.00 |
| MapQA-R | **All** | **79.76** | **81.36** | **+1.60** |
| MapQA-S | surface | 99.11 | 99.11 | +0.00 |
| MapQA-S | retrieval | 84.28 | 86.82 | +2.54 |
| MapQA-S | relational | 74.89 | 74.89 | +0.00 |
| MapQA-S | **All** | **81.30** | **82.30** | **+1.00** |
| MapQA-U | surface | 100.00 | 100.00 | +0.00 |
| MapQA-U | retrieval | 82.98 | 92.70 | +9.72 |
| MapQA-U | relational | 69.93 | 72.45 | +2.52 |
| MapQA-U | **All** | **78.90** | **84.25** | **+5.35** |
| **MapQA (all)** | **All** | **79.99** | **82.64** | **+2.65** |
