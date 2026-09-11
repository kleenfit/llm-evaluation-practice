"""ARB 全量 × qianfan (deepseek-v3.2 / qwen3.5-35b-a3b)。

九个纯文本 subset，共 1049 题（含图的 68 题需要 VLM，不在本配置内）：

    A Numerical   math_numerical 52 + physics_numerical 80
    B MC          law 627 + mcat_science val 65 + test 76 + mcat_reading 78
    C Symbolic    math_symbolic 34 + physics_symbolic 18
    D Proof-like  math_prooflike 19

已知数据源缺陷：MCAT Reading 的 val/test 两个 API 路由返回同一批 78 条
（Table 1 报 165），本配置只拉 val，不相加。

数据准备：
    for s in math_numerical physics_numerical law math_symbolic \
             physics_symbolic math_prooflike mcat_reading_val \
             mcat_science_val mcat_science_test; do
      python tools/download_arb.py --subset $s --out data/
    done

启动（预计 4-5 小时，建议 caffeinate 挂机）：
    caffeinate -i bash -c '
      python run.py eval_arb_full.py -w outputs/arb_full9 --mode infer &&
      python run.py eval_arb_full.py -w outputs/arb_full9 --mode eval -r latest
    ' 2>&1 | tee outputs/arb_full9.log

环境变量：QIANFAN_DEEPSEEK_API_KEY / QIANFAN_QWEN_API_KEY / QIANFAN_JUDGE_API_KEY

口径提醒：C 组 accuracy 是自动可判部分的下界（manual_review 单独报告）；
D 组 accuracy = 平均 rubric 得分/10*100。config 顶层只放可序列化字面量
（OC 会 dump 回 .py 重解析，函数/模块对象会炸，已踩三次）。
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

JUDGE_CFG = dict(
    api_base='https://qianfan.baidubce.com/v2',
    path='deepseek-v4-flash',
    key_env='QIANFAN_JUDGE_API_KEY',
    temperature=0.0,
    max_tokens=16384,
    concurrency=2,               # 多 eval 子进程共打一个端点，429 教训
    retry=3,
    cache_path='./outputs/arb_proof_judge_cache.json',
)

datasets = [
    # ---- A. Numerical ----
    dict(
        abbr='arb_math_numerical',
        type=ARBDataset,
        path='data/arb_math_numerical.json',
        problem_type='Numerical',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
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
            inferencer=dict(type=GenInferencer,
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMathNumericalEvaluator, relative_tolerance=0.01, strip_units=False, report_lenient=False, llm_extract_cfg=None),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    dict(
        abbr='arb_physics_numerical',
        type=ARBDataset,
        path='data/arb_physics_numerical.json',
        problem_type='Numerical',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
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
            inferencer=dict(type=GenInferencer,
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMathNumericalEvaluator, relative_tolerance=0.01, strip_units=True, report_lenient=False, llm_extract_cfg=None),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- B. Multiple choice ----
    dict(
        abbr='arb_law_mc',
        type=ARBDataset,
        path='data/arb_law.json',
        problem_type=None,
        reader_cfg=dict(
            input_columns=['question', 'choices'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMultipleChoiceEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    dict(
        abbr='arb_mcat_science_val',
        type=ARBDataset,
        path='data/arb_mcat_science_val.json',
        problem_type=None,
        reader_cfg=dict(
            input_columns=['question', 'choices'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMultipleChoiceEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    dict(
        abbr='arb_mcat_science_test',
        type=ARBDataset,
        path='data/arb_mcat_science_test.json',
        problem_type=None,
        reader_cfg=dict(
            input_columns=['question', 'choices'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMultipleChoiceEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    dict(
        abbr='arb_mcat_reading',
        type=ARBDataset,
        path='data/arb_mcat_reading_val.json',
        problem_type=None,
        reader_cfg=dict(
            input_columns=['question', 'choices'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBMultipleChoiceEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- C. Symbolic ----
    dict(
        abbr='arb_math_symbolic',
        type=ARBDataset,
        path='data/arb_math_symbolic.json',
        problem_type='Symbolic',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBSymbolicEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    dict(
        abbr='arb_physics_symbolic',
        type=ARBDataset,
        path='data/arb_physics_symbolic.json',
        problem_type='Symbolic',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBSymbolicEvaluator),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
    # ---- D. Proof-like ----
    dict(
        abbr='arb_math_prooflike',
        type=ARBDataset,
        path='data/arb_math_prooflike.json',
        problem_type='Proof-like',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
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
                            max_out_len=24576,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(type=ARBProofEvaluator, judge_cfg=JUDGE_CFG),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    ),
]

qianfan_meta_template = dict(
    round=[
        dict(role='HUMAN', api_role='HUMAN'),
        dict(role='BOT', api_role='BOT', generate=True),
    ],
    reserved_roles=[dict(role='SYSTEM', api_role='SYSTEM')],
)

_COMMON = dict(
    type=OpenAISDK,
    openai_api_base='https://qianfan.baidubce.com/v2',
    meta_template=qianfan_meta_template,
    max_seq_len=32768,
    max_out_len=24576,
    batch_size=BATCH_SIZE,
    query_per_second=2,
    retry=5,
    temperature=0.0,
)

models = [
    dict(
        **_COMMON,
        abbr='deepseek-v3.2',
        path='deepseek-v3.2',
        key=__import__('os').environ.get('QIANFAN_DEEPSEEK_API_KEY', ''),
    ),
    dict(
        **_COMMON,
        abbr='qwen3.5-35b-a3b',
        path='qwen3.5-35b-a3b',
        key=__import__('os').environ.get('QIANFAN_QWEN_API_KEY', ''),
    ),
]

summarizer = dict(
    dataset_abbrs=[
        'arb_math_numerical',
        ['arb_math_numerical', 'no_delimiter_rate'],
        ['arb_math_numerical', 'parse_fail_rate'],
        'arb_physics_numerical',
        ['arb_physics_numerical', 'no_delimiter_rate'],
        ['arb_physics_numerical', 'parse_fail_rate'],
        'arb_law_mc',
        ['arb_law_mc', 'parse_fail_rate'],
        'arb_mcat_science_val',
        'arb_mcat_science_test',
        'arb_mcat_reading',
        'arb_math_symbolic',
        ['arb_math_symbolic', 'manual_review_rate'],
        'arb_physics_symbolic',
        ['arb_physics_symbolic', 'manual_review_rate'],
        'arb_math_prooflike',
        ['arb_math_prooflike', 'avg_rubric_score'],
        ['arb_math_prooflike', 'judge_fail_rate'],
    ],
    summary_groups=[],
)

work_dir = './outputs/arb_full9'