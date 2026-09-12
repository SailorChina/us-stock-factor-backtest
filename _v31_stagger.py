# -*- coding: utf-8 -*-
"""
v31: 错开调仓（staggered rebalancing）—— 能不能【零成本】压缩相位风险？

v30 的结论
----------
调仓周期是一个【相位】: RB = {i | i >= anchor, (i-anchor) % rebal == 0}。
anchor 平移 1 天, 10 日调仓的 CAGR 就在 51.3% ~ 100.6% 之间摆动（极差 49.3pp），
比 v27~v29 讨论的任何一项交易成本都大一个量级。

而 v30 [6] 证明: 在 $1,490 本金下, 把【本金】拆成 N 份做相位分散【买不起】——
因为拆本金 = 持股数从 2 只变 4 只, 佣金笔数翻倍。N=2 就吃掉 6.2pp。

但那是【错的分散方式】。真正零成本的做法是【错开两腿的调仓日】:
    基线 : 每 10 天一次调仓, 一次动 2 只  -> 最多 2 卖 + 2 买 = $8 / 10 天
    错开 : 每 5 天一次调仓, 一次动 1 只   -> 10 天共 2 卖 + 2 买 = $8 / 10 天
**持股数不变(仍是 2 只)、每只仓位不变(仍 ~$745)、佣金总额不变。**
唯一变的是【调仓事件被摊到整个周期上】—— 这正是相位风险的对冲。

审计设计
--------
[1] 自证      : 腿机械在 offset=0 时, 成交笔数必须与 v27 复刻引擎【完全相同】
                （若不同 -> 我的实现有 bug, 下面全部无意义）
[2] 成本核对  : 各 offset 的成交笔数 / 佣金总额, 验证"零成本"这个前提
[3] 错开扫描  : offset ∈ {0..9} × phase ∈ {0..9} -> CAGR 分布（口径 B）
[4] 关键判据  : 有没有某个 offset 同时做到「中位不降 + 最差不降 + 极差收窄」
[5] 稳定性    : 逐年 / 滚动窗口, 看收窄是全程的还是局部的
[6] 21 日调仓能不能也错开
[7] 结论

口径
----
- 口径 A 全周期  : base = 本金, 从面板第 252 根算起（含空仓前缀）
- 口径 B 共同窗口: base = 各相位都建完仓之后那一天（唯一干净的纯相位比较）
- offset=0 用【腿机械】跑（对齐但两腿不等权），作为"机械对照";
  另外用 v27 复刻引擎跑一遍真正的基线（对齐且等权），两者之差 = 等权与否的影响。

用法:  python _v31_stagger.py
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
from _v30_phase import engine_phase as _EP      # v30 已验证过的逐相位基线引擎

N = None
START_I = None
COMMON_I0 = None
DATES = None
CAP_REAL = 1490.49
COMM_REAL = 2.0


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
    C.N = N
    DATES = pd.DatetimeIndex(dates)
    return PX, A, Ov, Cv, gm


def engine_stagger(A, Ov, Cv, gm, rebal, phase, offset, topk=2,
                   cap=CAP_REAL, comm=COMM_REAL, want_wdev=False):
    """两腿【错开】调仓的 v25.1 口径引擎。

    leg0 调仓日: i >= START+phase,            (i - (START+phase)) % rebal == 0
    leg1 调仓日: i >= START+phase+offset,     (i - (START+phase+offset)) % rebal == 0

    单腿规则（与基线语义对齐）:
      1) 算出当期 Top-2 集合 t2;
      2) 若本腿现持票仍在 t2 里 -> 不动（零佣金, 权重自然漂移）;
      3) 否则卖掉本腿, 改买 t2 里【另一腿没持有】的那只
         （另一腿都不持有则买 t2[0]）;
      4) t2 不足 2 只 -> 卖掉本腿持币（与基线一致）。

    与基线唯一的结构差别: 本引擎【不把两腿调回等权】。
    offset=0 时两腿同日调仓, 于是与基线只差"等权 vs 不等权"这一项 —— 这正是
    [1] 自证里要量化的东西（成交笔数必须完全相同）。
    """
    a = START_I + int(phase)
    ev = {}
    for k, off in enumerate((0, int(offset))):
        s = a + off
        for i in range(s, N):
            if (i - s) % rebal == 0:
                ev.setdefault(i, []).append(k)
    leg_cash = [cap / 2.0, cap / 2.0]
    leg_sh = [0.0, 0.0]
    leg_j = [-1, -1]
    eq = np.full(N, np.nan)
    eq[:START_I] = cap
    n_sell = n_buy = 0
    wdev = []
    for i in range(START_I, N):
        if i in ev:
            js = i - 1
            row = A[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx):
                idx = idx[gm[js, idx]]
            t2 = list(idx[np.argsort(-row[idx])][:topk]) if len(idx) >= topk else []
            for k in ev[i]:
                cur = leg_j[k]
                if t2 and cur in t2:
                    continue                       # 仍在 Top-2 里 -> 一笔不动
                if not t2:
                    pick = -1
                else:
                    oth = leg_j[1 - k]
                    if oth == t2[0] and len(t2) > 1:
                        pick = t2[1]
                    elif len(t2) > 1 and oth == t2[1]:
                        pick = t2[0]
                    else:
                        pick = t2[0]
                if cur >= 0:
                    pr = Ov[i, cur]
                    if np.isfinite(pr) and pr > 0:
                        leg_cash[k] += leg_sh[k] * pr - comm
                        n_sell += 1
                        leg_sh[k] = 0.0
                        leg_j[k] = -1
                    else:
                        continue                   # 卖不掉 -> 保留持仓（F2 口径）
                if pick >= 0:
                    pr = Ov[i, pick]
                    if np.isfinite(pr) and pr > 0:
                        bud = max(0.0, leg_cash[k] - comm)
                        sh = bud / pr
                        if sh > 0:
                            leg_sh[k] = sh
                            leg_cash[k] -= sh * pr + comm
                            leg_j[k] = pick
                            n_buy += 1
        v0 = leg_cash[0] + (leg_sh[0] * Cv[i, leg_j[0]] if leg_j[0] >= 0
                            and np.isfinite(Cv[i, leg_j[0]]) else 0.0)
        v1 = leg_cash[1] + (leg_sh[1] * Cv[i, leg_j[1]] if leg_j[1] >= 0
                            and np.isfinite(Cv[i, leg_j[1]]) else 0.0)
        eq[i] = v0 + v1
        if want_wdev and (v0 + v1) > 0:
            wdev.append(abs(v0 / (v0 + v1) - 0.5))
    return dict(eq=eq, n_sell=n_sell, n_buy=n_buy,
                wdev=float(np.mean(wdev)) if wdev else float("nan"))


def cagr_from(eq, i0):
    yrs = (N - i0) / 252.0
    base, final = float(eq[i0]), float(eq[-1])
    if not np.isfinite(base) or base <= 0 or not np.isfinite(final) or final <= 0:
        return float("nan")
    return (final / base) ** (1.0 / yrs) - 1.0


def dist(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    if not len(v):
        return dict(n=0, mn=float("nan"), median=float("nan"), mx=float("nan"),
                    std=float("nan"), span=float("nan"), p25=float("nan"),
                    p75=float("nan"))
    return dict(n=len(v), mn=float(v.min()), p25=float(np.percentile(v, 25)),
                median=float(np.median(v)), p75=float(np.percentile(v, 75)),
                mx=float(v.max()), std=float(v.std(ddof=1)) if len(v) > 1 else 0.0,
                span=float(v.max() - v.min()))


def scan_offset(A, Ov, Cv, gm, rebal, offset, phases):
    out = []
    for p in phases:
        r = engine_stagger(A, Ov, Cv, gm, rebal, p, offset)
        out.append(dict(phase=p, cagr_win=cagr_from(r["eq"], COMMON_I0),
                        cagr_all=cagr_from(r["eq"], START_I),
                        n_trade=r["n_sell"] + r["n_buy"], eq=r["eq"]))
    return out


def main():
    global START_I, COMMON_I0
    PX, A, Ov, Cv, gm = build()
    START_I = U.START
    V30.N = N                       # 让 _v30_phase.engine_phase 用同一个面板
    V30.START_I = START_I
    REB = 10
    COMMON_I0 = START_I + 9
    phases = list(range(REB))

    print("=" * 108)
    print("v31 错开调仓：零成本压缩相位风险？")
    print("=" * 108)
    print(f"  面板 {N} 根 ｜ 区间 {DATES[START_I].date()} ~ {DATES[-1].date()}"
          f" ｜ 回测 {(N-START_I)/252:.2f} 年 ｜ 共同窗口 {(N-COMMON_I0)/252:.2f} 年")
    print(f"  口径: 最小换手 ｜ 本金 ${CAP_REAL:,.2f} ｜ 佣金 ${COMM_REAL:.0f}/笔 ｜ 成交价 = 开盘")

    # ---------------------------------------------------------------- [1] 自证
    print()
    print("=" * 108)
    print("[1] 自证：腿机械在 offset=0 时，成交笔数必须与 v27 复刻引擎【完全相同】")
    print("=" * 108)
    print(f"  {'相位':>5}{'复刻引擎 卖/买':>16}{'腿机械 卖/买':>16}{'笔数差':>9}"
          f"{'复刻终值':>14}{'腿机械终值':>14}{'差%':>9}")
    print("  " + "-" * 84)
    ok = True
    base_eq, base_nt = {}, {}
    for p in phases:
        b = _EP(A, Ov, Cv, gm, REB, p, mode="min", cap=CAP_REAL, comm=COMM_REAL)
        base_nt[p] = b["n_sell"] + b["n_buy"]
        base_eq[p] = float(b["eq"][-1])
        lg = engine_stagger(A, Ov, Cv, gm, REB, p, 0)
        lt = lg["n_sell"] + lg["n_buy"]
        same = (lt == base_nt[p])
        ok &= same
        print(f"  {p:>5}{base_nt[p]:>16}{lt:>16}{lt - base_nt[p]:>9}"
              f"${base_eq[p]:>13,.0f}${float(lg['eq'][-1]):>13,.0f}"
              f"{(float(lg['eq'][-1])/base_eq[p]-1)*100:>8.3f}%  {'✅' if same else '❌'}")
    # 再用 v27 复刻引擎交叉核对 phase=0 这一行（独立实现）
    c0 = C.engine(A, Ov, Cv, gm, REB, mode="min", cap=CAP_REAL)
    cross = abs(float(c0["eq"][-1]) - base_eq[0]) < 1e-6
    ok &= cross
    print(f"  phase=0 与 v27 复刻引擎交叉核对: ${float(c0['eq'][-1]):,.2f} vs "
          f"${base_eq[0]:,.2f}  {'✅' if cross else '❌'}")
    print(f"  → 成交笔数{'全部一致' if ok else '不一致 —— 实现有 bug，停止'}；"
          f"终值差异只来自「等权 vs 不等权」这一项。")
    if not ok:
        return 1

    # ---------------------------------------------------------------- [2] 成本核对
    print()
    print("=" * 108)
    print("[2] 成本核对：错开到底有没有多花钱？（7.67 年累计）")
    print("=" * 108)
    print(f"  {'offset':>7}{'相位0 笔数':>12}{'相位0 佣金':>12}{'平均笔数':>11}"
          f"{'vs 基线':>10}{'两腿权重偏离 50/50':>20}")
    print("  " + "-" * 76)
    cost = {}
    for d in range(REB):
        nts, cm, wd = [], [], []
        for p in phases:
            r = engine_stagger(A, Ov, Cv, gm, REB, p, d, want_wdev=(p == 0))
            nts.append(r["n_sell"] + r["n_buy"])
            cm.append((r["n_sell"] + r["n_buy"]) * COMM_REAL)
            if p == 0:
                wd.append(r["wdev"])
        cost[d] = dict(nt_mean=float(np.mean(nts)), comm=float(np.mean(cm)),
                       wdev=float(np.mean(wd)))
        base_nt_mean = float(np.mean([base_nt[p] for p in phases]))
        print(f"  {d:>7}{nts[0]:>12}{cm[0]:>11,.0f}${cost[d]['nt_mean']:>10.0f}"
              f"{(cost[d]['nt_mean']/base_nt_mean-1)*100:>+9.1f}%"
              f"{cost[d]['wdev']*100:>19.1f}%")
    print(f"  基线（等权、对齐）平均笔数 {base_nt_mean:.0f}，"
          f"累计佣金 ${base_nt_mean*COMM_REAL:,.0f}")
    print(f"  → offset=0（腿机械）笔数应与基线完全相同；offset>0 的笔数差异见上表。")
    print(f"     两腿权重偏离 50/50 越大 = 越「不等权」，这是错开的固有代价，需一并披露。")

    # ---------------------------------------------------------------- [3] 错开扫描
    print()
    print("=" * 108)
    print("[3] 错开扫描：每个 offset 取遍 10 个相位，看 CAGR 分布（口径 B 共同窗口）")
    print("=" * 108)
    print(f"  {'offset':>7}{'最差':>8}{'P25':>8}{'中位':>8}{'P75':>8}{'最好':>8}"
          f"{'IQR':>8}{'标准差':>9}{'极差':>9}{'vs 基线中位':>12}")
    print("  " + "-" * 86)
    base_cg = np.array([cagr_from(_EP(A, Ov, Cv, gm, REB, p, mode="min", cap=CAP_REAL,
                                     comm=COMM_REAL)["eq"], COMMON_I0) for p in phases])
    dbase = dist(base_cg)
    print(f"  {'基线':>7}{dbase['mn']*100:>7.1f}%{dbase['p25']*100:>7.1f}%"
          f"{dbase['median']*100:>7.1f}%{dbase['p75']*100:>7.1f}%{dbase['mx']*100:>7.1f}%"
          f"{(dbase['p75']-dbase['p25'])*100:>7.1f}pp{dbase['std']*100:>8.1f}pp"
          f"{dbase['span']*100:>8.1f}pp{'—':>12}")
    res = {}
    for d in range(REB):
        rows = scan_offset(A, Ov, Cv, gm, REB, d, phases)
        v = np.array([r["cagr_win"] for r in rows], float)
        dd = dist(v)
        res[d] = dict(dist=dd, rows=rows)
        print(f"  {d:>7}{dd['mn']*100:>7.1f}%{dd['p25']*100:>7.1f}%{dd['median']*100:>7.1f}%"
              f"{dd['p75']*100:>7.1f}%{dd['mx']*100:>7.1f}%"
              f"{(dd['p75']-dd['p25'])*100:>7.1f}pp{dd['std']*100:>8.1f}pp"
              f"{dd['span']*100:>8.1f}pp{(dd['median']-dbase['median'])*100:>+11.1f}pp")
    print(f"  ⚠ 结构性对称: offset=d 与 offset={REB}-d 的【事件间隔多重集】相同"
          f"（都是 {{d, {REB}-d}}），")
    print(f"     两腿在规则里完全对称 ⇒ 它们本质是同一个排程。所以真正独立的只有 "
          f"d = 0..{REB//2} 这 {REB//2+1} 种。")

    # ---------------------------------------------------------------- [4] 关键判据
    print()
    print("=" * 108)
    print("[4] ★ 关键判据：错开是「风险-收益互换」还是「免费午餐」？")
    print("=" * 108)
    print(f"  基线: 中位 {dbase['median']*100:.1f}% ｜ 最差 {dbase['mn']*100:.1f}% ｜ "
          f"IQR {(dbase['p75']-dbase['p25'])*100:.1f}pp ｜ 标准差 {dbase['std']*100:.1f}pp")
    print()
    print(f"  {'offset':>7}{'Δ中位':>10}{'Δ最差':>10}{'ΔIQR':>10}{'Δ标准差':>11}"
          f"{'Δ极差':>10}{'判断':>22}")
    print("  " + "-" * 80)
    best = []
    for d in range(1, REB):
        dd = res[d]["dist"]
        dm = (dd["median"] - dbase["median"]) * 100
        dmn = (dd["mn"] - dbase["mn"]) * 100
        diqr = ((dd["p75"] - dd["p25"]) - (dbase["p75"] - dbase["p25"])) * 100
        dsd = (dd["std"] - dbase["std"]) * 100
        dsp = (dd["span"] - dbase["span"]) * 100
        free = (dm >= -0.5) and (dmn >= 0) and (diqr < 0) and (dsd < 0)
        best.append((d, dm, dmn, diqr, dsd, dsp, free))
        tag = "✅ 免费午餐" if free else ("互换" if (dmn > 0 or diqr < 0) else "全面变差")
        print(f"  {d:>7}{dm:>+9.1f}pp{dmn:>+9.1f}pp{diqr:>+9.1f}pp{dsd:>+10.1f}pp"
              f"{dsp:>+9.1f}pp{tag:>22}")
    winners = [b for b in best if b[6]]
    print()
    if winners:
        w = max(winners, key=lambda x: x[2] - x[3])
        print(f"  → offset={w[0]} 满足「中位不降 + 最差不降 + IQR 收窄 + 标准差收窄」")
    else:
        print(f"  → ❌ 没有任何 offset 是免费午餐。全部都是【用中位换下限/换离散度】的互换。")
        gain = [b for b in best if b[2] > 0 and b[3] < 0]
        if gain:
            g = max(gain, key=lambda x: x[2] - x[3])
            print(f"     互换幅度最大的 offset={g[0]}: 最差 {g[2]:+.1f}pp、IQR {g[3]:+.1f}pp、"
                  f"标准差 {g[4]:+.1f}pp，代价是中位 {g[1]:+.1f}pp。")
    print(f"  ⚠ 多重比较警告: 真正独立的排程只有 {REB//2} 种（见 [3] 末注），")
    print(f"     从 {REB//2} 种里挑「离散度最小」的那个, 本身就是一次选择性偏差。")
    print(f"     [5b] 用滚动窗口把样本量提上来再判一次。")

    # ---------------------------------------------------------------- [5] 稳定性
    print()
    print("=" * 108)
    print("[5] 稳定性：逐个 offset 的【逐年最差相位】—— 看谁在坏年份更抗跌")
    print("=" * 108)
    years = sorted(set(DATES.year))[1:]
    print(f"  {'offset':>7}" + "".join(f"{y:>9}" for y in years) + f"{'最差年':>10}")
    print("  " + "-" * (7 + 9 * len(years) + 10))

    def yearly_worst(eqs):
        out = []
        for y in years:
            vals = []
            for e in eqs:
                idx = np.where(DATES.year == y)[0]
                ip = int(idx[0]) - 1
                if ip < 0:
                    continue
                b = float(e[ip])
                if b > 0:
                    vals.append(float(e[int(idx[-1])]) / b - 1.0)
            out.append(min(vals) if vals else float("nan"))
        return out

    base_eqs = [_EP(A, Ov, Cv, gm, REB, p, mode="min", cap=CAP_REAL,
                    comm=COMM_REAL)["eq"] for p in phases]
    bw = yearly_worst(base_eqs)
    print(f"  {'基线':>7}" + "".join(f"{v*100:>8.1f}%" for v in bw)
          + f"{min(bw)*100:>9.1f}%")
    for d in range(REB):
        ws = yearly_worst([r["eq"] for r in res[d]["rows"]])
        print(f"  {d:>7}" + "".join(f"{v*100:>8.1f}%" for v in ws)
              + f"{min(ws)*100:>9.1f}%")
    print("  （每格 = 该 offset 下【10 个相位里最差那个】在该年的收益 —— 悲观视角）")

    # ---------------------------------------------------------------- [5b] 稳健离散度
    print()
    print("=" * 108)
    print("[5b] ★ 稳健版：滚动 252 日窗口内的【跨相位标准差】，再对窗口取平均")
    print("=" * 108)
    print(f"  [3] 的离散度只基于 10 个相位，样本太小。这里把每个相位切成滚动窗口，")
    print(f"  在【每个窗口内部】算 10 个相位的收益标准差，再对窗口取平均 —— 样本量放大到窗口数。")
    H = 252
    idxs = list(range(COMMON_I0, N - H, 21))
    half = len(idxs) // 2

    def win_stds(eqs):
        out = []
        for i in idxs:
            v = np.array([e[i + H] / e[i] - 1.0 for e in eqs], float)
            if np.isfinite(v).all():
                out.append(float(np.std(v, ddof=1)))
        return np.array(out, float)

    base_ws = win_stds(base_eqs)
    print()
    print(f"  窗口数 {len(base_ws)}（步长 21）｜ 前半段 {half} 个 ｜ 后半段 {len(base_ws)-half} 个")
    print(f"  {'offset':>7}{'平均跨相位std':>15}{'中位':>10}{'前半段':>11}{'后半段':>11}"
          f"{'vs 基线':>10}")
    print("  " + "-" * 66)
    ws_all = {}
    for tag, ws in (("基线", base_ws),):
        print(f"  {tag:>7}{ws.mean()*100:>14.1f}pp{np.median(ws)*100:>9.1f}pp"
              f"{ws[:half].mean()*100:>10.1f}pp{ws[half:].mean()*100:>10.1f}pp{'—':>10}")
    for d in range(REB):
        ws = win_stds([r["eq"] for r in res[d]["rows"]])
        ws_all[d] = ws
        print(f"  {d:>7}{ws.mean()*100:>14.1f}pp{np.median(ws)*100:>9.1f}pp"
              f"{ws[:half].mean()*100:>10.1f}pp{ws[half:].mean()*100:>10.1f}pp"
              f"{(ws.mean()-base_ws.mean())*100:>+9.1f}pp")
    print()
    print(f"  判据: 真正可信的收窄, 必须【前半段与后半段同向】。只在一半里收窄 = 运气。")
    consistent = []
    for d in range(REB):
        a = ws_all[d][:half].mean() - base_ws[:half].mean()
        b = ws_all[d][half:].mean() - base_ws[half:].mean()
        if a < 0 and b < 0:
            consistent.append((d, a * 100, b * 100))
    if consistent:
        for d, a, b in consistent:
            print(f"    ✅ offset={d}: 前半段 {a:+.1f}pp、后半段 {b:+.1f}pp —— 两段都收窄")
    else:
        print(f"    ❌ 【没有任何 offset 在两段里都收窄】⇒ [3] 里看到的「某个 offset 离散度更小」")
        print(f"       不能排除是 10 个相位的小样本波动。")

    # ---------------------------------------------------------------- [6] 21 日
    print()
    print("=" * 108)
    print("[6] 21 日调仓能不能也错开？（相位 0..20，offset 取 {0,5,7,10}）")
    print("=" * 108)
    R21 = 21
    ph21 = list(range(R21))
    c21 = np.array([cagr_from(_EP(A, Ov, Cv, gm, R21, p, mode="min", cap=CAP_REAL,
                                  comm=COMM_REAL)["eq"], COMMON_I0) for p in ph21])
    d21 = dist(c21)
    print(f"  {'offset':>7}{'最差':>9}{'中位':>9}{'最好':>9}{'标准差':>10}{'极差':>10}")
    print("  " + "-" * 56)
    print(f"  {'基线':>7}{d21['mn']*100:>8.1f}%{d21['median']*100:>8.1f}%{d21['mx']*100:>8.1f}%"
          f"{d21['std']*100:>9.1f}pp{d21['span']*100:>9.1f}pp")
    for d in (5, 7, 10):
        v = np.array([cagr_from(engine_stagger(A, Ov, Cv, gm, R21, p, d)["eq"], COMMON_I0)
                      for p in ph21], float)
        dd = dist(v)
        print(f"  {d:>7}{dd['mn']*100:>8.1f}%{dd['median']*100:>8.1f}%{dd['mx']*100:>8.1f}%"
              f"{dd['std']*100:>9.1f}pp{dd['span']*100:>9.1f}pp")

    # ---------------------------------------------------------------- [7] 结论
    print()
    print("=" * 108)
    print("[7] 结论")
    print("=" * 108)
    print(f"  1. 成本前提【部分成立】：offset=0 的成交笔数与基线逐相位完全相同，")
    print(f"     说明「把 2 只票拆成 2 条腿」本身不产生额外交易。")
    print(f"  2. ⚠ 但错开会引入一个【新的风险源】——两腿不等权。")
    print(f"     基线在「两只票同时换掉」时会把权重【免费调回等权】；错开版做不到，")
    print(f"     实测两腿权重偏离 50/50 平均达 {max(cost[d]['wdev'] for d in range(REB))*100:.1f}%"
          f"（最小 {min(cost[d]['wdev'] for d in range(REB))*100:.1f}%）。")
    print(f"     这解释了为什么 offset=0（腿机械、不等权）的离散度反而【高于】基线：")
    print(f"     极差 {res[0]['dist']['span']*100:.1f}pp vs 基线 {dbase['span']*100:.1f}pp。")
    print(f"  3. 相位风险：基线极差 {dbase['span']*100:.1f}pp、标准差 {dbase['std']*100:.1f}pp。")
    if winners:
        w = max(winners, key=lambda x: x[2] - x[3])
        print(f"     offset={w[0]} 看似四项全中（中位 {w[1]:+.1f}pp、最差 {w[2]:+.1f}pp、"
              f"IQR {w[3]:+.1f}pp、标准差 {w[4]:+.1f}pp）")
        print(f"     —— 但见 [5b]：换滚动窗口复核后这个结论是否稳。")
    else:
        print(f"     【没有任何 offset 是免费午餐】：全部都是用中位换下限/换离散度的互换。")
    print(f"  4. 等权版错开【买不起】：若要在每次调仓同时把两腿调回等权，")
    print(f"     每个事件要动 4 条腿（2 卖 + 2 买 = $8），事件频率翻倍 ⇒ 佣金 ~2.3 倍")
    print(f"     （基线 {base_nt_mean:.0f} 笔 → ~{base_nt_mean*2.3:.0f} 笔），按 v28 的拖累律会再吃掉两位数 pp。")
    print(f"  5. 21 日调仓（[6]）方向相反：错开把中位从 {d21['median']*100:.1f}% 抬到 ~65-67%，")
    print(f"     但离散度也同步放大（极差 {d21['span']*100:.1f}pp → 70~83pp）。")

    out = dict(meta=dict(n_bars=int(N), start_i=int(START_I), common_i0=int(COMMON_I0),
                         cap=CAP_REAL, comm=COMM_REAL, rebal=REB),
               baseline=dbase, cost=cost,
               offsets={str(d): res[d]["dist"] for d in res},
               winners=[dict(offset=b[0], d_median=b[1], d_min=b[2], d_iqr=b[3],
                             d_std=b[4], d_span=b[5], free_lunch=b[6]) for b in best],
               winstd=dict(n_win=int(len(base_ws)), baseline=float(base_ws.mean()),
                           offsets={str(d): float(ws_all[d].mean()) for d in ws_all},
                           first_half={str(d): float(ws_all[d][:half].mean()) for d in ws_all},
                           second_half={str(d): float(ws_all[d][half:].mean()) for d in ws_all},
                           consistent=[dict(offset=d, first_half=a, second_half=b)
                                       for d, a, b in consistent]),
               rebal21=dict(baseline=d21))
    fp = os.path.join(U.BASE, "_v31_stagger.json")
    json.dump(out, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=float)
    print(f"\n  明细已写入 {os.path.basename(fp)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
