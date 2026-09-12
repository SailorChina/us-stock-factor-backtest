# -*- coding: utf-8 -*-
"""构建报告资产: 推荐配置的持仓时间线 + 权益曲线 HTML"""
import os, json
import numpy as np, pandas as pd

BASE=r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
mi=json.load(open(BASE+"/market_info.json")); fetched=json.load(open(BASE+"/fetched_codes.json"))
def is_etf(n):
    n=(n or "").upper(); return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
uni=[c for c in fetched if not is_etf(mi.get(c,{}).get("name","")) and (mi.get(c,{}).get("total_market_val",0)or 0)>=10e9]
panel={}
for c in uni:
    df=pd.read_csv(BASE+f"/data_kline/{c.replace('.','_')}.csv"); df["time_key"]=pd.to_datetime(df["time_key"])
    panel[c]=df.set_index("time_key").sort_index()
dates=sorted(set().union(*[set(df.index) for df in panel.values()])); dates=pd.to_datetime(dates)
close=pd.DataFrame({c:panel[c]["close"].reindex(dates).ffill() for c in uni})
N=len(dates)
def pct(a,n): return a/a.shift(n)-1.0
m1=pct(close,21); m3=pct(close,63); m6=pct(close,126); m12=pct(close,252)
mom_multi=0.1*m1+0.2*m3+0.3*m6+0.4*m12

# ---- 推荐配置: A1 top2 月频 ----
picks_timeline=[]
cur=None
for i in range(N):
    if i>=252 and (i-252)%21==0:
        sc=mom_multi.iloc[i].dropna().sort_values(ascending=False); pk=sc.index[:2].tolist()
        picks_timeline.append((str(dates[i].date()),[(c, round(mom_multi.iloc[i][c]*100,1)) for c in pk]))
        cur=pk
# 当前(最后)信号
last=dates[-1]; sci=mom_multi.iloc[-1].dropna().sort_values(ascending=False)
cur_signal=[(c, round(sci[c]*100,1), mi.get(c,{}).get("name","")) for c in sci.index[:5].tolist()]

# ---- 读权益曲线 ----
eqdf=pd.read_csv(BASE+"/_optimal_equity.csv", index_col=0)
# 选取关键列
cols=["A1 多周期动量 top2 月频 无止损","A1 多周期动量 top3 月频 无止损",
      "A1 多周期动量 top2 月频 +15%止损+回收0.90","经典12-1 top2 月频 无止损",
      "VOO 买入持有 (基准)"]
cols=[c for c in cols if c in eqdf.columns]
plot_dates=[d[:7] for d in eqdf.index]  # YYYY-MM
# 降采样到月度末, 减少点数
m=eqdf.iloc[:,0].copy(); m.index=pd.to_datetime(eqdf.index)
month_end=m.groupby(m.index.to_period("M")).last()
plot_dates=[str(p) for p in month_end.index]
plot_data={c:[] for c in cols}
for c in cols:
    s=eqdf[c]; s.index=pd.to_datetime(eqdf.index)
    me=s.groupby(s.index.to_period("M")).last()
    plot_data[c]=me.values.tolist()

html=f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>美股最优策略 · 权益曲线</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;background:#fafafa;margin:0;padding:24px;color:#222}}
.card{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 2px 10px rgba(0,0,0,.06);margin-bottom:20px}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:16px;margin:18px 0 8px}}
.legend span{{display:inline-block;margin-right:14px;font-size:13px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:middle}}
table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{border:1px solid #eee;padding:6px 8px;text-align:left}}
th{{background:#f5f7fa}}tr:nth-child(even){{background:#fafbfc}}
.up{{color:#e23}} .note{{color:#888;font-size:12px}}</style></head>
<body>
<div class="card">
<h1>美股最优策略 · 权益曲线 ($3000 起点, 近3年回测)</h1>
<div class="legend">
<span><i class="dot" style="background:#e23"></i>A1多周期动量 top2 月频 无止损</span>
<span><i class="dot" style="background:#d97706"></i>A1 top3 月频 无止损</span>
<span><i class="dot" style="background:#2563eb"></i>A1 top2 +15%止损回收0.90</span>
<span><i class="dot" style="background:#16a34a"></i>经典12-1 top2 无止损</span>
<span><i class="dot" style="background:#888"></i>VOO 基准</span>
</div>
<canvas id="eq" height="340"></canvas>
<div class="note">注: 前252个交易日(约1年)为动量因子预热期, 资金闲置, 故曲线前段走平。</div>
</div>
<div class="card">
<h2>推荐配置 A1 top2 月频 · 历史月度选股 (节选)</h2>
<table><tr><th>调仓日</th><th>入选标的 (动量分%)</th></tr>
{''.join(f"<tr><td>{d}</td><td>"+", ".join(f'{c} ({v})' for c,v in pk)+"</td></tr>" for d,pk in picks_timeline[::3])}
</table>
</div>
<div class="card">
<h2>当前信号 ({last.date()}) · A1 动量前5</h2>
<table><tr><th>代码</th><th>名称</th><th>动量分%</th></tr>
{''.join(f"<tr><td>{c}</td><td>{n}</td><td class='up'>{v}</td></tr>" for c,n,v in cur_signal)}
</table>
<div class="note">当前信号仅供参考, 实际以平台调仓日计算为准。</div>
</div>
<script>
const labels={json.dumps(plot_dates)};
const series={json.dumps(plot_data)};
const colors={{"A1 多周期动量 top2 月频 无止损":"#e23","A1 多周期动量 top3 月频 无止损":"#d97706",
"A1 多周期动量 top2 月频 +15%止损+回收0.90":"#2563eb","经典12-1 top2 月频 无止损":"#16a34a","VOO 买入持有 (基准)":"#888"}};
const ds=Object.keys(series).map(k=>({{label:k,data:series[k],borderColor:colors[k],backgroundColor:colors[k],borderWidth:2,pointRadius:0,tension:.15}}));
new Chart(document.getElementById('eq'),{{type:'line',data:{{labels,datasets:ds}},
options:{{responsive:true,interaction:{{mode:'index',intersect:false}},
plugins:{{legend:{{display:false}}}},scales:{{y:{{title:{{display:true,text:'账户权益 ($)'}}}},x:{{ticks:{{maxTicksLimit:12}}}}}}}}}});
</script></body></html>"""

out=os.path.join(BASE,"_optimal_equity_chart.html")
open(out,"w",encoding="utf-8").write(html)
json.dump({"picks_timeline":picks_timeline,"current_signal":cur_signal},
          open(BASE+"/_optimal_holdings.json","w"),ensure_ascii=False,indent=2)
print("Saved ->", out)
print("Last rebalance picks:", picks_timeline[-1])
print("Current top5 signal:", cur_signal)
