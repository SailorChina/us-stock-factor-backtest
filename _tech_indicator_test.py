# -*- coding: utf-8 -*-
"""对照实验：MACD / 短期反转 / 个股200DMA过滤 是否能改进动量策略。
数据：data_kline_long/ 37只大盘股 + VOO，2018-01~2026-09，本地缓存不耗额度。
"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LD   = os.path.join(BASE, "data_kline_long")
CAP0 = 3000.0
COMM = lambda sh: max(abs(sh)*0.01, 1.5)

# ---------- 1. 读数据（正确用 time_key 建索引）----------
mi   = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]

panel = {}
for c in UNI:
    df = pd.read_csv(f"{LD}/{c.replace('.','_')}.csv", parse_dates=["time_key"]).sort_values("time_key").set_index("time_key")
    panel[c] = df
dates = sorted(set().union(*[set(d.index) for d in panel.values()]))
dates = pd.to_datetime(dates)
close = pd.DataFrame({c: panel[c]["close"].reindex(dates).ffill() for c in UNI})
N = len(dates)

# ---------- 2. 构造各类信号 ----------
def pct(a, n): return a / a.shift(n) - 1.0
m1  = pct(close, 21)
m3  = pct(close, 63)
m6  = pct(close, 126)
m12 = pct(close, 252)
mom12_1 = close.shift(21)/close.shift(252) - 1.0
A1 = 0.1*m1 + 0.2*m3 + 0.3*m6 + 0.4*m12

# MACD(12,26,9) 柱状图（MACD线 - 信号线），横截面选股用 z-score
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
macd  = ema12 - ema26
signal= macd.ewm(span=9, adjust=False).mean()
macd_hist = macd - signal   # 柱状图：正值=动能向上
def z(x):
    sd = x.std(); sd = sd.replace(0, np.nan)
    return (x - x.mean()) / sd
z_mom  = z(mom12_1)
z_macd = z(macd_hist)
z_rev  = z(m1)            # 1月收益（反转因子：近期输家未来反弹）
# 组合信号
blend_macd = z_mom + z_macd                      # 动量 + MACD
blend_rev  = z_mom - z_rev                       # 动量 - 短期反转（反转取反）

# VOO 牛熊 + 个股200DMA
_voo_df = pd.read_csv(f"{LD}/US_VOO.csv", parse_dates=["time_key"]).sort_values("time_key").set_index("time_key")
voo = _voo_df["close"].reindex(dates).ffill()
voo_ma200 = voo.rolling(200).mean()
regime = (voo > voo_ma200).values                # True=牛市
stock_ma200 = close.rolling(200).mean()           # 个股自身200DMA

# ---------- 3. 回测引擎 ----------
def backtest(score, topk=2, stop=0.0, recover=False, reclaim=0.90,
             rebal=21, regime_filter=False, stock_ma200_filter=False):
    cash = CAP0; pos={}; peak={}; entry={}; stopped_peak={}
    equity=[]; first_trade=None
    for i in range(N):
        p = close.iloc[i]
        # 牛熊过滤：熊市清仓空仓
        if regime_filter and not regime[i]:
            for c in list(pos): cash += pos.pop(c)*p[c]-COMM(pos.get(c,0))
            peak.clear(); entry.clear(); stopped_peak.clear()
            equity.append(cash); continue
        # 持仓期 止损
        for c in list(pos):
            pk = max(peak.get(c, p[c]), p[c]); peak[c]=pk
            if stop>0 and p[c] <= pk*(1-stop):
                sh=pos.pop(c); cash += sh*p[c]-COMM(sh)
                stopped_peak[c]=pk; peak.pop(c,None); entry.pop(c,None)
            elif stop>0 and p[c] >= entry[c]*(1+0.25):
                sh=pos.pop(c); cash += sh*p[c]-COMM(sh)
                peak.pop(c,None); entry.pop(c,None)
        # 恢复再入场
        if recover:
            for c in list(stopped_peak):
                if c not in pos and p[c] >= stopped_peak[c]*reclaim:
                    bud = cash/topk; sh=int(bud/p[c])
                    if sh>0 and cash>=sh*p[c]:
                        cash-=sh*p[c]+COMM(sh); pos[c]=sh; entry[c]=p[c]; peak[c]=p[c]
                        stopped_peak.pop(c,None)
        # 调仓
        if i>=252 and (i-252)%rebal==0:
            sc = score.iloc[i].dropna()
            if stock_ma200_filter:
                above = (close.iloc[i] > stock_ma200.iloc[i])
                sc = sc[sc.index.isin(above[above].index)]
            picks = sc.sort_values(ascending=False).index[:topk].tolist()
            if len(picks) < topk:
                picks = sc.sort_values(ascending=False).index[:len(picks)].tolist()
            for c in list(pos):
                sh=pos.pop(c); cash += sh*p[c]-COMM(sh)
            peak.clear(); entry.clear(); stopped_peak.clear()
            for c in picks:
                sh=int((cash/topk)//p[c])
                if sh>0: cash-=sh*p[c]+COMM(sh); pos[c]=sh; entry[c]=p[c]; peak[c]=p[c]
            if first_trade is None and (pos or cash<CAP0): first_trade=i
        equity.append(cash + sum(pos.get(c,0)*p[c] for c in pos))
    eq = np.array(equity)
    yrs = (N-252)/252
    ret = eq[-1]/eq[0]-1
    cagr = (eq[-1]/eq[0])**(1/yrs)-1
    sharpe = (eq[1:]/eq[:-1]-1).mean()/(eq[1:]/eq[:-1]-1).std()*np.sqrt(252)
    pk = np.maximum.accumulate(eq); mdd = ((eq-pk)/pk).min()*100
    return dict(final=eq[-1], total=ret*100, cagr=cagr*100, sharpe=sharpe, mdd=mdd)

# ---------- 4. 配置矩阵 ----------
configs = [
    # 名称, 信号, topk, stop, regime, stock_ma200_filter
    ("经典12-1 Top2 (基准)",        mom12_1, 2, 0.0, False, False),
    ("A1多周期 Top2",               A1,      2, 0.0, False, False),
    ("MACD柱状图 Top2 (纯技术)",     macd_hist,2, 0.0, False, False),
    ("动量+MACD z融合 Top2",         blend_macd,2,0.0, False, False),
    ("动量-1月反转 z融合 Top2",      blend_rev, 2,0.0, False, False),
    ("动量 Top2 + 个股200DMA过滤",   mom12_1, 2, 0.0, False, True),
    ("A1 Top2 + 个股200DMA过滤",     A1,      2, 0.0, False, True),
    # 实盘稳健版（叠加止损+牛熊），看叠加层贡献
    ("动量 Top2 +15%止损+牛熊",      mom12_1, 2, 0.15,True,  False),
    ("动量 Top2 +15%止损+牛熊+个股200DMA", mom12_1,2,0.15,True, True),
]

print("="*96)
print(f"对照实验区间: {dates[0].date()} ~ {dates[-1].date()} ({N}日) 起点 $3000  月度调仓")
print("="*96)
results=[]
hdr=f"{'策略':<30}{'终值':>9}{'总收益%':>9}{'年化%':>8}{'夏普':>8}{'最大回撤%':>11}"
print(hdr); print("-"*96)
for name, sc, tk, st, rg, sm in configs:
    r = backtest(sc, topk=tk, stop=st, regime_filter=rg, stock_ma200_filter=sm)
    results.append(dict(name=name, **r))
    print(f"{name:<30}{r['final']:>9.0f}{r['total']:>9.1f}{r['cagr']:>8.1f}{r['sharpe']:>8.2f}{r['mdd']:>11.1f}")

json.dump(results, open(os.path.join(BASE,"_tech_indicator_results.json"),"w"), ensure_ascii=False, indent=2)
print("\n已保存 _tech_indicator_results.json")
