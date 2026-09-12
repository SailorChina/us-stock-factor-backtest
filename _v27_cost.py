# -*- coding: utf-8 -*-
"""
v27: 把 Vortex Top2 @10日调仓 落成实盘方案前，先把【成本】算清楚。

本脚本不引用任何现成结论，自己按 v25.1 口径重跑引擎，然后：
  [1] 自证：复算出的终值必须对上 _rank_all.json 的官方数字（对不上就说明我算错了）
  [2] 统计：全换手口径下每年真实付出的佣金（笔数 x $2），以及占本金的比例
  [3] 量化：回测假设"每次调仓全部卖光再买回"，但实盘用【最小换手】可以省掉
      选票没变时的那一次无谓买卖 —— 这部分是回测【多收】的
  [4] 结论：10 日 vs 21 日，真实成本差多少；不同本金下的负担

用完可删（一次性分析脚本）。
"""
import os, sys, json
import numpy as np, pandas as pd

sys.argv = [sys.argv[0]]                      # 屏蔽外部参数，避免污染被导入模块的 arg()
import _update_signal as U

CAP = 3000.0
COMM = U.COMM
START = U.START
N = None


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
    return dates, A, Ov, Cv, gm


def engine(A, Ov, Cv, gm, rebal, mode="full", topk=2, cap=CAP):
    """v25.1 口径的最小复刻。mode='full' 复现回测；mode='min' 是实盘最小换手。"""
    RB = set(i for i in range(N) if i >= START and (i - START) % rebal == 0)
    cash, pos = cap, {}
    eq = np.full(N, np.nan); eq[:START] = cap
    n_sell = n_buy = n_reb = n_noop = 0
    prev_tgt = None
    same_pick = 0
    for i in range(START, N):
        if i in RB:
            js = i - 1
            n_reb += 1
            row = A[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx):
                idx = idx[gm[js, idx]]
            if len(idx) >= topk:
                tgt = list(idx[np.argsort(-row[idx])][:topk])
            else:
                tgt = []
            if prev_tgt is not None and set(tgt) == set(prev_tgt):
                same_pick += 1
            prev_tgt = list(tgt)

            if mode == "full":
                for j in list(pos):
                    pr = Ov[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += pos.pop(j) * pr - COMM; n_sell += 1
                if len(tgt) >= topk:
                    bud = max(0.0, (cash - topk * COMM) / topk)
                    for j in tgt:
                        pr = Ov[i, j]
                        if not np.isfinite(pr) or pr <= 0: continue
                        sh = bud / pr
                        if sh > 0:
                            pos[j] = sh; cash -= sh * pr + COMM; n_buy += 1
            else:
                # 实盘最小换手：只动【变了的那几条腿】，选票没变就一笔不交易
                if set(tgt) == set(pos) and len(pos) == len(tgt):
                    n_noop += 1
                else:
                    for j in list(pos):
                        if j in tgt: continue
                        pr = Ov[i, j]
                        if np.isfinite(pr) and pr > 0:
                            cash += pos.pop(j) * pr - COMM; n_sell += 1
                    newj = [j for j in tgt if j not in pos]
                    if newj:
                        bud = max(0.0, (cash - len(newj) * COMM) / len(newj))
                        for j in newj:
                            pr = Ov[i, j]
                            if not np.isfinite(pr) or pr <= 0: continue
                            sh = bud / pr
                            if sh > 0:
                                pos[j] = sh; cash -= sh * pr + COMM; n_buy += 1
        v = cash
        for j, sh in pos.items():
            p = Cv[i, j]
            if np.isfinite(p): v += sh * p
        eq[i] = v
    return dict(eq=eq, cash=cash, pos=pos, n_sell=n_sell, n_buy=n_buy, n_reb=n_reb,
                n_noop=n_noop, same_pick=same_pick,
                comm_total=(n_sell + n_buy) * COMM)


def stats(eq):
    e = eq[np.isfinite(eq)]
    yrs = (N - START) / 252.0
    final = float(e[-1])
    cagr = (final / CAP) ** (1 / yrs) - 1
    pk = np.maximum.accumulate(e)
    mdd = float((e / pk - 1).min())
    return final, cagr, mdd, yrs


def main():
    dates, A, Ov, Cv, gm = build()
    official = json.load(open(os.path.join(U.BASE, "_rank_all.json"), encoding="utf-8"))["results"]
    off = {}
    for nm, key in (("Vortex Top2", 21), ("Vortex Top2 @10日调仓", 10)):
        r = [x for x in official if x["name"] == nm][0]
        off[key] = r["m_on"]["final"]

    print("=" * 100)
    print("[1] 自证：我的复刻引擎必须对上 v26 官方数字")
    print("=" * 100)
    res = {}
    ok_all = True
    for rebal in (21, 10):
        r = engine(A, Ov, Cv, gm, rebal, mode="full")
        f, c, m, y = stats(r["eq"])
        rel = abs(f - off[rebal]) / off[rebal]
        ok = rel < 1e-6
        ok_all &= ok
        res[(rebal, "full")] = (r, f, c, m, y)
        print(f"  调仓 {rebal:>2}日  复刻终值 ${f:>12,.2f}  官方 ${off[rebal]:>12,.2f}  "
              f"相对差 {rel:.2e}  {'✅ 一致' if ok else '❌ 不一致'}")
    print(f"  → {'复刻引擎可信，下面的成本分解才有意义' if ok_all else '⚠ 复刻失败，停止'}")
    if not ok_all:
        return 1

    print()
    print("=" * 100)
    print("[2] 真实佣金：全换手口径（回测假设）")
    print("=" * 100)
    print(f"  本金 ${CAP:,.0f} ｜ 佣金 ${COMM:.0f}/笔（买卖各收）｜ 区间 {dates[START].date()} ~ {dates[-1].date()}")
    print(f"  {'口径':<12}{'调仓次数':>9}{'卖/买笔数':>11}{'总佣金':>12}{'每年佣金':>11}"
          f"{'占本金/年':>11}{'年化换手':>10}")
    print("  " + "-" * 80)
    for rebal in (21, 10):
        r, f, c, m, y = res[(rebal, "full")]
        per_yr = r["comm_total"] / y
        print(f"  {rebal:>2}日调仓{'':<4}{r['n_reb']:>9}{r['n_sell']:>6}/{r['n_buy']:<5}"
              f"${r['comm_total']:>11,.0f}${per_yr:>10,.0f}{per_yr/CAP*100:>10.2f}%"
              f"{r['n_buy']/y:>10.1f}")

    print()
    print("=" * 100)
    print("[3] 回测【多收】了多少：它假设每次调仓全部卖光再买回，哪怕选票没变")
    print("=" * 100)
    print(f"  {'口径':<12}{'调仓次数':>9}{'选票与上期相同':>15}{'相同率':>9}"
          f"{'空操作(0佣金)':>14}{'全换手佣金':>13}{'最小换手佣金':>14}{'省下':>10}")
    print("  " + "-" * 92)
    res_min = {}
    for rebal in (21, 10):
        rf = res[(rebal, "full")][0]
        rn = engine(A, Ov, Cv, gm, rebal, mode="min")
        res_min[rebal] = rn
        save = rf["comm_total"] - rn["comm_total"]
        print(f"  {rebal:>2}日调仓{'':<4}{rf['n_reb']:>9}{rf['same_pick']:>15}"
              f"{rf['same_pick']/rf['n_reb']*100:>8.1f}%{rn['n_noop']:>14}"
              f"${rf['comm_total']:>12,.0f}${rn['comm_total']:>13,.0f}"
              f"${save:>9,.0f} ({save/rf['comm_total']*100:.0f}%)")

    print()
    print("=" * 100)
    print("[4] 最小换手下的真实业绩（这才是你实际能拿到的口径）")
    print("=" * 100)
    print(f"  {'口径':<20}{'终值':>14}{'CAGR':>9}{'最大回撤':>10}{'总佣金':>11}{'每年佣金':>10}{'占本金/年':>10}")
    print("  " + "-" * 84)
    for rebal in (21, 10):
        for mode, tag in (("full", f"{rebal}日·回测口径"), ("min", f"{rebal}日·最小换手")):
            if mode == "full":
                r, f, c, m, y = res[(rebal, "full")]
            else:
                r = res_min[rebal]; f, c, m, y = stats(r["eq"])
            per_yr = r["comm_total"] / y
            print(f"  {tag:<20}${f:>13,.0f}{c*100:>8.1f}%{m*100:>9.1f}%"
                  f"${r['comm_total']:>10,.0f}${per_yr:>9,.0f}{per_yr/CAP*100:>9.2f}%")

    print()
    print("=" * 100)
    print("[5] 不同本金下，10 日调仓的佣金负担（最小换手口径，按第一年 25 次调仓估）")
    print("=" * 100)
    rn = res_min[10]
    reb_per_yr = rn["n_reb"] / stats(rn["eq"])[3]
    print(f"  10 日调仓 = 每年约 {reb_per_yr:.1f} 次调仓")
    print(f"  {'本金':>10}{'每次调仓佣金':>14}{'每年佣金':>12}{'占本金/年':>12}")
    print("  " + "-" * 50)
    for cap in (1490.49, 3000.0, 5000.0, 10000.0, 30000.0):
        per = reb_per_yr * 2 * 2 * COMM          # 2 只 x (卖+买) x $2
        print(f"  ${cap:>9,.0f}${4*COMM:>13,.0f}${per:>11,.0f}{per/cap*100:>11.2f}%")
    print("  注：这是【上限】估计 —— 假设每次都换股。实测选票相同率见 [3]，")
    print("      真实情况介于最小换手与全换手之间。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
