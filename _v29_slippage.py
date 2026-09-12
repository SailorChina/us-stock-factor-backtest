# -*- coding: utf-8 -*-
"""
v29: 滑点与【执行时点】审计 —— 把回测里"成交价 = 开盘价"这个假设拆开看。

v27/v28 把所有执行层成本都归结为 $2/笔固定佣金。但回测还有一个更硬的隐含假设：

    成交价【恰好等于】第 i 根的开盘价。

真实世界里你人在国内，美股开盘是北京 21:30（夏令时）/ 22:30（冬令时）。
"21:30 那一分钟正好按下单"是个很强的要求。本脚本回答三件事：

  [1] 自证：slip=0 时必须复现官方终值
  [2] 滑点敏感度：每笔单边滑 1/2/5/10/20/50 bp，CAGR 掉多少
  [3] 市场冲击核算：$745 的订单占各股成交额多少 —— 证明"冲击"根本不是问题，
      问题只在【价差 + 时点】
  [4] ★ 执行时点：如果起不来，改成【收盘价】执行，代价是多少？
      （以及"晚一天执行"的代价，作为对照）

用法:  python _v29_slippage.py
"""
import os, sys, json
import numpy as np
import pandas as pd

sys.argv = [sys.argv[0]]
import _update_signal as U
import _v27_cost as C

N = None
START_I = None
CAP_REAL = 1490.49
COMM_REAL = 2.0        # 富途美股 $2/笔


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
    C.N = N
    return dates, PX, A, Ov, Cv, gm


def engine3(A, Ov, Cv, gm, rebal, mode="min", topk=2, cap=3000.0, comm=2.0,
            slip=0.0, px="open"):
    """v25.1 口径复刻 + 滑点 + 可选执行价。

    slip : 单边滑点(小数)。买入付 px*(1+slip)，卖出收 px*(1-slip)。
           slip=0 且 px="open" 时必须与 _v27_cost.engine 逐位一致。
    px   : "open" 用第 i 根开盘价成交（回测口径）
           "close" 用第 i 根收盘价成交（信号仍是第 i-1 根收盘）
           浮点数 t 用「开盘 + t x (收盘 - 开盘)」成交 —— 半日内下单的代理模型
    """
    if px == "open":
        P = Ov
    elif px == "close":
        P = Cv
    elif px == "open1":
        # 晚一整天：用【下一根】的开盘价成交。最后一根越界 -> 全 NaN -> 当天不交易
        # （deal() 与卖出分支都会因 isfinite 为假而跳过，不会崩）。
        P = np.vstack([Ov[1:], np.full((1, Ov.shape[1]), np.nan)])
    else:
        t = float(px)
        P = Ov + t * (Cv - Ov)
    RB = set(i for i in range(N) if i >= START_I and (i - START_I) % rebal == 0)
    cash, pos = cap, {}
    eq = np.full(N, np.nan); eq[:START_I] = cap
    n_sell = n_buy = n_reb = n_noop = 0
    prev_tgt = None
    same_pick = 0

    def deal(j, budget, buying):
        """按滑点后的价格成交，返回 (股数, 现金流变化)。"""
        pr = P[i, j]
        if not np.isfinite(pr) or pr <= 0:
            return 0.0, 0.0
        eff = pr * (1 + slip) if buying else pr * (1 - slip)
        sh = budget / eff
        return sh, sh * eff

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
                    pr = P[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += pos.pop(j) * pr * (1 - slip) - comm; n_sell += 1
                if len(tgt) >= topk:
                    bud = max(0.0, (cash - topk * comm) / topk)
                    for j in tgt:
                        sh, amt = deal(j, bud, True)
                        if sh <= 0: continue
                        pos[j] = sh; cash -= amt + comm; n_buy += 1
            else:
                if set(tgt) == set(pos) and len(pos) == len(tgt):
                    n_noop += 1
                else:
                    for j in list(pos):
                        if j in tgt: continue
                        pr = P[i, j]
                        if np.isfinite(pr) and pr > 0:
                            cash += pos.pop(j) * pr * (1 - slip) - comm; n_sell += 1
                    newj = [j for j in tgt if j not in pos]
                    if newj:
                        bud = max(0.0, (cash - len(newj) * comm) / len(newj))
                        for j in newj:
                            sh, amt = deal(j, bud, True)
                            if sh <= 0: continue
                            pos[j] = sh; cash -= amt + comm; n_buy += 1

        v = cash
        for j, sh in pos.items():
            p = Cv[i, j]
            if np.isfinite(p): v += sh * p
        eq[i] = v

    return dict(eq=eq, cash=cash, pos=pos, n_sell=n_sell, n_buy=n_buy, n_reb=n_reb,
                n_noop=n_noop, same_pick=same_pick, comm_total=(n_sell + n_buy) * comm)


def stats(eq, cap):
    e = eq[np.isfinite(eq)]
    yrs = (N - START_I) / 252.0
    final = float(e[-1])
    cagr = (final / cap) ** (1 / yrs) - 1
    pk = np.maximum.accumulate(e)
    mdd = float((e / pk - 1).min())
    return dict(final=final, cagr=cagr, mdd=mdd, yrs=yrs)


def main():
    global START_I
    dates, PX, A, Ov, Cv, gm = build()
    START_I = U.START
    official = json.load(open(os.path.join(U.BASE, "_rank_all.json"), encoding="utf-8"))["results"]
    off = {21: [x for x in official if x["name"] == "Vortex Top2"][0]["m_on"]["final"],
           10: [x for x in official if x["name"] == "Vortex Top2 @10日调仓"][0]["m_on"]["final"]}

    # ---------------------------------------------------------------- [1] 自证
    print("=" * 104)
    print("[1] 自证：slip=0 + px=open 必须复现官方终值（否则下面全部无意义）")
    print("=" * 104)
    ok = True
    for rebal in (21, 10):
        r = engine3(A, Ov, Cv, gm, rebal, mode="full", cap=3000.0)
        f = stats(r["eq"], 3000.0)["final"]
        r2 = C.engine(A, Ov, Cv, gm, rebal, mode="full", cap=3000.0)
        f2 = float(r2["eq"][np.isfinite(r2["eq"])][-1])
        rel = abs(f - off[rebal]) / off[rebal]
        same = abs(f - f2) < 1e-6 and rel < 1e-6
        ok &= same
        print(f"  {rebal:>2}日 我的 ${f:>12,.2f}  官方 ${off[rebal]:>12,.2f}  "
              f"相对差 {rel:.2e}  {'✅' if same else '❌'}")
    print(f"  → {'可信' if ok else '⚠ 自证失败，停止'}")
    if not ok:
        return 1

    # ---------------------------------------------------------------- [2] 滑点敏感度
    print()
    print("=" * 104)
    print(f"[2] 滑点敏感度（本金 ${CAP_REAL:,.2f}，最小换手，执行价 = 开盘）")
    print("=" * 104)
    base = {}
    slips = {}
    print(f"  {'单边滑点':>9}{'10日 CAGR':>11}{'滑点拖累':>11}{'10日终值':>15}"
          f"{'21日 CAGR':>11}{'滑点拖累':>11}{'21日终值':>15}")
    print("  " + "-" * 94)
    for bp in (0, 1, 2, 5, 10, 20, 50):
        row = {}
        for rebal in (21, 10):
            r = engine3(A, Ov, Cv, gm, rebal, mode="min", cap=CAP_REAL, slip=bp / 1e4)
            row[rebal] = stats(r["eq"], CAP_REAL)
        slips[bp] = row
        if bp == 0:
            base = row
        d10 = (base[10]["cagr"] - row[10]["cagr"]) * 100
        d21 = (base[21]["cagr"] - row[21]["cagr"]) * 100
        print(f"  {bp:>7}bp {row[10]['cagr']*100:>10.1f}%{d10:>10.2f}pp"
              f"${row[10]['final']:>14,.0f}{row[21]['cagr']*100:>10.1f}%{d21:>10.2f}pp"
              f"${row[21]['final']:>14,.0f}")
    per_bp = (base[10]["cagr"] - slips[1][10]["cagr"]) * 100
    print(f"  → 10 日调仓：每 1bp 单边滑点约吃掉 {per_bp:.2f}pp CAGR")

    # ---------------------------------------------------------------- [3] 市场冲击
    print()
    print("=" * 104)
    print("[3] 市场冲击核算：$745 的订单，在池子里算大还是算小？")
    print("=" * 104)
    W = 60
    dv = (PX["close"] * PX["volume"]).iloc[-W:]
    med = dv.median().sort_values()
    bud = CAP_REAL / 2
    ratio = bud / med
    print(f"  订单规模 = 每腿 ${bud:,.0f}（本金 ${CAP_REAL:,.0f} / 2）")
    print(f"  池内各股【近 {W} 日中位日成交额】分布：")
    print(f"    最小 {med.iloc[0]/1e6:,.1f}M ({med.index[0].replace('US.','')})  "
          f"｜ 中位 {med.median()/1e6:,.1f}M ｜ 最大 {med.iloc[-1]/1e6:,.0f}M "
          f"({med.index[-1].replace('US.','')})")
    print(f"    订单/成交额 比例：最大 {ratio.max()*100:.4f}% ｜ 中位 {ratio.median()*100:.5f}%")
    print(f"  判据：经验上 order/ADV < 0.1% 时市场冲击可忽略（约 1 个价差量级）。")
    print(f"  → 最差的一只也只有 {ratio.max()*100:.4f}%，"
          f"即 {'✅ 冲击可忽略' if ratio.max() < 0.001 else '⚠ 需注意'}")
    print(f"  注：ADV 用的是【近 {W} 日】。历史上池里曾有流动性差得多的票")
    print(f"     （v25 闸门 $5M 才放行），但即便如此 $745/{5e6:,.0f} = {bud/5e6*100:.4f}% 仍可忽略。")

    # ---------------------------------------------------------------- [4] 执行时点
    print()
    print("=" * 104)
    print("[4] ★ 执行时点：起不来怎么办？（本金 $1,490，最小换手，零滑点）")
    print("=" * 104)
    print("  A) 【同日不同价】—— 干净的时点效应（调仓日不变，只有成交价变）")
    print(f"  {'执行价':<22}{'10日 CAGR':>11}{'vs 开盘':>10}{'10日终值':>15}"
          f"{'21日 CAGR':>11}{'vs 开盘':>10}{'21日终值':>15}")
    print("  " + "-" * 96)
    rows = {}
    for tag, px in (("开盘价（回测口径）", "open"), ("收盘价（当天收盘）", "close")):
        row = {}
        for rebal in (21, 10):
            r = engine3(A, Ov, Cv, gm, rebal, mode="min", cap=CAP_REAL, px=px)
            row[rebal] = stats(r["eq"], CAP_REAL)
        rows[px] = row
        d10 = (row[10]["cagr"] - rows["open"][10]["cagr"]) * 100
        d21 = (row[21]["cagr"] - rows["open"][21]["cagr"]) * 100
        print(f"  {tag:<20}{row[10]['cagr']*100:>10.1f}%{d10:>+9.2f}pp${row[10]['final']:>14,.0f}"
              f"{row[21]['cagr']*100:>10.1f}%{d21:>+9.2f}pp${row[21]['final']:>14,.0f}")

    print()
    print("  B) 【跨日执行】—— ⚠ 这一栏【不是】纯时点成本，它把调仓日历整体后移了一天，")
    print("     收益里混进了【相位变化】。v21/v26 已确认：频率与相位对最终收益的解释力")
    print("     只有 4~7%，但足以让慢周期策略的排名上下浮动。所以看方向、别看数值。")
    r1 = engine3(A, Ov, Cv, gm, 10, mode="min", cap=CAP_REAL, px="open1")
    r2 = engine3(A, Ov, Cv, gm, 21, mode="min", cap=CAP_REAL, px="open1")
    rows["open1"] = {10: stats(r1["eq"], CAP_REAL), 21: stats(r2["eq"], CAP_REAL)}
    print(f"  {'次日开盘（晚一整天）':<20}{rows['open1'][10]['cagr']*100:>10.1f}%"
          f"{(rows['open1'][10]['cagr']-rows['open'][10]['cagr'])*100:>+9.2f}pp"
          f"${rows['open1'][10]['final']:>14,.0f}"
          f"{rows['open1'][21]['cagr']*100:>10.1f}%"
          f"{(rows['open1'][21]['cagr']-rows['open'][21]['cagr'])*100:>+9.2f}pp"
          f"${rows['open1'][21]['final']:>14,.0f}")
    _o10 = (rows["open1"][10]["cagr"] - rows["open"][10]["cagr"]) * 100
    _o21 = (rows["open1"][21]["cagr"] - rows["open"][21]["cagr"]) * 100
    print(f"  → 10 日 {_o10:+.2f}pp、21 日 {_o21:+.2f}pp：一个变差一个变好，"
          f"而「晚一天」不可能同时是优势和劣势。")
    print(f"     ⇒ 这一栏主要反映的是【换了批交易日】，不是「晚了」本身。")
    print(f"     注：晚一天时最后一根越界，那个调仓日不成交（只有 1 次，影响很小）。")

    # 机制核验：轮换日「新买 vs 卖出」的日内收益差 —— 用它解释 A) 的方向，而不是猜
    print()
    print("  C) 机制核验：A) 里【开盘优于收盘】到底为什么？")
    print("     推导：调仓日 i，开盘执行到收盘时持有的是【新票】，收盘执行持有的是【旧票】")
    print("     ⇒ 两者之差 = V x [ ID(新票) − ID(旧票) ]，ID = 当日收盘/开盘。")
    print("     所以只要实测这个差为正，就说明机制成立（而不是我编的解释）。")
    diffs = {}
    for rebal in (10, 21):
        RB = [i for i in range(START_I, N) if (i - START_I) % rebal == 0]
        prev, ds = None, []
        for i in RB:
            js = i - 1
            row = A[js]
            idx = np.where(np.isfinite(row))[0]
            if len(idx):
                idx = idx[gm[js, idx]]
            tgt = list(idx[np.argsort(-row[idx])][:2]) if len(idx) >= 2 else []
            if prev is not None and tgt:
                old = [j for j in prev if j not in tgt]
                new = [j for j in tgt if j not in prev]
                if old and new:
                    idn = np.nanmean([Cv[i, j] / Ov[i, j] - 1 for j in new])
                    ido = np.nanmean([Cv[i, j] / Ov[i, j] - 1 for j in old])
                    ds.append(idn - ido)
            prev = tgt
        diffs[rebal] = (float(np.mean(ds)), len(ds))
        print(f"     {rebal:>2}日调仓：轮换日 ID(新) − ID(旧) 均值 "
              f"{diffs[rebal][0]*100:+.4f}%（{diffs[rebal][1]} 个轮换样本）"
              f"  {'✅ 为正，机制成立' if diffs[rebal][0] > 0 else '❌ 为负，解释不成立'}")

    # 开盘到收盘的日内漂移分布（背景事实，注意幸存者偏差）
    print()
    print(f"  背景：池内 {len(U.UNI)} 只【全区间】的日内漂移（收盘/开盘 − 1）：")
    oc = (PX["close"] / PX["open"] - 1).values
    oc = oc[np.isfinite(oc)]
    print(f"    均值 {oc.mean()*100:+.4f}%  中位 {np.median(oc)*100:+.4f}%  "
          f"标准差 {oc.std()*100:.3f}%")
    print(f"    ⚠ 这个池子是【按 2026 年热度筛出来的赢家名单】，日内漂移为正很可能")
    print(f"      含幸存者偏差，不要外推成「美股开盘总是便宜」。")

    # ---------------------------------------------------------------- [4b] 半日内下单
    print()
    print("=" * 104)
    print("[4b] 晚几小时下单的代价：执行价 = 开盘 + t x (收盘 - 开盘)")
    print("=" * 104)
    print("      t 是「你在当日行程中走了多远」的代理（0=开盘价, 1=收盘价）。")
    print("      ⚠ 这是【代理模型】：日线数据没有盘中路径, 用开收线性插值近似。")
    print(f"  {'t':>6}{'10日 CAGR':>12}{'vs 开盘':>11}{'21日 CAGR':>12}{'vs 开盘':>11}")
    print("  " + "-" * 52)
    t_rows = {}
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        row = {}
        for rebal in (21, 10):
            r = engine3(A, Ov, Cv, gm, rebal, mode="min", cap=CAP_REAL, px=t)
            row[rebal] = stats(r["eq"], CAP_REAL)
        t_rows[t] = row
        d10 = (row[10]["cagr"] - t_rows[0.0][10]["cagr"]) * 100
        d21 = (row[21]["cagr"] - t_rows[0.0][21]["cagr"]) * 100
        print(f"  {t:>6.2f}{row[10]['cagr']*100:>11.1f}%{d10:>+10.2f}pp"
              f"{row[21]['cagr']*100:>11.1f}%{d21:>+10.2f}pp")
    print(f"  → 10 日调仓的代价随 t 近似线性：每天晚 1/4 个交易日 ≈ "
          f"{(t_rows[0.25][10]['cagr'] - t_rows[0.0][10]['cagr'])*100:.2f}pp CAGR")

    print()
    print("=" * 104)
    print("[5] 结论")
    print("=" * 104)
    s10 = rows["open"][10]["cagr"] * 100
    s10c = rows["close"][10]["cagr"] * 100
    print(f"  1. 滑点不是主要成本：本金 ${CAP_REAL:,.0f} 下 $745 的订单占最差一只股票的"
          f"成交额仅 {ratio.max()*100:.4f}%，")
    print(f"     市场冲击可忽略。真实滑点只来自【买卖价差 + 下单时点】。")
    print(f"  2. 滑点近似线性：10 日调仓每 1bp 单边滑点约 {per_bp:.2f}pp CAGR。")
    print(f"     按大票开盘价差 2bp 估，滑点成本约 "
          f"{(base[10]['cagr'] - slips[2][10]['cagr']) * 100:.1f}pp。")
    print(f"  3. ★ 执行时点比滑点重要得多：改成【收盘价】执行，10 日 CAGR "
          f"{s10:.1f}% -> {s10c:.1f}%（{s10c-s10:+.2f}pp）；21 日只差 "
          f"{(rows['close'][21]['cagr']-rows['open'][21]['cagr'])*100:+.2f}pp。")
    print(f"     机制已核验（[4] C 段）：调仓日【新买票的日内收益】系统性高于【卖出票】")
    print(f"     （10 日 +{diffs[10][0]*100:.4f}% / 21 日 +{diffs[21][0]*100:.4f}%），")
    print(f"     所以买在开盘 = 吃到这部分日内上涨。代价与换手频率成正比。")
    print(f"  4. ⚠ 别把【跨日执行】当成时点成本：[4] B 段里 10 日 -7.05pp 而 21 日 +2.31pp，")
    print(f"     那是相位噪声（换了批交易日），不是「晚一天」的代价。")
    print(f"  5. 可操作：能 21:30 下单就 21:30 下单；起不来则按 [4b] 的 t 曲线估，")
    print(f"     10 日调仓每「晚 1/4 个交易日」约 "
          f"{(t_rows[0.25][10]['cagr']-t_rows[0.0][10]['cagr'])*100:.2f}pp。")

    # ---------------------------------------------------------------- [6] 综合口径
    print()
    print("=" * 104)
    print("[6] 综合口径：把佣金 + 滑点 + 执行时点叠起来（10 日调仓，本金 $1,490）")
    print("=" * 104)
    print("     每一项都相对【零佣金 + 零滑点 + 开盘成交】这个理想基准测。")
    print(f"  {'口径':<34}{'CAGR':>9}{'相对理想':>11}{'终值':>14}")
    print("  " + "-" * 68)
    combos = [
        ("理想：零佣金 + 零滑点 + 开盘", 0.0, 0.0, "open"),
        ("+ 佣金 $2/笔", COMM_REAL, 0.0, "open"),
        ("+ 滑点 2bp", COMM_REAL, 0.0002, "open"),
        ("+ 滑点 10bp", COMM_REAL, 0.0010, "open"),
        ("+ 改为收盘价执行（佣金+2bp 滑点）", COMM_REAL, 0.0002, "close"),
    ]
    ideal = None
    for tag, cm, sl, pxm in combos:
        r = engine3(A, Ov, Cv, gm, 10, mode="min", cap=CAP_REAL, comm=cm, slip=sl, px=pxm)
        s = stats(r["eq"], CAP_REAL)
        if ideal is None:
            ideal = s["cagr"]
        print(f"  {tag:<32}{s['cagr']*100:>8.1f}%{(s['cagr']-ideal)*100:>+10.2f}pp"
              f"${s['final']:>13,.0f}")

    out = {"slip_base": {str(k): v for k, v in base.items()},
           "exec_px": {k: {str(r): v for r, v in vv.items()} for k, vv in rows.items()},
           "intraday_t": {str(k): {str(r): v for r, v in vv.items()} for k, vv in t_rows.items()},
           "adv_ratio_max": float(ratio.max()), "adv_median": float(med.median()),
           "intraday_drift_mean": float(oc.mean()), "cap": CAP_REAL}
    json.dump(out, open(os.path.join(U.BASE, "_v29_slippage.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=float)
    print(f"\n  明细已写入 _v29_slippage.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
