#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 export_eval_excel.py 导出的 xlsx 生成符号等价性人工复核页面。

读「BadCase」表中 reason == manual_review 的行,输出一个自包含 HTML:
左右并排渲染模型答案与标准答案(MathJax),键盘判定,底部实时显示
判定对各子集分数的影响,导出 CSV 与进度保存/恢复。

答案取值规则(v2,修复截断问题):
  - 模型答案优先从「完整输出」列取最后一个 ANSWER: 之后的全文——
    evaluator 写入 results JSON 的 pred 字段是截断过的,完整输出才是全的。
    没有分隔符时回退到「模型最终答案」列。
  - 标准答案全文展示,不做任何截断。
  - 「模型输出结尾」默认折叠展示末尾 3000 字符,可展开全文。

用法:
    python tools/make_review_html.py docs/results/arb_full9_analysis_v4.xlsx \
        --out docs/results/manual_review.html
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

_ANS = re.compile(r'ANSWER\s*:\s*', re.I)


def norm_math(s: str) -> str:
    """剥外层数学定界符;修复答案字段里被写坏的换行(\\n -> \\ )。"""
    t = str(s or '').strip()
    t = re.sub(r'\\n(?![a-zA-Z])', r'\\ ', t)
    for a, z in (('$$', '$$'), ('\\[', '\\]'), ('\\(', '\\)'), ('$', '$')):
        if t.startswith(a) and t.endswith(z) and len(t) > len(a) + len(z):
            t = t[len(a):-len(z)].strip()
            break
    return t


def final_answer(full_output: str, fallback: str) -> str:
    """取完整输出中最后一个 ANSWER: 之后的全文;qwen 的自我怀疑循环会
    重复输出 ANSWER 行,最后一个才是最终提交。没有分隔符时用 fallback。"""
    t = str(full_output or '')
    parts = _ANS.split(t)
    if len(parts) > 1:
        ans = parts[-1].strip()
        if ans:
            return ans
    return str(fallback or '')


def build(xlsx: Path, out: Path, tail_chars: int) -> None:
    b = pd.read_excel(xlsx, sheet_name='BadCase')
    ov = pd.read_excel(xlsx, sheet_name='总览')
    m = b[b['reason'] == 'manual_review'].copy()
    if m.empty:
        raise SystemExit('BadCase 表里没有 reason==manual_review 的行')

    items = []
    for _, r in m.iterrows():
        full = str(r.get('完整输出', '') or '')
        pred = final_answer(full, r.get('模型最终答案', ''))
        gold = str(r.get('标准答案', '') or '')
        items.append({
            'model': r['模型'], 'subset': r['子集'], 'qid': str(r['题号']),
            'pred': norm_math(pred), 'gold': norm_math(gold),
            'predRaw': pred, 'goldRaw': gold,
            'stem': str(r.get('题干', '') or ''),
            'tail': full[-tail_chars:] if len(full) > tail_chars else full,
            'full': full,
        })

    subsets = sorted(m['子集'].unique())
    base = {}
    for _, r in ov[ov['子集'].isin(subsets)].iterrows():
        base[f"{r['模型']}|{r['子集']}"] = {
            'n': int(r['题数']),
            'ok': round(float(r['官方指标']) / 100 * int(r['题数'])),
            'score': float(r['官方指标']),
        }

    data = json.dumps({'items': items, 'base': base}, ensure_ascii=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.replace('__DATA__', data), encoding='utf-8')
    print(f'写出 {out}')
    print(f'  {len(items)} 条待复核 / 涉及子集: {", ".join(subsets)}')
    print('  判定规则: 默认不等价,由「等价」承担举证责任;只判数学等价,'
          '不看格式;存疑按不等价计并单独披露。')


TEMPLATE = r'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>符号等价性人工复核</title>
<script>window.MathJax={tex:{inlineMath:[['$','$'],['\\(','\\)']],displayMath:[['$$','$$'],['\\[','\\]']],processEscapes:true},options:{skipHtmlTags:['script','noscript','style','textarea','pre','code']},startup:{typeset:false}};</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js"></script>
<style>
:root{--paper:#FBFBF9;--ink:#12161C;--muted:#6B7280;--rule:#DCDED8;--slate:#2F4858;
  --eq:#1F6F4A;--neq:#9B2226;--unsure:#8A6D1F;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
  --sans:ui-sans-serif,-apple-system,"Helvetica Neue","PingFang SC",sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
header{position:sticky;top:0;z-index:20;background:rgba(251,251,249,.94);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--rule);padding:14px 24px}
.hrow{display:flex;align-items:baseline;gap:18px;flex-wrap:wrap}
h1{font-size:16px;margin:0;letter-spacing:.04em;font-weight:650}
.sub{color:var(--muted);font-size:12.5px;font-family:var(--mono)}
.bar{height:3px;background:var(--rule);margin-top:12px;border-radius:2px;overflow:hidden;display:flex}
.bar i{display:block;height:100%}
.bar .e{background:var(--eq)}.bar .n{background:var(--neq)}.bar .u{background:var(--unsure)}
main{max-width:1080px;margin:0 auto;padding:24px 24px 160px}
.card{border:1px solid var(--rule);border-radius:3px;background:#fff;margin:0 0 18px;
  scroll-margin-top:110px;transition:border-color .15s}
.card[data-v="eq"]{border-left:3px solid var(--eq)}
.card[data-v="neq"]{border-left:3px solid var(--neq)}
.card[data-v="unsure"]{border-left:3px solid var(--unsure)}
.card.cur{border-color:var(--slate);box-shadow:0 0 0 2px rgba(47,72,88,.10)}
.chead{display:flex;justify-content:space-between;align-items:center;gap:12px;
  padding:9px 16px;border-bottom:1px solid var(--rule);font-family:var(--mono);
  font-size:11.5px;color:var(--muted);letter-spacing:.03em}
.chead b{color:var(--ink);font-weight:600}
.split{display:grid;grid-template-columns:1fr 46px 1fr;align-items:stretch}
.side{padding:18px 16px;min-width:0}
.side .lab{font-family:var(--mono);font-size:10.5px;letter-spacing:.11em;
  color:var(--muted);margin-bottom:10px}
.expr{overflow-x:auto;font-size:16px;min-height:34px;max-height:300px;overflow-y:auto}
.raw{margin-top:10px;font-family:var(--mono);font-size:11px;color:var(--muted);
  word-break:break-all;white-space:pre-wrap;line-height:1.45;max-height:220px;overflow-y:auto}
.gutter{display:flex;align-items:center;justify-content:center;
  border-left:1px solid var(--rule);border-right:1px solid var(--rule);
  background:#FCFCFA;font-size:19px;color:var(--muted);font-family:var(--mono)}
.card[data-v="eq"] .gutter{color:var(--eq)}
.card[data-v="neq"] .gutter{color:var(--neq)}
.card[data-v="unsure"] .gutter{color:var(--unsure)}
.acts{display:flex;gap:8px;padding:12px 16px;border-top:1px solid var(--rule);
  align-items:center;flex-wrap:wrap;background:#FCFCFA}
button{font-family:var(--sans);font-size:13px;padding:6px 14px;border-radius:3px;
  border:1px solid var(--rule);background:#fff;color:var(--ink);cursor:pointer;transition:.12s}
button:hover{border-color:var(--slate)}
button:focus-visible{outline:2px solid var(--slate);outline-offset:2px}
button.on[data-a="eq"]{background:var(--eq);border-color:var(--eq);color:#fff}
button.on[data-a="neq"]{background:var(--neq);border-color:var(--neq);color:#fff}
button.on[data-a="unsure"]{background:var(--unsure);border-color:var(--unsure);color:#fff}
button .k{font-family:var(--mono);font-size:10px;opacity:.55;margin-left:6px}
.note{flex:1;min-width:180px;border:1px solid var(--rule);border-radius:3px;
  padding:6px 10px;font-family:var(--sans);font-size:12.5px;background:#fff}
details{border-top:1px solid var(--rule)}
summary{cursor:pointer;padding:8px 16px;font-family:var(--mono);font-size:11px;
  color:var(--muted);letter-spacing:.05em;user-select:none}
summary:hover{color:var(--ink)}
.dbody{padding:4px 16px 16px;font-size:14px;border-top:1px dashed var(--rule);
  max-height:420px;overflow:auto}
.dbody pre{white-space:pre-wrap;font-family:var(--mono);font-size:11.5px;
  color:#374151;margin:0}
.morebtn{margin:8px 0 0;font-size:11.5px}
footer{position:fixed;left:0;right:0;bottom:0;z-index:30;background:rgba(251,251,249,.97);
  border-top:1px solid var(--rule);padding:10px 24px;backdrop-filter:blur(8px)}
.fwrap{max-width:1080px;margin:0 auto;display:flex;gap:22px;align-items:center;
  flex-wrap:wrap;justify-content:space-between}
table.impact{border-collapse:collapse;font-family:var(--mono);font-size:11.5px}
table.impact td,table.impact th{padding:2px 10px 2px 0;text-align:left;
  color:var(--muted);font-weight:400}
table.impact td.now{color:var(--ink);font-weight:600}
table.impact td.up{color:var(--eq);font-weight:600}
.tools{display:flex;gap:8px;align-items:center}
.hint{font-family:var(--mono);font-size:10.5px;color:var(--muted)}
@media(max-width:760px){.split{grid-template-columns:1fr}.gutter{border:0;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);height:34px}}
@media(prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head><body>

<header><div class="hrow">
  <h1>符号等价性人工复核</h1>
  <span class="sub" id="meta"></span>
  <span class="sub" id="prog"></span>
  <span class="hint">1 等价 · 2 不等价 · 3 存疑 · J/K 上下 · 判完自动跳下一条</span>
</div><div class="bar"><i class="e" id="be"></i><i class="n" id="bn"></i><i class="u" id="bu"></i></div></header>

<main id="list"></main>

<footer><div class="fwrap">
  <table class="impact"><tbody id="impact"></tbody></table>
  <div class="tools">
    <button id="exp">导出 CSV</button>
    <button id="cp">复制进度</button>
    <button id="ld">载入进度</button>
  </div>
</div></footer>

<script>
const D = __DATA__;
const V = {}, N = {};
const key = it => it.model + '|' + it.subset + '|' + it.qid;
let cur = 0;
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function render(){
  document.getElementById('meta').textContent =
    `SymPy 判不动的 ${D.items.length} 对表达式`;
  document.getElementById('list').innerHTML = D.items.map((it,i)=>`
  <section class="card" id="c${i}" data-i="${i}">
    <div class="chead"><span><b>${esc(it.model)}</b> · ${esc(it.subset)} · 题 ${esc(it.qid)}</span>
      <span>${i+1} / ${D.items.length}</span></div>
    <div class="split">
      <div class="side"><div class="lab">模型答案(完整输出中最后一个 ANSWER 之后)</div>
        <div class="expr">\\[${it.pred}\\]</div>
        <div class="raw">${esc(it.predRaw)}</div></div>
      <div class="gutter" id="g${i}">=?</div>
      <div class="side"><div class="lab">标准答案(全文)</div>
        <div class="expr">\\[${it.gold}\\]</div>
        <div class="raw">${esc(it.goldRaw)}</div></div>
    </div>
    <div class="acts">
      <button data-a="eq"     data-i="${i}">等价<span class="k">1</span></button>
      <button data-a="neq"    data-i="${i}">不等价<span class="k">2</span></button>
      <button data-a="unsure" data-i="${i}">存疑<span class="k">3</span></button>
      <input class="note" data-i="${i}" placeholder="理由(可选,存疑建议写)">
    </div>
    <details><summary>题干</summary><div class="dbody">${esc(it.stem)}</div></details>
    <details><summary>模型输出结尾(${it.tail.length} / ${it.full.length} 字符)</summary>
      <div class="dbody"><pre id="t${i}">${esc(it.tail)}</pre>
      ${it.full.length>it.tail.length?`<button class="morebtn" data-f="${i}">展开全文</button>`:''}
      </div></details>
  </section>`).join('');

  document.querySelectorAll('.acts button').forEach(b=>{
    b.onclick = () => mark(+b.dataset.i, b.dataset.a);
  });
  document.querySelectorAll('.morebtn').forEach(b=>{
    b.onclick = () => {
      const i = +b.dataset.f;
      document.getElementById('t'+i).textContent = D.items[i].full;
      b.remove();
    };
  });
  document.querySelectorAll('.note').forEach(n=>{
    n.oninput = () => { N[key(D.items[+n.dataset.i])] = n.value; };
  });
  if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise();
  focusCard(0);
}

function mark(i, v){
  const k = key(D.items[i]);
  V[k] = (V[k] === v) ? undefined : v;
  if (!V[k]) delete V[k];
  const card = document.getElementById('c'+i);
  card.dataset.v = V[k] || '';
  document.getElementById('g'+i).textContent =
    V[k]==='eq' ? '≡' : V[k]==='neq' ? '≠' : V[k]==='unsure' ? '?' : '=?';
  card.querySelectorAll('.acts button').forEach(b=>
    b.classList.toggle('on', b.dataset.a === V[k]));
  update();
  if (V[k] && i < D.items.length-1) focusCard(i+1, true);
}

function focusCard(i, scroll){
  cur = Math.max(0, Math.min(i, D.items.length-1));
  document.querySelectorAll('.card').forEach(c=>c.classList.remove('cur'));
  const c = document.getElementById('c'+cur);
  c.classList.add('cur');
  if (scroll) c.scrollIntoView({behavior:'smooth', block:'start'});
}

function update(){
  const vals = Object.values(V);
  const e = vals.filter(v=>v==='eq').length;
  const n = vals.filter(v=>v==='neq').length;
  const u = vals.filter(v=>v==='unsure').length;
  const t = D.items.length;
  document.getElementById('prog').textContent =
    `${vals.length} / ${t} 已判 · 等价 ${e} · 不等价 ${n} · 存疑 ${u}`;
  document.getElementById('be').style.width = e/t*100 + '%';
  document.getElementById('bn').style.width = n/t*100 + '%';
  document.getElementById('bu').style.width = u/t*100 + '%';

  document.getElementById('impact').innerHTML =
    Object.entries(D.base).map(([k,b])=>{
      const gained = D.items.filter(it => it.model+'|'+it.subset === k
        && V[key(it)] === 'eq').length;
      const ns = (b.ok + gained) / b.n * 100;
      const [mo, su] = k.split('|');
      return `<tr><td>${mo}</td><td>${su.replace('arb_','')}</td>
        <td>原 ${b.score.toFixed(2)}</td>
        <td class="${gained?'up':'now'}">复核后 ${ns.toFixed(2)}${
          gained?' (+'+(ns-b.score).toFixed(2)+')':''}</td></tr>`;
    }).join('');
}

document.addEventListener('keydown', e=>{
  if (/INPUT|TEXTAREA/.test(document.activeElement.tagName)) return;
  if (e.key==='1') mark(cur,'eq');
  else if (e.key==='2') mark(cur,'neq');
  else if (e.key==='3') mark(cur,'unsure');
  else if (e.key==='j'||e.key==='ArrowDown'){ focusCard(cur+1,true); e.preventDefault(); }
  else if (e.key==='k'||e.key==='ArrowUp'){ focusCard(cur-1,true); e.preventDefault(); }
});

document.getElementById('exp').onclick = ()=>{
  const head = '模型,子集,题号,人工判定,理由\n';
  const body = D.items.map(it=>{
    const k = key(it);
    const note = (N[k]||'').replace(/"/g,'""');
    return `${it.model},${it.subset},${it.qid},${V[k]||'未判'},"${note}"`;
  }).join('\n');
  const url = URL.createObjectURL(new Blob(['\ufeff'+head+body],{type:'text/csv'}));
  const a = document.createElement('a');
  a.href = url; a.download = 'manual_review.csv'; a.click();
  URL.revokeObjectURL(url);
};

document.getElementById('cp').onclick = async ()=>{
  const s = JSON.stringify({V,N});
  try { await navigator.clipboard.writeText(s);
    alert('进度已复制到剪贴板,粘回「载入进度」即可恢复'); }
  catch { prompt('复制下面这段保存:', s); }
};

document.getElementById('ld').onclick = ()=>{
  const s = prompt('粘贴之前复制的进度:');
  if (!s) return;
  try {
    const o = JSON.parse(s);
    Object.assign(V, o.V||{}); Object.assign(N, o.N||{});
    D.items.forEach((it,i)=>{
      const k = key(it);
      const card = document.getElementById('c'+i);
      card.dataset.v = V[k]||'';
      document.getElementById('g'+i).textContent =
        V[k]==='eq'?'≡':V[k]==='neq'?'≠':V[k]==='unsure'?'?':'=?';
      card.querySelectorAll('.acts button').forEach(b=>
        b.classList.toggle('on', b.dataset.a===V[k]));
      const nn = card.querySelector('.note'); if (N[k]) nn.value = N[k];
    });
    update();
  } catch(err){ alert('这段进度读不出来,检查是否复制完整'); }
};

render(); update();
</script></body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('xlsx', help='export_eval_excel.py 导出的分析工作簿')
    ap.add_argument('--out', default=None, help='输出 HTML 路径,默认同目录 manual_review.html')
    ap.add_argument('--tail-chars', type=int, default=3000,
                    help='「模型输出结尾」默认展示的末尾字符数(可点击展开全文)')
    args = ap.parse_args()
    xlsx = Path(args.xlsx)
    out = Path(args.out) if args.out else xlsx.with_name('manual_review.html')
    build(xlsx, out, args.tail_chars)


if __name__ == '__main__':
    main()
