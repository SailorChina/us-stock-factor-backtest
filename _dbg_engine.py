# -*- coding: utf-8 -*-
"""定位 v14 引擎与 v13(_detail_v12) 引擎的差异: 同一 Vortex 信号, 两个引擎跑对比"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
CAP0 = 3000.0; START = 252
def is_etf(n):
    n=(n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
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
dfH,dfL,dfC=[pd.DataFrame(x,index=dp,columns=CODES) for x in (H,L,C)]
def vortex(h,lo,cl,n=14):
    pc=cl.shift(); tr=np.maximum(np.maximum(h-lo,(h-pc).abs()),(lo-pc).abs())
    vip=(h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    vim=(lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
    return vip-vim
SC=vortex(dfH,dfL,dfC)

# ---------- 旧引擎 (完全照抄 _detail_v12.py) ----------
def old_bt(score,topk=2,slip=0.0005):
    A=np.asarray(score.values,dtype=float); A=np.where(np.isfinite(A),A,np.nan)
    cash=CAP0; pos={}; pend=[]; eq=[]; hist=[]
    comm=lambda sh: max(abs(sh)*0.005,1.0) if abs(sh)>0 else 0.0
    for i in range(N):
        co=C[i]; op=O[i]
        for typ,arg in pend:
            if typ=="rebal":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                if arg:
                    for c in arg:
                        bud=cash/len(arg); pr=op[c]*(1+slip); sh=bud/pr
                        if sh>0 and cash>=sh*pr: cash-=sh*pr+comm(sh); pos[c]=sh
        pend=[]
        if i>=START and (i-START)%21==0:
            row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
            if len(idx)>0:
                pick=list(idx[np.argsort(-row[idx])][:topk]); pend.append(("rebal",pick))
                hist.append((str(dp[i].date()),[CODES[c] for c in pick]))
        eq.append(cash+sum(pos.get(c,0)*co[c] for c in pos))
    return np.array(eq),hist

# ---------- 新引擎 (v14) ----------
def new_bt(score,topk=2,expo=None,safe=None,slip=0.0005,dd_stop=None):
    A=np.asarray(score.values,dtype=float); A=np.where(np.isfinite(A),A,np.nan)
    expo=np.ones(N) if expo is None else np.asarray(expo,dtype=float)
    comm=lambda sh: max(abs(sh)*0.005,1.0) if abs(sh)>0 else 0.0
    cash=CAP0; pos={}; safe_sh=0.0; pend=[]; eq=[]; nav_peak=CAP0; halted=False
    last_pick=None; hist=[]; nreb=0
    def liquidate(op_i):
        nonlocal cash
        for c in list(pos.keys()):
            sh=pos.pop(c); cash+=sh*op_i[c]*(1-slip)-comm(sh)
    for i in range(N):
        co=C[i]; op=O[i]
        for typ,arg in pend:
            if typ=="rebal":
                liquidate(op); picks=arg
                if picks and expo[i]>0:
                    budget=cash*expo[i]
                    for c in picks:
                        pr=op[c]*(1+slip); sh=(budget/len(picks))/pr
                        if sh>0 and cash>=sh*pr: cash-=sh*pr+comm(sh); pos[c]=sh
                if safe is not None and expo[i]<1:
                    pr=safe[i]*(1+slip); budget=cash*(1-expo[i]); sh=budget/pr if pr>0 else 0
                    if sh>0 and cash>=sh*pr: cash-=sh*pr+comm(sh); safe_sh+=sh
            elif typ=="exit_safe":
                if safe_sh>0: cash+=safe_sh*safe[i]*(1-slip)-comm(safe_sh); safe_sh=0.0
        pend=[]
        nav=cash+safe_sh*(safe[i] if safe is not None else 0)+sum(pos.get(c,0)*co[c] for c in pos)
        eq.append(nav); nav_peak=max(nav_peak,nav)
        if i>=START:
            eff_expo=expo[i]
            if dd_stop is not None:
                if halted:
                    if nav>=nav_peak*(1-dd_stop*0.5): halted=False
                else:
                    if nav<=nav_peak*(1-dd_stop): halted=True
                if halted: eff_expo=0.0
            state_changed=False
            if i>START:
                prev_eff=expo[i-1]
                if dd_stop is not None and halted and prev_eff>0: prev_eff=0.0
                if abs(eff_expo-prev_eff)>1e-9: state_changed=True
            want_rebal=((i-START)%21==0)
            if want_rebal:
                row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
                if len(idx)>0:
                    last_pick=list(idx[np.argsort(-row[idx])][:topk])
                    hist.append((str(dp[i].date()),[CODES[c] for c in last_pick]))
            if state_changed or (want_rebal and last_pick is not None):
                pend.append(("exit_safe",None)); pend.append(("rebal",last_pick))
    return np.array(eq),hist

eo,ho=old_bt(SC); en,hn=new_bt(SC)
print(f"调仓次数  旧={len(ho)}  新={len(hn)}")
print(f"全程      旧={(eo[-1]/CAP0-1)*100:+.0f}%   新={(en[-1]/CAP0-1)*100:+.0f}%")
print()
print("前 8 次调仓对比")
print(f"{'#':<4}{'日期':<12}{'旧引擎选股':<28}{'新引擎选股':<28}{'一致'}")
print("-"*84)
for k in range(8):
    d1=ho[k][0] if k<len(ho) else "-"; p1=",".join(x.replace("US.","") for x in ho[k][1]) if k<len(ho) else "-"
    d2=hn[k][0] if k<len(hn) else "-"; p2=",".join(x.replace("US.","") for x in hn[k][1]) if k<len(hn) else "-"
    print(f"{k:<4}{d1:<12}{p1:<28}{p2:<28}{'Y' if p1==p2 else 'N'}")
print()
print("日期对齐后的选股一致率:")
d_old={d:p for d,p in ho}; d_new={d:p for d,p in hn}
same=sum(1 for d in d_old if d in d_new and d_old[d]==d_new[d])
print(f"  共同日期 {len(set(d_old)&set(d_new))} 个, 选股一致 {same} 个 ({same/max(1,len(set(d_old)&set(d_new)))*100:.0f}%)")
print()
print("关键日期净值对比")
print(f"{'日期':<12}{'旧引擎':>14}{'新引擎':>14}{'比值':>8}")
print("-"*84)
for ds in ["2020-01-02","2020-06-01","2021-01-04","2022-01-03","2022-10-12","2023-01-03","2024-01-02","2025-01-02","2026-01-02"]:
    m=(dp>=pd.Timestamp(ds)); idx=np.where(m)[0]
    if len(idx)==0: continue
    j=idx[0]
    print(f"{ds:<12}{eo[j]:>13.0f}{en[j]:>14.0f}{en[j]/eo[j]:>8.2f}")
