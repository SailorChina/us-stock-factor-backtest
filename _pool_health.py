# -*- coding: utf-8 -*-
"""
标的池健康度体检 —— 找出"看起来能交易、实际是假价格"的标的
隐患类型:
  A 长期停牌(缺口) -> 面板 ffill 后变成一条水平直线: 波动率 0、21日收益 0
    -> 会被"低波动/反转"类因子排到最前面, 是隐形地雷
  B 极端低流动性(日成交额极小) -> 回测里能成交, 实盘滑点巨大
  C 单日 |涨跌| >100% -> 多半是复权/拆股口径问题, 而非真实行情
"""
import os, json, glob
import pandas as pd
import numpy as np

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
D = os.path.join(BASE, "data_kline_long")
target = json.load(open(os.path.join(BASE, "universe_heat100_target.json"), encoding="utf-8"))
rank = {r["code"]: r["rank"] for r in target["target100"]}
name = {r["code"]: r["name"] for r in target["target100"]}

spy = pd.read_csv(os.path.join(D, "US_SPY.csv"))
ref = set(spy["time_key"])

print("=" * 112)
print("ISRG 拆股复权抽查 (Intuitive Surgical 2025-10 三拆一)")
print("=" * 112)
p = os.path.join(D, "US_ISRG.csv")
if os.path.exists(p):
    s = pd.read_csv(p)
    print(s[(s.time_key >= "2025-10-01") & (s.time_key <= "2025-10-09")].to_string(index=False))
    print("  -> 前复权: 拆股前应显示约 150 而非约 450")

print()
print("=" * 112)
rows = []
for f in sorted(glob.glob(os.path.join(D, "*.csv"))):
    c = os.path.basename(f)[:-4].replace("_", ".")
    if c not in rank:
        continue
    df = pd.read_csv(f)
    n = len(df)
    lo, hi = df["time_key"].iloc[0], df["time_key"].iloc[-1]
    ref_in = {d for d in ref if lo <= d <= hi}
    cover = len(set(df["time_key"]) & ref_in) / max(1, len(ref_in))
    dv = (df["close"] * df["volume"])
    med_dv = dv.median()
    zero_vol = int((df["volume"] <= 0).sum())
    tiny_vol = int((df["volume"] < 1000).sum())
    r = df["close"].pct_change()
    max_abs = float(np.nanmax(np.abs(r.fillna(0))))
    # 连续无成交最长的段
    gaps = sorted(ref_in - set(df["time_key"]))
    longest = 0
    if gaps:
        run = 1
        for a, b in zip(gaps, gaps[1:]):
            run = run + 1 if (pd.to_datetime(b) - pd.to_datetime(a)).days <= 4 else 1
            longest = max(longest, run)
    flags = []
    if cover < 0.95: flags.append(f"覆盖率{cover:.0%}")
    if longest >= 30: flags.append(f"最长停牌{len(gaps)}天")
    if med_dv < 5e6: flags.append(f"日额${med_dv/1e6:.1f}M")
    if zero_vol > 20: flags.append(f"零成交{zero_vol}天")
    if tiny_vol > 20: flags.append(f"极微量{tiny_vol}天")
    if max_abs > 1.0: flags.append(f"单日{max_abs*100:.0f}%")
    rows.append({"code": c, "rank": rank[c], "name": name.get(c, ""), "rows": n,
                 "cover": cover, "longest_gap": len(gaps) if gaps else 0,
                 "longest_run": longest, "med_dv": med_dv, "zero_vol": zero_vol,
                 "tiny_vol": tiny_vol, "max_abs": max_abs, "flags": flags})

rows.sort(key=lambda x: x["rank"])
print(f"{'名次':>4} {'代码':<8} {'行数':>5} {'覆盖率':>7} {'最长连续停牌':>10} "
      f"{'日中位成交额':>12} {'零成交':>6} {'<1千股':>6} {'单日极值':>8}  问题")
print("-" * 112)
clean, dirty = [], []
for x in rows:
    tag = " | ".join(x["flags"]) if x["flags"] else ""
    (dirty if tag else clean).append(x)
    print(f"{x['rank']:>4} {x['code'].replace('US.',''):<8} {x['rows']:>5} "
          f"{x['cover']:>7.0%} {x['longest_run']:>10} {x['med_dv']/1e6:>10,.1f}M "
          f"{x['zero_vol']:>6} {x['tiny_vol']:>6} {x['max_abs']*100:>7.0f}%  {tag}")
print("-" * 112)
print(f"\n干净 {len(clean)} 只 / 有疑点 {len(dirty)} 只")
print("\n有疑点明细:")
for x in dirty:
    print(f"   {x['code'].replace('US.',''):<8} {x['name'][:22]:<24} {', '.join(x['flags'])}")
json.dump(rows, open(os.path.join(BASE, "_pool_health.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\nHEALTH_DONE")
