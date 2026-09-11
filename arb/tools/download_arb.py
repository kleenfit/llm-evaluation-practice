"""从 ARB 官方 REST API 拉取数据集。

数据集不进版本库 —— 论文作者刻意只通过 API 分发、不放 GitHub/HuggingFace，
目的是降低被爬进训练语料的概率（论文第 3 节）。把它提交到公开仓库等于
亲手破坏这一点，所以这里只提交下载脚本。

注意这不是授权问题 —— 仓库是 MIT 协议，法律上可以再分发。
不提交纯粹是为了不破坏作者防污染的意图。

    python tools/download_arb.py
    python tools/download_arb.py --subset math_numerical --out data/

端点来自 TheDuckAI/arb 的 README。两个域名指向同一套服务，脚本会依次尝试。
这个项目 2023 年之后基本停止维护，端点随时可能失效 —— 失效时脚本会明确报错，
不会写出一个空文件让你对着排查。请务必保留一份本地备份。
"""

import argparse
import json
import pathlib
import sys
import urllib.error
import urllib.request

# 路径已对照官方 API 文档核实（端点根 https://.../api/ 即文档页）。
# 注意 base 带 /lib。
BASES = [
    'https://advanced-reasoning-benchmark.netlify.app/api/lib',
]

# subset 名 -> API 路径。已对照官方文档核实。
#
#   math      /math/{numerical|symbolic|prooflike}
#   law       /law/
#   physics   /physics/{numerical|symbolic}/{img|noimg}
#   mcatRead  /mcatReading/{val|test}
#   mcatSci   /mcatScience/{val|test}/{img|noimg}
#
# 任一路径后面接 /{id} 可取单题，例如
#   /math/numerical/64ade9c30b1afac21d212df7
SUBSET_PATHS = {
    'math_numerical': 'math/numerical',
    'math_symbolic': 'math/symbolic',
    'math_prooflike': 'math/prooflike',
    'physics_numerical': 'physics/numerical/noimg',
    'physics_numerical_img': 'physics/numerical/img',
    'physics_symbolic': 'physics/symbolic/noimg',
    'physics_symbolic_img': 'physics/symbolic/img',
    'law': 'law',
    'mcat_reading_val': 'mcatReading/val',
    'mcat_reading_test': 'mcatReading/test',
    'mcat_science_val': 'mcatScience/val/noimg',
    'mcat_science_val_img': 'mcatScience/val/img',
    'mcat_science_test': 'mcatScience/test/noimg',
    'mcat_science_test_img': 'mcatScience/test/img',
}

# 论文 Table 1 的题数，仅用于下载后粗查。
#
# 两点注意：
#  1. 官方导出**多于**论文题数 —— 混有 Problem Type 为空的杂项
#     （math_numerical 是 69 条里 52 条有效），loader 会按 Problem Type 过滤。
#     所以「多」是正常的，「少」才需要查。
#  2. MCAT 两类按 val/test 分割返回，而 Table 1 给的是合计，
#     单个 split 无法直接比对，故此处留空。
EXPECTED_COUNTS = {
    'math_numerical': 52,
    'math_symbolic': 34,
    'math_prooflike': 19,
    'physics_numerical': 80,
    'physics_numerical_img': 18,
    'physics_symbolic': 18,
    'physics_symbolic_img': 13,
    'law': 627,
}


def fetch(path: str, timeout: int = 30):
    errors = []
    for base in BASES:
        url = f'{base.rstrip("/")}/{path.lstrip("/")}'
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': 'arb-downloader/1.0'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp), url
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError) as exc:
            errors.append(f'  {url}\n    -> {type(exc).__name__}: {exc}')
    raise RuntimeError(
        'ARB 官方端点全部不可用：\n' + '\n'.join(errors) +
        '\n\n这个项目自 2023 年起基本停止维护，端点可能已永久下线。'
        '\n请改用本地备份，或去 https://github.com/TheDuckAI/arb 查看最新说明。')


def normalize(raw):
    """API 可能返回 list，也可能把 list 包在某个 key 下面。"""
    if isinstance(raw, dict):
        for key in ('data', 'items', 'questions', 'results'):
            if isinstance(raw.get(key), list):
                return raw[key]
    if isinstance(raw, list):
        return raw
    raise TypeError(f'预期是 list 或含 list 的 dict，实际拿到 {type(raw)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subset', default='math_numerical',
                    choices=sorted(SUBSET_PATHS) + ['all'])
    ap.add_argument('--out', default='data')
    args = ap.parse_args()

    targets = sorted(SUBSET_PATHS) if args.subset == 'all' else [args.subset]
    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    failed = []
    for name in targets:
        try:
            raw, url = fetch(SUBSET_PATHS[name])
        except RuntimeError as exc:
            print(f'[{name}] 下载失败\n{exc}', file=sys.stderr)
            failed.append(name)
            continue

        rows = normalize(raw)
        dest = outdir / f'arb_{name}.json'
        dest.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                        encoding='utf-8')

        expected = EXPECTED_COUNTS.get(name)
        note = ''
        if expected is not None and len(rows) != expected:
            note = (f'  (论文 Table 1 为 {expected} 题'
                    f'{"，导出含杂项，loader 会过滤" if len(rows) > expected else "，偏少，请核查"})')
        print(f'[{name}] {len(rows)} 条 -> {dest}{note}')
        print(f'         来源: {url}')

    if failed:
        sys.exit(f'\n以下 subset 下载失败: {", ".join(failed)}')


if __name__ == '__main__':
    main()
