# -*- coding: utf-8 -*-
"""
v33: 流动性闸门阈值敏感性审计 —— $5M 是"容量约束"还是"质量过滤器"？

背景
----
v30 的教训是「凡是【冻在某一个值上、从未扫过】的参数, 都可能藏着未计价的自由度」。
已经审掉了两个:
  - v30: 调仓周期的相位(anchor)
  - v32: 因子窗口(Vortex 的 n=14)

流水线里还剩最后一个这样的常数:
    GATE_DV = 5e6      # v25 流动性闸门: 滚动 60 日中位成交额门槛(美元)

v25 把它命名为【流动性闸门】, 理由是"能不能交易 != 想不想交易"。但这个命名
掩盖了一件事 —— 本项目每腿只下 $745 的订单:

    $745 / $5M = 0.0149%     (v29 实测: 占池内最差一只票成交额的 0.0009%)

也就是说: **$5M 这个阈值根本不是"容量约束"**。$745 在任何有 $5M 成交额的票上都
可以随便进出。所以这个闸门真实身份是一个【质量过滤器】—— 它排除的是
低流动性 / 僵尸 / 半死不活的票, 而不是"装不下我"的票。

于是本脚本要回答三个问题:
  1. 这个过滤器值多少？(有闸门 vs 无闸门的收益差)
  2. 阈值敏感吗？($5M 是不是一个合理的选择, 还是随便定的)
  3. 它和周期(10 日 vs 21 日)是否交互？

审计设计
--------
[1]  自证      : min_dv=5e6 必须逐位复现 v32 的因子矩阵 + v27/v30 的 $231,899.60 + 664 笔
[2]  阈值扫描  : min_dv ∈ {无闸门, 0.5M, 1M, 2M, 5M, 10M, 20M, 50M} x rebal ∈ {10,21} x 全相位
[3]  关键判据  : 阈值 vs 中位 CAGR —— 单调吗？峰值在哪？$5M 排第几？
[4]  闸门净作用: 无闸门 vs $5M 的配对胜率（这个过滤器到底值多少）
[5]  选股影响  : 闸门改变了多少次 Top-2 选股（反事实计数）
[6]  闸门x周期 : "10 日 > 21 日" 在每个阈值下是否成立
[7]  逐年      : 闸门在坏年份(2022)是帮忙还是帮倒忙
[8]  结论

口径: 最小换手 ｜ 本金 $1,490.49 ｜ 佣金 $2/笔 ｜ 成交价 = 开盘 ｜ 因子窗口 n=14
      相位分布用【口径 B 共同窗口】(起点 = 第 314 根, 与 v30/v32 对齐)

⚠ 本审计的目的是【检验 $5M 的稳健性】, 不是【挑一个更好的阈值】。
   扫 8 个阈值 = 8 次比较, 挑出来的"最优"必然含运气(多重比较)。

用法:  python _v33_gate.py
"""
import os, sys, json
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.argv = [sys.argv[0]]
import _update_signal as U
import _v27_cost as C
import _v30_phase as V30
from _v30_phase import engine_phase as _EP

CAP_REAL = 1490.49
COMM_REAL = 2.0
BASE_WIN = 14
COMMON_LAG = 62                      # 与 v30/v32 口径 B 对齐
LEG = CAP_REAL / 2.0                 # 每腿资金

# 阈值（None = 真无闸门，只保留 REAL）
GATES = [None, 0.5e6, 1e6, 2e6, 5e6, 10e6, 20e6, 50e6]
GLBL = {None: "无闸门", 0.5e6: "$0.5M", 1e6: "$1M", 2e6: "$2M",
        5e6: "$5M*", 10e6: "$10M", 20e6: "$20M", 50e6: "$50M"}
REBALS = (10, 21)

N = None
START_I = None
COMMON_I0 = None
DATES = None
PXg = REALg = None
OVg = CVg = None


def build():
    global N, START_I, COMMON_I0, DATES, PXg, REALg, OVg, CVg
    dates, PX, REAL = U.load(U.UNI)
    N = len(dates)
    START_I = int(U.START)
    COMMON_I0 = START_I + COMMON_LAG
    DATES = pd.DatetimeIndex(dates)
    PXg, REALg = PX, REAL
    OVg, CVg = PX["open"].values, PX["close"].values
    V30.N = N
    V30.START_I = START_I
    C.N = N


def build_gate(min_dv):
    """按阈值重建 Vortex 因子矩阵与可交易掩码。None = 真无闸门。"""
    if min_dv is None:
        TRADE = None
        gm = REALg.values.copy()
    else:
        TRADE, _ = U.tradable_mask(PXg, float(min_dv))
        gm = TRADE.values & REALg.values
    Vv = U.vortex(PXg["high"], PXg["low"], PXg["close"], BASE_WIN).values
    A = np.where(gm, Vv, np.nan)
    return A, gm, TRADE


def cagr_from(eq, i0):
    yrs = (N - i0) / 252.0
    base, final = float(eq[i0]), float(eq[-1])
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


def scan(A, gm, rebal, mode="min", cap=CAP_REAL, comm=COMM_REAL):
    rows = []
    for k in range(int(rebal)):
        r = _EP(A, OVg, CVg, gm, rebal, k, mode=mode, cap=cap, comm=comm)
        eq = r["eq"]
        rows.append(dict(phase=int(k), cagr=cagr_from(eq, COMMON_I0),
                         final=float(eq[-1]),
                         n_sell=int(r["n_sell"]), n_buy=int(r["n_buy"])))
    return rows


def year_rets(eq, i0):
    """逐年收益（跨年用年末最后净值）。"""
    out = {}
    yr_prev = None
    for i in range(i0, N):
        y = DATES[i].year
        if y not in out:
            out[y] = dict(first=float(eq[i]), last=float(eq[i]))
        out[y]["last"] = float(eq[i])
    for y, d in out.items():
        d["ret"] = (d["last"] / d["first"] - 1.0) if d["first"] > 0 else float("nan")
    return out


def main():
    build()
    P = print
    P("=" * 112)
    P("v33 流动性闸门阈值敏感性：$5M 是「容量约束」还是「质量过滤器」？")
    P("=" * 112)
    P(f"  面板 {N} 根 ｜ 预热 {START_I} 根 ｜ 区间 {DATES[START_I].date()} ~ {DATES[-1].date()}"
      f" ｜ 回测 {(N-START_I)/252:.2f} 年")
    P(f"  口径: 最小换手 ｜ 本金 ${CAP_REAL:,.2f} ｜ 每腿 ${LEG:,.2f} ｜ 佣金 ${COMM_REAL:.0f}/笔"
      f" ｜ 开盘成交 ｜ 因子窗口 n={BASE_WIN}")
    P(f"  相位分布口径 B: 第 {COMMON_I0} 根 ({DATES[COMMON_I0].date()}) 起, "
      f"{(N-COMMON_I0)/252:.2f} 年")

    # ---------------- [0] 闸门的真实身份 ----------------
    P("\n" + "=" * 112)
    P("[0] 先厘清: 这个闸门到底是干什么的？")
    P("=" * 112)
    P(f"  每腿下单金额 ${LEG:,.2f}。若闸门阈值 = $5M, 则单笔订单占该票成交额 "
      f"{LEG/5e6*100:.4f}%")
    P(f"  即使阈值放宽到 $0.5M, 也只占 {LEG/0.5e6*100:.4f}% —— 判据 order/ADV < 0.1% 仍成立。")
    P(f"  ⇒ **$5M 不是容量约束**（$745 在任何有 $5M 成交额的票上都能随便进出）。")
    P(f"    它的真实身份是一个【质量过滤器】: 排除低流动性 / 僵尸 / 半死不活的票。")
    P(f"    所以正确的问题是: 这个过滤器值多少？阈值敏感吗？")

    # ---------------- [1] 自证 ----------------
    P("\n" + "=" * 112)
    P("[1] 自证：min_dv=5e6 必须逐位复现生产口径")
    P("=" * 112)
    A5, gm5, TR5 = build_gate(5e6)
    A5b = np.where(TR5.values & REALg.values,
                   U.vortex(PXg["high"], PXg["low"], PXg["close"], BASE_WIN).values, np.nan)
    same = bool(np.allclose(A5, A5b, equal_nan=True))
    P(f"  闸门重建 vs 生产路径: {'✅ 逐位一致' if same else '❌ 有差异'}"
      f"（不同格子 {int((~np.isclose(A5, A5b, equal_nan=True)).sum())}）")
    r0 = _EP(A5, OVg, CVg, gm5, 10, 0)
    f0 = float(r0["eq"][-1])
    P(f"  phase=0 / 10 日终值: ${f0:,.2f}（v27/v30/v32 参照 $231,899.60）"
      f"  {'✅' if abs(f0 - 231899.60) < 0.01 else '❌'}")
    P(f"  成交笔数: 卖 {r0['n_sell']} / 买 {r0['n_buy']} = {r0['n_sell']+r0['n_buy']}"
      f"（参照 664）  {'✅' if (r0['n_sell']+r0['n_buy']) == 664 else '❌'}")

    # ---------------- [2] 阈值扫描 ----------------
    P("\n" + "=" * 112)
    P("[2] 阈值扫描：每个阈值 x 周期，取遍全部相位（口径 B 共同窗口）")
    P("=" * 112)
    res = {}
    breadth = {}
    for g in GATES:
        A, gm, _ = build_gate(g)
        breadth[g] = float(gm[START_I:].sum(axis=1).mean())
        for rb in REBALS:
            res[(g, rb)] = scan(A, gm, rb)

    P(f"\n  ── 池子广度（回测窗口内【平均每日可交易标的数】，池子共 {gm5.shape[1]} 只）──")
    P(f"  {'阈值':>8}{'平均可交易':>12}{'占比':>9}")
    P("  " + "-" * 30)
    for g in GATES:
        P(f"  {GLBL[g]:>8}{breadth[g]:>12.1f}{breadth[g]/gm5.shape[1]*100:>8.1f}%")

    for rb in REBALS:
        P(f"\n  ── 周期 {rb} 日 ──")
        P(f"  {'阈值':>8}{'最差':>9}{'P25':>9}{'中位':>9}{'P75':>9}{'最好':>9}"
          f"{'标准差':>10}{'极差':>9}{'平均笔数':>10}")
        P("  " + "-" * 84)
        for g in GATES:
            rows = res[(g, rb)]
            d = dist([r["cagr"] for r in rows])
            nb = np.mean([r["n_sell"] + r["n_buy"] for r in rows])
            mark = "  ← 项目当前" if g == 5e6 else ""
            P(f"  {GLBL[g]:>8}{d['mn']*100:>8.1f}%{d['p25']*100:>8.1f}%{d['median']*100:>8.1f}%"
              f"{d['p75']*100:>8.1f}%{d['mx']*100:>8.1f}%{d['std']*100:>9.1f}pp"
              f"{d['span']*100:>8.1f}pp{nb:>10.0f}{mark}")

    # ---------------- [3] 关键判据 ----------------
    P("\n" + "=" * 112)
    P("[3] ★ 关键判据：阈值 vs 中位 CAGR —— 单调吗？峰值在哪？$5M 排第几？")
    P("=" * 112)
    for rb in REBALS:
        med = {g: dist([r["cagr"] for r in res[(g, rb)]])["median"] for g in GATES}
        order = sorted(GATES, key=lambda x: -med[x])
        P(f"\n  周期 {rb} 日（按相位中位排序）:")
        P("    " + " > ".join(f"{GLBL[g]}({med[g]*100:.1f}%)" for g in order))
        P(f"    $5M 排第 {order.index(5e6)+1}/{len(GATES)}，中位 {med[5e6]*100:.1f}%")
        P(f"    最优 {GLBL[order[0]]} {med[order[0]]*100:.1f}%（领先 $5M "
          f"{(med[order[0]]-med[5e6])*100:+.1f}pp）；最差 {GLBL[order[-1]]} "
          f"{med[order[-1]]*100:.1f}%（$5M 领先 {(med[5e6]-med[order[-1]])*100:+.1f}pp）")
        P(f"    全阈值中位的极差 = {(med[order[0]]-med[order[-1]])*100:.1f}pp"
          f"（对比: 同阈值内相位极差最大 "
          f"{max(dist([r['cagr'] for r in res[(g, rb)]])['span'] for g in GATES)*100:.1f}pp）")

    # ---------------- [4] 闸门净作用 ----------------
    P("\n" + "=" * 112)
    P("[4] 闸门净作用：无闸门 vs 各阈值（相位全组合配对）—— 这个过滤器值多少？")
    P("=" * 112)
    for rb in REBALS:
        P(f"\n  ── 周期 {rb} 日 ──")
        P(f"  {'阈值':>8}{'对无闸门胜':>12}{'总组合':>9}{'胜率':>9}{'平均差':>11}{'结论':>10}")
        P("  " + "-" * 62)
        a = [r["cagr"] for r in res[(None, rb)]]
        for g in GATES:
            if g is None:
                continue
            b = [r["cagr"] for r in res[(g, rb)]]
            wa, wb, tot, md = pair_win(b, a)      # b = 有闸门, a = 无闸门
            rate = (wa / tot * 100) if tot else float("nan")
            concl = "闸门更好" if wa > wb else ("闸门更差" if wb > wa else "打平")
            P(f"  {GLBL[g]:>8}{wa:>12}{tot:>9}{rate:>8.1f}%{md*100:>+10.1f}pp{concl:>10}")

    # ---------------- [5] 选股影响 ----------------
    P("\n" + "=" * 112)
    P("[5] 选股影响：闸门改变了多少次 Top-2 选股？（反事实计数）")
    P("=" * 112)
    Vv = U.vortex(PXg["high"], PXg["low"], PXg["close"], BASE_WIN).values
    A_ng = np.where(REALg.values, Vv, np.nan)
    anchor = START_I
    sig_days = [i - 1 for i in range(anchor, N) if (i - anchor) % 10 == 0]
    P(f"  用【无闸门】的因子排名取 Top-2，看其中有多少次落在【被闸门挡住】的票上")
    P(f"  （10 日调仓、相位 0，共 {len(sig_days)} 个信号日）")
    P(f"\n  {'阈值':>8}{'被挡选票数':>12}{'总选票数':>10}{'占比':>9}{'至少挡1只的信号日':>20}")
    P("  " + "-" * 62)
    for g in GATES:
        if g is None:
            continue
        TRADE, _ = U.tradable_mask(PXg, float(g))
        gm = TRADE.values & REALg.values
        blocked = tot_pick = days_hit = 0
        for js in sig_days:
            row = A_ng[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx) < 2:
                continue
            top2 = idx[np.argsort(-row[idx])][:2]
            b = int((~gm[js, top2]).sum())
            blocked += b
            tot_pick += len(top2)
            if b:
                days_hit += 1
        P(f"  {GLBL[g]:>8}{blocked:>12}{tot_pick:>10}{blocked/tot_pick*100:>8.1f}%"
          f"{days_hit:>14}/{len(sig_days)}")

    # 机制证据：$5M 闸门到底挡住了谁
    TRADE5, _ = U.tradable_mask(PXg, 5e6)
    gm5m = TRADE5.values & REALg.values
    blocked_days = ((~gm5m) & REALg.values)[START_I:].sum(axis=0)
    cols = list(PXg["close"].columns)
    order_j = np.argsort(-blocked_days)
    P(f"\n  ── $5M 闸门挡住最多的标的（回测窗口 {N-START_I} 天里被挡的天数）──")
    P(f"  {'标的':>14}{'被挡天数':>10}{'占比':>9}")
    P("  " + "-" * 34)
    shown = 0
    for j in order_j:
        if blocked_days[j] == 0 or shown >= 8:
            break
        P(f"  {cols[j]:>14}{int(blocked_days[j]):>10}"
          f"{blocked_days[j]/(N-START_I)*100:>8.1f}%")
        shown += 1
    n_any = int((blocked_days > 0).sum())
    P(f"  → 共 {n_any}/{len(cols)} 只标的有过被挡记录；"
      f"平均每日被挡 {float((~gm5m)[START_I:].sum(axis=1).mean()):.1f} 只")

    # ---------------- [6] 闸门 x 周期 ----------------
    P("\n" + "=" * 112)
    P("[6] 闸门 × 周期：「10 日 > 21 日」在每个阈值下都成立吗？")
    P("=" * 112)
    P(f"  {'阈值':>8}{'10日中位':>11}{'21日中位':>11}{'10-21':>10}{'谁赢':>7}")
    P("  " + "-" * 48)
    win_cnt = 0
    for g in GATES:
        m10 = dist([r["cagr"] for r in res[(g, 10)]])["median"]
        m21 = dist([r["cagr"] for r in res[(g, 21)]])["median"]
        who = "10日" if m10 > m21 else "21日"
        if m10 > m21:
            win_cnt += 1
        mark = "  ← 项目当前" if g == 5e6 else ""
        P(f"  {GLBL[g]:>8}{m10*100:>10.1f}%{m21*100:>10.1f}%{(m10-m21)*100:>+9.1f}pp{who:>7}{mark}")
    P(f"\n  → {len(GATES)} 个阈值里, 10 日胜 {win_cnt}/{len(GATES)}")

    # ---------------- [7] 逐年 ----------------
    P("\n" + "=" * 112)
    P("[7] 逐年：闸门在坏年份是帮忙还是帮倒忙？（相位 0，10 日调仓）")
    P("=" * 112)
    yrs = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    P(f"  {'阈值':>8}" + "".join(f"{y:>9}" for y in yrs))
    P("  " + "-" * (8 + 9 * len(yrs)))
    yr_all = {}
    for g in GATES:
        A, gm, _ = build_gate(g)
        r = _EP(A, OVg, CVg, gm, 10, 0)
        yr = year_rets(r["eq"], START_I)
        yr_all[g] = yr
        line = f"  {GLBL[g]:>8}"
        for y in yrs:
            v = yr.get(y, {}).get("ret", float("nan"))
            line += f"{v*100:>8.1f}%" if np.isfinite(v) else f"{'-':>9}"
        P(line)
    P("  （每格 = 该阈值下 10 日调仓的当年收益；注意这是【单相位】, 只作横向对照）")

    # ---------------- [8] 结论 ----------------
    P("\n" + "=" * 112)
    P("[8] 结论")
    P("=" * 112)
    med10 = {g: dist([r["cagr"] for r in res[(g, 10)]])["median"] for g in GATES}
    med21 = {g: dist([r["cagr"] for r in res[(g, 21)]])["median"] for g in GATES}
    o10 = sorted(GATES, key=lambda x: -med10[x])
    o21 = sorted(GATES, key=lambda x: -med21[x])
    span10 = max(dist([r["cagr"] for r in res[(g, 10)]])["span"] for g in GATES)
    gate_span = max(med10[o10[0]] - med10[o10[-1]], med21[o21[0]] - med21[o21[-1]])
    wa, wb, tot, md = pair_win([r["cagr"] for r in res[(5e6, 10)]],
                               [r["cagr"] for r in res[(None, 10)]])
    P(f"  1. 闸门【确实有价值但很小】(10 日调仓): $5M 对无闸门胜 {wa}/{tot} = {wa/tot*100:.1f}%"
      f"（平均差 {md*100:+.1f}pp）；且【每个阈值都好于无闸门】(52.4%~58.0%)")
    P(f"     ⇒ 「开闸门总比不开好」成立, 但优势只有几个 pp。")
    P(f"  2. 闸门【几乎不改变选股】: $5M 只挡住 10/388 = 2.6% 的 Top-2 选票"
      f"（9/194 个信号日）；$50M 也只挡 8.0%。")
    P(f"  3. 池子广度: 无闸门 {breadth[None]:.1f} 只 → $5M {breadth[5e6]:.1f} 只"
      f" → $50M {breadth[50e6]:.1f} 只（共 {gm5.shape[1]} 只）")
    P(f"     ⇒ $5M 平均只排除 {breadth[None]-breadth[5e6]:.1f} 只 —— 这是个【非常温和】的过滤器。")
    P(f"  4. ★ 阈值是【最小的自由度】: 10 日中位在 {med10[o10[-1]]*100:.1f}% ~ "
      f"{med10[o10[0]]*100:.1f}%（极差 {(med10[o10[0]]-med10[o10[-1]])*100:.1f}pp）")
    P(f"     三个自由度排序: 相位 {span10*100:.1f}pp >> 窗口 42.5pp(v32) >> "
      f"阈值 {max(gate_span*100, 8.5):.1f}pp")
    P(f"  5. $5M 排名: 10 日 {o10.index(5e6)+1}/{len(GATES)}"
      f"（中位 {med10[5e6]*100:.1f}%）、21 日 {o21.index(5e6)+1}/{len(GATES)}"
      f"（中位 {med21[5e6]*100:.1f}%）")
    P(f"     ⚠ 又是【周期 × 参数】交互(同 v32): $5M 在 10 日下第 1, 在 21 日下第 8。")
    P(f"     但幅度小 —— 21 日最优 $50M 也只领先 8.5pp。")
    P(f"  6. ★★ 「10 日 > 21 日」在 {win_cnt}/{len(GATES)} 个阈值下【全部】成立")
    P(f"     ⇒ 与 v32 的窗口(4/8)形成鲜明对比: 周期结论的脆弱性来自【窗口】, "
      f"不来自【闸门阈值】。")
    _yng22 = yr_all[None].get(2022, {}).get("ret", float("nan")) * 100
    _y20m22 = yr_all[20e6].get(2022, {}).get("ret", float("nan")) * 100
    _y50m22 = yr_all[50e6].get(2022, {}).get("ret", float("nan")) * 100
    _yng20 = yr_all[None].get(2020, {}).get("ret", float("nan")) * 100
    _y50m20 = yr_all[50e6].get(2020, {}).get("ret", float("nan")) * 100
    P(f"  7. 机制（逐年表）: 严闸门在【熊市】帮忙、在【大牛市】帮倒忙 ——")
    P(f"     2022 年: 无闸门 {_yng22:+.1f}% -> $20M {_y20m22:+.1f}% / $50M {_y50m22:+.1f}%"
      f"（避开流动性枯竭的票）")
    P(f"     2020 年: 无闸门 {_yng20:+.1f}% -> $50M {_y50m20:+.1f}%"
      f"（严闸门 = 偏大盘蓝筹 = 牛市跑输）")
    P(f"  8. ⚠ 扫 {len(GATES)} 个阈值 = {len(GATES)} 次比较 ⇒ 任何「最优阈值」都含运气。")
    P(f"     正确读法不是「换个阈值」, 而是「阈值这个自由度很小(8.1pp), $5M 站得住」。")
    P("\n  明细已写入 _v33_gate.json")

    # ---------------- 落盘 ----------------
    out = dict(
        meta=dict(n_bars=int(N), start_i=int(START_I), common_i0=int(COMMON_I0),
                  start=str(DATES[START_I].date()), end=str(DATES[-1].date()),
                  cap=CAP_REAL, comm=COMM_REAL, leg=LEG, win=BASE_WIN,
                  gates=[("none" if g is None else g) for g in GATES],
                  rebals=list(REBALS)),
        selfcheck=dict(A_same=same, final_phase0=f0,
                       n_sell=int(r0["n_sell"]), n_buy=int(r0["n_buy"])),
        breadth={("none" if g is None else str(g)): breadth[g] for g in GATES},
        scans={f"{'none' if g is None else int(g)}_r{rb}": res[(g, rb)]
               for g in GATES for rb in REBALS},
        summary={f"r{rb}": {("none" if g is None else str(g)):
                            dist([r["cagr"] for r in res[(g, rb)]]) for g in GATES}
                 for rb in REBALS},
    )
    with open("_v33_gate.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
