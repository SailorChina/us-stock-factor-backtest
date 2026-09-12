# -*- coding: utf-8 -*-
"""
美股因子策略 · 牛熊长周期回测 (2018-01 ~ 2026-09)
================================================
复用 v7 已验证引擎，数据来自 data_kline_long/ (37 只大盘股 + VOO 基准)。
起点 $3000；分段统计 2018/2020/2022 熊市与牛市表现。
"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
OUT_JSON = os.path.join(BASE, "_long_results.json")

# ---------- 1. 数据加载 ----------
def is_etf(name):
    n = (name or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])

mi = json.load(open(os.path.join(BASE,"market_info.json")))
fetched = json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI = [c for c in fetched
       if not is_etf(mi.get(c,{}).get("name",""))
       and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]

def load_panel(codes):
    panel = {}
    for c in codes:
        f = os.path.join(LONGDIR, c.replace(".","_")+".csv")
        df = pd.read_csv(f); df["time_key"]=pd.to_datetime(df["time_key"])
        df = df.sort_values("time_key").reset_index(drop=True)
        panel[c] = df.set_index("time_key")
    all_dates = sorted(set().union(*[set(df.index) for df in panel.values()]))
    dates = pd.to_datetime(all_dates)
    close = pd.DataFrame({c: panel[c]["close"].reindex(dates).ffill() for c in codes})
    return dates, close

# ---------- 2. 因子 ----------
def pct(a,n): return a/a.shift(n)-1.0
def build_factors(close):
    mom12_1 = close.shift(21)/close.shift(252)-1.0
    m1=pct(close,21); m3=pct(close,63); m6=pct(close,126); m12=pct(close,252)
    mom_multi = 0.1*m1 + 0.2*m3 + 0.3*m6 + 0.4*m12
    return mom12_1, mom_multi

# ---------- 3. 引擎 (与 v7 一致) ----------
CAP0 = 3000.0
COMM = lambda sh: max(abs(sh)*0.01, 1.5)

def metrics(equity, dates, first_trade_idx):
    eq = np.array(equity, dtype=float)
    rets = np.diff(eq)/eq[:-1]
    total = eq[-1]/eq[0]-1
    years_full = len(eq)/252.0
    cagr_full = (eq[-1]/eq[0])**(1/years_full)-1
    if first_trade_idx and first_trade_idx < len(eq)-1:
        ae = eq[first_trade_idx:]; yrs_a=(len(ae))/252.0
        cagr_a = (ae[-1]/ae[0])**(1/yrs_a)-1 if yrs_a>0 else 0
    else:
        cagr_a = cagr_full
    sharpe = np.mean(rets)/np.std(rets)*np.sqrt(252) if np.std(rets)>0 else 0
    peak = np.maximum.accumulate(eq); mdd=(eq-peak)/peak
    return dict(final=round(eq[-1],0), total=round(total*100,1),
                cagr_full=round(cagr_full*100,1), cagr_active=round(cagr_a*100,1),
                sharpe=round(sharpe,2), mdd=round(mdd.min()*100,1))

def backtest(close, score_func, topk=2, stop=0.0, recover=False,
             reclaim=0.90, rebal=21, take_profit=0.0, regime=None, safe_prices=None):
    N = len(close)
    cash = CAP0; pos={}; peak={}; entry={}; stopped_peak={}
    safe_shares = 0; in_safe = False
    equity=[]; first_trade=None
    for i in range(N):
        price = close.iloc[i]
        # ---- 市场牛熊过滤 ----
        # regime=False 熊市: 清股票改持安全资产(VOO, 若提供) 或空仓; regime=True 牛市: 退出安全资产回股票
        if regime is not None:
            bear = not regime[i]
            if bear:
                if safe_prices is not None and not in_safe:
                    for c in list(pos.keys()):
                        cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    peak.clear(); entry.clear(); stopped_peak.clear()
                    sp=safe_prices[i]; sh=int(cash//sp)
                    if sh>0: cash-=sh*sp+COMM(sh); safe_shares=sh; in_safe=True
                elif safe_prices is None:
                    for c in list(pos.keys()):
                        cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    peak.clear(); entry.clear(); stopped_peak.clear()
                    equity.append(cash); continue
            else:
                if in_safe:
                    sp=safe_prices[i]; cash+=safe_shares*sp-COMM(safe_shares); safe_shares=0; in_safe=False
            if in_safe:
                mv=safe_shares*safe_prices[i]; equity.append(cash+mv); continue
        for c in list(pos.keys()):
            p=price[c]; ep=entry[c]
            peak[c]=max(peak.get(c,p),p)
            if stop>0 and p<=peak[c]*(1-stop):
                sh=pos.pop(c); cash+=sh*p-COMM(sh)
                stopped_peak[c]=peak[c]; peak.pop(c,None); entry.pop(c,None)
            elif take_profit>0 and p>=ep*(1+take_profit):
                sh=pos.pop(c); cash+=sh*p-COMM(sh)
                peak.pop(c,None); entry.pop(c,None)
        if recover:
            for c in list(stopped_peak.keys()):
                if c not in pos and price[c] >= stopped_peak[c]*reclaim:
                    budget = cash/topk; sh=int(budget/price[c])
                    if sh>0 and cash>=sh*price[c]:
                        cash-=sh*price[c]+COMM(sh); pos[c]=sh
                        entry[c]=price[c]; peak[c]=price[c]; stopped_peak.pop(c,None)
        if i>=252 and (i-252)%rebal==0:
            sc=score_func(i).dropna().sort_values(ascending=False)
            picks=sc.index[:topk].tolist()
            for c in list(pos.keys()):
                cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
            peak.clear(); entry.clear(); stopped_peak.clear()
            for c in picks:
                sh=int((cash/topk)//price[c])
                if sh>0:
                    cash-=sh*price[c]+COMM(sh); pos[c]=sh; entry[c]=price[c]; peak[c]=price[c]
                    if first_trade is None: first_trade=i
        mv=sum(pos.get(c,0)*price[c] for c in pos)
        equity.append(cash+mv)
    return np.array(equity), first_trade

# ---------- 4. 分牛熊阶段 ----------
PHASES = [
    ("2018牛市(至顶)", "2018-01-02", "2018-09-20", "bull"),
    ("2018回落(熊)",   "2018-09-21", "2018-12-24", "bear"),
    ("2019-20.2牛市",  "2019-01-01", "2020-02-19", "bull"),
    ("2020崩盘(熊)",   "2020-02-19", "2020-03-23", "bear"),
    ("2020-21牛市",    "2020-03-24", "2021-12-31", "bull"),
    ("2022熊市(熊)",   "2022-01-03", "2022-10-12", "bear"),
    ("2023-26牛市",    "2023-01-01", "2026-09-10", "bull"),
]

def phase_stats(dates, eq, voo_eq):
    out=[]
    darr = pd.to_datetime(dates)
    for name,s,e,kind in PHASES:
        mask = (darr>=s)&(darr<=e)
        idx = np.where(mask)[0]
        if len(idx)==0:
            out.append((name,kind,None,None,None)); continue
        i0,i1=idx[0],idx[-1]
        s_ret = eq[i1]/eq[i0]-1 if eq[i0]>0 else None
        v_ret = voo_eq[i1]/voo_eq[i0]-1 if voo_eq[i0]>0 else None
        # 阶段内最大回撤 (策略)
        seg = eq[i0:i1+1]
        if len(seg)>1:
            pk=np.maximum.accumulate(seg); dd=(seg-pk)/pk; mdd=dd.min()*100
        else: mdd=None
        out.append((name,kind,
                    round(s_ret*100,1) if s_ret is not None else None,
                    round(v_ret*100,1) if v_ret is not None else None,
                    round(mdd,1) if mdd is not None else None))
    return out

# ---------- 5. 运行 ----------
dates, close = load_panel(UNI)
mom12_1, mom_multi = build_factors(close)
# VOO 基准 (买入持有)
_, voo_close = load_panel(["US.VOO"])
voo_full = pd.DataFrame({"US.VOO": voo_close["US.VOO"].reindex(dates).ffill()})
voo_eq = (voo_full["US.VOO"].values / voo_full["US.VOO"].values[0] * CAP0)
# 牛熊过滤: VOO 收盘价 > 200日均线 = 牛市(in market), 否则熊市(空仓)
voo_ser = voo_full["US.VOO"].values
voo_ma200 = pd.Series(voo_ser).rolling(200).mean().values
regime = voo_ser > voo_ma200   # boolean array, 与 dates 等长

sf_A1 = lambda i: mom_multi.iloc[i]
sf_12 = lambda i: mom12_1.iloc[i]

configs = [
    ("A1 Top2 月频 无止损",            sf_A1, 2, 0.0,  False, 0.90, 21, 0.0, None, None),
    ("A1 Top2 月频 +15%止损(无回补)",   sf_A1, 2, 0.15, False, 0.90, 21, 0.0, None, None),
    ("A1 Top2 月频 +15%止损+回收0.90",  sf_A1, 2, 0.15, True,  0.90, 21, 0.0, None, None),
    ("A1 Top3 月频 无止损",            sf_A1, 3, 0.0,  False, 0.90, 21, 0.0, None, None),
    ("A1 Top2 周频 无止损",            sf_A1, 2, 0.0,  False, 0.90, 5,  0.0, None, None),
    ("经典12-1 Top2 月频 无止损",       sf_12, 2, 0.0,  False, 0.90, 21, 0.0, None, None),
    ("A1 Top2 月频 + 200DMA牛熊过滤",   sf_A1, 2, 0.0,  False, 0.90, 21, 0.0, regime, None),
    ("经典12-1 Top2 月频 + 200DMA过滤", sf_12, 2, 0.0,  False, 0.90, 21, 0.0, regime, None),
    ("A1 Top2 月频 +15%止损 + 200DMA过滤", sf_A1, 2, 0.15, False, 0.90, 21, 0.0, regime, None),
    ("A1 Top2 月频 + 200DMA过滤(熊持VOO)", sf_A1, 2, 0.0, False, 0.90, 21, 0.0, regime, voo_ser),
    ("经典12-1 Top2 月频 + 200DMA过滤(熊持VOO)", sf_12, 2, 0.0, False, 0.90, 21, 0.0, regime, voo_ser),
    ("A1 Top2 月频 +15%止损 + 200DMA过滤(熊持VOO)", sf_A1, 2, 0.15, False, 0.90, 21, 0.0, regime, voo_ser),
]

results=[]
print("="*100)
print(f"长周期回测区间: {dates[0].date()} ~ {dates[-1].date()}  ({len(dates)} 交易日)  起点 $3000")
print(f"VOO 全期: ${voo_eq[-1]:.0f}  总收益={(voo_eq[-1]/voo_eq[0]-1)*100:.1f}%")
print("="*100)
for name,sf,tk,st,rec,rc,rb,tp,rg,sp in configs:
    eq, ft = backtest(close, sf, topk=tk, stop=st, recover=rec, reclaim=rc, rebal=rb, take_profit=tp, regime=rg, safe_prices=sp)
    m = metrics(eq, dates, ft)
    ph = phase_stats(dates, eq, voo_eq)
    results.append(dict(name=name, metrics=m, phases=ph, first_trade=str(dates[ft].date()) if ft else None))
    print(f"\n### {name}")
    print(f"  终值 ${m['final']:.0f} | 总收益 {m['total']}% | 年化和 {m['cagr_full']}% | 活跃年化 {m['cagr_active']}% | 夏普 {m['sharpe']} | 最大回撤 {m['mdd']}%")
    print(f"  首笔交易: {results[-1]['first_trade']}")
    print(f"  {'阶段':<14}{'类型':<6}{'策略%':>9}{'VOO%':>9}{'阶段最大回撤%':>15}")
    for nm,kind,sr,vr,md in ph:
        print(f"  {nm:<14}{kind:<6}{str(sr):>9}{str(vr):>9}{str(md):>15}")

json.dump(results, open(OUT_JSON,"w"), ensure_ascii=False, indent=2, default=str)
print("\nSAVED", OUT_JSON)
