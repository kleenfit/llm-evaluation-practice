"""ARB 四组 demo × qwen3.5-35b-a3b（每组前 15 题）。

    A Numerical   math_numerical[0:15]    Table 14 prompt, SymPy 数值判分
    B MC          law[0:15]               Table 13 prompt, 字母比对
    C Symbolic    math_symbolic[0:15]     Table 15 prompt, SymPy 等价 + manual_review
    D Proof-like  math_prooflike[0:15]    Table 16 prompt, 官方 rubric + LLM 打分

数据准备（先跑）：
    python tools/download_arb.py --subset math_numerical --out data/
    python tools/download_arb.py --subset law --out data/
    python tools/download_arb.py --subset math_symbolic --out data/
    python tools/download_arb.py --subset math_prooflike --out data/

启动：
    python run.py eval_arb_demo.py -w outputs/arb_demo4 --mode infer
    python run.py eval_arb_demo.py -w outputs/arb_demo4 --mode eval -r latest

环境变量：
    QIANFAN_QWEN_API_KEY      被测模型
    QIANFAN_JUDGE_API_KEY     D 组 rubric 打分用（可与上面同一个 key）

口径说明：
  - A/B 是确定性判分，可与论文 Figure 1 对照（图，无精确值）。
  - C 的 accuracy 是自动可判部分的**下界**；论文此组为人工判分（Table 2 有
    精确数值：gpt-4 在 Math Symbolic 18%）。manual_review_rate 高是预期内的。
  - D 的 accuracy = 平均 rubric 得分/10*100，不是判对率。rubric 是 GPT-4
    生成的（论文 Table 19 流程），非人工 gold；论文实测该流程与人工评分
    Pearson 相关 0.82。
"""

BATCH_SIZE = 8

from opencompass.datasets.arb import (ARBDataset,
                                      ARBMathNumericalEvaluator,
                                      ARBMultipleChoiceEvaluator,
                                      ARBSymbolicEvaluator,
                                      ARBProofEvaluator,
                                      arb_math_numerical_pred_postprocess,
                                      arb_math_numerical_ref_postprocess)
from opencompass.models import OpenAISDK
from opencompass.openicl.icl_inferencer import GenInferencer
from opencompass.openicl.icl_prompt_template import PromptTemplate
from opencompass.openicl.icl_retriever import ZeroRetriever

# ===========================================================================
# Prompt —— 论文附录 Table 13/14/15/16 原文
# ===========================================================================

ARB_SYSTEM = ('You are a top graduate student taking an open-ended qualifying '
              'exam. Your final answer should always be in the last line of '
              'your response, preceded by ANSWER:.')

# Table 14 —— Numerical
PROMPT_NUMERICAL = (
    'You are a top graduate student taking an open-ended qualifying exam. '
    'Below you will find a question requiring you to compute a numerical '
    'value.\n\n'
    'Question: {question}\n\n'
    'Now it is time to give your answer. Think carefully and go step by step. '
    'Make sure to justify all your work. Please simplify all expressions as '
    'much as possible and do not leave any variables in your final answer.\n\n'
    'Your final answer should NOT contain units and should be given at the end '
    'of your work and preceded by ANSWER:\n'
    'For example, if you think the answer is 2.4 meters, the last line of your '
    'answer should be ANSWER: 2.4.\n\n'
    'Solution:')

# Table 13 —— Multiple choice
PROMPT_MC = (
    'You are a top graduate student taking a qualifying exam. Below you will '
    'find a multiple choice question.\n\n'
    'Question: {question}\n\n'
    'Answer Choices: {choices}\n\n'
    'Now it is time to choose an answer. Think carefully and go step by step.\n'
    'Make sure to justify all your work. Your final answer should be one of '
    'A,B,C,D,... given at the end of your work and preceded by ANSWER:. For '
    'example, if you think the answer is B, the last line of your answer '
    'should be ANSWER: B\n\n'
    'Solution:')

# Table 15 —— Symbolic
PROMPT_SYMBOLIC = (
    'You are a top graduate student taking an open-ended qualifying exam. '
    'Below you will find a question requiring you to give a symbolic '
    'answer.\n\n'
    'Question: {question}\n\n'
    'Now it is time to give your answer. Think carefully and go step by step. '
    'Make sure to justify all your work.\n\n'
    'Your final answer should NOT contain units and should be given at the end '
    'of your work and preceded by ANSWER:\n'
    'For example, if you think the answer is x * y, the last line of your '
    'answer should be ANSWER: x * y\n\n'
    'Solution:')

# Table 16 —— Proof-like（无 ANSWER: 抽取，judge 看全文）
PROMPT_PROOF = (
    'You are a top graduate student taking an open-ended qualifying exam. '
    'Below you will find a question requiring you to prove the given '
    'statement.\n\n'
    'Question: {question}\n\n'
    'Now it is time to give your answer. Think carefully and go step by step. '
    'Make sure to justify all your work.\n\n'
    'Solution:')

# ===========================================================================
# D 组的 rubric 打分模型
# ===========================================================================
# deepseek-v4-flash：非被测模型，无自评嫌疑。
# concurrency=2：OC 对每个 dataset 起独立 eval 子进程，多个并行时打向
# 同一端点，并发要压低（429 教训，见 findings.md §4）。
JUDGE_CFG = dict(
    api_base='https://qianfan.baidubce.com/v2',
    path='deepseek-v4-flash',
    key_env='QIANFAN_JUDGE_API_KEY',
    temperature=0.0,
    max_tokens=4096,
    concurrency=2,
    retry=3,
    cache_path='./outputs/arb_proof_judge_cache.json',
)

# ---------------------------------------------------------------------------
# 注意：config 顶层只能放 dict/str/int 等可序列化字面量。
# OC 会把解析后的 config dump 回 .py 再读一遍 —— 模块对象、函数对象
# 都会被写成 <module ...> / <function ...>，直接 SyntaxError。
# 所以这里不用工厂函数，四个 dataset 全部展开写。
# ---------------------------------------------------------------------------

datasets = [
    # ---- A. Numerical (math_numerical [0:15]) ---------------------------
    dict(
        abbr='arb_demo_numerical',
        type=ARBDataset,
        path='data/arb_math_numerical.json',
        problem_type='Numerical',           # 导出含杂项，须过滤（69 -> 52）
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
            test_range='[0:15]',
        ),
        infer_cfg=dict(
            prompt_template=dict(
                type=PromptTemplate,
                template=dict(
                    begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                                prompt=ARB_SYSTEM)],
                    round=[
                        dict(role='HUMAN', prompt=PROMPT_NUMERICAL),
                        dict(role='BOT', prompt=''),
                    ],
                ),
            ),
            retriever=dict(type=ZeroRetriever),
            # 16384：4096 会截断长推理，把样本误判成"不守格式"并反转
            # 模型排名（findings.md §3）。四组同理。
            inferencer=dict(type=GenInferencer,
                            max_out_len=16384,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(
                type=ARBMathNumericalEvaluator,
                relative_tolerance=0.01,
                strip_units=False,
                report_lenient=False,
                llm_extract_cfg=None,       # 结论是关闭（findings.md §6）
            ),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- B. Multiple choice (law [0:15]) --------------------------------
    dict(
        abbr='arb_demo_law_mc',
        type=ARBDataset,
        path='data/arb_law.json',
        problem_type=None,                  # law 有 1 条合法题缺该字段，不过滤
        reader_cfg=dict(
            input_columns=['question', 'choices'],
            output_column='answer',
            test_range='[0:15]',
        ),
        infer_cfg=dict(
            prompt_template=dict(
                type=PromptTemplate,
                template=dict(
                    begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                                prompt=ARB_SYSTEM)],
                    round=[
                        dict(role='HUMAN', prompt=PROMPT_MC),
                        dict(role='BOT', prompt=''),
                    ],
                ),
            ),
            retriever=dict(type=ZeroRetriever),
            inferencer=dict(type=GenInferencer,
                            max_out_len=16384,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMultipleChoiceEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- C. Symbolic (math_symbolic [0:15]) -----------------------------
    dict(
        abbr='arb_demo_symbolic',
        type=ARBDataset,
        path='data/arb_math_symbolic.json',
        problem_type='Symbolic',            # 52 -> 34
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
            test_range='[0:15]',
        ),
        infer_cfg=dict(
            prompt_template=dict(
                type=PromptTemplate,
                template=dict(
                    begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                                prompt=ARB_SYSTEM)],
                    round=[
                        dict(role='HUMAN', prompt=PROMPT_SYMBOLIC),
                        dict(role='BOT', prompt=''),
                    ],
                ),
            ),
            retriever=dict(type=ZeroRetriever),
            inferencer=dict(type=GenInferencer,
                            max_out_len=16384,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBSymbolicEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- D. Proof-like (math_prooflike [0:15], 实际 19 条全量) ----------
    dict(
        abbr='arb_demo_prooflike',
        type=ARBDataset,
        path='data/arb_math_prooflike.json',
        problem_type='Proof-like',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
            test_range='[0:15]',
        ),
        infer_cfg=dict(
            prompt_template=dict(
                type=PromptTemplate,
                template=dict(
                    begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                                prompt=ARB_SYSTEM)],
                    round=[
                        dict(role='HUMAN', prompt=PROMPT_PROOF),
                        dict(role='BOT', prompt=''),
                    ],
                ),
            ),
            retriever=dict(type=ZeroRetriever),
            inferencer=dict(type=GenInferencer,
                            max_out_len=16384,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBProofEvaluator, judge_cfg=JUDGE_CFG),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
]

# ===========================================================================
# Model —— 仅 qwen
# ===========================================================================

qianfan_meta_template = dict(
    round=[
        dict(role='HUMAN', api_role='HUMAN'),
        dict(role='BOT', api_role='BOT', generate=True),
    ],
    reserved_roles=[dict(role='SYSTEM', api_role='SYSTEM')],
)

models = [
    dict(
        type=OpenAISDK,
        abbr='qwen3.5-35b-a3b',
        path='qwen3.5-35b-a3b',
        key=__import__('os').environ.get('QIANFAN_QWEN_API_KEY', ''),
        openai_api_base='https://qianfan.baidubce.com/v2',
        meta_template=qianfan_meta_template,
        max_seq_len=32768,
        max_out_len=16384,
        batch_size=BATCH_SIZE,
        query_per_second=2,
        retry=5,
        temperature=0.0,
    ),
]

# ===========================================================================
# Summarizer
# ===========================================================================
# 各组语义不同：A/B 的 accuracy 是判对率；C 是自动可判部分的下界，
# 须与 manual_review_rate 一起看；D 是平均 rubric 得分百分比。

summarizer = dict(
    dataset_abbrs=[
        'arb_demo_numerical',
        ['arb_demo_numerical', 'no_delimiter_rate'],
        ['arb_demo_numerical', 'parse_fail_rate'],
        'arb_demo_law_mc',
        ['arb_demo_law_mc', 'no_delimiter_rate'],
        ['arb_demo_law_mc', 'parse_fail_rate'],
        'arb_demo_symbolic',
        ['arb_demo_symbolic', 'manual_review_rate'],
        ['arb_demo_symbolic', 'no_delimiter_rate'],
        'arb_demo_prooflike',
        ['arb_demo_prooflike', 'avg_rubric_score'],
        ['arb_demo_prooflike', 'judge_fail_rate'],
    ],
    summary_groups=[],
)

work_dir = './outputs/arb_demo4'
