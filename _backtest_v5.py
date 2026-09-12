import json, os, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

codes = json.load(open("fetched_codes.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}
minfo = json.load(open("market_info.json"))

def keep(code):
    n = (univ.get(code) or "")
    if any(k in n.upper() for k in ("ETF", "ETN")):
        return False
    mv = (minfo.get(code) or {}).get("total_market_val") or 0
    if mv < 1e10:
        return False
    return True
fcodes = [c for c in codes if keep(c)]

kept, clo, opn, vol, hi, lo = [], [], [], [], [], []
for c in fcodes:
    df = pd.read_csv(f"data_kline/{c.replace('.','_')}.csv", parse_dates=['time_key']).set_index('time_key').sort_index()
    if df.index.min() > pd.Timestamp('2023-09-01'):
        continue
    kept.append(c)
    clo.append(df['close'].rename(c)); opn.append(df['open'].rename(c)); vol.append(df['volume'].rename(c))
    hi.append(df['high'].rename(c)); lo.append(df['low'].rename(c))
fcodes = kept
close = pd.concat(clo, axis=1); openp = pd.concat(opn, axis=1); vol = pd.concat(vol, axis=1)
high = pd.concat(hi, axis=1); low = pd.concat(lo, axis=1)
common = close.dropna(how='any').index
close, openp, vol = close.loc[common], openp.loc[common], vol.loc[common]
high, low = high.loc[common], low.loc[common]
dates = close.index; N = len(dates)
print("TRADING_DAYS", N, str(dates[0].date()), "->", str(dates[-1].date()), "UNIV", len(fcodes))

rets = close.pct_change().fillna(0)

# ATR(14) 真实波幅 -> 占价比例
prev_close = close.shift(1)
tr = (high - low).where((high - low) >= (high - prev_close).abs(), (high - prev_close).abs())
tr = tr.where(tr >= (low - prev_close).abs(), (low - prev_close).abs())
atr = tr.rolling(14).mean()
atr_frac = (atr / close).fillna(0.02)   # 早期/缺失用 2% 兜底

def score_at(i):
    sc = close.iloc[:i+1]
    return pd.Series(sc.iloc[-22]/sc.iloc[-253] - 1, index=fcodes)  # Momentum 12-1

reb_every = 21
start = 254
reb_days = set(range(start, N, reb_every))
COMM_PER_SHARE = 0.01
COMM_MIN = 1.5

def run(factor_topk_pick, topk, stop_mode, stop_val=0.0, recovery=False, pstop=None,
        atr_beta=4.0, dmin=0.08, dmax=0.30, capital0=3000.0):
    """stop_mode: 'none'|'fixed'|'atr'；pstop: 组合级止损比例或None"""
    cash = capital0
    shares = pd.Series(0, index=fcodes, dtype=int)
    entry = {}; peak = {}; stop_trig = {}
    port_peak = capital0; port_stopped = False
    equity = []; single_stops = 0; port_stops = 0; invested_days = 0
    for i in range(N):
        mv = cash + sum(shares[c]*close[c].iloc[i] for c in fcodes)
        invested_now = shares.sum() > 0
        # 组合级止损：从组合高点回撤 pstop 则全清
        if pstop and not port_stopped and invested_now and mv <= port_peak*(1-pstop):
            for c in fcodes:
                if shares[c] > 0:
                    p = close[c].iloc[i]; sh = shares[c]
                    fee = max(sh*COMM_PER_SHARE, COMM_MIN); cash += sh*p - fee; shares[c]=0
                    entry.pop(c,None); peak.pop(c,None); stop_trig.pop(c,None)
            port_stopped = True; port_stops += 1; port_peak = cash
        # 月度调仓（组合止损后也在此复位再入场）
        if i in reb_days:
            for c in fcodes:
                if shares[c] > 0:
                    p = close[c].iloc[i]; sh = shares[c]
                    fee = max(sh*COMM_PER_SHARE, COMM_MIN); cash += sh*p - fee; shares[c]=0
                    entry.pop(c,None); peak.pop(c,None); stop_trig.pop(c,None)
            port_stopped = False
            pick = factor_topk_pick(i)
            per = cash/len(pick)
            for c in pick:
                p = close[c].iloc[i]
                if p > 0:
                    sh = int(per//p)
                    if sh > 0:
                        fee = max(sh*COMM_PER_SHARE, COMM_MIN); cost = sh*p+fee
                        if cost <= cash:
                            shares[c]=sh; cash-=cost; entry[c]=p; peak[c]=p
            mv = cash + sum(shares[c]*close[c].iloc[i] for c in fcodes)
            port_peak = max(port_peak, mv)
        else:
            if not port_stopped:
                # 单票 trailing stop
                for c in fcodes:
                    if shares[c] > 0:
                        px = close[c].iloc[i]; pk = peak.get(c, px)
                        if px > pk: pk = px; peak[c] = px
                        if stop_mode == 'fixed':
                            d = stop_val
                        elif stop_mode == 'atr':
                            d = min(max(atr_beta*atr_frac[c].iloc[i], dmin), dmax)
                        else:
                            d = 0
                        if d > 0 and px <= pk*(1-d):
                            fee = max(shares[c]*COMM_PER_SHARE, COMM_MIN)
                            cash += shares[c]*px - fee
                            stop_trig[c] = px; single_stops += 1
                            shares[c]=0; peak.pop(c,None); entry.pop(c,None)
                # 回撤恢复再入场
                if recovery:
                    budget = cash/topk if cash > 0 else 0
                    for c in list(stop_trig):
                        if cash <= budget*0.5: break
                        px = close[c].iloc[i]
                        if px >= stop_trig[c]:
                            sh = int(budget//px)
                            if sh > 0:
                                fee = max(sh*COMM_PER_SHARE, COMM_MIN); cost = sh*px+fee
                                if cost <= cash:
                                    shares[c]=sh; cash-=cost; entry[c]=px; peak[c]=px
                                    del stop_trig[c]
            if shares.sum() > 0:
                port_peak = max(port_peak, mv)
        if shares.sum() > 0: invested_days += 1
        equity.append(cash + sum(shares[c]*close[c].iloc[i] for c in fcodes))
    eq = pd.Series(equity, index=dates)
    return eq, single_stops, port_stops, invested_days

def metrics(eq):
    eqv = eq.values[start:]
    pr = np.diff(eqv)/eqv[:-1]
    total = eqv[-1]/eqv[0]-1
    cagr = (eqv[-1]/eqv[0])**(252/len(eqv))-1
    sharpe = pr.mean()/pr.std()*np.sqrt(252) if pr.std()>0 else 0
    peak = np.maximum.accumulate(eqv); mdd = (eqv/peak-1).min()
    return total, cagr, sharpe, mdd

# 变体定义（top2 / top3 动量）
variants = [
    ("none",            dict(stop_mode='none')),
    ("fixed15",         dict(stop_mode='fixed', stop_val=0.15)),
    ("fixed15_rec",     dict(stop_mode='fixed', stop_val=0.15, recovery=True)),
    ("atr",             dict(stop_mode='atr', atr_beta=4.0)),
    ("atr_rec",         dict(stop_mode='atr', atr_beta=4.0, recovery=True)),
    ("pstop15",         dict(stop_mode='none', pstop=0.15)),
    ("pstop15_fixed15", dict(stop_mode='fixed', stop_val=0.15, pstop=0.15)),
]
topks = [2,3]
curves = {}; res = {}; info = {}
for k in topks:
    for vname, kw in variants:
        pick_fn = lambda i, k=k: list(score_at(i).dropna().sort_values(ascending=False).index[:k])
        eq, ss, ps, inv = run(pick_fn, k, **kw)
        curves[(k,vname)] = eq
        t,c,s,m = metrics(eq)
        res[(k,vname)] = (t,c,s,m)
        info[(k,vname)] = (ss, ps, inv)
        print(f"top{k} {vname:16s}: final ${eq.values[-1]:.0f}  total {t*100:7.1f}%  cagr {c*100:6.1f}%  sharpe {s:.2f}  mdd {m*100:6.1f}%  sStop={ss:3d} pStop={ps} inv={inv/N*100:.0f}%")

# VOO 基准
voo_csv = "data_kline/US_VOO.csv"
eq_voo = None
if os.path.exists(voo_csv):
    voo = pd.read_csv(voo_csv, parse_dates=['time_key']).set_index('time_key').sort_index().reindex(dates).ffill()
    p0 = voo['close'].iloc[start]; sh = int(3000//p0); fee0 = max(sh*COMM_PER_SHARE, COMM_MIN)
    eq_voo = pd.Series(3000 - sh*p0 - fee0 + sh*voo['close'].values, index=dates)
    tv,cv,sv,mv = metrics(eq_voo)
    print(f"VOO B&H: final ${eq_voo.values[-1]:.0f}  total {tv*100:.1f}%  cagr {cv*100:.1f}%  sharpe {sv:.2f}  mdd {mv*100:.1f}%")

# 绘图：top2 各变体
plt.figure(figsize=(12,7))
cmap = {"none":"#888888","fixed15":"#1f77b4","fixed15_rec":"#17becf","atr":"#2ca02c",
        "atr_rec":"#9467bd","pstop15":"#ff7f0e","pstop15_fixed15":"#d62728"}
for vname,_ in variants:
    eq = curves[(2,vname)]
    plt.plot(dates, eq.values/3000, lw=1.3, color=cmap[vname], label=f"top2 {vname}")
if eq_voo is not None:
    plt.plot(dates, eq_voo.values/3000, label="VOO B&H", ls=":", lw=1.6, color="black")
plt.axhline(1, color="gray", lw=0.8, ls="--")
plt.title("Momentum stop-loss variants: fixed / ATR-adaptive / recovery / portfolio-level ($3000)")
plt.ylabel("Portfolio value / initial $3000"); plt.legend(fontsize=8, ncol=2); plt.grid(alpha=0.3)
plt.tight_layout(); plt.savefig("backtest_v5_equity.png", dpi=130); plt.close()
print("SAVED backtest_v5_equity.png")

out = {"capital":3000,"rebalance":"monthly","universe":len(fcodes),
       "start":str(dates[start].date()),"end":str(dates[N-1].date()),
       "variants":{f"top{k}":{vname:{"final":float(curves[(k,vname)].values[-1]),
            "total_return":res[(k,vname)][0],"cagr":res[(k,vname)][1],"sharpe":res[(k,vname)][2],
            "max_dd":res[(k,vname)][3],"single_stops":info[(k,vname)][0],
            "portfolio_stops":info[(k,vname)][1],"pct_days_invested":round(info[(k,vname)][2]/N*100,1)}
            for vname,_ in variants} for k in topks}}
if eq_voo is not None:
    out["VOO_BH"]={"final":float(eq_voo.values[-1]),"total_return":tv,"cagr":cv,"sharpe":sv,"max_dd":mv}
json.dump(out, open("backtest_v5_results.json","w"), ensure_ascii=False, indent=2)
print("SAVED backtest_v5_results.json")
