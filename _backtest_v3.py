import json, os, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

codes = json.load(open("fetched_codes.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}
minfo = json.load(open("market_info.json"))

# 用户约束：不买小盘股和指数 -> 仅保留大盘个股
# 1) 剔除指数/行业/杠杆/商品 ETF（名称含 ETF 或 ETN）
# 2) 剔除总市值 < 100 亿美元的小盘股（total_market_val 单位为美元）
def keep(code):
    n = (univ.get(code) or "")
    if any(k in n.upper() for k in ("ETF", "ETN")):
        return False
    mv = (minfo.get(code) or {}).get("total_market_val") or 0
    if mv < 1e10:
        return False
    return True
fcodes = [c for c in codes if keep(c)]

# 剔除上市晚于 2023-09-01 的标的，恢复 3 年回测窗口（避免晚上市股拉短样本/污染因子）
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
    vl6 = np.log(vl.iloc[-6:].values); d2 = np.zeros_like(vl6); d2[2:]=vl6[2:]-vl6[:-2]
    x = cs_rank(d2); yv = (sc.iloc[-6:].values-oc.iloc[-6:].values)/oc.iloc[-6:].values
    y = cs_rank(yv); X=(x-x.mean(0))/(x.std(0)+1e-9); Y=(y-y.mean(0))/(y.std(0)+1e-9)
    out['WQ_Alpha2'] = pd.Series(-(X*Y).mean(0), index=fcodes)
    out['LowVol_BAB'] = -rets.iloc[:i+1].iloc[-63:].std(0)
    return out

reb_every = 21
start = 254
reb_days = set(range(start, N, reb_every))

COMM_PER_SHARE = 0.01   # Futu US: ~$0.0049/share comm + ~$0.005/platform, simplified
COMM_MIN = 1.5          # minimum per trade

def run_portfolio(factor, topk, capital0=3000.0):
    cash = capital0
    shares = pd.Series(0, index=fcodes, dtype=int)
    equity = []
    trades_log = []
    prev_hold = []
    for i in range(N):
        if i in reb_days:
            for c in prev_hold:
                p = close[c].iloc[i]; sh = shares[c]
                if sh > 0:
                    fee = max(sh*COMM_PER_SHARE, COMM_MIN)
                    cash += sh*p - fee
                    shares[c] = 0
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
            prev_hold = pick
            trades_log.append((str(dates[i].date()), {c:(shares[c], round(float(close[c].iloc[i]),2)) for c in pick if shares[c]>0}))
        mv = sum(shares[c]*close[c].iloc[i] for c in fcodes)
        equity.append(cash + mv)
    eq = pd.Series(equity, index=dates)
    return eq, trades_log

def metrics(eq):
    eqv = eq.values[start:]
    pr = np.diff(eqv)/eqv[:-1]
    total = eqv[-1]/eqv[0]-1
    cagr = (eqv[-1]/eqv[0])**(252/len(eqv))-1
    sharpe = pr.mean()/pr.std()*np.sqrt(252) if pr.std()>0 else 0
    peak = np.maximum.accumulate(eqv); mdd = (eqv/peak-1).min()
    return total, cagr, sharpe, mdd

configs = [("Momentum",3),("Momentum",2),("WQ_Alpha1",3),("LowVol_BAB",3)]
curves = {}; logs = {}; res = {}
for f,k in configs:
    eq, lg = run_portfolio(f,k)
    curves[(f,k)] = eq; logs[(f,k)] = lg
    t,c,s,m = metrics(eq)
    res[(f,k)] = (t,c,s,m)
    print(f"{f} top{k}: final ${eq.values[-1]:.0f}  total {t*100:.1f}%  cagr {c*100:.1f}%  sharpe {s:.2f}  mdd {m*100:.1f}%")

has_voo = False
voo_csv = "data_kline/US_VOO.csv"
if os.path.exists(voo_csv):
    voo = pd.read_csv(voo_csv, parse_dates=['time_key']).set_index('time_key').sort_index()
    voo = voo.reindex(dates).ffill()
    p0 = voo['close'].iloc[start]; sh = int(3000//p0)
    fee0 = max(sh*COMM_PER_SHARE, COMM_MIN)
    cash_voo = 3000 - sh*p0 - fee0
    eq_voo = pd.Series(cash_voo + sh*voo['close'].values, index=dates)
    tv,cv,sv,mv = metrics(eq_voo)
    has_voo = True
    print(f"VOO B&H: final ${eq_voo.values[-1]:.0f}  total {tv*100:.1f}%  cagr {cv*100:.1f}%  sharpe {sv:.2f}  mdd {mv*100:.1f}%")

print("\n=== Momentum top3 last rebalance ===")
print(logs[("Momentum",3)][-1])
print("=== Momentum top3 first rebalance ===")
print(logs[("Momentum",3)][0])

plt.figure(figsize=(11,6))
for f,k in configs:
    plt.plot(dates, curves[(f,k)].values/3000, label=f"{f} top{k}", lw=1.4)
if has_voo:
    plt.plot(dates, eq_voo.values/3000, label="VOO B&H", ls=":", lw=1.4, color="black")
plt.axhline(1, color="gray", lw=0.8, ls="--")
plt.title("Factor backtest: $3000 capital, hold 2-3 stocks, monthly rebalance (2023-2026)")
plt.ylabel("Portfolio value / initial $3000"); plt.legend(); plt.grid(alpha=0.3)
plt.tight_layout(); plt.savefig("backtest_v3_equity.png", dpi=130); plt.close()
print("SAVED backtest_v2_equity.png")

last = N-1
sc_last = score_at(last)
print("\n=== CURRENT SIGNAL (as of %s) ===" % str(dates[last].date()))
rec = {}
for f in ["Momentum","WQ_Alpha1","LowVol_BAB"]:
    s = sc_last[f].dropna().sort_values(ascending=False)
    rec[f] = {}
    print(f"\n{f}:")
    for c in s.index[:3]:
        p = float(close[c].iloc[last])
        sh3 = int((3000/3)//p); sh2 = int((3000/2)//p)
        rec[f][c] = {"price": round(p,2), "top3_shares": sh3, "top3_cost": round(sh3*p,2),
                     "top2_shares": sh2, "top2_cost": round(sh2*p,2)}
        print(f"  {c} {univ.get(c,'')}: ${p:.2f}  top3-> {sh3} sh (${sh3*p:.0f}) | top2-> {sh2} sh (${sh2*p:.0f})")

out = {"capital":3000,"topk":[2,3],"rebalance":"monthly","commission":"max(shares*0.01, 1.5) USD per trade",
       "start":str(dates[start].date()),"end":str(dates[last].date()),"universe":len(fcodes),
       "strategies":{f"top{k}_{f}":{"final":float(curves[(f,k)].values[-1]),"total_return":res[(f,k)][0],
                     "cagr":res[(f,k)][1],"sharpe":res[(f,k)][2],"max_dd":res[(f,k)][3]} for (f,k) in configs}}
if has_voo:
    out["VOO_BH"]={"final":float(eq_voo.values[-1]),"total_return":tv,"cagr":cv,"sharpe":sv,"max_dd":mv}
out["current_signal"] = rec
json.dump(out, open("backtest_v3_results.json","w"), ensure_ascii=False, indent=2)
print("SAVED backtest_v2_results.json")
