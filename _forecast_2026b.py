# -*- coding: utf-8 -*-
"""
v15b 补充: 实时信号 / 整股可行性 / 波动率压缩情景 / 牛市转熊压力测试
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
FX = 6.7092; CNY0 = 10000.0; CAP0 = CNY0/FX; HORIZON = 76; START = 252

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
_, vp = load(["US.VOO"]); VOO = vp["close"]["US.VOO"].values
dfH, dfL, dfC = [pd.DataFrame(x, index=dp, columns=CODES) for x in (H, L, C)]
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift(); tr = np.maximum(np.maximum(h-lo, (h-pc).abs()), (lo-pc).abs())
    return ((h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
            - (lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum())
mom12_1 = dfC.shift(21)/dfC.shift(252)-1.0
rev1 = dfC/dfC.shift(21)-1.0
SIG = {"Vortex": vortex(dfH, dfL, dfC), "动量-1月反转": (zs(mom12_1)-zs(rev1))/2.0}

def backtest(score, topk=2, cap=CAP0, slip=0.0005, frac=True):
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    comm = lambda sh: max(abs(sh)*0.005, 1.0) if abs(sh) > 0 else 0.0
    cash = cap; pos = {}; pend = None; eq = []
    def allocate(picks, op_i):
        nonlocal cash
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*op_i[c]*(1-slip) - comm(sh)
        total = cash; n = len(picks)
        for k, c in enumerate(picks):
            slots = n-k; bud = total/slots if slots > 0 else 0
            pr = op_i[c]*(1+slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = bud/pr
            if not frac: sh = int(sh)
            cost = sh*pr + comm(sh); guard = 0
            while cost > cash and sh > 0 and guard < 60:
                sh *= 0.995; cost = sh*pr + comm(sh); guard += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh*pr
    last_pick = None
    for i in range(N):
        co = C[i]; op = O[i]
        if pend is not None: allocate(pend, op); pend = None
        eq.append(cash + sum(pos.get(c, 0)*co[c] for c in pos))
        if i >= START and (i-START) % 21 == 0:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                pick = list(idx[np.argsort(-row[idx])][:topk])
                if pick != last_pick or last_pick is None:
                    pend = pick; last_pick = pick
    return np.array(eq)

i = N-1
ma200 = pd.Series(VOO, index=dp).rolling(200).mean().values
bull = (VOO > ma200) & np.isfinite(ma200)
r_voo = pd.Series(VOO, index=dp).pct_change()
vol21 = (r_voo.rolling(21).std()*np.sqrt(252)).values
vmed = np.nanmedian(vol21[START:]); v20 = np.nanpercentile(vol21[START:], 20)

print("="*128)
print("[A] 实时信号: 用 2026-09-10 收盘数据算, 2026-09-14(周一)开盘执行")
print("="*128)
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    for tk in [2, 3]:
        row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
        pick = list(idx[np.argsort(-row[idx])][:tk])
        bud = CAP0/tk
        print(f"\n  {nm} Top{tk}   (每只预算 ${bud:,.0f})")
        for c in pick:
            col = dfC.columns[c]; nm_c = CODES[c].replace("US.","")
            pr = C[i, c]
            p1 = dfC[col].iloc[i]/dfC[col].iloc[i-21]-1
            p3 = dfC[col].iloc[i]/dfC[col].iloc[i-63]-1
            p12 = dfC[col].iloc[i]/dfC[col].iloc[i-252]-1
            shares_f = bud/pr; shares_i = int(bud//pr)
            flag = "" if shares_i >= 1 else "   <-- 整股买不起1股!"
            print(f"     {nm_c:<6} ${pr:>9.2f}  近1月{p1*100:>+6.1f}% 近3月{p3*100:>+6.1f}% 近1年{p12*100:>+7.0f}%"
                  f"   碎股{shares_f:.3f}股 / 整股{shares_i}股{flag}")

print("\n" + "="*128)
print("[B] 整股约束的影响 (若券商不支持碎股, 小资金会被高价股卡住)")
print("="*128)
print(f"{'策略':<26}{'碎股8.7年':>16}{'整股8.7年':>16}{'差异':>12}")
print("-"*128)
for nm in SIG:
    for tk in [2, 3]:
        ef = backtest(SIG[nm], topk=tk, frac=True)
        ei = backtest(SIG[nm], topk=tk, frac=False)
        a = (ef[-1]/CAP0-1)*100; b = (ei[-1]/CAP0-1)*100
        print(f"{nm+' Top'+str(tk):<26}{a:>+15.0f}%{b:>+15.0f}%{b-a:>+11.0f}pp")

print("\n" + "="*128)
print("[C] 波动率压缩情景: 起点波动率极低(<20分位)时, 之后76天会怎样")
print("="*128)
low_vol = np.zeros(N, bool); low_vol[START:] = vol21[START:] < v20
print(f"  当前 VOO 21日年化波动率 {vol21[i]*100:.1f}% | 历史中位 {vmed*100:.1f}% | 20分位 {v20*100:.1f}%"
      f"  -> {'属于低波动压缩期' if vol21[i] < v20 else '不属于'}")
print(f"{'起点状态':<28}{'样本':>7}{'5%':>10}{'25%':>10}{'中位':>10}{'75%':>10}{'95%':>10}{'为正概率':>10}")
print("-"*128)
EQ = {f"{nm} Top{tk}": backtest(SIG[nm], topk=tk)
      for nm in SIG for tk in [2, 3]}
def roll(eq, h=HORIZON, mask=None):
    return np.array([eq[a+h]/eq[a]-1 for a in range(START, N-h)
                     if mask is None or mask[a]])
for label, mask in [("低波动起点(<20分位)", low_vol), ("高波动起点(>80分位)", None)]:
    if label.startswith("高"):
        hi80 = np.zeros(N, bool); hi80[START:] = vol21[START:] > np.nanpercentile(vol21[START:], 80)
        mask = hi80
    for nm in ["Vortex Top2", "动量-1月反转 Top2"]:
        r = roll(EQ[nm], mask=mask)
        if len(r) < 10: continue
        q = np.percentile(r, [5,25,50,75,95])
        print(f"{label+' | '+nm:<28}{len(r):>7}" + "".join(f"{CNY0*(1+x):>9,.0f}元" for x in q)
              + f"{(r>0).mean()*100:>9.0f}%")

print("\n" + "="*128)
print("[D] 压力测试: 起点在牛市, 但随后 76 天内 VOO 跌破 200 日均线 (最贴近当前风险)")
print("="*128)
turn = np.zeros(N, bool)
for a in range(START, N-HORIZON):
    if bull[a] and np.any(~bull[a:a+HORIZON]):
        turn[a] = True
print(f"  符合条件的窗口: {turn.sum()} 个")
print(f"{'策略':<26}{'样本':>7}{'5%':>11}{'25%':>11}{'中位':>11}{'75%':>11}{'95%':>11}{'为正概率':>10}")
print("-"*128)
for nm, eq in EQ.items():
    r = roll(eq, mask=turn)
    if len(r) < 5: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}" + "".join(f"{CNY0*(1+x):>10,.0f}元" for x in q) + f"{(r>0).mean()*100:>9.0f}%")
s0 = np.nan_to_num(C[START], nan=0.0); ok0 = s0 > 0
w = np.where(ok0, 1.0/ok0.sum(), 0.0); sh0 = CAP0*w/np.where(ok0, s0, 1.0)
eq_bh = np.full(N, CAP0); eq_bh[START:] = (np.nan_to_num(C, nan=0.0)@sh0)[START:]
eq_voo = np.concatenate([np.full(START, CAP0), VOO[START:]/VOO[START]*CAP0])
for nm, eq in [("等权全买37只", eq_bh), ("VOO 指数", eq_voo)]:
    r = roll(eq, mask=turn)
    if len(r) < 5: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}" + "".join(f"{CNY0*(1+x):>10,.0f}元" for x in q) + f"{(r>0).mean()*100:>9.0f}%")

print("\n" + "="*128)
print("[E] 单月最坏情况: 历史上任意 21 天窗口的最差表现 (本金 $1,490)")
print("="*128)
print(f"{'策略':<26}{'最差21天':>12}{'发生时':>14}{'最差63天':>12}{'最差76天':>12}")
print("-"*128)
for nm, eq in list(EQ.items()) + [("等权全买37只", eq_bh), ("VOO 指数", eq_voo)]:
    def worst(h):
        best = (1e9, None)
        for a in range(START, N-h):
            v = eq[a+h]/eq[a]-1
            if v < best[0]: best = (v, a)
        return best
    w21, a21 = worst(21); w63, _ = worst(63); w76, _ = worst(76)
    print(f"{nm:<26}{w21*100:>+11.1f}%{str(dp[a21].date()):>14}{w63*100:>+11.1f}%{w76*100:>+11.1f}%")
