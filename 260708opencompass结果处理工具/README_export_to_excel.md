# OpenCompass Excel Export Tool

本工具是为 **OpenCompass** 评测结果编写的辅助导出脚本，用于把 OpenCompass 运行后生成的 `summary`、`results` 和 `predictions` 文件整理成一个更易查看的 Excel 文件。

> 说明：本工具是基于 OpenCompass 输出文件格式编写的独立辅助工具，不属于 OpenCompass 官方项目，也不包含、复制或修改 OpenCompass 源代码。OpenCompass 的版权、商标和许可证归其原项目所有。本工具仅用于读取用户本地已生成的评测结果并进行格式化整理。

## 功能

脚本会读取一次 OpenCompass 评测运行目录，并生成一个 `.xlsx` 文件。

Excel 文件只包含两个工作表：

1. `summary`
   - 读取 `summary/*.md`
   - 将 OpenCompass 生成的 summary 表格写入 Excel

2. `details`
   - 逐题写入评测明细
   - 包含以下列：

| 列名 | 含义 |
|---|---|
| 题号 | 题目的编号；如果检测到多个数据集，会自动加上数据集名前缀 |
| 是否正确 | OpenCompass 判断的该题是否正确 |
| 模型结果 | 模型的完整输出 |
| 原始题目 | 当前这一条题目本身，不包含 few-shot 示例或整个题库 |
| 标准答案 | OpenCompass 结果文件中的标准答案 |
| 回答是否为空 | 根据模型输出是否为空进行判断 |

## 使用方法

在 OpenCompass 项目根目录下运行：

```bash
python tools/export_to_excel.py --input 目标文件夹 --output 输出文件.xlsx
```

例如：

```bash
python tools/export_to_excel.py \
  --input outputs/default/20260707_155019 \
  --output result.xlsx
```

也可以使用短参数：

```bash
python tools/export_to_excel.py -i outputs/default/20260707_155019 -o result.xlsx
```

## 默认行为

如果不指定 `--input`：

```bash
python tools/export_to_excel.py
```

脚本会自动读取：

```text
outputs/default
```

并在其中递归查找最新的、同时包含以下两个目录的运行结果文件夹：

```text
summary/
results/
```

也就是说，它支持以下常见结构：

```text
outputs/default/20260707_155019/
├── predictions/
├── results/
└── summary/
```

也支持：

```text
outputs/default/实验名称/20260707_155019/
├── predictions/
├── results/
└── summary/
```

如果不指定 `--output`，脚本会自动生成输出文件名，格式为：

```text
模型名-数据集名-时间戳文件夹名.xlsx
```

并默认保存到 input 文件夹下。

例如：

```text
qianfan-deepseek-v3.2-demo_gsm8k-20260707_155019.xlsx
```

## 输入目录要求

输入目录应当是一次 OpenCompass 评测运行后的结果目录，目录中通常包含：

```text
configs/
logs/
predictions/
results/
summary/
```

其中脚本主要使用：

```text
summary/*.md
results/**/*.json
predictions/**/*.json
```

`summary/*.md` 用于生成 `summary` 工作表。

`results/**/*.json` 用于读取每道题的：

```text
pred
answer
correct
example_abbr
```

`predictions/**/*.json` 用于读取每道题的：

```text
origin_prompt
prediction
gold
```

## 多数据集情况

脚本可以读取同一个运行目录下的多个 result json。

如果检测到多个数据集，`details` 表中的题号会自动加上数据集名前缀，避免不同数据集的题号冲突。

例如：

```text
demo_gsm8k_0
ceval-computer_network_0
mmlu-abstract_algebra_0
```

一般情况下，建议一次只导出一个主要数据集；如果目录中确实有多个数据集结果，脚本也会尽量合并写入同一个 Excel 文件。

## 依赖

脚本需要安装 `openpyxl`：

```bash
pip install openpyxl
```

如果当前 OpenCompass 环境中已经安装过 `openpyxl`，可以直接运行。

## 输出效果

生成的 Excel 文件会自动设置：

- 表头样式
- 冻结首行
- 自动筛选
- 自动换行
- 合理列宽
- 正确 / 错误的简单颜色区分
- 空回答标记

目标是方便人工检查模型输出，而不是保留 OpenCompass 的全部原始调试信息。

## 常见命令

自动查找最新结果并导出：

```bash
python tools/export_to_excel.py
```

指定输入目录，自动命名输出：

```bash
python tools/export_to_excel.py --input outputs/default/20260707_155019
```

指定输入和输出：

```bash
python tools/export_to_excel.py \
  --input outputs/default/20260707_155019 \
  --output gsm8k_result.xlsx
```

## 注意事项

- 本工具只读取本地文件，不会修改 OpenCompass 的评测结果。
- 本工具不会重新评分，只使用 OpenCompass 已经生成的 `correct` 字段。
- `模型结果` 来自 `predictions` 文件中的 `prediction` 字段。
- `原始题目` 会从 `origin_prompt` 中提取最后一道题，避免把 few-shot 示例一起写入 Excel。
- 如果 `predictions` 文件缺失，脚本会尽量使用 `results` 文件中的 `pred` 字段兜底。
- 如果目录结构和 OpenCompass 默认输出差异过大，可能需要手动指定 `--input`。
