# -*- coding: utf-8 -*-
"""v25 审计 · 联网部分 —— 两项必须用新鲜数据才能验的检查。

H1 复权接缝: 本地 CSV 是【分批增量合并】(fetch_latest 只刷最近 45 天, keep="last")。
   若期间发生拆股/复权基准漂移, 历史段与新刷段会落在不同基准上 -> 假断层。
   验证法: 用长窗口重拉一份 QFQ, 与本地逐日比对重叠区。

H2 成交额口径: 闸门用 close(QFQ) x volume 当"成交额"。QFQ 把历史价格按拆股比例
   缩放过 -> 历史"成交额"被同比例压低 -> 闸门可能误杀真实流动性充足的标的。
   验证法: 拉 autype=NONE(不复权), 用原始价算成交额, 看两种口径下闸门判定差多少。
"""
import os, sys, json, time, tempfile, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
OUT = []
def P(*a):
    s = " ".join(str(x) for x in a); print(s); OUT.append(s)

_T = os.path.join(tempfile.gettempdir(), "futu_log_audit"); os.makedirs(_T, exist_ok=True)
os.environ["APPDATA"] = _T
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close          # noqa: E402
from futu import SubType, AuType, SysConfig                    # noqa: E402
SysConfig.set_all_thread_daemon(True)

# 挑样本: 含拆股史的大票 + 闸门挡得最多的标的
SAMPLE = ["US.NVDA", "US.AAPL", "US.ANET", "US.SMCI", "US.AMZN",
          "US.SNDK", "US.ARM", "US.IREN", "US.META", "US.AVGO"]

ctx = create_quote_context()
_, q0 = ctx.get_history_kl_quota(get_detail=False)
P("=" * 112)
P(f"额度(前): 已用 {q0[0]} / 剩余 {q0[1]}")
P("=" * 112)

def pull(code, autype, start="2018-01-01", max_pages=6):
    """翻页拉全历史 (单次只返回区间【前】N 根 —— 必须把 start 推到 last+1 天)。
    request_history_kline 返回 3 元组 (ret, data, page_req_key)。"""
    frames, cur = [], start
    for _ in range(max_pages):
        out = ctx.request_history_kline(code, start=cur, end="2026-09-12",
                                        ktype=SubType.K_DAY, autype=autype, max_count=1000)
        ret, d = out[0], out[1]
        if ret != 0 or d is None or len(d) == 0:
            return None, ret
        d = d[["time_key", "open", "high", "low", "close", "volume"]].copy()
        d["time_key"] = pd.to_datetime(d["time_key"])
        frames.append(d)
        if len(d) < 1000:
            break
        nxt = (d["time_key"].iloc[-1] + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if nxt == cur:
            break
        cur = nxt
        time.sleep(0.7)
    if not frames:
        return None, -1
    return (pd.concat(frames, ignore_index=True).drop_duplicates("time_key", keep="last")
            .sort_values("time_key").reset_index(drop=True)), 0

LOCAL = {}
for c in SAMPLE:
    d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    LOCAL[c] = d.sort_values("time_key").drop_duplicates("time_key", keep="last").reset_index(drop=True)

# ---------------- H1 复权接缝 ----------------
P("\n" + "=" * 112)
P("[H1] 复权接缝检测 —— 本地(分批增量合并) vs 新鲜长窗口(一次性 QFQ)")
P("=" * 112)
P(f"  {'标的':<7}{'重叠根数':>8}{'最大相对差':>12}{'差异根数':>9}{'首次不同':>13}  判定")
H1_rows = []
for c in SAMPLE:
    fresh, ret = pull(c, AuType.QFQ)
    if fresh is None:
        P(f"  {c:<7} 拉取失败 ret={ret}"); continue
    lo = LOCAL[c]
    m = lo.merge(fresh, on="time_key", suffixes=("_loc", "_new"))
    rel = (np.abs(m["close_loc"] - m["close_new"]) / m["close_new"].replace(0, np.nan))
    nz = rel > 1e-6
    first = m.loc[nz.idxmax(), "time_key"] if nz.any() else None
    mx = float(rel.max()) if len(rel) else np.nan
    # 判定: 只有最后一根不同 = 未完成 bar; 局部差异 = 危险; 全段均匀差异 = 基准漂移
    if nz.sum() == 0:
        verdict = "✅ 完全一致"
    elif nz.sum() == 1 and m.loc[nz.idxmax(), "time_key"] == m["time_key"].iloc[-1]:
        verdict = "⚠ 仅末根不同(未完成 bar)"
    elif nz.mean() > 0.9:
        verdict = f"❌ 全段系统性差异 x{m['close_new'].iloc[0]/m['close_loc'].iloc[0]:.4f} (基准漂移)"
    else:
        verdict = f"❌ 局部断层, 首次不同 {first.date()} (最危险)"
    H1_rows.append({"sym": c.replace("US.", ""), "n": len(m), "max_rel": mx,
                    "nz": int(nz.sum()), "first": str(first.date()) if first is not None else "-",
                    "verdict": verdict})
    P(f"  {c.replace('US.',''):<7}{len(m):>8}{mx:>12.2e}{int(nz.sum()):>9}"
      f"{(str(first.date()) if first is not None else '-'):>13}  {verdict}")
    time.sleep(0.4)

_n_bad = sum(1 for r in H1_rows if r["verdict"].startswith("❌"))
P(f"\n  结论: 检查 {len(H1_rows)} 只, 接缝异常 {_n_bad} 只")

# ---------------- H2 成交额口径 ----------------
P("\n" + "=" * 112)
P("[H2] 成交额口径 —— 闸门用 QFQ 复权价算成交额是否正确?")
P("=" * 112)
P(f"  {'标的':<7}{'复权因子范围':>16}{'原始价vs复权价':>16}{'两种口径闸门判定差异':>22}")
H2_rows = []
Q = {r["sym"]: None for r in H1_rows}
for c in SAMPLE:
    sym = c.replace("US.", "")
    if not any(r["sym"] == sym for r in H1_rows):
        continue
    raw, ret = pull(c, AuType.NONE)
    if raw is None:
        P(f"  {sym:<7} NONE 拉取失败 ret={ret}"); continue
    m = LOCAL[c].merge(raw, on="time_key", suffixes=("_q", "_r"))
    if len(m) < 200:
        P(f"  {sym:<7} 重叠不足 {len(m)}"); continue
    ratio = m["close_q"] / m["close_r"]
    # 复权因子: 平滑段的比值 -> 拆股/分红事件表现为跳变
    jumps = ratio.pct_change().abs() > 0.02
    dv_q = (m["close_q"] * m["volume_q"]).rolling(60, min_periods=60).median()
    dv_r = (m["close_r"] * m["volume_r"]).rolling(60, min_periods=60).median()
    ok_q = dv_q >= 5e6
    ok_r = dv_r >= 5e6
    diff = int((ok_q != ok_r).sum())
    valid = int((dv_q.notna() & dv_r.notna()).sum())
    lo, hi = float(ratio.min()), float(ratio.max())
    H2_rows.append({"sym": sym, "rmin": lo, "rmax": hi, "diff": diff, "valid": valid,
                    "jumps": int(jumps.sum())})
    P(f"  {sym:<7}{lo:>7.4f} ~ {hi:<7.4f}{'':>2}1:{1/lo:<8.2f}{'':>4}"
      f"{diff:>6} / {valid:<6} ({diff/max(valid,1)*100:5.1f}%)")
    time.sleep(0.4)

_tot_d = sum(r["diff"] for r in H2_rows)
_tot_v = sum(r["valid"] for r in H2_rows)
P(f"\n  结论: 用 QFQ 价算成交额, 在 {_tot_d:,}/{_tot_v:,} 个可比格子上给出了"
  f"{'不同' if _tot_d else '相同'}的闸门判定 ({_tot_d/max(_tot_v,1)*100:.2f}%)")
P("  含义: 复权因子恒为 1 的标的(无拆股)完全不受影响; 因子 != 1 的标的历史成交额被")
P("        同比例缩放 —— 缩得越小, 越可能被当成'不流动'而误杀。")

_, q1 = ctx.get_history_kl_quota(get_detail=False)
P("\n" + "=" * 112)
P(f"额度(后): 已用 {q1[0]} / 剩余 {q1[1]}   本次消耗 {q1[0]-q0[0]}")
P("=" * 112)
safe_close(ctx)
open(os.path.join(BASE, "_audit_v25_net.txt"), "w", encoding="utf-8").write("\n".join(OUT))
print("\nNET_DONE")
