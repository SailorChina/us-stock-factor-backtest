# -*- coding: utf-8 -*-
"""
美股深度指标全家桶 · 聪明钱 / 技术分析 / 技术指标 / AI买卖 · 牛熊长周期 (2018-2026)
=================================================================================
在 v10 已验证引擎上扩展:
  [聪明钱 Smart Money] OBV斜率 / CMF / MFI / AD线斜率 / Chaikin ADOsc / 放量加速度
  [技术分析 Tech Analysis] Aroon / Parabolic SAR / Keltner突破 / Ichimoku云
  [技术指标 Tech Indicators] CMO / TSI / Vortex / ROC120  (含 RSI/CCI/... 变体)
  [AI买卖] walk-forward 随机森林: 用技术特征预测下月(21日)涨跌概率, 按概率排序
全部按"总收益"降序排行; 并对顶级组合加 15%止损+200DMA(熊持VOO) 风控对照。
"""
import os, json, time, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
OUT_JSON = os.path.join(BASE, "_deep_v11_results.json")

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

# ---------- 引擎 (与 v8/v9/v10 一致) ----------
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

# ---------- 通用指标工具 ----------
def true_range(high, low, close):
    pc=close.shift()
    hl=high-low; hc=(high-pc).abs(); lc=(low-pc).abs()
    return np.maximum(np.maximum(hl,hc),lc)
def zs(x):
    m=x.mean(axis=1); s=x.std(axis=1)
    z=x.sub(m,axis=0).div(s,axis=0).replace([np.inf,-np.inf],np.nan)
    return z
def ensemble_z(zlist):
    arr = np.stack([z.values for z in zlist], axis=0)
    with np.errstate(invalid='ignore'):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=zlist[0].index, columns=zlist[0].columns)
def rank_total(df):  # 仅用于调试/中间打印
    return df

# ---------- 既有技术指标 (v10) ----------
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
    return plus_di-minus_di
def roc(close,n): return close/close.shift(n)-1.0
def donchian_dist(close,n=55): return close/close.rolling(n).max()-1.0

# ---------- 聪明钱 Smart Money ----------
def obv(close, volume):
    sign = np.sign(close.diff()).replace(0, np.nan).fillna(0.0)
    return (sign * volume).cumsum()
def obv_slope(close, volume, n=20):
    return obv(close, volume).pct_change(n)
def cmf(high, low, close, volume, n=20):
    denom=(high-low).replace(0,np.nan)
    m=((close-low)-(high-close))/denom*volume
    return m.rolling(n).sum()/volume.rolling(n).sum()
def mfi(high, low, close, volume, n=14):
    tp=(high+low+close)/3; rmf=tp*volume
    up=tp.diff()>0; down=tp.diff()<0
    pos=rmf.where(up,0.0).rolling(n).sum(); neg=rmf.where(down,0.0).rolling(n).sum()
    r=pos/neg.replace(0,np.nan)
    return 100-100/(1+r)
def ad_line(high, low, close, volume):
    denom=(high-low).replace(0,np.nan)
    return (((close-low)-(high-close))/denom*volume).cumsum()
def ad_slope(high, low, close, volume, n=20):
    return ad_line(high,low,close,volume).pct_change(n)
def chaikin_adosc(high, low, close, volume, s=3, l=10):
    denom=(high-low).replace(0,np.nan)
    cl=((close-low)-(high-close))/denom*volume
    return cl.ewm(span=s,adjust=False).mean()-cl.ewm(span=l,adjust=False).mean()
def accel(close, volume, n=5, w=60):
    # 放量加速度: 5日上涨 且 成交量异常放大 -> 聪明钱吸筹
    up = (close.pct_change(n)>0).astype(float)
    vr = volume/volume.rolling(w).mean()
    return up * vr

# ---------- 技术分析 Tech Analysis ----------
def aroon(high, low, n=25):
    up = high.rolling(n).apply(lambda x: ((n-1)-x[::-1].argmax())/(n-1)*100, raw=True)
    dn = low.rolling(n).apply(lambda x: ((n-1)-x[::-1].argmin())/(n-1)*100, raw=True)
    return up-dn
def psar(high, low, af=0.02, max_af=0.20):
    # high, low: 1D numpy arrays (单只股票)
    n=len(high)
    sar=np.full(n,np.nan); ep=np.full(n,np.nan); upt=np.zeros(n,bool); afc=np.zeros(n)
    ep[0]=high[0]; sar[0]=low[0]; upt[0]=True; afc[0]=af
    for i in range(1,n):
        ps=sar[i-1]
        if upt[i-1]:
            sar[i]=ps+afc[i-1]*(ep[i-1]-ps)
            if low[i]<sar[i]:
                upt[i]=False; sar[i]=ep[i-1]; ep[i]=low[i]; afc[i]=af
            else:
                upt[i]=True
                if high[i]>ep[i-1]: ep[i]=high[i]; afc[i]=min(afc[i-1]+af,max_af)
                else: ep[i]=ep[i-1]; afc[i]=afc[i-1]
        else:
            sar[i]=ps-afc[i-1]*(ps-ep[i-1])
            if high[i]>sar[i]:
                upt[i]=True; sar[i]=ep[i-1]; ep[i]=high[i]; afc[i]=af
            else:
                upt[i]=False
                if low[i]<ep[i-1]: ep[i]=low[i]; afc[i]=min(afc[i-1]+af,max_af)
                else: ep[i]=ep[i-1]; afc[i]=afc[i-1]
    return sar
def sar_dist(close, high, low):
    out=pd.DataFrame(index=high.index, columns=high.columns, dtype=float)
    for c in high.columns:
        s=psar(high[c].values, low[c].values)
        out[c]=close[c].values/s-1.0
    return out
def keltner(high, low, close, n=20, m=2):
    ema=close.ewm(span=n,adjust=False).mean()
    atr=true_range(high,low,close).ewm(span=n,adjust=False).mean()
    upper=ema+m*atr
    return close/upper-1.0
def ichimoku(close, high, low):
    tenkan=(high.rolling(9).max()+low.rolling(9).min())/2
    kijun=(high.rolling(26).max()+low.rolling(26).min())/2
    senkouA=(tenkan+kijun)/2
    senkouB=(high.rolling(52).max()+low.rolling(52).min())/2
    cloud=np.maximum(senkouA,senkouB)
    return close/cloud-1.0

# ---------- 技术指标 Tech Indicators (扩展) ----------
def cmo(close, n=20):
    d=close.diff(); su=d.clip(lower=0).rolling(n).sum(); sd=(-d.clip(upper=0)).rolling(n).sum()
    return (su-sd)/(su+sd)*100
def tsi(close, r=25, s=13):
    m=close.diff()
    e2=m.ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    a2=m.abs().ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    return e2/a2*100
def vortex(high, low, close, n=14):
    tr=true_range(high,low,close)
    vm_up=(high-low.shift()).abs(); vm_dn=(low-high.shift()).abs()
    vp=vm_up.rolling(n).sum(); vn=vm_dn.rolling(n).sum(); ts=tr.rolling(n).sum()
    return vp/ts-vn/ts

# ---------- AI 买卖 (walk-forward 随机森林) ----------
from sklearn.ensemble import RandomForestClassifier
def build_ai_signal(C, H, L, V, dates, warmup=378, HOR=21, win=756, seed=0, rebal=21, n_est=120):
    N=len(C); S=C.shape[1]
    r21=C/C.shift(21)-1; r63=C/C.shift(63)-1; r126=C/C.shift(126)-1; r252=C/C.shift(252)-1
    dret=C.pct_change(); vol20=dret.rolling(20).std()
    rsi14=rsi(C,14); mh=macd_hist(C); vr=V/V.rolling(60).mean()
    bb=bollinger_pctB(C,20,2); md50=C/C.rolling(50).mean()-1
    feat=np.stack([r21.values,r63.values,r126.values,r252.values,vol20.values,
                   rsi14.values,mh.values,vr.values,bb.values,md50.values],axis=-1)  # (N,S,F)
    fwd=C.shift(-HOR)/C-1.0; fwd_v=fwd.values
    valid_feat=~np.any(np.isnan(feat),axis=2)
    valid_tgt=~np.isnan(fwd_v)
    rf=RandomForestClassifier(n_estimators=n_est,max_depth=4,min_samples_leaf=30,
                              class_weight='balanced',n_jobs=-1,random_state=seed)
    score=np.full((N,S),np.nan)
    rb_days=[i for i in range(N) if i>=252 and (i-252)%rebal==0]
    for i in rb_days:
        if i<warmup+HOR: continue
        t0=max(warmup,i-win); t1=i-HOR
        m=valid_feat[t0:t1+1]&valid_tgt[t0:t1+1]
        if m.sum()<200: continue
        Xtr=feat[t0:t1+1][m]; ytr=(fwd_v[t0:t1+1][m]>0).astype(int)
        if ytr.sum()==0 or ytr.sum()==len(ytr): continue
        rf.fit(Xtr,ytr)
        mp=valid_feat[i]
        if mp.sum()==0: continue
        pr=np.full(S,np.nan); pr[mp]=rf.predict_proba(feat[i][mp])[:,1]
        score[i]=pr
    return pd.DataFrame(score,index=dates,columns=C.columns)

# =================== 主流程 ===================
t0=time.time()
dates, PX = load_ohlcv(UNI)
O,H,L,C,V = PX["open"],PX["high"],PX["low"],PX["close"],PX["volume"]
pct=lambda a,n: a/a.shift(n)-1.0
mom12_1 = C.shift(21)/C.shift(252)-1.0

# 均线
ma50=C.rolling(50).mean(); ma200=C.rolling(200).mean()
ma_dist50=C/ma50-1.0; ma_slope200=ma200.pct_change(20)
golden = ma50>ma200
sf_golden = lambda i: ma_dist50.iloc[i].where(golden.iloc[i])

# 既有技术指标
rsi14=rsi(C,14); rsi7=rsi(C,7)
cci20=cci(H,L,C,20); cci14=cci(H,L,C,14)
stochK=stochastic(H,L,C,14); willR=williamsR(H,L,C,14)
bbB=bollinger_pctB(C,20,2); macdH=macd_hist(C)
di_diff=adx_di(H,L,C,14); roc60=roc(C,60); roc120=roc(C,120)
donch=donchian_dist(C,55); rev1=pct(C,21)

# 聪明钱
obv_s=obv_slope(C,V); cmf20=cmf(H,L,C,V,20); cmf14=cmf(H,L,C,V,14)
mfi14=mfi(H,L,C,V,14); ad_s=ad_slope(H,L,C,V); adosc=chaikin_adosc(H,L,C,V); acc=accel(C,V)
SMART = ensemble_z([zs(obv_s),zs(cmf20),zs(mfi14),zs(ad_s),zs(adosc),zs(acc)])

# 技术分析
aroon25=aroon(H,L); sard=sar_dist(C,H,L); kelt=keltner(H,L,C); ichi=ichimoku(C,H,L)
TA = ensemble_z([zs(aroon25),zs(sard),zs(kelt),zs(ichi)])

# 技术指标扩展
cmo20=cmo(C,20); tsi13=tsi(C); vortex14=vortex(H,L,C)
TECHX = ensemble_z([zs(cmo20),zs(tsi13),zs(vortex14)])

# AI 买卖 (多测几次: 不同窗口/种子)
ai_a = build_ai_signal(C,H,L,V,dates, win=756, seed=0)
ai_b = build_ai_signal(C,H,L,V,dates, win=756, seed=42)
ai_c = build_ai_signal(C,H,L,V,dates, win=504, seed=0)
z_ai_a=zs(ai_a); z_ai_b=zs(ai_b); z_ai_c=zs(ai_c)
# AI 组合
AI_MOM   = ensemble_z([z_ai_a, zs(mom12_1)])
AI_SMART = ensemble_z([z_ai_a, zs(SMART)])
ALLBLEND = ensemble_z([zs(mom12_1), zs(SMART), zs(TA), z_ai_a])

# 指标 z 分数 (单指标)
z_rsi=zs(rsi14); z_cci=zs(cci20); z_stoch=zs(stochK); z_will=zs(willR); z_bb=zs(bbB)
z_roc=zs(roc60); z_roc120=zs(roc120); z_di=zs(di_diff); z_macd=zs(macdH); z_donch=zs(donch)
z_obv=zs(obv_s); z_cmf=zs(cmf20); z_mfi=zs(mfi14); z_ads=zs(ad_s); z_adosc=zs(adosc); z_acc=zs(acc)
z_aroon=zs(aroon25); z_sar=zs(sard); z_kelt=zs(kelt); z_ichi=zs(ichi)
z_cmo=zs(cmo20); z_tsi=zs(tsi13); z_vortex=zs(vortex14)
z_ma50=zs(ma_dist50); z_slope=zs(ma_slope200)

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

def bt(sf,tk=2,st=0.0,rec=False,rc=0.90,rb=21,tp=0.0,rg=None,sp=None):
    sf_call = (lambda i: sf.iloc[i]) if isinstance(sf, pd.DataFrame) else sf
    return ("bt", sf_call, tk, st, rec, rc, rb, tp, rg, sp)

configs = []
# ---- [聪明钱] 单指标 ----
configs += [
    ("[聪明钱] OBV斜率 Top2",        bt(obv_s)),
    ("[聪明钱] CMF(20) Top2",         bt(cmf20)),
    ("[聪明钱] MFI(14) Top2",         bt(mfi14)),
    ("[聪明钱] AD线斜率 Top2",        bt(ad_s)),
    ("[聪明钱] Chaikin ADOsc Top2",   bt(adosc)),
    ("[聪明钱] 放量加速度 Top2",       bt(acc)),
    ("[聪明钱] 组合(6合1) Top2",      bt(SMART)),
]
# ---- [技术分析] 单指标 ----
configs += [
    ("[技术分析] Aroon(25) Top2",     bt(aroon25)),
    ("[技术分析] SAR距离 Top2",       bt(sard)),
    ("[技术分析] Keltner突破 Top2",   bt(kelt)),
    ("[技术分析] Ichimoku云 Top2",    bt(ichi)),
    ("[技术分析] 组合(4合1) Top2",    bt(TA)),
]
# ---- [技术指标] 单指标(含变体) ----
configs += [
    ("[技术指标] RSI14(强势) Top2",   bt(rsi14)),
    ("[技术指标] RSI7(强势) Top2",    bt(rsi7)),
    ("[技术指标] CCI20(强势) Top2",   bt(cci20)),
    ("[技术指标] CCI14(强势) Top2",   bt(cci14)),
    ("[技术指标] Stochastic%K Top2",  bt(stochK)),
    ("[技术指标] Williams%R Top2",    bt(willR)),
    ("[技术指标] Bollinger%B Top2",   bt(bbB)),
    ("[技术指标] MACD柱 Top2",        bt(macdH)),
    ("[技术指标] DI差 Top2",          bt(di_diff)),
    ("[技术指标] ROC60 Top2",         bt(roc60)),
    ("[技术指标] ROC120 Top2",        bt(roc120)),
    ("[技术指标] Donchian55 Top2",    bt(donch)),
    ("[技术指标] CMO20 Top2",         bt(cmo20)),
    ("[技术指标] TSI Top2",           bt(tsi13)),
    ("[技术指标] Vortex Top2",        bt(vortex14)),
    ("[技术指标] 均线与斜率",          bt(ensemble_z([z_ma50,z_slope]))),
]
# ---- [AI买卖] ----
configs += [
    ("[AI] 随机森林(窗口756 种子0) Top2",     bt(ai_a)),
    ("[AI] 随机森林(窗口756 种子42) Top2",    bt(ai_b)),
    ("[AI] 随机森林(窗口504 种子0) Top2",     bt(ai_c)),
    ("[AI] AI+动量 Top2",                     bt(AI_MOM)),
    ("[AI] AI+聪明钱 Top2",                   bt(AI_SMART)),
    ("[AI] 全家桶混合(动+聪明+技术+AI) Top2", bt(ALLBLEND)),
]
# ---- 同款风控对照 (顶级组合) ----
configs += [
    ("[风控] 聪明钱组合 +15%止损+200DMA",        bt(SMART, st=0.15, rg=regime, sp=voo_ser)),
    ("[风控] 技术分析组合 +15%止损+200DMA",      bt(TA, st=0.15, rg=regime, sp=voo_ser)),
    ("[风控] AI全家桶混合 +15%止损+200DMA",      bt(ALLBLEND, st=0.15, rg=regime, sp=voo_ser)),
    ("[风控] 经典12-1 +15%止损+200DMA",         bt(mom12_1, st=0.15, rg=regime, sp=voo_ser)),
]
# ---- 基准 ----
configs += [
    ("[基准] 经典12-1动量 Top2 无止损",  bt(mom12_1)),
    ("[基准] 金叉+MA50距离 Top2 无止损", bt(sf_golden)),
]

results=[]
print("="*110)
print(f"美股深度指标全家桶 (聪明钱/技术分析/技术指标/AI) · 区间 {dates[0].date()} ~ {dates[-1].date()} ({len(dates)} 交易日) 起点 $3000")
print(f"VOO 买入持有: ${voo_eq[-1]:.0f} (+{(voo_eq[-1]/voo_eq[0]-1)*100:.1f}%) | VOO 200DMA择时(空仓): ${voo_timing[-1]:.0f} (+{(voo_timing[-1]/voo_timing[0]-1)*100:.1f}%)")
print("="*110)
for name, (kind,sf,tk,st,rec,rc,rb,tp,rg,sp) in configs:
    eq, ft = backtest(C, sf, topk=tk, stop=st, recover=rec, reclaim=rc, rebal=rb, take_profit=tp, regime=rg, safe_prices=sp)
    m=metrics(eq,dates,ft); ph=phase_stats(dates,eq,voo_eq)
    results.append(dict(name=name, metrics=m, phases=ph, first_trade=str(dates[ft].date()) if ft else None))
    print(f"\n### {name}")
    print(f"  终值 ${m['final']:.0f} | 总收益 {m['total']}% | 年化全 {m['cagr_full']}% | 活跃年化 {m['cagr_active']}% | 夏普 {m['sharpe']} | 最大回撤 {m['mdd']}% | 首笔 {results[-1]['first_trade']}")
print("\n"+"="*110)
print("【总收益排行 (降序)】")
ranked=sorted(results, key=lambda r: r['metrics']['total'], reverse=True)
print(f"{'排名':>4} | {'总收益%':>9} | {'终值$':>9} | {'夏普':>6} | {'回撤%':>7} | 名称")
for i,r in enumerate(ranged:=ranked,1):
    m=r['metrics']
    print(f"{i:>4} | {m['total']:>9} | {m['final']:>9.0f} | {m['sharpe']:>6} | {m['mdd']:>7} | {r['name']}")

results.append(dict(name="[基准] VOO 买入持有", metrics=metrics(voo_eq,dates,0), phases=phase_stats(dates,voo_eq,voo_eq), first_trade=str(dates[0].date())))
results.append(dict(name="[基准] VOO 200DMA择时(空仓)", metrics=metrics(voo_timing,dates,0), phases=phase_stats(dates,voo_timing,voo_eq), first_trade=str(dates[0].date())))
json.dump(results, open(OUT_JSON,"w"), ensure_ascii=False, indent=2, default=str)
print(f"\nSAVED {OUT_JSON} | 耗时 {time.time()-t0:.1f}s")
