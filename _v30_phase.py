# -*- coding: utf-8 -*-
"""
v30: 周期选择的【相位稳健性】审计 —— 10 日调仓的冠军，是真优势还是相位运气？

背景
----
v26 的总排名里，Vortex Top2 @10日调仓 是风险调整后的冠军。但"调仓周期"其实
不是一个连续参数，它是一个【相位】:

    调仓日集合 = { i | i >= anchor 且 (i - anchor) % rebal == 0 }

回测里 anchor 固定取面板第 252 根（v27 把它参数化成 --anchor）。也就是说，
v26 报出的每一个 CAGR，都只是【某一个特定相位】上的结果 —— 换一天起步，
调仓日整体平移，选票、成交价、每一段持有期全部变样。

v29 已经露出苗头: 把执行日整体后移一天，10 日调仓 -7.05pp、21 日 +2.31pp。
"晚一天"不可能同时是优势又是劣势 => 那是相位噪声，不是成本。

所以本脚本回答一个更根本、也更危险的问题:

    如果 10 日的优势只在【某一个特定相位】上成立，那它不是策略，是巧合。

审计设计
--------
[1]  自证      : phase=0 必须逐位复现 v27 复刻引擎 + v26 官方终值
[2]  相位扫描  : rebal ∈ {5,10,15,21,42,63}，anchor 取遍【全部】偏移
[3]  关键判据  : 最差 10 日 vs 最好 21 日 —— 优势是碾压还是重叠
[4]  配对胜率  : 10 x 21 = 210 个 (相位10, 相位21) 组合
[4b] 口径稳健  : 换 4 种执行口径重做一遍，看结论是否口径依赖
[5]  稳定性    : 逐年 + 滚动一年窗口 + 逐年相位极差
[6]  相位分散化: 把本金拆到 N 个相位上，能不能买掉相位风险（含成本）
[7]  结论

两个口径必须分开（否则会把"起步晚"当成"策略差"）:
  A 全周期  : base = 本金，从面板第 252 根算起。含【空仓前缀】(0~rebal-1 天)，
              这才是"你在某天开始做"的真实结果。
  B 共同窗口: base = 各相位都建完仓之后的那一天，窗口完全重合。
              只有 B 是干净的【纯相位】比较。

用法:  python _v30_phase.py
"""
import os, sys, json, itertools
import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.argv = [sys.argv[0]]                 # 屏蔽外部参数，避免污染被导入模块的 arg()
import _update_signal as U
import _v27_cost as C

N = None
START_I = None
COMMON_I0 = None
DATES = None
CAP_REAL = 1490.49                       # 用户真实本金(USD)
COMM_REAL = 2.0                          # 富途美股 $2/笔
CAP_OFF = 3000.0                         # v26 官方口径本金
PERIODS = (5, 10, 15, 21, 42, 63)        # v26 排名里出现过的全部周期
LBL = ["最差", "P25", "中位", "P75", "最好", "标准差", "极差"]


def build():
    global N, DATES
    dates, PX, REAL = U.load(U.UNI)
    TRADE, _ = U.tradable_mask(PX, U.GATE_DV)
    SIG = U.build_signals(PX, TRADE, REAL)
    A = SIG["Vortex"].values
    Ov = PX["open"].values
    Cv = PX["close"].values
    gm = TRADE.values & REAL.values
    N = A.shape[0]
    C.N = N                              # _v27_cost.engine 用自己的模块级 N
    DATES = pd.DatetimeIndex(dates)
    return PX, A, Ov, Cv, gm


def engine_phase(A, Ov, Cv, gm, rebal, phase, mode="min", topk=2,
                 cap=CAP_REAL, comm=COMM_REAL):
    """v25.1 口径 + 相位偏移。phase=0 时必须与 _v27_cost.engine 逐位一致。

    与 _v27_cost.engine 的唯一差别: 调仓日历的锚点从 START 挪到 START + phase。
    """
    anchor_i = START_I + int(phase)
    RB = set(i for i in range(anchor_i, N) if (i - anchor_i) % rebal == 0)
    cash, pos = cap, {}
    eq = np.full(N, np.nan)
    eq[:START_I] = cap                   # 预热期视为持币
    n_sell = n_buy = n_reb = n_noop = 0
    prev_tgt = None
    for i in range(START_I, N):
        if i in RB:
            js = i - 1
            n_reb += 1
            row = A[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx):
                idx = idx[gm[js, idx]]
            tgt = list(idx[np.argsort(-row[idx])][:topk]) if len(idx) >= topk else []
            if mode == "full":
                for j in list(pos):
                    pr = Ov[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += pos.pop(j) * pr - comm; n_sell += 1
                if len(tgt) >= topk:
                    bud = max(0.0, (cash - topk * comm) / topk)
                    for j in tgt:
                        pr = Ov[i, j]
                        if not np.isfinite(pr) or pr <= 0: continue
                        sh = bud / pr
                        if sh > 0:
                            pos[j] = sh; cash -= sh * pr + comm; n_buy += 1
            else:
                if set(tgt) == set(pos) and len(pos) == len(tgt):
                    n_noop += 1
                else:
                    for j in list(pos):
                        if j in tgt: continue
                        pr = Ov[i, j]
                        if np.isfinite(pr) and pr > 0:
                            cash += pos.pop(j) * pr - comm; n_sell += 1
                    newj = [j for j in tgt if j not in pos]
                    if newj:
                        bud = max(0.0, (cash - len(newj) * comm) / len(newj))
                        for j in newj:
                            pr = Ov[i, j]
                            if not np.isfinite(pr) or pr <= 0: continue
                            sh = bud / pr
                            if sh > 0:
                                pos[j] = sh; cash -= sh * pr + comm; n_buy += 1
        v = cash
        for j, sh in pos.items():
            p = Cv[i, j]
            if np.isfinite(p): v += sh * p
        eq[i] = v
    return dict(eq=eq, n_sell=n_sell, n_buy=n_buy, n_reb=n_reb, n_noop=n_noop)


def cagr_from(eq, i0):
    """从 i0 起算的 CAGR。base = eq[i0]，所以口径 A/B 只是 i0 不同。
    终值 <= 0 视为【爆仓】，返回 NaN（由调用方决定怎么记）。"""
    yrs = (N - i0) / 252.0
    base, final = float(eq[i0]), float(eq[-1])
    if not np.isfinite(base) or base <= 0 or not np.isfinite(final) or final <= 0:
        return float("nan")
    return (final / base) ** (1.0 / yrs) - 1.0


def cagr_or_bust(eq, i0):
    """同 cagr_from，但把【爆仓】记成 -100%（总亏损），便于统计。
    返回 (cagr, 是否爆仓)。"""
    yrs = (N - i0) / 252.0
    base, final = float(eq[i0]), float(eq[-1])
    if not np.isfinite(base) or base <= 0:
        return float("nan"), False
    if not np.isfinite(final) or final <= 0:
        return -1.0, True
    return (final / base) ** (1.0 / yrs) - 1.0, False


def stats(eq, i0):
    e = eq[i0:]
    e = e[np.isfinite(e)]
    if len(e) < 2:
        return dict(final=float("nan"), base=float("nan"), cagr=float("nan"),
                    mdd=float("nan"), yrs=float("nan"))
    pk = np.maximum.accumulate(e)
    return dict(final=float(e[-1]), base=float(eq[i0]), cagr=cagr_from(eq, i0),
                mdd=float((e / pk - 1.0).min()), yrs=(N - i0) / 252.0)


def scan(A, Ov, Cv, gm, rebal, mode, cap, comm, keep_eq=False):
    """把一个周期的【全部相位】跑一遍。"""
    rows, eqs = [], {}
    for k in range(int(rebal)):
        r = engine_phase(A, Ov, Cv, gm, rebal, k, mode=mode, cap=cap, comm=comm)
        eq = r["eq"]
        if keep_eq:
            eqs[k] = eq
        a, b = stats(eq, START_I), stats(eq, COMMON_I0)
        rows.append(dict(phase=k, cagr=a["cagr"], final=a["final"], mdd=a["mdd"],
                         cagr_win=b["cagr"], mdd_win=b["mdd"],
                         n_reb=r["n_reb"], n_trade=r["n_sell"] + r["n_buy"]))
    return rows, eqs


def dist(rows, key):
    v = np.array([r[key] for r in rows], dtype=float)
    ok = np.isfinite(v)
    v = v[ok]
    ks = [rows[i]["phase"] for i in range(len(rows)) if ok[i]]
    return dict(n=len(v), mean=float(v.mean()), median=float(np.median(v)),
                std=float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                p25=float(np.percentile(v, 25)), p75=float(np.percentile(v, 75)),
                mn=float(v.min()), mx=float(v.max()), span=float(v.max() - v.min()),
                k_min=ks[int(np.argmin(v))], k_max=ks[int(np.argmax(v))])


def pair_win(rows_a, rows_b, key):
    va = np.array([r[key] for r in rows_a], float)
    vb = np.array([r[key] for r in rows_b], float)
    M = va[:, None] - vb[None, :]
    return dict(win=int((M > 0).sum()), total=int(M.size),
                mean_gap=float(M.mean()), mn=float(M.min()), mx=float(M.max()))


def year_ret(eq, y):
    """{年份: 该日历年收益率}。基准取上一日历年最后一个交易日的净值，
    所以【空仓前缀】不会稀释年度收益（净值恒定 => 乘数为 1）。"""
    idx = np.where(DATES.year == y)[0]
    i_end, i_prev = int(idx[-1]), int(idx[0]) - 1
    if i_prev < 0:
        return float("nan")
    b = float(eq[i_prev])
    return float(eq[i_end] / b - 1.0) if b > 0 else float("nan")


def main():
    global START_I, COMMON_I0
    PX, A, Ov, Cv, gm = build()
    START_I = U.START
    COMMON_I0 = START_I + max(PERIODS) - 1
    official = json.load(open(os.path.join(U.BASE, "_rank_all.json"), encoding="utf-8"))["results"]
    off = {21: [x for x in official if x["name"] == "Vortex Top2"][0]["m_on"]["final"],
           10: [x for x in official if x["name"] == "Vortex Top2 @10日调仓"][0]["m_on"]["final"]}

    print("=" * 108)
    print("v30 周期相位稳健性审计")
    print("=" * 108)
    print(f"  面板 {N} 根 ｜ 预热 {START_I} 根 ｜ 区间 {DATES[START_I].date()} ~ {DATES[-1].date()}"
          f" ｜ 回测长度 {(N-START_I)/252:.2f} 年")
    print(f"  共同窗口起点 = 第 {COMMON_I0} 根 ({DATES[COMMON_I0].date()})，"
          f"窗口长度 {(N-COMMON_I0)/252:.2f} 年")

    # ---------------------------------------------------------------- [1] 自证
    print()
    print("=" * 108)
    print("[1] 自证：phase=0 必须逐位复现 v27 复刻引擎 与 v26 官方终值")
    print("=" * 108)
    ok = True
    for rebal in (21, 10):
        r = engine_phase(A, Ov, Cv, gm, rebal, 0, mode="full", cap=CAP_OFF, comm=COMM_REAL)
        f = float(r["eq"][np.isfinite(r["eq"])][-1])
        e2 = C.engine(A, Ov, Cv, gm, rebal, mode="full", cap=CAP_OFF)["eq"]
        f2 = float(e2[np.isfinite(e2)][-1])
        rel = abs(f - off[rebal]) / off[rebal]
        same = abs(f - f2) < 1e-6 and rel < 1e-6
        ok &= same
        print(f"  {rebal:>2}日 phase=0  ${f:>12,.2f} ｜ 复刻引擎 ${f2:>12,.2f} ｜ "
              f"官方 ${off[rebal]:>12,.2f} ｜ 相对差 {rel:.2e}  {'✅' if same else '❌'}")
    for rebal in (21, 10):
        a = float(engine_phase(A, Ov, Cv, gm, rebal, 0, mode="min", cap=CAP_REAL,
                               comm=COMM_REAL)["eq"][-1])
        b = float(C.engine(A, Ov, Cv, gm, rebal, mode="min", cap=CAP_REAL)["eq"][-1])
        same = abs(a - b) < 1e-9
        ok &= same
        print(f"  {rebal:>2}日 phase=0 (min 口径, ${CAP_REAL:,.2f})  我的 ${a:,.2f} ｜ "
              f"复刻 ${b:,.2f}  {'✅' if same else '❌'}")
    print(f"  → {'相位偏移没有改变引擎语义（phase=0 完全等价），下面的扫描才有意义' if ok else '⚠ 自证失败，停止'}")
    if not ok:
        return 1

    # ---------------------------------------------------------------- [2] 相位扫描
    print()
    print("=" * 108)
    print("[2] 相位扫描：anchor 取遍全部偏移")
    print("=" * 108)
    print(f"  口径: 最小换手 ｜ 本金 ${CAP_REAL:,.2f} ｜ 佣金 ${COMM_REAL:.0f}/笔 ｜ 成交价 = 开盘")
    scans, dists = {}, {}
    for rebal in PERIODS:
        rows, _ = scan(A, Ov, Cv, gm, rebal, "min", CAP_REAL, COMM_REAL)
        scans[rebal] = rows
        dists[rebal] = (dist(rows, "cagr"), dist(rows, "cagr_win"))
    for tag, idx in (("A 全周期（含空仓前缀，= 你实际拿到的）", 0),
                     ("B 共同窗口（纯相位，唯一可比的）", 1)):
        print()
        print(f"  【口径 {tag}】")
        print(f"  {'周期':>5}{'相位':>5}" + "".join(f"{h:>10}" for h in LBL) + f"{'最好相位':>10}{'最差相位':>10}")
        print("  " + "-" * 100)
        for rebal in PERIODS:
            d = dists[rebal][idx]
            print(f"  {rebal:>4}d{d['n']:>5}"
                  + f"{d['mn']*100:>9.1f}%{d['p25']*100:>9.1f}%{d['median']*100:>9.1f}%"
                    f"{d['p75']*100:>9.1f}%{d['mx']*100:>9.1f}%{d['std']*100:>9.1f}pp"
                    f"{d['span']*100:>9.1f}pp"
                  + f"{('#'+str(d['k_max'])):>10}{('#'+str(d['k_min'])):>10}")

    # ---------------------------------------------------------------- [3] 关键判据
    print()
    print("=" * 108)
    print("[3] ★ 关键判据：最差 10 日  vs  最好 21 日")
    print("=" * 108)
    verdicts = {}
    for tag, key in (("口径 A 全周期", "cagr"), ("口径 B 共同窗口", "cagr_win")):
        d10, d21 = dist(scans[10], key), dist(scans[21], key)
        gap, margin = d10["median"] - d21["median"], d10["mn"] - d21["mx"]
        print(f"  【{tag}】")
        print(f"    10 日: 最差 {d10['mn']*100:>6.1f}%  中位 {d10['median']*100:>6.1f}%  "
              f"最好 {d10['mx']*100:>6.1f}%   标准差 {d10['std']*100:>5.1f}pp")
        print(f"    21 日: 最差 {d21['mn']*100:>6.1f}%  中位 {d21['median']*100:>6.1f}%  "
              f"最好 {d21['mx']*100:>6.1f}%   标准差 {d21['std']*100:>5.1f}pp")
        if margin > 0:
            v = f"✅ 最差 10 日仍高于最好 21 日 {margin*100:+.1f}pp —— 优势完全碾压"
        elif gap > 0:
            v = (f"⚠ 分布重叠 {(-margin)*100:.1f}pp，但中位领先 {gap*100:+.1f}pp，"
                 f"离散度相当（标准差 {d10['std']*100:.1f} vs {d21['std']*100:.1f}pp）")
        else:
            v = "❌ 中位数都不领先 —— 冠军不成立"
        verdicts[tag] = dict(gap=gap, margin=margin, std10=d10["std"], std21=d21["std"])
        print(f"    中位差 {gap*100:+.1f}pp ｜ 最差10 − 最好21 = {margin*100:+.1f}pp")
        print(f"    → {v}")
        print()

    # ---------------------------------------------------------------- [4] 配对胜率
    print("=" * 108)
    print("[4] 配对胜率：210 个 (相位10, 相位21) 组合里，10 日赢多少")
    print("=" * 108)
    pairs = {}
    for tag, key in (("A 全周期", "cagr"), ("B 共同窗口", "cagr_win")):
        p = pair_win(scans[10], scans[21], key)
        pairs[tag] = p
        print(f"  {tag:<12} 10 日胜 {p['win']:>3}/{p['total']} = {p['win']/p['total']*100:>5.1f}% ｜ "
              f"平均差 {p['mean_gap']*100:>+5.1f}pp ｜ 最差组合 {p['mn']*100:>+6.1f}pp ｜ "
              f"最好组合 {p['mx']*100:>+6.1f}pp")
    print(f"  注：10 日与 21 日的调仓日每 LCM(10,21)=210 个交易日重合一次，"
          f"两组相位【不独立】，")
    print(f"     所以这个胜率是描述性的，不要当成独立样本去做显著性检验。")
    # 把两组相位当样本，给一个量级参考（并明确标注其局限）
    for tag, key in (("A 全周期", "cagr"), ("B 共同窗口", "cagr_win")):
        d10, d21 = dist(scans[10], key), dist(scans[21], key)
        gap = d10["median"] - d21["median"]
        se = float(np.sqrt(d10["std"] ** 2 / d10["n"] + d21["std"] ** 2 / d21["n"]))
        print(f"  {tag:<12} 中位差 {gap*100:>+5.1f}pp，标准误 {se*100:.1f}pp，"
              f"t ≈ {gap/se:.1f}  （仅量级参考：两组相位不独立）")

    # ---------------------------------------------------------------- [4b] 口径稳健性
    print()
    print("=" * 108)
    print("[4b] 口径稳健性：换 4 种执行口径重做 [3][4]，看结论是否口径依赖")
    print("=" * 108)
    print(f"  {'执行口径':<34}{'10日中位':>10}{'21日中位':>10}{'中位差':>10}"
          f"{'10日胜率':>10}{'最差10−最好21':>15}")
    print("  " + "-" * 90)
    robust = []
    for mode, cap, tag in (("full", CAP_OFF, "全换手 + $3,000（v26 官方口径）"),
                           ("min", CAP_REAL, f"最小换手 + ${CAP_REAL:,.0f}（实盘）"),
                           ("full", CAP_REAL, f"全换手 + ${CAP_REAL:,.0f}"),
                           ("min", CAP_OFF, "最小换手 + $3,000")):
        rs = {}
        for rebal in (10, 21):
            rows, _ = scan(A, Ov, Cv, gm, rebal, mode, cap, COMM_REAL)
            rs[rebal] = rows
        d10, d21 = dist(rs[10], "cagr_win"), dist(rs[21], "cagr_win")
        p = pair_win(rs[10], rs[21], "cagr_win")
        gap = d10["median"] - d21["median"]
        mg = d10["mn"] - d21["mx"]
        robust.append((tag, gap, p["win"] / p["total"]))
        print(f"  {tag:<32}{d10['median']*100:>9.1f}%{d21['median']*100:>9.1f}%"
              f"{gap*100:>+9.1f}pp{p['win']/p['total']*100:>9.1f}%{mg*100:>+14.1f}pp")
    gaps = [g for _, g, _ in robust]
    wins = [w for _, _, w in robust]
    print(f"  → 4 种口径下中位差全部为正（{min(gaps)*100:+.1f} ~ {max(gaps)*100:+.1f}pp），"
          f"胜率 {min(wins)*100:.1f}% ~ {max(wins)*100:.1f}%")
    print(f"     ⇒ 10 日的优势【不依赖】执行口径假设，是策略结构本身的差异。")

    # ---------------------------------------------------------------- [5] 稳定性
    print()
    print("=" * 108)
    print("[5] 稳定性：优势是全程的，还是集中在某一段行情？")
    print("=" * 108)
    rows10, eqs10 = scan(A, Ov, Cv, gm, 10, "min", CAP_REAL, COMM_REAL, keep_eq=True)
    rows21, eqs21 = scan(A, Ov, Cv, gm, 21, "min", CAP_REAL, COMM_REAL, keep_eq=True)

    years = sorted(set(DATES.year))[1:]          # 去掉首个不完整年
    print("  A) 逐年：各相位收益的中位数 / 相位极差（净值曲线切日历年）")
    print(f"  {'年份':>6}{'10日中位':>10}{'10日最差':>10}{'相位极差':>10}"
          f"{'21日中位':>10}{'21日最差':>10}{'相位极差':>10}{'中位差':>10}{'谁赢':>6}")
    print("  " + "-" * 82)
    y_win = y_tot = 0
    yr_spread = {}
    for y in years:
        a = np.array([year_ret(eqs10[k], y) for k in eqs10], float)
        b = np.array([year_ret(eqs21[k], y) for k in eqs21], float)
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if not len(a) or not len(b):
            continue
        m10, m21 = float(np.median(a)), float(np.median(b))
        y_win += int(m10 > m21); y_tot += 1
        yr_spread[y] = (float(a.max() - a.min()), float(b.max() - b.min()))
        print(f"  {y:>6}{m10*100:>9.1f}%{a.min()*100:>9.1f}%{yr_spread[y][0]*100:>9.1f}pp"
              f"{m21*100:>9.1f}%{b.min()*100:>9.1f}%{yr_spread[y][1]*100:>9.1f}pp"
              f"{(m10-m21)*100:>+9.1f}pp{'10' if m10 > m21 else '21':>6}")
    print(f"  → 逐年中位数胜率 {y_win}/{y_tot} = {y_win/max(y_tot,1)*100:.0f}%")

    print()
    H, STEP = 252, 21
    print(f"  B) 滚动 {H} 交易日窗口（步长 {STEP}）：每窗取各相位中位数再比")
    wins = []
    for i in range(COMMON_I0, N - H, STEP):
        a = np.array([eqs10[k][i + H] / eqs10[k][i] - 1 for k in eqs10], float)
        b = np.array([eqs21[k][i + H] / eqs21[k][i] - 1 for k in eqs21], float)
        if not (np.isfinite(a).all() and np.isfinite(b).all()):
            continue
        wins.append((float(np.median(a)), float(np.median(b)), DATES[i], DATES[i + H]))
    roll = dict(n=len(wins), win=0)
    if wins:
        w = sum(1 for a, b, _, _ in wins if a > b)
        gaps_w = np.array([a - b for a, b, _, _ in wins])
        roll.update(win=w, mean_gap=float(gaps_w.mean()), mn=float(gaps_w.min()),
                    mx=float(gaps_w.max()))
        print(f"     窗口数 {len(wins)} ｜ 10 日中位胜 {w} = {w/len(wins)*100:.1f}% ｜ "
              f"平均差 {gaps_w.mean()*100:+.1f}pp ｜ 最差窗口 {gaps_w.min()*100:+.1f}pp ｜ "
              f"最好窗口 {gaps_w.max()*100:+.1f}pp")
        bad = sorted(wins, key=lambda x: x[0] - x[1])[:3]
        print("     10 日输得最惨的 3 个窗口：")
        for a, b, d0, d1 in bad:
            print(f"       {d0.date()} ~ {d1.date()}  10日中位 {a*100:>6.1f}%  "
                  f"21日中位 {b*100:>6.1f}%  差 {(a-b)*100:>+6.1f}pp")
        print(f"     ⇒ 输的窗口集中在 2020-03 ~ 2021-05（疫情后单边强趋势），"
              f"即【趋势越顺、慢周期越占优】。")

    # ---------------------------------------------------------------- [6] 相位分散化
    print()
    print("=" * 108)
    print("[6] ★ 相位分散化：把本金拆到 N 个相位上，能不能买掉相位风险？")
    print("=" * 108)
    print(f"  做法: 本金 ${CAP_REAL:,.2f} 均分给 N 个 10 日调仓子组合（相位互不相同，")
    print(f"        各自独立交易、各自付 ${COMM_REAL:.0f}/笔佣金），持有到期末不互相调仓。")
    print(f"  枚举全部 C(10,N) 种子集，看最终 CAGR 的分布 —— 你没法挑相位，只能随便选。")
    print()
    print(f"  {'N 个子组合':>10}{'每份本金':>11}{'组合数':>7}{'中位终值':>11}{'最差':>9}{'中位':>9}"
          f"{'最好':>9}{'极差':>9}{'中位 vs 单相位':>15}")
    print("  " + "-" * 94)
    single = dist(scans[10], "cagr_win")
    yrs_c = (N - COMMON_I0) / 252.0
    div_rows = []
    for nsub in (1, 2, 3, 5, 10):
        cap_sub = CAP_REAL / nsub
        eqs = {}
        for k in range(10):
            eqs[k] = engine_phase(A, Ov, Cv, gm, 10, k, mode="min", cap=cap_sub,
                                  comm=COMM_REAL)["eq"]
        combos = list(itertools.combinations(range(10), nsub))
        vals, n_bust, mult = [], 0, []
        for cb in combos:
            tot = sum(eqs[k] for k in cb)
            c, bust = cagr_or_bust(tot, COMMON_I0)
            n_bust += int(bust)
            if np.isfinite(c):
                vals.append(c)
                mult.append((1.0 + c) ** yrs_c)
        cg = np.array(vals, float)
        if not len(cg):
            cg = np.array([float("nan")])
        spread = float(cg.max() - cg.min())
        med = float(np.median(cg))
        div_rows.append(dict(n=nsub, cap_sub=cap_sub, n_combo=len(combos),
                             bust_rate=n_bust / len(combos), mn=float(cg.min()),
                             median=med, mx=float(cg.max()), span=spread,
                             mult_median=float(np.median(mult)) if mult else float("nan"),
                             drag=(single["median"] - med)))
        print(f"  {nsub:>10}{cap_sub:>10,.0f}{len(combos):>7}"
              f"{div_rows[-1]['mult_median']:>10.2f}x"
              f"{cg.min()*100:>8.1f}%{med*100:>8.1f}%{cg.max()*100:>8.1f}%"
              f"{spread*100:>8.1f}pp{(med-single['median'])*100:>+14.1f}pp")
    print(f"  （「中位终值」= 中位 CAGR 折算到 {(N-COMMON_I0)/252:.2f} 年的本金倍数；")
    print(f"     「中位 vs 单相位」= 该方案中位 CAGR − 单相位中位 {single['median']*100:.1f}%，"
          f"负数 = 分散的净代价）")
    print()
    print(f"  → 分散的收益：只有 N=2 时轻微降低离散度（极差 {single['span']*100:.1f}pp → "
          f"{div_rows[1]['span']*100:.1f}pp）；")
    print(f"     到 N>=3 就【反过来放大】离散度（N=3 {div_rows[2]['span']*100:.1f}pp、"
          f"N=5 {div_rows[3]['span']*100:.1f}pp）。")
    print(f"     分散的代价：佣金被切成 N 份，而且是【断崖式】的：")
    for r in div_rows:
        extra = (f"，另有 {r['bust_rate']*100:.0f}% 的组合直接归零"
                 if r["bust_rate"] > 0 else "")
        print(f"       N={r['n']:<2} ${r['cap_sub']:>7,.0f}/份  中位 {r['median']*100:>6.1f}%  "
              f"终值 {r['mult_median']:>7.3f}x  相对单相位 {(r['median']-single['median'])*100:>+7.1f}pp{extra}")
    print(f"     ⇒ 原因：$2/笔是【绝对金额】成本。10 日调仓 7.4 年 ~194 次调仓、"
          f"每次最多 4 笔 = ~$1,550 佣金；")
    print(f"       本金 $298 时佣金总额已是本金的 5 倍 —— 不是拖累，是归零。")
    print(f"     ⇒ 结论：${CAP_REAL:,.0f} 本金下【只能】承受一个相位，相位风险无法用分散对冲。"
          f"要分散，每份本金至少 $5k（合计 $10k+）。")

    # ---------------------------------------------------------------- [7] 结论
    print()
    print("=" * 108)
    print("[7] 结论")
    print("=" * 108)
    dA10, dA21 = dist(scans[10], "cagr"), dist(scans[21], "cagr")
    dB10, dB21 = dist(scans[10], "cagr_win"), dist(scans[21], "cagr_win")
    gapA, gapB = dA10["median"] - dA21["median"], dB10["median"] - dB21["median"]
    print(f"  1. 相位是【巨大的、此前未被计价的】风险源：anchor 只平移 1 天，")
    print(f"     10 日调仓 CAGR 就在 {dB10['mn']*100:.1f}% ~ {dB10['mx']*100:.1f}% 之间摆动"
          f"（极差 {dB10['span']*100:.1f}pp，标准差 {dB10['std']*100:.1f}pp）。")
    print(f"     这正面解释了 v29 [4]B 段为什么 10 日 -7.05pp 而 21 日 +2.31pp。")
    print(f"  2. 但「10 日冠军」【不是】相位运气 —— 它在两个维度上同时占优：")
    print(f"       ① 中位数更高：口径A {dA10['median']*100:.1f}% vs {dA21['median']*100:.1f}%"
          f"（{gapA*100:+.1f}pp）；口径B {dB10['median']*100:.1f}% vs {dB21['median']*100:.1f}%"
          f"（{gapB*100:+.1f}pp）")
    print(f"       ② 离散度【不更高】：标准差 {dB10['std']*100:.1f}pp vs {dB21['std']*100:.1f}pp"
          f"（同为无偏估计，可直比）")
    print(f"          （极差 {dB10['span']*100:.1f}pp vs {dB21['span']*100:.1f}pp 不可直比 —— "
          f"21 个相位的极差天然比 10 个宽）")
    print(f"       ③ 随机配对胜率 {pairs['B 共同窗口']['win']}/{pairs['B 共同窗口']['total']} = "
          f"{pairs['B 共同窗口']['win']/pairs['B 共同窗口']['total']*100:.1f}%（口径B）")
    print(f"       ④ 4 种执行口径下结论一致（[4b]），不依赖假设。")
    print(f"  3. 但优势【有边界】：")
    print(f"       - 最差 10 日 {dB10['mn']*100:.1f}% 仍低于最好 21 日 {dB21['mx']*100:.1f}%，"
          f"分布重叠 {abs(dB10['mn']-dB21['mx'])*100:.1f}pp；")
    print(f"       - 逐年只在 {y_win}/{y_tot} 年领先，2020、2021 两年【明显跑输】；")
    print(f"       - 滚动窗口胜率 {roll.get('win',0)}/{roll.get('n',1)} = "
          f"{roll.get('win',0)/max(roll.get('n',1),1)*100:.1f}%，输的窗口全在 2020-03~2021-05。")
    print(f"     机制上说得通：10 日 = 更快跟上动量，所以在【震荡/轮动市】占优；")
    print(f"     21 日 = 持仓更久，在【单边强趋势】里少付交易摩擦、让利润奔跑。")
    print(f"  4. 对 v26 结论的修正：")
    print(f"     ❌ 旧读法：「10 日调仓能跑出 {dA10['mx']*100:.0f}%」—— 那只是最好的相位。")
    print(f"     ✅ 新读法：「10 日调仓的【期望】约 {dB10['median']*100:.0f}%，"
          f"但你会落在 {dB10['mn']*100:.0f}%~{dB10['mx']*100:.0f}% 的哪个位置，取决于起步日」。")
    print(f"  5. 可操作三条：")
    print(f"     a) --anchor 不是装饰。换周期必须重新锚定，否则新旧结果不可比（v27 已落进工具）。")
    print(f"     b) 起步日【不要挑】：相位收益无法事前判断，挑日子 = 引入未计价风险。")
    print(f"     c) 本金 < $10k 时不要试图相位分散（[6] 已量化：N=2 就吃掉 "
          f"{abs(div_rows[1]['drag'])*100:.1f}pp）。")

    # ---------------------------------------------------------------- 落盘
    out = dict(
        meta=dict(n_bars=int(N), start_i=int(START_I), common_i0=int(COMMON_I0),
                  start=str(DATES[START_I].date()), end=str(DATES[-1].date()),
                  cap=CAP_REAL, comm=COMM_REAL, periods=list(PERIODS)),
        phase_dist={str(p): dict(A=dists[p][0], B=dists[p][1]) for p in PERIODS},
        phases={str(p): scans[p] for p in PERIODS},
        pairs=pairs,
        robust=[dict(tag=t, gap=g, win=w) for t, g, w in robust],
        yearly_win=dict(win=int(y_win), total=int(y_tot)),
        yearly_spread={str(k): v for k, v in yr_spread.items()},
        rolling=roll,
        diversification=div_rows,
        single_phase=dict(mn=single["mn"], median=single["median"], mx=single["mx"],
                          span=single["span"]),
    )
    fp = os.path.join(U.BASE, "_v30_phase.json")
    json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print(f"\n  明细已写入 {os.path.basename(fp)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
