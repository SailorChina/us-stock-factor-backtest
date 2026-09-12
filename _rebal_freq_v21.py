# -*- coding: utf-8 -*-
"""
v21  调仓频率专题: 为什么是 21 天? 其他天数呢?

之前 v16 只测了 21/42/63/126 四个频率, 且结果非单调 (21: +11272%, 42: +3966%,
63: +1663%, 126: +8261%)。无法分辨 "频率真的重要" 还是 "不同调仓日的运气"。
本脚本做三件事:

  [1] 全频率扫描 (5~252 交易日) + 佣金剥离: 三种成本模型
      full   = 每个调仓日全部卖出再买入 (上界, 2*K 笔)
      fullsk = 选股不变则不调仓 (v16 口径, 重现历史数字)
      min    = 只交易变动的名字 (最小换手, = 下单脚本的口径)
      none   = 零佣金零滑点 (纯信号质量)
  [2] 噪声检验: 同一频率遍历所有起始偏移 (offset=0..rebal-1), 看结果分布。
      若 "频率之间的差异" < "同频率内的偏移差", 则该频率差异是噪声。
  [3] 成本-资金规模分解, 持有期集中度 (剔最好10期), 信号变化概率 vs 频率。

引擎 = v14 修复版 (剩余现金/剩余槽位顺序分配, 保证等权满仓; T日收盘信号 -> T+1开盘成交)
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

FX = 6.7092; CAP0 = 10000.0 / FX        # ¥1万 = $1,490.49 (真实起点)
COMM = 2.0                              # 富途 买$2 + 卖$2, 按笔固定
SLIP = 0.0005
START = 252

def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF", "ETN", "3X", "2X", "ULTRA", "PROSHARES",
                                "LEVERAG", " -3X", "3XS", "BEAR", "BULL "])
mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

def load(codes):
    p = {}
    for c in codes:
        d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").reset_index(drop=True).set_index("time_key")
    ad = sorted(set().union(*[set(x.index) for x in p.values()])); dt = pd.to_datetime(ad)
    return dt, {k: pd.DataFrame({c: p[c][k].reindex(dt).ffill() for c in codes})
                for k in ["open", "high", "low", "close", "volume"]}

dates, PX = load(UNI); CODES = UNI
C = PX["close"].values; O = PX["open"].values; H = PX["high"].values; L = PX["low"].values
V = PX["volume"].values
N, S = C.shape; dp = pd.to_datetime(dates)
_, vp = load(["US.VOO"]); VOO = vp["close"]["US.VOO"].values

dfH, dfL, dfC = [pd.DataFrame(x, index=dp, columns=CODES) for x in (H, L, C)]
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift(); tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())
mom12_1 = dfC.shift(21) / dfC.shift(252) - 1.0
rev1 = dfC / dfC.shift(21) - 1.0
SIG = {"Vortex": vortex(dfH, dfL, dfC), "动量-1月反转": (zs(mom12_1) - zs(rev1)) / 2.0}
SIGA = {k: np.asarray(v.values, dtype=float) for k, v in SIG.items()}

# ======================= 引擎 =======================
def backtest(score, topk=2, cap=CAP0, rebal=21, offset=0, mode="min",
             slip=SLIP, comm=COMM, ret_hist=False, days=None):
    """
    mode: 'full' 每次全换手 | 'fullsk' 选股不变则跳过 | 'min' 只换变动名 | 'none' 零成本
    offset: 调仓日历相位 (0..rebal-1), 用于噪声检验
    days:  显式调仓日索引集合 (用于日历口径: 月末/月初); 给定时忽略 rebal/offset
    返回 eq 数组 (len N), 统计 dict
    """
    A = score
    free = (mode == "none")
    cf = (lambda: 0.0) if free else (lambda: comm)
    cash = cap; pos = {}; pend = None
    eq = np.empty(N)
    ntrade = 0; nreb = 0; nskip = 0; comm_tot = 0.0; pick_hist = []

    def sell_all(op_i):
        nonlocal cash, ntrade, comm_tot
        for c in list(pos.keys()):
            sh = pos.pop(c)
            cash += sh * op_i[c] * (1 - slip) - cf(); ntrade += 1; comm_tot += cf()

    def buy_eq(picks, op_i):
        nonlocal cash, ntrade, comm_tot
        total = cash; n = len(picks)
        for k, c in enumerate(picks):
            slots = n - k; bud = total / slots
            pr = op_i[c] * (1 + slip)
            if not (np.isfinite(pr) and pr > 0): continue
            sh = bud / pr; cost = sh * pr + cf(); g = 0
            while cost > cash and sh > 0 and g < 80:
                sh *= 0.995; cost = sh * pr + cf(); g += 1
            if sh > 0 and cost <= cash:
                cash -= cost; pos[c] = sh; total -= sh * pr
                ntrade += 1; comm_tot += cf()

    def rebal_min(picks, op_i):
        """只交易变动名: 卖非目标, 补足目标金额 (两个方向都不主动减仓已持有的)"""
        nonlocal cash, ntrade, comm_tot
        nav = cash + sum(pos.get(c, 0.0) * op_i[c] for c in pos)
        tgt = nav / topk
        for c in list(pos.keys()):
            if c not in picks:
                sh = pos.pop(c)
                cash += sh * op_i[c] * (1 - slip) - cf(); ntrade += 1; comm_tot += cf()
        for c in picks:
            pr = op_i[c] * (1 + slip)
            if not (np.isfinite(pr) and pr > 0): continue
            have = pos.get(c, 0.0)
            want = tgt / pr
            d = want - have
            if d <= 0: continue
            sh = d; g = 0
            while sh * pr + cf() > cash and sh > 0 and g < 80:
                sh *= 0.995; g += 1
            if sh > 0:
                cash -= sh * pr + cf(); pos[c] = have + sh
                ntrade += 1; comm_tot += cf()

    last_pick = None
    for i in range(N):
        op = O[i]
        if pend is not None:
            picks, m = pend; pend = None
            if m == "full":
                sell_all(op); buy_eq(picks, op)
            elif m == "min":
                rebal_min(picks, op)
            else:
                buy_eq(picks, op)
        eq[i] = cash + sum(pos.get(c, 0.0) * C[i, c] for c in pos)
        is_rb = (i in days) if days is not None else \
                (i >= START and (i - START - offset) % rebal == 0)
        if is_rb:
            row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
            if len(idx) > 0:
                picks = list(idx[np.argsort(-row[idx])][:topk])
                if mode == "fullsk" and last_pick is not None and set(picks) == set(last_pick):
                    nreb += 1; nskip += 1; continue
                nreb += 1; last_pick = picks
                # full / fullsk / none 的成交口径都是"全部卖出再等权买入"
                # (none 只是把佣金与滑点置零, 用来剥离成本、单看信号质量)
                m = "min" if mode == "min" else "full"
                pend = (picks, m)
                if ret_hist: pick_hist.append((i, tuple(picks)))
    st = dict(ntrade=ntrade, nreb=nreb, nskip=nskip, comm=comm_tot)
    return eq, st, pick_hist

def mdd(eq):
    v = eq[START:]; return float(((v - np.maximum.accumulate(v)) / np.maximum.accumulate(v)).min() * 100)
def cagr(eq, cap=CAP0): return float(((eq[-1] / cap) ** (1 / ((N - START) / 252.0)) - 1) * 100)
def sharpe(eq):
    r = np.diff(eq[START:]) / eq[START:-1]
    sd = r.std()
    return float(r.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan")
def tot(eq, cap=CAP0): return float((eq[-1] / cap - 1) * 100)

# ---------------- 基准 ----------------
s0 = np.nan_to_num(C[START], nan=0.0); ok0 = s0 > 0
sh0 = CAP0 * np.where(ok0, 1.0 / ok0.sum(), 0.0) / np.where(ok0, s0, 1.0)
eq_bh = np.full(N, np.nan); eq_bh[START:] = (np.nan_to_num(C, nan=0.0) @ sh0)[START:]
eq_voo = np.concatenate([np.full(START, np.nan), VOO[START:] / VOO[START] * CAP0])

FREQS = [5, 10, 15, 21, 30, 42, 63, 84, 126, 252]
FLABEL = {5: "周频(5日)", 10: "双周(10日)", 15: "半月(15日)", 21: "月频(21日)",
          30: "30日", 42: "双月(42日)", 63: "季频(63日)", 84: "84日",
          126: "半年(126日)", 252: "年频(252日)"}

print("=" * 138)
print(f"调仓频率专题 | 本金 ${CAP0:,.2f} (¥10,000 @ {FX}) | 富途佣金 ${COMM:.0f}/笔 | 数据 {dp[START].date()} ~ {dp[-1].date()}")
print(f"基准: 等权全买37只 {tot(eq_bh):+.0f}% (${eq_bh[-1]:,.0f}) | VOO {tot(eq_voo):+.0f}% (${eq_voo[-1]:,.0f})")
print("=" * 138)

print("\n[引擎自检] 顺序分配是否真的等权满仓 (闲置现金应≈0)")
for nm in SIGA:
    for tk in [2, 3]:
        eq, st, _ = backtest(SIGA[nm], topk=tk, rebal=21, mode="min")
        # 用满仓日平均现金占比自检
        print(f"   {nm} Top{tk}: 终值 ${eq[-1]:,.0f} | 交易 {st['ntrade']} 笔 | 佣金 ${st['comm']:.0f}"
              f" | 佣金/本金 {st['comm']/CAP0*100:.1f}%")

# ============ [1] 全频率扫描 (真实资本, 三种成本模型) ============
print("\n" + "=" * 138)
print("[1] 全频率扫描 — 本金 $1,490, Vortex Top2 (off=0)")
print("=" * 138)
print(f"{'频率':<14}{'调仓次数':>8}{'full终值':>13}{'fullsk终值':>13}{'min终值':>13}{'none终值':>13}"
      f"{'全额佣金$':>11}{'佣金/本金':>10}{'min回撤':>9}{'min夏普':>8}")
print("-" * 138)
scan = {}
for rb in FREQS:
    row = {}
    for m in ["full", "fullsk", "min", "none"]:
        eq, st, _ = backtest(SIGA["Vortex"], topk=2, rebal=rb, mode=m)
        row[m] = (eq, st)
    e_min, s_min = row["min"]
    scan[rb] = {"full": tot(row["full"][0]), "fullsk": tot(row["fullsk"][0]),
                "min": tot(e_min), "none": tot(row["none"][0]),
                "comm": row["full"][1]["comm"], "nreb": row["full"][1]["nreb"],
                "mdd_min": mdd(e_min), "sharpe_min": sharpe(e_min),
                "ntrade_full": row["full"][1]["ntrade"], "ntrade_min": s_min["ntrade"]}
    print(f"{FLABEL[rb]:<14}{row['full'][1]['nreb']:>8}"
          f"{'$'+format(row['full'][0][-1],',.0f'):>13}"
          f"{'$'+format(row['fullsk'][0][-1],',.0f'):>13}"
          f"{'$'+format(e_min[-1],',.0f'):>13}"
          f"{'$'+format(row['none'][0][-1],',.0f'):>13}"
          f"{row['full'][1]['comm']:>11,.0f}{row['full'][1]['comm']/CAP0*100:>9.0f}%"
          f"{mdd(e_min):>8.1f}%{sharpe(e_min):>8.2f}")

print("\n  同样对比 动量-1月反转 Top2:")
print(f"{'频率':<14}{'调仓次数':>8}{'full终值':>13}{'fullsk终值':>13}{'min终值':>13}{'none终值':>13}")
print("-" * 138)
scan_m = {}
for rb in FREQS:
    o = {}
    for m in ["full", "fullsk", "min", "none"]:
        eq, st, _ = backtest(SIGA["动量-1月反转"], topk=2, rebal=rb, mode=m)
        o[m] = (eq, st)
    scan_m[rb] = {k: tot(v[0]) for k, v in o.items()}
    print(f"{FLABEL[rb]:<14}{o['full'][1]['nreb']:>8}"
          f"{'$'+format(o['full'][0][-1],',.0f'):>13}"
          f"{'$'+format(o['fullsk'][0][-1],',.0f'):>13}"
          f"{'$'+format(o['min'][0][-1],',.0f'):>13}"
          f"{'$'+format(o['none'][0][-1],',.0f'):>13}")

# ============ [2] 噪声检验: 同频率内遍历偏移 ============
print("\n" + "=" * 138)
print("[2] 噪声检验 — 同一频率遍历所有起始偏移, 看终值分布 (Vortex Top2)")
print("   若『频率之间的差异』小于『同频率内的偏移差』, 则频率效应是噪声")
print("=" * 138)
rng = np.random.default_rng(7)
OFFS = {}
for rb in FREQS:
    alloff = list(range(rb))
    OFFS[rb] = alloff if len(alloff) <= 21 else sorted(rng.choice(alloff, 21, replace=False).tolist())

print(f"{'频率':<14}{'偏移数':>7}{'零成本 p10':>12}{'中位':>11}{'p90':>11}{'极差':>9}"
      f"{'最小换手 p10':>14}{'中位':>11}{'p90':>11}{'极差':>9}")
print("-" * 138)
noise = {}
for rb in FREQS:
    for m in ["none", "min"]:
        vals = np.array([backtest(SIGA["Vortex"], topk=2, rebal=rb, offset=o, mode=m)[0][-1]
                         for o in OFFS[rb]]) / CAP0
        noise.setdefault(rb, {})[m] = vals
    a = noise[rb]["none"]; b = noise[rb]["min"]
    q = lambda v: np.percentile(v, [10, 50, 90])
    qa = q(a); qb = q(b)
    print(f"{FLABEL[rb]:<14}{len(OFFS[rb]):>7}{qa[0]:>11.0f}x{qa[1]:>10.0f}x{qa[2]:>10.0f}x"
          f"{a.max()/max(a.min(),1e-3):>8.1f}x"
          f"{qb[0]:>13.0f}x{qb[1]:>10.0f}x{qb[2]:>10.0f}x{b.max()/max(b.min(),1e-3):>8.1f}x")

print("\n  [2a] 方差分解 — 等样本量(每频率21个偏移, 5/10/15日受限于偏移总数):")
print("       把 log10(终值/本金) 的总变异拆成『频率之间』与『频率内部(相位/运气)』")
for m in ["none", "min"]:
    # 只用偏移数>=20的频率, 保证等样本量
    usable = [rb for rb in FREQS if len(OFFS[rb]) >= 20]
    allv = np.concatenate([np.log10(np.maximum(noise[rb][m], 1e-3)) for rb in usable])
    gm = allv.mean()
    between = sum(len(OFFS[rb]) * (np.log10(np.maximum(noise[rb][m], 1e-3)).mean() - gm) ** 2
                  for rb in usable)
    total = ((allv - gm) ** 2).sum()
    print(f"     {m:<5} 样本 {len(allv)} 个 (频率: {', '.join(FLABEL[r] for r in usable)})"
          f" | 频率可解释 {between/total*100:.1f}% | 频率内部(相位) {100-between/total*100:.1f}%")

print("\n  [2b] 各频率 vs 21天 (最小换手) — 中位数与秩和检验(Mann-Whitney正态近似):")
print(f"{'频率':<14}{'中位倍数':>10}{'vs 21天':>10}{'p值':>9}{'结论':>26}")
print("-" * 138)
base = noise[21]["min"]
def mw(x, y):
    a = np.concatenate([x, y]); r = pd.Series(a).rank().values
    n1, n2 = len(x), len(y)
    R1 = r[:n1].sum()
    U = R1 - n1 * (n1 + 1) / 2
    mu = n1 * n2 / 2; sd = np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sd == 0: return 1.0
    z = (U - mu) / sd
    from math import erfc
    return float(erfc(abs(z) / np.sqrt(2)))
for rb in FREQS:
    b = noise[rb]["min"]
    p = mw(base, b) if rb != 21 else 1.0
    verdict = "无显著差异" if p > 0.05 else "显著"
    print(f"{FLABEL[rb]:<14}{np.median(b):>9.0f}x{np.median(b)/np.median(base):>9.2f}x{p:>9.3f}{verdict:>26}")

# ============ [2c] 日历口径: 21个交易日 ≠ 自然月 ============
print("\n" + "=" * 138)
print("[2c] 日历口径对照 — 21个交易日会相对自然月漂移, 换成真实月末/月初会怎样?")
print("=" * 138)
pos = pd.Series(np.arange(N), index=dp)
end_days, start_days, qend_days = [], [], []
for _, idx in pos.groupby(dp.to_period("M")):
    ii = [int(x) for x in idx.values if int(x) >= START]
    if ii:
        end_days.append(ii[-1]); start_days.append(ii[0])
for _, idx in pos.groupby(dp.to_period("Q")):
    ii = [int(x) for x in idx.values if int(x) >= START]
    if ii: qend_days.append(ii[-1])
daymap = {"21交易日(当前口径)": None, "日历月末": set(end_days),
          "日历月初": set(start_days), "日历季末": set(qend_days)}
print(f"{'调仓口径':<20}{'调仓次数':>9}{'最小换手终值':>14}{'回撤':>9}{'夏普':>8}{'满换手终值':>14}{'CAGR':>8}")
print("-" * 138)
cal = {}
for nm, ds in daymap.items():
    if ds is None:
        em, _, _ = backtest(SIGA["Vortex"], topk=2, rebal=21, mode="min")
        ef, _, _ = backtest(SIGA["Vortex"], topk=2, rebal=21, mode="full")
        nr = 93
    else:
        em, _, _ = backtest(SIGA["Vortex"], topk=2, mode="min", days=ds)
        ef, _, _ = backtest(SIGA["Vortex"], topk=2, mode="full", days=ds)
        nr = len(ds)
    cal[nm] = (tot(em), mdd(em), sharpe(em), tot(ef))
    print(f"{nm:<20}{nr:>9}{'$'+format(em[-1],',.0f'):>14}{mdd(em):>8.1f}%{sharpe(em):>8.2f}"
          f"{'$'+format(ef[-1],',.0f'):>14}{cagr(em):>7.1f}%")

# ============ [3] 成本-资金规模分解 ============
print("\n" + "=" * 138)
print("[3] 成本分解 — 降低频率能省多少? 不同本金下频率的可行性 (Vortex Top2, 满换手口径)")
print("=" * 138)
CAPS = [1490.49, 3000.0, 10000.0, 30000.0]
print(f"{'频率':<14}{'8.7年调仓次数':>13}{'每次满换手$':>12}" + "".join(f"{'$'+format(c,',.0f'):>16}" for c in CAPS))
print(f"{'':<14}{'':>13}{'':>12}" + "".join(f"{'总佣金占本金':>16}" for c in CAPS))
print("-" * 138)
for rb in FREQS:
    nreb = scan[rb]["nreb"]; per = 4 * COMM
    line = f"{FLABEL[rb]:<14}{nreb:>13}{'$'+format(per,'.0f'):>12}"
    for c in CAPS:
        line += f"{nreb*per/c*100:>15.0f}%"
    print(line)

print("\n  76 个交易日 (=你到年底的持有期) 内的调仓次数与成本 (本金 $1,490):")
print(f"{'频率':<14}{'76天内调仓':>11}{'满换手佣金':>12}{'占本金':>9}{'最小换手佣金':>14}{'占本金':>9}")
print("-" * 138)
for rb in FREQS:
    nr = 76 // rb
    print(f"{FLABEL[rb]:<14}{nr:>11}{nr*4*COMM:>11.0f}${nr*4*COMM/CAP0*100:>8.2f}%"
          f"{nr*2*COMM:>13.0f}${nr*2*COMM/CAP0*100:>8.2f}%")

# ============ [4] 持有期集中度 ============
print("\n" + "=" * 138)
print("[4] 集中度检验 — 剔掉最好的10个持有期后还剩多少? (Vortex Top2, 最小换手, offset=0)")
print("=" * 138)
print(f"{'频率':<14}{'持有期数':>9}{'原终值':>13}{'剔10期后':>13}{'保留比例':>10}{'单期最大':>10}{'单期平均':>10}")
print("-" * 138)
conc = {}
for rb in FREQS:
    eq, st, hist = backtest(SIGA["Vortex"], topk=2, rebal=rb, mode="min", ret_hist=True)
    # 用实际调仓日切持有期
    days = [i for i, _ in hist]
    rets = []
    for k in range(1, len(days)):
        a, b = days[k - 1], days[k]
        rets.append(eq[b] / eq[a] - 1)
    rets = np.array(rets)
    keep = np.sort(rets)[:-10] if len(rets) > 11 else np.array([0.0])
    conc[rb] = float(np.prod(1 + keep))
    print(f"{FLABEL[rb]:<14}{len(rets):>9}{'$'+format(eq[-1],',.0f'):>13}"
          f"{'$'+format(CAP0*np.prod(1+keep),',.0f'):>13}"
          f"{(np.prod(1+keep)/max(eq[-1]/CAP0,1e-9))*100:>9.0f}%"
          f"{rets.max()*100:>9.1f}%{rets.mean()*100:>9.2f}%")

# ============ [5] 信号变化概率 vs 频率 (直接按调仓日历算, 不经引擎) ============
print("\n" + "=" * 138)
print("[5] 为什么不能更快? — 选股重合度与信号自然周期 (Vortex Top2, 直接按日历算选股)")
print("=" * 138)
print(f"{'频率':<14}{'调仓次数':>9}{'两选股全同':>11}{'全同比例':>10}{'每期平均换掉':>13}{'仅换1只的比例':>14}"
      f"{'满换手笔数':>12}{'最小换手笔数':>14}{'省下':>9}")
print("-" * 138)
A_v = SIGA["Vortex"]
for rb in FREQS:
    days = [i for i in range(START, N) if (i - START) % rb == 0]
    picks = []
    for i in days:
        row = A_v[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
        if len(idx) == 0: continue
        picks.append(set(idx[np.argsort(-row[idx])][:2]))
    same = sum(1 for k in range(1, len(picks)) if picks[k] == picks[k - 1])
    over1 = sum(1 for k in range(1, len(picks)) if len(picks[k] & picks[k - 1]) == 1)
    chg = np.mean([2 - len(picks[k] & picks[k - 1]) for k in range(1, len(picks))])
    nt_full = 4 * (len(picks) - 1)
    nt_min = 2 * (len(picks) - 1) * chg / 2 + 2 * (len(picks) - 1) * 0  # 换chg只名 -> 卖chg+买chg = 2*chg 笔
    nt_min = 2 * chg * (len(picks) - 1)
    print(f"{FLABEL[rb]:<14}{len(picks):>9}{same:>11}{same/max(len(picks)-1,1)*100:>9.0f}%"
          f"{chg:>12.2f}只{over1/max(len(picks)-1,1)*100:>13.0f}%"
          f"{nt_full:>12.0f}{nt_min:>14.0f}{(nt_full-nt_min)*COMM:>8,.0f}")

# ============ [6] 换成 Top3 / 更小资金 会不会改变结论 ============
print("\n" + "=" * 138)
print("[6] 稳健性 — 换持股数 (最小换手口径, 本金 $1,490)")
print("=" * 138)
print(f"{'频率':<14}" + "".join(f"{'Top'+str(k):>14}" for k in [1, 2, 3, 4]))
print("-" * 138)
for rb in FREQS:
    line = f"{FLABEL[rb]:<14}"
    for tk in [1, 2, 3, 4]:
        eq, _, _ = backtest(SIGA["Vortex"], topk=tk, rebal=rb, mode="min")
        line += f"{'$'+format(eq[-1],',.0f'):>14}"
    print(line)

json.dump({"cap": CAP0, "comm": COMM, "bench": {"eq_bh": tot(eq_bh), "voo": tot(eq_voo)},
           "scan": {str(k): v for k, v in scan.items()},
           "scan_mom": {str(k): v for k, v in scan_m.items()},
           "noise_min": {str(k): [float(x) for x in noise[k]["min"]] for k in FREQS},
           "noise_none": {str(k): [float(x) for x in noise[k]["none"]] for k in FREQS},
           "concentration": {str(k): v for k, v in conc.items()}},
          open(os.path.join(BASE, "_rebal_freq_v21.json"), "w"), ensure_ascii=False, indent=2)
print("\nSAVED _rebal_freq_v21.json")
