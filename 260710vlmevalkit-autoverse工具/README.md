# AutoVerse

AutoVerse is an auxiliary tool for **VLMEvalKit** that provides flexible post-processing and precise Excel export for evaluation results.

Unlike modifying `run.py`, AutoVerse works as an external wrapper around the original evaluation pipeline. It can either:

- Run the original VLMEvalKit evaluation and automatically process the generated results.
- Analyze existing evaluation result folders without running any model.

The original VLMEvalKit workflow and output files remain unchanged.

---

## Features

- Call the original `run.py` directly.
- Analyze existing VLMEvalKit output folders.
- Automatically discover valid evaluation result files.
- Display all available output columns.
- Export only selected columns to a new Excel file.
- Interactive column selection.
- Target-column validation and automatic correction mode.
- No modification to the original VLMEvalKit source code.

---

# Workflow

## Mode 1: Run Evaluation + Export

AutoVerse first calls the original VLMEvalKit evaluation.

```
AutoVerse
        │
        ▼
Original run.py
        │
        ▼
Inference
        │
        ▼
Evaluation
        │
        ▼
Original VLMEvalKit outputs
        │
        ▼
AutoVerse
        │
        ▼
Select columns
        │
        ▼
New Excel
```

---

## Mode 2: Analyze Existing Results

If evaluation has already finished:

```
Existing Output Folder
        │
        ▼
AutoVerse
        │
        ▼
Detect result files
        │
        ▼
List available columns
        │
        ▼
Export selected columns
```

No model inference or evaluation will be executed.

---

# Usage

---

## 1. Run VLMEvalKit and export known columns

```bash
python autoverse.py \
    --run \
    --target split Overall AR CP \
    -- \
    --model qwen3.5-35b-a3b \
    --base-url https://qianfan.baidubce.com/v2 \
    --key "$QIANFAN_KEY" \
    --data MMBench_V11_MINI \
    --mode all \
    --work-dir ./outputs/qwen_demo
```

Everything after `--` is passed directly to the original `run.py`.

---

## 2. Run evaluation then choose columns interactively

```bash
python autoverse.py \
    --run \
    --interactive \
    -- \
    --model qwen3.5-35b-a3b \
    --base-url https://qianfan.baidubce.com/v2 \
    --key "$QIANFAN_KEY" \
    --data MMBench_V11_MINI \
    --mode all \
    --work-dir ./outputs/qwen_demo
```

After evaluation finishes, AutoVerse lists all legal columns and waits for user selection.

---

## 3. Process an existing output directory

```bash
python autoverse.py \
    --input ./outputs/qwen_demo \
    --target split Overall AR CP
```

---

## 4. Analyze existing outputs interactively

```bash
python autoverse.py \
    --input ./outputs/qwen_demo \
    --interactive
```

---

## 5. Only inspect available files and columns

```bash
python autoverse.py \
    --input ./outputs/qwen_demo \
    --list-only
```

---

# Target Validation

When all requested columns exist:

```
Target validation passed:
split
Overall
AR
CP
```

AutoVerse exports the selected columns directly.

---

## Correction Mode

If some requested columns are unavailable:

Example:

```
--target split Overall ABC
```

AutoVerse enters correction mode:

```
Found:
split
Overall

Not Found:
ABC

Available Columns:
split
Overall
AR
CP
LR
RR
FP-S
FP-C
```

The user may choose to:

1. Export only the found columns.
2. Append additional legal columns.
3. Re-select all output columns.
4. Cancel.

---

# Output

The original VLMEvalKit output files are preserved.

AutoVerse generates an additional Excel file:

```
<original_filename>_selected.xlsx
```

Only the selected columns are included.

---

# Notes

- AutoVerse does **not** modify VLMEvalKit source code.
- AutoVerse does **not** change the original evaluation results.
- AutoVerse is intended as a lightweight post-processing tool for flexible result extraction.
- All evaluation logic remains inside the original VLMEvalKit pipeline.