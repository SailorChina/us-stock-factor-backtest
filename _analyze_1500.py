# -*- coding: utf-8 -*-
"""分析 $1500 回测结果：挑最强两个 + 对比 $3000 看佣金拖累。"""
import json, os

D = r'C:\Users\sailor\WorkBuddy\2026-09-11-09-02-22'
j15 = json.load(open(os.path.join(D, '_rank_all_1500.json'), encoding='utf-8'))
j30 = json.load(open(os.path.join(D, '_rank_all.json'), encoding='utf-8'))

def idx(JS):
    return {r['name']: r for r in JS['results']}

R15 = idx(j15)
R30 = idx(j30)

def g(r, tag, k):
    return r.get('m_' + tag, {}).get(k)

STR = [r for r in j15['results'] if r['family'] != '基准']
# 非破产，按有闸门 CAGR
alive = [r for r in STR if not g(r, 'on', 'bankrupt')]
by_cagr = sorted(alive, key=lambda r: (g(r,'on','cagr') or -1), reverse=True)
by_calmar = sorted(alive, key=lambda r: (g(r,'on','calmar') or -9), reverse=True)

def row(r, tag):
    c = g(r, tag, 'cagr'); t = g(r, tag, 'total'); f = g(r, tag, 'final')
    return dict(name=r['name'], cagr=c, total=t, final=f,
                mdd=g(r,tag,'mdd'), sharpe=g(r,tag,'sharpe'), calmar=g(r,tag,'calmar'),
                to=g(r,tag,'turnover_yr'), cash=g(r,tag,'avg_cash'))

print('=' * 70)
print(f"$1500 回测口径: 池 {j15['meta']['pool']} 只 | {j15['meta']['start']}~{j15['meta']['end']} "
      f"({j15['meta']['years']:.2f}年) | 本金 ${j15['meta']['cap']:,.0f} | 佣金 ${j15['meta']['comm']:.0f}/笔双边")
print(f"AI 策略: {'已含' if not j15.get('FAST') else 'FAST跳过'}")
print('=' * 70)

print('\n【A】纯收益最强（按有闸门 CAGR 前 2）')
for i, r in enumerate(by_cagr[:2], 1):
    x = row(r, 'on')
    print(f"  {i}. {x['name']}: CAGR {x['cagr']*100:.1f}% | 总收益 {x['total']*100:,.0f}% | "
          f"终值 ${x['final']:,.0f} (本金$1500) | 最大回撤 {x['mdd']*100:.1f}% | 夏普 {x['sharpe']:.2f} | Calmar {x['calmar']:.2f}")

print('\n【B】风险调整最强（按 Calmar 前 2）')
for i, r in enumerate(by_calmar[:2], 1):
    x = row(r, 'on')
    print(f"  {i}. {x['name']}: Calmar {x['calmar']:.2f} | 夏普 {x['sharpe']:.2f} | CAGR {x['cagr']*100:.1f}% | "
          f"终值 ${x['final']:,.0f} | 最大回撤 {x['mdd']*100:.1f}%")

print('\n【C】最强两个在 $1500 vs $3000 下的终值/佣金拖累对比')
picks = [by_cagr[0], by_calmar[0]]  # 收益冠军 + 风险调整冠军（若重合去重）
seen=set(); picks2=[]
for r in [by_cagr[0], by_cagr[1], by_calmar[0], by_calmar[1]]:
    if r['name'] not in seen:
        seen.add(r['name']); picks2.append(r)
for r in picks2:
    n = r['name']
    x15 = row(r, 'on')
    r30 = R30.get(n)
    if r30:
        x30 = row(r30, 'on')
        drag = (x30['cagr'] - x15['cagr']) * 100
        print(f"  · {n}")
        print(f"      $1500: 终值 ${x15['final']:,.0f} | CAGR {x15['cagr']*100:.1f}% | 总收益 {x15['total']*100:,.0f}%")
        print(f"      $3000: 终值 ${x30['final']:,.0f} | CAGR {x30['cagr']*100:.1f}% | 总收益 {x30['total']*100:,.0f}%")
        print(f"      本金减半 -> CAGR 多吞 {drag:.1f}pp（佣金拖累翻倍）")
    else:
        print(f"  · {n}: $1500 终值 ${x15['final']:,.0f} | CAGR {x15['cagr']*100:.1f}% (无$3000对照,可能AI/FAST跳过)")

print('\n【D】破产策略（$1500 下不可投）')
bk = [r for r in STR if g(r,'on','bankrupt')]
print(f"  {len(bk)} 个: " + ", ".join(r['name'] for r in bk))

print('\n基准（有闸门）:')
for r in j15['results']:
    if r['family']=='基准':
        x=row(r,'on')
        print(f"  {r['name']}: CAGR {x['cagr']*100:.1f}% | 总收益 {x['total']*100:,.0f}% | 终值 ${x['final']:,.0f}")
