# -*- coding: utf-8 -*-
"""
美股因子策略 · 多维升级实验 (v6)
在 v5 最优基础 (Momentum top2 + 15%追踪止损 + 恢复再入场) 之上，
从因子层 / 组合层 / 择时层 / 再平衡层做全新升级测试。
数据：本地 data_kline/ 缓存 CSV (53只, 758交易日, 不消耗富途额度)
"""
import os, glob, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
OUT  = os.path.join(BASE, "_upgrade_results.json")

# ---------- 1. 加载数据 ----------
def is_etf(name):
    n = (name or "").upper()
    kw = ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "]
    return any(k in n for k in kw)

mi = json.load(open(os.path.join(BASE,"market_info.json")))
fetched = json.load(open(os.path.join(BASE,"fetched_codes.json")))

uni = [c for c in fetched
       if not is_etf(mi.get(c,{}).get("name",""))
       and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]
print("Universe (%d):" % len(uni), uni)

panel = {}
for c in uni:
    f = os.path.join(BASE,"data_kline", c.replace(".","_")+".csv")
    df = pd.read_csv(f)
    df["time_key"] = pd.to_datetime(df["time_key"])
    df = df.sort_values("time_key").reset_index(drop=True)
    panel[c] = df.set_index("time_key")

# 对齐交易日
all_dates = sorted(set().union(*[set(df.index) for df in panel.values()]))
dates = pd.to_datetime(all_dates)
close = pd.DataFrame({c: panel[c]["close"].reindex(dates).ffill() for c in uni})
high  = pd.DataFrame({c: panel[c]["high"].reindex(dates).ffill() for c in uni})
low   = pd.DataFrame({c: panel[c]["low"].reindex(dates).ffill()  for c in uni})
open_ = pd.DataFrame({c: panel[c]["open"].reindex(dates).ffill() for c in uni})
vol   = pd.DataFrame({c: panel[c]["volume"].reindex(dates).ffill() for c in uni})
N = len(dates)
print("Trading days:", N, dates[0].date(), "->", dates[-1].date())

# QQQ 作为市场择时基准 (若不在 universe 则单独加载)
qqq_file = os.path.join(BASE,"data_kline","US_QQQ.csv")
if os.path.exists(qqq_file):
    qdf = pd.read_csv(qqq_file); qdf["time_key"]=pd.to_datetime(qdf["time_key"])
    qqq = qdf.set_index("time_key")["close"].reindex(dates).ffill().values
else:
    qqq = None

# ---------- 2. 因子计算 ----------
def pct(a, n):
    return a / a.shift(n) - 1.0

# 动量 12-1 (经典 Jegadeesh-Titman: 过去12月剔除最近1月)
mom12_1 = close.shift(21) / close.shift(252) - 1.0
# 多周期动量
m1 = pct(close,21); m3 = pct(close,63); m6 = pct(close,126); m12 = pct(close,252)
mom_multi = 0.1*m1 + 0.2*m3 + 0.3*m6 + 0.4*m12
# 短期反转 (1周)
rev1w = -pct(close,5)
# WQ Alpha1: -corr(open,volume,10)
def wq_alpha1(df_o, df_v, w=10):
    out = df_o.copy()*np.nan
    for c in df_o.columns:
        o = df_o[c]; v = df_v[c]
        out[c] = -o.rolling(w).corr(v)
    return out
wq1 = wq_alpha1(open_, vol)
# LowVol BAB: -vol(63d)
lowvol = -close.pct_change().rolling(63).std()

# ---------- 3. 回测引擎 ----------
CAP0 = 3000.0
COMM = lambda sh: max(abs(sh)*0.01, 1.5)

def metrics(equity):
    eq = np.array(equity, dtype=float)
    rets = np.diff(eq) / eq[:-1]
    total = eq[-1]/eq[0]-1
    years = N/252.0
    cagr = (eq[-1]/eq[0])**(1/years)-1
    sharpe = np.mean(rets)/np.std(rets)*np.sqrt(252) if np.std(rets)>0 else 0
    peak = np.maximum.accumulate(eq)
    mdd = (eq-peak)/peak
    return dict(final=round(eq[-1],0), total=round(total*100,1), cagr=round(cagr*100,1),
                sharpe=round(sharpe,2), mdd=round(mdd.min()*100,1))

def backtest(score_func, topk=2, stop=0.15, recover=True, weighting="equal",
             rebal=21, mkt_timer=False, lowvol_flt=False, take_profit=0.0,
             long_short=False, verbose=False):
    """事件驱动日级回测。score_func(date_idx)->pd.Series(分值, 仅 universe)"""
    cash = CAP0
    pos = {}          # code -> shares
    peak = {}         # code -> 持仓以来最高收盘价
    stop_price = {}   # code -> 止损触发价 (用于恢复)
    equity = []
    short = {}        # code -> (shares_short, entry_price) 仅 long_short
    short_cash = 0.0  # 卖空保证金(简化)
    for i in range(N):
        price = close.iloc[i]
        # ---- 盘中：止损 / 恢复 / 止盈 ----
        for c in list(pos.keys()):
            p = price[c]
            if c in peak: peak[c] = max(peak[c], p)
            else: peak[c] = p
            # 止损
            if stop>0 and p <= peak[c]*(1-stop):
                sh = pos.pop(c)
                cash += sh*p - COMM(sh)
                stop_price[c] = peak[c]*(1-stop)
                peak.pop(c, None)
                if verbose: print(dates[i].date(),"STOP",c,round(p,1))
            # 止盈 (移动)
            elif take_profit>0 and peak.get(c,0)>0 and p >= peak[c]*(1+take_profit):
                sh = pos.pop(c)
                cash += sh*p - COMM(sh)
                peak.pop(c, None)
        # 恢复再入场 (v5: 涨回止损触发价即买回)
        if recover:
            for c in list(stop_price.keys()):
                if c not in pos and price[c] >= stop_price[c]:
                    # 用等权目标资金买回
                    budget = cash* (1.0/topk if weighting=="equal" else 1.0/topk)
                    sh = int(budget/price[c])
                    if sh>0 and cash>=sh*price[c]:
                        cash -= sh*price[c]+COMM(sh)
                        pos[c]=sh; peak[c]=price[c]
                        stop_price.pop(c, None)
        # ---- 调仓日 ----
        if i>=252 and (i-252)%rebal==0:
            # 计算分值
            sc = score_func(i)
            if lowvol_flt:
                v = close.pct_change().rolling(63).std().iloc[i]
                keep = v[v.notna()].rank() <= len(v[v.notna()])*2/3  # 剔除高波动1/3
                sc = sc[sc.index.isin(keep[keep].index)]
            # 市场择时
            if mkt_timer and qqq is not None:
                if qqq[i] <= pd.Series(qqq).rolling(200).mean().iloc[i]:
                    # 清仓
                    for c in list(pos.keys()):
                        cash += pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    peak.clear(); stop_price.clear()
                    sc = sc*0  # 不买入
            if long_short:
                ranked = sc.dropna().sort_values(ascending=False)
                longs = ranked.index[:topk].tolist()
                shorts = ranked.index[-topk:].tolist()
                # 平旧
                for c in list(pos.keys()):
                    cash += pos.pop(c)*price[c]-COMM(pos.get(c,0))
                for c in list(short.keys()):
                    sh,ep = short.pop(c); short_cash += (ep-price[c])*sh  # 回补盈利
                peak.clear(); stop_price.clear()
                budget = cash/2.0
                for c in longs:
                    sh=int(budget/price[c]/topk); 
                    if sh>0: cash-=sh*price[c]+COMM(sh); pos[c]=sh; peak[c]=price[c]
                for c in shorts:
                    sh=int(budget/price[c]/topk)
                    if sh>0: short[c]=(sh,price[c])
            else:
                # 多头 topk
                ranked = sc.dropna().sort_values(ascending=False)
                picks = ranked.index[:topk].tolist()
                # 清旧
                for c in list(pos.keys()):
                    cash += pos.pop(c)*price[c]-COMM(pos.get(c,0))
                peak.clear(); stop_price.clear()
                # 权重
                if weighting=="riskparity":
                    v = close.pct_change().rolling(63).std().iloc[i][picks]
                    w = (1.0/v)/(1.0/v).sum()
                else:
                    w = pd.Series(1.0/topk, index=picks)
                for c in picks:
                    budget = cash*w[c]
                    sh = int(budget/price[c])
                    if sh>0:
                        cash -= sh*price[c]+COMM(sh)
                        pos[c]=sh; peak[c]=price[c]
        # ---- 估值 ----
        mv = sum(pos.get(c,0)*price[c] for c in pos)
        eq = cash + mv + (sum((ep-price[c])*sh for c,(sh,ep) in short.items()) if long_short else 0)
        equity.append(eq)
    return equity

# ---------- 4. 实验矩阵 ----------
def score_mom12(i):   return mom12_1.iloc[i]
def score_multi(i):   return mom_multi.iloc[i]
def score_momrev(i):  return (mom12_1.iloc[i] + 0.5*rev1w.iloc[i])
def score_wq1(i):     return wq1.iloc[i]
def score_lowvol(i):  return lowvol.iloc[i]

# IC 加权集成 (时序滚动 IC: 每个交易日横截面 spearman IC)
fwd_ret = close.pct_change(21).shift(-21)
def ic_series_over_time(factor_df):
    arr=[]
    for i in range(N):
        fv=factor_df.iloc[i]; rv=fwd_ret.iloc[i]
        m=fv.notna()&rv.notna()
        if m.sum()<8: arr.append(np.nan); continue
        arr.append(fv[m].corr(rv[m], method="spearman"))
    return pd.Series(arr, index=close.index).rolling(126, min_periods=60).mean()
factors_ic = {"mom":mom12_1,"wq1":wq1,"lv":lowvol}
ics = {k: ic_series_over_time(f) for k,f in factors_ic.items()}

def score_icens(i):
    w = pd.Series({k: max(ics[k].iloc[i] if pd.notna(ics[k].iloc[i]) else 0, 0) for k in ics})
    if w.sum()==0: w = pd.Series(1.0/len(ics), index=list(ics))
    w = w/w.sum()
    s = sum(w[k]*factors_ic[k].iloc[i] for k in factors_ic)
    return s

# 市值分层
caps = pd.Series({c: mi[c]["total_market_val"] for c in uni})
def score_sizetier(i):
    sc = mom12_1.iloc[i]
    tier = (caps>=500e9).astype(int)
    r = sc*0
    for t in [0,1]:
        idx = tier[tier==t].index
        r[idx] = sc[idx].rank()
    return r

experiments = [
    ("CTRL 无止损 (Mom12-1 top2, 控制组)",   dict(score_func=score_mom12, stop=0.0, recover=False)),
    ("BASE (Mom12-1 top2, 15%止损+恢复)", dict(score_func=score_mom12)),
    ("A1 多周期动量融合 top2",               dict(score_func=score_multi)),
    ("A2 动量+1周反转 top2",                 dict(score_func=score_momrev)),
    ("A3 IC加权集成 top2",                   dict(score_func=score_icens)),
    ("B1 风险平价加权 (替代等权)",            dict(score_func=score_mom12, weighting="riskparity")),
    ("B2 市值分层排名 top2",                 dict(score_func=score_sizetier)),
    ("C1 市场择时过滤 (QQQ>MA200)",          dict(score_func=score_mom12, mkt_timer=True)),
    ("C2 低波动预筛 (剔除高波1/3)",          dict(score_func=score_mom12, lowvol_flt=True)),
    ("D1 周度调仓 (替代月度)",               dict(score_func=score_mom12, rebal=5)),
    ("D2 移动止盈 +25% (对称)",              dict(score_func=score_mom12, take_profit=0.25)),
    ("E1 多空组合 (多top2/空bottom2)",        dict(score_func=score_mom12, long_short=True)),
    ("F1 BASE+风险平价+择时 (组合最优)",       dict(score_func=score_mom12, weighting="riskparity", mkt_timer=True)),
    ("F2 BASE+多周期+风险平价",              dict(score_func=score_multi, weighting="riskparity")),
]

results = []
for name, kw in experiments:
    eq = backtest(**kw)
    m = metrics(eq)
    m["name"]=name
    results.append(m)
    print(f"{name:42s} final=${m['final']:>10.0f}  tot={m['total']:>7.1f}%  cagr={m['cagr']:>6.1f}%  sharpe={m['sharpe']:>4.2f}  mdd={m['mdd']:>6.1f}%")

# VOO 基准
if "US.VOO" in [c.replace(".","_") for c in []]:
    pass
voo_file = os.path.join(BASE,"data_kline","US_VOO.csv")
if os.path.exists(voo_file):
    vdf=pd.read_csv(voo_file); vdf["time_key"]=pd.to_datetime(vdf["time_key"])
    voo=vdf.set_index("time_key")["close"].reindex(dates).ffill().values
    voo_eq=list(CAP0*voo/voo[0])
    results.append(dict(name="VOO 买入持有 (基准)", **metrics(voo_eq)))
    print(f"{'VOO 买入持有 (基准)':42s} final=${metrics(voo_eq)['final']:>10.0f}  tot={metrics(voo_eq)['total']:>7.1f}%  cagr={metrics(voo_eq)['cagr']:>6.1f}%  sharpe={metrics(voo_eq)['sharpe']:>4.2f}  mdd={metrics(voo_eq)['mdd']:>6.1f}%")

# ---------- 5. 因子衰减检测 ----------
print("\n=== 动量因子 IC 年度衰减 (横截面 spearman IC) ===")
fwd = close.pct_change(21).shift(-21)
ic_year = {}
for y in [2023,2024,2025,2026]:
    mask = pd.Series(dates).dt.year==y
    icv=[]
    for i in range(N):
        if not mask.iloc[i]: continue
        fv=mom12_1.iloc[i]; rv=fwd.iloc[i]; m=fv.notna()&rv.notna()
        if m.sum()<8: continue
        icv.append(fv[m].corr(rv[m], method="spearman"))
    ic_year[y]=round(float(np.nanmean(icv)),3)
    print(f"  {y}: IC={ic_year[y]:.3f}")
results.append(dict(name="__factor_decay__", decay=ic_year))

json.dump(results, open(OUT,"w"), ensure_ascii=False, indent=2)
print("\nSaved ->", OUT)
