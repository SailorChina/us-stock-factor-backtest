# -*- coding: utf-8 -*-
"""
v12 BUG 修复与验证引擎
=================================================================================
体检(_audit_v12.py)发现的真实问题, 本脚本逐个隔离并量化其影响:

  BUG-1 [致命-基准] 宇宙内等权买入持有 = +1677%, VOO 仅 +249%。
        之前所有"超额收益"用 VOO 做基准 -> 严重夸大。必须改用宇宙等权(EW_ALL)做基准。
  BUG-2 [严重-inf]  obv_slope / ad_slope 用 pct_change 于累积量, 分母过零产生 inf;
        而回测里 dropna() 不剔除 inf, inf 会被 sort 选为 Top1 -> 选出垃圾票。
  BUG-3 [前视]     信号用 T 日收盘价计算, 却以 T 日收盘价成交(实务做不到)。
                   修复: T 日收盘产生指令 -> T+1 日开盘成交。
  BUG-4 [成本]     佣金 max(0.01/股, 1.5) 偏高但无滑点。修复: 0.005/股最低1.0 + 0.05%滑点。
  BUG-5 [碎股]     3000 本金整股取整 -> 高价股买不起而闲置现金。修复: 允许碎股(富途支持)。
  BUG-6 [逻辑]     月度调仓日 stopped_peak.clear() 清空了止损记录, recover 再入场失效。
  BUG-7 [偏差]     12 只票上市晚(TEM 缺 74%), 宇宙随时间扩大 -> 回填偏差(结构性, 只能披露)。

验证方法: 同一批策略跑三档引擎, 隔离每个 bug 的贡献:
  档A legacy   : 完全复刻 v11 (当日收盘成交, 旧佣金, 整股, inf 不清洗)
  档B +时序修复: 仅改成 T+1 开盘成交
  档C +全修复  : 时序 + 真实成本 + 碎股 + inf 清洗  (= strict)
另加: 宇宙等权基准 EW_ALL / 蒙特卡洛随机选股 300 次(判断真 alpha 还是运气) /
      前后半段稳定性(排名是否稳定)。
"""
import os, json, time, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
CAP0 = 3000.0
MC_N = 300

def is_etf(name):
    n=(name or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
mi=json.load(open(os.path.join(BASE,"market_info.json")))
fetched=json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI=[c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0) or 0)>=10e9]

def load(codes):
    panel={}
    for c in codes:
        df=pd.read_csv(os.path.join(LONGDIR,c.replace(".","_")+".csv"))
        df["time_key"]=pd.to_datetime(df["time_key"])
        panel[c]=df.sort_values("time_key").reset_index(drop=True).set_index("time_key")
    all_dates=sorted(set().union(*[set(df.index) for df in panel.values()]))
    dates=pd.to_datetime(all_dates); out={}
    for col in ["open","high","low","close","volume"]:
        out[col]=pd.DataFrame({c: panel[c][col].reindex(dates).ffill() for c in codes})
    return dates,out

dates,PX=load(UNI)
CODES=UNI
O,H,L,C,V=[PX[k].values for k in ["open","high","low","close","volume"]]
N,S=C.shape
dates_pd=pd.to_datetime(dates)

_,vp=load(["US.VOO"]); VOO=vp["close"]["US.VOO"].values
voo_ma=pd.Series(VOO).rolling(200).mean().values
REGIME=(VOO>voo_ma)

# ================= 指标库 =================
def tr(high,low,close):
    pc=close.shift(); return np.maximum(np.maximum(high-low,(high-pc).abs()),(low-pc).abs())
def rsi(cl,n=14):
    d=cl.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(alpha=1/n,adjust=False).mean(); al=l.ewm(alpha=1/n,adjust=False).mean()
    return 100-100/(1+ag/al)
def cci(h,lo,cl,n=20):
    tp=(h+lo+cl)/3; sma=tp.rolling(n).mean(); mad=(tp-sma).abs().rolling(n).mean()
    return (tp-sma)/(0.015*mad)
def macd_hist(cl,f=12,s=26,sg=9):
    m=cl.ewm(span=f,adjust=False).mean()-cl.ewm(span=s,adjust=False).mean()
    return m-m.ewm(span=sg,adjust=False).mean()
def roc(cl,n): return cl/cl.shift(n)-1.0
def stoch(h,lo,cl,n=14):
    return (cl-lo.rolling(n).min())/(h.rolling(n).max()-lo.rolling(n).min())*100
def obv_slope(cl,vol,n=20):
    sg=np.sign(cl.diff()).replace(0,np.nan).fillna(0.0)
    return (sg*vol).cumsum().pct_change(n)
def ad_slope(h,lo,cl,vol,n=20):
    d=(h-lo).replace(0,np.nan)
    return (((cl-lo)-(h-cl))/d*vol).cumsum().pct_change(n)
def cmf(h,lo,cl,vol,n=20):
    d=(h-lo).replace(0,np.nan); m=((cl-lo)-(h-cl))/d*vol
    return m.rolling(n).sum()/vol.rolling(n).sum()
def mfi(h,lo,cl,vol,n=14):
    tp=(h+lo+cl)/3; rmf=tp*vol; up=tp.diff()>0; dn=tp.diff()<0
    p=rmf.where(up,0.0).rolling(n).sum(); q=rmf.where(dn,0.0).rolling(n).sum()
    return 100-100/(1+p/q.replace(0,np.nan))
def chaikin(h,lo,cl,vol,s=3,l=10):
    d=(h-lo).replace(0,np.nan); x=((cl-lo)-(h-cl))/d*vol
    return x.ewm(span=s,adjust=False).mean()-x.ewm(span=l,adjust=False).mean()
def tsi(cl,r=25,s=13):
    m=cl.diff(); e2=m.ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    a2=m.abs().ewm(span=r,adjust=False).mean().ewm(span=s,adjust=False).mean()
    return e2/a2*100
def vortex(h,lo,cl,n=14):
    t=tr(h,lo,cl); vu=(h-lo.shift()).abs(); vd=(lo-h.shift()).abs()
    return vu.rolling(n).sum()/t.rolling(n).sum()-vd.rolling(n).sum()/t.rolling(n).sum()
def cmo(cl,n=20):
    d=cl.diff(); su=d.clip(lower=0).rolling(n).sum(); sd=(-d.clip(upper=0)).rolling(n).sum()
    return (su-sd)/(su+sd)*100
def aroon(h,lo,n=25):
    up=h.rolling(n).apply(lambda x:((n-1)-x[::-1].argmax())/(n-1)*100,raw=True)
    dn=lo.rolling(n).apply(lambda x:((n-1)-x[::-1].argmin())/(n-1)*100,raw=True)
    return up-dn
def ichimoku(cl,h,lo):
    t=(h.rolling(9).max()+lo.rolling(9).min())/2; k=(h.rolling(26).max()+lo.rolling(26).min())/2
    a=(t+k)/2; b=(h.rolling(52).max()+lo.rolling(52).min())/2
    return cl/np.maximum(a,b)-1.0
def psar_dist(cl,h,lo):
    def ps(hi,lw,af=0.02,mx=0.20):
        n=len(hi); s=np.full(n,np.nan); ep=np.full(n,np.nan); up=np.zeros(n,bool); a=np.zeros(n)
        ep[0]=hi[0]; s[0]=lw[0]; up[0]=True; a[0]=af
        for i in range(1,n):
            p=s[i-1]
            if up[i-1]:
                s[i]=p+a[i-1]*(ep[i-1]-p)
                if lw[i]<s[i]: up[i]=False; s[i]=ep[i-1]; ep[i]=lw[i]; a[i]=af
                else:
                    up[i]=True
                    if hi[i]>ep[i-1]: ep[i]=hi[i]; a[i]=min(a[i-1]+af,mx)
                    else: ep[i]=ep[i-1]; a[i]=a[i-1]
            else:
                s[i]=p-a[i-1]*(p-ep[i-1])
                if hi[i]>s[i]: up[i]=True; s[i]=ep[i-1]; ep[i]=hi[i]; a[i]=af
                else:
                    up[i]=False
                    if lw[i]<ep[i-1]: ep[i]=lw[i]; a[i]=min(a[i-1]+af,mx)
                    else: ep[i]=ep[i-1]; a[i]=a[i-1]
        return s
    Hd,Ld,Cd=pd.DataFrame(h),pd.DataFrame(lo),pd.DataFrame(cl)
    out=pd.DataFrame(index=Hd.index,columns=Hd.columns,dtype=float)
    for c in Hd.columns: out[c]=Cd[c].values/ps(Hd[c].values,Ld[c].values)-1.0
    return out

dfO,dfH,dfL,dfC,dfV=[pd.DataFrame(x,index=dates_pd,columns=CODES) for x in (O,H,L,C,V)]
pct=lambda a,n: a/a.shift(n)-1.0
ma50=dfC.rolling(50).mean(); ma200=dfC.rolling(200).mean()

SIG={}
SIG["经典12-1动量"]=dfC.shift(21)/dfC.shift(252)-1.0
SIG["金叉+MA50距离"]=(dfC/ma50-1.0).where(ma50>ma200)
SIG["MA50距离"]=dfC/ma50-1.0
SIG["MA200斜率"]=ma200.pct_change(20)
SIG["AD线斜率"]=ad_slope(dfH,dfL,dfC,dfV)
SIG["ChaikinADOsc"]=chaikin(dfH,dfL,dfC,dfV)
SIG["CMF20"]=cmf(dfH,dfL,dfC,dfV,20)
SIG["MFI14"]=mfi(dfH,dfL,dfC,dfV,14)
SIG["OBV斜率"]=obv_slope(dfC,dfV)
SIG["TSI"]=tsi(dfC)
SIG["Vortex"]=vortex(dfH,dfL,dfC)
SIG["CCI20"]=cci(dfH,dfL,dfC,20)
SIG["CMO20"]=cmo(dfC,20)
SIG["Stochastic%K"]=stoch(dfH,dfL,dfC,14)
SIG["RSI14"]=rsi(dfC,14)
SIG["ROC60"]=roc(dfC,60)
SIG["MACD柱"]=macd_hist(dfC)
SIG["Ichimoku云"]=ichimoku(dfC,dfH,dfL)
SIG["Aroon25"]=aroon(dfH,dfL)
SIG["SAR距离"]=psar_dist(dfC,dfH,dfL)
SIG["1月反转"]=pct(dfC,21)
SIG["动量-1月反转(z)"]=None  # 稍后构造
def zs(x):
    m=x.mean(axis=1); s=x.std(axis=1); return x.sub(m,axis=0).div(s,axis=0)
SIG["动量-1月反转(z)"]=(zs(SIG["经典12-1动量"])-zs(SIG["1月反转"]))/2.0

# ================= 引擎 =================
def metrics(eq):
    eq=np.asarray(eq,float); r=np.diff(eq)/eq[:-1]
    total=eq[-1]/eq[0]-1; yrs=len(eq)/252.0
    cagr=(eq[-1]/eq[0])**(1/yrs)-1
    sh=np.mean(r)/np.std(r)*np.sqrt(252) if np.std(r)>0 else 0
    pk=np.maximum.accumulate(eq); mdd=((eq-pk)/pk).min()
    return dict(final=eq[-1],total=total*100,cagr=cagr*100,sharpe=sh,mdd=mdd*100)

def backtest(score, mode="C", topk=2, stop=0.0, rebal=21, regime=None, safe=None,
             start=252, clean_inf=True, seed=None):
    """mode: A=legacy(v11原样) / B=仅时序修复 / C=全修复(strict)"""
    sc=score.copy()
    if clean_inf: sc=sc.where(np.isfinite(sc),np.nan)
    A=np.asarray(sc.values,dtype=float)
    cash=CAP0; pos={}; peak={}; entry={}; stopped={}
    safe_sh=0.0; in_safe=False
    pend=[]; pend_stop=[]
    eq=[]
    if seed is not None:
        rng=np.random.default_rng(seed)
    else:
        rng=None
    for i in range(N):
        co=C[i]; op=O[i]
        if mode=="A":
            px=co
            if regime is not None:
                bear=not regime[i]
                if bear:
                    if safe is not None and not in_safe:
                        for c in list(pos.keys()): cash+=pos.pop(c)*px[c]-max(pos.get(c,0)*0.01,1.5)
                        peak.clear(); entry.clear()
                        sh=int(cash//safe[i]);
                        if sh>0: cash-=sh*safe[i]+max(sh*0.01,1.5); safe_sh=sh; in_safe=True
                    elif safe is None:
                        for c in list(pos.keys()): cash+=pos.pop(c)*px[c]-max(pos.get(c,0)*0.01,1.5)
                        peak.clear(); entry.clear(); eq.append(cash); continue
                else:
                    if in_safe: cash+=safe_sh*safe[i]-max(safe_sh*0.01,1.5); safe_sh=0; in_safe=False
                if in_safe: eq.append(cash+safe_sh*safe[i]); continue
            for c in list(pos.keys()):
                p=px[c]; peak[c]=max(peak.get(c,p),p)
                if stop>0 and p<=peak[c]*(1-stop):
                    sh=pos.pop(c); cash+=sh*p-max(sh*0.01,1.5)
                    stopped[c]=peak[c]; peak.pop(c,None); entry.pop(c,None)
            if i>=start and (i-start)%rebal==0:
                row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
                if rng is not None and len(idx)>0:
                    pick=list(rng.choice(idx,size=min(topk,len(idx)),replace=False))
                else:
                    order=idx[np.argsort(-row[idx])]; pick=list(order[:topk])
                for c in list(pos.keys()): cash+=pos.pop(c)*px[c]-max(pos.get(c,0)*0.01,1.5)
                peak.clear(); entry.clear(); stopped.clear()
                for c in pick:
                    sh=int((cash/topk)//px[c])
                    if sh>0: cash-=sh*px[c]+max(sh*0.01,1.5); pos[c]=sh; entry[c]=px[c]; peak[c]=px[c]
            mv=sum(pos.get(c,0)*px[c] for c in pos)
            eq.append(cash+mv)
        else:
            slip=0.0005 if mode=="C" else 0.0
            cps,cmn=(0.005,1.0) if mode=="C" else (0.01,1.5)
            frac=(mode=="C")
            comm=lambda sh: max(abs(sh)*cps,cmn) if abs(sh)>0 else 0.0
            # --- 开盘: 执行昨日指令 ---
            for c in pend_stop:
                if c in pos:
                    sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh); peak.pop(c,None); entry.pop(c,None)
            pend_stop=[]
            for typ,arg in pend:
                if typ=="unsafe":
                    cash+=safe_sh*safe[i]*(1-slip)-comm(safe_sh); safe_sh=0.0; in_safe=False
                elif typ=="rebal":
                    for c in list(pos.keys()):
                        sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                    peak.clear(); entry.clear()
                    pk=arg
                    if pk:
                        for c in pk:
                            bud=cash/len(pk); pr=op[c]*(1+slip)
                            sh=(bud/pr) if frac else int(bud//pr)
                            if sh>0 and cash>=sh*pr:
                                cash-=sh*pr+comm(sh); pos[c]=sh; entry[c]=pr; peak[c]=pr
                elif typ=="safe":
                    for c in list(pos.keys()):
                        sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                    peak.clear(); entry.clear()
                    sh=(cash/safe[i]) if frac else int(cash//safe[i])
                    if sh>0: cash-=sh*safe[i]*(1+slip)+comm(sh); safe_sh=sh; in_safe=True
                elif typ=="flat":
                    for c in list(pos.keys()):
                        sh=pos.pop(c); cash+=sh*op[c]*(1-slip)-comm(sh)
                    peak.clear(); entry.clear()
            pend=[]
            # --- 收盘: 估值 + 生成指令 ---
            for c in list(pos.keys()):
                p=co[c]; peak[c]=max(peak.get(c,entry[c]),p)
                if stop>0 and p<=peak[c]*(1-stop):
                    pend_stop.append(c); stopped[c]=peak[c]
            bear = (regime is not None) and (not regime[i])
            if in_safe and not bear: pend.append(("unsafe",None))
            if i>=start and (i-start)%rebal==0 and not bear:
                row=A[i]; ok=np.isfinite(row); idx=np.where(ok)[0]
                if len(idx)>0:
                    if rng is not None: pick=list(rng.choice(idx,size=min(topk,len(idx)),replace=False))
                    else:
                        order=idx[np.argsort(-row[idx])]; pick=list(order[:topk])
                    pend.append(("rebal",pick))
            if bear and (len(pos)>0) and not in_safe:
                pend.append(("safe" if safe is not None else "flat", None))
            mv=sum(pos.get(c,0)*co[c] for c in pos)
            eq.append(cash+mv if not in_safe else cash+safe_sh*safe[i])
    return np.array(eq)

# ================= 基准 =================
def ew_all_bt(rebal=21,start=252):
    """宇宙内等权全持(所有有效票), 月度再平衡, strict 时序"""
    allzero=pd.DataFrame(0.0,index=dates_pd,columns=CODES).where(np.isfinite(C))
    return backtest(allzero,mode="C",topk=999,rebal=rebal,start=start)

def buy_hold_eq():
    """等权买入持有: 第252日等权买入所有有效票, 之后不再调整"""
    s=np.nan_to_num(C[252], nan=0.0)
    ok=s>0
    w=np.where(ok, 1.0/ok.sum(), 0.0)
    shares=CAP0*w/np.where(ok,s,1.0)
    Vv=np.nan_to_num(C, nan=0.0)
    val=Vv@shares
    eq=np.full(N, CAP0); eq[252:]=val[252:]
    return eq

print("="*118)
print(f"v12 BUG 修复与验证 · 宇宙 {S} 只 · {dates_pd[0].date()} ~ {dates_pd[-1].date()} ({N} 交易日) · 起点 $3000")
print("="*118)

bh=buy_hold_eq(); ew=ew_all_bt()
mb=metrics(bh); me=metrics(ew)
print(f"[基准1] VOO 买入持有      : ${VOO[-1]/VOO[252]*CAP0:.0f} (+{(VOO[-1]/VOO[252]-1)*100:.1f}%)")
print(f"[基准2] 宇宙等权买入持有  : ${mb['final']:.0f} (+{mb['total']:.1f}%)")
print(f"[基准3] 宇宙等权月度再平衡: ${me['final']:.0f} (+{me['total']:.1f}%)  <== 正确基准")
print(f">> 此前 v8~v11 全部以 VOO 为基准, 而宇宙等权是 VOO 的 "
      f"{(1+mb['total']/100)/(VOO[-1]/VOO[252]):.1f} 倍 -> 历史超额被严重夸大\n")

# ---------- BUG-2: inf 清洗验证 ----------
print("="*118)
print("[BUG-2 验证] inf 污染: dropna() 不剔除 inf, inf 会被排序选为 Top1")
print("="*118)
for nm in ["AD线斜率","OBV斜率","ChaikinADOsc"]:
    a=SIG[nm].values
    nf=np.isinf(a).sum()
    eq_dirty=backtest(SIG[nm],mode="A",clean_inf=False)
    eq_clean=backtest(SIG[nm],mode="A",clean_inf=True)
    md,mc=metrics(eq_dirty),metrics(eq_clean)
    print(f"  {nm:<14} inf格数={nf:<5} 未清洗 +{md['total']:>8.1f}%  清洗后 +{mc['total']:>8.1f}%  差异 {mc['total']-md['total']:+.1f}pp")

# ---------- BUG-3/4/5 时序与成本隔离 ----------
print("\n"+"="*118)
print("[BUG-3/4/5 验证] 三档引擎对照 (A=v11原样 / B=仅T+1开盘成交 / C=全修复)")
print("="*118)
TEST=[("经典12-1动量",2,0.0),("金叉+MA50距离",2,0.0),("AD线斜率",2,0.0),("Vortex",2,0.0),
      ("TSI",2,0.0),("CCI20",2,0.0),("MACD柱",2,0.0),("动量-1月反转(z)",2,0.0),
      ("金叉+MA50距离",3,0.0),("经典12-1动量",2,0.15)]
print(f"{'策略':<18}{'K':>2}{'止损':>6} | {'A: 总收益%':>11}{'夏普':>7}{'回撤%':>8} | {'B: 总收益%':>11}{'夏普':>7} | {'C: 总收益%':>11}{'夏普':>7}{'回撤%':>8} | C/A倍差")
cmp_rows=[]
for nm,tk,st in TEST:
    ea=backtest(SIG[nm],mode="A",topk=tk,stop=st)
    eb=backtest(SIG[nm],mode="B",topk=tk,stop=st)
    ec=backtest(SIG[nm],mode="C",topk=tk,stop=st)
    ma,mb_,mc=metrics(ea),metrics(eb),metrics(ec)
    ratio=(1+mc['total']/100)/(1+ma['total']/100)
    cmp_rows.append((nm,tk,st,ma,mb_,mc,ratio))
    print(f"{nm:<18}{tk:>2}{st:>6.2f} | {ma['total']:>11.1f}{ma['sharpe']:>7.2f}{ma['mdd']:>8.1f} | "
          f"{mb_['total']:>11.1f}{mb_['sharpe']:>7.2f} | {mc['total']:>11.1f}{mc['sharpe']:>7.2f}{mc['mdd']:>8.1f} | x{ratio:.2f}")
avg=np.mean([r[6] for r in cmp_rows])
print(f"\n>> 平均 C/A = x{avg:.2f}: 修复时序+成本+碎股后, 策略收益平均变为原来的 "
      f"{(avg-1)*100:+.0f}%。若某策略在 C 档大幅缩水, 说明原收益主要来自前视/零成本假设。")

# ---------- 蒙特卡洛: 真 alpha 还是运气 ----------
print("\n"+"="*118)
print(f"[蒙特卡洛] 随机选股 {MC_N} 次 (同宇宙/同时序/同调仓) —— 校准'运气'分布")
print("="*118)
mc_tot=[];mc_sh=[]
t0=time.time()
for s in range(MC_N):
    e=backtest(SIG["经典12-1动量"],mode="C",topk=2,start=252,seed=s)
    m=metrics(e); mc_tot.append(m['total']); mc_sh.append(m['sharpe'])
mc_tot=np.array(mc_tot); mc_sh=np.array(mc_sh)
print(f"随机Top2 总收益分布: P5={np.percentile(mc_tot,5):.0f}%  P25={np.percentile(mc_tot,25):.0f}%  "
      f"中位数={np.median(mc_tot):.0f}%  P75={np.percentile(mc_tot,75):.0f}%  P95={np.percentile(mc_tot,95):.0f}%")
print(f"随机Top2 夏普分布  : P5={np.percentile(mc_sh,5):.2f}  中位数={np.median(mc_sh):.2f}  P95={np.percentile(mc_sh,95):.2f}")
print(f"宇宙等权基准 +{me['total']:.0f}% 在随机分布中的分位: {(mc_tot<me['total']).mean()*100:.0f}%")
print(f"耗时 {time.time()-t0:.0f}s")

# ---------- strict 完整排行 ----------
print("\n"+"="*118)
print("[最终排行] strict 引擎 (C档) · 按总收益降序 · 含相对宇宙等权超额 & 蒙特卡洛分位")
print("="*118)
rows=[]
for nm in SIG:
    e=backtest(SIG[nm],mode="C",topk=2)
    m=metrics(e)
    pctile=(mc_tot<m['total']).mean()*100
    excess=(1+m['total']/100)/(1+me['total']/100)
    rows.append((nm,m,pctile,excess))
# 加入风控版
risky=[]
for nm in ["经典12-1动量","金叉+MA50距离","Vortex","AD线斜率","TSI","Ichimoku云"]:
    e=backtest(SIG[nm],mode="C",topk=2,stop=0.15,regime=REGIME,safe=VOO)
    m=metrics(e); risky.append((nm+" +15%止损+200DMA",m,(mc_tot<m['total']).mean()*100,
                                (1+m['total']/100)/(1+me['total']/100)))
rows+=risky
rows.sort(key=lambda r:r[1]['total'],reverse=True)
print(f"{'#':>3} | {'策略':<26}{'总收益%':>9}{'终值$':>10}{'夏普':>7}{'回撤%':>8}{'vs宇宙':>8}{'随机分位':>9}")
print("-"*118)
for i,(nm,m,p,ex) in enumerate(rows,1):
    print(f"{i:>3} | {nm:<26}{m['total']:>9.0f}{m['final']:>10.0f}{m['sharpe']:>7.2f}{m['mdd']:>8.1f}{ex:>8.2f}{p:>8.0f}%")
print("-"*118)
print(f"{'':>3} | {'[基准] 宇宙等权月度再平衡':<26}{me['total']:>9.0f}{me['final']:>10.0f}{me['sharpe']:>7.2f}{me['mdd']:>8.1f}{1.0:>8.2f}{'--':>9}")
print(f"{'':>3} | {'[基准] 宇宙等权买入持有':<26}{mb['total']:>9.0f}{mb['final']:>10.0f}{mb['sharpe']:>7.2f}{mb['mdd']:>8.1f}{(1+mb['total']/100)/(1+me['total']/100):>8.2f}{'--':>9}")
print(f"{'':>3} | {'[基准] VOO 买入持有':<26}{(VOO[-1]/VOO[252]-1)*100:>9.0f}{VOO[-1]/VOO[252]*CAP0:>10.0f}{0:>7.2f}{0:>8.1f}{(VOO[-1]/VOO[252])/(1+me['total']/100):>8.2f}{'--':>9}")

# ---------- 前后半段稳定性 ----------
print("\n"+"="*118)
print("[稳定性] 前半段(2019-2022.9) vs 后半段(2022.10-2026.9) 排名是否一致")
print("="*118)
mid=np.where(dates_pd>=pd.Timestamp("2022-10-01"))[0][0]
def seg_bt(nm,a=0,b=None,mode="C",**kw):
    e=backtest(SIG[nm],mode=mode,**kw); 
    return e[a:b] if b else e[a:]
h1=[];h2=[]
for nm in SIG:
    e=backtest(SIG[nm],mode="C",topk=2)
    r1=e[252:mid][-1]/e[252:mid][0]-1; r2=e[mid:][-1]/e[mid:][0]-1
    h1.append((nm,r1*100)); h2.append((nm,r2*100))
d1=pd.DataFrame(h1,columns=["name","r1"]).set_index("name")
d2=pd.DataFrame(h2,columns=["name","r2"]).set_index("name")
d=d1.join(d2); d["rank1"]=d["r1"].rank(ascending=False); d["rank2"]=d["r2"].rank(ascending=False)
rho=d["rank1"].corr(d["rank2"],method="spearman")
d=d.sort_values("r1",ascending=False)
print(f"{'策略':<20}{'前半收益%':>10}{'后半收益%':>10}{'前段排名':>9}{'后段排名':>9}{'排名变化':>9}")
for nm,row in d.iterrows():
    print(f"{nm:<20}{row['r1']:>10.0f}{row['r2']:>10.0f}{row['rank1']:>9.0f}{row['rank2']:>9.0f}{row['rank1']-row['rank2']:>+9.0f}")
print(f"\n>> 前后段排名 Spearman rho = {rho:.2f} (越接近1越稳定; <0.3 说明排行基本是样本内噪声)")

json.dump(dict(
    rows=[(nm,dict(m),float(p),float(ex)) for nm,m,p,ex in rows],
    mc_pct=[float(np.percentile(mc_tot,q)) for q in (5,25,50,75,95)],
    ew_all=dict(me), bh=dict(mb), rho=float(rho),
    stability={nm:[float(r['r1']),float(r['r2'])] for nm,r in d.iterrows()},
    cmp=[(nm,tk,st,dict(ma),dict(mb_),dict(mc),float(rt)) for nm,tk,st,ma,mb_,mc,rt in cmp_rows],
), open(os.path.join(BASE,"_v12_results.json"),"w"), ensure_ascii=False, indent=2, default=str)
print("\nSAVED _v12_results.json")
