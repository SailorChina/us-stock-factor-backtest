# -*- coding: utf-8 -*-
"""
独立均线系统 & 其他系统 · 牛熊长周期对照测试 (2018-01 ~ 2026-09)
=================================================================
在同一套数据(data_kline_long/)与同一引擎上, 测试"纯均线"作为独立信号,
并与已知动量策略(V8)对照。同时加入突破系统 / 双动量等"其他系统"。

纯均线系统的几种形态:
  A. 均线距离选股:   score = close/MAx - 1, Top2/Top3 (趋势强度排序)
  B. 趋势跟踪组合:   持有所有 close>MA200 的个股, 等权 (纯择时, 无选股)
  C. 金叉选股:       只在 MA50>MA200(金叉状态) 的个股里按均线距离 Top2
  D. 均线斜率选股:   score = MA200 的 20 日斜率
其他系统:
  E. 突破系统:       score = close / 55日新高 - 1 (唐奇安/海龟式)
  F. 双动量:         12-1 动量, 但只在个股处于自身 MA200 之上(绝对动量正)才入选
基准:
  G. 经典12-1动量 Top2 (V8 已知 +2967%)
  H. VOO 买入持有
  I. VOO 200日均线择时(跌破空仓) -- 纯指数均线系统
"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
OUT_JSON = os.path.join(BASE, "_ma_results.json")

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

# ---------- 2. 引擎 (与 V8 一致) ----------
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

# 趋势跟踪组合: 在 rebalance 时, 等权持有 elig_func(i) 返回的个股列表 (纯择时, 无 TopK 选股)
def backtest_tf(close, elig_func, rebal=21, regime=None, safe_prices=None):
    N = len(close)
    cash=CAP0; pos={}
    safe_shares=0; in_safe=False
    equity=[]; first_trade=None
    for i in range(N):
        price=close.iloc[i]
        if regime is not None:
            bear = not regime[i]
            if bear:
                if safe_prices is not None and not in_safe:
                    for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    sp=safe_prices[i]; sh=int(cash//sp)
                    if sh>0: cash-=sh*sp+COMM(sh); safe_shares=sh; in_safe=True
                elif safe_prices is None:
                    for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    equity.append(cash); continue
            else:
                if in_safe:
                    sp=safe_prices[i]; cash+=safe_shares*sp-COMM(safe_shares); safe_shares=0; in_safe=False
            if in_safe:
                equity.append(cash+safe_shares*safe_prices[i]); continue
        if i>=252 and (i-252)%rebal==0:
            elig=elig_func(i)
            for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
            k=len(elig)
            if k>0:
                for c in elig:
                    sh=int((cash/k)//price[c])
                    if sh>0:
                        cash-=sh*price[c]+COMM(sh); pos[c]=sh
                        if first_trade is None: first_trade=i
        mv=sum(pos.get(c,0)*price[c] for c in pos)
        equity.append(cash+mv)
    return np.array(equity), first_trade

# ---------- 3. 分牛熊阶段 ----------
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
        seg = eq[i0:i1+1]
        if len(seg)>1:
            pk=np.maximum.accumulate(seg); dd=(seg-pk)/pk; mdd=dd.min()*100
        else: mdd=None
        out.append((name,kind,
                    round(s_ret*100,1) if s_ret is not None else None,
                    round(v_ret*100,1) if v_ret is not None else None,
                    round(mdd,1) if mdd is not None else None))
    return out

# ---------- 4. 数据 & 因子 ----------
dates, close = load_panel(UNI)
pct = lambda a,n: a/a.shift(n)-1.0
mom12_1 = close.shift(21)/close.shift(252)-1.0   # 经典 12-1 动量
m1=pct(close,21); m3=pct(close,63); m6=pct(close,126); m12=pct(close,252)
mom_multi = 0.1*m1 + 0.2*m3 + 0.3*m6 + 0.4*m12    # A1

# 均线
ma50 = close.rolling(50).mean()
ma200 = close.rolling(200).mean()
above50 = close > ma50
above200 = close > ma200
golden = ma50 > ma200            # 金叉状态 (MA50 在 MA200 之上)
ma_dist50 = close/ma50 - 1.0     # 均线距离 (趋势强度)
ma_dist200 = close/ma200 - 1.0
ma_slope200 = ma200.pct_change(20)   # MA200 的 20 日斜率
donchian = close/close.rolling(55).max() - 1.0   # 距 55 日新高 (突破系统)

# VOO 基准 & 牛熊过滤
_, voo_close = load_panel(["US.VOO"])
voo_full = pd.DataFrame({"US.VOO": voo_close["US.VOO"].reindex(dates).ffill()})
voo_ser = voo_full["US.VOO"].values
voo_eq = voo_ser / voo_ser[0] * CAP0
voo_ma200 = pd.Series(voo_ser).rolling(200).mean().values
regime = voo_ser > voo_ma200      # True=牛市(在场内)

# VOO 200日均线择时(纯指数均线系统, 跌破空仓)
voo_ret = np.diff(voo_ser)/voo_ser[:-1]
voo_timing = np.array([CAP0])
for i in range(1,len(voo_ser)):
    if regime[i-1]:   # 用上一日信号决定今日是否持有
        voo_timing = np.append(voo_timing, voo_timing[-1]*(1+voo_ret[i-1]))
    else:
        voo_timing = np.append(voo_timing, voo_timing[-1])   # 空仓, 现金不动

# ---------- 5. 配置 ----------
sf_ma50  = lambda i: ma_dist50.iloc[i]
sf_ma200 = lambda i: ma_dist200.iloc[i]
sf_slope = lambda i: ma_slope200.iloc[i]
sf_golden= lambda i: ma_dist50.iloc[i].where(golden.iloc[i])   # 仅金叉状态下按距离排序
sf_break = lambda i: donchian.iloc[i]
sf_dual  = lambda i: mom12_1.iloc[i].where(above200.iloc[i])   # 动量 + 绝对动量门(个股在MA200上)
sf_mom12 = lambda i: mom12_1.iloc[i]
elig_above200 = lambda i: [c for c in UNI if bool(above200.iloc[i][c])]
elig_golden   = lambda i: [c for c in UNI if bool(golden.iloc[i][c])]

configs = []  # (name, kind, fn_or_params, ...)
# --- 纯均线系统 (A 均线距离选股) ---
configs += [
    ("[均线] MA50距离 Top2 月频",          "bt", sf_ma50,  2, 0.0, False, 0.90, 21, 0.0, None, None),
    ("[均线] MA200距离 Top2 月频",         "bt", sf_ma200, 2, 0.0, False, 0.90, 21, 0.0, None, None),
    ("[均线] MA50距离 Top3 月频",          "bt", sf_ma50,  3, 0.0, False, 0.90, 21, 0.0, None, None),
    ("[均线] MA50距离 Top2 +200DMA过滤",    "bt", sf_ma50,  2, 0.0, False, 0.90, 21, 0.0, regime, None),
    ("[均线] MA50距离 Top2 +200DMA过滤(熊持VOO)", "bt", sf_ma50, 2, 0.0, False, 0.90, 21, 0.0, regime, voo_ser),
    # --- (C 金叉选股) ---
    ("[均线] 金叉状态+MA50距离 Top2 月频",  "bt", sf_golden, 2, 0.0, False, 0.90, 21, 0.0, None, None),
    # --- (D 均线斜率选股) ---
    ("[均线] MA200斜率 Top2 月频",          "bt", sf_slope, 2, 0.0, False, 0.90, 21, 0.0, None, None),
    # --- (B 趋势跟踪组合) ---
    ("[趋势组合] 持有所有>MA200等权 月频",   "tf", elig_above200, 21, None, None, None, None, None, None),
    ("[趋势组合] 持有所有金叉个股等权 月频", "tf", elig_golden,   21, None, None, None, None, None, None),
    ("[趋势组合] >MA200等权 +200DMA(熊持VOO)","tf", elig_above200, 21, None, None, None, None, regime, voo_ser),
    # --- 同款风控对照 (15%止损 + 200DMA熊持VOO) ---
    ("[均线] 金叉+MA50距离 Top2 +15%止损+200DMA(熊持VOO)", "bt", sf_golden, 2, 0.15, False, 0.90, 21, 0.0, regime, voo_ser),
    ("[均线] MA50距离 Top2 +15%止损+200DMA(熊持VOO)", "bt", sf_ma50,  2, 0.15, False, 0.90, 21, 0.0, regime, voo_ser),
    # --- 其他系统 ---
    ("[其他] 突破(Donchian55距离) Top2 月频", "bt", sf_break, 2, 0.0, False, 0.90, 21, 0.0, None, None),
    ("[其他] 双动量(12-1 + 个股MA200门) Top2","bt", sf_dual,  2, 0.0, False, 0.90, 21, 0.0, None, None),
    # --- 基准 (同款风控) ---
    ("[基准] 经典12-1 Top2 +15%止损+200DMA(熊持VOO)", "bt", sf_mom12, 2, 0.15, False, 0.90, 21, 0.0, regime, voo_ser),
    # --- 基准 ---
    ("[基准] 经典12-1动量 Top2 月频 无止损", "bt", sf_mom12, 2, 0.0, False, 0.90, 21, 0.0, None, None),
]

results=[]
print("="*110)
print(f"独立均线/其他系统对照 · 区间 {dates[0].date()} ~ {dates[-1].date()}  ({len(dates)} 交易日)  起点 $3000")
print(f"VOO 买入持有: ${voo_eq[-1]:.0f} (+{(voo_eq[-1]/voo_eq[0]-1)*100:.1f}%)  | VOO 200DMA择时(空仓): ${voo_timing[-1]:.0f} (+{(voo_timing[-1]/voo_timing[0]-1)*100:.1f}%)")
print("="*110)
for cfg in configs:
    name, kind = cfg[0], cfg[1]
    if kind=="bt":
        tk, st, rec, rc, rb, tp, rg, sp = cfg[3:]
        eq, ft = backtest(close, cfg[2], topk=tk, stop=st, recover=rec, reclaim=rc, rebal=rb, take_profit=tp, regime=rg, safe_prices=sp)
    else:
        elig, rb = cfg[2], cfg[3]
        rg, sp = cfg[8], cfg[9]
        eq, ft = backtest_tf(close, elig, rebal=rb, regime=rg, safe_prices=sp)
    m = metrics(eq, dates, ft)
    ph = phase_stats(dates, eq, voo_eq)
    results.append(dict(name=name, metrics=m, phases=ph, first_trade=str(dates[ft].date()) if ft else None))
    print(f"\n### {name}")
    print(f"  终值 ${m['final']:.0f} | 总收益 {m['total']}% | 年化和 {m['cagr_full']}% | 活跃年化 {m['cagr_active']}% | 夏普 {m['sharpe']} | 最大回撤 {m['mdd']}%")
    print(f"  首笔交易: {results[-1]['first_trade']}")
    print(f"  {'阶段':<14}{'类型':<6}{'策略%':>9}{'VOO%':>9}{'阶段最大回撤%':>15}")
    for nm,kind2,sr,vr,md in ph:
        print(f"  {nm:<14}{kind2:<6}{str(sr):>9}{str(vr):>9}{str(md):>15}")

# VOO 基准 & 择时 作为结果条目
results.append(dict(name="[基准] VOO 买入持有", metrics=metrics(voo_eq, dates, 0), phases=phase_stats(dates, voo_eq, voo_eq), first_trade=str(dates[0].date())))
results.append(dict(name="[基准] VOO 200DMA择时(空仓)", metrics=metrics(voo_timing, dates, 0), phases=phase_stats(dates, voo_timing, voo_eq), first_trade=str(dates[0].date())))

json.dump(results, open(OUT_JSON,"w"), ensure_ascii=False, indent=2, default=str)
print("\nSAVED", OUT_JSON)
