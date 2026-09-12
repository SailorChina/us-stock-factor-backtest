import json, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

codes = json.load(open("fetched_codes.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}

def keep(code):
    n = (univ.get(code) or "")
    if any(k in n for k in ["三倍","2倍","3X","2X","ULTRA","PROSHARES","杠杆","BULL","BEAR"]):
        return False
    if code in ("US.GLD","US.SLV","US.USO","US.GDXU","US.TLT"):
        return False
    return True

fcodes = [c for c in codes if keep(c)]
print("FACTOR_UNIVERSE", len(fcodes), fcodes[:12], "...")

# 读数据（剔除历史不足 3 年的新股，避免对齐窗口被压短）
MIN_START = pd.Timestamp('2023-10-01')
clo, opn, vol = [], [], []
dropped = []
for c in fcodes:
    df = pd.read_csv(f"data_kline/{c.replace('.','_')}.csv", parse_dates=['time_key']).set_index('time_key').sort_index()
    if df.index[0] > MIN_START:
        dropped.append((c, str(df.index[0].date()))); continue
    clo.append(df['close'].rename(c)); opn.append(df['open'].rename(c)); vol.append(df['volume'].rename(c))
fcodes = [c for c in fcodes if c not in {d[0] for d in dropped}]
print("DROPPED_SHORT_HISTORY", dropped)
close = pd.concat(clo, axis=1); openp = pd.concat(opn, axis=1); vol = pd.concat(vol, axis=1)
common = close.dropna(how='any').index
close, openp, vol = close.loc[common], openp.loc[common], vol.loc[common]
rets = close.pct_change().fillna(0)
dates = close.index; N = len(dates)
print("TRADING_DAYS", N, "RANGE", dates[0].date(), "->", dates[-1].date())

def cs_rank(m):
    order = m.argsort(1)
    r = np.empty_like(order, dtype=float)
    for i in range(m.shape[0]):
        r[i, order[i]] = np.arange(m.shape[1])
    return r/(m.shape[1]-1) - 0.5

def compute_scores(i):
    sc, oc, vl = close.iloc[:i+1], openp.iloc[:i+1], vol.iloc[:i+1]
    out = {}
    # 1) Momentum 12-1
    out['Momentum'] = sc.iloc[-22]/sc.iloc[-253] - 1
    # 2) WorldQuant Alpha#1 = -corr(open, volume, 10)
    A = oc.iloc[-10:].values; B = vl.iloc[-10:].values
    A = (A-A.mean(0))/(A.std(0)+1e-9); B = (B-B.mean(0))/(B.std(0)+1e-9)
    out['WQ_Alpha1'] = pd.Series(-(A*B).mean(0), index=fcodes)
    # 3) WorldQuant Alpha#2 = -corr(rank(dlogV,2), rank((C-O)/O), 6)
    vl6 = np.log(vl.iloc[-6:].values); d2 = np.zeros_like(vl6); d2[2:] = vl6[2:]-vl6[:-2]
    x = cs_rank(d2)
    yv = (sc.iloc[-6:].values - oc.iloc[-6:].values)/oc.iloc[-6:].values
    y = cs_rank(yv)
    X = (x-x.mean(0))/(x.std(0)+1e-9); Y = (y-y.mean(0))/(y.std(0)+1e-9)
    out['WQ_Alpha2'] = pd.Series(-(X*Y).mean(0), index=fcodes)
    # 4) Low Volatility / BAB (AQR 风格, 纯量价)
    out['LowVol_BAB'] = -rets.iloc[:i+1].iloc[-63:].std(axis=0)
    return out

reb_every = 21; start = 254; topn = 10
W = {k: pd.DataFrame(0.0, index=dates, columns=fcodes) for k in ['Momentum','WQ_Alpha1','WQ_Alpha2','LowVol_BAB','Ensemble']}
for i in range(start, N, reb_every):
    sc = compute_scores(i)
    for k, s in sc.items():
        rk = s.dropna().sort_values(ascending=False)
        top = rk.index[:topn]
        W[k].loc[dates[i], top] = 1.0/len(top)
    ranks = [sc[k].rank(ascending=False, pct=True) for k in ['Momentum','WQ_Alpha1','WQ_Alpha2','LowVol_BAB']]
    ens = sum(ranks)/len(ranks)
    rk = ens.dropna().sort_values(ascending=False)
    W['Ensemble'].loc[dates[i], rk.index[:topn]] = 1.0/len(top)

results = {}; eq_curves = {}
for k in W:
    w = W[k].shift(1).fillna(0.0)
    pr = (w * rets).sum(axis=1)
    eq_curves[k] = (1+pr).cumprod()
    results[k] = pr

w_b = pd.DataFrame(1.0/len(fcodes), index=dates, columns=fcodes)
pr_b = (w_b.shift(1).fillna(0.0)*rets).sum(axis=1)
eq_bench = (1+pr_b).cumprod()
has_voo = 'US.VOO' in fcodes
if has_voo:
    eq_voo = close['US.VOO']/close['US.VOO'].iloc[0]

def metrics(eq, pr):
    eqv = eq.values; rv = pr.values
    total = eqv[-1]/eqv[0]-1
    cagr = eqv[-1]**(252/len(rv))-1
    sharpe = rv.mean()/rv.std()*np.sqrt(252) if rv.std()>0 else 0
    peak = np.maximum.accumulate(eqv); mdd = (eqv/peak-1).min()
    return total, cagr, sharpe, mdd

print("")
print("=== 回测结果（美股热门前%d·3年·月度调仓·等权做多前%d）===" % (len(fcodes), topn))
print("%-12s%10s%10s%8s%10s" % ("策略","总收益","年化","夏普","最大回撤"))
rows = []
for k in ['Momentum','WQ_Alpha1','WQ_Alpha2','LowVol_BAB','Ensemble']:
    t,c,s,m = metrics(eq_curves[k], results[k])
    print("%-12s%9.1f%%%9.1f%%%8.2f%9.1f%%" % (k, t*100, c*100, s, m*100))
    rows.append((k,t,c,s,m))
tb,cb,sb,mb = metrics(eq_bench, pr_b)
print("%-12s%9.1f%%%9.1f%%%8.2f%9.1f%%" % ("等权基准", tb*100, cb*100, sb, mb*100))
if has_voo:
    tv,cv,sv,mv = metrics(eq_voo, close['US.VOO'].pct_change().fillna(0))
    print("%-12s%9.1f%%%9.1f%%%8.2f%9.1f%%" % ("VOO", tv*100, cv*100, sv, mv*100))

plt.figure(figsize=(11,6))
for k in ['Momentum','WQ_Alpha1','WQ_Alpha2','LowVol_BAB','Ensemble']:
    plt.plot(dates, eq_curves[k].values, label=k, lw=1.4)
plt.plot(dates, eq_bench.values, label='等权基准', ls='--', lw=1.2, color='gray')
if has_voo:
    plt.plot(dates, eq_voo.values, label='VOO', ls=':', lw=1.2, color='black')
plt.title('US Hot Top%d Factor Backtest Equity Curve (2023-09~2026-09, monthly rebal, EW top%d)' % (len(fcodes), topn))
plt.ylabel(u'净值 (起始=1)'); plt.legend(); plt.grid(alpha=0.3)
plt.tight_layout(); plt.savefig('backtest_equity.png', dpi=130); plt.close()
print("SAVED backtest_equity.png")

out = {"universe_size": len(fcodes), "start": str(dates[0].date()), "end": str(dates[-1].date()),
       "rebalance":"monthly", "topn": topn,
       "strategies": {r[0]: {"total_return":r[1],"cagr":r[2],"sharpe":r[3],"max_dd":r[4]} for r in rows},
       "note": "Ensemble = 四因子横截面百分位排名等权平均后取前10",
       "benchmark_equal_weight": {"total_return":tb,"cagr":cb,"sharpe":sb,"max_dd":mb}}
if has_voo:
    out["VOO"] = {"total_return":tv,"cagr":cv,"sharpe":sv,"max_dd":mv}
json.dump(out, open("backtest_results.json","w"), ensure_ascii=False, indent=2)
print("SAVED backtest_results.json")
