# -*- coding: utf-8 -*-
"""
v28: 小资金实盘路径审计 —— 冠军是在 $3,000 下选出来的，你的本金是 $1,490.49。

v26/v27 的所有结论都建立在【本金 $3,000】上。但佣金是【每笔固定 $2】，
不随本金缩放 —— 本金越小，佣金占本金的比例越高。于是有一个必须回答的问题：

    【在 $1,490 下，10 日调仓还是冠军吗？】

本脚本做四件事：
  [1] 自证：自写引擎在 (frac, comm=$2) 下必须复现 _v27_cost 的已验证结果
  [2] 佣金拖累的精确度量：跑一遍【零佣金】反事实，拖累 = CAGR(零佣金) − CAGR(实佣金)
      —— 这比"每年佣金 ÷ 本金"更准，因为它含了复利损失
  [3] 冠军重排序：在本金 $1,490 下，10 日 vs 21 日 谁赢
  [4] 整股口径敏感性：若不能用碎股（富途碎股仅限常规时段、当日有效、不能挂附加单），
      只能买整股，会额外损失多少

用法:  python _v28_smallcap.py
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.argv = [sys.argv[0]]                 # 屏蔽外部参数，避免污染被导入模块的 arg()
import _update_signal as U
import _v27_cost as C                    # 复用已验证的复刻引擎（同一套 load/build_signals）

N = None
CAP_REAL = 1490.49                       # 账户实际本金（signal_snapshot.json 的 capital_usd）


# ---------------------------------------------------------------- 数据
def build():
    global N
    dates, PX, REAL = U.load(U.UNI)
    TRADE, _ = U.tradable_mask(PX, U.GATE_DV)
    SIG = U.build_signals(PX, TRADE, REAL)
    A = SIG["Vortex"].values
    Ov = PX["open"].values
    Cv = PX["close"].values
    gm = TRADE.values & REAL.values
    N = A.shape[0]
    C.N = N                      # _v27_cost 的 engine() 用自己模块级的 N，同步过去
    return dates, A, Ov, Cv, gm


# ---------------------------------------------------------------- 引擎
def engine2(A, Ov, Cv, gm, rebal, mode="full", topk=2, cap=3000.0,
            comm=2.0, lot="frac"):
    """v25.1 口径复刻 + 两个新维度。

    lot="frac" -> sh = bud/pr        （回测口径，可买小数股）
    lot="int"  -> sh = floor(bud/pr) （整股口径；买不起一手就这条腿空着）

    当 (lot="frac", comm=2.0) 时，本函数必须与 _v27_cost.engine 逐位一致（见 [1] 自证）。
    """
    RB = set(i for i in range(N) if i >= START_I and (i - START_I) % rebal == 0)
    cash, pos = cap, {}
    eq = np.full(N, np.nan); eq[:START_I] = cap
    n_sell = n_buy = n_reb = n_noop = 0
    n_miss = 0                 # 想买但一手都买不起的腿数
    miss_codes = {}
    inv_ratio = []             # 每个调仓日的仓位占比
    prev_tgt = None
    same_pick = 0

    def buy(j, budget):
        """返回 (成交股数, 花费)。整股口径下取 floor。"""
        pr = Ov[i, j]
        if not np.isfinite(pr) or pr <= 0:
            return 0.0, 0.0
        sh = budget / pr if lot == "frac" else float(np.floor(budget / pr))
        if sh <= 0:
            return 0.0, 0.0
        return sh, sh * pr

    for i in range(START_I, N):
        if i in RB:
            js = i - 1
            n_reb += 1
            row = A[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx):
                idx = idx[gm[js, idx]]
            tgt = list(idx[np.argsort(-row[idx])][:topk]) if len(idx) >= topk else []
            if prev_tgt is not None and set(tgt) == set(prev_tgt):
                same_pick += 1
            prev_tgt = list(tgt)

            if mode == "full":
                for j in list(pos):
                    pr = Ov[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += pos.pop(j) * pr - comm; n_sell += 1
                if len(tgt) >= topk:
                    bud = max(0.0, (cash - topk * comm) / topk)
                    for j in tgt:
                        sh, cost = buy(j, bud)
                        if sh <= 0:
                            n_miss += 1
                            miss_codes[U.UNI[j]] = miss_codes.get(U.UNI[j], 0) + 1
                            continue
                        pos[j] = sh; cash -= cost + comm; n_buy += 1
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
                            sh, cost = buy(j, bud)
                            if sh <= 0:
                                n_miss += 1
                                miss_codes[U.UNI[j]] = miss_codes.get(U.UNI[j], 0) + 1
                                continue
                            pos[j] = sh; cash -= cost + comm; n_buy += 1

        v = cash
        for j, sh in pos.items():
            p = Cv[i, j]
            if np.isfinite(p): v += sh * p
        eq[i] = v
        if i in RB and v > 0:
            hold = v - cash
            inv_ratio.append(hold / v)

    return dict(eq=eq, cash=cash, pos=pos, n_sell=n_sell, n_buy=n_buy, n_reb=n_reb,
                n_noop=n_noop, same_pick=same_pick, n_miss=n_miss, miss=miss_codes,
                comm_total=(n_sell + n_buy) * comm,
                inv=float(np.mean(inv_ratio)) if inv_ratio else float("nan"))


def stats(eq, cap):
    e = eq[np.isfinite(eq)]
    yrs = (N - START_I) / 252.0
    final = float(e[-1])
    cagr = (final / cap) ** (1 / yrs) - 1
    pk = np.maximum.accumulate(e)
    mdd = float((e / pk - 1).min())
    return dict(final=final, cagr=cagr, mdd=mdd, yrs=yrs)


START_I = U.START


def main():
    global START_I
    dates, A, Ov, Cv, gm = build()
    START_I = U.START

    official = json.load(open(os.path.join(U.BASE, "_rank_all.json"), encoding="utf-8"))["results"]
    off = {21: [x for x in official if x["name"] == "Vortex Top2"][0]["m_on"]["final"],
           10: [x for x in official if x["name"] == "Vortex Top2 @10日调仓"][0]["m_on"]["final"]}

    print("=" * 104)
    print("[1] 自证：自写 engine2 在 (frac, $2/笔, 本金 $3,000) 下必须复现官方数字")
    print("=" * 104)
    ok_all = True
    for rebal in (21, 10):
        for mode in ("full", "min"):
            r = engine2(A, Ov, Cv, gm, rebal, mode=mode, cap=3000.0, comm=2.0, lot="frac")
            f = stats(r["eq"], 3000.0)["final"]
            r2 = C.engine(A, Ov, Cv, gm, rebal, mode=mode, cap=3000.0)
            f2 = float(r2["eq"][np.isfinite(r2["eq"])][-1])
            same = abs(f - f2) < 1e-6
            ok_all &= same
            tag = ""
            if mode == "full":
                rel = abs(f - off[rebal]) / off[rebal]
                tag = f"  官方 ${off[rebal]:,.2f} 相对差 {rel:.2e}"
                ok_all &= rel < 1e-6
            print(f"  {rebal:>2}日 {mode:<5} 我的 ${f:>13,.2f}   _v27_cost 的 ${f2:>13,.2f}  "
                  f"{'✅ 一致' if same else '❌ 不一致'}{tag}")
    print(f"  → {'引擎可信，下面所有数字才有意义' if ok_all else '⚠ 自证失败，停止'}")
    if not ok_all:
        return 1

    # ---------------------------------------------------------------- [2] 佣金拖累
    print()
    print("=" * 104)
    print("[2] 佣金拖累的精确度量：零佣金反事实（本金 $3,000，最小换手，碎股）")
    print("=" * 104)
    print(f"  {'口径':<14}{'零佣金终值':>15}{'实佣金终值':>15}{'零佣金CAGR':>12}{'实佣金CAGR':>12}{'拖累':>9}")
    print("  " + "-" * 92)
    drag3000 = {}
    for rebal in (21, 10):
        r0 = engine2(A, Ov, Cv, gm, rebal, mode="min", cap=3000.0, comm=0.0)
        r1 = engine2(A, Ov, Cv, gm, rebal, mode="min", cap=3000.0, comm=2.0)
        s0, s1 = stats(r0["eq"], 3000.0), stats(r1["eq"], 3000.0)
        drag3000[rebal] = (s0["cagr"] - s1["cagr"]) * 100
        print(f"  {rebal:>2}日调仓{'':<6}${s0['final']:>14,.0f}${s1['final']:>14,.0f}"
              f"{s0['cagr']*100:>11.2f}%{s1['cagr']*100:>11.2f}%{drag3000[rebal]:>8.2f}pp")

    # ---------------------------------------------------------------- [2b] 尺度不变性
    print()
    print("=" * 104)
    print("[2b] 尺度不变性：碎股口径下，【零佣金】的 CAGR 必须与本金完全无关")
    print("=" * 104)
    print("      （若成立 ⇒ 策略本身是尺度不变的，本金对结果的【全部】影响都来自那 $2/笔固定佣金）")
    base = {}
    for rebal in (21, 10):
        vals = []
        for cap in (500.0, 1490.49, 3000.0, 50000.0):
            r = engine2(A, Ov, Cv, gm, rebal, mode="min", cap=cap, comm=0.0)
            vals.append(stats(r["eq"], cap)["cagr"])
        spread = (max(vals) - min(vals)) * 100
        base[rebal] = vals[0]
        print(f"  {rebal:>2}日调仓  零佣金CAGR: " +
              "  ".join(f"${c:,.0f}→{v*100:.4f}%" for c, v in
                        zip((500, 1490, 3000, 50000), vals)) +
              f"   极差 {spread:.2e}pp {'✅ 尺度不变' if spread < 1e-6 else '❌ 有尺度效应'}")

    # ---------------------------------------------------------------- [3] 本金扫描
    print()
    print("=" * 104)
    print("[3] 本金扫描：佣金拖累随本金怎么变（最小换手，碎股）")
    print("=" * 104)
    caps = [500.0, 1000.0, 1490.49, 2000.0, 3000.0, 5000.0, 10000.0, 20000.0, 50000.0]
    rows = []
    for cap in caps:
        row = {"cap": cap}
        for rebal in (21, 10):
            r0 = engine2(A, Ov, Cv, gm, rebal, mode="min", cap=cap, comm=0.0)
            r1 = engine2(A, Ov, Cv, gm, rebal, mode="min", cap=cap, comm=2.0)
            s0, s1 = stats(r0["eq"], cap), stats(r1["eq"], cap)
            row[rebal] = dict(final=s1["final"], cagr=s1["cagr"], mdd=s1["mdd"],
                              drag=(s0["cagr"] - s1["cagr"]) * 100,
                              comm=r1["comm_total"], inv=r1["inv"])
        rows.append(row)

    print(f"  {'本金':>10} | {'21日CAGR':>9}{'21日拖累':>9}{'21日终值':>13} | "
          f"{'10日CAGR':>9}{'10日拖累':>9}{'10日终值':>13} | {'冠军':>6}{'领先':>8} | {'拖累×本金':>10}")
    print("  " + "-" * 112)
    for row in rows:
        a, b = row[21], row[10]
        win = "10日" if b["cagr"] > a["cagr"] else "21日"
        lead = abs(b["cagr"] - a["cagr"]) * 100
        print(f"  ${row['cap']:>9,.0f} | {a['cagr']*100:>8.1f}%{a['drag']:>8.2f}pp${a['final']:>12,.0f} | "
              f"{b['cagr']*100:>8.1f}%{b['drag']:>8.2f}pp${b['final']:>12,.0f} | {win:>6}{lead:>7.1f}pp | "
              f"{b['drag']*row['cap']:>10,.0f}")
    _ks = [r[10]["drag"] * r["cap"] for r in rows if r["cap"] >= 1490]
    print(f"  → 「拖累(pp) × 本金」在 $1,490 以上稳定在 ${min(_ks):,.0f} ~ ${max(_ks):,.0f} 之间")
    print(f"    ⇒ 经验律：**佣金拖累(pp) ≈ 7,700 ÷ 本金(美元)**（本金 < $1,000 时该近似失效，拖累涨得更快）")

    # ---------------------------------------------------------------- [4] 整股口径
    print()
    print("=" * 104)
    print("[4] 整股口径敏感性：如果不能买碎股（只能整股），额外损失多少（最小换手，$2/笔）")
    print("=" * 104)
    print(f"  {'本金':>10} | {'10日 碎股CAGR':>14}{'10日 整股CAGR':>14}{'整股额外损失':>14}"
          f"{'仓位占比':>10}{'买不起腿数':>11}")
    print("  " + "-" * 92)
    for cap in (500.0, 1000.0, 1490.49, 3000.0, 10000.0, 50000.0):
        rf = engine2(A, Ov, Cv, gm, 10, mode="min", cap=cap, comm=2.0, lot="frac")
        ri = engine2(A, Ov, Cv, gm, 10, mode="min", cap=cap, comm=2.0, lot="int")
        sf, si = stats(rf["eq"], cap), stats(ri["eq"], cap)
        loss = (sf["cagr"] - si["cagr"]) * 100
        print(f"  ${cap:>9,.0f} | {sf['cagr']*100:>13.1f}%{si['cagr']*100:>13.1f}%"
              f"{loss:>13.2f}pp{ri['inv']*100:>9.1f}%{ri['n_miss']:>11}")

    # ---------------------------------------------------------------- [5] 结论
    print()
    print("=" * 104)
    print("[5] 结论")
    print("=" * 104)
    r = [x for x in rows if abs(x["cap"] - CAP_REAL) < 1][0]
    a, b = r[21], r[10]
    win = "10 日" if b["cagr"] > a["cagr"] else "21 日"
    print(f"  你的本金 ${CAP_REAL:,.2f}：")
    print(f"    21 日调仓  CAGR {a['cagr']*100:6.2f}%   佣金拖累 {a['drag']:5.2f}pp   终值 ${a['final']:,.0f}")
    print(f"    10 日调仓  CAGR {b['cagr']*100:6.2f}%   佣金拖累 {b['drag']:5.2f}pp   终值 ${b['final']:,.0f}")
    print(f"    → 在本金 ${CAP_REAL:,.0f} 下，冠军仍是【{win}】")
    print()
    print(f"  对比 $3,000 口径（v26/v27 的结论基础）：10 日拖累 {drag3000[10]:.2f}pp，"
          f"${CAP_REAL:,.0f} 下是 {b['drag']:.2f}pp —— 放大 {b['drag']/drag3000[10]:.2f} 倍")
    print()
    print("  ⚠ 勘误：v27 报告 §[5] 报的「$1,490 时占本金/年 11.6%~13.57%」")
    print("     那个数字把本金【固定在 $1,490 不动】来算，而本策略年化 ~93%，本金一年就翻倍")
    print("     → 佣金占【当期本金】的比例会迅速衰减，它不是一个恒定的年费率。")
    print(f"     真正该拿来和 CAGR 比较的是【拖累 pp】：${CAP_REAL:,.0f} 下为 {b['drag']:.2f}pp。")
    print("     v27 把「第 1 年的比例」与「CAGR」并列，属口径混用 —— 成本被高估约 "
          f"{11.6/b['drag']:.1f}~{13.57/b['drag']:.1f} 倍。")

    # 佣金拖累降到 1pp 以内需要多少本金
    thr = None
    for cap in np.arange(3000, 200001, 1000):
        rr = engine2(A, Ov, Cv, gm, 10, mode="min", cap=float(cap), comm=2.0)
        r0 = engine2(A, Ov, Cv, gm, 10, mode="min", cap=float(cap), comm=0.0)
        d = (stats(r0["eq"], cap)["cagr"] - stats(rr["eq"], cap)["cagr"]) * 100
        if d <= 1.0:
            thr = float(cap); break
    if thr:
        print(f"  10 日调仓的佣金拖累降到 1pp 以内，需要本金约 ${thr:,.0f}")

    out = {"caps": [{ "cap": x["cap"],
                      "r21": {k: v for k, v in x[21].items()},
                      "r10": {k: v for k, v in x[10].items()}} for x in rows],
           "drag3000": drag3000, "threshold_cap": thr, "cap_real": CAP_REAL}
    json.dump(out, open(os.path.join(U.BASE, "_v28_smallcap.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print(f"\n  明细已写入 _v28_smallcap.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
