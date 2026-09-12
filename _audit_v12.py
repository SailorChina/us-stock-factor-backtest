# -*- coding: utf-8 -*-
"""
v12 第一步: 数据体检 + 信号数值体检
目的: 找出"不会报错、只会让回测结果悄悄变好/变坏"的隐性问题
检查项:
  A. 数据完整性: 每票起始日/缺失/ffill填充比例/零成交量/停牌段
  B. 拆股与复权: 单日 |收益|>25% 的跳变 (疑似未复权拆股)
  C. 信号数值健康: NaN比例 / inf / 极端值爆炸 / 分布退化 / 是否常数为0
  D. 信号重复: 两两相关矩阵(找互为线性变换的冗余指标)
  E. 选股集中度: 每个指标月度Top2 落在哪些票、换手率
"""
import os, json, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

def is_etf(name):
    n=(name or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])

mi=json.load(open(os.path.join(BASE,"market_info.json")))
fetched=json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI=[c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0) or 0)>=10e9]

def load_ohlcv(codes):
    panel={}
    for c in codes:
        f=os.path.join(LONGDIR, c.replace(".","_")+".csv")
        df=pd.read_csv(f); df["time_key"]=pd.to_datetime(df["time_key"])
        panel[c]=df.sort_values("time_key").reset_index(drop=True).set_index("time_key")
    all_dates=sorted(set().union(*[set(df.index) for df in panel.values()]))
    dates=pd.to_datetime(all_dates); out={}
    for col in ["open","high","low","close","volume"]:
        out[col]=pd.DataFrame({c: panel[c][col].reindex(dates) for c in codes})   # 不 ffill, 保留 NaN 以检测缺失
    return dates, out, panel

print("="*100)
print(f"[A] 数据完整性体检 · 宇宙 {len(UNI)} 只")
print("="*100)
dates, RAW, panel = load_ohlcv(UNI)
N=len(dates)
print(f"交易日并集: {N} | {dates[0].date()} ~ {dates[-1].date()}")

rows=[]
for c in UNI:
    df=panel[c]
    s=RAW["close"][c]
    first_valid=s.first_valid_index(); last_valid=s.last_valid_index()
    n_nat=s.isna().sum()
    v=RAW["volume"][c]
    zero_vol=int((v.fillna(0)==0).sum())
    rows.append(dict(code=c, start=str(first_valid.date()), end=str(last_valid.date()),
                     rows=len(df), nat=int(n_nat), nat_pct=round(n_nat/N*100,2), zero_vol=zero_vol))
dr=pd.DataFrame(rows).sort_values("nat_pct",ascending=False)
print("\n-- 缺失比例 Top10 (nat 表示相对全市场交易日并集缺失的天数) --")
print(dr.head(10).to_string(index=False))
print(f"\n起始日分布: {dr['start'].value_counts().to_dict()}")
late=dr[dr["start"]>str(dates[0].date())]
print(f"起始晚于首日的票: {len(late)} 只 -> {late['code'].tolist()[:20]}")

print("\n"+"="*100)
print("[B] 拆股 / 复权体检: 单日 |收益|>25% 的跳变")
print("="*100)
FILL=RAW["close"].ffill()   # 用 ffill 版本来算收益(与回测一致)
ret=FILL.pct_change()
susp=[]
for c in UNI:
    r=ret[c]
    idx=np.where(r.abs()>0.25)[0]
    for i in idx:
        if i<1: continue
        prev=FILL[c].iloc[i-1]; cur=FILL[c].iloc[i]
        # 拆股特征: 价格按比例跳变 + 成交量反向跳变 + 之后不回补
        vv=RAW["volume"][c].ffill()
        vr=vv.iloc[i]/max(vv.iloc[i-1],1)
        susp.append((str(dates[i].date()), c, round(prev,2), round(cur,2), round(r.iloc[i]*100,1), round(vr,2)))
susp.sort()
print(f"共 {len(susp)} 次 |日收益|>25% 的跳变")
if susp:
    print(f"{'日期':<12}{'代码':<12}{'前收':>10}{'当收':>10}{'收益%':>9}{'量比':>8}")
    for s in susp[:60]:
        print(f"{s[0]:<12}{s[1]:<12}{s[2]:>10}{s[3]:>10}{s[4]:>9}{s[5]:>8}")
# 关键: 检测疑似拆股 (价格跌 ~50%/75%/90% 且成交量放大 ~2x/4x/10x, 且非全市场同日下跌)
mkt=ret.mean(axis=1)
print("\n-- 疑似拆股判定(个股暴跌>40% 但同日全市场跌幅<5%, 量比>1.5) --")
splits=[]
for s in susp:
    d,c,prev,cur,r,vr=s
    i=list(dates).index(pd.Timestamp(d))
    if r<-40 and abs(mkt.iloc[i])<0.05 and vr>1.5:
        splits.append(s)
print(f"命中 {len(splits)} 次:")
for s in splits: print("   ",s)
print("\n注: 若上面命中非空, 说明数据未复权 -> 拆股会造成假暴跌, 动量/止损全部失真(必须修复)。")

print("\n"+"="*100)
print("[C] 信号数值健康体检 (NaN / inf / 极端值 / 退化)")
print("="*100)
O,H,L,C,V = RAW["open"].ffill(),RAW["high"].ffill(),RAW["low"].ffill(),RAW["close"].ffill(),RAW["volume"].ffill()

# --- 指标库(与 v11 一致) ---
def true_range(high,low,close):
    pc=close.shift(); return np.maximum(np.maximum(high-low,(high-pc).abs()),(low-pc).abs())
def rsi(close,n=14):
    d=close.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/n,adjust=False).mean(); al=l.ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+ag/al)
def cci(high,low,close,n=20):
    tp=(high+low+close)/3; sma=tp.rolling(n).mean(); mad=(tp-sma).abs().rolling(n).mean()
    return (tp-sma)/(0.015*mad)
def macd_hist(close,f=12,s=26,sig=9):
    ml=close.ewm(span=f,adjust=False).mean()-close.ewm(span=s,adjust=False).mean()
    return ml-ml.ewm(span=sig,adjust=False).mean()
def roc(close,n): return close/close.shift(n)-1.0
def obv(close,volume):
    sign=np.sign(close.diff()).replace(0,np.nan).fillna(0.0)
    return (sign*volume).cumsum()
def obv_slope(close,volume,n=20): return obv(close,volume).pct_change(n)
def ad_line(high,low,close,volume):
    denom=(high-low).replace(0,np.nan)
    return (((close-low)-(high-close))/denom*volume).cumsum()
def ad_slope(high,low,close,volume,n=20): return ad_line(high,low,close,volume).pct_change(n)
def cmf(high,low,close,volume,n=20):
    denom=(high-low).replace(0,np.nan)
    m=((close-low)-(high-close))/denom*volume
    return m.rolling(n).sum()/volume.rolling(n).sum()
def tsi(close,r=25,s=13):
    m=close.diff()
    e2=m.ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    a2=m.abs().ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    return e2/a2*100
def vortex(high,low,close,n=14):
    tr=true_range(high,low,close)
    vm_up=(high-low.shift()).abs(); vm_dn=(low-high.shift()).abs()
    return vm_up.rolling(n).sum()/tr.rolling(n).sum()-vm_dn.rolling(n).sum()/tr.rolling(n).sum()
def cmo(close,n=20):
    d=close.diff(); su=d.clip(lower=0).rolling(n).sum(); sd=(-d.clip(upper=0)).rolling(n).sum()
    return (su-sd)/(su+sd)*100
def stochastic(high,low,close,n=14):
    ll=low.rolling(n).min(); hh=high.rolling(n).max(); return (close-ll)/(hh-ll)*100
def sar_dist_df(close,high,low):
    def psar(h,l,af=0.02,mx=0.20):
        n=len(h); s=np.full(n,np.nan); ep=np.full(n,np.nan); up=np.zeros(n,bool); a=np.zeros(n)
        ep[0]=h[0]; s[0]=l[0]; up[0]=True; a[0]=af
        for i in range(1,n):
            ps=s[i-1]
            if up[i-1]:
                s[i]=ps+a[i-1]*(ep[i-1]-ps)
                if l[i]<s[i]: up[i]=False; s[i]=ep[i-1]; ep[i]=l[i]; a[i]=af
                else:
                    up[i]=True
                    if h[i]>ep[i-1]: ep[i]=h[i]; a[i]=min(a[i-1]+af,mx)
                    else: ep[i]=ep[i-1]; a[i]=a[i-1]
            else:
                s[i]=ps-a[i-1]*(ps-ep[i-1])
                if h[i]>s[i]: up[i]=True; s[i]=ep[i-1]; ep[i]=h[i]; a[i]=af
                else:
                    up[i]=False
                    if l[i]<ep[i-1]: ep[i]=l[i]; a[i]=min(a[i-1]+af,mx)
                    else: ep[i]=ep[i-1]; a[i]=a[i-1]
        return s
    out=pd.DataFrame(index=high.index,columns=high.columns,dtype=float)
    for c in high.columns: out[c]=close[c].values/psar(high[c].values,low[c].values)-1.0
    return out

sigs={
 "mom12_1": C.shift(21)/C.shift(252)-1.0,
 "ma_dist50": C/C.rolling(50).mean()-1.0,
 "ma_slope200": C.rolling(200).mean().pct_change(20),
 "rsi14": rsi(C,14), "cci20": cci(H,L,C,20), "macdH": macd_hist(C),
 "roc60": roc(C,60), "stochK": stochastic(H,L,C,14),
 "cmo20": cmo(C,20), "tsi": tsi(C), "vortex": vortex(H,L,C),
 "obv_slope": obv_slope(C,V), "ad_slope": ad_slope(H,L,C,V), "cmf20": cmf(H,L,C,V,20),
 "sar_dist": sar_dist_df(C,H,L),
}
print(f"{'指标':<14}{'NaN%':>8}{'inf%':>8}{'|值|>1e6 %':>12}{'P1':>12}{'P50':>10}{'P99':>12}{'零值%':>8}")
health={}
for k,s in sigs.items():
    a=s.values.astype(float)
    tot=a.size; nan=np.isnan(a).sum(); inf=np.isinf(a).sum()
    fin=a[np.isfinite(a)]
    big=(np.abs(fin)>1e6).sum()/tot*100 if fin.size else 0
    zero=(fin==0).sum()/tot*100 if fin.size else 0
    p1,p50,p99=(np.percentile(fin,[1,50,99]) if fin.size else (0,0,0))
    health[k]=dict(nan=nan/tot*100,inf=inf/tot*100,big=big,zero=zero,p1=p1,p99=p99)
    print(f"{k:<14}{nan/tot*100:>8.2f}{inf/tot*100:>8.3f}{big:>12.3f}{p1:>12.3f}{p50:>10.3f}{p99:>12.3f}{zero:>8.2f}")

print("\n>> 判定: P1/P99 出现 1e6 以上量级 = 数值爆炸(pct_change 分母过零), 该指标排名不可信")
for k,v in health.items():
    if abs(v["p1"])>1e4 or abs(v["p99"])>1e4 or v["inf"]>0:
        print(f"   [爆炸嫌疑] {k}: P1={v['p1']:.3g} P99={v['p99']:.3g} inf={v['inf']:.3f}%")

print("\n"+"="*100)
print("[D] 信号冗余体检: 月度调仓日的两两 Spearman 相关 (|ρ|>0.95 视为重复)")
print("="*100)
rb=[i for i in range(N) if i>=252 and (i-252)%21==0]
keys=list(sigs.keys())
M=pd.DataFrame(index=keys,columns=keys,dtype=float)
for a in keys:
    for b in keys:
        x=sigs[a].iloc[rb].values.ravel(); y=sigs[b].iloc[rb].values.ravel()
        ok=np.isfinite(x)&np.isfinite(y)
        if ok.sum()<50: M.loc[a,b]=np.nan; continue
        M.loc[a,b]=pd.Series(x[ok]).corr(pd.Series(y[ok]),method="spearman")
for a in keys:
    for b in keys:
        if a<b and abs(M.loc[a,b])>0.95:
            print(f"   [重复] {a} ~ {b}: rho={M.loc[a,b]:.3f}")

print("\n"+"="*100)
print("[E] 选股集中度 & 换手 (Top2)")
print("="*100)
print(f"{'指标':<14}{'不同票数':>9}{'Top1票(占比%)':>22}{'月均换手(只)':>14}")
for k,s in sigs.items():
    picks=[]
    prev=set()
    turn=0
    for i in rb:
        row=s.iloc[i].dropna().sort_values(ascending=False)
        if len(row)<2: continue
        p=set(row.index[:2]); picks+=list(p)
        if prev: turn+=len(p-prev)
        prev=p
    vc=pd.Series(picks).value_counts()
    top1=f"{vc.index[0]} ({vc.iloc[0]/len(picks)*100:.0f}%)" if len(vc) else "-"
    print(f"{k:<14}{len(vc):>9}{top1:>22}{turn/max(1,len(rb)):>14.2f}")

print("\n"+"="*100)
print("[F] 宇宙内等权买入持有基准 (关键! 用于校准 Top2 是否为真 alpha)")
print("="*100)
# 等权全持 37 只, 买入并持有(用 ffill 价格), 从首个全票有效日开始
eq_ret=ret.mean(axis=1)
start=max(sigs["mom12_1"].first_valid_index(), dates[252])
m=(pd.Series(dates)>=start).values
eq=np.cumprod(1+eq_ret.values[m])
print(f"等权全持有(37只, 每日再平衡口径) 从 {start.date()} 起:")
print(f"   终值倍数 x{eq[-1]:.2f} -> 若 $3000 起点 = ${3000*eq[-1]:.0f} (+{(eq[-1]-1)*100:.0f}%)")
# 月度调仓的等权全持(更接近策略口径)
print(f"   (对比 VOO 买入持有 +222.8%)")
voo=pd.read_csv(os.path.join(LONGDIR,"US_VOO.csv")); voo["time_key"]=pd.to_datetime(voo["time_key"])
vs=voo.set_index("time_key")["close"].reindex(dates).ffill()
print(f"   同期 VOO: x{vs.values[m][-1]/vs.values[m][0]:.2f} (+{(vs.values[m][-1]/vs.values[m][0]-1)*100:.0f}%)")
print("\n完成。")
