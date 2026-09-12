# -*- coding: utf-8 -*-
"""
判定新抓文件的复权口径 (不依赖任何外部记忆):
  同一只票, 分别用 autype=NONE(不复权) 与 QFQ(前复权) 拉一次, 对比:
    - NONE 在拆股日附近会出现巨大断崖(价格腰斩/除以N)
    - QFQ 应当平滑
  若两者序列完全一致 -> 说明该票区间内没有除权事件, 换一只再看
注意: 重复请求本窗口内已占额度 -> 不消耗额度
"""
import os, sys, json, tempfile, time
import pandas as pd
import numpy as np

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_au")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig, SubType, AuType

SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()

ret, q = ctx.get_history_kl_quota(get_detail=False)
print(f"额度: 已用 {q[0]} / 总 {q[0]+q[1]}   剩余 {q[1]}  (重复请求应当免费)")

TESTS = ["US.ANET", "US.NVDA", "US.NFLX"]

def grab(code, autype):
    out = ctx.request_history_kline(code, start="2018-01-01", end="2026-09-12",
                                    ktype=SubType.K_DAY, autype=autype, max_count=1000)
    if out[0] != 0:
        return None, str(out[1])[:90]
    d = out[1]
    d = d[d["time_key"] < "2026-09-12"].copy()
    d["time_key"] = pd.to_datetime(d["time_key"]).dt.strftime("%Y-%m-%d")
    return d[["time_key", "close"]].reset_index(drop=True), None

for code in TESTS:
    print("\n" + "=" * 90)
    print(f"[{code}]")
    print("=" * 90)
    dq, eq = grab(code, AuType.QFQ)
    dn, en = grab(code, AuType.NONE)
    if dq is None or dn is None:
        print(f"   QFQ err={eq}   NONE err={en}")
        continue
    m = dq.merge(dn, on="time_key", suffixes=("_qfq", "_raw"))
    m["ratio"] = m["close_qfq"] / m["close_raw"]
    print(f"   行数 QFQ={len(dq)} NONE={len(dn)} 合并={len(m)}")
    print(f"   首行: {m.time_key.iloc[0]}  qfq={m.close_qfq.iloc[0]:.4f} raw={m.close_raw.iloc[0]:.4f} 比={m.ratio.iloc[0]:.6f}")
    print(f"   末行: {m.time_key.iloc[-1]}  qfq={m.close_qfq.iloc[-1]:.4f} raw={m.close_raw.iloc[-1]:.4f} 比={m.ratio.iloc[-1]:.6f}")
    same = bool(np.allclose(m.close_qfq, m.close_raw, rtol=1e-9))
    print(f"   两条序列完全相同? {same}")
    # 找比值跳变(除权点)
    m["dratio"] = m.ratio.pct_change()
    jumps = m[m.dratio.abs() > 0.05]
    if len(jumps):
        print(f"   比值跳变(除权事件) {len(jumps)} 处:")
        for _, r in jumps.head(8).iterrows():
            print(f"      {r.time_key}  比 {r.ratio:.4f} (变化 {r.dratio*100:+.2f}%)"
                  f"   qfq {r.close_qfq:.2f}  raw {r.close_raw:.2f}")
    else:
        print("   比值恒定 -> 该区间无除权事件, 换一只验证")
    # 各自的最大单日跳变
    for tag, col in [("QFQ", "close_qfq"), ("RAW", "close_raw")]:
        r = m[col].pct_change()
        i = int(np.nanargmax(np.abs(r.fillna(0))))
        print(f"   {tag} 最大单日变动: {r.iloc[i]*100:+.1f}%  于 {m.time_key.iloc[i]}")

safe_close(ctx)
print("\nAU_DONE")
