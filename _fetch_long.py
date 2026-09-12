# -*- coding: utf-8 -*-
"""
拉取 37 只美股大盘股 2018-01-01 ~ 2026-09-11 的日线历史 K 线 (牛熊长周期)
存入 data_kline_long/，供长周期回测使用。

要点（基于用户长期记忆中的 futu SDK 已知坑）:
  - 坑4 额度: 每只标的 30 天内只计 1 次；37 只远在额度内。
  - 坑6 翻页: request_history_kline 单次要 max_count(<=1000) 根，且返回的是
    区间【前】N 根（从 start 往前数）。要覆盖 8.7 年必须翻页。
  - 坑1 日志: 导入 futu 前把 APPDATA 临时重定向，避免日志写入被拒导致静默退出。
"""
import os, sys, json, time, tempfile

# ---- 坑1: 导入 futu 前重定向 APPDATA，避免日志写入被拒静默退出 ----
_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_long")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SubType, AuType

START = "2018-01-01"
END   = "2026-09-11"
OUTDIR = os.path.join(BASE, "data_kline_long")
os.makedirs(OUTDIR, exist_ok=True)

# ---- 复用与 v7 完全相同的 37 只大盘股池 ----
mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
def is_etf(name):
    n = (name or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched
       if not is_etf(mi.get(c,{}).get("name",""))
       and (mi.get(c,{}).get("total_market_val",0) or 0) >= 10e9]
print("UNIVERSE_SIZE", len(UNI), UNI)

# ---- 先看剩余额度 ----
ctx = create_quote_context()
_, q = ctx.get_history_kl_quota(get_detail=False)
remaining = q[1] if isinstance(q, (list, tuple)) else 9999
print("QUOTA_REMAINING", remaining)
safe_close(ctx)
if remaining < len(UNI):
    print(f"[WARN] 额度 {remaining} < 需要 {len(UNI)}，将只取前 {remaining} 只")

import pandas as pd

def fetch_one(ctx, code):
    """分页拉取单只标的 [START, END] 全段日线，返回 DataFrame（含 time_key/open/close/high/low/volume）。"""
    chunks = []
    start = START
    pages = 0
    while True:
        pages += 1
        if pages > 20:
            print(f"  [ABORT] {code} 翻页超限"); break
        retry = 0
        while True:
            try:
                out = ctx.request_history_kline(code, start=start, end=END,
                                               ktype=SubType.K_DAY, autype=AuType.QFQ,
                                               max_count=1000)
                ret = out[0]; kd = out[1]
            except Exception as e:
                retry += 1
                if retry > 4:
                    print(f"  [ERR] {code} 异常 {e}"); return None
                time.sleep(3); continue
            if ret != 0:
                # 频率超限等可重试错误
                msg = str(kd)
                retry += 1
                if "freq" in msg.lower() or "limit" in msg.lower() or retry <= 4:
                    time.sleep(5); continue
                print(f"  [ERR] {code} ret={ret} {msg[:60]}"); return None
            break
        if kd is None or len(kd) == 0:
            break
        kd = kd[kd["time_key"] < END].copy()
        chunks.append(kd)
        last = kd["time_key"].iloc[-1]
        if last >= END or len(kd) < 1000:
            break
        # 翻页: 从最后一根次日继续（坑6: 返回区间前 N 根，需推进 start）
        nxt = (pd.to_datetime(last) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if nxt <= start:
            break
        start = nxt
        time.sleep(1.0)  # 节流，远低于 60/30s
    if not chunks:
        return None
    full = pd.concat(chunks, ignore_index=True).drop_duplicates("time_key").sort_values("time_key")
    return full

ctx = create_quote_context()
manifest = []
for code in UNI:
    fpath = os.path.join(OUTDIR, code.replace(".", "_") + ".csv")
    df = fetch_one(ctx, code)
    if df is None or len(df) < 200:
        print(f"SKIP {code} rows={len(df) if df is not None else 0}")
        continue
    df[["time_key","open","close","high","low","volume"]].to_csv(fpath, index=False)
    manifest.append((code, len(df), df["time_key"].iloc[0], df["time_key"].iloc[-1]))
    print(f"OK {code} rows={len(df)} {df['time_key'].iloc[0]}..{df['time_key'].iloc[-1]}")
    time.sleep(1.0)
safe_close(ctx)

with open(os.path.join(BASE, "fetched_long_manifest.json"), "w") as f:
    json.dump([{"code":c,"rows":r,"first":a,"last":b} for c,r,a,b in manifest], f, ensure_ascii=False, indent=2)
print("FETCHED", len(manifest), "FILES_IN", OUTDIR)
print("FETCH_DONE")
