# -*- coding: utf-8 -*-
"""统一 data_kline_long 里 time_key 的格式为纯日期, 并复核额度消耗"""
import os, sys, json, glob, tempfile
import pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
D = os.path.join(BASE, "data_kline_long")

print("=" * 80)
print("[1] 统一 time_key 为 YYYY-MM-DD")
print("=" * 80)
fixed = 0
for p in sorted(glob.glob(os.path.join(D, "*.csv"))):
    df = pd.read_csv(p)
    raw = df["time_key"].astype(str)
    new = raw.str.slice(0, 10)
    if not raw.equals(new):
        df["time_key"] = new
        df.to_csv(p, index=False)
        fixed += 1
print(f"   规范化了 {fixed} 个文件")
# 复核
bad = []
for p in sorted(glob.glob(os.path.join(D, "*.csv"))):
    df = pd.read_csv(p)
    if (df["time_key"].astype(str).str.len() != 10).any():
        bad.append(os.path.basename(p))
print(f"   仍非 10 位日期的文件: {bad if bad else '无'}")
print(f"   data_kline_long 现有 {len(glob.glob(os.path.join(D, '*.csv')))} 个 CSV")

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_q")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig

print()
print("=" * 80)
print("[2] 额度复核 —— 花了多少")
print("=" * 80)
SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()
ret, q = ctx.get_history_kl_quota(get_detail=True)
ok = ret == 0
print(f"   已用 {q[0]} / 总 {q[0]+q[1]}   剩余 {q[1]}")
print(f"   抓取前: 已用 290, 剩余 10")
print(f"   抓取后: 已用 {q[0]}, 剩余 {q[1]}  ->  实际消耗 {q[0]-290} 个")
safe_close(ctx)
print("NORMALIZE_DONE")
