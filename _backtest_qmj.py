import json, numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

codes = json.load(open("fetched_codes.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}
minfo = json.load(open("market_info.json"))
def keep(code):
    n = (univ.get(code) or "")
    if any(k in n.upper() for k in ("ETF","ETN")): return False
    if (minfo.get(code) or {}).get("total_market_val",0) < 1e10: return False
    return True
fcodes = [c for c in codes if keep(c)]
kept, clo = [], []
for c in fcodes:
    df = pd.read_csv(f"data_kline/{c.replace('.','_')}.csv", parse_dates=['time_key']).set_index('time_key').sort_index()
    if df.index.min() > pd.Timestamp('2023-09-01'): continue
    kept.append(c); clo.append(df['close'].rename(c))
fcodes = kept
close = pd.concat(clo, axis=1)
common = close.dropna(how='any').index; close = close.loc[common]
dates = close.index; N = len(dates)
raw = json.load(open("qmj_raw.json"))

# 构建 QMJ 质量复合（Asness 风格：高盈利 + 低杠杆）
# 关键：每个指标跨股票做 z-score，再按股票平均（不能在同一只股票内互标）
def col_z(field_id):
    vals = np.array([raw[c].get(str(field_id)) for c in fcodes], dtype=float)  # None->nan
    mu = np.nanmean(vals); sd = np.nanstd(vals)
    return (vals - mu) / (sd + 1e-9)
zp = np.mean([col_z(14029), col_z(14002), col_z(14005)], axis=0)   # 盈利能力 z：ROE/毛利率/净利率
zs = np.mean([col_z(14018), col_z(14019)], axis=0)                 # 安全性 z：财务杠杆/有息负债率（高=差）
qual_arr = (zp - zs) / 2.0                                         # 质量分：盈利高+杠杆低
qual = {c: float(qual_arr[i]) for i, c in enumerate(fcodes)}
qscore = pd.Series(qual).sort_values(ascending=False)
print("=== QMJ 质量排名（当前快照，前10）===")
for c in qscore.index[:10]:
    print(f"  {c} {univ.get(c,'')}: Q={qual[c]:.2f} ROE={raw[c].get('14029')} GM={raw[c].get('14002')} Lev={raw[c].get('14018')}")

# 前视演示：用当前质量分数作为恒定因子，过最优止损框架(fixed15+恢复)
COMM_PER_SHARE=0.01; COMM_MIN=1.5
reb_every=21; start=254; reb_days=set(range(start,N,reb_every))
def run_qmj(topk, stop_val=0.15, recovery=True, capital0=3000.0):
    cash=capital0; shares=pd.Series(0,index=fcodes,dtype=int)
    entry={}; peak={}; stop_trig={}
    eq=[]; invested=0
    for i in range(N):
        if i in reb_days:
            for c in fcodes:
                if shares[c]>0:
                    p=close[c].iloc[i]; sh=shares[c]; fee=max(sh*COMM_PER_SHARE,COMM_MIN)
                    cash+=sh*p-fee; shares[c]=0; entry.pop(c,None); peak.pop(c,None); stop_trig.pop(c,None)
            pick=list(qscore.index[:topk]); per=cash/topk
            for c in pick:
                p=close[c].iloc[i]
                if p>0:
                    sh=int(per//p)
                    if sh>0:
                        fee=max(sh*COMM_PER_SHARE,COMM_MIN); cost=sh*p+fee
                        if cost<=cash: shares[c]=sh; cash-=cost; entry[c]=p; peak[c]=p
        else:
            for c in fcodes:
                if shares[c]>0:
                    px=close[c].iloc[i]; pk=peak.get(c,px)
                    if px>pk: pk=px; peak[c]=px
                    if px<=pk*(1-stop_val):
                        fee=max(shares[c]*COMM_PER_SHARE,COMM_MIN); cash+=shares[c]*px-fee
                        stop_trig[c]=px; shares[c]=0; peak.pop(c,None); entry.pop(c,None)
            if recovery:
                budget=cash/topk
                for c in list(stop_trig):
                    if cash<=budget*0.5: break
                    px=close[c].iloc[i]
                    if px>=stop_trig[c]:
                        sh=int(budget//px)
                        if sh>0:
                            fee=max(sh*COMM_PER_SHARE,COMM_MIN); cost=sh*px+fee
                            if cost<=cash: shares[c]=sh; cash-=cost; entry[c]=px; peak[c]=px; del stop_trig[c]
        if shares.sum()>0: invested+=1
        eq.append(cash+sum(shares[c]*close[c].iloc[i] for c in fcodes))
    return pd.Series(eq,index=dates), invested

def metrics(eq):
    eqv=eq.values[start:]; pr=np.diff(eqv)/eqv[:-1]
    total=eqv[-1]/eqv[0]-1; cagr=(eqv[-1]/eqv[0])**(252/len(eqv))-1
    sharpe=pr.mean()/pr.std()*np.sqrt(252) if pr.std()>0 else 0
    pk=np.maximum.accumulate(eqv); mdd=(eqv/pk-1).min()
    return total,cagr,sharpe,mdd

for k in (2,3):
    eq,inv=run_qmj(k)
    t,c,s,m=metrics(eq)
    print(f"\n[前视演示] QMJ top{k} +fixed15_rec: final ${eq.values[-1]:.0f}  total {t*100:.1f}%  cagr {c*100:.1f}%  sharpe {s:.2f}  mdd {m*100:.1f}%  (inv={inv/N*100:.0f}%)")

# 当前实盘推荐（2-3只）
last=N-1
print("\n=== 当前 QMJ 实盘推荐（2026-09-10, 3000美金）===")
for k in (2,3):
    print(f"top{k}:", end=" ")
    for c in qscore.index[:k]:
        p=float(close[c].iloc[last]); sh=int((3000/k)//p)
        print(f"{c}(${p:.2f}->{sh}sh ${sh*p:.0f})", end="  ")
    print()

qscore.to_json("qmj_scores.json")
print("SAVED qmj_scores.json")
