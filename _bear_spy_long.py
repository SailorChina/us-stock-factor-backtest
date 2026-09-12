# -*- coding: utf-8 -*-
"""
v14b 用 SPY 长历史 (2006-08 ~ 2026-09, 含 2008 金融危机 / 2011 / 2015-16 / 2018Q4 / 2020 / 2022)
检验: 指数择时到底能不能避开熊市? 躲开的钱 vs 牛市踏空的钱, 哪个多?
避险去向对比: 空持现金 / TLT长债 / GLD黄金 / SHY短债
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
IDIR = os.path.join(BASE, "data_index_long")

def rd(code):
    d = pd.read_csv(os.path.join(IDIR, "US_" + code + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    return d.sort_values("time_key").reset_index(drop=True).set_index("time_key")

S = {c: rd(c) for c in ["SPY", "TLT", "GLD", "SHY"]}
dp = S["SPY"].index
C = {c: S[c]["close"].reindex(dp).ffill().values for c in S}
N = len(dp)
CAP0 = 3000.0

def ma(x, n):
    return pd.Series(x, index=dp).rolling(n).mean().values
def above(x, n):
    m = ma(x, n); return (x > m) & np.isfinite(m)
def cross(x, f=50, s=200):
    a = ma(x, f); b = ma(x, s); return (a > b) & np.isfinite(b)
def confirm(x, n, k):
    a = above(x, n); m = ma(x, n); out = a.copy(); c = 0
    for i in range(len(a)):
        if not np.isfinite(m[i]): out[i] = False; continue
        c = c+1 if not a[i] else 0
        out[i] = not (c >= k)
    return out

SPY = C["SPY"]
REG = {
    "SPY 200DMA": above(SPY, 200),
    "SPY 200DMA+连5天确认": confirm(SPY, 200, 5),
    "SPY 50/200 金叉死叉": cross(SPY),
    "SPY 100DMA": above(SPY, 100),
    "SPY 50DMA": above(SPY, 50),
}

def run(flag, safe=None):
    """flag: 收盘判定(T日); T+1开盘成交. safe=None持现金, 否则为避险资产代码"""
    eq = np.empty(N); cash = CAP0; sh_spy = 0.0; sh_sf = 0.0
    pend = None; inm = 0
    for i in range(N):
        op = {c: S[c]["open"].reindex(dp).ffill().values[i] for c in (["SPY"] + ([safe] if safe else []))}
        if pend is not None:
            tgt = pend
            if sh_spy > 0:
                cash += sh_spy*op["SPY"] - 0.0; sh_spy = 0.0
            if sh_sf > 0:
                cash += sh_sf*op[safe]; sh_sf = 0.0
            if tgt:
                sh_spy = cash/op["SPY"]; cash = 0.0
            else:
                if safe: sh_sf = cash/op[safe]; cash = 0.0
        pend = None
        eq[i] = cash + sh_spy*SPY[i] + (sh_sf*(C[safe][i]) if safe and sh_sf > 0 else 0.0)
        if flag[i]: inm += 1
        nxt = bool(flag[i])
        if i == 0: continue
        cur = (sh_spy > 0)
        if nxt != cur: pend = nxt
    return eq, inm

def mdd(eq):
    v = eq[200:]; return ((v-np.maximum.accumulate(v))/np.maximum.accumulate(v)).min()*100
def cagr(eq): return ((eq[-1]/CAP0)**(1/((N-200)/252.0))-1)*100
def seg(eq, s, e):
    m = (dp >= pd.Timestamp(s)) & (dp <= pd.Timestamp(e)); idx = np.where(m)[0]
    if len(idx) < 2: return None
    a, b = idx[0], idx[-1]
    v = eq[a:b+1]; sub = (v-np.maximum.accumulate(v))/np.maximum.accumulate(v)
    return (v[-1]/v[0]-1)*100, sub.min()*100

eq_bh = SPY/SPY[200]*CAP0
eq_bh = np.concatenate([np.full(200, CAP0), eq_bh[200:]])

PHASES = [("2007顶->2009底 金融危机","2007-10-09","2009-03-09","熊"),
          ("2009-2011 复苏牛","2009-03-10","2011-04-29","牛"),
          ("2011 欧债回落","2011-05-02","2011-10-03","熊"),
          ("2011-2015 牛市","2011-10-04","2015-05-21","牛"),
          ("2015-16 调整","2015-05-22","2016-02-11","熊"),
          ("2016-2018 牛市","2016-02-12","2018-09-20","牛"),
          ("2018 Q4 回落","2018-09-21","2018-12-24","熊"),
          ("2019-2020.2 牛市","2018-12-25","2020-02-19","牛"),
          ("2020 疫情崩盘","2020-02-19","2020-03-23","熊"),
          ("2020-2021 牛市","2020-03-24","2021-12-31","牛"),
          ("2022 熊市","2022-01-03","2022-10-12","熊"),
          ("2023-2026 牛市","2022-10-13","2026-09-10","牛")]

print("="*132)
print("A. SPY 长历史 (2006-08 ~ 2026-09, 20年) 择时 vs 买入持有")
print("="*132)
rows = [("SPY 买入持有(基准)", eq_bh)]
for rn, fl in REG.items():
    for an, sf in [("空仓", None), ("持TLT长债", "TLT"), ("持GLD黄金", "GLD"), ("持SHY短债", "SHY")]:
        e, im = run(fl, sf); rows.append((f"{rn} -> {an}", e, im))
print(f"{'方案':<30}{'终值':>12}{'CAGR':>8}{'最大回撤':>10}{'在场比例':>10}")
print("-"*132)
for r in rows:
    nm, e = r[0], r[1]; im = r[2] if len(r) > 2 else N-200
    print(f"{nm:<30}${e[-1]:>10,.0f}{cagr(e):>+7.1f}%{mdd(e):>9.1f}%{im/(N-200)*100:>9.0f}%")

print()
print("="*132)
print("B. 各牛熊分段收益 (括号内为区间内最大回撤)")
print("="*132)
hdr = f"{'阶段':<26}{'性质':>4}"
named = [("SPY买入持有", eq_bh)]
for rn in ["SPY 200DMA", "SPY 50/200 金叉死叉"]:
    for an, sf in [("空仓", None), ("持TLT长债", "TLT")]:
        named.append((f"{rn}->{an}", run(REG[rn], sf)[0]))
print(hdr + "".join(f"{n[:13]:>17}" for n, _ in named))
print("-"*132)
for nm, s, e, kind in PHASES:
    line = f"{nm:<26}{kind:>4}"
    for _, eq in named:
        r = seg(eq, s, e)
        line += f"{f'{r[0]:+.0f}% ({r[1]:.0f}%)':>17}" if r else f"{'-':>17}"
    print(line)
print("-"*132)
line = f"{'全程':<26}{'':>4}"
for _, eq in named:
    line += f"{(eq[-1]/CAP0-1)*100:>+16.0f}% "
print(line)

print()
print("="*132)
print("C. 熊市段合计: 择时躲开了多少钱?  牛市段合计: 又踏空了多少钱?")
print("="*132)
bears = [(n, s, e) for n, s, e, k in PHASES if k == "熊"]
bulls = [(n, s, e) for n, s, e, k in PHASES if k == "牛"]
print(f"{'方案':<30}{'熊市段累计(复利)':>18}{'牛市段累计(复利)':>18}{'熊市少亏(相对基准)':>20}")
print("-"*132)
def comp(eq, segs):
    v = 1.0
    for n, s, e in segs:
        r = seg(eq, s, e)
        if r: v *= (1+r[0]/100)
    return (v-1)*100
bb = comp(eq_bh, bears); bu = comp(eq_bh, bulls)
print(f"{'SPY 买入持有(基准)':<30}{bb:>+17.0f}%{bu:>+17.0f}%{'-':>20}")
for rn in ["SPY 200DMA", "SPY 50/200 金叉死叉"]:
    for an, sf in [("空仓", None), ("持TLT长债", "TLT"), ("持GLD黄金", "GLD")]:
        e = run(REG[rn], sf)[0]
        b2 = comp(e, bears); b3 = comp(e, bulls)
        save = ((1+b2/100)/(1+bb/100)-1)*100
        print(f"{rn+' -> '+an:<30}{b2:>+17.0f}%{b3:>+17.0f}%{save:>+19.0f}%")
print()
print("(熊市少亏为正 = 择时确实少亏了; 需与'牛市段累计'对比看代价)")

print()
print("="*132)
print("D. 择时信号的滞后成本: 每次熊市从顶点到发出离场信号, 已经跌了多少")
print("="*132)
print(f"{'熊市区间':<26}{'顶点日':<12}{'离场信号日':<13}{'滞后':>7}{'信号时已跌':>12}{'熊市全程跌幅':>14}{'躲开比例':>10}")
print("-"*132)
for rn in ["SPY 200DMA", "SPY 50/200 金叉死叉"]:
    fl = REG[rn]; ev = []; i = 201
    while i < N:
        if not fl[i] and fl[i-1]:
            j = i
            while j < N and not fl[j]: j += 1
            ev.append((i, j)); i = j
        else: i += 1
    print(f"--- {rn} (共 {len(ev)} 次离场, 累计离场 {sum(b-a for a,b in ev)} 日 = {sum(b-a for a,b in ev)/(N-201)*100:.0f}%) ---")
    wrong = sum(1 for a, b in ev if (SPY[b]/SPY[a]-1) > 0)
    for n, s, e in bears:
        m = (dp >= pd.Timestamp(s)) & (dp <= pd.Timestamp(e)); idx = np.where(m)[0]
        if len(idx) < 2: continue
        a0, b0 = idx[0], idx[-1]; pk = a0+int(np.argmax(SPY[a0:b0+1]))
        sig = next((a for a, b in ev if a0 <= a <= b0), None)
        full = (SPY[b0]/SPY[pk]-1)*100
        if sig is None:
            print(f"{n:<26}{str(dp[pk].date()):<12}{'无信号':<13}{'-':>7}{'-':>12}{full:>+13.1f}%{0:>9.0f}%")
        else:
            lost = (SPY[sig]/SPY[pk]-1)*100
            saved = (1-lost/100)/(1-full/100)-1 if full < 0 else 0
            print(f"{n:<26}{str(dp[pk].date()):<12}{str(dp[sig].date()):<13}{(sig-pk):>6d}日{lost:>+11.1f}%{full:>+13.1f}%{saved*100:>9.0f}%")
    print(f"   假信号率: 离场期间SPY反而上涨 {wrong}/{len(ev)} = {wrong/len(ev)*100:.0f}%")
    print()

json.dump({"A": {nm: float(e[-1]) for nm, e, *_ in rows}},
          open(os.path.join(BASE, "_bear_spy_long.json"), "w"), ensure_ascii=False, indent=2)
print("SAVED _bear_spy_long.json")
