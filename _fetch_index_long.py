# -*- coding: utf-8 -*-
"""
拉取长历史指数/防御资产日线，用于"能不能避开熊市"的择时统计。
SPY 1993 起（含 2000-02 互联网泡沫、2008 金融危机、2020、2022 四次熊市）。
同时拉 TLT(长债)/GLD(黄金)/SHY(短债) 作为熊市避险去向候选。

规避已知坑:
  - 坑1 日志: import futu 前重定向 APPDATA
  - 坑4 额度: 先查额度
  - 坑6 翻页: 单次返回区间【前】N 根，必须推进 start 翻页
"""
import os, sys, json, time, tempfile

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_bear")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SubType, AuType
import pandas as pd

START = "1993-01-01"
END   = "2026-09-12"
OUTDIR = os.path.join(BASE, "data_index_long")
os.makedirs(OUTDIR, exist_ok=True)

TARGETS = ["US.SPY", "US.TLT", "US.GLD", "US.SHY", "US.IEF", "US.VOO"]

ctx = create_quote_context()
_, q = ctx.get_history_kl_quota(get_detail=False)
remaining = q[1] if isinstance(q, (list, tuple)) else 9999
print("QUOTA_REMAINING", remaining)
safe_close(ctx)


def fetch_one(ctx, code):
    chunks = []
    start = START
    for page in range(40):
        out = ctx.request_history_kline(code, start=start, end=END,
                                        ktype=SubType.K_DAY, autype=AuType.QFQ,
                                        max_count=1000)
        ret, kd = out[0], out[1]
        if ret != 0:
            time.sleep(5)
            continue
        if kd is None or len(kd) == 0:
            break
        kd = kd[kd["time_key"] < END].copy()
        chunks.append(kd)
        last = kd["time_key"].iloc[-1]
        print(f"   page{page+1} rows={len(kd)} last={last}")
        if len(kd) < 1000:
            break
        nxt = (pd.to_datetime(last) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if nxt <= start:
            break
        start = nxt
        time.sleep(1.2)
    if not chunks:
        return None
    return (pd.concat(chunks, ignore_index=True)
              .drop_duplicates("time_key").sort_values("time_key").reset_index(drop=True))


ctx = create_quote_context()
rows = []
for code in TARGETS:
    df = fetch_one(ctx, code)
    if df is None or len(df) < 200:
        print(f"SKIP {code}")
        continue
    df[["time_key", "open", "close", "high", "low", "volume"]].to_csv(
        os.path.join(OUTDIR, code.replace(".", "_") + ".csv"), index=False)
    rows.append({"code": code, "rows": len(df),
                 "first": str(df["time_key"].iloc[0]), "last": str(df["time_key"].iloc[-1])})
    print(f"OK {code} rows={len(df)} {df['time_key'].iloc[0]}..{df['time_key'].iloc[-1]}")
    time.sleep(1.2)
safe_close(ctx)

json.dump(rows, open(os.path.join(BASE, "fetched_index_manifest.json"), "w"),
          ensure_ascii=False, indent=2)
print("FETCHED", len(rows))
print("FETCH_DONE")
