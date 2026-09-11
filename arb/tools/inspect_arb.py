"""拉取全部 ARB subset 并报告数据结构。

    python tools/inspect_arb.py                 # 全部
    python tools/inspect_arb.py --subset law    # 单个
    python tools/inspect_arb.py --sample 2      # 每个 subset 打印 2 条样例

扩展到新 subset 之前先跑这个 —— loader 和 evaluator 怎么写，
取决于字段名、Problem Type 取值、选项和图片的存放方式，这些必须先看清楚。
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter

BASE = 'https://advanced-reasoning-benchmark.netlify.app/api/lib'

SUBSETS = {
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

# 值可能很长（题面），只对这些字段统计取值分布
ENUM_FIELDS = ('Problem Type', 'Subject', 'Topic', 'Split', 'Answer Type')


def get(path, timeout=45):
    url = f'{BASE}/{path}'
    req = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0 (arb-inspect)'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def rows_of(raw):
    if isinstance(raw, dict):
        for k in ('data', 'items', 'questions', 'results'):
            if isinstance(raw.get(k), list):
                return raw[k]
    return raw if isinstance(raw, list) else []


def preview(v, n=90):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = ' '.join(s.split())
    return s[:n] + ('…' if len(s) > n else '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subset', choices=sorted(SUBSETS))
    ap.add_argument('--sample', type=int, default=1)
    args = ap.parse_args()

    names = [args.subset] if args.subset else sorted(SUBSETS)

    for name in names:
        print('=' * 72)
        print(name, ' ->', SUBSETS[name])
        try:
            rows = rows_of(get(SUBSETS[name]))
        except Exception as exc:                            # noqa: BLE001
            print(f'  下载失败: {type(exc).__name__}: {exc}', file=sys.stderr)
            continue

        print(f'  条数: {len(rows)}')
        if not rows:
            continue

        # 字段并集，并标出哪些字段不是每条都有
        all_keys = Counter()
        for r in rows:
            if isinstance(r, dict):
                all_keys.update(r.keys())
        print('  字段:')
        for k, c in sorted(all_keys.items()):
            mark = '' if c == len(rows) else f'  ← 仅 {c}/{len(rows)} 条有'
            print(f'    {k}{mark}')

        # 枚举字段的取值分布 —— loader 靠这个过滤
        for f in ENUM_FIELDS:
            if f in all_keys:
                dist = Counter(str(r.get(f, '')).strip() for r in rows)
                print(f'  {f} 分布: {dict(dist)}')

        # 图片字段探测
        img_keys = [k for k in all_keys
                    if any(t in k.lower() for t in ('image', 'img', 'figure'))]
        if img_keys:
            for k in img_keys:
                vals = [r.get(k) for r in rows if r.get(k)]
                print(f'  图片字段 {k}: {len(vals)} 条非空，样例 {preview(vals[0]) if vals else "-"}')

        for i, r in enumerate(rows[:args.sample]):
            print(f'  --- 样例 {i} ---')
            for k in sorted(r):
                print(f'    {k:<22} {preview(r[k])}')


if __name__ == '__main__':
    main()
