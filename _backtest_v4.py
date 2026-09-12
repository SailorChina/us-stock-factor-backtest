import json, os, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

codes = json.load(open("fetched_codes.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}
minfo = json.load(open("market_info.json"))

# 仅保留大盘个股（同 v3）：剔除 ETF/ETN，剔除总市值<100亿美元小盘
def keep(code):
    n = (univ.get(code) or "")
    if any(k in n.upper() for k in ("ETF", "ETN")):
        return False
    mv = (minfo.get(code) or {}).get("total_market_val") or 0
    if mv < 1e10:
        return False
    return True
fcodes = [c for c in codes if keep(c)]

kept, clo, opn, vol = [], [], [], []
for c in fcodes:
    df = pd.read_csv(f"data_kline/{c.replace('.','_')}.csv", parse_dates=['time_key']).set_index('time_key').sort_index()
    if df.index.min() > pd.Timestamp('2023-09-01'):
        continue
    kept.append(c)
    clo.append(df['close'].rename(c)); opn.append(df['open'].rename(c)); vol.append(df['volume'].rename(c))
fcodes = kept
close = pd.concat(clo, axis=1); openp = pd.concat(opn, axis=1); vol = pd.concat(vol, axis=1)
common = close.dropna(how='any').index
close, openp, vol = close.loc[common], openp.loc[common], vol.loc[common]
dates = close.index; N = len(dates)
print("TRADING_DAYS", N, str(dates[0].date()), "->", str(dates[-1].date()), "UNIV", len(fcodes))

rets = close.pct_change().fillna(0)

def cs_rank(m):
    order = m.argsort(1)
    r = np.empty_like(order, dtype=float)
    for i in range(m.shape[0]):
        r[i, order[i]] = np.arange(m.shape[1])
    return r/(m.shape[1]-1) - 0.5

def score_at(i):
    sc = close.iloc[:i+1]; oc = openp.iloc[:i+1]; vl = vol.iloc[:i+1]
    out = {}
    out['Momentum'] = sc.iloc[-22]/sc.iloc[-253] - 1
    A = oc.iloc[-10:].values; B = vl.iloc[-10:].values
    A = (A-A.mean(0))/(A.std(0)+1e-9); B = (B-B.mean(0))/(B.std(0)+1e-9)
    out['WQ_Alpha1'] = pd.Series(-(A*B).mean(0), index=fcodes)
    return out

reb_every = 21
start = 254
reb_days = set(range(start, N, reb_every))

COMM_PER_SHARE = 0.01
COMM_MIN = 1.5

def run_portfolio_v4(factor, topk, stop_pct, capital0=3000.0):
    """日级事件驱动：月度调仓 + 盘中 trailing stop（从峰值回撤 stop_pct 清仓转现金）"""
    cash = capital0
    shares = pd.Series(0, index=fcodes, dtype=int)
    entry = {}   # code -> 入场价
    peak = {}    # code -> 持仓以来最高收盘价
    equity = []
    stop_events = []   # (date, code, exit_price, pnl_pct)
    invested_days = 0
    for i in range(N):
        if i in reb_days:
            # 1) 清掉所有现有持仓
            for c in fcodes:
                if shares[c] > 0:
                    p = close[c].iloc[i]; sh = shares[c]
                    fee = max(sh*COMM_PER_SHARE, COMM_MIN)
                    cash += sh*p - fee; shares[c] = 0
                    entry.pop(c, None); peak.pop(c, None)
            # 2) 按动量 top-K 重新入场（被止损的票若仍在前K即重新买入）
            sc = score_at(i)[factor].dropna().sort_values(ascending=False)
            pick = list(sc.index[:topk])
            per = cash/topk
            for c in pick:
                p = close[c].iloc[i]
                if p > 0:
                    sh = int(per // p)
                    if sh > 0:
                        fee = max(sh*COMM_PER_SHARE, COMM_MIN)
                        cost = sh*p + fee
                        if cost <= cash:
                            shares[c] = sh; cash -= cost
                            entry[c] = p; peak[c] = p
        else:
            # 盘中 trailing stop 检查（仅非调仓日）
            for c in fcodes:
                sh = shares[c]
                if sh > 0:
                    px = close[c].iloc[i]
                    pk = peak.get(c, px)
                    if px > pk:
                        pk = px; peak[c] = px
                    if stop_pct and px <= pk*(1-stop_pct):
                        fee = max(sh*COMM_PER_SHARE, COMM_MIN)
                        cash += sh*px - fee
                        ep = entry.get(c, px)
                        stop_events.append((str(dates[i].date()), c, round(px,2), (px/ep-1)))
                        shares[c] = 0; peak.pop(c, None); entry.pop(c, None)
        mv = sum(shares[c]*close[c].iloc[i] for c in fcodes)
        if mv > 0:
            invested_days += 1
        equity.append(cash + mv)
    eq = pd.Series(equity, index=dates)
    return eq, stop_events, invested_days

def metrics(eq):
    eqv = eq.values[start:]
    pr = np.diff(eqv)/eqv[:-1]
    total = eqv[-1]/eqv[0]-1
    cagr = (eqv[-1]/eqv[0])**(252/len(eqv))-1
    sharpe = pr.mean()/pr.std()*np.sqrt(252) if pr.std()>0 else 0
    peak = np.maximum.accumulate(eqv); mdd = (eqv/peak-1).min()
    return total, cagr, sharpe, mdd

# 扫描：Momentum top2 / top3，止损档位
stop_levels = [0.0, 0.10, 0.15, 0.20, 0.25]
configs = [("Momentum",2),("Momentum",3)]
curves = {}; res = {}; stopcounts = {}
for f,k in configs:
    for sp in stop_levels:
        eq, ev, inv = run_portfolio_v4(f, k, sp)
        curves[(f,k,sp)] = eq
        t,c,s,m = metrics(eq)
        res[(f,k,sp)] = (t,c,s,m)
        stopcounts[(f,k,sp)] = (len(ev), inv)
        label = "no-stop" if sp==0 else f"stop{int(sp*100)}%"
        print(f"{f} top{k} {label}: final ${eq.values[-1]:.0f}  total {t*100:.1f}%  cagr {c*100:.1f}%  sharpe {s:.2f}  mdd {m*100:.1f}%  stops={len(ev)} invested={inv/N*100:.0f}%")

# VOO 基准
voo_csv = "data_kline/US_VOO.csv"
eq_voo = None
if os.path.exists(voo_csv):
    voo = pd.read_csv(voo_csv, parse_dates=['time_key']).set_index('time_key').sort_index().reindex(dates).ffill()
    p0 = voo['close'].iloc[start]; sh = int(3000//p0)
    fee0 = max(sh*COMM_PER_SHARE, COMM_MIN)
    cash_voo = 3000 - sh*p0 - fee0
    eq_voo = pd.Series(cash_voo + sh*voo['close'].values, index=dates)
    tv,cv,sv,mv = metrics(eq_voo)
    print(f"VOO B&H: final ${eq_voo.values[-1]:.0f}  total {tv*100:.1f}%  cagr {cv*100:.1f}%  sharpe {sv:.2f}  mdd {mv*100:.1f}%")

# 绘图：Momentum top2 与 top3 各止损档位 + VOO
plt.figure(figsize=(12,7))
cmap2 = {0.0:"#888888", 0.10:"#1f77b4", 0.15:"#2ca02c", 0.20:"#ff7f0e", 0.25:"#d62728"}
for k in (2,3):
    for sp in stop_levels:
        eq = curves[("Momentum",k,sp)]
        ls = "-" if k==2 else "--"
        plt.plot(dates, eq.values/3000, ls=ls, lw=1.3,
                 color=cmap2[sp], label=f"Mom top{k} {'no-stop' if sp==0 else f'stop{int(sp*100)}'}")
if eq_voo is not None:
    plt.plot(dates, eq_voo.values/3000, label="VOO B&H", ls=":", lw=1.6, color="black")
plt.axhline(1, color="gray", lw=0.8, ls="--")
plt.title("Momentum with trailing stop + monthly re-entry ($3000, large-cap only, 2023-2026)")
plt.ylabel("Portfolio value / initial $3000"); plt.legend(fontsize=8, ncol=2); plt.grid(alpha=0.3)
plt.tight_layout(); plt.savefig("backtest_v4_equity.png", dpi=130); plt.close()
print("SAVED backtest_v4_equity.png")

# 输出 JSON
def fmt(eq):
    t,c,s,m = metrics(eq)
    return {"final":float(eq.values[-1]),"total_return":t,"cagr":c,"sharpe":s,"max_dd":m}
out = {"capital":3000,"rebalance":"monthly","stop_type":"trailing_from_peak","commission":"max(shares*0.01,1.5) USD",
       "start":str(dates[start].date()),"end":str(dates[N-1].date()),"universe":len(fcodes),
       "stop_sweep":{f"top{k}_{f}":{("no-stop" if sp==0 else f"stop{int(sp*100)}"):{**fmt(curves[(f,k,sp)]),
            "num_stops":stopcounts[(f,k,sp)][0], "pct_days_invested":round(stopcounts[(f,k,sp)][1]/N*100,1)}
            for sp in stop_levels} for (f,k) in configs}}
if eq_voo is not None:
    out["VOO_BH"]=fmt(eq_voo)
json.dump(out, open("backtest_v4_results.json","w"), ensure_ascii=False, indent=2)
print("SAVED backtest_v4_results.json")
