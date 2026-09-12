# -*- coding: utf-8 -*-
"""
美股因子策略 · 最优系统 (v7, 含 BUG 修复)
========================================
目标：在本地缓存数据上，构建一套「选股 + 交易策略」完整体系，
起点 $3000、回测近 3 年，输出最优方案。

修复 v6 已知问题：
  1) 移动止盈改用「入场价」而非 running peak (D2 原版永不会触发)
  2) 恢复再入场改用「回收峰值比例」 reclaim，避免止损次日即回补 (原版形同虚设)
  3) CAGR 同时给出「全周期」与「活跃期(首笔交易起)」

数据：data_kline/ 缓存 CSV (不消耗富途额度)
"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
OUT_JSON = os.path.join(BASE, "_optimal_results.json")
OUT_EQ   = os.path.join(BASE, "_optimal_equity.csv")

# ---------- 1. 数据加载 ----------
def is_etf(name):
    n = (name or "").upper()
    kw = ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "]
    return any(k in n for k in kw)

mi = json.load(open(os.path.join(BASE,"market_info.json")))
fetched = json.load(open(os.path.join(BASE,"fetched_codes.json")))

def build_universe(mode):
    if mode == "large":   # 37 只纯大盘 (>=100亿美元, 非ETF)
        return [c for c in fetched
                if not is_etf(mi.get(c,{}).get("name",""))
                and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]
    if mode == "hot":     # 53 只热门池 (去掉ETF)
        return [c for c in fetched if not is_etf(mi.get(c,{}).get("name",""))]
    raise ValueError(mode)

def load_panel(uni):
    panel = {}
    for c in uni:
        f = os.path.join(BASE,"data_kline", c.replace(".","_")+".csv")
        df = pd.read_csv(f); df["time_key"]=pd.to_datetime(df["time_key"])
        df = df.sort_values("time_key").reset_index(drop=True)
        panel[c] = df.set_index("time_key")
    all_dates = sorted(set().union(*[set(df.index) for df in panel.values()]))
    dates = pd.to_datetime(all_dates)
    close = pd.DataFrame({c: panel[c]["close"].reindex(dates).ffill() for c in uni})
    high  = pd.DataFrame({c: panel[c]["high"].reindex(dates).ffill()  for c in uni})
    low   = pd.DataFrame({c: panel[c]["low"].reindex(dates).ffill()   for c in uni})
    open_ = pd.DataFrame({c: panel[c]["open"].reindex(dates).ffill()  for c in uni})
    vol   = pd.DataFrame({c: panel[c]["volume"].reindex(dates).ffill() for c in uni})
    return dates, close, high, low, open_, vol

# ---------- 2. 因子 ----------
def pct(a,n): return a/a.shift(n)-1.0

def build_factors(close):
    # 经典 12-1 动量 (Jegadeesh-Titman)
    mom12_1 = close.shift(21)/close.shift(252)-1.0
    # A1 多周期动量融合 (1/3/6/12 月, 原始收益加权 0.1/0.2/0.3/0.4)
    # 偏向长周期动量 + 短周期加速；v6/v7 验证有效 (注意: 含样本内权重, 需警惕过拟合)
    m1=pct(close,21); m3=pct(close,63); m6=pct(close,126); m12=pct(close,252)
    mom_multi = 0.1*m1 + 0.2*m3 + 0.3*m6 + 0.4*m12
    return mom12_1, mom_multi

# ---------- 3. 回测引擎 (BUG 修复版) ----------
CAP0 = 3000.0
COMM = lambda sh: max(abs(sh)*0.01, 1.5)

def metrics(equity, dates, first_trade_idx):
    eq = np.array(equity, dtype=float)
    rets = np.diff(eq)/eq[:-1]
    total = eq[-1]/eq[0]-1
    years_full = len(eq)/252.0
    cagr_full = (eq[-1]/eq[0])**(1/years_full)-1
    if first_trade_idx and first_trade_idx < len(eq)-1:
        active_eq = eq[first_trade_idx:]
        yrs_a = (len(active_eq))/252.0
        cagr_a = (active_eq[-1]/active_eq[0])**(1/yrs_a)-1 if yrs_a>0 else 0
    else:
        cagr_a = cagr_full
    sharpe = np.mean(rets)/np.std(rets)*np.sqrt(252) if np.std(rets)>0 else 0
    peak = np.maximum.accumulate(eq); mdd=(eq-peak)/peak
    return dict(final=round(eq[-1],0), total=round(total*100,1),
                cagr_full=round(cagr_full*100,1), cagr_active=round(cagr_a*100,1),
                sharpe=round(sharpe,2), mdd=round(mdd.min()*100,1))

def backtest(close, score_func, topk=2, stop=0.0, recover=False,
             reclaim=0.90, rebal=21, take_profit=0.0, verbose=False):
    """事件驱动日级回测。
    reclaim: 恢复再入场需价格收复「止损时峰值」的比例 (0.90=回到峰值90%才回补)
    take_profit: 基于「入场价」的移动止盈比例 (0=关闭), 独立于止损
    """
    N = len(close)
    cash = CAP0
    pos={}; peak={}; entry={}; stopped_peak={}
    equity=[]; first_trade=None
    for i in range(N):
        price = close.iloc[i]
        # ---- 持仓期：止损 / 止盈 / 恢复 ----
        for c in list(pos.keys()):
            p=price[c]; ep=entry[c]
            peak[c]=max(peak.get(c,p),p)
            if stop>0 and p<=peak[c]*(1-stop):
                sh=pos.pop(c); cash+=sh*p-COMM(sh)
                stopped_peak[c]=peak[c]; peak.pop(c,None); entry.pop(c,None)
            elif take_profit>0 and p>=ep*(1+take_profit):   # 移动止盈 (基于入场价, 修复v6 BUG)
                sh=pos.pop(c); cash+=sh*p-COMM(sh)
                peak.pop(c,None); entry.pop(c,None)
        if recover:
            for c in list(stopped_peak.keys()):
                if c not in pos and price[c] >= stopped_peak[c]*reclaim:
                    budget = cash/topk
                    sh=int(budget/price[c])
                    if sh>0 and cash>=sh*price[c]:
                        cash-=sh*price[c]+COMM(sh); pos[c]=sh
                        entry[c]=price[c]; peak[c]=price[c]
                        stopped_peak.pop(c,None)
        # ---- 调仓日 ----
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
    return equity, first_trade

# ---------- 4. 选股体系 + 交易策略 全系统扫描 ----------
def run_system(uni_mode, score_kind, topk, stop, recover, reclaim, rebal, tp=0.0):
    dates, close, *_ = load_panel(build_universe(uni_mode))
    mom12_1, mom_multi = build_factors(close)
    sf = (lambda i: mom_multi.iloc[i]) if score_kind=="A1" else (lambda i: mom12_1.iloc[i])
    eq, ft = backtest(close, sf, topk=topk, stop=stop, recover=recover,
                      reclaim=reclaim, rebal=rebal, take_profit=tp)
    m = metrics(eq, dates, ft)
    return dates, eq, m

configs = [
    # 名称, uni, 因子, topk, stop, recover, reclaim, rebal, tp
    ("A1 多周期动量 top2 月频 无止损",          "large","A1",2,0.0,False,0.90,21,0.0),
    ("A1 多周期动量 top2 周频 无止损",          "large","A1",2,0.0,False,0.90,5,0.0),
    ("A1 多周期动量 top3 月频 无止损",          "large","A1",3,0.0,False,0.90,21,0.0),
    ("A1 多周期动量 top2 月频 +15%止损(无回补)", "large","A1",2,0.15,False,0.90,21,0.0),
    ("A1 多周期动量 top2 月频 +15%止损+回收0.90", "large","A1",2,0.15,True,0.90,21,0.0),
    ("A1 多周期动量 top2 月频 +15%止损+回收0.95", "large","A1",2,0.15,True,0.95,21,0.0),
    ("A1 多周期动量 top2 月频 +15%止损+回收1.00", "large","A1",2,0.15,True,1.00,21,0.0),
    ("经典12-1 top2 月频 无止损 (对照)",        "large","mom12",2,0.0,False,0.90,21,0.0),
    ("经典12-1 top2 月频 +15%止损+回收0.90",    "large","mom12",2,0.15,True,0.90,21,0.0),
    ("A1 top2 月频 无止损 (53热门池)",          "hot","A1",2,0.0,False,0.90,21,0.0),
]

results=[]; eq_curves={}
for name,uni,sk,tk,st,rec,rc,rb,tp in configs:
    dates, eq, m = run_system(uni,sk,tk,st,rec,rc,rb,tp)
    m["name"]=name; m["config"]=dict(uni=uni,score=sk,topk=tk,stop=st,recover=rec,reclaim=rc,rebal=rb)
    results.append(m); eq_curves[name]=list(eq)
    print(f"{name:44s} ${m['final']:>9.0f} tot={m['total']:>7.1f}% cagrA={m['cagr_active']:>6.1f}% "
          f"sharpe={m['sharpe']:>4.2f} mdd={m['mdd']:>6.1f}%")

# VOO 基准
vdf=pd.read_csv(os.path.join(BASE,"data_kline","US_VOO.csv")); vdf["time_key"]=pd.to_datetime(vdf["time_key"])
voo=vdf.set_index("time_key")["close"].reindex(dates).ffill().values
voo_eq=list(CAP0*voo/voo[0]); vm=metrics(voo_eq,dates,0)
results.append(dict(name="VOO 买入持有 (基准)", **vm))
print(f"{'VOO 买入持有 (基准)':44s} ${vm['final']:>9.0f} tot={vm['total']:>7.1f}% cagrA={vm['cagr_active']:>6.1f}% "
      f"sharpe={vm['sharpe']:>4.2f} mdd={vm['mdd']:>6.1f}%")

# ---------- 5. 稳健性：A1 vs 经典12-1 分年度 ----------
print("\n=== 分年度稳健性 (A1 vs 经典12-1, 月频top2无止损) ===")
_, close, *_ = load_panel(build_universe("large"))
mom12_1, mom_multi = build_factors(close)
def yearly_ret(score_func):
    out={}
    for y in [2024,2025,2026]:
        mask=pd.Series(dates).dt.year==y
        idxs=[i for i in range(len(dates)) if mask.iloc[i] and i>=252]
        if not idxs: continue
        start=idxs[0]; end=idxs[-1]
        eq,_=backtest(close,score_func,topk=2,stop=0.0,recover=False,reclaim=0.9,rebal=21)
        out[y]=round((eq[end]/eq[start]-1)*100,1)
    return out
ya=yearly_ret(lambda i: mom_multi.iloc[i]); ym=yearly_ret(lambda i: mom12_1.iloc[i])
for y in ya: print(f"  {y}: A1={ya[y]:>7.1f}%  经典12-1={ym[y]:>7.1f}%")
results.append(dict(name="__robustness__", A1=ya, mom12=ym))

# ---------- 6. 导出 ----------
json.dump(results, open(OUT_JSON,"w"), ensure_ascii=False, indent=2, default=str)
eqdf=pd.DataFrame(eq_curves, index=[d.date() for d in dates])
eqdf.to_csv(OUT_EQ)
print("\nSaved ->", OUT_JSON, OUT_EQ)
