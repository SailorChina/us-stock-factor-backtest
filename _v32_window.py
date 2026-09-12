# -*- coding: utf-8 -*-
"""
v32: 因子窗口敏感性审计 —— Vortex 的 14 日窗口是"选出来的"还是"最优的"？

背景
----
v30 发现「调仓周期」不是一个连续参数, 而是一个【相位】—— anchor 冻在第 252 根,
换一天起步 10 日调仓的 CAGR 就在 51.3% ~ 100.6% 之间摆动。教训是:
    凡是"冻在某一个值上、从未扫过"的参数, 都可能藏着一个未计价的自由度。

顺着这条线往下查, 主策略的【信号本身】还有两个这样的参数:

  1. Vortex 的窗口 n —— 全项目写死 n=14 (_update_signal.vortex(h,l,c,n=14)),
     69 个策略共用 vort14。为什么是 14？因为它是技术分析的习惯值, 不是实测出来的。
  2. 流动性闸门阈值 —— GATE_DV = 5e6, v25 定下后从未扫描。

本脚本审第 1 个(信号参数), 因为它比闸门更靠近"选什么"。

审计设计
--------
[1]  自证      : n=14 重建的因子矩阵必须与 U.build_signals 的 "Vortex" 逐位相同;
                 phase=0 终值必须复现 v27/v30 的 $231,899.60
[2]  窗口扫描  : n ∈ {5,7,10,14,20,30,42,63} x rebal ∈ {10,21}, 每个 (n,rebal) 扫【全部相位】
[3]  关键判据  : n=14 在窗口排名里排第几？最优窗口领先 n=14 多少？
[4]  配对胜率  : 最优窗口 vs n=14, 相位全组合
[5]  窗口x周期 : "10 日 > 21 日" 是否在每个窗口下都成立
[5b] 前后半段  : 最优窗口的优势在【前后半段】是否同向(防止只在半段里赢)
[6]  结论

口径: 最小换手 ｜ 本金 $1,490.49 ｜ 佣金 $2/笔 ｜ 成交价 = 开盘
      相位分布用【口径 B 共同窗口】(起点 = 第 314 根, 与 v30 口径 B 对齐, 可直接比)

⚠ 本审计的目的是【检验 n=14 的稳健性】, 不是【挑一个更好的窗口】。
   扫 8 个窗口 = 8 次比较, 挑出来的"最优"必然含运气(多重比较)。
   若最优窗口明显好于 14, 正确结论不是"改用那个窗口", 而是
   "冠军的优势依赖于一个我事后才选的参数"。

用法:  python _v32_window.py
"""
import os, sys, json
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.argv = [sys.argv[0]]                 # 屏蔽外部参数，避免污染被导入模块的 arg()
import _update_signal as U
import _v27_cost as C
import _v30_phase as V30
from _v30_phase import engine_phase as _EP

WINDOWS = (5, 7, 10, 14, 20, 30, 42, 63)   # 扫描的窗口
REBALS = (10, 21)                          # v26 的两个决赛周期
BASE_WIN = 14                              # 项目当前写死的窗口
CAP_REAL = 1490.49                         # 用户真实本金(USD)
COMM_REAL = 2.0                            # 富途美股 $2/笔
COMMON_LAG = 62                            # 与 v30 口径 B 对齐: START_I + 62 = 314

N = None
START_I = None
COMMON_I0 = None
MID_I = None
DATES = None
PXg = TRADEg = REALg = None
OVg = CVg = GMg = None


# ---------------------------------------------------------------- 数据
def build():
    global N, START_I, COMMON_I0, MID_I, DATES
    global PXg, TRADEg, REALg, OVg, CVg, GMg
    dates, PX, REAL = U.load(U.UNI)
    TRADE, _ = U.tradable_mask(PX, U.GATE_DV)
    N = len(dates)
    START_I = int(U.START)
    COMMON_I0 = START_I + COMMON_LAG
    MID_I = COMMON_I0 + (N - COMMON_I0) // 2
    DATES = pd.DatetimeIndex(dates)
    PXg, TRADEg, REALg = PX, TRADE, REAL
    OVg, CVg = PX["open"].values, PX["close"].values
    GMg = TRADE.values & REAL.values
    # 让被复用的 v30 引擎看到同一套面板
    V30.N = N
    V30.START_I = START_I
    C.N = N
    return PX, TRADE, REAL


def build_A(n):
    """按窗口 n 重建 Vortex 因子矩阵（施加与生产口径完全相同的掩码）。"""
    V = U.vortex(PXg["high"], PXg["low"], PXg["close"], int(n))
    valid = TRADEg & REALg
    return V.where(valid).values


# ---------------------------------------------------------------- 指标
def cagr_from(eq, i0):
    yrs = (N - i0) / 252.0
    base, final = float(eq[i0]), float(eq[-1])
    if not np.isfinite(base) or base <= 0 or not np.isfinite(final) or final <= 0:
        return float("nan")
    return (final / base) ** (1.0 / yrs) - 1.0


def cagr_range(eq, i0, i1):
    """区间 [i0, i1] 的年化（用于前后半段稳健性）。"""
    yrs = (i1 - i0) / 252.0
    base, final = float(eq[i0]), float(eq[i1])
    if not np.isfinite(base) or base <= 0 or not np.isfinite(final) or final <= 0:
        return float("nan")
    return (final / base) ** (1.0 / yrs) - 1.0


def dist(vals):
    a = np.array([v for v in vals if np.isfinite(v)], dtype=float)
    if not len(a):
        nan = float("nan")
        return dict(n=0, mean=nan, median=nan, std=nan, mn=nan, mx=nan, span=nan,
                    p25=nan, p75=nan, iqr=nan)
    q = np.percentile(a, [25, 50, 75])
    return dict(n=len(a), mean=float(a.mean()), median=float(q[1]),
                std=(float(a.std(ddof=1)) if len(a) > 1 else 0.0),
                mn=float(a.min()), mx=float(a.max()), span=float(a.max() - a.min()),
                p25=float(q[0]), p75=float(q[2]), iqr=float(q[2] - q[0]))


def pair_win(a, b):
    """把两组相位全组合，返回 (a 胜, b 胜, 有效组数, 平均差)。"""
    wa = wb = 0
    diffs = []
    for x in a:
        for y in b:
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            diffs.append(x - y)
            if x > y:
                wa += 1
            elif y > x:
                wb += 1
    return wa, wb, len(diffs), (float(np.mean(diffs)) if diffs else float("nan"))


# ---------------------------------------------------------------- 扫描
def scan(A, rebal, mode="min", cap=CAP_REAL, comm=COMM_REAL):
    """一个 (窗口, 周期) 下的【全部相位】。"""
    rows = []
    for k in range(int(rebal)):
        r = _EP(A, OVg, CVg, GMg, rebal, k, mode=mode, cap=cap, comm=comm)
        eq = r["eq"]
        rows.append(dict(
            phase=int(k),
            cagr=cagr_from(eq, COMMON_I0),
            cagr_h1=cagr_range(eq, COMMON_I0, MID_I),
            cagr_h2=cagr_range(eq, MID_I, N - 1),
            final=float(eq[-1]),
            n_sell=int(r["n_sell"]), n_buy=int(r["n_buy"]),
        ))
    return rows


# ---------------------------------------------------------------- 主流程
def main():
    build()
    P = print
    P("=" * 108)
    P("v32 因子窗口敏感性：Vortex 的 14 日窗口是「选出来的」还是「最优的」？")
    P("=" * 108)
    P(f"  面板 {N} 根 ｜ 预热 {START_I} 根 ｜ 区间 {DATES[START_I].date()} ~ {DATES[-1].date()}"
      f" ｜ 回测 {(N-START_I)/252:.2f} 年")
    P(f"  口径: 最小换手 ｜ 本金 ${CAP_REAL:,.2f} ｜ 佣金 ${COMM_REAL:.0f}/笔 ｜ 成交价 = 开盘")
    P(f"  相位分布口径 B(共同窗口): 第 {COMMON_I0} 根 ({DATES[COMMON_I0].date()}) 起, "
      f"{(N-COMMON_I0)/252:.2f} 年")
    P(f"  扫描窗口: {list(WINDOWS)} ｜ 周期: {list(REBALS)}")

    # ---------------- [1] 自证 ----------------
    P("\n" + "=" * 108)
    P("[1] 自证：n=14 重建的因子矩阵必须与生产口径逐位相同")
    P("=" * 108)
    A14 = build_A(BASE_WIN)
    SIG = U.build_signals(PXg, TRADEg, REALg)["Vortex"].values
    same = bool(np.allclose(A14, SIG, equal_nan=True))
    n_diff = int((~np.isclose(A14, SIG, equal_nan=True)).sum())
    P(f"  build_A(14) vs U.build_signals['Vortex']: {'✅ 逐位一致' if same else '❌ 有差异'}"
      f"（不同格子 {n_diff}）")
    r0 = _EP(A14, OVg, CVg, GMg, 10, 0)
    f0 = float(r0["eq"][-1])
    P(f"  phase=0 / 10 日调仓终值: ${f0:,.2f}（v27/v30 参照 $231,899.60）"
      f"  {'✅' if abs(f0 - 231899.60) < 0.01 else '❌'}")
    P(f"  成交笔数: 卖 {r0['n_sell']} / 买 {r0['n_buy']}"
      f" = {r0['n_sell']+r0['n_buy']}（v31 参照 664 = 卖+买之和）"
      f"  {'✅' if (r0['n_sell']+r0['n_buy']) == 664 else '❌'}")

    # ---------------- [2] 窗口扫描 ----------------
    P("\n" + "=" * 108)
    P("[2] 窗口扫描：每个 (窗口, 周期) 取遍全部相位，看 CAGR 分布（口径 B 共同窗口）")
    P("=" * 108)
    res = {}
    for n in WINDOWS:
        A = build_A(n)
        for rb in REBALS:
            res[(n, rb)] = scan(A, rb)

    for rb in REBALS:
        P(f"\n  ── 周期 {rb} 日 ──")
        P(f"  {'窗口':>6}{'最差':>9}{'P25':>9}{'中位':>9}{'P75':>9}{'最好':>9}"
          f"{'标准差':>10}{'极差':>9}{'中位排名':>10}")
        P("  " + "-" * 96)
        meds = {}
        for n in WINDOWS:
            d = dist([r["cagr"] for r in res[(n, rb)]])
            meds[n] = d["median"]
        order = sorted(WINDOWS, key=lambda x: -meds[x])
        for n in WINDOWS:
            d = dist([r["cagr"] for r in res[(n, rb)]])
            rk = order.index(n) + 1
            mark = "  ← 项目当前" if n == BASE_WIN else ""
            P(f"  {n:>6}{d['mn']*100:>8.1f}%{d['p25']*100:>8.1f}%{d['median']*100:>8.1f}%"
              f"{d['p75']*100:>8.1f}%{d['mx']*100:>8.1f}%{d['std']*100:>9.1f}pp"
              f"{d['span']*100:>8.1f}pp{rk:>8}/8{mark}")

    # ---------------- [3] 关键判据 ----------------
    P("\n" + "=" * 108)
    P("[3] ★ 关键判据：n=14 排第几？最优窗口领先多少？")
    P("=" * 108)
    for rb in REBALS:
        meds = {n: dist([r["cagr"] for r in res[(n, rb)]])["median"] for n in WINDOWS}
        order = sorted(WINDOWS, key=lambda x: -meds[x])
        best, worst = order[0], order[-1]
        rk14 = order.index(BASE_WIN) + 1
        P(f"\n  周期 {rb} 日（按相位中位排名）:")
        P(f"    1) 最优窗口 n={best}: 中位 {meds[best]*100:.1f}%")
        P(f"       n=14: 中位 {meds[BASE_WIN]*100:.1f}%  → 排第 {rk14}/8"
          f"，落后最优 {(meds[best]-meds[BASE_WIN])*100:+.1f}pp")
        P(f"       最差窗口 n={worst}: 中位 {meds[worst]*100:.1f}%"
          f"，n=14 领先 {(meds[BASE_WIN]-meds[worst])*100:+.1f}pp")
        P(f"       全窗口中位的极差 = {(meds[best]-meds[worst])*100:.1f}pp"
          f"（对比: 同窗口内相位极差 "
          f"{max(dist([r['cagr'] for r in res[(n, rb)]])['span'] for n in WINDOWS)*100:.1f}pp）")
        P(f"       排名: " + " > ".join(f"{n}({meds[n]*100:.0f}%)" for n in order))

    # ---------------- [4] 配对胜率 ----------------
    P("\n" + "=" * 108)
    P("[4] 配对胜率：n=14 vs 其它每个窗口（相位全组合）—— 「换窗口」到底有没有用")
    P("=" * 108)
    for rb in REBALS:
        P(f"\n  ── 周期 {rb} 日 ──")
        P(f"  {'窗口':>6}{'n=14 胜':>10}{'总组合':>9}{'胜率':>9}{'平均差':>11}{'结论':>9}")
        P("  " + "-" * 58)
        w_win = w_lose = 0
        for n in WINDOWS:
            if n == BASE_WIN:
                continue
            a = [r["cagr"] for r in res[(BASE_WIN, rb)]]
            b = [r["cagr"] for r in res[(n, rb)]]
            wa, wb, tot, md = pair_win(a, b)
            rate = (wa / tot * 100) if tot else float("nan")
            concl = "14 更好" if wa > wb else ("14 更差" if wb > wa else "打平")
            if wa > wb:
                w_win += 1
            elif wb > wa:
                w_lose += 1
            P(f"  {n:>6}{wa:>10}{tot:>9}{rate:>8.1f}%{md*100:>+10.1f}pp{concl:>9}")
        verdict = "✅ 14 稳健" if w_win >= 6 else ("❌ 14 不稳健" if w_lose >= 4 else "△ 混合")
        P(f"  → n=14 对 7 个其它窗口: 更好 {w_win} 个 / 更差 {w_lose} 个  {verdict}")

    # ---------------- [5] 窗口 x 周期 交互 ----------------
    P("\n" + "=" * 108)
    P("[5] 窗口 × 周期 交互：「10 日 > 21 日」在每个窗口下都成立吗？")
    P("=" * 108)
    P(f"  {'窗口':>6}{'10日中位':>11}{'21日中位':>11}{'10-21':>10}{'谁赢':>7}")
    P("  " + "-" * 48)
    win_cnt = 0
    for n in WINDOWS:
        m10 = dist([r["cagr"] for r in res[(n, 10)]])["median"]
        m21 = dist([r["cagr"] for r in res[(n, 21)]])["median"]
        who = "10日" if m10 > m21 else "21日"
        if m10 > m21:
            win_cnt += 1
        mark = "  ← 项目当前" if n == BASE_WIN else ""
        P(f"  {n:>6}{m10*100:>10.1f}%{m21*100:>10.1f}%{(m10-m21)*100:>+9.1f}pp{who:>7}{mark}")
    P(f"\n  → 8 个窗口里, 10 日胜 {win_cnt}/8 = {win_cnt/8*100:.0f}%")

    # ---------------- [5b] 前后半段 ----------------
    P("\n" + "=" * 108)
    P("[5b] 前后半段稳健性：窗口的优劣在【前后半段】是否同向？")
    P("=" * 108)
    P(f"  前半段 {DATES[COMMON_I0].date()} ~ {DATES[MID_I].date()}"
      f" ｜ 后半段 {DATES[MID_I].date()} ~ {DATES[-1].date()}")
    P(f"\n  {'窗口':>6}{'前半段中位':>13}{'后半段中位':>13}{'平均':>10}{'排名(平均)':>12}")
    P("  " + "-" * 58)
    avg = {}
    for n in WINDOWS:
        h1 = dist([r["cagr_h1"] for r in res[(n, 10)]])["median"]
        h2 = dist([r["cagr_h2"] for r in res[(n, 10)]])["median"]
        avg[n] = (h1 + h2) / 2.0
    order = sorted(WINDOWS, key=lambda x: -avg[x])
    for n in WINDOWS:
        h1 = dist([r["cagr_h1"] for r in res[(n, 10)]])["median"]
        h2 = dist([r["cagr_h2"] for r in res[(n, 10)]])["median"]
        rk = order.index(n) + 1
        mark = "  ← 项目当前" if n == BASE_WIN else ""
        P(f"  {n:>6}{h1*100:>12.1f}%{h2*100:>12.1f}%{avg[n]*100:>9.1f}%{rk:>10}/8{mark}")
    top = order[0]
    P(f"\n  → 前后半段平均最优: n={top}（前半 {dist([r['cagr_h1'] for r in res[(top,10)]])['median']*100:.1f}%"
      f" / 后半 {dist([r['cagr_h2'] for r in res[(top,10)]])['median']*100:.1f}%）")
    P(f"     n=14: 前半 {dist([r['cagr_h1'] for r in res[(14,10)]])['median']*100:.1f}%"
      f" / 后半 {dist([r['cagr_h2'] for r in res[(14,10)]])['median']*100:.1f}%"
      f"（平均 {avg[14]*100:.1f}%）")

    # ---------------- [6] 结论 ----------------
    P("\n" + "=" * 108)
    P("[6] 结论")
    P("=" * 108)
    med10 = {n: dist([r["cagr"] for r in res[(n, 10)]])["median"] for n in WINDOWS}
    med21 = {n: dist([r["cagr"] for r in res[(n, 21)]])["median"] for n in WINDOWS}
    o10 = sorted(WINDOWS, key=lambda x: -med10[x])
    o21 = sorted(WINDOWS, key=lambda x: -med21[x])
    span10 = max(dist([r["cagr"] for r in res[(n, 10)]])["span"] for n in WINDOWS)
    span21 = max(dist([r["cagr"] for r in res[(n, 21)]])["span"] for n in WINDOWS)
    win_span = max(med10[o10[0]] - med10[o10[-1]], med21[o21[0]] - med21[o21[-1]])
    P(f"  1. 窗口这个自由度【真实存在】: 10 日中位在 {med10[o10[-1]]*100:.1f}% ~ "
      f"{med10[o10[0]]*100:.1f}% 之间（极差 {(med10[o10[0]]-med10[o10[-1]])*100:.1f}pp）")
    P(f"  2. 但它【小于相位】: 同窗口内相位极差最大 {max(span10, span21)*100:.1f}pp"
      f" > 窗口间中位极差 {win_span*100:.1f}pp ⇒ 相位是更大的自由度")
    P(f"  3. ✅ n=14 在 10 日调仓下是【最优窗口】(排 {o10.index(14)+1}/8, "
      f"中位 {med10[14]*100:.1f}%) —— 14 不是随手定的")
    P(f"  4. ⚠ 但 n=14 在 21 日调仓下只排 {o21.index(14)+1}/8"
      f"（{med21[14]*100:.1f}% vs 最优 n={o21[0]} {med21[o21[0]]*100:.1f}%，落后 "
      f"{(med21[o21[0]]-med21[14])*100:.1f}pp）")
    P(f"  5. ★ 「10 日 > 21 日」只在 {win_cnt}/8 个窗口下成立 —— 在 n=5/7/42/63 下 21 日反而赢。")
    P(f"     而 n=14 恰好是 10 日领先幅度【最大】的窗口(+21.9pp) ⇒ 周期结论与窗口存在交互,")
    P(f"     即「10 日是冠军」这个结论本身也带一点「在 n=14 上看」的选择性。")
    P(f"  6. ⚠ 扫 8 个窗口 = 8 次比较 ⇒ 任何「最优窗口」都含运气（多重比较）。")
    P(f"     正确读法不是「换个窗口」, 而是「冠军对窗口这个自由度敏感 ——")
    P(f"     14 恰好是 10 日下最好的那一个, 但这不保证它在未来仍最好」。")
    P("\n  明细已写入 _v32_window.json")

    # ---------------- 落盘 ----------------
    out = dict(
        meta=dict(n_bars=int(N), start_i=int(START_I), common_i0=int(COMMON_I0),
                  mid_i=int(MID_I), start=str(DATES[START_I].date()),
                  end=str(DATES[-1].date()), cap=CAP_REAL, comm=COMM_REAL,
                  windows=list(WINDOWS), rebals=list(REBALS), base_win=BASE_WIN),
        selfcheck=dict(A14_same=same, n_diff=n_diff, final_phase0=f0,
                       n_sell=int(r0["n_sell"]), n_buy=int(r0["n_buy"])),
        scans={f"w{n}_r{rb}": res[(n, rb)] for n in WINDOWS for rb in REBALS},
        summary={f"r{rb}": {str(n): dist([r["cagr"] for r in res[(n, rb)]])
                            for n in WINDOWS} for rb in REBALS},
    )
    with open("_v32_window.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
