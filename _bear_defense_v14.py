# -*- coding: utf-8 -*-
"""
v14 熊市防御专题 (修复版)  --  能不能避开熊市?

引擎修复记录 (相对初版):
  BUG-1 分配错误: 初版 `if cash>=sh*pr` 因手续费导致第二只票永远买不进
                  (实际只买1只+50%现金). v13旧引擎则是 top1=50%/top2=25%/现金25%.
                  -> 改为 "剩余现金/剩余槽位" 顺序分配, 保证等权且满仓, 并加自检.
  BUG-2 前视偏差: 初版开盘执行时用【当日】的指数状态决定仓位, 当日状态含当日收盘信息.
                  -> 改为指令携带【决策日】的 expo (T日收盘判定 -> T+1开盘执行).
  BUG-3 避险资产价格: 用收盘价在开盘成交 -> 改用开盘价序列.
  BUG-4 dd_stop 未生效: 指令用 expo[i] 而非 eff_expo -> 随指令携带.
  BUG-5 捕获率表 None 崩溃 (2018Q4 处于252根预热期) -> 跳过无数据区间.
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
CAP0 = 3000.0; START = 252

def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
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
                for k in ["open","high","low","close","volume"]}

dates, PX = load(UNI); CODES = UNI
C = PX["close"].values; O = PX["open"].values; H = PX["high"].values; L = PX["low"].values
N, S = C.shape; dp = pd.to_datetime(dates)
_, vp = load(["US.VOO"]); VOO = vp["close"]["US.VOO"].values; VOO_O = vp["open"]["US.VOO"].values
IDIR = os.path.join(BASE, "data_index_long")
def load_idx(code):
    d = pd.read_csv(os.path.join(IDIR, "US_" + code + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    d = d.sort_values("time_key").set_index("time_key")
    return d["open"].reindex(dp).ffill().values
GLD_O = load_idx("GLD"); TLT_O = load_idx("TLT"); SHY_O = load_idx("SHY")

dfH, dfL, dfC = [pd.DataFrame(x, index=dp, columns=CODES) for x in (H, L, C)]
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift(); tr = np.maximum(np.maximum(h-lo, (h-pc).abs()), (lo-pc).abs())
    return ((h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
            - (lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum())
mom12_1 = dfC.shift(21)/dfC.shift(252)-1.0
rev1 = dfC/dfC.shift(21)-1.0
SIG = {"Vortex": vortex(dfH, dfL, dfC), "动量-1月反转": (zs(mom12_1)-zs(rev1))/2.0}
RB = [i for i in range(N) if i >= START and (i-START) % 21 == 0]

# ================== 修复版引擎 ==================
def backtest(score, topk=2, expo=None, safe=None, slip=0.0005, dd_stop=None, check=False, cool=21):
    """
    score : DataFrame 选股信号 (T日收盘可得)
    expo  : 长度N, 每日【收盘判定】的目标股票暴露; 指令次日开盘执行, 用判定日的值 -> 无前视
    safe  : 避险资产【开盘价】序列, None=持现金
    dd_stop: 组合净值从峰值回撤该比例 -> 强制空仓, 涨回半程才回场
    """
    A = np.asarray(score.values, dtype=float); A = np.where(np.isfinite(A), A, np.nan)
    expo = np.ones(N) if expo is None else np.asarray(expo, dtype=float)
    comm = lambda sh: max(abs(sh)*0.005, 1.0) if abs(sh) > 0 else 0.0
    cash = CAP0; pos = {}; safe_sh = 0.0; pend = []; eq = []
    nav_peak = CAP0; halted = False; halt_days = 0; last_pick = None; hist = []
    in_mkt = 0; n_switch = 0; prev_state = None; idle_sum = 0.0; idle_n = 0

    def allocate(picks, expo_v, op_i, safe_v):
        """等权满仓分配: 剩余现金/剩余槽位, 保证投满 expo_v 比例"""
        nonlocal cash, safe_sh
        for c in list(pos.keys()):
            sh = pos.pop(c); cash += sh*op_i[c]*(1-slip) - comm(sh)
        if safe_sh > 0:
            cash += safe_sh*safe_v*(1-slip) - comm(safe_sh); safe_sh = 0.0
        total = cash
        if picks and expo_v > 0:
            invest = total*expo_v
            n = len(picks)
            for k, c in enumerate(picks):
                slots = n-k
                bud = invest/slots
                pr = op_i[c]*(1+slip)
                if not (np.isfinite(pr) and pr > 0): continue
                sh = bud/pr
                cost = sh*pr + comm(sh)
                guard = 0
                while cost > cash and sh > 0 and guard < 60:
                    sh *= 0.995; cost = sh*pr + comm(sh); guard += 1
                if sh > 0 and cost <= cash:
                    cash -= cost; pos[c] = sh; invest -= sh*pr
        if safe is not None and expo_v < 1:
            sv = safe_v*(1+slip)
            bud = total*(1-expo_v)
            if np.isfinite(sv) and sv > 0 and bud > 0:
                sh = bud/sv; cost = sh*sv + comm(sh); guard = 0
                while cost > cash and sh > 0 and guard < 60:
                    sh *= 0.995; cost = sh*sv + comm(sh); guard += 1
                if sh > 0 and cost <= cash:
                    cash -= cost; safe_sh = sh

    for i in range(N):
        co = C[i]; op = O[i]
        sv = safe[i] if safe is not None else 0.0
        for typ, a, b in pend:
            if typ == "rebal": allocate(a, b, op, sv)
        pend = []
        nav = cash + safe_sh*(safe[i] if safe is not None else 0.0) + sum(pos.get(c, 0)*co[c] for c in pos)
        eq.append(nav); nav_peak = max(nav_peak, nav)
        if check and expo[i] > 0.99 and len(pos) > 0:
            idle_sum += cash/nav; idle_n += 1
        st = 1 if expo[i] > 0.5 else (0.5 if expo[i] > 0 else 0)
        if prev_state is not None and st != prev_state: n_switch += 1
        prev_state = st
        if expo[i] > 0: in_mkt += 1

        if i >= START:
            eff = expo[i]
            if dd_stop is not None:
                if halted:
                    # 空仓期间净值恒定, "净值反弹"永远不成立 -> 改用冷却期回场
                    halt_days += 1
                    if halt_days >= cool: halted = False; halt_days = 0; nav_peak = nav
                elif nav <= nav_peak*(1-dd_stop):
                    halted = True; halt_days = 0; nav_peak = nav
                if halted: eff = 0.0
            changed = False
            if i > START:
                pv = expo[i-1]
                if abs(eff - pv) > 1e-9: changed = True
            want = ((i-START) % 21 == 0)
            if want:
                row = A[i]; ok = np.isfinite(row); idx = np.where(ok)[0]
                if len(idx) > 0:
                    last_pick = list(idx[np.argsort(-row[idx])][:topk])
                    hist.append((str(dp[i].date()), [CODES[c] for c in last_pick]))
            if changed or (want and last_pick is not None):
                pend.append(("rebal", last_pick, eff))
    eq = np.array(eq)
    if check and idle_n:
        print(f"   [自检] 满仓日平均闲置现金占比 = {idle_sum/idle_n*100:.2f}%  (应接近0)")
    return eq, hist, in_mkt, n_switch

# ---------------- 择时信号 ----------------
def ma(x, n): return pd.Series(x, index=dp).rolling(n).mean().values
def above_ma(x, n):
    m = ma(x, n); return (x > m) & np.isfinite(m)
def confirm_k(x, n, k):
    a = above_ma(x, n); m = ma(x, n); out = a.copy(); cnt = 0
    for i in range(len(a)):
        if not np.isfinite(m[i]): out[i] = False; continue
        cnt = cnt+1 if not a[i] else 0
        out[i] = not (cnt >= k)
    return out
def monthly_hold(f):
    out = np.zeros(N, dtype=bool); cur = False
    for i in range(N):
        if i >= START and (i-START) % 21 == 0:
            cur = bool(f[i])
        out[i] = cur
    return out
def cross50200(x):
    m50 = ma(x, 50); m200 = ma(x, 200); return (m50 > m200) & np.isfinite(m200)
def vol_expo(x, win=21, hi=0.30):
    r = pd.Series(x, index=dp).pct_change(); v = r.rolling(win).std()*np.sqrt(252)
    return np.where(np.isfinite(v.values), np.where(v.values > hi, 0.5, 1.0), 1.0)

REG = {
    "无择时(始终满仓)": np.ones(N, dtype=bool),
    "VOO 200DMA 日频": above_ma(VOO, 200),
    "VOO 200DMA 月度": monthly_hold(above_ma(VOO, 200)),
    "VOO 200DMA+连5天确认": confirm_k(VOO, 200, 5),
    "VOO 100DMA 日频": above_ma(VOO, 100),
    "VOO 50/200 金叉死叉": cross50200(VOO),
    "VOO 50/200 月度": monthly_hold(cross50200(VOO)),
}

# ---------------- 基准 ----------------
s0 = np.nan_to_num(C[START], nan=0.0); ok0 = s0 > 0
w = np.where(ok0, 1.0/ok0.sum(), 0.0)
sh0 = CAP0*w/np.where(ok0, s0, 1.0)
eq_bh = np.full(N, CAP0); eq_bh[START:] = (np.nan_to_num(C, nan=0.0)@sh0)[START:]
eq_voo = np.concatenate([np.full(START, CAP0), VOO[START:]/VOO[START]*CAP0])

PHASES = [("2019-2020.2 牛市","2019-01-01","2020-02-19","牛"),
          ("2020 疫情崩盘","2020-02-19","2020-03-23","熊"),
          ("2020-2021 牛市","2020-03-24","2021-12-31","牛"),
          ("2022 熊市","2022-01-03","2022-10-12","熊"),
          ("2023-2026 牛市","2023-01-01","2026-09-10","牛")]
def seg(eq, s, e):
    m = (dp >= pd.Timestamp(s)) & (dp <= pd.Timestamp(e)); idx = np.where(m)[0]
    if len(idx) < 2: return None
    a, b = idx[0], idx[-1]
    if a < START: a = START
    if b <= a: return None
    v = eq[a:b+1]; sub = (v-np.maximum.accumulate(v))/np.maximum.accumulate(v)
    return (v[-1]/v[0]-1)*100, sub.min()*100
def mdd(eq):
    v = eq[START:]; return ((v-np.maximum.accumulate(v))/np.maximum.accumulate(v)).min()*100
def cagr(eq): return ((eq[-1]/CAP0)**(1/((N-START)/252.0))-1)*100

def table(rows, title, hdr="方案", w=26):
    print(title)
    print(f"{hdr:<{w}}{'全程':>11}{'CAGR':>8}{'最大回撤':>10}", end="")
    for n, _, _, _ in PHASES: print(f"{n[:9]:>11}", end="")
    print()
    print("-"*(w+40+11*len(PHASES)))
    for nm, eq in rows:
        print(f"{nm:<{w}}{(eq[-1]/CAP0-1)*100:>+10.0f}%{cagr(eq):>+7.1f}%{mdd(eq):>9.1f}%", end="")
        for n, s, e, k in PHASES:
            r = seg(eq, s, e); print(f"{(f'{r[0]:+.0f}%') if r else '-':>11}", end="")
        print()

print("="*128)
print("[引擎自检] 满仓策略是否真的满仓 (闲置现金应≈0)")
print("="*128)
e_chk, _, _, _ = backtest(SIG["Vortex"], check=True)
e_chk3, _, _, _ = backtest(SIG["Vortex"], topk=3, check=True)

print()
print("="*128)
print("Q0  持股数量与仓位分配 (修复分配BUG后的真实数字)")
print("="*128)
q0 = []
for tk in [1, 2, 3, 4]:
    for nm in ["Vortex", "动量-1月反转"]:
        e, h, im, ns = backtest(SIG[nm], topk=tk)
        q0.append((f"{nm} Top{tk} 等权满仓", e))
table(q0, "", "策略", 28)

print()
print("="*128)
print("[诊断] 极端收益来源核查: 是数据异常, 还是少数几期暴涨?")
print("="*128)
# 1) 数据体检: 单日收益率异常
r_all = dfC.pct_change()
ext_up = (r_all > 1.0).sum().sum(); ext_dn = (r_all < -0.5).sum().sum()
print(f"  全样本单日涨幅>100% 的观测: {ext_up} 个 | 单日跌幅>50%: {ext_dn} 个 "
      f"(共 {r_all.notna().sum().sum()} 个观测)")
if ext_up:
    w = r_all[r_all > 1.0].stack()
    print(f"    例: {', '.join(f'{c.replace('US.','')} {d.date()} {v*100:.0f}%' for (d,c),v in list(w.items())[:5])}")
print(f"  价格最小值: {np.nanmin(C):.4f}  (若接近0说明复权异常)")
# 2) Top1 策略各期贡献
for nm in ["Vortex", "动量-1月反转"]:
    e1, h1, _, _ = backtest(SIG[nm], topk=1)
    idxs = RB[:len(h1)]
    per = []
    for k in range(1, len(idxs)):
        a, b = idxs[k-1], idxs[k]
        per.append((str(dp[a].date()), ",".join(x.replace("US.","") for x in h1[k-1][1]),
                    e1[b]/e1[a]-1))
    per.sort(key=lambda x: -x[2])
    print(f"\n  {nm} Top1  共 {len(per)} 期, 贡献最大的 8 期:")
    for d, p, r in per[:8]:
        print(f"      {d}  {p:<12} {r*100:>+8.1f}%")
    top10 = np.prod([1+x[2] for x in per[:10]])
    print(f"    -> 最好的 10 期累计贡献 {top10:.0f} 倍; 剔除这 10 期后全程收益 "
          f"{((e1[-1]/CAP0)/top10-1)*100:+.0f}%  (原 {(e1[-1]/CAP0-1)*100:+.0f}%)")

print()
print("="*128)
print("Q1  不加任何择时: 选股策略自带多少熊市防御力?")
print("="*128)
base_res = {}
for nm in SIG:
    base_res[nm] = backtest(SIG[nm])[0]
table([("等权全买(基准)", eq_bh), ("VOO 买入持有", eq_voo),
       ("Vortex Top2", base_res["Vortex"]), ("动量-1月反转 Top2", base_res["动量-1月反转"])],
      "", "策略", 28)

print()
print("="*128)
print("Q2  指数择时能躲开多少? 代价多大?  (基础 = Vortex Top2 月频)")
print("="*128)
sc = SIG["Vortex"]; rows = []
for rn, flag in REG.items():
    for an, sf in [("空仓", None), ("持VOO", VOO_O)]:
        if rn.startswith("无择时") and an == "持VOO": continue
        e, h, im, ns = backtest(sc, expo=flag.astype(float), safe=sf)
        rows.append((f"{rn}+{an}", e, im, ns))
for rn in ["VOO 200DMA 日频", "VOO 50/200 金叉死叉", "VOO 100DMA 日频"]:
    e, h, im, ns = backtest(sc, expo=REG[rn].astype(float)*0.5+0.5, safe=VOO_O)
    rows.append((f"{rn}+半仓(50%)", e, im, ns))
for rn in ["VOO 200DMA 日频", "VOO 50/200 金叉死叉", "VOO 100DMA 日频"]:
    for an, sf in [("持GLD黄金", GLD_O), ("持TLT长债", TLT_O), ("持SHY短债", SHY_O)]:
        e, h, im, ns = backtest(sc, expo=REG[rn].astype(float), safe=sf)
        rows.append((f"{rn}+{an}", e, im, ns))
print(f"{'方案':<28}{'全程':>11}{'最大回撤':>10}{'在场天数':>10}{'切换次数':>10}", end="")
for n, _, _, _ in PHASES: print(f"{n[:9]:>11}", end="")
print()
print("-"*128)
for nm, e, im, ns in rows:
    print(f"{nm:<28}{(e[-1]/CAP0-1)*100:>+10.0f}%{mdd(e):>9.1f}%{im:>8d}日{ns:>9d}", end="")
    for n, s, ee, k in PHASES:
        r = seg(e, s, ee); print(f"{(f'{r[0]:+.0f}%') if r else '-':>11}", end="")
    print()
print("-"*128)
for nm, e in [("[对照] Vortex 裸策略", base_res["Vortex"]), ("[对照] 等权全买", eq_bh)]:
    print(f"{nm:<28}{(e[-1]/CAP0-1)*100:>+10.0f}%{mdd(e):>9.1f}%{'全部':>8}日{0:>9}", end="")
    for n, s, ee, k in PHASES:
        r = seg(e, s, ee); print(f"{(f'{r[0]:+.0f}%') if r else '-':>11}", end="")
    print()

print()
print("="*128)
print("Q3  不依赖指数的防御: 组合回撤止损 / 波动率目标")
print("="*128)
q3 = []
for dd in [0.12, 0.15, 0.20, 0.25, 0.30]:
    e, h, im, ns = backtest(sc, dd_stop=dd)
    q3.append((f"组合回撤止损 {int(dd*100)}%(涨回半程回场)", e, im, ns))
for hi in [0.25, 0.30]:
    e, h, im, ns = backtest(sc, expo=vol_expo(VOO, hi=hi), safe=VOO_O)
    q3.append((f"波动率目标(年化>{int(hi*100)}%降半仓)", e, im, ns))
print(f"{'方案':<34}{'全程':>11}{'最大回撤':>10}{'在场天数':>10}", end="")
for n, _, _, _ in PHASES: print(f"{n[:9]:>11}", end="")
print()
print("-"*128)
print(f"{'[对照] Vortex 裸策略':<34}{(base_res['Vortex'][-1]/CAP0-1)*100:>+10.0f}%{mdd(base_res['Vortex']):>9.1f}%{'全部':>8}日", end="")
for n, s, ee, k in PHASES:
    r = seg(base_res["Vortex"], s, ee); print(f"{(f'{r[0]:+.0f}%') if r else '-':>11}", end="")
print()
for nm, e, im, ns in q3:
    print(f"{nm:<34}{(e[-1]/CAP0-1)*100:>+10.0f}%{mdd(e):>9.1f}%{im:>8d}日", end="")
    for n, s, ee, k in PHASES:
        r = seg(e, s, ee); print(f"{(f'{r[0]:+.0f}%') if r else '-':>11}", end="")
    print()

print()
print("="*128)
print("Q4  择时信号的滞后成本与假信号  (VOO 200DMA 日频)")
print("="*128)
flag = REG["VOO 200DMA 日频"]; ev = []; i = START
while i < N:
    if not flag[i] and (i == START or flag[i-1]):
        j = i
        while j < N and not flag[j]: j += 1
        ev.append((i, j)); i = j
    else: i += 1
print(f"{'离场日':<12}{'回场日':<12}{'离场':>7}{'期间VOO':>10}{'期间等权':>10}{'期间Vortex裸':>13}{'回场后20日VOO':>14}")
print("-"*128)
for a, b in ev:
    if b >= N: b = N-1
    aft = (VOO[min(b+20, N-1)]/VOO[b]-1)*100
    print(f"{str(dp[a].date()):<12}{str(dp[b].date()):<12}{(b-a):>6d}日"
          f"{(VOO[b]/VOO[a]-1)*100:>+9.1f}%{(eq_bh[b]/eq_bh[a]-1)*100:>+9.1f}%"
          f"{(base_res['Vortex'][b]/base_res['Vortex'][a]-1)*100:>+12.1f}%{aft:>+13.1f}%")
print("-"*128)
tot = sum(b-a for a, b in ev)
print(f"共 {len(ev)} 次离场信号, 累计离场 {tot} 个交易日 (占全程 {tot/(N-START)*100:.1f}%)")
wrong = sum(1 for a, b in ev if (VOO[b]/VOO[a]-1) > 0)
print(f"其中离场期间 VOO 反而上涨(假信号) {wrong} 次 / {len(ev)} 次 = {wrong/len(ev)*100:.0f}%")

print()
print("滞后成本: 熊市从顶点到发出离场信号, 已经跌了多少")
BEARS = [("2020 疫情崩盘","2020-02-19","2020-03-23"), ("2022 熊市","2022-01-03","2022-10-12")]
print(f"{'熊市区间':<16}{'顶点日':<12}{'离场信号日':<12}{'滞后':>8}{'信号时已跌':>12}{'熊市全程跌幅':>14}")
print("-"*128)
for nm, s, e in BEARS:
    m = (dp >= pd.Timestamp(s)) & (dp <= pd.Timestamp(e)); idx = np.where(m)[0]
    if len(idx) < 2: continue
    a0, b0 = idx[0], idx[-1]; pk = a0+int(np.argmax(VOO[a0:b0+1]))
    sig = next((a for a, b in ev if a0 <= a <= b0), None)
    if sig is None:
        print(f"{nm:<16}{str(dp[pk].date()):<12}{'无信号':<12}{'-':>8}{'-':>12}{(VOO[b0]/VOO[pk]-1)*100:>+13.1f}%")
    else:
        print(f"{nm:<16}{str(dp[pk].date()):<12}{str(dp[sig].date()):<12}{(sig-pk):>7d}日"
              f"{(VOO[sig]/VOO[pk]-1)*100:>+11.1f}%{(VOO[b0]/VOO[pk]-1)*100:>+13.1f}%")

print()
print("熊市捕获率: 熊市跌幅中实际躲开多少 (括号内为该段最大回撤)")
print(f"{'熊市区间':<16}{'VOO':>16}{'等权全买':>16}{'Vortex裸':>16}{'200DMA空仓':>16}{'50/200空仓':>16}")
print("-"*128)
cache = {rn: backtest(sc, expo=REG[rn].astype(float), safe=None)[0]
         for rn in ["VOO 200DMA 日频", "VOO 50/200 金叉死叉"]}
for nm, s, e in BEARS:
    rv = seg(eq_voo, s, e); rb = seg(eq_bh, s, e); rx = seg(base_res["Vortex"], s, e)
    r1 = seg(cache["VOO 200DMA 日频"], s, e); r2 = seg(cache["VOO 50/200 金叉死叉"], s, e)
    def f(r): return f"{r[0]:+.0f}% ({r[1]:.0f}%)" if r else "-"
    print(f"{nm:<16}{f(rv):>16}{f(rb):>16}{f(rx):>16}{f(r1):>16}{f(r2):>16}")

json.dump({"q0": {nm: float(e[-1]) for nm, e in q0},
           "q2": {nm: {"final": float(e[-1]), "mdd": float(mdd(e))} for nm, e, _, _ in rows},
           "q3": {nm: {"final": float(e[-1]), "mdd": float(mdd(e))} for nm, e, _, _ in q3},
           "events": [[str(dp[a].date()), str(dp[b].date())] for a, b in ev]},
          open(os.path.join(BASE, "_bear_defense_v14.json"), "w"), ensure_ascii=False, indent=2)
print("\nSAVED _bear_defense_v14.json")
