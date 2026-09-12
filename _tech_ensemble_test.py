# -*- coding: utf-8 -*-
"""
技术指标全家桶 & 多指标组合 · 牛熊长周期对照 (2018-01 ~ 2026-09)
=================================================================
在同样的数据/引擎上:
  1) 把 RSI / CCI / Stochastic / Williams%R / Bollinger%B / MACD柱 / ADX(DI差) /
     ROC / Donchian 等经典指标, 逐个当作"独立选股信号"测一遍。
  2) 做几种"组合起来"的方式:
       - 趋势集成: 动量/ROC/均线距离/斜率 的 z 平均
       - 全指标集成: 上面 + 所有摆动指标 z 平均 (测摆动指标是否有用)
       - 智能组合: 动量 + 均线 + 1月反转(负向)  z 平均 (v8结论方向)
       - 多数投票: 多数指标看多才入选, 按票数+均z排序
  3) 给最优组合套 15%止损 + 200DMA牛熊过滤(熊持VOO)。
对照基准: 经典12-1动量、金叉+MA50距离、VOO。
"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
OUT_JSON = os.path.join(BASE, "_tech_ensemble_results.json")

# ---------- 数据加载 (含 OHLCV) ----------
def is_etf(name):
    n = (name or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])

mi = json.load(open(os.path.join(BASE,"market_info.json")))
fetched = json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI = [c for c in fetched
       if not is_etf(mi.get(c,{}).get("name",""))
       and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]

def load_ohlcv(codes):
    panel = {c: None for c in codes}
    for c in codes:
        f = os.path.join(LONGDIR, c.replace(".","_")+".csv")
        df = pd.read_csv(f); df["time_key"]=pd.to_datetime(df["time_key"])
        df = df.sort_values("time_key").reset_index(drop=True).set_index("time_key")
        panel[c] = df
    all_dates = sorted(set().union(*[set(df.index) for df in panel.values()]))
    dates = pd.to_datetime(all_dates)
    out = {}
    for col in ["open","high","low","close","volume"]:
        out[col] = pd.DataFrame({c: panel[c][col].reindex(dates).ffill() for c in codes})
    return dates, out

# ---------- 引擎 (与 v8/v9 一致) ----------
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
    cash=CAP0; pos={}; peak={}; entry={}; stopped_peak={}
    safe_shares=0; in_safe=False
    equity=[]; first_trade=None
    for i in range(N):
        price=close.iloc[i]
        if regime is not None:
            bear = not regime[i]
            if bear:
                if safe_prices is not None and not in_safe:
                    for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    peak.clear(); entry.clear(); stopped_peak.clear()
                    sp=safe_prices[i]; sh=int(cash//sp)
                    if sh>0: cash-=sh*sp+COMM(sh); safe_shares=sh; in_safe=True
                elif safe_prices is None:
                    for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
                    peak.clear(); entry.clear(); stopped_peak.clear()
                    equity.append(cash); continue
            else:
                if in_safe:
                    sp=safe_prices[i]; cash+=safe_shares*sp-COMM(safe_shares); safe_shares=0; in_safe=False
            if in_safe:
                equity.append(cash+safe_shares*safe_prices[i]); continue
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
                    budget=cash/topk; sh=int(budget/price[c])
                    if sh>0 and cash>=sh*price[c]:
                        cash-=sh*price[c]+COMM(sh); pos[c]=sh
                        entry[c]=price[c]; peak[c]=price[c]; stopped_peak.pop(c,None)
        if i>=252 and (i-252)%rebal==0:
            sc=score_func(i).dropna().sort_values(ascending=False)
            picks=sc.index[:topk].tolist()
            for c in list(pos.keys()): cash+=pos.pop(c)*price[c]-COMM(pos.get(c,0))
            peak.clear(); entry.clear(); stopped_peak.clear()
            for c in picks:
                sh=int((cash/topk)//price[c])
                if sh>0:
                    cash-=sh*price[c]+COMM(sh); pos[c]=sh; entry[c]=price[c]; peak[c]=price[c]
                    if first_trade is None: first_trade=i
        mv=sum(pos.get(c,0)*price[c] for c in pos)
        equity.append(cash+mv)
    return np.array(equity), first_trade

PHASES = [
    ("2018牛市(至顶)","2018-01-02","2018-09-20","bull"),
    ("2018回落(熊)","2018-09-21","2018-12-24","bear"),
    ("2019-20.2牛市","2019-01-01","2020-02-19","bull"),
    ("2020崩盘(熊)","2020-02-19","2020-03-23","bear"),
    ("2020-21牛市","2020-03-24","2021-12-31","bull"),
    ("2022熊市(熊)","2022-01-03","2022-10-12","bear"),
    ("2023-26牛市","2023-01-01","2026-09-10","bull"),
]
def phase_stats(dates, eq, voo_eq):
    out=[]; darr=pd.to_datetime(dates)
    for name,s,e,kind in PHASES:
        mask=(darr>=s)&(darr<=e); idx=np.where(mask)[0]
        if len(idx)==0: out.append((name,kind,None,None,None)); continue
        i0,i1=idx[0],idx[-1]
        s_ret=eq[i1]/eq[i0]-1 if eq[i0]>0 else None
        v_ret=voo_eq[i1]/voo_eq[i0]-1 if voo_eq[i0]>0 else None
        seg=eq[i0:i1+1]
        mdd=(seg-np.maximum.accumulate(seg))/np.maximum.accumulate(seg)
        out.append((name,kind,round(s_ret*100,1) if s_ret is not None else None,
                    round(v_ret*100,1) if v_ret is not None else None, round(mdd.min()*100,1)))
    return out

# ---------- 技术指标库 ----------
def rsi(close, n=14):
    d=close.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/n,adjust=False).mean(); al=l.ewm(alpha=1/n,adjust=False).mean()
    rs=ag/al; return 100-100/(1+rs)
def cci(high,low,close,n=20):
    tp=(high+low+close)/3; sma=tp.rolling(n).mean()
    mad=(tp-sma).abs().rolling(n).mean()
    return (tp-sma)/(0.015*mad)
def stochastic(high,low,close,n=14,d=3):
    ll=low.rolling(n).min(); hh=high.rolling(n).max()
    return (close-ll)/(hh-ll)*100
def williamsR(high,low,close,n=14):
    hh=high.rolling(n).max(); ll=low.rolling(n).min()
    return (hh-close)/(hh-ll)*-100
def bollinger_pctB(close,n=20,k=2):
    m=close.rolling(n).mean(); s=close.rolling(n).std()
    return (close-(m-k*s))/((m+k*s)-(m-k*s))
def macd_hist(close,f=12,s=26,sig=9):
    ml=close.ewm(span=f,adjust=False).mean()-close.ewm(span=s,adjust=False).mean()
    return ml-ml.ewm(span=sig,adjust=False).mean()
def adx_di(high,low,close,n=14):
    up=high.diff(); dn=-low.diff()
    plus_dm=((up>dn)&(up>0))*up; minus_dm=((dn>up)&(dn>0))*dn
    pc=close.shift()
    hl=high-low; hc=(high-pc).abs(); lc=(low-pc).abs()
    tr=np.maximum(np.maximum(hl,hc),lc)
    atr=tr.ewm(alpha=1/n,adjust=False).mean()
    plus_di=(plus_dm.ewm(alpha=1/n,adjust=False).mean()/atr)*100
    minus_di=(minus_dm.ewm(alpha=1/n,adjust=False).mean()/atr)*100
    return plus_di-minus_di   # 方向性趋势差(>0看涨趋势, <0看跌趋势)
def roc(close,n): return close/close.shift(n)-1.0
def donchian_dist(close,n=55): return close/close.rolling(n).max()-1.0
def zs(x):
    m=x.mean(axis=1); s=x.std(axis=1)
    z=x.sub(m,axis=0).div(s,axis=0).replace([np.inf,-np.inf],np.nan)
    return z
def ensemble_z(zlist):
    arr = np.stack([z.values for z in zlist], axis=0)   # (k, dates, stocks)
    with np.errstate(invalid='ignore'):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=zlist[0].index, columns=zlist[0].columns)

# ---------- 数据 & 因子 ----------
dates, PX = load_ohlcv(UNI)
O,H,L,C,V = PX["open"],PX["high"],PX["low"],PX["close"],PX["volume"]
pct=lambda a,n: a/a.shift(n)-1.0
mom12_1 = C.shift(21)/C.shift(252)-1.0

# 均线 (v9 已验证)
ma50=C.rolling(50).mean(); ma200=C.rolling(200).mean()
ma_dist50=C/ma50-1.0; ma_dist200=C/ma200-1.0; ma_slope200=ma200.pct_change(20)
golden = ma50>ma200
sf_golden = lambda i: ma_dist50.iloc[i].where(golden.iloc[i])

# 技术指标
rsi14=rsi(C,14); cci20=cci(H,L,C,20); stochK=stochastic(H,L,C,14); willR=williamsR(H,L,C,14)
bbB=bollinger_pctB(C,20,2); macdH=macd_hist(C); di_diff=adx_di(H,L,C,14)
roc60=roc(C,60); donch=donchian_dist(C,55); rev1=pct(C,21)   # 1月收益(反转用)

# 指标 z 分数
z_mom=zs(mom12_1); z_roc=zs(roc60); z_ma50=zs(ma_dist50); z_ma200=zs(ma_dist200); z_slope=zs(ma_slope200)
z_rsi=zs(rsi14); z_cci=zs(cci20); z_stoch=zs(stochK); z_will=zs(willR); z_bb=zs(bbB)

# 集成
ENS_TREND = ensemble_z([z_mom,z_roc,z_ma50,z_slope,z_ma200])
ENS_ALL   = ensemble_z([z_mom,z_roc,z_ma50,z_slope,z_ma200,z_rsi,z_cci,z_stoch,z_will,z_bb])
ENS_SMART = ensemble_z([z_mom,z_ma50, zs(-rev1)])   # 动量+均线+1月反转(负向)
# 多数投票: 10 个指标多数看多, 按票数*100 + 均z 排序
vote_list=[z_mom,z_roc,z_ma50,z_slope,z_ma200,z_rsi,z_cci,z_stoch,z_will,z_bb]
votes = sum((z>0).astype(float) for z in vote_list)
avgz = ensemble_z(vote_list)
SCORE_VOTE = votes*100 + avgz.fillna(0)

# VOO 基准 & 牛熊
_, voo_close = load_ohlcv(["US.VOO"])
voo_ser = voo_close["close"]["US.VOO"].reindex(dates).ffill().values
voo_eq = voo_ser/voo_ser[0]*CAP0
voo_ma200 = pd.Series(voo_ser).rolling(200).mean().values
regime = voo_ser > voo_ma200
voo_ret=np.diff(voo_ser)/voo_ser[:-1]
voo_timing=np.array([CAP0])
for i in range(1,len(voo_ser)):
    voo_timing=np.append(voo_timing, voo_timing[-1]*(1+voo_ret[i-1]) if regime[i-1] else voo_timing[-1])

# ---------- 配置 ----------
def bt(sf,tk=2,st=0.0,rec=False,rc=0.90,rb=21,tp=0.0,rg=None,sp=None):
    sf_call = (lambda i: sf.iloc[i]) if isinstance(sf, pd.DataFrame) else sf
    return ("bt", sf_call, tk, st, rec, rc, rb, tp, rg, sp)

configs = []
# ---- 单指标独立信号 (Top2 月频, 无风控) ----
configs += [
    ("[单指标] ROC60 Top2",          bt(roc60)),
    ("[单指标] RSI14(强势) Top2",     bt(rsi14)),
    ("[单指标] RSI14(超卖反弹) Top2", bt(-rsi14)),
    ("[单指标] CCI20(强势) Top2",     bt(cci20)),
    ("[单指标] CCI20(反转) Top2",     bt(-cci20)),
    ("[单指标] Stochastic%K Top2",    bt(stochK)),
    ("[单指标] Williams%R Top2",      bt(willR)),
    ("[单指标] Bollinger%B Top2",     bt(bbB)),
    ("[单指标] MACD柱 Top2",          bt(macdH)),
    ("[单指标] DI差(方向趋势) Top2",   bt(di_diff)),
    ("[单指标] Donchian55突破 Top2",  bt(donch)),
    # ---- 组合方式 ----
    ("[组合] 趋势集成(动量+ROC+均线) Top2",       bt(ENS_TREND)),
    ("[组合] 全指标集成(趋势+摆动) Top2",         bt(ENS_ALL)),
    ("[组合] 智能组合(动量+均线+1月反转) Top2",    bt(ENS_SMART)),
    ("[组合] 多数投票(10指标) Top2",              bt(SCORE_VOTE)),
    # ---- 同款风控对照 ----
    ("[组合] 智能组合 +15%止损+200DMA(熊持VOO)",  bt(ENS_SMART, st=0.15, rg=regime, sp=voo_ser)),
    ("[组合] 趋势集成 +15%止损+200DMA(熊持VOO)",   bt(ENS_TREND, st=0.15, rg=regime, sp=voo_ser)),
    ("[组合] 多数投票 +15%止损+200DMA(熊持VOO)",   bt(SCORE_VOTE, st=0.15, rg=regime, sp=voo_ser)),
    # ---- 基准 ----
    ("[基准] 经典12-1动量 Top2 无止损",  bt(mom12_1)),
    ("[基准] 金叉+MA50距离 Top2 无止损", bt(sf_golden)),
]

results=[]
print("="*108)
print(f"技术指标全家桶 & 组合 · 区间 {dates[0].date()} ~ {dates[-1].date()}  ({len(dates)} 交易日)  起点 $3000")
print(f"VOO 买入持有: ${voo_eq[-1]:.0f} (+{(voo_eq[-1]/voo_eq[0]-1)*100:.1f}%)  | VOO 200DMA择时(空仓): ${voo_timing[-1]:.0f} (+{(voo_timing[-1]/voo_timing[0]-1)*100:.1f}%)")
print("="*108)
for name, (kind,sf,tk,st,rec,rc,rb,tp,rg,sp) in configs:
    eq, ft = backtest(C, sf, topk=tk, stop=st, recover=rec, reclaim=rc, rebal=rb, take_profit=tp, regime=rg, safe_prices=sp)
    m=metrics(eq,dates,ft); ph=phase_stats(dates,eq,voo_eq)
    results.append(dict(name=name, metrics=m, phases=ph, first_trade=str(dates[ft].date()) if ft else None))
    print(f"\n### {name}")
    print(f"  终值 ${m['final']:.0f} | 总收益 {m['total']}% | 年化和 {m['cagr_full']}% | 活跃年化 {m['cagr_active']}% | 夏普 {m['sharpe']} | 最大回撤 {m['mdd']}%")
    print(f"  首笔交易: {results[-1]['first_trade']}")
    print(f"  {'阶段':<14}{'类型':<6}{'策略%':>9}{'VOO%':>9}{'阶段最大回撤%':>15}")
    for nm,kind2,sr,vr,md in ph:
        print(f"  {nm:<14}{kind2:<6}{str(sr):>9}{str(vr):>9}{str(md):>15}")

results.append(dict(name="[基准] VOO 买入持有", metrics=metrics(voo_eq,dates,0), phases=phase_stats(dates,voo_eq,voo_eq), first_trade=str(dates[0].date())))
results.append(dict(name="[基准] VOO 200DMA择时(空仓)", metrics=metrics(voo_timing,dates,0), phases=phase_stats(dates,voo_timing,voo_eq), first_trade=str(dates[0].date())))
json.dump(results, open(OUT_JSON,"w"), ensure_ascii=False, indent=2, default=str)
print("\nSAVED", OUT_JSON)
