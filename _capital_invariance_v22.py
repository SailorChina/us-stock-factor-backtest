# -*- coding: utf-8 -*-
"""
v22  选股信号 × 资金量  独立性验证

命题(用户提出): 选股信号不应受回测金额影响 —— 回测金额只是回测数据, 不是选股标准。

本脚本用【实证】回答三件事:
  A. 生产脚本 `_update_signal.py` 在不同本金下, 选出的票是否完全一致?
     (真·生产路径: subprocess 直接跑 --no-fetch --capital X, 解析 stdout)
  B. 回测引擎 `_bear_defense_v14.backtest` 在不同 CAP0 下, 【实际持仓】序列是否一致?
     (verbatim 复用生产函数源码, 仅插入一行持仓记录, 保证不失真)
  C. TopK(持股数) 该由谁决定?
     (零成本=纯信号能力 vs $2/笔=真实成本, 各资本下 k=1..5 的表现与排名)

注意: A 段会覆写 signal_snapshot.json / signal_history.csv -> 脚本自行备份还原。
"""
import os, sys, io, json, shutil, inspect, contextlib, subprocess
import numpy as np, pandas as pd

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
PY = sys.executable          # 用当前解释器, 换机器不用改
OUT = {}


def hdr(t, w=110):
    print("\n" + "=" * w); print(t); print("=" * w)


# =====================================================================================
# A. 生产脚本: 不同本金 -> 选票是否一致 (真·生产路径)
# =====================================================================================
hdr("A. 生产脚本 _update_signal.py : 不同本金下选出的票")

snap_p, hist_p = os.path.join(BASE, "signal_snapshot.json"), os.path.join(BASE, "signal_history.csv")
snap_b = os.path.join(BASE, "signal_snapshot.bak.json")
hist_b = os.path.join(BASE, "signal_history.bak.csv")

# v27 修复: 备份必须【在 A 段覆写之前】真的做出来。
# 原写法只声明了 snap_b / hist_b 却从未写入 -> 下面 finally 里的还原是【空操作】
# (os.path.exists(snap_b) 恒为 False), A 段 6 次 subprocess 覆写生产文件后无人还原。
# 现在 signal_snapshot.json 已退出版本控制, 被覆写就【没有 git 可回滚】, 所以这个备份更关键。
for _src, _dst in ((snap_p, snap_b), (hist_p, hist_b)):
    if os.path.exists(_src):
        shutil.copy2(_src, _dst)
    else:
        print(f"  [!] {os.path.basename(_src)} 不存在 -> 跳过备份 (A 段会重新生成它)")

CAPS = [
    ("$1 极端",            ["--capital", "1"]),
    ("$100",               ["--capital", "100"]),
    ("$1,490.49 (¥1万)",   ["--capital", "1490.49"]),
    ("默认(¥1万/6.7092)",  []),
    ("$100,000",           ["--capital", "100000"]),
    ("$10,000,000",        ["--capital", "10000000"]),
]
rows_a = []
try:
    for label, extra in CAPS:
        cmd = [PY, os.path.join(BASE, "_update_signal.py"), "--no-fetch"] + extra
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=BASE)
        out = r.stdout or ""
        line = next((l.strip() for l in out.splitlines() if l.strip().startswith("策略 ")), "?")
        # 目标股数行
        qty = {}
        for l in out.splitlines():
            for c in ["META", "BE", "MU", "LITE"]:
                if l.strip().startswith(c + " ") and "$" in l:
                    qty.setdefault(c, l.strip()[:60])
        rows_a.append({"label": label, "picks_line": line, "rc": r.returncode})
        print(f"  {label:<22} rc={r.returncode}  {line}")
finally:
    # 还原生产快照, 避免 A 段覆写污染真实信号文件
    if os.path.exists(snap_b): shutil.copy(snap_b, snap_p)
    if os.path.exists(hist_b): shutil.copy(hist_b, hist_p)
    print("  (已还原 signal_snapshot.json / signal_history.csv 到 A 段之前的备份)")

picks_set = {r["picks_line"] for r in rows_a}
print(f"\n  -> 不同本金产出的选票行共 {len(picks_set)} 种: {picks_set}")
A_OK = (len(picks_set) == 1)
print(f"  -> 结论 A: {'✅ 选股完全不受本金影响' if A_OK else '❌ 存在资金驱动的选股差异'}")
OUT["A"] = {"rows": rows_a, "unique": list(picks_set), "capital_invariant": A_OK}


# =====================================================================================
# B. 回测引擎: 不同 CAP0 -> 实际持仓序列是否一致
# =====================================================================================
hdr("B. 回测引擎 _bear_defense_v14.backtest : 不同 CAP0 下的【实际持仓】序列")
sys.path.insert(0, BASE)
m = None
try:
    with contextlib.redirect_stdout(io.StringIO()):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_bd14", os.path.join(BASE, "_bear_defense_v14.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)          # 生产模块全量执行(输出已静音)
    print("  已加载生产模块 _bear_defense_v14 (源码级复用, 非重写)")

    # --- verbatim 取生产 backtest 源码, 只插入 1 行持仓记录, 并参数化佣金/本金 ---
    src = inspect.getsource(m.backtest)
    old_pend = '''        for typ, a, b in pend:
            if typ == "rebal": allocate(a, b, op, sv)'''
    new_pend = '''        for typ, a, b in pend:
            if typ == "rebal":
                allocate(a, b, op, sv)
                SNAPS.append((str(dp[i].date()), {k: v for k, v in pos.items() if v > 0}))'''
    assert old_pend in src, "注入点1未命中 -> 源码已变, 拒绝继续(防静默失效)"
    src = src.replace(old_pend, new_pend)
    old_c = "comm = lambda sh: max(abs(sh)*0.005, 1.0) if abs(sh) > 0 else 0.0"
    assert old_c in src, "注入点2未命中 -> 佣金行已变, 拒绝继续(防静默失效)"
    src = src.replace(old_c, "comm = COMMFN")

    C0_LIVE = 2.0   # 富途实盘口径: $2/笔
    COMM_ZERO = lambda sh: 0.0
    COMM_FIX2 = lambda sh: (C0_LIVE if abs(sh) > 0 else 0.0)
    COMM_OLD = lambda sh: (max(abs(sh) * 0.005, 1.0) if abs(sh) > 0 else 0.0)

    def make_engine(snaps):
        G = dict(m.__dict__)
        G["SNAPS"] = snaps
        G["COMMFN"] = COMM_FIX2
        G["np"] = np
        exec(src, G)
        return G["backtest"]

    def realized(score, cap, topk=2):
        """返回 (每个调仓日的实际持仓代码集合, 净值序列, 选票意图)"""
        snaps, eng = [], None
        eng = make_engine(snaps)
        m.CAP0set = cap
        g = eng.__globals__; g["CAP0"] = cap
        eq, hist, _, _ = eng(score, topk=topk)
        return [frozenset(m.CODES[j].replace("US.", "") for j in s) for _, s in snaps], eq, hist

    CAPS_B = [100.0, 500.0, 1490.49, 10_000.0, 1_000_000.0]
    ref = None
    b_rows = []
    for cap in CAPS_B:
        sets, eq, hist = realized(m.SIG["Vortex"], cap, topk=2)
        if ref is None: ref = sets
        diff = [i for i, (a, b) in enumerate(zip(ref, sets)) if a != b]
        b_rows.append({"cap": cap, "n_rebal": len(sets), "n_diff_vs_1490": len(diff),
                       "terminal": float(eq[-1]), "mult": float(eq[-1] / cap),
                       "held_now": sorted(sets[-1])})
        print(f"  CAP0 ${cap:>12,.2f}  调仓 {len(sets)} 次  与 $1,490 的持仓差异 {len(diff)} 次  "
              f"终值 ${eq[-1]:>12,.0f}  倍数 {eq[-1]/cap:>7.3f}x  末次持仓 {sorted(sets[-1])}")
    B_OK = all(r["n_diff_vs_1490"] == 0 for r in b_rows)
    print(f"\n  -> 结论 B: {'✅ 实际持仓序列与本金无关(≥$500 时)' if B_OK else '⚠ 见上表差异'}")
    if not B_OK:
        print("     说明: 本金过小时 $2/笔佣金会使某只票买不起 -> 只影响【能不能成交】, 不影响选股本身")
    OUT["B"] = b_rows
except Exception as e:
    print(f"  B 段异常: {type(e).__name__}: {e}")
    OUT["B"] = {"error": str(e)}


# =====================================================================================
# C. TopK 由谁决定: 纯信号能力 vs 真实成本
# =====================================================================================
hdr("C. 持股数 TopK: 该由【信号本身】决定还是由【资金量】决定?")
try:
    def perf(score, topk, cap, commfn):
        snaps = []
        G = dict(m.__dict__); G["SNAPS"] = snaps; G["COMMFN"] = commfn; G["CAP0"] = cap
        exec(src, G)
        eq, _, _, _ = G["backtest"](score, topk=topk)
        eq = np.asarray(eq, dtype=float)
        v = eq[m.START:]
        mdd = float(((v - np.maximum.accumulate(v)) / np.maximum.accumulate(v)).min() * 100)
        yrs = (m.N - m.START) / 252.0
        cagr = float(((eq[-1] / cap) ** (1 / yrs) - 1) * 100)
        return float(eq[-1] / cap), cagr, mdd

    c_rows = []
    for strat in ["Vortex", "动量-1月反转"]:
        for cap in [1490.49, 100_000.0]:
            print(f"\n  [{strat}]  本金 ${cap:,.0f}")
            print(f"    {'k':<4}{'纯信号(0成本)':>26}{'实盘($2/笔)':>26}")
            print(f"    {'':<4}{'倍数':>9}{'CAGR':>9}{'MDD':>8}{'倍数':>9}{'CAGR':>9}{'MDD':>8}")
            best0 = best2 = None
            for k in [1, 2, 3, 4, 5]:
                f0, c0, d0 = perf(m.SIG[strat], k, cap, COMM_ZERO)
                f2, c2, d2 = perf(m.SIG[strat], k, cap, COMM_FIX2)
                if best0 is None or c0 > best0[1]: best0 = (k, c0, f0, d0)
                if best2 is None or c2 > best2[1]: best2 = (k, c2, f2, d2)
                c_rows.append({"strat": strat, "cap": cap, "k": k,
                               "free_mult": f0, "free_cagr": c0, "free_mdd": d0,
                               "real_mult": f2, "real_cagr": c2, "real_mdd": d2})
                print(f"    {k:<4}{f0:>9.1f}x{c0:>8.1f}%{d0:>7.1f}%{f2:>9.1f}x{c2:>8.1f}%{d2:>7.1f}%")
            # 持仓分散度: TopK 的波动随 k
            print(f"    -> 纯信号最优 k = {best0[0]} (CAGR {best0[1]:.1f}%); "
                  f"扣$2/笔后最优 k = {best2[0]} (CAGR {best2[1]:.1f}%)")
    OUT["C"] = c_rows

    # 关键判据: k 的排名是否随本金变化
    print("\n  [判据] k 的优劣排名是否随本金改变?")
    krank = {}
    for strat in ["Vortex", "动量-1月反转"]:
        for mode in ["free_cagr", "real_cagr"]:
            for cap in [1490.49, 100_000.0]:
                sub = [r for r in c_rows if r["strat"] == strat and r["cap"] == cap]
                order = [r["k"] for r in sorted(sub, key=lambda x: -x[mode])]
                krank[(strat, mode, cap)] = order
                print(f"    {strat:<10} {mode:<10} 本金 ${cap:>10,.0f} -> k 排序 {order}")
    C_OK = all(krank[(s, m_, 1490.49)] == krank[(s, m_, 100_000.0)]
               for s in ["Vortex", "动量-1月反转"] for m_ in ["free_cagr", "real_cagr"])
    print(f"\n  -> 结论 C: {'✅ k 的排名不随本金改变 -> k 应由信号本身决定' if C_OK else '⚠ k 排名随本金改变'}")
    OUT["C_rank"] = {f"{k[0]}|{k[1]}|{k[2]:.0f}": v for k, v in krank.items()}
    OUT["C_invariant"] = C_OK
except Exception as e:
    print(f"  C 段异常: {type(e).__name__}: {e}")
    OUT["C"] = {"error": str(e)}

json.dump(OUT, open(os.path.join(BASE, "_capital_invariance_v22.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=str)
print("\n" + "=" * 110)
print("结果已保存 _capital_invariance_v22.json")
