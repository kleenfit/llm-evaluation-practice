"""ARB Math Numerical dataset config。

prompt 照论文附录 Table 14（含 system prompt）。改动 prompt 会让分数失去
与论文的可比性 —— 要改先跑 `--dry-run` 确认渲染结果，并在报告里注明。
"""

from opencompass.datasets.arb import (ARBMathNumericalDataset,
                                      ARBMathNumericalEvaluator,
                                      arb_math_numerical_pred_postprocess,
                                      arb_math_numerical_ref_postprocess)
from opencompass.openicl.icl_inferencer import GenInferencer
from opencompass.openicl.icl_prompt_template import PromptTemplate
from opencompass.openicl.icl_retriever import ZeroRetriever

# --- 论文 Table 14 ---------------------------------------------------------
ARB_SYSTEM = ('You are a top graduate student taking an open-ended qualifying '
              'exam. Your final answer should always be in the last line of '
              'your response, preceded by ANSWER:.')

ARB_NUMERICAL_USER = (
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

arb_math_numerical_reader_cfg = dict(
    input_columns=['question'],
    output_column='answer',
    # 调试期解开，先跑 5 条打通链路
    # test_range='[0:5]',
)

arb_math_numerical_infer_cfg = dict(
    prompt_template=dict(
        type=PromptTemplate,
        template=dict(
            # 论文对 chat model 把指令放 system prompt；非 chat 模型
            # fallback_role 会退回 HUMAN，与论文说明一致
            begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                        prompt=ARB_SYSTEM)],
            round=[
                dict(role='HUMAN', prompt=ARB_NUMERICAL_USER),
                dict(role='BOT', prompt=''),
            ],
        ),
    ),
    retriever=dict(type=ZeroRetriever),
    inferencer=dict(type=GenInferencer, max_out_len=4096),
)

arb_math_numerical_eval_cfg = dict(
    evaluator=dict(
        type=ARBMathNumericalEvaluator,
        relative_tolerance=0.01,     # 论文，严格小于
        strip_units=False,           # math 答案是纯数；physics subset 要开
        report_lenient=True,         # 并行出一份兜底口径分数做对照
    ),
    pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
    dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
)

arb_math_numerical_datasets = [
    dict(
        abbr='arb_math_numerical',
        type=ARBMathNumericalDataset,
        path='data/arb_math_numerical.json',
        reader_cfg=arb_math_numerical_reader_cfg,
        infer_cfg=arb_math_numerical_infer_cfg,
        eval_cfg=arb_math_numerical_eval_cfg,
    )
]
