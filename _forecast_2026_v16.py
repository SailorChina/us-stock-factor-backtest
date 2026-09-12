# -*- coding: utf-8 -*-
"""
v16  富途真实佣金: 买入 $2/笔, 卖出 $2/笔 (固定, 不分股数)

之前用的 max(0.005/股, $1) 严重低估成本。固定 $2/笔 对小资金是硬成本:
  每只票 卖出$2 + 买入$2 = $4
  Top2 每次调仓 = 2卖+2买 = $8 ; Top3 = $12
  76 个交易日(4次调仓): Top2 $32 = 本金 2.15% ; Top3 $48 = 3.22%

本脚本:
  1) 用真实佣金重跑 8.7 年历史
  2) 调仓频率敏感性: 21 / 42 / 63 天 (降低频率能否省出成本)
  3) 重算 76 天分布与人民币结果
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

FX = 6.7092; CNY0 = 10000.0; CAP0 = CNY0/FX; HORIZON = 76; START = 252
COMM = 2.0          # 富途: 每笔固定 $2 (买/卖各计一笔)

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

# ================= 引擎: 佣金可切换 =================
def backtest(score, topk=2, cap=CAP0, rebal=21, slip=0.0005, comm_fixed=COMM, count_cost=True):
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    cf = (lambda sh: comm_fixed if abs(sh) > 0 else 0.0) if count_cost else (lambda sh: 0.0)
    cash = cap; pos = {}; pend = None; eq = []; ntrade = 0
    def allocate(picks, op_i):
        nonlocal cash, ntrade
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*op_i[c]*(1-slip) - cf(sh); ntrade += 1
        total = cash; n = len(picks)
        for k, c in enumerate(picks):
            slots = n-k; bud = total/slots if slots > 0 else 0
            pr = op_i[c]*(1+slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = bud/pr; cost = sh*pr + cf(sh); guard = 0
            while cost > cash and sh > 0 and guard < 60:
                sh *= 0.995; cost = sh*pr + cf(sh); guard += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh*pr; ntrade += 1
    last_pick = None
    for i in range(N):
        co = C[i]; op = O[i]
        if pend is not None: allocate(pend, op); pend = None
        eq.append(cash + sum(pos.get(c, 0)*co[c] for c in pos))
        if i >= START and (i-START) % rebal == 0:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                pick = list(idx[np.argsort(-row[idx])][:topk])
                if pick != last_pick or last_pick is None:
                    pend = pick; last_pick = pick
    return np.array(eq), ntrade

def buy_hold_all(cap=CAP0, slip=0.0005, comm_fixed=COMM):
    s0 = np.nan_to_num(C[START], nan=0.0); ok0 = s0 > 0
    w = np.where(ok0, 1.0/ok0.sum(), 0.0)
    sh = cap*w*(1-slip)/np.where(ok0, s0, 1.0)
    # 建仓只收一次买入佣金 (按笔数计, 这里按 37 笔近似)
    e = np.full(N, cap - comm_fixed*ok0.sum()); e[START:] = (np.nan_to_num(C, nan=0.0)@sh)[START:]
    return e
eq_bh = buy_hold_all()
eq_voo = np.concatenate([np.full(START, CAP0), VOO[START:]/VOO[START]*CAP0])

ma200 = pd.Series(VOO, index=dp).rolling(200).mean().values
bull = (VOO > ma200) & np.isfinite(ma200)
def mdd(eq):
    v = eq[START:]; return ((v-np.maximum.accumulate(v))/np.maximum.accumulate(v)).min()*100
def roll(eq, h=HORIZON, mask=None):
    return np.array([eq[a+h]/eq[a]-1 for a in range(START, N-h) if mask is None or mask[a]])
def val(q, base=CNY0):
    return "".join(f"{base*(1+x):>11,.0f}元" for x in q)

print("="*132)
print(f"富途真实佣金: 每笔固定 $2 (买/卖各计一笔) | 本金 ¥{CNY0:,.0f} = ${CAP0:,.2f} | 汇率 {FX}")
print(f"持有期 {HORIZON} 个交易日")
print("="*132)

print("\n[1] 单次调仓成本")
print(f"{'持股数':<8}{'每次调仓笔数':>12}{'每次成本':>10}{'76天内约4次':>14}{'占本金':>10}")
print("-"*132)
for tk in [1, 2, 3, 4]:
    per = 2*tk*COMM      # 卖 tk 笔 + 买 tk 笔
    tot = per*4
    print(f"Top{tk:<5}{2*tk:>12}{'$'+format(per,'.0f'):>10}{'$'+format(tot,'.0f'):>14}{tot/CAP0*100:>9.2f}%")

print("\n[2] 佣金模型对 8.7 年历史的影响 (本金 $1,490)")
print(f"{'策略':<26}{'旧模型(最低$1)':>16}{'真实($2/笔)':>16}{'差异':>12}{'回撤':>10}")
print("-"*132)
EQ_NEW = {}
for nm in SIG:
    for tk in [2, 3]:
        e_old, _ = backtest(SIG[nm], topk=tk, comm_fixed=1.0)   # 近似旧模型下限
        e_new, nt = backtest(SIG[nm], topk=tk, comm_fixed=COMM)
        EQ_NEW[f"{nm} Top{tk}"] = e_new
        a = (e_old[-1]/CAP0-1)*100; b = (e_new[-1]/CAP0-1)*100
        print(f"{nm+' Top'+str(tk):<26}{a:>+15.0f}%{b:>+15.0f}%{b-a:>+11.0f}pp{mdd(e_new):>9.1f}%")
EQ_NEW["等权全买37只"] = eq_bh; EQ_NEW["VOO 指数"] = eq_voo
print(f"{'等权全买37只':<26}{'-':>16}{(eq_bh[-1]/CAP0-1)*100:>+15.0f}%")
print(f"{'VOO 指数':<26}{'-':>16}{(eq_voo[-1]/CAP0-1)*100:>+15.0f}%")

print("\n[3] 调仓频率敏感性 (真实佣金下, 8.7 年)")
print(f"{'策略':<22}{'21天(月频)':>16}{'42天(双月)':>16}{'63天(季频)':>16}{'126天(半年)':>16}")
print("-"*132)
for nm in SIG:
    for tk in [2, 3]:
        row = [backtest(SIG[nm], topk=tk, rebal=rb)[0] for rb in [21, 42, 63, 126]]
        vals = [(e[-1]/CAP0-1)*100 for e in row]
        print(f"{nm+' Top'+str(tk):<22}" + "".join(f"{v:>+15.0f}%" for v in vals))

print("\n[4] 持有 76 个交易日 的分布 (真实佣金, 起点在牛市 = 当前状态)")
print(f"{'策略':<26}{'样本':>7}{'悲观5%':>12}{'25%':>12}{'中位':>12}{'75%':>12}{'乐观95%':>12}{'亏钱概率':>10}")
print("-"*132)
DIST = {}
for nm, eq in EQ_NEW.items():
    r = roll(eq, mask=bull)
    DIST[nm] = r
    if len(r) < 10: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}{val(q)}{ (r<0).mean()*100:>9.0f}%")

print("\n[5] 压力情景: 起点牛市但 76 天内跌破 200 日均线")
print(f"{'策略':<26}{'样本':>7}{'悲观5%':>12}{'25%':>12}{'中位':>12}{'75%':>12}{'乐观95%':>12}{'亏钱概率':>10}")
print("-"*132)
turn = np.zeros(N, bool)
for a in range(START, N-HORIZON):
    if bull[a] and np.any(~bull[a:a+HORIZON]): turn[a] = True
for nm, eq in EQ_NEW.items():
    r = roll(eq, mask=turn)
    if len(r) < 5: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}{val(q)}{ (r<0).mean()*100:>9.0f}%")

print("\n[6] 降低调仓频率能否省钱? (76 天窗口, 起点牛市, 中位收益)")
print(f"{'策略':<22}{'21天/4次 $32':>16}{'42天/2次 $16':>16}{'63天/1次 $8':>16}{'说明':>26}")
print("-"*132)
for nm in SIG:
    for tk in [2, 3]:
        outs = []
        for rb in [21, 42, 63]:
            e, _ = backtest(SIG[nm], topk=tk, rebal=rb)
            r = roll(e, mask=bull)
            outs.append(np.median(r))
        best = int(np.argmax(outs))
        tag = ["", "", ""]
        tag[best] = "  <-- 最优"
        print(f"{nm+' Top'+str(tk):<22}" + "".join(f"{CNY0*(1+v):>14,.0f}元{tag[k]:>2}" for k, v in enumerate(outs)))

print("\n[7] 碎股 vs 整股 + 真实佣金 (Vortex Top2)")
print("-"*132)
def bt_int(score, topk=2, cap=CAP0, rebal=21, slip=0.0005, comm_fixed=COMM):
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    cf = lambda sh: comm_fixed if abs(sh) > 0 else 0.0
    cash = cap; pos = {}; pend = None; eq = []; last = None
    def alloc(picks, op_i):
        nonlocal cash
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*op_i[c]*(1-slip) - cf(sh)
        total = cash; n = len(picks)
        for k, c in enumerate(picks):
            slots = n-k; bud = total/slots if slots > 0 else 0
            pr = op_i[c]*(1+slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = int(bud/pr); cost = sh*pr + cf(sh); guard = 0
            while cost > cash and sh > 0 and guard < 60:
                sh -= 1 if sh > 1 else 0; cost = sh*pr + cf(sh); guard += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh*pr
    for i in range(N):
        co = C[i]; op = O[i]
        if pend is not None: alloc(pend, op); pend = None
        eq.append(cash + sum(pos.get(c, 0)*co[c] for c in pos))
        if i >= START and (i-START) % rebal == 0:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                pick = list(idx[np.argsort(-row[idx])][:topk])
                if pick != last or last is None: pend = pick; last = pick
    return np.array(eq)
for nm in SIG:
    ef, _ = backtest(SIG[nm], topk=2); ei = bt_int(SIG[nm], topk=2)
    a = (ef[-1]/CAP0-1)*100; b = (ei[-1]/CAP0-1)*100
    print(f"  {nm:<20} 碎股 {a:>+10.0f}%   整股 {b:>+10.0f}%   差 {b-a:>+8.0f}pp")

print("\n[8] 本期实际成本 (当前信号, 76 天, 4 次调仓)")
print("-"*132)
i = N-1
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    for tk in [2, 3]:
        row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
        pick = list(idx[np.argsort(-row[idx])][:tk])
        names = [CODES[c].replace("US.","") for c in pick]
        prices = [C[i, c] for c in pick]
        per = CAP0/tk
        shares = [per/p for p in prices]
        ok_int = all(s >= 1 for s in shares)
        cost = 2*tk*COMM*4
        print(f"  {nm} Top{tk}: {', '.join(f'{n}(${p:.0f})' for n, p in zip(names, prices))}")
        print(f"      每只预算 ${per:.0f} | 碎股 {', '.join(f'{s:.2f}股' for s in shares)} | "
              f"整股可行: {'是' if ok_int else '否'} | 4次调仓佣金 ${cost:.0f} = 本金 {cost/CAP0*100:.2f}%")

json.dump({"comm": COMM, "cap_usd": CAP0, "fx": FX, "horizon": HORIZON,
           "median_cny": {k: float(CNY0*(1+np.median(v))) for k, v in DIST.items() if len(v) > 10},
           "p05_cny": {k: float(CNY0*(1+np.percentile(v, 5))) for k, v in DIST.items() if len(v) > 10},
           "p95_cny": {k: float(CNY0*(1+np.percentile(v, 95))) for k, v in DIST.items() if len(v) > 10},
           "final_87y": {k: float((e[-1]/CAP0-1)*100) for k, e in EQ_NEW.items()}},
          open(os.path.join(BASE, "_forecast_2026_v16.json"), "w"), ensure_ascii=False, indent=2)
print("\nSAVED _forecast_2026_v16.json")
