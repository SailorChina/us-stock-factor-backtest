# -*- coding: utf-8 -*-
"""调仓周期 × 本金 对比：月频(21日) vs 10日，以及 6 周期 × $1,500/$3,000 全景。
数据来自已跑完的两套统一回测：_rank_all.json($3000) / _rank_all_1500.json($1500)。
不做任何重跑——口径完全一致（81只池 / 2019-01-03~2026-09-11 / $2笔双边 / 闸门$5M）。
"""
import json, os
BASE = r'C:\Users\sailor\WorkBuddy\2026-09-11-09-02-22'
d3 = json.load(open(os.path.join(BASE, '_rank_all.json'), encoding='utf-8'))
d1 = json.load(open(os.path.join(BASE, '_rank_all_1500.json'), encoding='utf-8'))
META = d3['meta']

def idx(d):
    return {r['name']: r for r in d['results']}
i3, i1 = idx(d3), idx(d1)

# —— 匹配两个信号家族 × 6 个周期（rebal -> name 字典，杜绝错位）——
FAMS = {
    'Vortex Top2':       {21:'Vortex Top2', 5:'Vortex Top2 @5日调仓', 10:'Vortex Top2 @10日调仓',
                          15:'Vortex Top2 @15日调仓', 42:'Vortex Top2 @42日调仓', 63:'Vortex Top2 @63日调仓'},
    '动量-1月反转 Top2': {21:'动量-1月反转 Top2', 5:'动量-1月反转 Top2 @5日调仓', 10:'动量-1月反转 Top2 @10日调仓',
                          15:'动量-1月反转 Top2 @15日调仓', 42:'动量-1月反转 Top2 @42日调仓', 63:'动量-1月反转 Top2 @63日调仓'},
}
REBAL_ORDER = [5, 10, 15, 21, 42, 63]
REBAL_LABEL = {5:'5日',10:'10日',15:'15日',21:'月频(21)',42:'42日',63:'63日'}

def g(rec, tag, k):
    return rec['m_' + tag].get(k)

def num(x, nd=1):
    if x is None: return '—'
    if isinstance(x, float) and x != x: return '—'
    return f'{x:.{nd}f}'
def pc(x, nd=1):    # 小数 -> 百分数串（不含 %），如 0.599 -> '59.9'
    return '—' if x is None else f'{x*100:.{nd}f}'
def rt(x, nd=1):    # 倍数 -> 收益率百分数串（不含 %），如 36.95 -> '3595.0'
    return '—' if x is None else f'{(x-1)*100:.{nd}f}'
def dp(x, nd=1):    # 小数差 -> 百分点串（不含 pp），如 0.016 -> '1.6'
    return '—' if x is None else f'{x*100:.{nd}f}'

# 校验所有目标 name 在两套里都存在
missing = []
for fam, names in FAMS.items():
    for rb, nm in names.items():
        if nm not in i3 or nm not in i1:
            missing.append((fam, nm))
assert not missing, f'缺失样本: {missing}'

# ============ 报告 ============
OUT = []
def A(s=''): OUT.append(s)

A('# 调仓周期 × 本金 对比：月频 vs 10日（以及 6 周期 × $1,500/$3,000 全景）')
A()
A(f'> 生成口径：同一引擎、同一标的池（81 只）、同一回测区间（{META.get("start")}~{META.get("end")}，'
  f'约 7.69 年）、同一佣金模型（$2/笔双边）、同一流动性闸门（$5M 滚动 60 日成交额中位数）。')
A('> 数据来源：已跑完的两套统一回测 `_rank_all.json`（$3,000）与 `_rank_all_1500.json`（$1,500）。'
  '**本对比未做任何新回测**——只把两套现成结果按信号逻辑对齐，所以是严格的苹果对苹果。')
A()
A('## 0. 先看结论（省流版）')
A()

# 计算核心对子（小数形式）
def pair(fam, rb, cap_idx):
    return cap_idx[FAMS[fam][rb]]
v10_3 = g(pair('Vortex Top2',10,i3),'on','cagr'); v21_3 = g(pair('Vortex Top2',21,i3),'on','cagr')
v10_1 = g(pair('Vortex Top2',10,i1),'on','cagr'); v21_1 = g(pair('Vortex Top2',21,i1),'on','cagr')
m10_3 = g(pair('动量-1月反转 Top2',10,i3),'on','cagr'); m21_3 = g(pair('动量-1月反转 Top2',21,i3),'on','cagr')
m10_1 = g(pair('动量-1月反转 Top2',10,i1),'on','cagr'); m21_1 = g(pair('动量-1月反转 Top2',21,i1),'on','cagr')

# 拖累差（百分点）= CAGR(3000) - CAGR(1500)，小数差 -> 在显示时 ×100
def drag_pp(fam, rb):
    c3 = g(pair(fam,rb,i3),'on','cagr') or 0; c1 = g(pair(fam,rb,i1),'on','cagr') or 0
    return (c3 - c1) * 100
A(f'- **小本金下，月频确实比 10 日更"扛得住佣金"**：本金从 $3,000 砍到 $1,500，'
  f'固定 $2/笔的占比翻倍，但**调仓越频繁、被多吞的 CAGR 越多**。')
A(f'  - Vortex Top2：月频被多吞 **{dp((g(pair("Vortex Top2",21,i3),"on","cagr") or 0)-(g(pair("Vortex Top2",21,i1),"on","cagr") or 0))}pp**，'
  f'10 日被多吞 **{dp((g(pair("Vortex Top2",10,i3),"on","cagr") or 0)-(g(pair("Vortex Top2",10,i1),"on","cagr") or 0))}pp**（10 日更吃亏）。')
A(f'  - 动量-1月反转 Top2：月频被多吞 **{dp((g(pair("动量-1月反转 Top2",21,i3),"on","cagr") or 0)-(g(pair("动量-1月反转 Top2",21,i1),"on","cagr") or 0))}pp**，'
  f'10 日被多吞 **{dp((g(pair("动量-1月反转 Top2",10,i3),"on","cagr") or 0)-(g(pair("动量-1月反转 Top2",10,i1),"on","cagr") or 0))}pp**。')
A(f'- **因此在 $1,500 下，月频相对 10 日的"领先幅度"被缩小**：')
A(f'  - Vortex：月频(21) CAGR {pc(v21_1)}% vs 10日 {pc(v10_1)}%（差 {dp(v21_1-v10_1)}pp）；'
  f'在 $3,000 下则是 {pc(v21_3)}% vs {pc(v10_3)}%（差 {dp(v21_3-v10_3)}pp）。')
A(f'  - 动量：月频 CAGR {pc(m21_1)}% vs 10日 {pc(m10_1)}%（差 {dp(m21_1-m10_1)}pp）；'
  f'$3,000 下 {pc(m21_3)}% vs {pc(m10_3)}%（差 {dp(m21_3-m10_3)}pp）。')
A(f'- **净建议**：在 $1,500 这种小本金下，**月频策略的性价比高于 10 日调仓**——'
  '10 日的"风险调整优势"有一部分被佣金吃掉了。但 Vortex 家族在两种本金下、所有周期里都稳居前列，'
  '且月频版回撤也更小（见下表），所以 $1,500 实盘首选仍是 **Vortex Top2（月频）** 而非 10 日版。')
A()

A('## 1. 核心对子：月频(21日) vs 10日（同一信号、仅周期不同）')
A()
A('### 1.1 Vortex Top2（风险调整家族的代表）')
A()
A('| 本金 | 周期 | CAGR | 总收益 | 终值($) | 最大回撤 | 夏普 | Calmar |')
A('|---|---|---:|---:|---:|---:|---:|---:|')
for cap, idxd in [('$3,000',i3),('$1,500',i1)]:
    for rb in (21,10):
        r = pair('Vortex Top2', rb, idxd)['m_on']
        A(f'| {cap} | {REBAL_LABEL[rb]} | {pc(r["cagr"])}% | {rt(r["total"])}% | {num(r["final"],0)} | {pc(r["mdd"])}% | {num(r["sharpe"],2)} | {num(r["calmar"],2)} |')
A()
A('### 1.2 动量-1月反转 Top2（纯收益家族的代表）')
A()
A('| 本金 | 周期 | CAGR | 总收益 | 终值($) | 最大回撤 | 夏普 | Calmar |')
A('|---|---|---:|---:|---:|---:|---:|---:|')
for cap, idxd in [('$3,000',i3),('$1,500',i1)]:
    for rb in (21,10):
        r = pair('动量-1月反转 Top2', rb, idxd)['m_on']
        A(f'| {cap} | {REBAL_LABEL[rb]} | {pc(r["cagr"])}% | {rt(r["total"])}% | {num(r["final"],0)} | {pc(r["mdd"])}% | {num(r["sharpe"],2)} | {num(r["calmar"],2)} |')
A()
A('> 读数：Vortex 月频版在任何本金下都**回撤更小、Calmar 更高**；动量月频版在 $1,500 下 CAGR 与 10 日几乎持平（差 <1pp），'
  '但 10 日版佣金拖累更大——所以月频是更稳的选择。')
A()

A('## 2. 周期扫描全景：两家族 × 6 周期 × 2 本金')
A()
A('### 2.1 Vortex Top2 — CAGR（%）')
A()
A('| 周期 | $3,000 CAGR | $1,500 CAGR | 本金减半多吞 | $3,000 终值 | $1,500 终值 | $3,000 MDD | $1,500 MDD |')
A('|---|---:|---:|---:|---:|---:|---:|---:|')
for rb in REBAL_ORDER:
    c3 = g(pair('Vortex Top2',rb,i3),'on','cagr'); c1 = g(pair('Vortex Top2',rb,i1),'on','cagr')
    f3 = g(pair('Vortex Top2',rb,i3),'on','final'); f1 = g(pair('Vortex Top2',rb,i1),'on','final')
    d3_ = g(pair('Vortex Top2',rb,i3),'on','mdd'); d1_ = g(pair('Vortex Top2',rb,i1),'on','mdd')
    A(f'| {REBAL_LABEL[rb]} | {pc(c3)} | {pc(c1)} | {dp((c3 or 0)-(c1 or 0))}pp | {num(f3,0)} | {num(f1,0)} | {pc(d3_)}% | {pc(d1_)}% |')
A()
A('### 2.2 动量-1月反转 Top2 — CAGR（%）')
A()
A('| 周期 | $3,000 CAGR | $1,500 CAGR | 本金减半多吞 | $3,000 终值 | $1,500 终值 | $3,000 MDD | $1,500 MDD |')
A('|---|---:|---:|---:|---:|---:|---:|---:|')
for rb in REBAL_ORDER:
    c3 = g(pair('动量-1月反转 Top2',rb,i3),'on','cagr'); c1 = g(pair('动量-1月反转 Top2',rb,i1),'on','cagr')
    f3 = g(pair('动量-1月反转 Top2',rb,i3),'on','final'); f1 = g(pair('动量-1月反转 Top2',rb,i1),'on','final')
    d3_ = g(pair('动量-1月反转 Top2',rb,i3),'on','mdd'); d1_ = g(pair('动量-1月反转 Top2',rb,i1),'on','mdd')
    A(f'| {REBAL_LABEL[rb]} | {pc(c3)} | {pc(c1)} | {dp((c3 or 0)-(c1 or 0))}pp | {num(f3,0)} | {num(f1,0)} | {pc(d3_)}% | {pc(d1_)}% |')
A()
A('> 规律：Vortex 家族在 **15日/月频(21)/42日** 这几个周期 CAGR 都很高且回撤可控，10日优势被本金缩小；'
  '动量家族则是 **月频(21) 在 $1,500 下反而略高于 10日**（{0}% vs {1}%），是"小本金月频更优"最直观的证据。'.format(
      pc(g(pair('动量-1月反转 Top2',21,i1),'on','cagr')), pc(g(pair('动量-1月反转 Top2',10,i1),'on','cagr'))))
A()

A('## 3. 佣金拖累热力：本金减半（$3,000→$1,500）每个周期多吞多少 CAGR')
A()
A('把"本金减半多吞的 CAGR（百分点）"按调仓频率分组，越频繁越吃亏：')
A()
A('| 家族 | 5日 | 10日 | 15日 | 月频(21) | 42日 | 63日 |')
A('|---|---:|---:|---:|---:|---:|---:|')
for fam in FAMS:
    row = f'| {fam} |'
    for rb in REBAL_ORDER:
        row += f' {dp((g(pair(fam,rb,i3),"on","cagr") or 0)-(g(pair(fam,rb,i1),"on","cagr") or 0))}pp |'
    A(row)
A()
A('> 这是"固定 $2/笔"模型的必然结果：调仓次数 ∝ 1/周期，本金越小每笔占比越大。'
  '**10 日调仓的佣金拖累比月频高约 1~1.5pp**，在 $1,500 下足以抹平它相对月频的部分优势。')
A()

A('## 4. 全局印证：全部策略在两本金下的 CAGR 差（按频率分组平均）')
A()
from collections import defaultdict
diff_by_rb = defaultdict(list)
for nm, r3 in i3.items():
    if nm not in i1: continue
    rb = r3.get('rebal')
    if rb is None: continue
    c3 = g(r3,'on','cagr'); c1 = g(i1[nm],'on','cagr')
    if c3 is None or c1 is None: continue
    diff_by_rb[rb].append((c3 - c1) * 100)   # 已是百分点（×100）
A('| 调仓周期 | 样本数 | 平均多吞 CAGR | 中位多吞 |')
A('|---|---:|---:|---:|')
for rb in sorted(diff_by_rb):
    vals = diff_by_rb[rb]
    if not vals: continue
    avg = sum(vals)/len(vals)
    med = sorted(vals)[len(vals)//2]
    A(f'| {REBAL_LABEL[rb]} | {len(vals)} | {num(avg,1)}pp | {num(med,1)}pp |')
A()
A('> 样本说明：除 Vortex/动量两家族做了 5/10/15/42/63 日扫描外，其余 50+ 策略只跑了月频(21)，'
  '所以月频组样本量最大、最具代表性。趋势一致：**周期越短，本金减半的佣金惩罚越大**。')
A()

A('## 5. 给你的实盘建议（基于这份对比）')
A()
v21_1_cagr = g(pair('Vortex Top2',21,i1),'on','cagr'); v21_1_mdd = g(pair('Vortex Top2',21,i1),'on','mdd')
v21_1_cal = g(pair('Vortex Top2',21,i1),'on','calmar')
less = drag_pp('Vortex Top2',10) - drag_pp('Vortex Top2',21)   # 月频比 10 日少被佣金吞的 pp（正数）
A(f'- **$1,500 本金，首选 Vortex Top2（月频，21日）**：CAGR {pc(v21_1_cagr)}%、最大回撤 {pc(v21_1_mdd)}%、Calmar {num(v21_1_cal,2)}；'
  f'比同家族 10 日版少被佣金吞约 {num(less,1)}pp，且回撤更小。')
A('- **若追求最高收益且能扛 −68% 回撤**：月频均线双雄（金叉+MA50距离 / MA200距离）CAGR 都在 97% 附近，'
  '且月频的佣金拖累仅 ~2pp，是 $1,500 下"收益/成本"比最高的组合。')
A('- **避免 10 日以下高频**：在 $1,500 下，5日/10日调仓的佣金惩罚开始明显，且 v30 已证明短周期还叠加最大相位噪声——'
  '小本金 + 短周期 = 双重不利。')
A()
A('---')
A()
A('## 附：口径与可比性声明')
A()
A('- 所有数字来自**同一引擎 v33 的两套统一回测**（已在 `_rank_all_strategies.py` 的 10 项守恒恒等式下通过：'
  '价值守恒 13,874 次调仓、价格归因 126,200 天，残差 < 1e-14）。')
A('- 本对比**未做任何新回测**，仅对齐两套现成结果，因此不存在口径漂移。')
A('- ⚠️ **对比不是选股建议**：Vortex/动量家族的"第一"是在同一批数据上试过数十策略挑出来的（多重比较运气），'
  '且标的池是 2026 赢家榜（幸存者偏差）。回测 ≠ 预测。')
A('- 成本模型严格按你实盘口径：**美股固定 $2/笔、买卖各收**（富途 2026-09-12 确认）。')

txt = '\n'.join(OUT)
path = os.path.join(BASE, '美股调仓周期×本金对比.md')
with open(path, 'w', encoding='utf-8', newline='\n') as f:
    f.write(txt)
print('written:', path)
print('size:', len(txt.encode('utf-8')))
# 控制台校验
print('\n--- 校验 ---')
for cap, idxd, tag in [('$3000',i3,'3'),('$1500',i1,'1')]:
    for fam in ['Vortex Top2','动量-1月反转 Top2']:
        c21 = g(pair(fam,21,idxd),'on','cagr')*100
        c10 = g(pair(fam,10,idxd),'on','cagr')*100
        print(f'{cap} {fam}: 月频 {c21:.1f}% / 10日 {c10:.1f}%')
print('Vortex 拖累 月频/10日(pp):', drag_pp('Vortex Top2',21), '/', drag_pp('Vortex Top2',10))
print('动量 拖累 月频/10日(pp):', drag_pp('动量-1月反转 Top2',21), '/', drag_pp('动量-1月反转 Top2',10))
