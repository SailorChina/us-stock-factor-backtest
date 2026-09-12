# -*- coding: utf-8 -*-
"""
v12 明细: Vortex 与 动量-1月反转 的原理验证 + 牛熊分段 + 逐年 + 当前信号
strict 引擎 (T日收盘信号 -> T+1开盘成交, 0.005/股最低$1, 0.05%滑点, 允许碎股)
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE=r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"; LONGDIR=os.path.join(BASE,"data_kline_long")
CAP0=3000.0; START=252
def is_etf(n):
    n=(n or "").upper(); return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
mi=json.load(open(os.path.join(BASE,"market_info.json"))); fetched=json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI=[c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0) or 0)>=10e9]
def load(codes):
    p={}
    for c in codes:
        d=pd.read_csv(os.path.join(LONGDIR,c.replace(".","_")+".csv")); d["time_key"]=pd.to_datetime(d["time_key"])
        p[c]=d.sort_values("time_key").reset_index(drop=True).set_index("time_key")
    ad=sorted(set().union(*[set(x.index) for x in p.values()])); dt=pd.to_datetime(ad)
    return dt,{k:pd.DataFrame({c:p[c][k].reindex(dt).ffill() for c in codes}) for k in ["open","high","low","close","volume"]}
dates,PX=load(UNI); CODES=UNI
C=PX["close"].values; O=PX["open"].values; H=PX["high"].values; L=PX["low"].values
N,S=C.shape; dp=pd.to_datetime(dates)
RB=[i for i in range(N) if i>=START and (i-START)%21==0]

def backtest(score,topk=2,slip=0.0005):
    A=np.asarray(score.values,dtype=float); A=np.where(np.isfinite(A),A,np.nan)
    cash=CAP0; pos={}; peak={}; entry={}; pend=[]; eq=[]; hist=[]
    comm=lambda sh: max(abs(sh)*0.005,1.0) if abs(sh)>0 else 0.0
    for i in range(N):
        co=C[i]; op=O[i]
        for typ,arg in pend:
            if typ=="rebal":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                peak.clear(); entry.clear()
                if arg:
                    for c in arg:
                        bud=cash/len(arg); pr=op[c]*(1+slip); sh=bud/pr
                        if sh>0 and cash>=sh*pr: cash-=sh*pr+comm(sh); pos[c]=sh; entry[c]=pr; peak[c]=pr
        pend=[]
        if i>=START and (i-START)%21==0:
            row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
            if len(idx)>0:
                pick=list(idx[np.argsort(-row[idx])][:topk]); pend.append(("rebal",pick))
                hist.append((str(dp[i].date()),[CODES[c] for c in pick]))
        eq.append(cash+sum(pos.get(c,0)*co[c] for c in pos))
    return np.array(eq), hist

dfH,dfL,dfC=[pd.DataFrame(x,index=dp,columns=CODES) for x in (H,L,C)]
def zs(x): return x.sub(x.mean(axis=1),axis=0).div(x.std(axis=1),axis=0)
def vortex(h,lo,cl,n=14):
    pc=cl.shift(); tr=np.maximum(np.maximum(h-lo,(h-pc).abs()),(lo-pc).abs())
    vip=(h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    vim=(lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    return vip-vim
mom12_1 = dfC.shift(21)/dfC.shift(252)-1.0
rev1    = dfC/dfC.shift(21)-1.0
SIG={"Vortex": vortex(dfH,dfL,dfC), "动量-1月反转": (zs(mom12_1)-zs(rev1))/2.0}

# 基准: 等权买入持有
s0=np.nan_to_num(C[START],nan=0.0); ok=s0>0; w=np.where(ok,1.0/ok.sum(),0.0)
shares=CAP0*w/np.where(ok,s0,1.0); eq_bh=np.full(N,CAP0); eq_bh[START:]=(np.nan_to_num(C,nan=0.0)@shares)[START:]
_,vp=load(["US.VOO"]); VOO=vp["close"]["US.VOO"].values

PHASES=[("2018 牛市(至顶)","2018-01-02","2018-09-20","牛"),
        ("2018 Q4 回落","2018-09-21","2018-12-24","熊"),
        ("2019-2020.2 牛市","2019-01-01","2020-02-19","牛"),
        ("2020 疫情崩盘","2020-02-19","2020-03-23","熊"),
        ("2020-2021 牛市","2020-03-24","2021-12-31","牛"),
        ("2022 熊市","2022-01-03","2022-10-12","熊"),
        ("2023-2026 牛市","2023-01-01","2026-09-10","牛")]
def seg(eq,s,e):
    m=(dp>=pd.Timestamp(s))&(dp<=pd.Timestamp(e)); idx=np.where(m)[0]
    if len(idx)<2: return None
    a,b=idx[0],idx[-1]
    if a<START: a=START
    if b<=a: return None
    v=eq[a:b+1]; sub=(v-np.maximum.accumulate(v))/np.maximum.accumulate(v)
    return (v[-1]/v[0]-1)*100, sub.min()*100

print("="*120)
print("原理指标体检: Vortex 与 动量-1月反转 到底在选什么票")
print("="*120)
for nm,sc in SIG.items():
    a=sc.iloc[RB]
    print(f"\n--- {nm} ---")
    print(f"  数值范围: P5={np.nanpercentile(a,5):.3f}  中位={np.nanmedian(a):.3f}  P95={np.nanpercentile(a,95):.3f}")
    # 与未来21日收益的横截面 IC
    fwd=dfC.shift(-21)/dfC-1.0
    ics=[]
    for i in RB[:-1]:
        x=sc.iloc[i]; y=fwd.iloc[i]
        ok=np.isfinite(x)&np.isfinite(y)
        if ok.sum()>=10: ics.append(pd.Series(x[ok]).corr(pd.Series(y[ok]),method="spearman"))
    ics=np.array(ics)
    print(f"  预测力 IC(与未来21日收益的横截面Spearman): 均值={np.nanmean(ics):.4f}  正比例={(ics>0).mean()*100:.0f}%")
    # 选出的票的平均波动率 vs 宇宙
    vol=pd.DataFrame(C,index=dp,columns=CODES).pct_change().rolling(21).std()
    sel=[]; allv=[]
    for i in RB:
        x=sc.iloc[i].dropna().sort_values(ascending=False)
        if len(x)<2: continue
        for c in x.index[:2]:
            if np.isfinite(vol[c].iloc[i]): sel.append(vol[c].iloc[i])
        allv+= [v for v in vol.iloc[i].values if np.isfinite(v)]
    print(f"  选中票的21日波动率: {np.mean(sel)*100:.2f}%   宇宙平均: {np.mean(allv)*100:.2f}%  "
          f"({'更低=选得更稳' if np.mean(sel)<np.mean(allv) else '更高=选得更猛'})")
    # 选中票的近1月涨幅 vs 近1年涨幅
    m1=[]; y1=[]
    for i in RB:
        x=sc.iloc[i].dropna().sort_values(ascending=False)
        if len(x)<2: continue
        for c in x.index[:2]:
            if np.isfinite(rev1[c].iloc[i]): m1.append(rev1[c].iloc[i])
            if np.isfinite(mom12_1[c].iloc[i]): y1.append(mom12_1[c].iloc[i])
    print(f"  选中票近1月涨幅 {np.mean(m1)*100:+.1f}% | 近1年涨幅 {np.mean(y1)*100:+.1f}%   (宇宙近1月均值 {np.nanmean(rev1.iloc[RB].values)*100:+.1f}%)")

print("\n"+"="*120)
print("牛熊分段收益 (strict 引擎)")
print("="*120)
res={}
for nm,sc in SIG.items():
    e,h=backtest(sc); res[nm]=(e,h)
def f2(r,w=12):
    return (f"{r[0]:+.0f}%").rjust(w) if r else "预热期".rjust(w)
print(f"{'阶段':<20}{'性质':>4}{'Vortex':>12}{'动量-1月反转':>14}{'等权全买':>12}{'VOO':>10}")
print("-"*120)
for name,s,ee,kind in PHASES:
    row=[f2(seg(res[nm][0],s,ee)) for nm in ["Vortex","动量-1月反转"]]
    print(f"{name:<20}{kind:>4}{row[0]:>12}{row[1]:>14}{f2(seg(eq_bh,s,ee)):>12}{f2(seg(VOO,s,ee),10):>10}")
print("-"*120)
print(f"{'全程':<20}{'':>4}", end="")
for nm in ["Vortex","动量-1月反转"]:
    print(f"{(res[nm][0][-1]/CAP0-1)*100:>+11.0f}%", end="  ")
print(f"{(eq_bh[-1]/CAP0-1)*100:>+10.0f}%{(VOO[-1]/VOO[START]-1)*100:>+9.0f}%")

print("\n各阶段最大回撤 (区间内最惨时亏多少)")
def f3(r,w=12):
    return (f"{r[1]:.0f}%").rjust(w) if r else "预热期".rjust(w)
print(f"{'阶段':<20}{'Vortex':>12}{'动量-1月反转':>14}{'等权全买':>12}{'VOO':>10}")
print("-"*120)
for name,s,ee,kind in PHASES:
    row=[f3(seg(res[nm][0],s,ee)) for nm in ["Vortex","动量-1月反转"]]
    print(f"{name:<20}{row[0]:>12}{row[1]:>14}{f3(seg(eq_bh,s,ee)):>12}{f3(seg(VOO,s,ee),10):>10}")

print("\n"+"="*120)
print("逐年收益 & 月度胜率")
print("="*120)
years=[2019,2020,2021,2022,2023,2024,2025,2026]
print(f"{'年份':<8}{'Vortex':>12}{'动量-1月反转':>14}{'等权全买':>12}{'VOO':>10}  胜者")
print("-"*120)
for y in years:
    m=(dp.year==y); vals={}
    for nm in ["Vortex","动量-1月反转"]:
        v=pd.Series(res[nm][0],index=dp)[m]; vals[nm]=(v.iloc[-1]/v.iloc[0]-1)*100
    vb=pd.Series(eq_bh,index=dp)[m]; vv=pd.Series(VOO,index=dp)[m]
    vals["基准"]=(vb.iloc[-1]/vb.iloc[0]-1)*100; vals["VOO"]=(vv.iloc[-1]/vv.iloc[0]-1)*100
    win=max(vals,key=vals.get)
    print(f"{y:<8}{vals['Vortex']:>+11.0f}%{vals['动量-1月反转']:>+13.0f}%{vals['基准']:>+11.0f}%{vals['VOO']:>+9.0f}%  {win}")
print("-"*120)
for nm in ["Vortex","动量-1月反转"]:
    e=res[nm][0]; s=e[RB]; r=np.diff(s)/s[:-1]
    # 最大连亏月数
    st=0; mx=0
    for x in r:
        st = st+1 if x<0 else 0
        mx=max(mx,st)
    print(f"{nm:<14} 月度胜率 {(r>0).mean()*100:.0f}% | 最好月 {r.max()*100:+.0f}% | 最差月 {r.min()*100:+.0f}% | 最长连亏 {mx} 个月")
rb=np.diff(eq_bh[RB])/eq_bh[RB][:-1]
st=0;mx=0
for x in rb:
    st=st+1 if x<0 else 0; mx=max(mx,st)
print(f"{'等权全买':<14} 月度胜率 {(rb>0).mean()*100:.0f}% | 最好月 {rb.max()*100:+.0f}% | 最差月 {rb.min()*100:+.0f}% | 最长连亏 {mx} 个月")

print("\n"+"="*120)
print("当前信号 (2026-09-10 收盘后计算, 次日开盘买入)")
print("="*120)
for nm in ["Vortex","动量-1月反转"]:
    h=res[nm][1]
    print(f"  {nm:<14} 最近6期选股:")
    for d,p in h[-6:]:
        print(f"      {d}  ->  {', '.join(x.replace('US.','') for x in p)}")

print("\n"+"="*120)
print("历史持仓统计 (选中最多次的票)")
print("="*120)
for nm in ["Vortex","动量-1月反转"]:
    h=res[nm][1]
    vc=pd.Series([x.replace("US.","") for _,p in h for x in p]).value_counts()
    print(f"  {nm:<14} 共调仓 {len(h)} 次 | Top8: " + ", ".join(f"{k}({v})" for k,v in vc.head(8).items()))
    print(f"                 平均每次换手 {np.mean([len(set(h[i][1])-set(h[i-1][1])) for i in range(1,len(h))]):.2f} 只/月")

json.dump({nm:{"final":float(res[nm][0][-1]),
               "phases":{n:(seg(res[nm][0],s,e) or [None])[0] for n,s,e,_ in PHASES}} for nm in res},
          open(os.path.join(BASE,"_detail_v12.json"),"w"),ensure_ascii=False,indent=2)
print("\nSAVED _detail_v12.json")
