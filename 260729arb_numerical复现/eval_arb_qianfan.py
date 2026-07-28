"""ARB Math Numerical × 千帆 (deepseek-v3.2 / qwen3.5-35b-a3b)。

dataset 定义内联在本文件，不走 read_base()、也不跨文件 import ——
本地 mmengine 的 lazy import 在这个目录结构下解析异常，绕开即可，功能等价。
装在 OC 里的 opencompass/configs/datasets/arb/arb_math_numerical_gen.py
留着不用删，等哪天 read_base() 能用了可以切回去。

    python run.py eval_arb_qianfan.py -w outputs/arb_demo --dry-run
    python run.py eval_arb_qianfan.py -w outputs/arb_demo --mode infer
    python run.py eval_arb_qianfan.py -w outputs/arb_demo --mode eval -r latest

需要的环境变量:
    QIANFAN_DEEPSEEK_API_KEY    被测模型
    QIANFAN_QWEN_API_KEY        被测模型
    QIANFAN_JUDGE_API_KEY       LLM 抽取器（可指向上面任一个 key）
"""

from opencompass.datasets.arb import (ARBMathNumericalDataset,
                                      ARBMathNumericalEvaluator,
                                      arb_math_numerical_pred_postprocess,
                                      arb_math_numerical_ref_postprocess)
from opencompass.models import OpenAISDK
from opencompass.openicl.icl_inferencer import GenInferencer
from opencompass.openicl.icl_prompt_template import PromptTemplate
from opencompass.openicl.icl_retriever import ZeroRetriever

# 并发度：DataLoader 批大小和 API 线程池 max_workers 必须一起设，
# 实际并发取两者较小值。只改一边等于没改。
# 注意：这里只能放 int/str 这类能被 dump 回 .py 的值。
# 不要在模块顶层 import 任何东西（比如 import os）——
# OC 会把 config dump 成 .py 再重新解析，模块对象会被写成
# os=<module 'os' from '...'>，解析时直接 SyntaxError。
BATCH_SIZE = 8

# ===========================================================================
# Dataset —— prompt 为论文附录 Table 14 原文
# ===========================================================================

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

# ---------------------------------------------------------------------------
# LLM 抽取器
# ---------------------------------------------------------------------------
# 只负责从完整 CoT 里把最终数值捞出来；判分仍是 |pred-gt|/gt < 0.01 的
# 确定性数值比较，accuracy 一分不受影响。
#
# 判分模型刻意选了和两个被测模型都不同的型号 —— 用 deepseek-v3.2 抽自己的
# 答案有自偏风险。v3.1 和 v3.2 仍是同一家族，只算部分缓解，
# 真要干净就换非 deepseek 系的模型。
#
# max_tokens 给 1024 而不是默认的 64：如果判分模型带 thinking，
# 思考 token 会先把额度吃光，content 返回空 -> 抽取结果全是 None。
LLM_EXTRACT_CFG = dict(
    api_base='https://qianfan.baidubce.com/v2',
    path='deepseek-v4-flash',   # v3.1-250821 / v4 在本账号 401 invalid_model
    key_env='QIANFAN_JUDGE_API_KEY',
    temperature=0.0,
    max_tokens=1024,
    # 2 而不是 8：OC 把两个模型的 eval 任务放在独立子进程里并行跑，
    # 每个进程各开 concurrency 个线程打同一个判分端点，会撞千帆 RPM 限流(429)。
    # 详见 findings.md §4。
    concurrency=2,
    retry=3,
    # 按输入文本 hash 缓存，重跑 --mode eval 不重复计费，
    # 也让抽取这一步在复跑之间完全确定 —— 对方差测量很关键。
    cache_path='./outputs/arb_extract_cache.json',
)

datasets = [
    dict(
        abbr='arb_math_numerical',
        type=ARBMathNumericalDataset,
        path='data/arb_math_numerical.json',
        reader_cfg=dict(
            input_columns=['question'],
            output_column='answer',
            # 第一次先跑 5 条打通链路，通了再注释掉这行上全量 52 题
            #test_range='[0:5]',
        ),
        infer_cfg=dict(
            prompt_template=dict(
                type=PromptTemplate,
                template=dict(
                    begin=[dict(role='SYSTEM', fallback_role='HUMAN',
                                prompt=ARB_SYSTEM)],
                    round=[
                        dict(role='HUMAN', prompt=ARB_NUMERICAL_USER),
                        dict(role='BOT', prompt=''),
                    ],
                ),
            ),
            retriever=dict(type=ZeroRetriever),
            # max_out_len 以这里为准，会覆盖 model dict 里的同名字段；
            # batch_size 缺省是 1，不写死线程池再大也是串行。
            # 16384 而不是 4096：4096 会把 27% 的 qwen 输出在写出 ANSWER:
            # 之前截断，被误判成"不遵守格式"，并直接反转两个模型的排名。
            # 这是本项目最重要的发现，详见 findings.md §3。
            inferencer=dict(type=GenInferencer,
                            max_out_len=16384,
                            batch_size=BATCH_SIZE),
        ),
        eval_cfg=dict(
            evaluator=dict(
                type=ARBMathNumericalEvaluator,
                relative_tolerance=0.01,
                strip_units=False,
                # 正则兜底那套在 52 题上一条都没捞回来，关掉
                report_lenient=False,
                # 保持开启：docs/results/ 里那三轮 CSV 就是这个配置跑出来的。
                # 但结论是它应当关闭 —— 截断修复后净收益为 0 且增加方差，
                # 详见 findings.md §6。改成 llm_extract_cfg=None 即可关闭。
                llm_extract_cfg=LLM_EXTRACT_CFG,
            ),
            pred_postprocessor=dict(type=arb_math_numerical_pred_postprocess),
            dataset_postprocessor=dict(type=arb_math_numerical_ref_postprocess),
        ),
    )
]

# ===========================================================================
# Models —— 千帆 OpenAI 兼容端点
# ===========================================================================

# 论文把指令放在 system prompt，必须声明 SYSTEM 角色，
# 否则 prompt_template 的 begin 段会被丢掉。
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
    max_out_len=16384,       # 实际以 inferencer 的值为准，这里保持一致避免误导
    batch_size=BATCH_SIZE,   # → ThreadPoolExecutor(max_workers=8)
    query_per_second=2,      # 令牌桶，限的是发起速率不是在途数量
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

# ===========================================================================
# Summarizer —— 把自查指标一并提进 summary 表
# ===========================================================================

summarizer = dict(
    dataset_abbrs=[
        'arb_math_numerical',
        ['arb_math_numerical', 'accuracy_llm'],
        ['arb_math_numerical', 'llm_gap'],
        ['arb_math_numerical', 'llm_disagree_rate'],
        ['arb_math_numerical', 'llm_extract_fail_rate'],
        ['arb_math_numerical', 'no_delimiter_rate'],
        ['arb_math_numerical', 'parse_fail_rate'],
        ['arb_math_numerical', 'ref_parse_fail'],
    ],
    summary_groups=[],
)

work_dir = './outputs/arb'