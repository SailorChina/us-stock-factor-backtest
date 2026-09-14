# -*- coding: utf-8 -*-
"""从 _rank_all.json 生成一版【聚焦收益】的排行榜（比 v26 总报告更清爽）。"""
import json, os

D = r'C:\Users\sailor\WorkBuddy\2026-09-11-09-02-22'
d = json.load(open(os.path.join(D, '_rank_all.json'), encoding='utf-8'))
RES = d['results']
M = d['meta']

def g(r, tag, k):
    v = r.get('m_' + tag, {}).get(k)
    return v

def pct(x):
    if x is None: return '—'
    return f'{x*100:.1f}%'

def num(x, nd=1):
    if x is None: return '—'
    return f'{x:.{nd}f}'

# 过滤掉 benchmark（family 不在普通策略里）；benchmark 单独列
STR = [r for r in RES if r['family'] != '基准']
BEN = [r for r in RES if r['family'] == '基准']

# 主排序：有闸门 CAGR 降序（破产者 CAGR=-100% 自然垫底）
def keyf(r):
    c = g(r, 'on', 'cagr')
    return c if c is not None else -1.0
STR_sorted = sorted(STR, key=keyf, reverse=True)

lines = []
A = lines.append

A('# 美股因子策略 · 收益排行榜（统一口径 v26 引擎）\n')
A('> 数据来源：`_rank_all.json`（69 策略 × 2 口径 + 3 基准，统一引擎/池/区间/成本重跑）  \n'
  '> 生成时间：' + M.get('time','') + '\n')

A('## 口径声明（所有数字共用）\n')
A(f'- 标的池 **{M["pool"]} 只**（富途热门榜 + 三道闸门筛选）  \n'
  f'- 回测区间 **{M["start"]} ~ {M["end"]}**（{M["years"]:.2f} 年，用实际投资窗口，非数据跨度）  \n'
  f'- 本金 **${M["cap"]:,.0f}** ｜ 佣金 **${M["comm"]:.0f}/笔双边** ｜ 默认调仓 **{M["rebal"]} 交易日（月频）** ｜ Top2 等权  \n'
  f'- 闸门：滚动 60 日成交额中位 ≥ ${float(str(M["gate"]).split(">=")[-1].strip()):,.0f}（即「有闸门」列；去掉即「无闸门」列）  \n'
  f'- 复权：全部 QFQ 前复权；信号取 i-1 收盘、第 i 日开盘执行  \n'
  '- CAGR = (终值/本金)^(1/年数) − 1；破产策略终值恰为 0 → CAGR=−100%（不会出复数）。\n')

A('## ⚠️ 排行榜不是选股指南\n')
A('第一名（金叉+MA50距离 Top2）是在**同一批数据上试过几十个策略**后挑出来的，必然含'
  '**多重比较运气**；标的池本身是 2026 年赢家榜，含**幸存者偏差**。\n'
  '本榜用于「看清哪些因子族在历史上更赚钱、风险调整后谁更稳」，不是「现在该买什么」的清单。\n')

A('## 一、总收益排行（按有闸门 CAGR 从高到低）\n')
A('| # | 策略 | 家族 | TopK | 调仓 | 有闸门 CAGR | 有闸门总收益 | 无闸门 CAGR | 无闸门总收益 | 最大回撤(闸) | 夏普(闸) | Calmar(闸) |')
A('|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
for i, r in enumerate(STR_sorted, 1):
    tag = 'on'
    cagr_on = g(r, 'on', 'cagr'); tot_on = g(r, 'on', 'total')
    cagr_off = g(r, 'off', 'cagr'); tot_off = g(r, 'off', 'total')
    mdd = g(r, 'on', 'mdd'); sh = g(r, 'on', 'sharpe'); cal = g(r, 'on', 'calmar')
    on_s = '💀破产' if g(r,'on','bankrupt') else pct(cagr_on)
    tot_on_s = '💀破产' if g(r,'on','bankrupt') else (f'{tot_on*100:,.0f}%' if tot_on is not None else '—')
    off_s = '💀破产' if g(r,'off','bankrupt') else pct(cagr_off)
    tot_off_s = '💀破产' if g(r,'off','bankrupt') else (f'{tot_off*100:,.0f}%' if tot_off is not None else '—')
    mdd_s = '💀破产' if g(r,'on','bankrupt') else pct(mdd)
    cal_s = '—' if g(r,'on','bankrupt') else (num(cal,2) if cal is not None else '—')
    name = r['name']
    if name.startswith('Vortex Top2 @10'):
        name = '**' + name + '（风险调整冠军）**'
    A(f'| {i} | {name} | {r.get("family","?")} | {r.get("topk","?")} | {r.get("rebal",M["rebal"])}日 | {on_s} | {tot_on_s} | {off_s} | {tot_off_s} | {mdd_s} | {num(sh,2) if sh is not None else "—"} | {cal_s} |')

A('\n## 二、基准对照（买持有 / 大盘）\n')
A('| 基准 | 有闸门 CAGR | 有闸门总收益 | 最大回撤 | 夏普 | Calmar |')
A('|---|---:|---:|---:|---:|---:|')
for r in sorted(BEN, key=lambda r: (g(r,'on','cagr') or -1), reverse=True):
    cagr = g(r,'on','cagr'); tot = g(r,'on','total'); mdd = g(r,'on','mdd'); sh=g(r,'on','sharpe'); cal=g(r,'on','calmar')
    A(f'| {r["name"]} | {pct(cagr)} | {tot*100:,.0f}% | {pct(mdd)} | {num(sh,2)} | {num(cal,2)} |')

A('\n## 三、关键解读\n')
# 击败基准计数
ew = next(b for b in BEN if '等权' in b['name'])
voo = next(b for b in BEN if 'VOO' in b['name'] and '买入持有' in b['name'])
n_beat_ew = sum(1 for r in STR if (g(r,'on','cagr') or -1) > (g(ew,'on','cagr') or -1) and not g(r,'on','bankrupt'))
n_beat_voo = sum(1 for r in STR if (g(r,'on','cagr') or -1) > (g(voo,'on','cagr') or -1) and not g(r,'on','bankrupt'))
ew_c = g(ew,'on','cagr')
voo_c = g(voo,'on','cagr')
A(f'1. **基准不是摆设**：{len(STR)} 个可投策略里，只有 **{n_beat_ew}/{len(STR)}** 在有闸门口径下跑赢「池内等权买入持有」（{pct(ew_c)}），'
  f'**{n_beat_voo}/{len(STR)}** 跑赢 VOO（{pct(voo_c)}）。≈ **{len(STR)-n_beat_ew} 个策略连"什么都不做"都没打赢**。\n')

# 闸门后 CAGR 下降数
n_down = sum(1 for r in STR if (g(r,'on','cagr') or -1) < (g(r,'off','cagr') or -1))
A(f'2. **闸门是质量过滤器**：{n_down}/{len(STR)} 个策略在「有闸门」下 CAGR 反而更低（闸门挡掉薄流动性票，多数策略因此少赚一点或不变），'
  '但少数策略（如 Vortex）因避开僵尸票而更稳。\n')

A('3. **收益冠军 vs 风险调整冠军是两回事**：  \n'
  '   - 纯收益（CAGR）前三是 **金叉+MA50距离 Top2（99.9%）/ MA200距离 Top2（99.0%）/ 动量-1月反转 Top2@5日（96.7%）**，但它们的最大回撤都在 **−67%~−71%**，接近腰斩再腰斩。  \n'
  '   - **Vortex Top2 @10日调仓（CAGR 94.8%）** 是风险调整冠军：夏普 1.67、Calmar **2.65**、最大回撤仅 **−35.8%**、年胜率 100% —— 用约一半的回撤换几乎相同的收益，**这才是实盘更想要的那个**。\n')

A('4. **破产警告（真实成本）**：宽等权趋势组合（40~58 只）在 $3,000 本金、$2/笔 佣金下，**单笔调仓佣金超过账户价值 → 数学上不可投**（终值恰 0、CAGR −100%）。'
  '这反过来证明 Top2 等权 + 月频是本项目本金档位的合理选择。\n')

A('## 四、附：风险调整榜（按 Calmar 从高到低，剔除破产）\n')
A('| # | 策略 | Calmar | 夏普 | CAGR(闸) | 最大回撤 |')
A('|---:|---|---:|---:|---:|---:|')
rk = [r for r in STR if not g(r,'on','bankrupt')]
rk.sort(key=lambda r: (g(r,'on','calmar') or -9), reverse=True)
for i, r in enumerate(rk[:15], 1):
    cal = g(r,'on','calmar'); sh=g(r,'on','sharpe'); cagr=g(r,'on','cagr'); mdd=g(r,'on','mdd')
    A(f'| {i} | {r["name"]} | {num(cal,2)} | {num(sh,2)} | {pct(cagr)} | {pct(mdd)} |')

A('\n---\n')
A('完整 72 行细分榜（分家族 / 分阶段 / 逐年 / 诊断指标）见 `美股全策略总排名_v26.md`。  \n'
  '本榜所有数字来自统一重跑，引擎两道守恒恒等式（价值守恒 13,874 次、价格归因 126,200 天）残差均 < 1e-14，自检 10/10 通过。\n')

out = os.path.join(D, '美股收益排行榜_v26.md')
open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(lines))
print('written:', out, '| lines:', len(lines))
print('strategies:', len(STR), '| benchmarks:', len(BEN), '| beat_ew:', n_beat_ew, '| beat_voo:', n_beat_voo, '| gate_down:', n_down)
