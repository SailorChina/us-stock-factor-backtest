# -*- coding: utf-8 -*-
"""
v22b  修正 B 段参照基准 (v22 里 ref 误取成 $100 组, 而 $100 组已被佣金吃光 -> 全部报差异)
本脚本: 以 $1,490.49 为基准, 逐一比对其他本金下的【实际持仓集合】, 并给出差异样例。
"""
import os, io, inspect, contextlib, importlib.util
import numpy as np

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
with contextlib.redirect_stdout(io.StringIO()):
    spec = importlib.util.spec_from_file_location("_bd14", os.path.join(BASE, "_bear_defense_v14.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

src = inspect.getsource(m.backtest)
old_pend = '''        for typ, a, b in pend:
            if typ == "rebal": allocate(a, b, op, sv)'''
new_pend = '''        for typ, a, b in pend:
            if typ == "rebal":
                allocate(a, b, op, sv)
                SNAPS.append((str(dp[i].date()), {k: v for k, v in pos.items() if v > 0}))'''
assert old_pend in src and "comm = lambda sh: max" in src
src = src.replace(old_pend, new_pend).replace(
    "comm = lambda sh: max(abs(sh)*0.005, 1.0) if abs(sh) > 0 else 0.0", "comm = COMMFN")
# 只在"真正扣款/记账"处记录费用 —— 缩量重试循环里的 comm() 不计费(生产代码里它是纯函数)
marks = [
    ("cash += sh*op_i[c]*(1-slip) - comm(sh)",
     "cash += sh*op_i[c]*(1-slip) - comm(sh); FEE.append(comm(sh))"),
    ("cash += safe_sh*safe_v*(1-slip) - comm(safe_sh); safe_sh = 0.0",
     "cash += safe_sh*safe_v*(1-slip) - comm(safe_sh); FEE.append(comm(safe_sh)); safe_sh = 0.0"),
    ("cash -= cost; pos[c] = sh; invest -= sh*pr",
     "cash -= cost; FEE.append(comm(sh)); pos[c] = sh; invest -= sh*pr"),
    ("cash -= cost; safe_sh = sh",
     "cash -= cost; FEE.append(comm(sh)); safe_sh = sh"),
]
for a, b in marks:
    assert a in src, f"注费点未命中: {a}"
    src = src.replace(a, b)

COMM_FIX2 = lambda sh: (2.0 if abs(sh) > 0 else 0.0)

def run(score, cap, topk=2):
    """返回 (每调仓日持仓快照, 净值序列, 累计佣金, 实际成交笔数)"""
    snaps, fee_rec = [], []
    G = dict(m.__dict__); G["SNAPS"] = snaps; G["FEE"] = fee_rec
    G["COMMFN"] = COMM_FIX2; G["CAP0"] = cap
    exec(src, G)
    eq, hist, _, _ = G["backtest"](score, topk=topk)
    return snaps, np.asarray(eq, float), float(sum(fee_rec)), len(fee_rec)

print("=" * 116)
print("B(修正). 回测引擎: 以 $1,490.49 为基准, 比对不同 CAP0 下的【实际持仓集合】")
print("=" * 116)
CAPS = [100.0, 300.0, 500.0, 1000.0, 1490.49, 3000.0, 10_000.0, 100_000.0, 1_000_000.0]
res = {}
for cap in CAPS:
    snaps, eq, fee, nleg = run(m.SIG["Vortex"], cap, topk=2)
    res[cap] = (snaps, eq, fee, nleg)

ref_snaps = res[1490.49][0]
ref_sets = [frozenset(m.CODES[j].replace("US.", "") for j in s) for _, s in ref_snaps]
print(f"  基准 = $1,490.49, 共 {len(ref_sets)} 个调仓日")
print(f"\n  {'本金':>13} {'持仓差异日':>10} {'只买到1只':>10} {'终值':>14} {'倍数':>8} "
      f"{'成交笔数':>8} {'累计佣金':>10} {'佣金/初始':>10}")
print("  " + "-" * 96)
for cap in CAPS:
    snaps, eq, fee, nleg = res[cap]
    sets = [frozenset(m.CODES[j].replace("US.", "") for j in s) for _, s in snaps]
    diff = [i for i, (a, b) in enumerate(zip(ref_sets, sets)) if a != b]
    thin = sum(1 for s in sets if len(s) < 2)
    print(f"  ${cap:>12,.2f} {len(diff):>10} {thin:>10} ${eq[-1]:>13,.0f} {eq[-1]/cap:>7.1f}x "
          f"{nleg:>8} ${fee:>9,.0f} {fee/cap:>9.1%}")
    if diff and cap != 1490.49:
        for i in diff[:2]:
            a, b = sorted(ref_sets[i]), sorted(sets[i])
            print(f"       例 {ref_snaps[i][0]}: 基准={a}  本次={b}")

# 差异是否只是"少买一只" (执行层), 还是"换了另一只票" (选股层)
print("\n  [关键区分] 差异属于【买不起少一只】还是【换成别的票】?")
for cap in CAPS:
    sets = [frozenset(m.CODES[j].replace("US.", "") for j in s) for _, s in res[cap][0]]
    subset, swap = 0, []
    for a, b in zip(ref_sets, sets):
        if a == b: continue
        if b < a: subset += 1
        else: swap.append((sorted(a), sorted(b)))
    print(f"  ${cap:>12,.2f}  子集(仅少买) {subset:>3} 次   真·换股 {len(swap):>3} 次"
          + (f"   样例 {swap[:2]}" if swap else ""))

print("\n" + "=" * 116)
print("C(收紧判据). 最优 k 是否随本金改变")
print("=" * 116)
COMM_ZERO = lambda sh: 0.0
def perf(score, topk, cap, commfn):
    snaps = []
    G = dict(m.__dict__); G["SNAPS"] = snaps; G["COMMFN"] = commfn; G["CAP0"] = cap
    exec(src, G)
    eq, _, _, _ = G["backtest"](score, topk=topk)
    eq = np.asarray(eq, float); v = eq[m.START:]
    mdd = float(((v - np.maximum.accumulate(v)) / np.maximum.accumulate(v)).min() * 100)
    yrs = (m.N - m.START) / 252.0
    return float(((eq[-1] / cap) ** (1 / yrs) - 1) * 100), mdd

for strat in ["Vortex", "动量-1月反转"]:
    for mode, fn in [("零成本(纯信号)", COMM_ZERO), ("$2/笔(实盘)", COMM_FIX2)]:
        best = {}
        for cap in [1490.49, 10_000.0, 100_000.0]:
            cs = {k: perf(m.SIG[strat], k, cap, fn)[0] for k in [1, 2, 3, 4, 5]}
            bk = max(cs, key=cs.get)
            best[cap] = bk
            print(f"  {strat:<10} {mode:<12} 本金 ${cap:>9,.0f} -> 最优 k={bk}  "
                  + "  ".join(f"k{k}:{v:.1f}%" for k, v in cs.items()))
        print(f"    -> 最优 k 跨本金: {best}  {'✅ 一致(与资金无关)' if len(set(best.values()))==1 else '❌ 不一致'}")
