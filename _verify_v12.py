# -*- coding: utf-8 -*-
"""
v12 补充验证: 策略收益的数学上界 & 异常检测
------------------------------------------------------------------------------
1) 单票买入持有涨幅排行 (宇宙内谁是最大赢家)
2) 完美预期上界 (Perfect Foresight): 每次调仓都选到未来21天涨幅最高的票
   -> 任何策略收益都不可能超过它。若策略 ≈ 或 > 上界, 说明引擎有前视/复利 BUG。
3) 零成本 & 低换手版本的宇宙等权基准 (修正月度全额换手被佣金吃光的问题)
4) 异常月度收益检测 (单月 >150% 需怀疑数据错误)
5) 策略换手率 / 平均持仓数 / 集中度
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE=r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"; LONGDIR=os.path.join(BASE,"data_kline_long")
CAP0=3000.0
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
START=252
RB=[i for i in range(N) if i>=START and (i-START)%21==0]

print("="*112)
print(f"[1] 单票买入持有涨幅 ({dp[START].date()} -> {dp[-1].date()})")
print("="*112)
grow=C[-1]/C[START]
ord_=np.argsort(-grow)
for j in ord_[:8]:
    print(f"   {CODES[j]:<10} x{grow[j]:>7.2f}  (+{(grow[j]-1)*100:>8.0f}%)")
print(f"   ...\n   宇宙中位数 x{np.median(grow):.2f} | 最差 {CODES[ord_[-1]]} x{grow[ord_[-1]]:.2f}")
print(f"   >> 最大单票 = x{grow.max():.2f}. 策略若超过它是可能的(换股可叠加), 但不能超过'完美预期上界'。")

print("\n"+"="*112)
print("[2] 完美预期上界 Perfect Foresight (每次调仓都押中未来21天最强票)")
print("="*112)
def foresight(topk):
    eq=np.ones(len(RB)+1)
    for n,i in enumerate(RB):
        nxt=min(i+21,N-1)
        f=C[nxt]/C[i]-1.0
        f=np.where(np.isfinite(f),f,-np.inf)
        idx=np.argsort(-f)[:topk]
        r=np.mean(f[idx]) if topk>1 else f[idx[0]]
        eq[n+1]=eq[n]*(1+max(r,-0.99))
    return eq
for tk in (1,2,3):
    e=foresight(tk)
    print(f"   Top{tk} 完美预期: 终值 ${CAP0*e[-1]:,.0f}  (+{(e[-1]-1)*100:,.0f}%)   <== 数学上界")
e1=foresight(1); e2=foresight(2)

print("\n"+"="*112)
print("[3] 宇宙等权基准修正 (月度全额换手会被佣金吃光, 需低换手口径)")
print("="*112)
def ew_bh():
    s=np.nan_to_num(C[START],nan=0.0); ok=s>0
    w=np.where(ok,1.0/ok.sum(),0.0); sh=CAP0*w/np.where(ok,s,1.0)
    v=np.nan_to_num(C,nan=0.0)@sh; eq=np.full(N,CAP0); eq[START:]=v[START:]; return eq
def ew_rebal(comm_per_trade=0.0, rebal=21):
    cash=CAP0; pos={}; eq=[]
    hold=set()
    for i in range(N):
        if i>=START and (i-START)%rebal==0:
            ok=np.isfinite(C[i])&(C[i]>0)
            tgt=set(np.where(ok)[0])
            for c in list(pos):
                cash+=pos.pop(c)*C[i][c]; cash-=comm_per_trade
            if len(tgt)>0:
                bud=cash/len(tgt)
                for c in tgt:
                    sh=bud/C[i][c]
                    if sh>0: cash-=sh*C[i][c]; pos[c]=sh; cash-=comm_per_trade
        eq.append(cash+sum(pos.get(c,0)*C[i][c] for c in pos))
    return np.array(eq)
def mets(eq):
    eq=np.asarray(eq,float); r=np.diff(eq)/eq[:-1]
    pk=np.maximum.accumulate(eq)
    return dict(final=eq[-1],total=(eq[-1]/eq[0]-1)*100,cagr=((eq[-1]/eq[0])**(252/len(eq))-1)*100,
                sharpe=float(np.mean(r)/np.std(r)*np.sqrt(252)),mdd=float(((eq-pk)/pk).min()*100))
b_bh=mets(ew_bh()); b_r0=mets(ew_rebal(0.0)); b_r1=mets(ew_rebal(1.0))
print(f"   等权买入持有(零换手)      : ${b_bh['final']:>9,.0f} (+{b_bh['total']:>7.0f}%) 夏普 {b_bh['sharpe']:.2f} 回撤 {b_bh['mdd']:.0f}%")
print(f"   等权月度再平衡(零佣金)    : ${b_r0['final']:>9,.0f} (+{b_r0['total']:>7.0f}%) 夏普 {b_r0['sharpe']:.2f} 回撤 {b_r0['mdd']:.0f}%")
print(f"   等权月度再平衡($1/笔)     : ${b_r1['final']:>9,.0f} (+{b_r1['total']:>7.0f}%)  <- 37只全额换手被佣金摧毁")
print(f"   >> 采用【等权月度再平衡(零佣金)】做主基准: +{b_r0['total']:.0f}%")

print("\n"+"="*112)
print("[4] 关键策略 vs 上界 vs 基准 (strict 引擎)")
print("="*112)
# 复用 v12 引擎
import importlib.util
spec=importlib.util.spec_from_file_location("v12", os.path.join(BASE,"_fix_engine_v12.py"))
# 直接复制精简引擎, 避免重复执行主流程
def backtest(score, topk=2, stop=0.0, rebal=21, regime=None, safe=None, start=START, seed=None, slip=0.0005):
    A=np.asarray(score.values,dtype=float); A=np.where(np.isfinite(A),A,np.nan)
    cash=CAP0; pos={}; peak={}; entry={}; stopped={}; safe_sh=0.0; in_safe=False
    pend=[]; pend_stop=[]; eq=[]
    rng=np.random.default_rng(seed) if seed is not None else None
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
                peak.clear(); entry.clear()
                sh=cash/safe[i]
                if sh>0: cash-=sh*safe[i]*(1+slip)+comm(sh); safe_sh=sh; in_safe=True
            elif typ=="flat":
                for c in list(pos.keys()):
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                peak.clear(); entry.clear()
        pend=[]
        for c in list(pos.keys()):
            p=co[c]; peak[c]=max(peak.get(c,entry[c]),p)
            if stop>0 and p<=peak[c]*(1-stop): pend_stop.append(c); stopped[c]=peak[c]
        bear=(regime is not None) and (not regime[i])
        if in_safe and not bear: pend.append(("unsafe",None))
        if i>=start and (i-start)%rebal==0 and not bear:
            row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
            if len(idx)>0:
                pick=(list(rng.choice(idx,size=min(topk,len(idx)),replace=False)) if rng is not None
                      else list(idx[np.argsort(-row[idx])][:topk]))
                pend.append(("rebal",pick))
        if bear and len(pos)>0 and not in_safe: pend.append(("safe" if safe is not None else "flat",None))
        eq.append(cash+sum(pos.get(c,0)*co[c] for c in pos) if not in_safe else cash+safe_sh*safe[i])
    return np.array(eq)

dfH,dfL,dfC,dfV=[pd.DataFrame(PX[k].values,index=dp,columns=CODES) for k in ["high","low","close","volume"]]
ma50=dfC.rolling(50).mean(); ma200=dfC.rolling(200).mean()
def zs(x): return x.sub(x.mean(axis=1),axis=0).div(x.std(axis=1),axis=0)
SIG={
 "经典12-1动量": dfC.shift(21)/dfC.shift(252)-1.0,
 "金叉+MA50距离": (dfC/ma50-1.0).where(ma50>ma200),
 "MA200斜率": ma200.pct_change(20),
 "Vortex": None,"TSI": None,
 "动量-1月反转(z)": None,
}
def vortex(h,lo,cl,n=14):
    pc=cl.shift(); t=np.maximum(np.maximum(h-lo,(h-pc).abs()),(lo-pc).abs())
    vu=(h-lo.shift()).abs(); vd=(lo-h.shift()).abs()
    return vu.rolling(n).sum()/t.rolling(n).sum()-vd.rolling(n).sum()/t.rolling(n).sum()
def tsi(cl,r=25,s=13):
    m=cl.diff(); e2=m.ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    a2=m.abs().ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean(); return e2/a2*100
SIG["Vortex"]=vortex(dfH,dfL,dfC); SIG["TSI"]=tsi(dfC)
SIG["动量-1月反转(z)"]=(zs(SIG["经典12-1动量"])-zs(dfC/dfC.shift(21)-1.0))/2.0

_,vp=load(["US.VOO"]); VOO=vp["close"]["US.VOO"].values
REGIME=VOO>pd.Series(VOO).rolling(200).mean().values

print(f"{'策略':<22}{'总收益%':>10}{'终值$':>12}{'占上界%':>9}{'vs等权':>9}{'夏普':>7}{'回撤%':>8}")
print("-"*112)
ub=e2[-1]
res={}
for nm,sc in SIG.items():
    e=backtest(sc,topk=2); m=mets(e); res[nm]=m
    print(f"{nm:<22}{m['total']:>10.0f}{m['final']:>12,.0f}{(e[-1]/CAP0)/ub*100:>9.2f}{(1+m['total']/100)/(1+b_r0['total']/100):>9.2f}{m['sharpe']:>7.2f}{m['mdd']:>8.1f}")
    if (e[-1]/CAP0)>ub*1.05:
        print(f"      !!! 超过完美预期上界 -> 引擎必然有 BUG")
for nm in ["经典12-1动量","金叉+MA50距离","Vortex"]:
    e=backtest(SIG[nm],topk=2,stop=0.15,regime=REGIME,safe=VOO); m=mets(e)
    print(f"{nm+'+止损+200DMA':<22}{m['total']:>10.0f}{m['final']:>12,.0f}{(e[-1]/CAP0)/ub*100:>9.2f}{(1+m['total']/100)/(1+b_r0['total']/100):>9.2f}{m['sharpe']:>7.2f}{m['mdd']:>8.1f}")
print("-"*112)
print(f"{'[上界] 完美预期Top2':<22}{(ub-1)*100:>10.0f}{CAP0*ub:>12,.0f}{100.0:>9.2f}{ub/(1+b_r0['total']/100):>9.2f}")
print(f"{'[基准] 等权月再平衡(0佣)':<22}{b_r0['total']:>10.0f}{b_r0['final']:>12,.0f}{(b_r0['final']/CAP0)/ub*100:>9.2f}{1.0:>9.2f}{b_r0['sharpe']:>7.2f}{b_r0['mdd']:>8.1f}")
print(f"{'[基准] 等权买入持有':<22}{b_bh['total']:>10.0f}{b_bh['final']:>12,.0f}{(b_bh['final']/CAP0)/ub*100:>9.2f}{(1+b_bh['total']/100)/(1+b_r0['total']/100):>9.2f}{b_bh['sharpe']:>7.2f}{b_bh['mdd']:>8.1f}")
voo=VOO[-1]/VOO[START]
print(f"{'[基准] VOO买入持有':<22}{(voo-1)*100:>10.0f}{CAP0*voo:>12,.0f}{voo/ub*100:>9.2f}{voo/(1+b_r0['total']/100):>9.2f}")

print("\n"+"="*112)
print("[5] 异常检测: 策略单月收益 >150% 的次数 (数据错误/复利BUG的信号)")
print("="*112)
for nm,sc in SIG.items():
    e=backtest(sc,topk=2)
    mr=[]; prev=RB[0]
    seg=[e[prev]]
    for i in RB[1:]:
        seg.append(e[i])
    seg=np.array(seg); rr=np.diff(seg)/seg[:-1]
    print(f"   {nm:<22} 单月最大 +{rr.max()*100:>6.0f}%  最小 {rr.min()*100:>6.0f}%  |>+150%| 次数={int((rr>1.5).sum())}")

print("\n"+"="*112)
print("[6] 幸存者偏差量化: 宇宙 vs 大盘")
print("="*112)
print(f"   宇宙等权(37只, 事后按2026年市值选) : +{b_bh['total']:.0f}%")
print(f"   VOO(同期大盘)                      : +{(voo-1)*100:.0f}%")
print(f"   >> 选股池本身跑赢大盘 {(1+b_bh['total']/100)/voo:.1f} 倍 = 纯幸存者偏差(用2026年的赢家名单回测2018年)")
print(f"   >> 12只票上市晚于2018(TEM缺74%), 宇宙随时间扩大 -> 回填偏差")
json.dump(dict(ub_top2=float(ub),ub_top1=float(e1[-1]),ew_rebal0=dict(b_r0),ew_bh=dict(b_bh),
               voo=float(voo),grow_max=float(grow.max()),
               strategies={k:dict(v) for k,v in res.items()}),
          open(os.path.join(BASE,"_verify_v12.json"),"w"),ensure_ascii=False,indent=2)
print("\nSAVED _verify_v12.json")
