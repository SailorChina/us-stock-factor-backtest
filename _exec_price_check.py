# -*- coding: utf-8 -*-
"""
补测: 回测按【次日开盘价】成交, 但策略选的是强势股, 会不会系统性高开低走 -> 开盘买吃亏?
对比三种成交假设:
  A 次日开盘价买 (回测现状)
  B 次日收盘价买 (信号日 T 收盘判定, T+1 收盘下单)
  C 次日开盘买 vs 当日收盘 的日内收益 (衡量"高开低走"程度)
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
CAP0 = 10000.0/6.7092; COMM = 2.0; START = 252

def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]
def load(codes):
    p = {}
    for c in codes:
        d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").reset_index(drop=True).set_index("time_key")
    ad = sorted(set().union(*[set(x.index) for x in p.values()])); dt = pd.to_datetime(ad)
    return dt, {k: pd.DataFrame({c: p[c][k].reindex(dt).ffill() for c in codes})
                for k in ["open","high","low","close","volume"]}
dates, PX = load(UNI); CODES = UNI
C = PX["close"].values; O = PX["open"].values; H = PX["high"].values; L = PX["low"].values
N, S = C.shape; dp = pd.to_datetime(dates)
dfH, dfL, dfC = [pd.DataFrame(x, index=dp, columns=CODES) for x in (H, L, C)]
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift(); tr = np.maximum(np.maximum(h-lo, (h-pc).abs()), (lo-pc).abs())
    return ((h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
            - (lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum())
mom12_1 = dfC.shift(21)/dfC.shift(252)-1.0
rev1 = dfC/dfC.shift(21)-1.0
SIG = {"Vortex": vortex(dfH, dfL, dfC), "动量-1月反转": (zs(mom12_1)-zs(rev1))/2.0}

print("="*124)
print("[1] 策略买入的票, 在买入当天是否【高开低走】? (开盘买 -> 当日收盘)")
print("="*124)
print(f"{'策略':<20}{'样本':>6}{'5%':>10}{'25%':>10}{'中位':>10}{'75%':>10}{'95%':>10}{'均值':>10}")
print("-"*124)
RB = [i for i in range(N) if i >= START and (i-START) % 21 == 0]
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    intraday = []
    for j in RB[:-1]:
        row = A[j]; ok = np.isfinite(row); idx = np.where(ok)[0]
        if len(idx) == 0: continue
        pick = list(idx[np.argsort(-row[idx])][:2])
        k = j+1
        if k >= N: continue
        for c in pick:
            if np.isfinite(O[k, c]) and np.isfinite(C[k, c]) and O[k, c] > 0:
                intraday.append(C[k, c]/O[k, c]-1)
    g = np.array(intraday)
    q = np.percentile(g, [5, 25, 50, 75, 95])
    print(f"{nm:<20}{len(g):>6}" + "".join(f"{v*100:>+9.2f}%" for v in q) + f"{g.mean()*100:>+9.3f}%")
print("\n  解读: 若中位为负 = 高开低走, 开盘买吃亏; 为正 = 开盘后继续涨, 开盘买划算。")
print("        注意: 这不是成本, 是'择时日内哪个时点下注'的偏好差异。")

print("\n" + "="*124)
print("[2] 开盘成交 vs 收盘成交: 8.7 年终值对比 (真实佣金 $2/笔)")
print("="*124)
def backtest(score, topk=2, cap=CAP0, slip=0.0005, use_open=True):
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    cf = lambda sh: COMM if abs(sh) > 0 else 0.0
    cash = cap; pos = {}; pend = None; eq = []; last = None
    def alloc(picks, px):
        nonlocal cash
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*px[c]*(1-slip) - cf(sh)
        total = cash; n = len(picks)
        for k, c in enumerate(picks):
            slots = n-k; bud = total/slots if slots > 0 else 0
            pr = px[c]*(1+slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = bud/pr; cost = sh*pr + cf(sh); guard = 0
            while cost > cash and sh > 0 and guard < 60:
                sh *= 0.995; cost = sh*pr + cf(sh); guard += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh*pr
    for i in range(N):
        px = (O[i] if use_open else C[i])
        if pend is not None: alloc(pend, px); pend = None
        eq.append(cash + sum(pos.get(c, 0)*C[i][c] for c in pos))
        if i >= START and (i-START) % 21 == 0:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                pick = list(idx[np.argsort(-row[idx])][:topk])
                if pick != last or last is None: pend = pick; last = pick
    return np.array(eq)
print(f"{'策略':<20}{'次日开盘成交(现状)':>20}{'次日收盘成交':>18}{'差异':>12}")
print("-"*124)
for nm in SIG:
    eo = backtest(SIG[nm], use_open=True)
    ec = backtest(SIG[nm], use_open=False)
    a = (eo[-1]/CAP0-1)*100; b = (ec[-1]/CAP0-1)*100
    print(f"{nm:<20}{a:>+19.0f}%{b:>+17.0f}%{b-a:>+11.0f}pp")
print("\n  注: '次日收盘成交' 需要你等到收盘才知道价格并下单, 实务上更难精确执行, 仅作对照。")

print("\n" + "="*124)
print("[3] 9/14 开盘价的预期区间 (基于 9/11 收盘 + 历史跳空分布)")
print("="*124)
i = N-1
j = None
for nm in ["US.META", "US.BE", "US.MU", "US.LITE", "US.DELL", "US.COHR"]:
    if nm in CODES:
        c = CODES.index(nm); j = c
        p = C[i, c]
        print(f"\n  {nm.replace('US.',''):<6} 9/11 收盘 ${p:,.2f}")
        print(f"     9/14 开盘预期:  悲观(5%) ${p*(1-0.0359):,.2f} | 较可能(25~75%) "
              f"${p*(1-0.0063):,.2f}~${p*(1+0.0115):,.2f} | 中位 ${p*(1+0.0028):,.2f} | "
              f"乐观(95%) ${p*(1+0.0375):,.2f}")
print("\n  (跳空分位数取自 Vortex 策略历史实际买入票的 182 个样本)")

print("\n" + "="*124)
print("[4] 按 9/11 收盘价, $1,490 本金的整股可行性")
print("="*124)
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    for tk in [2, 3]:
        row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
        pick = list(idx[np.argsort(-row[idx])][:tk])
        bud = CAP0/tk
        tot = 0; parts = []
        for c in pick:
            p = C[i, c]; n = int(bud//p); tot += n*p
            parts.append(f"{CODES[c].replace('US.','')} {n}股=${n*p:,.0f}")
        print(f"  {nm} Top{tk}: {' + '.join(parts)} = ${tot:,.0f} / ${CAP0:,.0f} "
              f"(投入 {tot/CAP0*100:.0f}%, 闲置 ${CAP0-tot:,.0f})")
