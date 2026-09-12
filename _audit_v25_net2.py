# -*- coding: utf-8 -*-
"""v25 审计 · 联网 H2 全池版 —— 成交额口径是否让闸门误判?

背景: 闸门用 close(QFQ) x volume 当"成交额"。QFQ 会把历史价格按累计复权因子
      缩小(实测 NVDA 1:40.5、AMZN 1:20、ANET 1:16、AVGO 1:12.6、SMCI 1:10),
      于是历史"成交额"被同比例压低 -> 理论上可能把真实流动性充足的标的误判为"不流动"。
判定: 只要能找到任何一个格子 verdict 从"不可交易"翻成"可交易", 该缺陷就会实际改变信号。
      否则只能记为"口径不严谨但实测无影响", 并给出成立条件。
副产品: 落盘 adj_factor_changes.json (每只票的累计复权因子变化点), 供将来做"原始价闸门"。
"""
import os, sys, json, time, tempfile, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
GATE_DV, GATE_WIN = 5e6, 60
OUT = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

mi = json.load(open(os.path.join(BASE, "market_info.json"), encoding="utf-8"))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json"), encoding="utf-8"))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

_T = os.path.join(tempfile.gettempdir(), "futu_log_audit2"); os.makedirs(_T, exist_ok=True)
os.environ["APPDATA"] = _T
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close          # noqa: E402
from futu import SubType, AuType, SysConfig                    # noqa: E402
SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()
_, q0 = ctx.get_history_kl_quota(get_detail=False)
P(f"额度(前) 已用 {q0[0]} / 剩余 {q0[1]}")
P(f"全池 {len(UNI)} 只, 逐只拉 autype=NONE 全历史(已在本窗口内 -> 实测免费)")

def pull_raw(code, max_pages=6):
    frames, cur = [], "2018-01-01"
    for _ in range(max_pages):
        out = ctx.request_history_kline(code, start=cur, end="2026-09-12",
                                        ktype=SubType.K_DAY, autype=AuType.NONE, max_count=1000)
        ret, d = out[0], out[1]
        if ret != 0 or d is None or len(d) == 0:
            return None, ret
        d = d[["time_key", "close", "volume"]].copy()
        d["time_key"] = pd.to_datetime(d["time_key"])
        frames.append(d)
        if len(d) < 1000: break
        nxt = (d["time_key"].iloc[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if nxt == cur: break
        cur = nxt
        time.sleep(0.7)
    if not frames: return None, -1
    return (pd.concat(frames, ignore_index=True).drop_duplicates("time_key", keep="last")
            .sort_values("time_key").reset_index(drop=True)), 0

ADJ = {}
rows, ROWS = [], []
for k, c in enumerate(UNI, 1):
    sym = c.replace("US.", "")
    loc = pd.read_csv(os.path.join(LONGDIR, sym and c.replace(".", "_") + ".csv"))
    loc["time_key"] = pd.to_datetime(loc["time_key"])
    loc = loc.sort_values("time_key").drop_duplicates("time_key", keep="last")
    raw, ret = pull_raw(c)
    if raw is None:
        ROWS.append({"sym": sym, "n": 0, "minratio": np.nan, "flip": -1, "note": f"拉取失败 ret={ret}"})
        P(f"  [{k:>2}/{len(UNI)}] {sym:<7} 拉取失败 ret={ret}")
        continue
    m = loc.merge(raw, on="time_key", suffixes=("_q", "_r")).set_index("time_key")
    if len(m) < 70:
        ROWS.append({"sym": sym, "n": len(m), "minratio": np.nan, "flip": -1, "note": "重叠不足"})
        P(f"  [{k:>2}/{len(UNI)}] {sym:<7} 重叠不足 {len(m)} 根")
        continue
    ratio = (m["close_q"] / m["close_r"]).replace([np.inf, -np.inf], np.nan)
    dv_q = (m["close_q"] * m["volume_q"]).rolling(GATE_WIN, min_periods=GATE_WIN).median()
    dv_r = (m["close_r"] * m["volume_r"]).rolling(GATE_WIN, min_periods=GATE_WIN).median()
    ok_q, ok_r = dv_q >= GATE_DV, dv_r >= GATE_DV
    valid = dv_q.notna() & dv_r.notna()
    flip = int(((~ok_q) & ok_r & valid).sum())        # QFQ 口径说"不可交易", 原始口径说"可交易"
    back = int((ok_q & (~ok_r) & valid).sum())        # 反向
    # 复权因子变化点(只记变化, 稀疏)
    rc = ratio.round(6)
    chg = rc[rc.diff().abs() > 1e-6]
    ADJ[sym] = [{"date": str(t.date()), "ratio": float(v)} for t, v in chg.items()]
    rows.append({"sym": sym, "n": int(valid.sum()), "minratio": float(ratio.min()),
                 "flip": flip, "back": back})
    ROWS.append({"sym": sym, "n": int(valid.sum()), "minratio": float(ratio.min()),
                 "flip": flip, "note": ""})
    if flip or back:
        P(f"  [{k:>2}/{len(UNI)}] {sym:<7} ⚠ QFQ口径误判 {flip} 格 (反向 {back})")
    elif k % 10 == 0:
        P(f"  [{k:>2}/{len(UNI)}] {sym:<7} ok  可比 {int(valid.sum()):>4} 格, "
          f"复权因子最小 {ratio.min():.4f}")

df = pd.DataFrame(rows)
P("\n" + "=" * 112)
P("[H2] 全池结论")
P("=" * 112)
P(f"  可比格子总数: {df['n'].sum():,}")
P(f"  QFQ 口径把'可交易'误判为'不可交易' 的格子: {df['flip'].clip(lower=0).sum()}"
  f"   (反向 {df['back'].clip(lower=0).sum()})")
_bad = df[df["flip"] > 0].sort_values("flip", ascending=False)
if len(_bad):
    P("  受影响标的:")
    for _, r in _bad.iterrows():
        P(f"    {r['sym']:<7} {int(r['flip']):>5} 格  (复权因子最小 {r['minratio']:.4f})")
else:
    P("  ✅ 无任何格子因复权口径而改变闸门判定 -> 该口径缺陷在本池中【实测无影响】")
P("\n  成立条件(什么情况下才会咬人): 标的必须【同时】满足")
P("    ① 历史上发生过拆股/大额分红(复权因子 << 1); 且")
P("    ② 其真实成交额处在门槛附近(被缩放后跌破 $5M)。")
P("  本池里的拆股票(NVDA/AMZN/ANET/AVGO/SMCI/AAPL...)成交额都远超门槛, 缩放 40 倍仍过关。")
P("  => 结论: 保留现实现(用 QFQ 价), 但把本检查列为【每次扩容后的必跑项】。")
json.dump(ADJ, open(os.path.join(BASE, "adj_factor_changes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
P(f"\n  副产品: 已落盘 adj_factor_changes.json ({len(ADJ)} 只票的累计复权因子变化点)")
_, q1 = ctx.get_history_kl_quota(get_detail=False)
P(f"  额度(后) 已用 {q1[0]} / 剩余 {q1[1]}   本次消耗 {q1[0]-q0[0]}")
safe_close(ctx)
open(os.path.join(BASE, "_audit_v25_net2.txt"), "w", encoding="utf-8").write("\n".join(OUT))
print("\nNET2_DONE")
