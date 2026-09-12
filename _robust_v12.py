# -*- coding: utf-8 -*-
"""
v12 稳健性检验: 高收益是否只由少数几个月贡献?
- 剔除最优 3/5/10 个月后的收益 (若暴跌 -> 收益靠运气)
- 月度胜率 / 逐年收益 / 最大连续亏损
- 换手与集中度
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
C=PX["close"].values; O=PX["open"].values; N,S=C.shape; dp=pd.to_datetime(dates)
RB=[i for i in range(N) if i>=START and (i-START)%21==0]

def backtest(score,topk=2,stop=0.0,rebal=21,regime=None,safe=None,slip=0.0005):
    A=np.asarray(score.values,dtype=float); A=np.where(np.isfinite(A),A,np.nan)
    cash=CAP0; pos={}; peak={}; entry={}; safe_sh=0.0; in_safe=False; pend=[]; pend_stop=[]; eq=[]
    comm=lambda sh: max(abs(sh)*0.005,1.0) if abs(sh)>0 else 0.0
    for i in range(N):
        co=C[i]; op=O[i]
        for c in pend_stop:
            if c in pos:
                sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh); peak.pop(c,None); entry.pop(c,None)
        pend_stop=[]
        for typ,arg in pend:
            if typ=="unsafe": cash+=safe_sh*safe[i]*(1-slip)-comm(safe_sh); safe_sh=0.0; in_safe=False
            elif typ=="rebal":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                peak.clear(); entry.clear()
                if arg:
                    for c in arg:
                        bud=cash/len(arg); pr=op[c]*(1+slip); sh=bud/pr
                        if sh>0 and cash>=sh*pr: cash-=sh*pr+comm(sh); pos[c]=sh; entry[c]=pr; peak[c]=pr
            elif typ=="safe":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                peak.clear(); entry.clear(); sh=cash/safe[i]
                if sh>0: cash-=sh*safe[i]*(1+slip)+comm(sh); safe_sh=sh; in_safe=True
            elif typ=="flat":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                peak.clear(); entry.clear()
        pend=[]
        for c in list(pos.keys()):
            p=co[c]; peak[c]=max(peak.get(c,entry[c]),p)
            if stop>0 and p<=peak[c]*(1-stop): pend_stop.append(c)
        bear=(regime is not None) and (not regime[i])
        if in_safe and not bear: pend.append(("unsafe",None))
        if i>=START and (i-START)%rebal==0 and not bear:
            row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
            if len(idx)>0: pend.append(("rebal",list(idx[np.argsort(-row[idx])][:topk])))
        if bear and len(pos)>0 and not in_safe: pend.append(("safe" if safe is not None else "flat",None))
        eq.append(cash+sum(pos.get(c,0)*co[c] for c in pos) if not in_safe else cash+safe_sh*safe[i])
    return np.array(eq)

dfH,dfL,dfC,dfV=[pd.DataFrame(PX[k].values,index=dp,columns=CODES) for k in ["high","low","close","volume"]]
ma50=dfC.rolling(50).mean(); ma200=dfC.rolling(200).mean()
def zs(x): return x.sub(x.mean(axis=1),axis=0).div(x.std(axis=1),axis=0)
def tsi(cl,r=25,s=13):
    m=cl.diff(); e2=m.ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    a2=m.abs().ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean(); return e2/a2*100
def vortex(h,lo,cl,n=14):
    pc=cl.shift(); t=np.maximum(np.maximum(h-lo,(h-pc).abs()),(lo-pc).abs())
    return (h-lo.shift()).abs().rolling(n).sum()/t.rolling(n).sum()-(lo-h.shift()).abs().rolling(n).sum()/t.rolling(n).sum()
def ad_slope(h,lo,cl,vol,n=20):
    d=(h-lo).replace(0,np.nan); return (((cl-lo)-(h-cl))/d*vol).cumsum().pct_change(n)
SIG={
 "动量-1月反转(z)": (zs(dfC.shift(21)/dfC.shift(252)-1.0)-zs(dfC/dfC.shift(21)-1.0))/2.0,
 "MA200斜率": ma200.pct_change(20),
 "金叉+MA50距离": (dfC/ma50-1.0).where(ma50>ma200),
 "TSI": tsi(dfC),
 "Vortex": vortex(dfH,dfL,dfC),
 "经典12-1动量": dfC.shift(21)/dfC.shift(252)-1.0,
 "AD线斜率": ad_slope(dfH,dfL,dfC,dfV),
}
# 基准: 等权买入持有
s0=np.nan_to_num(C[START],nan=0.0); ok=s0>0; w=np.where(ok,1.0/ok.sum(),0.0)
shares=CAP0*w/np.where(ok,s0,1.0); eq_bh=np.full(N,CAP0)
eq_bh[START:]=(np.nan_to_num(C,nan=0.0)@shares)[START:]

print("="*118)
print("[稳健性] 剔除最优月份后收益是否崩塌 (strict 引擎, 月度频率)")
print("="*118)
print(f"{'策略':<20}{'总收益%':>9}{'剔最优3月':>10}{'剔最优5月':>10}{'剔最优10月':>11}{'月胜率':>8}{'月度中位':>9}{'最差月':>8}")
print("-"*118)
out={}
for nm,sc in SIG.items():
    e=backtest(sc,topk=2)
    seg=e[RB]; r=np.diff(seg)/seg[:-1]
    tot=(e[-1]/CAP0-1)*100
    def drop(k):
        rr=r.copy(); rr.sort(); rr=rr[:-k]
        return (np.prod(1+rr)-1)*100
    out[nm]=dict(total=tot,d3=drop(3),d5=drop(5),d10=drop(10),win=(r>0).mean()*100,
                 med=np.median(r)*100,worst=r.min()*100)
    print(f"{nm:<20}{tot:>9.0f}{drop(3):>10.0f}{drop(5):>10.0f}{drop(10):>11.0f}{(r>0).mean()*100:>8.0f}{np.median(r)*100:>9.1f}{r.min()*100:>8.1f}")
rb=np.diff(eq_bh[RB])/eq_bh[RB][:-1]
def drop_b(k):
    rr=np.sort(rb)[:-k]; return (np.prod(1+rr)-1)*100
print("-"*118)
print(f"{'[基准] 等权买入持有':<20}{(eq_bh[-1]/CAP0-1)*100:>9.0f}{drop_b(3):>10.0f}{drop_b(5):>10.0f}{drop_b(10):>11.0f}{(rb>0).mean()*100:>8.0f}{np.median(rb)*100:>9.1f}{rb.min()*100:>8.1f}")
print("-"*118)
print("【超额倍数 = (1+策略)/(1+基准), 剔除最优月后仍>1 才算真 alpha】")
print(f"{'策略':<20}{'原始超额':>10}{'剔3月':>10}{'剔5月':>10}{'剔10月':>10}")
for nm,v in out.items():
    b=lambda k:(1+drop_b(k)/100)
    print(f"{nm:<20}{(1+v['total']/100)/(1+(eq_bh[-1]/CAP0-1)*100):>10.2f}"
          f"{(1+v['d3']/100)/b(3):>10.2f}{(1+v['d5']/100)/b(5):>10.2f}{(1+v['d10']/100)/b(10):>10.2f}")

print("\n"+"="*118)
print("[逐年收益%] 看收益是否集中在某一年")
print("="*118)
years=sorted(set(dp.year))
print(f"{'策略':<20}"+"".join(f"{y:>8}" for y in years))
for nm,sc in SIG.items():
    e=backtest(sc,topk=2); s=pd.Series(e,index=dp)
    row=[]
    for y in years:
        m=(dp.year==y)
        if m.sum()<2: row.append(np.nan); continue
        v=s[m]; row.append((v.iloc[-1]/v.iloc[0]-1)*100)
    print(f"{nm:<20}"+"".join(f"{v:>8.0f}" if np.isfinite(v) else f"{'-':>8}" for v in row))
s=pd.Series(eq_bh,index=dp); row=[]
for y in years:
    m=(dp.year==y); v=s[m]
    row.append((v.iloc[-1]/v.iloc[0]-1)*100 if len(v)>1 else np.nan)
print(f"{'[基准] 等权买入持有':<20}"+"".join(f"{v:>8.0f}" if np.isfinite(v) else f"{'-':>8}" for v in row))

json.dump(out,open(os.path.join(BASE,"_robust_v12.json"),"w"),ensure_ascii=False,indent=2)
print("\nSAVED _robust_v12.json")
