# -*- coding: utf-8 -*-
"""
v15  1万人民币起步 -> 2026年底 能有多少?

要点:
 1) 资金规模效应: 富途最低佣金 $1/笔, 本金只有 $1490 时成本占比远大于 $3000 回测,
    必须用【真实本金】重跑历史, 拿该本金下的日净值序列做分布, 不能拿 3000 的结果缩放.
 2) 期限: 2026-09-12 -> 2026-12-31 约 76 个美股交易日 (已扣除周末/感恩节/圣诞).
 3) 三种分布估计:
      A 全历史滚动 76 日窗口的真实收益分布
      B 条件化: 只在"起点处于牛市(VOO>200DMA)"的窗口 -> 匹配当前状态
      C 条件化: 只在"起点处于熊市或高波动"的窗口 -> 悲观情景
      D Block bootstrap (块长21, 保留月内自相关)
 4) 引擎沿用 v14 修复版 (等权满仓 + 无前视), 参数化 CAP0.
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

FX = 6.7092          # USD/CNY 2026-09-12
CNY0 = 10000.0
CAP0 = CNY0 / FX     # 约 1490 美元
HORIZON = 76         # 2026-09-12 -> 2026-12-31 的美股交易日
N_SIM = 20000

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
START = 252

# ================= v14 修复版引擎 (参数化本金) =================
def backtest(score, topk=2, cap=CAP0, slip=0.0005):
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    comm = lambda sh: max(abs(sh)*0.005, 1.0) if abs(sh) > 0 else 0.0
    cash = cap; pos = {}; pend = None; eq = []
    def allocate(picks, op_i):
        nonlocal cash
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*op_i[c]*(1-slip) - comm(sh)
        total = cash
        n = len(picks)
        for k, c in enumerate(picks):
            slots = n-k
            bud = total/slots if slots > 0 else 0
            pr = op_i[c]*(1+slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = bud/pr; cost = sh*pr + comm(sh); guard = 0
            while cost > cash and sh > 0 and guard < 60:
                sh *= 0.995; cost = sh*pr + comm(sh); guard += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh*pr
    last_pick = None
    for i in range(N):
        co = C[i]; op = O[i]
        if pend is not None:
            allocate(pend, op); pend = None
        eq.append(cash + sum(pos.get(c, 0)*co[c] for c in pos))
        if i >= START and (i-START) % 21 == 0:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                pick = list(idx[np.argsort(-row[idx])][:topk])
                if pick != last_pick or last_pick is None:
                    pend = pick; last_pick = pick
    return np.array(eq)

# ---------------- 基准 ----------------
def buy_hold_all(cap=CAP0, slip=0.0005):
    s0 = np.nan_to_num(C[START], nan=0.0); ok0 = s0 > 0
    w = np.where(ok0, 1.0/ok0.sum(), 0.0)
    sh = cap*w*(1-slip)/np.where(ok0, s0, 1.0)
    e = np.full(N, cap); e[START:] = (np.nan_to_num(C, nan=0.0)@sh)[START:]
    return e
eq_bh = buy_hold_all()
eq_voo = np.concatenate([np.full(START, CAP0), VOO[START:]/VOO[START]*CAP0])

def mdd(eq):
    v = eq[START:]; return ((v-np.maximum.accumulate(v))/np.maximum.accumulate(v)).min()*100

print("="*130)
print(f"起始: 人民币 {CNY0:,.0f} 元  |  汇率 {FX}  |  折合美元 ${CAP0:,.2f}")
print(f"持有期: 2026-09-12 -> 2026-12-31  =  {HORIZON} 个美股交易日")
print("="*130)

# ============ 1) 本金规模效应: $1490 vs $3000 ============
print("\n[1] 本金规模效应 (最低佣金 $1/笔 对小资金的拖累)")
print(f"{'策略':<26}{'$1,490 本金 8.7年':>18}{'$3,000 本金 8.7年':>18}{'差异':>12}")
print("-"*130)
EQUITY = {}
for nm in SIG:
    for tk in [2, 3]:
        e_small = backtest(SIG[nm], topk=tk, cap=CAP0)
        e_big   = backtest(SIG[nm], topk=tk, cap=3000.0)
        EQUITY[f"{nm} Top{tk}"] = e_small
        r1 = (e_small[-1]/CAP0-1)*100; r2 = (e_big[-1]/3000.0-1)*100
        print(f"{nm+' Top'+str(tk):<26}{r1:>+17.0f}%{r2:>+17.0f}%{r1-r2:>+11.0f}pp")
EQUITY["等权全买37只"] = eq_bh
EQUITY["VOO 指数"] = eq_voo
rb = (eq_bh[-1]/CAP0-1)*100; rv = (eq_voo[-1]/CAP0-1)*100
print(f"{'等权全买37只':<26}{rb:>+17.0f}%")
print(f"{'VOO 指数':<26}{rv:>+17.0f}%")

# ============ 2) 当前市场状态 ============
print("\n" + "="*130)
print("[2] 当前市场状态 (截至数据时点)")
print("="*130)
ma200 = pd.Series(VOO, index=dp).rolling(200).mean().values
ma100 = pd.Series(VOO, index=dp).rolling(100).mean().values
i = N-1
print(f"  数据最后交易日: {str(dp[i].date())}")
print(f"  VOO 收盘 {VOO[i]:.2f} | MA200 {ma200[i]:.2f} | MA100 {ma100[i]:.2f}")
print(f"  -> {'牛市 (在 200 日均线上方)' if VOO[i]>ma200[i] else '熊市 (跌破 200 日均线)'}"
      f"  偏离 {(VOO[i]/ma200[i]-1)*100:+.1f}%")
r_voo = pd.Series(VOO, index=dp).pct_change()
vol21 = r_voo.rolling(21).std().values*np.sqrt(252)
print(f"  VOO 近21日年化波动率 {vol21[i]*100:.1f}%  (历史中位 {np.nanmedian(vol21[START:])*100:.1f}%)")
print(f"  VOO 近1月 {(VOO[i]/VOO[i-21]-1)*100:+.1f}% | 近3月 {(VOO[i]/VOO[i-63]-1)*100:+.1f}%"
      f" | 近1年 {(VOO[i]/VOO[i-252]-1)*100:+.1f}%")
# 宇宙近况
ret21 = (dfC.iloc[i]/dfC.iloc[i-21]-1).dropna()
print(f"  37只宇宙 近1月: 中位 {ret21.median()*100:+.1f}% | 上涨 {(ret21>0).sum()}/{len(ret21)} 只")
above = [(dfC[c].iloc[i] > np.nanmean(dfC[c].iloc[i-200:i])) for c in dfC.columns]
print(f"  站上自身200日均线的个股: {sum(above)}/{len(above)}")

# ============ 3) 76 个交易日的真实收益分布 ============
print("\n" + "="*130)
print(f"[3] 持有 {HORIZON} 个交易日 的历史真实收益分布 (每 {HORIZON} 天一个窗口, 全样本滚动)")
print("="*130)
def roll_ret(eq, h=HORIZON, mask=None):
    out = []
    for a in range(START, N-h):
        if mask is not None and not mask[a]: continue
        out.append(eq[a+h]/eq[a]-1)
    return np.array(out)

bull = (VOO > ma200) & np.isfinite(ma200)
hi_vol = np.zeros(N, bool); hi_vol[START:] = vol21[START:] > np.nanpercentile(vol21[START:], 60)
bear_cond = (~bull) | hi_vol

print(f"{'策略':<26}{'样本数':>7}{'5%分位':>10}{'25%':>10}{'中位':>10}{'75%':>10}{'95%分位':>10}{'为正概率':>10}")
print("-"*130)
DIST = {}
for nm, eq in EQUITY.items():
    r = roll_ret(eq)
    DIST[nm] = r
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}{q[0]*100:>+9.1f}%{q[1]*100:>+9.1f}%{q[2]*100:>+9.1f}%"
          f"{q[3]*100:>+9.1f}%{q[4]*100:>+9.1f}%{(r>0).mean()*100:>9.0f}%")

print(f"\n--- 情景B: 只在【牛市起点】(VOO>200DMA) 的窗口, 匹配当前状态 ---")
print(f"{'策略':<26}{'样本数':>7}{'5%分位':>10}{'25%':>10}{'中位':>10}{'75%':>10}{'95%分位':>10}{'为正概率':>10}")
print("-"*130)
DIST_B = {}
for nm, eq in EQUITY.items():
    r = roll_ret(eq, mask=bull)
    DIST_B[nm] = r
    if len(r) < 10: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}{q[0]*100:>+9.1f}%{q[1]*100:>+9.1f}%{q[2]*100:>+9.1f}%"
          f"{q[3]*100:>+9.1f}%{q[4]*100:>+9.1f}%{(r>0).mean()*100:>9.0f}%")

print(f"\n--- 情景C: 只在【熊市或高波动起点】的窗口 (悲观情景) ---")
print(f"{'策略':<26}{'样本数':>7}{'5%分位':>10}{'25%':>10}{'中位':>10}{'75%':>10}{'95%分位':>10}{'为正概率':>10}")
print("-"*130)
DIST_C = {}
for nm, eq in EQUITY.items():
    r = roll_ret(eq, mask=bear_cond)
    DIST_C[nm] = r
    if len(r) < 10: continue
    q = np.percentile(r, [5,25,50,75,95])
    print(f"{nm:<26}{len(r):>7}{q[0]*100:>+9.1f}%{q[1]*100:>+9.1f}%{q[2]*100:>+9.1f}%"
          f"{q[3]*100:>+9.1f}%{q[4]*100:>+9.1f}%{(r>0).mean()*100:>9.0f}%")

# ============ 4) 换算成人民币 ============
print("\n" + "="*130)
print(f"[4] 换算: 人民币 {CNY0:,.0f} 元起步, 到 2026-12-31 大概剩多少 (假设汇率不变 {FX})")
print("="*130)
def show(dist, title):
    print(f"\n{title}")
    print(f"{'策略':<26}{'悲观5%':>14}{'较差25%':>14}{'中位50%':>14}{'较好75%':>14}{'乐观95%':>14}{'亏钱概率':>10}")
    print("-"*130)
    for nm in ["Vortex Top2","Vortex Top3","动量-1月反转 Top2","动量-1月反转 Top3","等权全买37只","VOO 指数"]:
        r = dist.get(nm)
        if r is None or len(r) < 10: continue
        q = np.percentile(r, [5,25,50,75,95])
        vals = [CNY0*(1+x) for x in q]
        print(f"{nm:<26}" + "".join(f"{v:>13,.0f}元" for v in vals) + f"{(r<0).mean()*100:>9.0f}%")
show(DIST, "【全历史】不分牛熊")
show(DIST_B, "【情景B】起点在牛市 (VOO 在200日均线上方) —— 当前正是这种状态")
show(DIST_C, "【情景C】起点在熊市/高波动 —— 悲观情景")

# ============ 5) Block bootstrap 蒙特卡洛 ============
print("\n" + "="*130)
print(f"[5] 蒙特卡洛 (Block bootstrap, 块长21日, {N_SIM:,} 次) —— 与滚动窗口互相验证")
print("="*130)
rng = np.random.default_rng(42)
print(f"{'策略':<26}{'5%':>12}{'25%':>12}{'中位':>12}{'75%':>12}{'95%':>12}{'亏钱概率':>10}")
print("-"*130)
for nm in ["Vortex Top2","Vortex Top3","动量-1月反转 Top2","动量-1月反转 Top3"]:
    eq = EQUITY[nm]
    d = np.diff(eq[START:])/eq[START:-1]
    d = d[np.isfinite(d)]
    B = 21; nb = int(np.ceil(HORIZON/B))
    sims = np.empty(N_SIM)
    for s in range(N_SIM):
        starts = rng.integers(0, len(d)-B, size=nb)
        path = np.concatenate([d[a:a+B] for a in starts])[:HORIZON]
        sims[s] = np.prod(1+path)-1
    q = np.percentile(sims, [5,25,50,75,95])
    print(f"{nm:<26}" + "".join(f"{CNY0*(1+x):>11,.0f}元" for x in q) + f"{(sims<0).mean()*100:>9.0f}%")

# ============ 6) 当前该买什么 ============
print("\n" + "="*130)
print("[6] 当前信号 (最近一期调仓) —— 用最新数据算出的选股")
print("="*130)
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    for tk in [2, 3]:
        last_rb = max(j for j in range(START, N) if (j-START) % 21 == 0)
        row = A[last_rb]; ok = np.isfinite(row); idx = np.where(ok)[0]
        pick = list(idx[np.argsort(-row[idx])][:tk])
        names = [CODES[c].replace("US.","") for c in pick]
        # 这些票的近况
        info = []
        for c in pick:
            col = dfC.columns[c]
            p1 = dfC[col].iloc[i]/dfC[col].iloc[i-21]-1
            p12 = dfC[col].iloc[i]/dfC[col].iloc[i-252]-1
            info.append(f"{CODES[c].replace('US.','')}(近1月{p1*100:+.0f}%/近1年{p12*100:+.0f}%)")
        pr = [C[i, c] for c in pick]
        print(f"  {nm} Top{tk}  [调仓日 {str(dp[last_rb].date())}]")
        print(f"     买入: {', '.join(info)}")
        print(f"     按 ${CAP0:,.0f} 等权, 每只约 ${CAP0/tk:,.0f}; 现价 " +
              ", ".join(f"{CODES[c].replace('US.','')}=${v:.2f}" for c, v in zip(pick, pr)))
    print()

# ============ 7) 持有期内的成本 ============
print("="*130)
print("[7] 小资金成本测算 (76 个交易日 ≈ 4 次月度调仓)")
print("="*130)
n_reb = 4
for tk in [2, 3]:
    per = CAP0/tk
    comm_per = max(per*0.005/ (per/150), 1.0) if False else 1.0   # 每笔最低 $1
    total_comm = n_reb*tk*2*comm_per
    slip_cost = CAP0*0.0005*2*n_reb
    print(f"  Top{tk}: 每只约 ${per:,.0f} | 4次调仓 x {tk}只 x 买卖2笔 x $1 = ${total_comm:.0f} 佣金"
          f" | 滑点 ${slip_cost:.1f} | 合计 ${total_comm+slip_cost:.0f} = 本金 {(total_comm+slip_cost)/CAP0*100:.2f}%")
print(f"  注: 若券商免佣金(如部分零佣), 可省下上表佣金部分; 但滑点无法避免。")

json.dump({"cap_usd": CAP0, "fx": FX, "horizon": HORIZON,
           "median_cny": {k: float(CNY0*(1+np.median(v))) for k, v in DIST_B.items() if len(v) > 10},
           "p05_cny": {k: float(CNY0*(1+np.percentile(v, 5))) for k, v in DIST_B.items() if len(v) > 10},
           "p95_cny": {k: float(CNY0*(1+np.percentile(v, 95))) for k, v in DIST_B.items() if len(v) > 10}},
          open(os.path.join(BASE, "_forecast_2026.json"), "w"), ensure_ascii=False, indent=2)
print("\nSAVED _forecast_2026.json")
