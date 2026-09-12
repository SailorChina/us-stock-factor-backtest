# -*- coding: utf-8 -*-
"""诊断: 短历史标的 / 极端跳变 / ffill 假平稳 / 候选池健康度"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

P = {}
for c in UNI:
    d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    P[c] = d.sort_values("time_key").reset_index(drop=True).set_index("time_key")
ad = sorted(set().union(*[set(x.index) for x in P.values()])); idx = pd.to_datetime(ad)
C = pd.DataFrame({c: P[c]["close"].reindex(idx) for c in UNI})
H = pd.DataFrame({c: P[c]["high"].reindex(idx) for c in UNI})
L = pd.DataFrame({c: P[c]["low"].reindex(idx) for c in UNI})
N, S = C.shape
print(f"面板 {N} 行 x {S} 列   首 {str(idx[0].date())}  末 {str(idx[-1].date())}\n")

print("=" * 118); print("[1] 各标的真实历史覆盖（未 ffill）"); print("=" * 118)
rows = []
for c in UNI:
    v = C[c].dropna()
    rows.append((c.replace("US.", ""), str(v.index[0].date()), len(v),
                 str(v.index[-1].date()), int(C[c].isna().sum())))
rows.sort(key=lambda x: x[2])
print(f"{'标的':<8}{'首个有效日':>14}{'有效根数':>10}{'最后有效日':>14}{'缺口数':>9}{'缺口%':>8}")
print("-" * 118)
for nm, s, n, e, na in rows:
    flag = "  ⚠ 短历史" if n < N * 0.9 else ""
    print(f"{nm:<8}{s:>14}{n:>10}{e:>14}{na:>9}{na/N*100:>7.1f}%{flag}")
short = [r[0] for r in rows if r[2] < N * 0.9]
print(f"\n短历史标的（覆盖 <90%）: {len(short)} 只 -> {short}")

print("\n" + "=" * 118); print("[2] ffill 补齐后的「假平稳段」（会让动量/波动率失真）"); print("=" * 118)
Cf = C.ffill()
flat = {}
for c in UNI:
    v = Cf[c].values
    f = int(np.argmax(np.isfinite(v))) if np.isfinite(v).any() else N
    if f >= N - 1: continue
    k = f
    while k + 1 < N and abs(v[k+1] - v[k]) < 1e-9: k += 1
    if k - f > 0: flat[c.replace("US.", "")] = (str(idx[f].date()), k - f)
if flat:
    for nm, (d0, run) in sorted(flat.items(), key=lambda x: -x[1][1]):
        print(f"  {nm:<8} 自 {d0} 起连续 {run} 根价格不变")
else:
    print("  ✅ 无假平稳段")

print("\n" + "=" * 118); print("[3] 单日 >50% 跳变明细"); print("=" * 118)
prev = Cf.shift(); prev = prev.where(prev.abs() > 1e-9)
ret = Cf / prev - 1.0
m = np.nan_to_num(ret.values > 0.5, nan=False) | np.nan_to_num(ret.values < -0.5, nan=False)
ii, jj = np.where(m)
if len(ii) == 0:
    print("  无")
for i, j in zip(ii, jj):
    if i < 2: continue
    c = UNI[j]
    print(f"  {str(idx[i].date())}  {c.replace('US.',''):<7} "
          f"{Cf.values[i-1,j]:.2f} -> {Cf.values[i,j]:.2f} ({ret.values[i,j]*100:+.1f}%)  "
          f"当日 O={P[c]['open'].reindex(idx).ffill().values[i]:.2f} "
          f"H={P[c]['high'].reindex(idx).ffill().values[i]:.2f} "
          f"L={P[c]['low'].reindex(idx).ffill().values[i]:.2f}")

print("\n" + "=" * 118); print("[4] 当前候选池健康度: Vortex 排名前 10"); print("=" * 118)
def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())
V = vortex(H.ffill(), L.ffill(), Cf)
row = V.values[N-1]
ok = np.isfinite(row); o = np.where(ok)[0]
order = o[np.argsort(-row[o])][:10]
print(f"{'排名':<5}{'标的':<8}{'Vortex':>10}{'有效根数':>10}{'252日动量':>12}{'现价':>12}")
print("-" * 118)
for r, j in enumerate(order, 1):
    c = UNI[j]
    nv = int(C[c].notna().sum())
    m252 = Cf.values[N-1, j] / Cf.values[N-253, j] - 1 if np.isfinite(Cf.values[N-253, j]) else np.nan
    print(f"{r:<5}{c.replace('US.',''):<8}{row[j]:>10.3f}{nv:>10}{m252*100:>11.0f}%"
          f"{Cf.values[N-1,j]:>12.2f}")

print("\n" + "=" * 118); print("[5] 加「历史覆盖闸门」后信号是否变化"); print("=" * 118)
good = [j for j in range(S) if C[UNI[j]].notna().sum() >= N * 0.9]
print(f"  合格 {len(good)}/{S}; 被剔除: {[UNI[j].replace('US.','') for j in range(S) if j not in good]}")
r1 = V.values[N-1]
o1 = np.where(np.isfinite(r1))[0]
p1 = [UNI[j].replace("US.", "") for j in o1[np.argsort(-r1[o1])][:2]]
r2 = r1.copy(); bad = [j for j in range(S) if j not in good]
r2[bad] = np.nan
o2 = np.where(np.isfinite(r2))[0]
p2 = [UNI[j].replace("US.", "") for j in o2[np.argsort(-r2[o2])][:2]]
print(f"  Vortex Top2:  原 {p1}  ->  闸门后 {p2}   {'【变了】' if p1 != p2 else '（未变）'}")
