"""ARB (arXiv 2307.13692) Math Numerical 的 OpenCompass 适配。

评分规则严格照论文第 4 节 "Numerical":
  1. 抽取 `ANSWER:` 之后的文本；找不到分隔符 -> 判错
  2. (可选) 正则剥单位
  3. SymPy 解析；解析失败 -> 判错
  4. |pred - gt| / gt < 0.01 判对

与旧版的关键差异
----------------
旧版用 "从字符串里找第一个数字 token" 提数，会把 LaTeX 闭式表达式静默截断:
    \\sqrt{2}                -> 2.0
    2^{10}                   -> 2.0
    \\frac{\\pi}{2\\sqrt{2}}... -> 2.0
从而产生**假阳性**(两个无关的值判成相等)。本版改为 LaTeX 归一化 + SymPy 求值,
解析不出来就判错，绝不退化到"抓第一个数字"。

strict / lenient 双轨
--------------------
strict=True (默认) 对齐论文: 只认 ANSWER: 分隔符。
同一次评测会**并行**算一份 lenient 分数(允许 \\boxed{} / Final Answer / 末行兜底),
两者的差值量化了"论文的严格解析损失了多少分",不需要跑两遍。

抽取的位置
----------
所有抽取都在 evaluator 里做，pred_postprocessor 只负责透传原始输出。
理由: lenient 按定义是 strict 的超集，必须和 strict 看到**同一份原文**才可能更宽松。
若在 postprocessor 里先抽一道，evaluator 拿到的已经是 strict 的结果，
lenient 只能在其之上再抽一次，结构上不可能更宽 —— 会出现 gap 为负。
"""

import hashlib
from collections import Counter
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from datasets import Dataset

from opencompass.openicl import BaseEvaluator
from opencompass.registry import (ICL_EVALUATORS, LOAD_DATASET,
                                  TEXT_POSTPROCESSORS)
from opencompass.utils import get_data_path

from .base import BaseDataset

# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@LOAD_DATASET.register_module()
class ARBMathNumericalDataset(BaseDataset):
    """Load ARB Math numerical questions from the official JSON export."""

    @staticmethod
    def load(path: str, **kwargs) -> Dataset:
        import json

        path = get_data_path(path)
        with open(path, 'r', encoding='utf-8') as file:
            raw_data = json.load(file)

        if isinstance(raw_data, dict):
            for key in ('data', 'items', 'questions', 'results'):
                if isinstance(raw_data.get(key), list):
                    raw_data = raw_data[key]
                    break

        if not isinstance(raw_data, list):
            raise TypeError(
                "ARB data must be a JSON list or contain a list under "
                "'data', 'items', 'questions', or 'results'.")

        rows = []
        for index, item in enumerate(raw_data):
            if not isinstance(item, dict):
                continue
            # 官方导出里混有 Problem Type 为空的杂项（69 条里有 17 条）。
            # 只保留 Numerical，条数与论文 Table 1 的 52 题一致。
            # 其余题型评分规则不同，混进来会同时污染 accuracy 和 parse_fail_rate。
            if str(item.get('Problem Type', '')).strip().lower() != 'numerical':
                continue
            question = str(item.get('Problem_Statement', '')).strip()
            answer = str(item.get('Final Answer', '')).strip()
            if not question or not answer:
                continue
            rows.append({
                'id': str(item.get('_id', index)),
                'question': question,
                'answer': answer,
                'topic': str(item.get('Topic', '')).strip(),
                'problem_type': str(item.get('Problem Type', '')).strip(),
            })

        if not rows:
            raise ValueError(
                "No valid ARB samples were loaded. Expected "
                "'Problem_Statement' and 'Final Answer' fields, and "
                "'Problem Type' == 'Numerical'.")
        return Dataset.from_list(rows)


# ---------------------------------------------------------------------------
# 答案抽取
# ---------------------------------------------------------------------------

_ANSWER_DELIM = re.compile(r'ANSWER\s*:', re.IGNORECASE)
_LENIENT_DELIM = re.compile(r'(?:final\s+answer|answer)\s*(?:is|:|=)',
                            re.IGNORECASE)


def _last_braced(text: str, command: str) -> Optional[str]:
    """取最后一个 \\command{...} 的花括号内容，支持嵌套。"""
    marker = '\\' + command
    start = text.rfind(marker)
    if start < 0:
        return None
    brace = text.find('{', start + len(marker))
    if brace < 0:
        return None
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[brace + 1:i]
    return None


def extract_strict(text: Any) -> Optional[str]:
    """论文规则：取 ANSWER: 之后的剩余文本。找不到分隔符返回 None（=判错）。"""
    if text is None:
        return None
    value = str(text)
    if not _ANSWER_DELIM.search(value):
        return None
    return _ANSWER_DELIM.split(value)[-1].strip()


def extract_lenient(text: Any) -> Optional[str]:
    """兜底抽取：\\boxed{} -> Final Answer/ANSWER -> 最后一个非空行。

    仅用于并行统计 lenient 分数，不参与论文口径的官方分。
    输入必须是**模型原始输出**；喂 strict 抽过的片段会让它退化成
    "在 strict 结果里再抽一次"，失去兜底意义。
    """
    if text is None:
        return None
    value = str(text).strip()
    if not value:
        return None

    boxed = _last_braced(value, 'boxed')
    if boxed is not None:
        return boxed.strip()

    if _LENIENT_DELIM.search(value):
        value = _LENIENT_DELIM.split(value)[-1].strip()

    lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
    return lines[-1] if lines else None


# ---------------------------------------------------------------------------
# LaTeX -> SymPy
# ---------------------------------------------------------------------------

# 论文: "we apply a series of regexes to remove units"。
# 但这只适用于 physics(答案常带单位)。math_numerical 的答案是纯数,
# 而 L/N/K/J/W/A/s 这些字母在数学表达式里可能是有意义的符号,
# 盲目剥离会制造新的错误 —— 所以本 subset 默认 strip_units=False。
_UNIT_RE = re.compile(
    r'(?<![A-Za-z])(m/s\^?2|m/s|km/h|kg|mol|cm|mm|km|nm|µm|um|'
    r'meters?|metres?|seconds?|minutes?|hours?|grams?|joules?|watts?|'
    r'volts?|amperes?|newtons?|kelvin|degrees?|radians?|liters?|litres?|'
    r'Hz|kHz|MHz|GHz|Pa|kPa|MPa|eV|keV|MeV|GeV|ohms?)(?![A-Za-z])',
    re.IGNORECASE)


def _expand_command(text: str, command: str, nargs: int, template: str) -> str:
    """把 \\command{a}{b} 展开成 template.format(a, b)，支持嵌套花括号。"""
    marker = '\\' + command
    out, i = [], 0
    while True:
        pos = text.find(marker, i)
        if pos < 0:
            out.append(text[i:])
            break
        # 避免 \sqrt 命中 \sqrtx 这类
        nxt = pos + len(marker)
        if nxt < len(text) and text[nxt].isalpha():
            out.append(text[i:nxt])
            i = nxt
            continue
        out.append(text[i:pos])
        args, j = [], nxt
        ok = True
        for _ in range(nargs):
            while j < len(text) and text[j] in ' \t':
                j += 1
            if j < len(text) and text[j] == '{':
                depth, k = 0, j
                while k < len(text):
                    if text[k] == '{':
                        depth += 1
                    elif text[k] == '}':
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                if k >= len(text):
                    ok = False
                    break
                args.append(text[j + 1:k])
                j = k + 1
            elif j < len(text) and (text[j].isdigit() or text[j].isalpha()):
                # \sqrt2 / \frac12 这类无花括号写法
                args.append(text[j])
                j += 1
            else:
                ok = False
                break
        if not ok:
            out.append(text[pos:nxt])
            i = nxt
            continue
        out.append(template.format(*args))
        i = j
    return ''.join(out)


_GREEK = {
    r'\pi': 'pi', r'\alpha': 'alpha', r'\beta': 'beta', r'\gamma': 'gamma',
    r'\theta': 'theta', r'\lambda': 'lamda', r'\mu': 'mu', r'\sigma': 'sigma',
    r'\omega': 'omega', r'\phi': 'phi', r'\rho': 'rho', r'\tau': 'tau',
    r'\varepsilon': 'epsilon', r'\epsilon': 'epsilon', r'\infty': 'oo',
}


_UNICODE_MATH = {
    'π': 'pi', 'θ': 'theta', 'α': 'alpha', 'β': 'beta', 'γ': 'gamma',
    'δ': 'delta', 'ε': 'epsilon', 'λ': 'lamda', 'μ': 'mu', 'σ': 'sigma',
    'ω': 'omega', 'φ': 'phi', 'ϕ': 'phi', 'ρ': 'rho', 'τ': 'tau',
    '∞': 'oo', '⋅': '*', '÷': '/', '≈': ' ', '≃': ' ', '∼': ' ',
    '⁄': '/', '−': '-',
}


def latex_to_expr(text: str) -> str:
    """把常见 LaTeX 写法归一化成 SymPy 可解析的字符串。"""
    s = text.strip()

    # 去装饰
    s = re.sub(r'\\(?:text|mathrm|mathbf|operatorname|displaystyle)\s*\{([^{}]*)\}',
               r'\1', s)
    s = re.sub(r'\\(?:left|right|,|;|!|:|quad|qquad)', ' ', s)
    s = s.replace('$', '').replace('\\\\', ' ')
    s = s.replace('−', '-').replace('–', '-').replace('×', '*').replace('·', '*')

    # 千分位：1{,}024 和 1,024 两种写法
    s = re.sub(r'(?<=\d)\{\s*,\s*\}(?=\d)', '', s)
    s = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', s)

    # 结构化命令
    s = _expand_command(s, 'dfrac', 2, '(({0})/({1}))')
    s = _expand_command(s, 'tfrac', 2, '(({0})/({1}))')
    s = _expand_command(s, 'frac', 2, '(({0})/({1}))')
    s = re.sub(r'\\sqrt\s*\[\s*([^\]]+)\s*\]\s*\{([^{}]*)\}',
               r'(\2)**(1/(\1))', s)
    s = _expand_command(s, 'sqrt', 1, 'sqrt({0})')

    # 函数名
    s = re.sub(r'\\ln\b', 'log', s)
    s = re.sub(r'\\log_\{?10\}?', 'log10', s)
    # SymPy 的反三角是 acos/asin/atan；'arccos' 会被隐式乘法拆成变量串
    s = re.sub(r'\\arc(sin|cos|tan)\b', r'a\1', s)
    s = re.sub(r'\barc(sin|cos|tan)\b', r'a\1', s)      # 模型裸写 arccos 的也救
    s = re.sub(r'\\(sin|cos|tan|sec|csc|cot|sinh|cosh|'
               r'tanh|log|exp|max|min)\b', r'\1', s)

    for k, v in _GREEK.items():
        s = re.sub(re.escape(k) + r'(?![A-Za-z])', v, s)

    # 下标：x_{0} -> x_0，必须在 '{'->'(' 之前做，否则变成 x*(0)
    s = re.sub(r'([A-Za-z])_\{\s*([A-Za-z0-9]+)\s*\}', r'\1_\2', s)
    # 绝对值：|a| -> Abs(a)（单层，不处理嵌套）
    s = re.sub(r'\|([^|]+)\|', r'Abs(\1)', s)

    # 模型经常直接吐 Unicode 数学符号而不是 LaTeX 命令（'2π' 而不是 '2\pi'）。
    # 这些字符 SymPy 不认，会被解析成未知符号 -> free_symbols 非空 -> parse_fail。
    for k, v in _UNICODE_MATH.items():
        s = s.replace(k, v)
    s = re.sub(r'√\s*\(([^()]*)\)', r'sqrt(\1)', s)
    s = re.sub(r'√\s*(\d+(?:\.\d+)?|[A-Za-z]\w*)', r'sqrt(\1)', s)

    s = s.replace('\\cdot', '*').replace('\\times', '*').replace('\\div', '/')
    s = s.replace('{', '(').replace('}', ')')
    s = re.sub(r'\\[A-Za-z]+', ' ', s)          # 残留未知命令
    s = s.replace('\\', '')

    # 裸 e 是欧拉数，不是未知变量。SymPy 里欧拉数写作大写 E，
    # 小写 e 会被解析成 Symbol('e')，导致 free_symbols 非空而被 to_number 拒绝
    # —— 这是 parse_fail 的主要来源（52 题里两个模型合计 8 条）。
    # 前后不接字母/数字，避开 exp、theta 和 1.6e-19 这类。
    # 注意: 仅对 math_numerical 成立。physics subset 里 e 常指基本电荷,
    # 那边必须关掉这条，否则会把含未知量的答案错误求值成数，制造假阳性。
    s = re.sub(r'(?<![A-Za-z0-9_.])e(?![A-Za-z0-9_])', 'E', s)
    return s.strip()


def to_number(text: Any, strip_units: bool = False) -> Optional[float]:
    """解析成 float。解析不出来返回 None —— 调用方必须把 None 当判错处理，
    绝不允许退化成 '抓第一个数字' 或字符串比较。"""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    from sympy import Float, Integer, Rational
    from sympy.parsing.sympy_parser import (convert_xor,
                                            implicit_multiplication_application,
                                            parse_expr, standard_transformations)

    transformations = (standard_transformations +
                       (implicit_multiplication_application, convert_xor))

    candidates: List[str] = []
    body = raw
    if strip_units:
        body = _UNIT_RE.sub(' ', body)
    candidates.append(body)
    # 剩余文本跨多行时，再试首个非空行（解析更稳，不改变分隔符规则）
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) > 1:
        candidates.append(lines[0])

    for cand in candidates:
        # 模型输出是 Markdown 不是纯 LaTeX，答案常被包在加粗/行内代码里
        # （**ANSWER: 1** -> 抽出 ' 1**'）。残留的 * 会被 SymPy 当成乘/幂运算符，
        # `1**` 缺指数直接解析失败。只剥首尾，表达式内部的运算符不受影响。
        expr_str = latex_to_expr(cand).strip('*` ').rstrip('.;,: ')
        expr_str = re.sub(r'\s+', ' ', expr_str).strip()
        if not expr_str:
            continue
        try:
            expr = parse_expr(expr_str, transformations=transformations,
                              evaluate=True)
        except Exception:                                   # noqa: BLE001
            continue
        try:
            if expr.free_symbols:      # 还有自由变量 -> 不是数值答案
                continue
            value = float(expr.evalf())
        except Exception:                                   # noqa: BLE001
            continue
        if math.isnan(value):
            continue
        return value
    return None


# ---------------------------------------------------------------------------
# LLM 辅助抽取
# ---------------------------------------------------------------------------

# 设计取舍：只用 LLM 做"抽取"，判分仍然是 |pred-gt|/gt < tol 的确定性数值比较。
#
# 理由：Math Numerical 的判分本身是两个浮点数比大小，确定性、可审计、零成本，
# 换成 LLM 判分是纯亏损（论文 Table 8 实测 GPT-3.5 判符号等价假阴性极多，
# 准确率只有 0.76，会系统性低估）。真正脆的是从几千字 CoT 里把答案捞出来
# 这一层 —— no_delimiter 和 parse_fail 全部出在这里。
#
# 如果确实要做完整的 LLM 判分，把 _EXTRACT_USER 换成打分 prompt、
# 在 score() 里跳过 to_number 即可，但那样分数不再可复现。

_EXTRACT_SYSTEM = (
    'You extract final answers from written solutions to mathematics '
    'problems. You output only the answer itself, never any explanation.')

_EXTRACT_USER = (
    "Below is a student's full solution to a problem that asks for a single "
    'numerical value.\n\n'
    'Output ONLY the final numerical answer the student committed to, written '
    'as a plain-text mathematical expression that Python\'s SymPy can parse.\n'
    'Use pi for pi, E for Euler\'s number, sqrt(x) for square roots, '
    'log(x) for natural log. Do not output units, LaTeX delimiters, '
    'markdown, or any surrounding text.\n'
    'Examples of valid output: 0.487 | pi/2 | sqrt(2) | (E-3)/2 | 3*log(2)\n\n'
    'If the student never commits to a final numerical value, output exactly '
    'NONE.\n\n'
    'Solution:\n{solution}\n\n'
    'Final numerical answer:')


class LLMAnswerExtractor:
    """用一个外部 API 模型把最终数值答案从完整解答里抽出来。

    走 OpenAI 兼容端点，key 从环境变量读（和被测模型同样的方式）。
    结果按输入文本的 hash 落盘缓存，重跑 --mode eval 不会重复计费。

    Args:
        api_base: OpenAI 兼容端点，例如 https://qianfan.baidubce.com/v2
        path: 模型名
        key_env: 存放 API key 的环境变量名
        temperature: 固定 0，抽取任务不需要多样性
        max_tokens: 只输出一个表达式，给小一点防止它开始解释
        max_input_chars: 送进抽取器的最大字符数，None = 不截断（默认）。
            设成具体数值会只取尾部。**慎用** —— 这等于给抽取器蒙上一半眼睛，
            而且和 infer 阶段的 max_out_len 完全脱钩：max_out_len 一调大，
            这里就悄悄开始丢内容。真截断时会计数并打印警告，不会静默。
        retry / concurrency: 失败重试次数、并发线程数
        cache_path: 缓存文件；设为 None 关闭缓存
    """

    def __init__(self,
                 api_base: str,
                 path: str,
                 key_env: str = 'ARB_JUDGE_API_KEY',
                 temperature: float = 0.0,
                 max_tokens: int = 4096,
                 max_input_chars: Optional[int] = None,
                 retry: int = 3,
                 concurrency: int = 8,
                 cache_path: Optional[str] = './outputs/arb_extract_cache.json'):
        self.api_base = api_base
        self.path = path
        self.key_env = key_env
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_input_chars = max_input_chars
        self.retry = retry
        self.concurrency = concurrency
        self.cache_path = cache_path
        self._cache = self._load_cache()
        self._errors: List[str] = []
        self.n_truncated = 0

    # -- 缓存 ---------------------------------------------------------------

    def _load_cache(self) -> Dict[str, str]:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:                                   # noqa: BLE001
            return {}

    def _save_cache(self) -> None:
        if not self.cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self.cache_path) or '.', exist_ok=True)
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(self._cache, f, ensure_ascii=False)
        except Exception:                                   # noqa: BLE001
            pass

    def _key(self, text: str) -> str:
        raw = f'{self.path}\x00{text}'.encode('utf-8')
        return hashlib.sha1(raw).hexdigest()

    # -- 调用 ---------------------------------------------------------------

    def _client(self):
        from openai import OpenAI
        api_key = os.environ.get(self.key_env, '')
        if not api_key:
            raise RuntimeError(
                f'环境变量 {self.key_env} 为空，LLM 抽取无法工作。'
                f'export {self.key_env}=... 后重跑。')
        return OpenAI(api_key=api_key, base_url=self.api_base)

    def _one(self, client, text: str):
        """抽一条。

        返回 (ok, value):
            (True, '0.487')  抽到了
            (True, None)     模型明确说 NONE —— 这是有效结论，可以缓存
            (False, None)    API 调用失败 —— **不缓存**，下次还要重试

        区分这两种 None 很重要：早期版本把失败也缓存成空串，
        导致一次网络抖动之后每次重跑都直接命中缓存返回 None，
        表现为 llm_extract_fail_rate 永远 100% 且再也发不出请求。
        """
        body = text or ''
        if self.max_input_chars and len(body) > self.max_input_chars:
            self.n_truncated += 1
            body = body[-self.max_input_chars:]
        if not body.strip():
            return True, None
        for attempt in range(self.retry):
            try:
                resp = client.chat.completions.create(
                    model=self.path,
                    messages=[
                        {'role': 'system', 'content': _EXTRACT_SYSTEM},
                        {'role': 'user',
                         'content': _EXTRACT_USER.format(solution=body)},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                msg = resp.choices[0].message
                out = (msg.content or '').strip()
                if not out:
                    # content 为空 = 失败，**不是**"模型说没有答案"。
                    # 带 thinking 的模型在长输入上会把 max_tokens 全烧在
                    # 思考里，一个字都吐不出来。早期版本把这种情况当成有效
                    # 结论缓存下来，导致调大 max_tokens 后重跑直接命中缓存、
                    # 永远修不好 —— 所以这里必须返回 False。
                    reasoning = (getattr(msg, 'reasoning_content', None)
                                 or getattr(msg, 'reasoning', None))
                    self._note_error(
                        'content 为空 (finish_reason=%s%s)'
                        % (resp.choices[0].finish_reason,
                           '，有 reasoning_content，八成是 max_tokens 不够'
                           if reasoning else ''))
                    return False, None
                # 模型偶尔会加反引号或前缀，剥一层
                out = out.strip('`').strip()
                out = re.sub(r'^(?:answer|final answer)\s*[:=]\s*', '', out,
                             flags=re.IGNORECASE).strip()
                if not out or out.upper() == 'NONE':
                    return True, None
                return out and (True, out) or (True, None)
            except Exception as exc:                        # noqa: BLE001
                self._note_error('%s: %s' % (type(exc).__name__, exc))
                if attempt == self.retry - 1:
                    return False, None
                time.sleep(1.0 * (attempt + 1))
        return False, None

    def _note_error(self, msg: str) -> None:
        """只留前几条，避免 104 条一样的报错刷屏。"""
        if len(self._errors) < 3:
            self._errors.append(msg)

    def extract_many(self, texts: List[str]) -> List[Optional[str]]:
        """批量抽取，顺序与输入一致。命中缓存的不发请求。"""
        results: List[Optional[str]] = [None] * len(texts)
        todo = []
        for i, t in enumerate(texts):
            k = self._key(t or '')
            if k in self._cache:
                cached = self._cache[k]
                results[i] = cached if cached else None
            else:
                todo.append(i)

        if todo:
            client = self._client()
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                out = list(pool.map(lambda i: self._one(client, texts[i] or ''),
                                    todo))
            n_fail = 0
            for i, (ok, val) in zip(todo, out):
                results[i] = val
                if ok:
                    # 只缓存有效结论（抽到了，或模型明确说没有）
                    self._cache[self._key(texts[i] or '')] = val or ''
                else:
                    n_fail += 1
            self._save_cache()

            if n_fail:
                print('[ARB] LLM 抽取: %d/%d 条调用失败（未写入缓存，下次会重试）'
                      % (n_fail, len(todo)))
            if self.n_truncated:
                print('[ARB] 警告: %d 条输入超过 max_input_chars=%s 被截断，'
                      '抽取器只看到尾部。抽取结果可能不完整。'
                      % (self.n_truncated, self.max_input_chars))
            if self._errors:
                print('[ARB] 前几条报错:')
                for e in self._errors:
                    print('       ', e[:300])

        return results


# ---------------------------------------------------------------------------
# Postprocessors
# ---------------------------------------------------------------------------


@TEXT_POSTPROCESSORS.register_module('arb_math_numerical_pred')
def arb_math_numerical_pred_postprocess(text: str) -> str:
    """透传模型原始输出，不做任何抽取。

    抽取全部下放到 evaluator —— 只有它同时看得到原文和 gold，
    才能让 strict / lenient 从同一份原文各抽一次。

    parse_fail_rate / no_delimiter_rate 这些自查信号没有丢，
    只是改由 evaluator 记录，语义不变：仍然**不做** fuzzy 兜底，
    论文正文给了 gpt-3.5-turbo 在 Law 上约 25% 解析失败、gpt-4 >99% 成功的
    对照，兜底会让失败率恒为 0，这个自查信号就没了。
    """
    return '' if text is None else str(text)


@TEXT_POSTPROCESSORS.register_module('arb_math_numerical_ref')
def arb_math_numerical_ref_postprocess(text: str) -> str:
    """gold 不含 ANSWER: 分隔符，原样返回，交给 SymPy 解析。"""
    return '' if text is None else str(text).strip()


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


@ICL_EVALUATORS.register_module()
class ARBMathNumericalEvaluator(BaseEvaluator):
    """论文口径: |pred - gt| / gt < 0.01，解析失败判错。

    Args:
        relative_tolerance: 论文为 0.01，判定用严格小于。
        zero_atol: gold 为 0 时相对误差无定义，改用绝对误差。论文未规定，
            属于本实现的补充，会单独计数。
        strip_units: 是否剥单位。math_numerical 默认关闭，physics 应打开。
        report_lenient: 并行统计一份正则兜底抽取的分数用于对照。
            实测在 52 题上一条都捞不回来（no_delimiter 样本的答案混在散文里），
            默认关闭；LLM 抽取上线后它基本没有存在价值。
        llm_extract_cfg: 传给 LLMAnswerExtractor 的 dict；None 表示关闭。
            开启后额外输出 accuracy_llm 等指标，**不影响 accuracy**。
    """

    def __init__(self,
                 relative_tolerance: float = 0.01,
                 zero_atol: float = 1e-9,
                 strip_units: bool = False,
                 report_lenient: bool = False,
                 llm_extract_cfg: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.relative_tolerance = relative_tolerance
        self.zero_atol = zero_atol
        self.strip_units = strip_units
        self.report_lenient = report_lenient
        self.llm_extract_cfg = llm_extract_cfg

    # 保持旧版 API，install.sh 的冒烟测试直接用它。
    # prediction 正常是 postprocessor 处理过的纯表达式；为避免误用，
    # 这里检测到 ANSWER: 会先补一次 strict 抽取。
    def is_equal(self, prediction: Any, reference: Any) -> bool:
        if prediction is not None and _ANSWER_DELIM.search(str(prediction)):
            prediction = extract_strict(prediction)
        pred = to_number(prediction, self.strip_units)
        ref = to_number(reference, self.strip_units)
        return self._close(pred, ref)

    @staticmethod
    def _strip_wrapper(text: str) -> str:
        r"""剥掉整体包装（** 加粗、\( \)、$、成对小括号），再按逗号切。
        不剥的话 '\( 0.2048, 9.62e-9 \)' 切完两个元素各带半只括号。"""
        t = str(text).strip().strip('*` ').strip()
        t = t.replace('\\(', '(').replace('\\)', ')').strip('$ ').strip()
        if t.startswith('(') and t.endswith(')'):
            # 只剥"包住整体"的那对括号，(a,b),(c,d) 这种不能剥
            depth = 0
            for i, ch in enumerate(t):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0 and i < len(t) - 1:
                        return t
            return t[1:-1]
        return t

    def _tuple_close(self, span: str, ref: str) -> Optional[bool]:
        """逗号分隔多值的逐元素比较。None = 元素数不符或解析失败。"""
        span = self._strip_wrapper(span)
        ref = self._strip_wrapper(ref)
        ps = [to_number(x, self.strip_units) for x in str(span).split(',')]
        rs = [to_number(x, self.strip_units) for x in str(ref).split(',')]
        if (len(ps) != len(rs) or any(v is None for v in ps)
                or any(v is None for v in rs)):
            return None
        return all(self._close(p, r) for p, r in zip(ps, rs))

    def _close(self, pred: Optional[float], ref: Optional[float]) -> bool:
        # 解析失败一律判错，绝不退化成字符串相等
        if pred is None or ref is None:
            return False
        if not (math.isfinite(pred) and math.isfinite(ref)):
            return pred == ref
        if abs(ref) <= self.zero_atol:
            return abs(pred) <= self.zero_atol
        return abs(pred - ref) / abs(ref) < self.relative_tolerance

    def score(self, predictions, references, origin_prompt=None,
              test_set=None) -> Dict[str, Any]:
        if len(predictions) != len(references):
            return {'error': f'length mismatch: {len(predictions)} != '
                             f'{len(references)}'}

        total = len(references)
        correct = no_delim = parse_fail = ref_fail = lenient_correct = 0
        llm_correct = llm_fail = llm_disagree = 0
        details: List[Dict[str, Any]] = []

        raw_outputs = None
        if test_set is not None and 'origin_prediction' in getattr(
                test_set, 'column_names', []):
            raw_outputs = test_set['origin_prediction']

        # LLM 抽取：一次性批量跑完，避免逐条串行。
        # 对**全部**样本抽取，不只是 strict 失败的那些 —— 这样两条口径
        # 在同一批样本上可比，strict 的假阳性也能暴露出来。
        llm_preds: List[Optional[str]] = [None] * total
        _n_trunc = 0
        if self.llm_extract_cfg:
            try:
                extractor = LLMAnswerExtractor(**self.llm_extract_cfg)
                llm_preds = extractor.extract_many(
                    [str(p) if p is not None else '' for p in predictions])
                _n_trunc = extractor.n_truncated
            except Exception as exc:                        # noqa: BLE001
                # 抽取器挂了不能拖垮正式分数，记一笔继续走
                print(f'[ARB] LLM 抽取失败，accuracy 不受影响: {exc}')
                self.llm_extract_cfg = None

        for i, (pred, ref) in enumerate(zip(predictions, references)):
            ref_num = to_number(ref, self.strip_units)
            # gold 单值解析失败先记嫌疑；若随后被元组路径成功处理
            # （多小问 gold 天然含逗号），撤销计数 —— 否则多值 gold
            # 每条都会把 ref_parse_fail 顶高，指标失真。
            ref_suspect = ref_num is None

            # strict：论文口径，只认 ANSWER: 分隔符。
            # pred 现在是模型原始输出，抽取在这里做。
            span = extract_strict(pred)
            if span is None:
                no_delim += 1
                pred_num, why = None, 'no_delimiter'
                ok = False
            else:
                pred_num = to_number(span, self.strip_units)
                if pred_num is not None:
                    why = ''
                    ok = self._close(pred_num, ref_num)
                elif ',' in span and ',' in str(ref):
                    # 多小问答案（'0.2048, 9.62e-9'）：双方逐元素容差比较。
                    # 单值路径完全不受影响。
                    ok, why = self._tuple_close(span, ref), ''
                    if ok is None:
                        parse_fail += 1
                        ok, why = False, 'parse_fail'
                    else:
                        ref_suspect = False   # gold 被元组路径正常消化
                elif ',' in span and ref_num is not None:
                    # pred 多值、gold 单值：模型把中间量一起写了，
                    # 最终答案按惯例在最后 -> 取末元素比对。
                    last = self._strip_wrapper(span).split(',')[-1]
                    last_num = to_number(last, self.strip_units)
                    if last_num is None:
                        parse_fail += 1
                        ok, why = False, 'parse_fail'
                    else:
                        ok, why = self._close(last_num, ref_num), ''
                elif ref_num is None:
                    # gold 本身不可解析（数据源把符号答案混进了 numerical
                    # 子集，如 gold='$$c$$'）。数值比较无从谈起，退化为
                    # 归一化字符串精确匹配 —— 只影响 ref_parse_fail 的
                    # 那几条，pred 可解析的正常路径不受任何影响。
                    na = re.sub(r'\s+', '', latex_to_expr(span))
                    nb = re.sub(r'\s+', '', latex_to_expr(str(ref)))
                    ok = bool(na) and na == nb
                    why = '' if ok else 'gold_unparseable'
                else:
                    parse_fail += 1
                    ok, why = False, 'parse_fail'
            if ref_suspect:
                ref_fail += 1
            if ok:
                correct += 1
            elif not why:
                why = 'wrong_value'

            row = {
                'idx': i,
                'pred': span,
                'answer': ref,
                'pred_number': pred_num,
                'answer_number': ref_num,
                'correct': ok,
                'reason': why,
            }

            if self.report_lenient:
                source = raw_outputs[i] if raw_outputs else pred
                lenient = extract_lenient(source)
                lenient_num = to_number(lenient, self.strip_units)
                # lenient 按定义是 strict 的超集：只加不减，gap 恒 >= 0。
                # 出现负值说明这里的单调性被破坏了。
                lenient_ok = ok or self._close(lenient_num, ref_num)
                lenient_correct += int(lenient_ok)
                row['lenient_pred'] = lenient
                row['lenient_correct'] = lenient_ok

            if self.llm_extract_cfg:
                llm_pred = llm_preds[i]
                llm_num = to_number(llm_pred, self.strip_units)
                if llm_num is None:
                    llm_fail += 1
                llm_ok = self._close(llm_num, ref_num)
                llm_correct += int(llm_ok)
                # 两条口径判定不一致的样本 —— 这才是值得人工看的那些
                if llm_ok != ok:
                    llm_disagree += 1
                row['llm_pred'] = llm_pred
                row['llm_number'] = llm_num
                row['llm_correct'] = llm_ok

            details.append(row)

        result = {
            'accuracy': 100.0 * correct / total if total else 0.0,
            'correct': correct,
            'total': total,
            # 以下三个是 pipeline 自查指标，不是模型能力指标
            'no_delimiter_rate': 100.0 * no_delim / total if total else 0.0,
            'parse_fail_rate': 100.0 * parse_fail / total if total else 0.0,
            'ref_parse_fail': ref_fail,
            'details': details,
        }
        if self.report_lenient:
            lenient_acc = 100.0 * lenient_correct / total if total else 0.0
            result['accuracy_lenient'] = lenient_acc
            result['strict_lenient_gap'] = lenient_acc - result['accuracy']
        if self.llm_extract_cfg:
            llm_acc = 100.0 * llm_correct / total if total else 0.0
            result['accuracy_llm'] = llm_acc
            # 可正可负，且负值不是 bug：LLM 抽错、或 strict 撞对了都会造成。
            # 要定位就去 details 里筛 llm_correct != correct 的样本。
            result['llm_gap'] = llm_acc - result['accuracy']
            result['llm_extract_fail_rate'] = (
                100.0 * llm_fail / total if total else 0.0)
            result['llm_disagree_rate'] = (
                100.0 * llm_disagree / total if total else 0.0)
            # 抽取器输入被截断的比例。非 0 说明 max_input_chars 在悄悄丢内容，
            # 此时 accuracy_llm 不可信 —— 和 infer 阶段 max_out_len 太小是
            # 同一类问题，只是发生在下一层。
            result['llm_input_truncated_rate'] = (
                100.0 * _n_trunc / total if total else 0.0)
        return result


# ===========================================================================
# ============ 以下为多 subset 集成扩展（A/B/C/D 四组） ======================
# ===========================================================================
#
# 组别对应论文：
#   A Numerical      -> ARBNumericalEvaluator（即上面的 ARBMathNumericalEvaluator，
#                       physics 用 strip_units=True）
#   B Multiple choice-> ARBMultipleChoiceEvaluator（Table 13 prompt）
#   C Symbolic       -> ARBSymbolicEvaluator（尽力自动判分 + manual_review 兜底；
#                       论文此组为人工判分，见 Table 2）
#   D Proof-like     -> ARBProofEvaluator（官方 rubric + LLM 按 Table 18 打分）


# ---------------------------------------------------------------------------
# 通用 Dataset —— 处理各 subset 的字段差异
# ---------------------------------------------------------------------------
#
# 实测的三个特例（tools/inspect_arb.py，2026-07-29）：
#   - math/physics 用 'Problem_Statement'，law/MCAT 用 'Problem Statement'（带空格）
#   - law 627 条里 1 条没有 'Problem Type' 字段；physics_symbolic_img 整个字段不存在
#     -> 过滤必须可关（problem_type=None 表示不过滤）
#   - MCAT Reading 的 val/test 两个路由返回同一批数据，只能取其一

_LETTERS = 'ABCDEFGHIJ'


@LOAD_DATASET.register_module()
class ARBDataset(BaseDataset):
    """通用 ARB loader。

    Args:
        path: 本地 JSON（tools/download_arb.py 的产物）。
        problem_type: 按 'Problem Type' 过滤；None = 不过滤。
            math/physics 的导出混有 Problem Type 为空的杂项，须过滤；
            law/MCAT 不要过滤（law 有 1 条合法题缺这个字段）。
        min_rows: 加载后少于该数则报错，防止过滤规则用错时静默返回空集。
    """

    @staticmethod
    def load(path: str, problem_type: Optional[str] = None,
             min_rows: int = 1, **kwargs) -> Dataset:
        import json as _json

        path = get_data_path(path)
        with open(path, 'r', encoding='utf-8') as f:
            raw = _json.load(f)
        if isinstance(raw, dict):
            for key in ('data', 'items', 'questions', 'results'):
                if isinstance(raw.get(key), list):
                    raw = raw[key]
                    break
        if not isinstance(raw, list):
            raise TypeError(f'{path}: 期望 JSON list，拿到 {type(raw)}')

        rows = []
        for idx, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            if problem_type is not None:
                ptype = str(item.get('Problem Type', '')).strip().lower()
                if ptype != problem_type.strip().lower():
                    continue
            # 两种题面字段名
            question = str(item.get('Problem_Statement')
                           or item.get('Problem Statement') or '').strip()
            answer = str(item.get('Final Answer', '')).strip()
            if not question:
                continue
            # Proof-like 的 Final Answer 为空是正常的（判的是过程）
            choices_raw = item.get('Answer Candidates')
            choices_text = ''
            if isinstance(choices_raw, list) and choices_raw:
                choices_text = '\n'.join(
                    f'{_LETTERS[i]}. {str(c).strip()}'
                    for i, c in enumerate(choices_raw[:len(_LETTERS)]))
            rows.append({
                'id': str(item.get('_id', idx)),
                'question': question,
                'answer': answer,
                'choices': choices_text,
                'rubric': str(item.get('rubric', '')).strip(),
                'solution': str(item.get('Solution', '')).strip(),
                'topic': str(item.get('Topic', '')).strip(),
            })

        if len(rows) < min_rows:
            raise ValueError(
                f'{path}: 过滤后仅 {len(rows)} 条（< {min_rows}）。'
                f'检查 problem_type={problem_type!r} 是否适用于该 subset —— '
                f'law/MCAT 应传 None，physics_symbolic_img 没有该字段。')
        return Dataset.from_list(rows)


# ---------------------------------------------------------------------------
# 公共判分基座 —— 三类失败分解，A/B/C/D 通用
# ---------------------------------------------------------------------------


class _ARBEvaluatorBase(BaseEvaluator):
    """所有 ARB evaluator 共用的骨架。

    统一产出 no_delimiter / parse_fail / wrong_value 三类互斥失败 + accuracy，
    使任何 subset 上都能区分"模型不行"和"harness 不行"。
    子类只实现 `_judge(span, ref, row_ctx) -> (ok, pred_repr, why)`：
        ok        : 判定结果
        pred_repr : 写进 details 的抽取结果（便于排查）
        why       : '' / 'parse_fail' / 其他子类自定义原因
    """

    def _judge(self, span, ref, row_ctx):                   # pragma: no cover
        raise NotImplementedError

    def score(self, predictions, references, origin_prompt=None,
              test_set=None) -> Dict[str, Any]:
        if len(predictions) != len(references):
            return {'error': f'length mismatch: {len(predictions)} != '
                             f'{len(references)}'}
        total = len(references)
        correct = no_delim = parse_fail = 0
        extra: Counter = Counter()
        details: List[Dict[str, Any]] = []

        for i, (pred, ref) in enumerate(zip(predictions, references)):
            raw = '' if pred is None else str(pred)
            row_ctx = {}
            if test_set is not None:
                try:
                    row_ctx = dict(test_set[i])
                except Exception:                           # noqa: BLE001
                    row_ctx = {}

            span = extract_strict(raw)
            if span is None:
                no_delim += 1
                ok, pred_repr, why = False, None, 'no_delimiter'
            else:
                ok, pred_repr, why = self._judge(span, ref, row_ctx)
                if why == 'parse_fail':
                    parse_fail += 1
                elif why and why not in ('', 'wrong_value'):
                    extra[why] += 1
            if ok:
                correct += 1
            elif not why:
                why = 'wrong_value'
            details.append({'idx': i, 'pred': pred_repr, 'answer': ref,
                            'correct': ok, 'reason': why})

        result = {
            'accuracy': 100.0 * correct / total if total else 0.0,
            'correct': correct,
            'total': total,
            'no_delimiter_rate': 100.0 * no_delim / total if total else 0.0,
            'parse_fail_rate': 100.0 * parse_fail / total if total else 0.0,
            'details': details,
        }
        for k, v in extra.items():
            result[f'{k}_rate'] = 100.0 * v / total if total else 0.0
        return result


# ---------------------------------------------------------------------------
# B. 选择题（law / MCAT）—— Table 13
# ---------------------------------------------------------------------------

_MC_LETTER = re.compile(
    r'^[\s*_`(\[]*(?:option\s+|choice\s+|answer\s+)?([A-J])[\s)\].:,*_`]*',
    re.IGNORECASE)


def extract_choice_letter(span: str) -> Optional[str]:
    """从 ANSWER: 之后的片段里抽选项字母。

    覆盖实测变体：'B' / '(B)' / 'B.' / '**B**' / 'option B' / 'B) because...'
    抽不出返回 None（= parse_fail）。
    """
    if not span:
        return None
    m = _MC_LETTER.match(span.strip())
    if not m:
        return None
    letter = m.group(1).upper()
    # 防误伤：span 若以普通单词开头（如 'Because...'）不应命中。
    # _MC_LETTER 已要求字母后是边界符或结尾，此处再排除后面直接跟字母的情况。
    rest = span.strip()[m.end():]
    if rest[:1].isalpha() and m.group(0).strip()[-1:].isalpha():
        return None
    return letter


@ICL_EVALUATORS.register_module()
class ARBMultipleChoiceEvaluator(_ARBEvaluatorBase):
    """字母比对。论文口径：>97% 可解析，gpt-3.5 在 Law 上约 25% 失败作对照。"""

    def _judge(self, span, ref, row_ctx):
        letter = extract_choice_letter(span)
        if letter is None:
            return False, span[:40], 'parse_fail'
        gold = str(ref).strip().upper()[:1]
        return letter == gold, letter, ''


# ---------------------------------------------------------------------------
# C. 符号题 —— 尽力自动判分；论文此组为人工判分（Table 2）
# ---------------------------------------------------------------------------
#
# 论文原话：SymPy 等价判定"error-prone and only works for the subset of
# symbolic responses in a function form"。本实现：
#   1) 双方都解析成 SymPy 表达式 -> simplify(a-b)==0，或数值抽样比较
#   2) 任一方解析失败 -> 计入 manual_review（不判对错，单独报告）
# accuracy 因而是**下界**；manual_review_rate 高说明该 subset 离不开人工。


def _try_parse_expr(text: str):
    from sympy.parsing.sympy_parser import (convert_xor,
                                            implicit_multiplication_application,
                                            parse_expr, standard_transformations)
    tf = standard_transformations + (implicit_multiplication_application,
                                     convert_xor)
    expr_str = latex_to_expr(str(text)).strip('*` ').rstrip('.;,: ')
    expr_str = re.sub(r'\s+', ' ', expr_str).strip()
    if not expr_str:
        return None
    try:
        expr = parse_expr(expr_str, transformations=tf, evaluate=True)
    except Exception:                                       # noqa: BLE001
        return None
    # parse_expr 对含逗号的输入（坐标 '(3, 4)'、多解 'x=1, x=2'）会返回
    # Python tuple 而非表达式对象，后续 .free_symbols 直接 AttributeError。
    # 非 Basic 一律视为解析失败 -> manual_review。
    from sympy import Basic
    if not isinstance(expr, Basic):
        return None
    return expr


def symbolic_equal(pred_text: str, gold_text: str,
                   n_samples: int = 6, tol: float = 1e-6) -> Optional[bool]:
    """None = 无法判定（manual review）；True/False = 判定结果。

    绝不抛异常：单条样本的任何意外都以 manual_review 收场，
    不允许炸掉整个 eval 任务（demo 首跑时 tuple 答案曾把 15 条全部陪葬）。
    """
    try:
        return _symbolic_equal_inner(pred_text, gold_text, n_samples, tol)
    except Exception:                                       # noqa: BLE001
        return None


def _first_line(text):
    """取首个非空行。模型答完常继续自言自语（'0, 1/4\\n\\nWait...'），
    整段解析不了时首行往往就是答案本体。"""
    if not text:
        return None
    for line in str(text).splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _strip_eq_prefix(text: str) -> str:
    """剥掉 'y(t) = ...' / '(a, b) = ...' 这类左值前缀，取等号右侧。

    仅当恰有一个 '=' 且左侧足够短（像变量声明而非方程）时触发，
    避免把 'x = y' 这种真正的方程答案剥坏。"""
    t = text.strip()
    if t.count('=') != 1:
        return t
    lhs, rhs = t.split('=', 1)
    lhs = lhs.strip()
    if 0 < len(lhs) <= 16 and not any(op in lhs for op in '+-*/^<>'):
        return rhs.strip()
    return t


def _parse_maybe_tuple(text: str):
    """返回 ('expr', Basic) / ('tuple', tuple[Basic]) / (None, None)。"""
    from sympy import Basic
    from sympy.parsing.sympy_parser import (convert_xor,
                                            implicit_multiplication_application,
                                            parse_expr, standard_transformations)
    tf = standard_transformations + (implicit_multiplication_application,
                                     convert_xor)
    expr_str = latex_to_expr(str(text)).strip('*` ').rstrip('.;,: ')
    expr_str = re.sub(r'\s+', ' ', expr_str).strip()
    if not expr_str:
        return None, None
    try:
        expr = parse_expr(expr_str, transformations=tf, evaluate=True)
    except Exception:                                       # noqa: BLE001
        return None, None
    if isinstance(expr, Basic):
        return 'expr', expr
    if isinstance(expr, tuple) and expr and all(
            isinstance(e, Basic) for e in expr):
        return 'tuple', expr
    return None, None


def _exprs_equal(a, b, n_samples, tol):
    from sympy import simplify
    import random
    fa, fb = a.free_symbols, b.free_symbols
    if fa != fb and len(fa) == 1 and len(fb) == 1:
        b = b.subs(list(fb)[0], list(fa)[0])
        fb = b.free_symbols
    try:
        if simplify(a - b) == 0:
            return True
    except Exception:                                       # noqa: BLE001
        pass
    if fa != fb and not (fa <= fb or fb <= fa):
        return None                    # 可能是置换等价，交人工
    all_syms = fa | fb
    rng = random.Random(0)
    try:
        for _ in range(n_samples):
            subs = {s: rng.uniform(0.3, 2.7) for s in all_syms}
            va = complex(a.evalf(subs=subs))
            vb = complex(b.evalf(subs=subs))
            if abs(va - vb) > tol * max(1.0, abs(vb)):
                return False
        return True
    except Exception:                                       # noqa: BLE001
        return None


def _symbolic_equal_inner(pred_text, gold_text, n_samples, tol):
    # 剥 'y(t)=' 类前缀；模型答完还自言自语时再试首行
    gold = _strip_eq_prefix(str(gold_text))
    pred_cands = [_strip_eq_prefix(str(pred_text))]
    first = _first_line(pred_text)
    if first and _strip_eq_prefix(first) not in pred_cands:
        pred_cands.append(_strip_eq_prefix(first))

    kg, g = _parse_maybe_tuple(gold)
    verdict_seen_false = False
    for cand in pred_cands:
        kp, p = _parse_maybe_tuple(cand)
        if kg == kp == 'expr':
            v = _exprs_equal(p, g, n_samples, tol)
        elif kg == kp == 'tuple':
            if len(p) != len(g):
                v = False
            else:
                sub = [_exprs_equal(x, y, n_samples, tol)
                       for x, y in zip(p, g)]
                v = (True if all(x is True for x in sub)
                     else False if any(x is False for x in sub) else None)
        else:
            v = None
        if v is True:
            return True
        if v is False:
            verdict_seen_false = True
    # 双方都解析不了，但归一化后逐字相同 -> 同一个答案（内积记号等场景）
    na = re.sub(r'\s+', '', latex_to_expr(str(pred_text)))
    nb = re.sub(r'\s+', '', latex_to_expr(gold))
    if na and na == nb:
        return True
    return False if verdict_seen_false else None


@ICL_EVALUATORS.register_module()
class ARBSymbolicEvaluator(_ARBEvaluatorBase):
    """accuracy 是自动可判部分的下界；manual_review_rate 单独报告。"""

    def _judge(self, span, ref, row_ctx):
        verdict = symbolic_equal(span, ref)
        if verdict is None:
            return False, span[:60], 'manual_review'
        return verdict, span[:60], ''


# ---------------------------------------------------------------------------
# D. 证明题 —— 官方 rubric + LLM 按论文 Table 18 打分
# ---------------------------------------------------------------------------
#
# 数据集自带 rubric（GPT-4 按论文 Table 19 流程生成，非人工 gold —— 论文
# 评估其覆盖度 Likert ~3.94，分值分配 ~4.06，"覆盖关键步骤但分值分配欠佳"）。
# 本 evaluator 忠实复刻论文第 5 节的自评流程；论文实测该流程与人工评分的
# Pearson 相关 0.82（proof-like），可用但非人工替代。

_PROOF_JUDGE_SYSTEM = ('You are a top professor grading an open-ended '
                       'qualifying exam.')

# 论文 Table 18 原文
_PROOF_JUDGE_USER = (
    'Problem Statement: {problem}\n\n'
    'Rubric: {rubric}\n\n'
    'Student Answer: {response}\n\n'
    'Now it is time to grade the student answer. Make sure to check each '
    'point of the rubric step by step. And make sure to print the total '
    'number of earned points at the end of your grading. For example, if '
    'the student earned 8 points, print Rubric Score: 8 points\n\n'
    'Rubric Evaluation:')

_SCORE_RE = re.compile(r'Rubric Score:\s*([0-9]+(?:\.[0-9]+)?)', re.IGNORECASE)
_SCORE_RE_FALLBACK = re.compile(
    r'\*{0,2}(?:Rubric|Total|Final)\s+Score\*{0,2}\s*[:：]?\s*\*{0,2}'
    r'([0-9]+(?:\.[0-9]+)?)\s*(?:/\s*10)?\s*points?',
    re.IGNORECASE)


@ICL_EVALUATORS.register_module()
class ARBProofEvaluator(BaseEvaluator):
    """LLM rubric 评分（0-10），accuracy = 平均得分/10*100。

    不走 _ARBEvaluatorBase：证明题没有 ANSWER: 抽取一说，失败分解不适用。
    judge_cfg 与 LLMAnswerExtractor 同构（api_base/path/key_env/...），
    缓存、失败不入缓存、错误可见等行为一致。
    """

    def __init__(self, judge_cfg: Dict[str, Any],
                 max_points: float = 10.0):
        super().__init__()
        self.judge_cfg = dict(judge_cfg)
        self.max_points = max_points

    def _call_judge(self, prompts: List[str]) -> List[Optional[str]]:
        cfg = self.judge_cfg
        client_holder = LLMAnswerExtractor(
            api_base=cfg['api_base'], path=cfg['path'],
            key_env=cfg.get('key_env', 'ARB_JUDGE_API_KEY'),
            temperature=cfg.get('temperature', 0.0),
            max_tokens=cfg.get('max_tokens', 4096),
            max_input_chars=cfg.get('max_input_chars'),
            retry=cfg.get('retry', 3),
            concurrency=cfg.get('concurrency', 2),
            cache_path=cfg.get('cache_path'))
        # 复用其缓存/并发/重试骨架，但换成打分 prompt：
        # 直接借 extract_many 不合适（prompt 不同），走同构的小循环。
        client = client_holder._client()
        results: List[Optional[str]] = [None] * len(prompts)
        todo = []
        for i, p in enumerate(prompts):
            k = client_holder._key('PROOF\x00' + p)
            if k in client_holder._cache:
                results[i] = client_holder._cache[k] or None
            else:
                todo.append(i)
        if todo:
            def one(i):
                for attempt in range(client_holder.retry):
                    try:
                        resp = client.chat.completions.create(
                            model=cfg['path'],
                            messages=[
                                {'role': 'system',
                                 'content': _PROOF_JUDGE_SYSTEM},
                                {'role': 'user', 'content': prompts[i]},
                            ],
                            temperature=client_holder.temperature,
                            max_tokens=client_holder.max_tokens)
                        out = (resp.choices[0].message.content or '').strip()
                        if out:
                            return True, out
                        client_holder._note_error('proof judge content 为空')
                        return False, None
                    except Exception as exc:                # noqa: BLE001
                        client_holder._note_error(
                            f'{type(exc).__name__}: {exc}')
                        if attempt == client_holder.retry - 1:
                            return False, None
                        time.sleep(1.0 * (attempt + 1))
                return False, None
            with ThreadPoolExecutor(
                    max_workers=client_holder.concurrency) as pool:
                out = list(pool.map(one, todo))
            for i, (ok, val) in zip(todo, out):
                results[i] = val
                if ok:
                    client_holder._cache[
                        client_holder._key('PROOF\x00' + prompts[i])] = val or ''
            client_holder._save_cache()
            n_fail = sum(1 for ok, _ in out if not ok)
            if n_fail:
                print(f'[ARB] proof judge: {n_fail}/{len(todo)} 条调用失败'
                      '（未入缓存，重跑会重试）')
            if client_holder._errors:
                print('[ARB] 前几条报错:')
                for e in client_holder._errors:
                    print('       ', e[:300])
        return results

    def score(self, predictions, references, origin_prompt=None,
              test_set=None) -> Dict[str, Any]:
        total = len(predictions)
        if test_set is None:
            return {'error': 'ARBProofEvaluator 需要 test_set 提供 '
                             'question/rubric 列'}
        prompts, missing_rubric = [], 0
        for i, pred in enumerate(predictions):
            row = dict(test_set[i])
            rubric = row.get('rubric', '')
            if not rubric:
                missing_rubric += 1
            prompts.append(_PROOF_JUDGE_USER.format(
                problem=row.get('question', ''),
                rubric=rubric or '(no rubric provided)',
                response='' if pred is None else str(pred)))

        outs = self._call_judge(prompts)

        scores, judge_fail = [], 0
        details = []
        for i, out in enumerate(outs):
            if out is None:
                judge_fail += 1
                details.append({'idx': i, 'rubric_score': None,
                                'reason': 'judge_fail'})
                continue
            m = _SCORE_RE.search(out) or _SCORE_RE_FALLBACK.search(out)
            if not m:
                judge_fail += 1
                details.append({'idx': i, 'rubric_score': None,
                                'reason': 'score_parse_fail',
                                'judge_tail': out[-200:]})
                continue
            pts = min(float(m.group(1)), self.max_points)
            scores.append(pts)
            details.append({'idx': i, 'rubric_score': pts, 'reason': ''})

        avg = sum(scores) / len(scores) if scores else 0.0
        return {
            # 与其他组同名，便于 summarizer 汇总；语义是平均 rubric 得分百分比
            'accuracy': 100.0 * avg / self.max_points,
            'avg_rubric_score': avg,
            'graded': len(scores),
            'total': total,
            'judge_fail_rate': 100.0 * judge_fail / total if total else 0.0,
            'missing_rubric': missing_rubric,
            'details': details,
        }