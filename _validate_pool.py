# -*- coding: utf-8 -*-
"""
标的池数据质量验证 (对 100 只目标标的全查)
检查项:
  1. 文件存在 / 行数 / 起止日期
  2. 与基准(SPY)交易日对齐: 停牌缺口、多出的日期
  3. OHLC 逻辑: high>=max(open,close), low<=min(open,close), 全正
  4. 重复 time_key / NaN
  5. 单日极端涨跌 (>50%) —— 多半是复权或拆股口径问题
  6. 末根 bar 是否疑似盘中未完成(量比 < 0.5)
"""
import os, json, glob, sys
import pandas as pd
import numpy as np

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
D = os.path.join(BASE, "data_kline_long")

target = json.load(open(os.path.join(BASE, "universe_heat100_target.json"), encoding="utf-8"))
codes = [r["code"] for r in sorted(target["target100"], key=lambda x: x["rank"])]

ref = pd.read_csv(os.path.join(D, "US_SPY.csv"))
ref_dates = set(ref["time_key"])

print("=" * 96)
print(f"验证 {len(codes)} 只目标标的")
print("=" * 96)
print(f"{'代码':<8}{'行数':>6}{'起始':>12}{'末日':>12}{'缺日':>6}{'多日':>6}"
      f"{'OHLC错':>7}{'重复':>6}{'NaN':>5}{'极端%':>6}{'末量比':>8}  判定")
print("-" * 96)

problems, summary = [], []
for c in codes:
    p = os.path.join(D, c.replace(".", "_") + ".csv")
    if not os.path.exists(p):
        print(f"{c.replace('US.',''):<8}{'—':>6}  文件缺失  <== 未抓取")
        problems.append((c, "文件缺失"))
        continue
    df = pd.read_csv(p)
    n = len(df)
    first, last = df["time_key"].iloc[0], df["time_key"].iloc[-1]
    dset = set(df["time_key"])
    # 只比对区间内的日期
    lo, hi = first, last
    ref_in = {d for d in ref_dates if lo <= d <= hi}
    miss = len(ref_in - dset)     # 基准有我们没有 -> 停牌/缺数据
    extra = len(dset - ref_dates)  # 我们有基准没有 -> 日历不一致
    o, h, l, cl = df["open"], df["high"], df["low"], df["close"]
    ohlc_bad = int(((h < np.maximum(o, cl) - 1e-6) | (l > np.minimum(o, cl) + 1e-6)
                    | (o <= 0) | (cl <= 0) | (h <= 0) | (l <= 0)).sum())
    dup = int(n - df["time_key"].nunique())
    nan = int(df[["open", "close", "high", "low", "volume"]].isna().sum().sum())
    ret = cl.pct_change()
    ext = int((ret.abs() > 0.5).sum())
    med = df["volume"].tail(21).iloc[:-1].median()
    ratio = df["volume"].iloc[-1] / med if med else float("nan")
    flags = []
    if n < 253: flags.append(f"历史<253")
    if miss > 5: flags.append(f"缺口大于5天")
    if ohlc_bad: flags.append("OHLC异常")
    if dup: flags.append("重复行")
    if nan: flags.append("NaN")
    if ext: flags.append("极端涨跌")
    if ratio == ratio and ratio < 0.5: flags.append("末根疑似未完成")
    verdict = "OK" if not flags else " | ".join(flags)
    if flags:
        problems.append((c, verdict))
    summary.append((c, n, miss, extra, last, ratio))
    print(f"{c.replace('US.',''):<8}{n:>6}{first:>12}{last:>12}{miss:>6}{extra:>6}"
          f"{ohlc_bad:>7}{dup:>6}{nan:>5}{ext:>6}{(f'{ratio:.2f}' if ratio==ratio else '—'):>8}  {verdict}")

print("-" * 96)
ok = len(codes) - len(problems)
print(f"\n通过 {ok} / {len(codes)}    异常 {len(problems)}")
if problems:
    print("\n异常明细:")
    for c, why in problems:
        print(f"   {c.replace('US.',''):<8} {why}")

lasts = {}
for c, n, miss, extra, last, ratio in summary:
    lasts[last] = lasts.get(last, 0) + 1
print(f"\n末根日期分布: {lasts}")
print(f"行数区间: {min(n for _,n,_,_,_,_ in summary)} .. {max(n for _,n,_,_,_,_ in summary)}")
json.dump({"ok": ok, "problems": problems,
           "rows": {c: n for c, n, _, _, _, _ in summary}},
          open(os.path.join(BASE, "_pool_validate.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("VALIDATE_DONE")
