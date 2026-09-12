# -*- coding: utf-8 -*-
"""v27.1: 审计并修正 signal_history.csv 里的 exec_day 列。

背景: v27 初版的 [3] 段在"最后一根恰好是调仓日"时会报 next_trading_day(最后一根),
比引擎实际成交日晚 1 个交易日。凡是那次口径下写进历史的 exec_day 都是错的。

为什么可以【就地修正】而不是重跑:
    exec_day 是【派生列】, 只由 (date, rebal, anchor) 决定 —— 与 pool_size / variant 无关。
    而 pool_size=37 那两行出自已经变更过的旧标的池, 重跑已不可复现。
    所以只重算这一列, 不动 picks / pool_size / variant, 既修好又保住审计轨迹。

用法:
    python _v27_hist_audit.py          # 只审计, 不改文件
    python _v27_hist_audit.py --fix    # 就地修正 exec_day (先备份 .cal-bak)

用完可删（一次性分析脚本）。
"""
import sys, os, shutil, datetime
import pandas as pd

FIX = "--fix" in sys.argv
sys.argv = [sys.argv[0]]
import _update_signal as U

dates, PX, REAL = U.load(U.UNI)
dp = pd.to_datetime(dates)
N = len(dp)
pos = {str(d.date()): i for i, d in enumerate(dp)}


def anchor_index(tag):
    """把 history 里的 anchor 标签还原成面板索引 (与 [3] 段同一套规则)"""
    if tag in ("-", "", "nan") or pd.isna(tag):
        return U.START, False
    ad = datetime.date.fromisoformat(str(tag))
    cand = [i for i in range(N) if dp[i].date() >= ad]
    if not cand:                                  # 未来锚点 -> 投影到面板之后
        k, d = 0, dp[N - 1].date()
        while d < ad:
            d = U.next_trading_day(d); k += 1
        return (N - 1) + k, True
    return cand[0], False


h = pd.read_csv(U.HIST)
print(f"signal_history.csv 共 {len(h)} 行 ｜ 面板 {dp[0].date()} ~ {dp[N-1].date()}")
print("=" * 104)
print(f"  {'date':<12}{'strategy':<14}{'pool':>5}{'rebal':>6}{'anchor':>12}"
      f"{'历史 exec_day':>15}{'应为':>14}  判定")
print("  " + "-" * 100)

bad, unknown, ok = [], [], 0
newcol = h["exec_day"].astype(object).copy() if "exec_day" in h.columns else None
for n, (_, r) in enumerate(h.iterrows()):
    d = str(r["date"])
    reb = int(r["rebal"]) if "rebal" in h.columns and pd.notna(r.get("rebal")) else 21
    anc = str(r["anchor"]) if "anchor" in h.columns and pd.notna(r.get("anchor")) else "-"
    got = "" if pd.isna(r.get("exec_day")) else str(r["exec_day"])
    if d not in pos:
        unknown.append((d, r["strategy"], reb, "日期不在面板")); continue
    ai, virt = anchor_index(anc)
    if virt:
        unknown.append((d, r["strategy"], reb, "未来锚点, 需人工确认")); continue
    off = U.next_exec_offset(pos[d], ai, reb)
    want = str(U.project_trading_days(dp[pos[d]].date(), off))
    newcol.iloc[n] = want
    if want == got:
        ok += 1
        continue
    bad.append((d, r["strategy"], reb, anc, got, want))
    print(f"  {d:<12}{str(r['strategy']):<14}{int(r['pool_size']):>5}{reb:>6}{anc:>12}"
          f"{got:>15}{want:>14}  ❌ 旧口径")

print("  " + "-" * 100)
print(f"  ✅ 一致 {ok} 行 ｜ ❌ 旧口径 {len(bad)} 行 ｜ ⚠ 无法判定 {len(unknown)} 行")
for u in unknown:
    print(f"     ⚠ {u[0]} {u[1]} rebal={u[2]} —— {u[3]}")

if not bad:
    print("\n  无需修正。")
elif not FIX:
    print(f"\n  加 --fix 就地修正这 {len(bad)} 行的 exec_day（先自动备份 .cal-bak）。")
else:
    if unknown:
        raise SystemExit(f"  拒绝修正: 还有 {len(unknown)} 行无法判定, 请先人工确认")
    bak = U.HIST + ".cal-bak"
    shutil.copy2(U.HIST, bak)
    h["exec_day"] = newcol
    h.to_csv(U.HIST, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ 已修正 {len(bad)} 行; 备份 -> {os.path.basename(bak)}")
    print("     重跑本脚本应显示『无需修正』。")
