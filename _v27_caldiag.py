# -*- coding: utf-8 -*-
"""日历一致性诊断: 工具报出的执行日 vs 回测引擎的执行日。

⚠ 本脚本【故意复刻 v27 修复前】的日历逻辑 (is_rebal -> next_trading_day),
  用来当 off-by-one 缺陷的【证据】保留 —— 它现在会报出不一致, 那是预期的。
  当前生效的逻辑在 _update_signal.py 的 next_exec_offset(), 一致性由自检
  的『面板内执行日索引 100% 命中引擎调仓日』(1932 个样本) 保证。

结论(2026-09-12 实测): 引擎执行日含 2026-09-11, 旧写法报 2026-09-14 -> 晚 1 个交易日。
用完可删。
"""
import sys, datetime, io
sys.argv = [sys.argv[0]]
import _update_signal as U

out = []
def P(s=""):
    out.append(str(s)); print(s)

dates, PX, REAL = U.load(U.UNI)
N = len(dates); START = U.START

for REBAL in (21, 10):
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    rbset = set(RB)
    P(f"===== 调仓周期 {REBAL} 日 =====")
    P("引擎执行日(最后5个): " + ", ".join(str(dates[i].date()) for i in RB[-5:]))
    P("")
    P("复刻【工具】的日历逻辑, 遍历'数据末根 t', 看它报出的执行日:")
    prev = None
    flips = 0
    for t in range(max(START, N - 40), N):
        if t in rbset:
            ex = U.next_trading_day(dates[t].date())
        else:
            nxt = [i for i in RB if i > t]
            ex = dates[nxt[0]].date() if nxt else None
        if ex != prev:
            P(f"   数据末根 {dates[t].date()}  ->  执行日 {ex}")
            if prev is not None:
                flips += 1
            prev = ex
    P("")
    P(f"  执行日切换次数: {flips}（每次切换 = 用户会被通知一个新的执行日）")
    P("")
    # 关键判据: 引擎的执行日, 在工具序列里出现过吗?
    eng = [dates[i].date() for i in RB[-8:]]
    tool = []
    prev = None
    for t in range(max(START, N - 40), N):
        if t in rbset:
            ex = U.next_trading_day(dates[t].date())
        else:
            nxt = [i for i in RB if i > t]
            ex = dates[nxt[0]].date() if nxt else None
        if ex != prev:
            tool.append(ex); prev = ex
    P("  引擎执行日集合: " + ", ".join(str(x) for x in eng))
    P("  工具执行日集合: " + ", ".join(str(x) for x in tool))
    P("  交集: " + (", ".join(str(x) for x in sorted(set(eng) & set(tool))) or "（空！）"))
    P("")

with io.open("_v27_cal_diag.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(out))
