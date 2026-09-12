# -*- coding: utf-8 -*-
"""
验证 B1 修复的影响: 面板 ffill 策略(无限 vs limit=10) 对历史信号与回测结果的影响
若差异显著 -> 之前所有回测结论需按新面板重算

【已归档 · 不要拿它的数字当结论】
本脚本是 v19 时期的一次性对比, 面板没有 v25.1 的 REAL 掩码, 且曾复制了 F2/F3 两处
缺陷(已于 v25.1 就地修好)。任何【回测收益】结论请以 _liquidity_gate_v25.py(已修复)
与 美股回测深度审计_v25.1.md 为准。
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
START, REBAL, COMM, CAP0 = 252, 21, 2.0, 3000.0

mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

def panel(limit):
    p = {}
    for c in UNI:
        d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").drop_duplicates("time_key", keep="last").set_index("time_key")
    ad = sorted(set().union(*[set(x.index) for x in p.values()])); dt = pd.to_datetime(ad)
    out = {}
    for k in ["open","close","high","low"]:
        m = pd.DataFrame({c: p[c][k].reindex(dt) for c in UNI})
        out[k] = m.ffill() if limit is None else m.ffill(limit=limit)
    return dt, out

def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())

def picks_of(A, i, k=2):
    row = A[i] if isinstance(A, np.ndarray) else A.values[i]
    ok = np.isfinite(row); idx = np.where(ok)[0]
    if len(idx) == 0: return []
    return list(idx[np.argsort(-row[idx])][:k])

def backtest(C, O, A, topk=2, comm=COMM, cap=CAP0, frac=True):
    N = C.shape[0]
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    cash = cap; pos = {}; eq = np.full(N, cap)
    for i in range(START, N):
        # 收盘估值
        val = cash + sum(pos.get(j, 0) * C[i, j] for j in pos)
        eq[i] = val
        # 调仓: 昨日收盘生成指令, 今日开盘执行
        if i in set(RB):
            k = topk
            # 全部卖出: 按今日开盘价成交, 每笔扣佣金
            # v25.1 修复(F2): 卖不掉的持仓必须保留, 不得凭空清空(见 美股回测深度审计_v25.1.md)
            keep = {}
            for j, sh in pos.items():
                pr = O[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh * pr - comm
                else:
                    keep[j] = sh
            pos = keep
            row = A[i-1] if isinstance(A, np.ndarray) else A.values[i-1]
            ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) >= k:
                pk = list(idx[np.argsort(-row[idx])][:k])
                bud = (cash - k * comm) / k      # 预留买入佣金
                for j in pk:
                    pr = O[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    if j in pos: continue            # 卡住的仓位不重复买
                    sh = bud / pr if frac else int(bud // pr)
                    if sh > 0:
                        pos[j] = sh; cash -= sh * pr + comm   # v25.1 修复(F3): 补上买入佣金
    return eq

print("=" * 116)
print("面板 ffill 策略对比: 无限填充(旧)  vs  limit=10(新)")
print("=" * 116)
res = {}
for lab, lim in [("旧(无限ffill)", None), ("新(limit=10)", 10)]:
    dt, PX = panel(lim)
    C, H, L = PX["close"], PX["high"], PX["low"]
    N = C.shape[0]
    V = vortex(H, L, C)
    mom = C.shift(21) / C.shift(252) - 1.0
    rev = C / C.shift(21) - 1.0
    zs = lambda x: x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
    M = (zs(mom) - zs(rev)) / 2.0
    res[lab] = {"Vortex": V.values, "动量-1月反转": M.values, "N": N}
    print(f"  {lab}: 面板 {C.shape}, 收盘 NaN {C.isna().mean().mean()*100:.2f}%")

print("\n" + "=" * 116)
print("影响 1: 历史上每个调仓日选出的 Top2 是否相同")
print("=" * 116)
N = res["旧(无限ffill)"]["N"]
RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
dt0, _ = panel(None); dp = pd.to_datetime(dt0)
for nm in ["Vortex", "动量-1月反转"]:
    A_old = res["旧(无限ffill)"][nm]; A_new = res["新(limit=10)"][nm]
    diff = []
    for i in RB:
        po = picks_of(A_old, i, 2); pn = picks_of(A_new, i, 2)
        if po != pn: diff.append(i)
    print(f"  {nm}: {len(RB)} 个调仓日中【{len(diff)}】个选股不同 "
          f"({len(diff)/len(RB)*100:.1f}%)")
    if diff:
        print(f"     首次不同的日期: {[str(dp[i].date()) for i in diff[:6]]}")

print("\n" + "=" * 116)
print("影响 2: 8.7 年回测终值 (Top2 等权, 碎股, 佣金 $2/笔)")
print("=" * 116)
_, PXo = panel(None); _, PXn = panel(10)
Co, Oo, Ho, Lo = PXo["close"].values, PXo["open"].values, PXo["high"].values, PXo["low"].values
Cn, On, Hn, Ln = PXn["close"].values, PXn["open"].values, PXn["high"].values, PXn["low"].values
for nm in ["Vortex", "动量-1月反转"]:
    Ao = res["旧(无限ffill)"][nm]; An = res["新(limit=10)"][nm]
    eo = backtest(Co, Oo, Ao)
    en = backtest(Cn, On, An)
    c0 = Cn[START]; w = np.where(np.isfinite(c0), 1.0, 0.0); w = w / w.sum()
    port = np.nansum(Cn[START:] * w, axis=1)
    bas = np.full(N, np.nan); bas[START:] = port / port[0] * CAP0
    print(f"  {nm}:")
    print(f"     旧面板 终值 ${eo[-1]:,.0f}  ({(eo[-1]/CAP0-1)*100:+.0f}%)")
    print(f"     新面板 终值 ${en[-1]:,.0f}  ({(en[-1]/CAP0-1)*100:+.0f}%)")
    print(f"     等权基准 ${bas[-1]:,.0f}  ({(bas[-1]/CAP0-1)*100:+.0f}%)")

print("\n" + "=" * 116)
print("影响 3: 单日跳空 >50% 的票, 之后 1 个月是否被策略选中过")
print("=" * 116)
prev = np.where(np.abs(Co[:-1]) > 1e-9, Co[:-1], np.nan)
ret = Co[1:] / prev - 1.0
rr, cc = np.where(np.nan_to_num(ret > 0.5, nan=False))
print(f"  全样本单日 >50% 共 {len(rr)} 次")
if len(rr):
    for i, c in list(zip(rr, cc))[:8]:
        nm = UNI[c].replace("US.", "")
        print(f"     {str(dp[i+1].date())} {nm:<7} {ret[i,c]*100:+.0f}%")
