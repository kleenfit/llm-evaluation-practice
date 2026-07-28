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
    s = re.sub(r'\\(sin|cos|tan|sec|csc|cot|arcsin|arccos|arctan|sinh|cosh|'
               r'tanh|log|exp|max|min)\b', r'\1', s)

    for k, v in _GREEK.items():
        s = re.sub(re.escape(k) + r'(?![A-Za-z])', v, s)

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
            if ref_num is None:
                ref_fail += 1

            # strict：论文口径，只认 ANSWER: 分隔符。
            # pred 现在是模型原始输出，抽取在这里做。
            span = extract_strict(pred)
            if span is None:
                no_delim += 1
                pred_num, why = None, 'no_delimiter'
            else:
                pred_num = to_number(span, self.strip_units)
                if pred_num is None:
                    parse_fail += 1
                    why = 'parse_fail'
                else:
                    why = ''

            ok = self._close(pred_num, ref_num)
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
