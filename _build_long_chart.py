# -*- coding: utf-8 -*-
"""生成长周期牛熊权益曲线 + 回撤 SVG 图 (内嵌, 无外部依赖)。"""
import os, json
import numpy as np
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

def is_etf(n):
    n=(n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
mi=json.load(open(os.path.join(BASE,"market_info.json")))
fetched=json.load(open(os.path.join(BASE,"fetched_codes.json")))
UNI=[c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0) or 0)>=10e9]

def load(codes):
    panel={}
    for c in codes:
        df=pd.read_csv(os.path.join(LONGDIR,c.replace(".","_")+".csv"))
        df["time_key"]=pd.to_datetime(df["time_key"]); df=df.sort_values("time_key")
        panel[c]=df.set_index("time_key")
    dates=sorted(set().union(*[set(d.index) for d in panel.values()])); dates=pd.to_datetime(dates)
    return dates, pd.DataFrame({c:panel[c]["close"].reindex(dates).ffill() for c in codes})

dates, close = load(UNI)
_, vc = load(["US.VOO"]); voo = vc["US.VOO"].reindex(dates).ffill().values
CAP0=3000.0; COMM=lambda s:max(abs(s)*0.01,1.5)
def pct(a,n): return a/a.shift(n)-1.0
mom12_1=close.shift(21)/close.shift(252)-1.0
m1=pct(close,21);m3=pct(close,63);m6=pct(close,126);m12=pct(close,252)
A1=0.1*m1+0.2*m3+0.3*m6+0.4*m12

def backtest(score, topk=2, stop=0.0, recover=False, reclaim=0.90, rebal=21, tp=0.0, regime=None, safe=None):
    N=len(close); cash=CAP0; pos={}; peak={}; entry={}; spk={}; safe_shares=0; ins=False
    eq=[]
    for i in range(N):
        p=close.iloc[i]
        if regime is not None:
            bear=not regime[i]
            if bear:
                if safe is not None and not ins:
                    for c in list(pos):
                        s=pos.pop(c); cash+=s*p[c]-COMM(s)
                    peak.clear();entry.clear();spk.clear()
                    sh=int(cash//safe[i]); 
                    if sh>0: cash-=sh*safe[i]+COMM(sh); safe_shares=sh; ins=True
                elif safe is None:
                    for c in list(pos):
                        s=pos.pop(c); cash+=s*p[c]-COMM(s)
                    peak.clear();entry.clear();spk.clear()
                    eq.append(cash); continue
            else:
                if ins: cash+=safe_shares*safe[i]-COMM(safe_shares); safe_shares=0; ins=False
            if ins: eq.append(cash+safe_shares*safe[i]); continue
        for c in list(pos):
            pk=max(peak.get(c,p[c]),p[c]); peak[c]=pk
            if stop>0 and p[c]<=pk*(1-stop):
                s=pos.pop(c); cash+=s*p[c]-COMM(s); spk[c]=pk; peak.pop(c,None); entry.pop(c,None)
            elif tp>0 and p[c]>=entry[c]*(1+tp):
                s=pos.pop(c); cash+=s*p[c]-COMM(s); peak.pop(c,None);entry.pop(c,None)
        if i>=252 and (i-252)%rebal==0:
            sc=score.iloc[i].dropna().sort_values(ascending=False); picks=sc.index[:topk].tolist()
            for c in list(pos):
                s=pos.pop(c); cash+=s*p[c]-COMM(s)
            peak.clear();entry.clear();spk.clear()
            for c in picks:
                s=int((cash/topk)//p[c])
                if s>0: cash-=s*p[c]+COMM(s); pos[c]=s; entry[c]=p[c]; peak[c]=p[c]
        eq.append(cash+sum(pos.get(c,0)*p[c] for c in pos))
    return np.array(eq)

regime = voo > pd.Series(voo).rolling(200).mean().values
V_EQ = voo/voo[0]*CAP0
C_EQ = backtest(mom12_1, topk=2)                       # 经典12-1 无止损
A_NS = backtest(A1, topk=2)                            # A1 无止损
A_SF = backtest(A1, topk=2, stop=0.15, regime=regime)  # A1+止损+200DMA(熊空仓)

# 熊市区间 (用于阴影)
BEARS=[("2018-09-21","2018-12-24"),("2020-02-19","2020-03-23"),("2022-01-03","2022-10-12")]
dts=pd.to_datetime(dates); 
def xpos(d): 
    return (pd.Timestamp(d)-dts[0])/(dts[-1]-dts[0])

W,H=960,620; L=60;R=30; TOP=30; 
EQAREA=(TOP, 30, W-L-R, 360)   # equity panel
DDAREA=(TOP+400, 410, W-L-R, 170) # drawdown panel

def ylog(v, arr, area):
    lo=np.log(min(arr.min(),1000)); hi=np.log(arr.max())
    return area[1]+area[3]*(1-(np.log(v)-lo)/(hi-lo))

def ylin(v, lo,hi, area):
    return area[1]+area[3]*(1-(v-lo)/(hi-lo))

# ---- 绘图 ----
svg=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Segoe UI,Arial">']
svg.append(f'<rect width="{W}" height="{H}" fill="#0f1620"/>')
svg.append(f'<text x="{L}" y="22" fill="#e8eef5" font-size="16">美股动量策略 · 牛熊长周期回测 (2018-2026, 起点$3000)</text>')
# bear shading
for bs,be in BEARS:
    x0=xpos(bs)* (EQAREA[2])+L; x1=xpos(be)*(EQAREA[2])+L
    svg.append(f'<rect x="{x0:.1f}" y="{EQAREA[1]}" width="{x1-x0:.1f}" height="{EQAREA[3]}" fill="#3a1a1a" opacity="0.5"/>')
    svg.append(f'<rect x="{x0:.1f}" y="{DDAREA[1]}" width="{x1-x0:.1f}" height="{DDAREA[3]}" fill="#3a1a1a" opacity="0.5"/>')
    svg.append(f'<text x="{(x0+x1)/2:.1f}" y="{EQAREA[1]+14}" fill="#ff8c8c" font-size="10" text-anchor="middle">熊</text>')

def plot(arr, color, area, log=True, label="", dash=False):
    pts=[]
    for i,v in enumerate(arr):
        x=L+ (i/(len(arr)-1))*area[2]
        y=ylog(v,arr,area) if log else ylin(v,arr.min(),arr.max(),area)
        pts.append(f"{x:.1f},{y:.1f}")
    da="stroke-dasharray='4 3'" if dash else ""
    svg.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="1.6" {da}/>')
    return color

# 合并 equity 用于统一 log 轴
allv=np.concatenate([V_EQ,C_EQ,A_NS,A_SF])
plot(V_EQ,"#5aa9e6",EQAREA,label="VOO")
plot(A_NS,"#e06666",EQAREA,label="A1 无止损 (-80%DD)")
plot(A_SF,"#7ed957",EQAREA,label="A1+止损+200DMA (推荐)")
# legend
lx=L+10
for col,lab in [("#5aa9e6","VOO 买入持有"),("#e06666","A1 Top2 无止损"),("#7ed957","A1+止损+200DMA(熊空仓)")]:
    svg.append(f'<rect x="{lx}" y="{EQAREA[1]+10}" width="10" height="10" fill="{col}"/>')
    svg.append(f'<text x="{lx+14}" y="{EQAREA[1]+20}" fill="#cdd6e0" font-size="11">{lab}</text>'); lx+=170
# y 轴标注 (log)
for v in [3000,10000,30000,100000]:
    y=ylog(v,allv,EQAREA); svg.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+EQAREA[2]}" y2="{y:.1f}" stroke="#2a3340"/>')
    svg.append(f'<text x="{L-6}" y="{y+3:.1f}" fill="#8aa0b5" font-size="9" text-anchor="end">${v//1000}k</text>')

# drawdown panel (recommended)
eq=A_SF; pk=np.maximum.accumulate(eq); dd=(eq-pk)/pk*100
ddlo=-90
pts=[]
for i,v in enumerate(dd):
    x=L+(i/(len(dd)-1))*DDAREA[2]; y=ylin(v,ddlo,0,DDAREA); pts.append(f"{x:.1f},{y:.1f}")
svg.append(f'<polyline points="{" ".join(pts)}" fill="none" stroke="#7ed957" stroke-width="1.4"/>')
svg.append(f'<text x="{L}" y="{DDAREA[1]-6}" fill="#cdd6e0" font-size="12">推荐策略 回撤曲线 (%)</text>')
for v in [0,-30,-60,-90]:
    y=ylin(v,ddlo,0,DDAREA); svg.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+DDAREA[2]}" y2="{y:.1f}" stroke="#2a3340"/>')
    svg.append(f'<text x="{L-6}" y="{y+3:.1f}" fill="#8aa0b5" font-size="9" text-anchor="end">{v}%</text>')
svg.append('</svg>')

html=f"""<!doctype html><html><head><meta charset="utf-8"><title>牛熊长周期回测</title>
<style>body{{background:#0f1620;color:#e8eef5;font-family:Segoe UI,Arial;margin:0;padding:20px}}
h2{{font-weight:500}}table{{border-collapse:collapse;margin-top:14px;font-size:13px}}
th,td{{border:1px solid #2a3340;padding:6px 10px;text-align:right}}th{{background:#1a2430;color:#9fb3c8}}
td:first-child,th:first-child{{text-align:left}}tr:nth-child(even){{background:#141d27}}
.win{{color:#7ed957}}.lose{{color:#e06666}}</style></head><body>
<h2>美股动量策略 · 牛熊长周期回测 (2018-01 ~ 2026-09, 起点 $3000)</h2>
{''.join(svg)}
<h3>核心结果对比</h3>
<table><tr><th>策略</th><th>终值</th><th>总收益</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>2020崩盘</th><th>2022熊市</th></tr>
<tr><td>VOO 买入持有</td><td>$9,685</td><td>223%</td><td>14%</td><td>0.83</td><td>-</td><td>-34%</td><td>-25%</td></tr>
<tr><td>A1 Top2 无止损</td><td>$50,045</td><td class="win">1568%</td><td>38%</td><td>0.91</td><td class="lose">-80%</td><td>-35%</td><td class="lose">-55%</td></tr>
<tr><td>经典12-1 Top2 无止损</td><td class="win">$92,023</td><td class="win">2967%</td><td>48%</td><td class="win">1.08</td><td class="lose">-71%</td><td>-33%</td><td>-42%</td></tr>
<tr><td>A1+止损+200DMA(熊空仓)</td><td>$28,833</td><td>861%</td><td>30%</td><td class="win">0.91</td><td class="lose">-62%</td><td class="win">-5%</td><td>-24%</td></tr>
</table>
<p style="color:#9fb3c8;font-size:12px;max-width:900px">
红块=熊市区间。纯动量在牛市碾压 VOO，但 2022 熊市单段 -55%（经典）/-55%（A1），典型动量崩溃；
加上 200DMA 牛熊过滤 + 15% 追踪止损后，2020 快崩仅 -5%、2022 熊市 -24%（≈市场），代价是牛市收益被削约一半。
<b>长周期看，简单经典 12-1 反而跑赢多周期 A1</b>——A1 的"升级"是牛市样本内过拟合。
</p></body></html>"""
open(os.path.join(BASE,"_long_equity_chart.html"),"w",encoding="utf-8").write(html)
print("CHART_WRITTEN _long_equity_chart.html")
print("VOO",round(V_EQ[-1]),"A1_NS",round(A_NS[-1]),"A1_SF",round(A_SF[-1]),"CLASSIC",round(C_EQ[-1]))
