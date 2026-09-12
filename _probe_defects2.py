# -*- coding: utf-8 -*-
"""缺陷取证 第二轮: 未完成bar / 空洞 / 重复追加 / 输入校验"""
import os, sys, json, time, tempfile, datetime
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

print("=" * 110)
print("F  最后一根 bar 是否可能是【盘中未完成】或【被事后修正】")
print("=" * 110)
for c in ["US.AAPL", "US.MSFT", "US.META"]:
    p = os.path.join(LONGDIR, c.replace(".", "_") + ".csv")
    d = pd.read_csv(p)
    mt = datetime.datetime.fromtimestamp(os.path.getmtime(p))
    d["time_key"] = pd.to_datetime(d["time_key"])
    last = d.iloc[-1]
    print(f"  {c}: 文件修改时间 {mt:%Y-%m-%d %H:%M:%S} | 最后一根 {last['time_key'].date()} "
          f"O={last['open']:.2f} C={last['close']:.2f} V={last['volume']:,.0f}")

now_cn = datetime.datetime.now()
print(f"\n  当前北京时间: {now_cn:%Y-%m-%d %H:%M} ({'周六' if now_cn.weekday()==5 else '工作日'})")
# 美股常规时段(北京): 夏令时 21:30-04:00, 冬令时 22:30-05:00
def us_session_state(t):
    h = t.hour + t.minute/60.0
    # 简化: 用 21:30-04:00 判断(夏令时)
    return (h >= 21.5) or (h < 4.0)
print(f"  当前是否处于美股常规时段(北京 21:30-04:00): {us_session_state(now_cn)}")
src = open(os.path.join(BASE, "_update_signal.py"), encoding="utf-8").read()
has_guard = any(k in src for k in ["盘中", "未完成", "market_open", "is_us_session", "session_open"])
print(f"  脚本是否有【盘中运行】的防护: {'有' if has_guard else '❌ 无'}")
print("  -> 若在美股盘中运行, 最后一根是【未完成 bar】(有价格、有成交量), 现有检查无法识别")

print()
print("=" * 110)
print("G  面板中间出现【数据空洞】时能否被发现")
print("=" * 110)
import glob
files = sorted(glob.glob(os.path.join(LONGDIR, "*.csv")))
alld = {}
for f in files:
    d = pd.read_csv(f); d["time_key"] = pd.to_datetime(d["time_key"])
    alld[os.path.basename(f)[:-4]] = d.set_index("time_key").sort_index()
gaps_found = []
for k, d in alld.items():
    dd = d.index.to_series().diff().dt.days
    big = dd[dd > 12]
    if len(big) > 0:
        for ts, v in big.items():
            gaps_found.append((k, str(ts.date()), int(v)))
print(f"  扫描 {len(alld)} 个文件, 发现 >12 自然日的间隔: {len(gaps_found)} 处")
for k, ts, v in gaps_found[:12]:
    print(f"     {k}: 到 {ts} 前有空档 {v} 天")
print(f"  脚本 load() 用 ffill(limit=10) -> 空档 >10 日不会被填充, 面板里留 NaN")
print(f"  脚本是否有【面板空洞】检测: {'有' if any(k in src for k in ['空洞','gap','缺口']) else '❌ 无'}")

print()
print("=" * 110)
print("H  重复运行是否会在 signal_history.csv 里写重复行")
print("=" * 110)
HIST = os.path.join(BASE, "signal_history.csv")
if os.path.exists(HIST):
    h = pd.read_csv(HIST)
    print(f"  现有 {len(h)} 行")
    dup = h.duplicated(subset=["date", "strategy", "topk"], keep=False)
    print(f"  按(date,strategy,topk)重复的行: {dup.sum()} 行")
    if dup.sum():
        print(h[dup].to_string(index=False))
    print(f"  脚本是否有去重: {'有' if 'drop_duplicates' in src.split('def self_test')[0].split('# 持久化')[-1] else '❌ 无 (mode=\"a\" 直接追加)'}")
else:
    print("  signal_history.csv 不存在")

print()
print("=" * 110)
print("I  portfolio.json 输入校验")
print("=" * 110)
print("  --bought 解析: c,q = cq.split(':') ; 无 ticker 白名单校验")
print("  --positions 解析: c,q = kv.split(':') ; 无校验")
try:
    _ = float("abc")
except Exception as e:
    print(f"  float('abc') -> {type(e).__name__} (会在启动阶段直接崩, 无友好提示)")
print("  若填错 ticker (如 'APPL'), POSITIONS 里会有幽灵持仓, 但 px_now.get 取不到 -> 市值为 0")
print("  -> 市值被低估, 净值算错, 目标股数跟着错。脚本是否校验 ticker 合法性: ❌ 无")

print()
print("=" * 110)
print("J  税务 / 分红 / 除息 是否被建模")
print("=" * 110)
for kw, desc in [("dividend", "股息"), ("withhold", "预扣税"), ("tax", "资本利得税"), ("ex_div", "除息")]:
    print(f"  {'✓' if kw in src.lower() else '❌'} 提及「{desc}」")
print("  -> 全部未建模: 美股股息对非美居民征 30%, 分红再投资也没算进收益")

print()
print("=" * 110)
print("K  汇率与本金口径")
print("=" * 110)
print(f"  FX 默认 6.7092 硬编码在源码第 54 行, 不联网更新")
print(f"  CAP0 来源优先级: --capital > --cny/FX > 10000/FX")
print(f"  -> 长期运行需要人工改源码或每次传参, 汇率漂移无人提醒")
