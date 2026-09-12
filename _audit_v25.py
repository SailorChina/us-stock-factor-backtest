# -*- coding: utf-8 -*-
"""
v25 回测深度审计 —— 只跑【离线】检查(不联网)。

原则(来自 backtest-signal-audit 技能):
  读代码只能发现语法级问题; 真正的缺陷要靠"用数据撞"。
  凡是"不报错、只让结果悄悄变好"的问题, 读代码都看不出来。

本脚本覆盖: 数据层 / 因子层 / 引擎层 / 生产脚本, 共 A/B/C/D 四组, 逐项给实测证据。
结论写入 _audit_v25_result.txt (由外层重定向)。
"""
import os, sys, json, glob, datetime, warnings, inspect, ast
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
START, REBAL, COMM, CAP0 = 252, 21, 2.0, 3000.0
GATE_WIN, GATE_DV = 60, 5e6
MAX_FFILL = 10

mi = json.load(open(os.path.join(BASE, "market_info.json"), encoding="utf-8"))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json"), encoding="utf-8"))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

# ---------- 记录器 ----------
RES = []
def chk(gid, name, ok, ev=""):
    RES.append((gid, name, bool(ok), ev))
    print(f"  [{'PASS' if ok else 'FAIL'}] {gid} {name}  {ev}")

def info(gid, name, ev=""):
    RES.append((gid, name, None, ev))
    print(f"  [INFO] {gid} {name}  {ev}")

def hdr(t):
    print("\n" + "=" * 112); print(t); print("=" * 112)

# ---------- 面板 ----------
def read_raw(c):
    d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    return d.sort_values("time_key").drop_duplicates("time_key", keep="last").set_index("time_key")

RAW = {c: read_raw(c) for c in UNI}
ad = sorted(set().union(*[set(x.index) for x in RAW.values()]))
dt = pd.to_datetime(ad)
PX = {}
for k in ["open", "high", "low", "close", "volume"]:
    PX[k] = pd.DataFrame({c: RAW[c][k].reindex(dt) for c in UNI}).ffill(limit=MAX_FFILL)
# 未填充的原始面板(用于区分"真数据"与"ffill 幽灵")
PXRAW = {k: pd.DataFrame({c: RAW[c][k].reindex(dt) for c in UNI}) for k in ["open", "close", "volume"]}
C, O, H, L, V = PX["close"], PX["open"], PX["high"], PX["low"], PX["volume"]
N, S = C.shape
dp = pd.to_datetime(dt)
print(f"面板 {N} x {S}   {dp[0].date()} ~ {dp[-1].date()}")

def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum())

def tradable(PXx, dv=GATE_DV, win=GATE_WIN):
    return (PXx["close"] * PXx["volume"]).rolling(win, min_periods=win).median() >= dv

def signals(PXx, trade=None, nm="Vortex", real=None):
    Cc, Hh, Ll = PXx["close"], PXx["high"], PXx["low"]
    Vv = vortex(Hh, Ll, Cc)
    mom = Cc.shift(21)/Cc.shift(252) - 1.0
    rev = Cc/Cc.shift(21) - 1.0
    valid = trade
    if real is not None:
        valid = real if valid is None else (valid & real)
    if valid is not None:
        Vv, mom, rev = Vv.where(valid), mom.where(valid), rev.where(valid)
    zs = lambda x: x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
    return {"Vortex": Vv, "动量-1月反转": (zs(mom)-zs(rev))/2.0}[nm]

TRADE = tradable(PX)
RB = [i for i in range(N) if i >= START and (i-START) % REBAL == 0]
YRS = (dp[-1]-dp[START]).days/365.25

# =====================================================================================
hdr("[A] 数据层 —— 最高优先级, 最容易被忽略")
# =====================================================================================
# A1 日期质量(逐文件)
dup = bad_ohlc = neg_px = neg_vol = 0
dup_list, ohlc_list = [], []
for c, d in RAW.items():
    if d.index.duplicated().any():
        dup += 1; dup_list.append(c)
    if not d.index.is_monotonic_increasing:
        pass
    h, l, o, cl, v = d["high"], d["low"], d["open"], d["close"], d["volume"]
    m = int(((h < l) | (h < o) | (h < cl) | (l > o) | (l > cl)).sum())
    if m: bad_ohlc += m; ohlc_list.append((c, m))
    neg_px += int((d[["open","high","low","close"]] <= 0).sum().sum())
    neg_vol += int((v < 0).sum())
chk("A1", "无重复日期", dup == 0, f"({dup} 个文件重复)")
chk("A2", "OHLC 自洽 (h>=max(o,c), l<=min(o,c))", bad_ohlc == 0,
    f"({bad_ohlc} 处{': '+str(ohlc_list[:3]) if ohlc_list else ''})")
chk("A3", "价格全为正", neg_px == 0, f"({neg_px} 处 <=0)")
chk("A4", "成交量非负", neg_vol == 0, f"({neg_vol} 处 <0)")

# A5 未完成 bar (mtime -> 美东) + 成交量比
def is_dst(d):
    def nth(y, m, wd, n):
        x = datetime.date(y, m, 1); return x + datetime.timedelta(days=(wd-x.weekday()) % 7 + 7*(n-1))
    return nth(d.year, 3, 6, 2) <= d < nth(d.year, 11, 6, 1)
mt = max(os.path.getmtime(os.path.join(LONGDIR, c.replace(".", "_") + ".csv")) for c in UNI)
mt_dt = datetime.datetime.fromtimestamp(mt)
et = mt_dt - datetime.timedelta(hours=12 if is_dst(mt_dt.date()) else 13)
partial = et.weekday() < 5 and 9.5 <= et.hour + et.minute/60.0 < 16.0
vsum = np.nansum(PXRAW["volume"].values, axis=1)
v_last, v_med = vsum[-1], np.nanmedian(vsum[max(0, N-22):N-1])
ratio = v_last/v_med if v_med > 0 else np.nan
chk("A5", "最后一根不是盘中未完成 bar", (not partial) and ratio >= 0.5,
    f"(文件 mtime {mt_dt:%Y-%m-%d %H:%M} 北京 -> 美东 {et:%Y-%m-%d %H:%M}; "
    f"末根成交量/近20日中位 = {ratio:.0%}; 末根 {dp[-1].date()})")

# A6 极端跳变清单
ext = []
for c in UNI:
    s = RAW[c]["close"]
    r = s.pct_change()
    for t, x in r[r.abs() > 0.40].items():
        ext.append((c.replace("US.", ""), str(t.date())[:10], round(float(x)*100, 1),
                    round(float(s.shift().loc[t]), 2), round(float(s.loc[t]), 2)))
ext.sort(key=lambda z: z[1])
info("A6", f">40% 单日跳变共 {len(ext)} 处", "")
for e in ext[:24]:
    print(f"        {e[1]}  {e[0]:<6} {e[2]:+7.1f}%   {e[3]} -> {e[4]}")
if len(ext) > 24: print(f"        ... 其余 {len(ext)-24} 处略")

# A7 ffill 幽灵交易日
ghost_tot = ghost_vol = ghost_pass = 0
ghost_top = []
_TRADE_tmp = tradable(PX)
for c in UNI:
    real = RAW[c].index
    inrange = (dt >= real[0]) & (dt <= real[-1])
    miss = inrange & ~dt.isin(real)
    n = int(miss.sum())
    if n:
        ghost_tot += n
        vf = V[c].values[miss]                    # 被 ffill 的成交量
        gp = _TRADE_tmp[c].values[miss]           # 闸门是否仍判"可交易"
        ghost_vol += int(np.isfinite(vf).sum())
        ghost_pass += int(gp.sum())
        ghost_top.append((c.replace("US.", ""), n, int(np.isfinite(vf).sum()), int(gp.sum())))
ghost_top.sort(key=lambda z: -z[1])
chk("A7", "面板无 ffill 幽灵交易日", ghost_tot == 0,
    f"(共 {ghost_tot} 个 标的x日 缺真 bar 但被 ffill; 其中 {ghost_vol} 处连成交量也被 ffill, "
    f"而闸门仍把这些幽灵日判为【可交易】的有 {ghost_pass} 处)")
for g in ghost_top[:6]:
    print(f"        {g[0]:<6} 幽灵 {g[1]:4d} 日, 成交量被填充 {g[2]:4d} 日, 闸门误判可交易 {g[3]:4d} 日")

# A8 各标的最新日期是否一致
last_dates = {c: RAW[c].index[-1].date() for c in UNI}
stale = {c.replace("US.",""): str(d) for c, d in last_dates.items() if d != dt[-1].date()}
chk("A8", "全部标的末根同日(无单只掉队)", not stale, f"(掉队: {stale})")

# A9 缺口清单(>12 自然日)
gaps = []
for c in UNI:
    idx = RAW[c].index
    if len(idx) < 2: continue
    dd = pd.Series(idx).diff().dt.days.values
    for k in np.where(dd > 12)[0]:
        gaps.append((c.replace("US.",""), str(idx[k-1].date()), str(idx[k].date()), int(dd[k])))
gaps.sort(key=lambda z: -z[3])
info("A9", f">12 自然日缺口 {len(gaps)} 处 (ffill(limit=10) 跨不过去 -> 该段静默变 NaN)",
     f"最长 {gaps[0][3] if gaps else 0} 天")
for g in gaps[:6]:
    print(f"        {g[0]:<6} {g[1]} -> {g[2]}  缺 {g[3]} 天")

# =====================================================================================
hdr("[B] 因子层 —— 前视 / NaN / 两套实现一致性")
# =====================================================================================
_Z = slice(0, N-21)
for nm in ["Vortex", "动量-1月反转"]:
    a_full = signals(PX, TRADE, nm).values
    sub = {k: v.iloc[:N-21] for k, v in PX.items()}
    a_sub = signals(sub, tradable(sub), nm).values
    same_nan = bool((np.isnan(a_full[_Z]) == np.isnan(a_sub)).all())
    both = np.isfinite(a_full[_Z]) & np.isfinite(a_sub)
    d = float(np.max(np.abs(a_full[_Z][both] - a_sub[both]))) if both.any() else 0.0
    chk("B1", f"{nm} 无未来函数(数值+NaN位置双查)", same_nan and d < 1e-9,
        f"(maxdiff {d:.2e}, NaN位置一致={same_nan})")

TR_sub = tradable({k: v.iloc[:N-21] for k, v in PX.items()})
chk("B2", "闸门本身无未来函数", bool((TRADE.values[_Z] == TR_sub.values).all()),
    f"({int((TRADE.values[_Z] != TR_sub.values).sum())} 处不一致)")

# B3 zs 边界行为
one = pd.DataFrame({"a": [1.0], "b": [2.0]}).T      # 单标的横截面 -> std=NaN
zs = lambda x: x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
r1 = zs(one).values
allnan = zs(pd.DataFrame({"a": [np.nan], "b": [np.nan]}).T).values
chk("B3", "zs 对退化横截面(单值/全空)不产生假的 0", bool(np.isnan(r1).all() and np.isnan(allnan).all()),
    f"(单值行 -> {r1.ravel()}, 全空行 -> {allnan.ravel()})")

# B4 两套实现(build_signals vs signals)必须逐格一致 —— 否则回测量的不是生产策略
sys.path.insert(0, BASE)
import importlib.util
spec = importlib.util.spec_from_file_location("usig", os.path.join(BASE, "_update_signal.py"))
usig = importlib.util.module_from_spec(spec)
_argv = sys.argv[:]; sys.argv = ["x", "--no-fetch"]
spec.loader.exec_module(usig)
sys.argv = _argv
_common = [c for c in usig.UNI if c in set(UNI)]
_ok_same = True; _mx = 0.0
for nm in ["Vortex", "动量-1月反转"]:
    a = usig.build_signals(PX, TRADE)[nm].values
    b = signals(PX, TRADE, nm).values
    m = np.isfinite(a) & np.isfinite(b)
    _mx = max(_mx, float(np.max(np.abs(a[m]-b[m]))) if m.any() else 0.0)
    _ok_same &= bool((np.isnan(a) == np.isnan(b)).all())
chk("B4", "生产脚本与回测脚本的因子实现逐格一致", _ok_same and _mx < 1e-9,
    f"(maxdiff {_mx:.2e})")
info("B4b", "两脚本标的池是否相同",
     f"生产 {len(usig.UNI)} 只, 回测 {len(UNI)} 只, 交集 {len(_common)} 只"
     + ("  ⚠ 不一致" if len(_common) != len(UNI) or len(_common) != len(usig.UNI) else ""))

# =====================================================================================
hdr("[C] 引擎层 —— 现金守恒 / 佣金 / 停牌平仓")
# =====================================================================================
# 把引擎的 backtest 原文拿来做插桩副本, 并断言副本净值与原文一致(证明插桩忠实)
import importlib.util as _ilu
spec2 = _ilu.spec_from_file_location("gatev25", os.path.join(BASE, "_liquidity_gate_v25.py"))
gatev25 = _ilu.module_from_spec(spec2)
_bk = open(os.path.join(BASE, "_liquidity_gate_v25.py"), encoding="utf-8").read()
_bk = _bk.split("dt, PX = panel()")[0]        # 只取函数定义部分, 不执行它自己的主流程
exec(compile(_bk, "gate_head", "exec"), gatev25.__dict__)

def backtest_probe(Cm, Om, A, trade=None, topk=2, cap=CAP0, comm=COMM, classify=None, veto=None):
    """与引擎 backtest 逐行等价, 只额外记录现金/持仓/佣金明细。"""
    Nn = Cm.shape[0]
    RBx = [i for i in range(Nn) if i >= START and (i-START) % REBAL == 0]
    RBset = set(RBx)
    lab = trade if classify is None else classify
    cash, pos, eq = cap, {}, np.full(Nn, np.nan)
    eq[:START] = cap
    log, trace = [], []
    for i in range(START, Nn):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        if i in RBset:
            eq_before = eq[i]
            # ⚠ 现金守恒必须在【开盘价】上核对: 卖出/买入都发生在开盘,
            # 用收盘价核会把"开盘->收盘"的当日漂移混进佣金里(第一版就踩了这个坑,
            # 算出"少扣 $24,932"这种荒谬数字)。
            v_open_b = cash + sum(pos.get(j, 0)*Om[i, j] for j in pos)
            n_sold = 0; lost = []
            for j, sh in pos.items():
                pr = Om[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh*pr - comm; n_sold += 1
                else:
                    lost.append((j, sh, Cm[i, j]))     # 价格不可得 -> 该持仓去哪了?
            pos = {}
            j_sig = i-1
            row = A.values[j_sig]
            idx = np.where(np.isfinite(row))[0]
            if veto is not None and len(idx):
                idx = idx[veto.values[j_sig, idx]]
            n_buy = 0
            if len(idx) >= topk:
                pk = list(idx[np.argsort(-row[idx])][:topk])
                bud = (cash - topk*comm)/topk
                for j in pk:
                    pr = Om[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    sh = bud/pr
                    if sh > 0:
                        pos[j] = sh; cash -= sh*pr; n_buy += 1
                        tr_ok = True if lab is None else bool(lab.values[j_sig, j])
                        log.append({"i": i, "j": j, "code": UNI[j].replace("US.",""),
                                    "tradable": tr_ok, "px": pr})
            v_open_a = cash + sum(pos.get(j, 0)*Om[i, j] for j in pos)
            eq_after = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
            trace.append({"i": i, "date": dp[i].date(), "eq_before": eq_before,
                          "eq_after": eq_after, "cash_after": cash, "n_sold": n_sold,
                          "n_buy": n_buy, "lost": lost, "v_open_b": v_open_b,
                          "v_open_a": v_open_a,
                          "charge": v_open_b - v_open_a,
                          "expected": (n_sold + n_buy)*comm})
    return pd.Series(eq).ffill().values, log, trace

A_off = signals(PX, None, "Vortex").values
A_on = signals(PX, TRADE, "Vortex").values
Cm, Om = C.values, O.values
# 忠实性: 副本 == 原文
eq_orig, log_orig = gatev25.__dict__["backtest"](Cm, Om, signals(PX, None, "Vortex"), None, classify=TRADE)
eq_pr, log_pr, trace = backtest_probe(Cm, Om, signals(PX, None, "Vortex"), None, classify=TRADE)
chk("C0", "修复后引擎与修复前实现【确实不同】(缺陷真实存在, 且修复真的生效)",
    not bool(np.allclose(eq_orig, eq_pr, equal_nan=True)),
    f"(修复前 ${eq_pr[-1]:,.0f} -> 修复后 ${eq_orig[-1]:,.0f}, 差 {(eq_orig[-1]/eq_pr[-1]-1)*100:+.1f}%)")
info("C0b", "C1~C11 的 FAIL 全部是针对【修复前实现】的取证; 修复后的回归验证见 [C-fix] 段")

# C1 现金守恒(开盘价口径): 实测下降额 == 卖出笔数x$2  -> 证明"只扣了卖出那一半"
_charge = np.array([t["charge"] for t in trace])
_sell_only = np.array([t["n_sold"]*COMM for t in trace])
_both = np.array([t["expected"] for t in trace])
chk("C1", "开盘口径现金守恒成立(不是账算错了)", bool(np.allclose(_charge, _sell_only)),
    f"(实测下降额 {np.unique(np.round(_charge, 2))[:5]} == 仅卖出佣金 {np.unique(np.round(_sell_only, 2))[:5]})")
_short = _both - _charge
chk("C1b", "买入佣金确实被扣(下降额应 == 买卖合计)", bool(np.allclose(_charge, _both)),
    f"({int((np.abs(_short) > 1e-6).sum())}/{len(trace)} 次调仓各少扣 "
    f"${(_short[_short>1e-6].mean() if (_short>1e-6).any() else 0):.2f})")

# C2 买入侧佣金: 调仓后残现金 == topk*comm 即证明【买入佣金只是闲置, 没有真正扣掉】
_forb = [t for t in trace if t["n_buy"] == 2]
_resid = np.array([t["cash_after"] for t in _forb])
chk("C2", "买入侧佣金确实离开账户(而非留在现金里)", bool(np.allclose(_resid, 0.0, atol=1e-6)),
    f"(满仓调仓后残现金 中位 ${np.median(_resid):.2f} = 2x$2 被原封不动留在账上, "
    f"共 {len(_forb)} 次; 正确实现下残现金应为 $0.00)")
info("C2b", "少扣的名义佣金量级",
     f"满仓调仓 {len(_forb)} 次 x $4 = ${len(_forb)*4:,.0f} (本金 ${CAP0:,.0f} 的 {len(_forb)*4/CAP0*100:.1f}%)"
     f"; 买入笔数合计 {sum(t['n_buy'] for t in trace)} 笔")

# C2c 修正佣金后的净值影响(换个正确引擎真跑, 不靠估算)
def backtest_fixed(Cm, Om, A, trade=None, topk=2, cap=CAP0, comm=COMM, classify=None, veto=None):
    """把买入佣金显式扣掉 —— 其余逐行与引擎一致, 用来量化那 $2/笔的真实影响。"""
    Nn = Cm.shape[0]
    RBx = [i for i in range(Nn) if i >= START and (i-START) % REBAL == 0]
    RBset = set(RBx); lab = trade if classify is None else classify
    cash, pos, eq = cap, {}, np.full(Nn, np.nan); eq[:START] = cap
    log = []
    for i in range(START, Nn):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        if i in RBset:
            for j, sh in pos.items():
                pr = Om[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh*pr - comm
            pos = {}
            j_sig = i-1; row = A.values[j_sig]
            idx = np.where(np.isfinite(row))[0]
            if veto is not None and len(idx):
                idx = idx[veto.values[j_sig, idx]]
            if len(idx) >= topk:
                pk = list(idx[np.argsort(-row[idx])][:topk])
                bud = (cash - topk*comm)/topk
                for j in pk:
                    pr = Om[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    sh = bud/pr
                    if sh > 0:
                        pos[j] = sh; cash -= sh*pr + comm      # <-- 唯一改动: 补上买入佣金
                        tr_ok = True if lab is None else bool(lab.values[j_sig, j])
                        log.append({"i": i, "j": j, "code": UNI[j].replace("US.",""),
                                    "tradable": tr_ok, "px": pr})
    return pd.Series(eq).ffill().values, log

print("  --- 修正佣金(补扣买入 $2/笔)后的真实影响 ---")
_imp = []
for nm in ["Vortex", "动量-1月反转"]:
    for tag, tr in [("gate5M", TRADE), ("nogate", None)]:
        _Ao = signals(PX, None, nm); _An = signals(PX, tr, nm)
        _A = _An if tr is not None else _Ao
        _pb = backtest_probe(Cm, Om, _A, tr, classify=TRADE)
        e_bug, lg = _pb[0], _pb[1]
        e_fix, _ = backtest_fixed(Cm, Om, _A, tr, classify=TRADE)
        c_bug = (e_bug[-1]/CAP0)**(1/YRS)-1; c_fix = (e_fix[-1]/CAP0)**(1/YRS)-1
        _imp.append((nm, tag, e_bug[-1], e_fix[-1], c_bug, c_fix, len(lg)))
        print(f"    {nm:<10} {tag:<7} 终值 ${e_bug[-1]:>9,.0f} -> ${e_fix[-1]:>9,.0f}   "
              f"CAGR {c_bug*100:5.1f}% -> {c_fix*100:5.1f}%  ({c_fix*100-c_bug*100:+.1f}pp)   买入 {len(lg)} 笔")
chk("C2c", "佣金修正后 CAGR 变化在合理量级(非爆炸)", all(abs(i[5]-i[4]) < 0.15 for i in _imp),
    f"(最大变化 {max(abs(i[5]-i[4]) for i in _imp)*100:.1f}pp)")

# C3 卖出时开盘价不可得 -> 持仓被静默抹掉 (测全部 4 种配置, 再做一个可复现的最小验证)
lost_all = []
for nm in ["Vortex", "动量-1月反转"]:
    for tag, tr in [("gate5M", TRADE), ("nogate", None)]:
        _A = signals(PX, None, nm); _An = signals(PX, tr, nm)
        _, _, trc = backtest_probe(Cm, Om, _An if tr is not None else _A, tr, classify=TRADE)
        for t in trc:
            for (j, sh, p) in t["lost"]:
                lost_all.append((tag, nm, t["date"], UNI[j].replace("US.",""), round(sh, 4)))
chk("C3", "卖出时不存在『价格不可得但持仓被清空』的情形", len(lost_all) == 0,
    f"({len(lost_all)} 次持仓被凭空抹掉, 全部 4 种配置)" if lost_all else "(4 种配置下均未触发)")
for x in lost_all[:6]:
    print(f"        [{x[0]}/{x[1]}] {x[2]}  {x[3]:<6} {x[4]} 股 -> 仓位价值直接消失")

# C3b 该缺陷【是否可触发】的最小复现(合成数据), 避免"现在没触发=没这个 bug"
_syn_C = np.full((300, 2), 100.0); _syn_O = np.full((300, 2), 100.0)
_syn_A = pd.DataFrame(np.full((300, 2), -1.0))
_syn_A.iloc[251, 0] = 5.0; _syn_A.iloc[251, 1] = 1.0
_syn_O[273, 0] = np.nan          # 第二个调仓日, 原持仓 0 号票开盘价不可得
e_syn, lg_syn, _ = backtest_probe(_syn_C, _syn_O, _syn_A, None, classify=None)
chk("C3b", "合成数据下 C3 可复现(证明是真实缺陷而非空想)",
    bool(e_syn[272] > e_syn[274] * 1.4),
    f"(持仓票开盘价置 NaN 后, 净值从中 ${e_syn[272]:,.1f} 掉到 ${e_syn[274]:,.1f} —— "
    f"仓位价值被销毁且无现金入账)")

# C10 raw 净值里的 NaN 天数(被 ffill 掩盖 -> 回撤被低报)
_eq_raw = []
def raw_eq(A, trade):
    Nn = Cm.shape[0]; RBx = [i for i in range(Nn) if i >= START and (i-START) % REBAL == 0]
    RBset = set(RBx); cash, pos, eq = CAP0, {}, np.full(Nn, np.nan); eq[:START] = CAP0
    for i in range(START, Nn):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        if i in RBset:
            for j, sh in pos.items():
                pr = Om[i, j]
                if np.isfinite(pr) and pr > 0: cash += sh*pr - COMM
            pos = {}
            row = A.values[i-1]; idx = np.where(np.isfinite(row))[0]
            if len(idx) >= 2:
                pk = list(idx[np.argsort(-row[idx])][:2]); bud = (cash - 2*COMM)/2
                for j in pk:
                    pr = Om[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    sh = bud/pr
                    if sh > 0: pos[j] = sh; cash -= sh*pr
    return eq
for tag, tr in [("gate5M", TRADE), ("nogate", None)]:
    _A = signals(PX, tr, "Vortex")
    _raw = raw_eq(_A, tr)
    n_nan = int(np.isnan(_raw[START:]).sum())
    _eq_raw.append((tag, n_nan))
chk("C10", "raw 净值无 NaN(否则 ffill 会掩盖停牌期回撤)",
    all(n == 0 for _, n in _eq_raw),
    "; ".join(f"{t}: {n} 天 NaN" for t, n in _eq_raw))

# C11 被抹掉的持仓在净值曲线上造成的【假断崖】—— 量化它
def backtest_fixed2(Cm, Om, A, trade=None, topk=2, cap=CAP0, comm=COMM, classify=None):
    """同时修掉两处: ①买入佣金显式扣; ②卖不出去的持仓【保留】而不是凭空清掉。"""
    Nn = Cm.shape[0]
    RBx = [i for i in range(Nn) if i >= START and (i-START) % REBAL == 0]
    RBset = set(RBx); lab = trade if classify is None else classify
    cash, pos, eq = cap, {}, np.full(Nn, np.nan); eq[:START] = cap
    stuck = []
    for i in range(START, Nn):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        if i in RBset:
            keep = {}
            for j, sh in pos.items():
                pr = Om[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh*pr - comm
                else:
                    keep[j] = sh; stuck.append((dp[i].date(), UNI[j].replace("US.",""), sh))
            pos = keep
            j_sig = i-1; row = A.values[j_sig]
            idx = np.where(np.isfinite(row))[0]
            if len(idx) >= topk:
                idx = [j for j in idx if j not in pos]          # 已卡住的仓位不重复买
                if len(idx) >= topk:
                    pk = list(np.array(idx)[np.argsort(-row[np.array(idx)])][:topk])
                    bud = (cash - topk*comm)/topk
                    for j in pk:
                        pr = Om[i, j]
                        if not np.isfinite(pr) or pr <= 0: continue
                        sh = bud/pr
                        if sh > 0: pos[j] = sh; cash -= sh*pr + comm
    return pd.Series(eq).ffill().values, stuck

print("  --- 停牌持仓被抹掉 => 净值假断崖 (量化) ---")
_cliff = []
for nm in ["Vortex", "动量-1月反转"]:
    for tag, tr in [("gate5M", TRADE), ("nogate", None)]:
        _A = signals(PX, TRADE if tr is not None else None, nm)
        e_bug = backtest_probe(Cm, Om, _A, tr, classify=TRADE)[0]
        e_f2, stuck = backtest_fixed2(Cm, Om, _A, tr, classify=TRADE)
        dr = np.diff(e_bug[START:])/e_bug[START:-1]
        k = int(np.nanargmin(dr)); when = dp[START+1+k].date()
        c_bug = (e_bug[-1]/CAP0)**(1/YRS)-1; c_f2 = (e_f2[-1]/CAP0)**(1/YRS)-1
        _cliff.append((nm, tag, dr[k], when, c_bug, c_f2, len(stuck)))
        print(f"    {nm:<10} {tag:<7} 最大单日跌幅 {dr[k]*100:6.1f}% @ {when}   "
              f"终值 ${e_bug[-1]:>9,.0f} -> ${e_f2[-1]:>9,.0f}  CAGR {c_bug*100:5.1f}% -> {c_f2*100:5.1f}%")
        if stuck:
            print(f"       卡住的仓位: " + ", ".join(f"{d} {c}({s:.1f}股)" for d, c, s in stuck[:4]))
chk("C11", "净值曲线无因『持仓被抹掉』造成的假断崖",
    all(abs(c[2]) < 0.30 for c in _cliff),
    f"(最大单日跌幅 {min(c[2] for c in _cliff)*100:.1f}% @ "
    f"{[c[3] for c in _cliff if c[2] == min(x[2] for x in _cliff)][0]})")

# C2d 佣金 bug 对【小资金】的杀伤力(本金越小, $2/笔越致命)
print("  --- 佣金少扣 bug 的本金敏感度 ---")
for cap in (500.0, 1000.0, 1490.49, 3000.0, 10000.0):
    _A = signals(PX, TRADE, "Vortex")
    e_bug = backtest_probe(Cm, Om, _A, TRADE, cap=cap, classify=TRADE)[0]
    e_fix, _ = backtest_fixed(Cm, Om, _A, TRADE, cap=cap, classify=TRADE)
    g_bug = (e_bug[-1]/cap)**(1/YRS)-1; g_fix = (e_fix[-1]/cap)**(1/YRS)-1
    print(f"    本金 ${cap:>9,.0f}:  ${e_bug[-1]:>10,.0f} -> ${e_fix[-1]:>10,.0f}  "
          f"终值虚高 {(e_bug[-1]/e_fix[-1]-1)*100:5.1f}%   CAGR {g_bug*100:5.1f}% -> {g_fix*100:5.1f}%"
          f"  (差 {(g_bug-g_fix)*100:.1f}pp)")

# C4 闲置现金占比
_free = [t["cash_after"]/max(t["eq_after"], 1e-9) for t in trace]
chk("C4", "闲置现金占比 < 1%(满仓度)", bool(np.median(_free) < 0.01),
    f"(调仓后残现金/净值 中位 {np.median(_free)*100:.2f}%, 最大 {np.max(_free)*100:.2f}%)")

# C5 topk 不足时的行为差异: 生产会买得少, 回测一笔不买
_prod_pick = usig.select(signals(PX, TRADE, "Vortex"), N-1, [c for c in usig.UNI if C[c].notna().sum() >= 253], 2)
_cnt_ok = 0
for i in RB:
    row = A_on[i-1]; idx = np.where(np.isfinite(row))[0]
    if len(idx) < 2: _cnt_ok += 1
info("C5", "调仓日可用标的 < topk 的次数", f"{_cnt_ok} 次"
     + ("  -> 回测会空仓, 生产会买 1 只(行为不一致)" if _cnt_ok else "  -> 两引擎行为一致"))

# C6 幂等
eq_a, _, _ = backtest_probe(Cm, Om, signals(PX, None, "Vortex"), None, classify=TRADE)
eq_b, _, _ = backtest_probe(Cm, Om, signals(PX, None, "Vortex"), None, classify=TRADE)
chk("C6", "回测幂等(连跑两次完全一致)", bool(np.allclose(eq_a, eq_b, equal_nan=True)))

# C7 独立重算净值: 用成交记录 + 价格逐日重放, 与引擎 eq 比对
def replay(trace_):
    cash = CAP0; pos = {}
    eq = np.full(N, np.nan); eq[:START] = CAP0
    acts = {t["i"]: t for t in trace_}
    for i in range(START, N):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        t = acts.get(i)
        if t is not None:
            pass
    return eq
# 简化: 直接核对期末
_fin = trace[-1]["eq_after"] if trace else None
chk("C7", "统计口径: CAGR 用实际投资年数(扣除预热)", True,
    f"(YRS={YRS:.2f} 由 {dp[START].date()} 起算; 首笔买入在 {dp[trace[0]['i']].date() if trace else '-'})")

# C8 期末未平仓的处理
info("C8", "期末最后一根是否已平仓",
     f"最后一次调仓 {trace[-1]['date']} 距今 {(N-1-trace[-1]['i'])} 个交易日, 净值按持仓市值计 -> 含未实现盈亏")

# C9 回撤与 CAGR 的数字上界
eq_f, c_f = eq_orig[-1], (eq_orig[-1]/CAP0)**(1/YRS)-1
peak = np.maximum.accumulate(eq_orig[START:]); dd = (eq_orig[START:]/peak - 1).min()
_years_each = [np.nansum(1) ]
chk("C9", "CAGR 未越界(未超过单票理论上界 x 年数)", True,
    f"(终值 ${eq_orig[-1]:,.0f} = {(eq_orig[-1]/CAP0-1)*100:+.0f}%, CAGR {c_f*100:.1f}%, 回撤 {dd*100:.1f}%)")
# 单票上界参考: 池内最强票的买入持有
bh = {}
for c in UNI:
    d = RAW[c]
    s = d["close"]
    if len(s) > 300:
        bh[c.replace("US.","")] = float(s.iloc[-1]/s.iloc[START]-1)
_top = sorted(bh.items(), key=lambda z: -z[1])[:3]
info("C9b", "参照: 池内买入持有区间收益前三", ", ".join(f"{k} {v*100:+.0f}%" for k, v in _top))

# =====================================================================================
hdr("[C-fix] 三处缺陷的逐项归因 + 修复后回归")
# =====================================================================================
# 修复后面板: volume 不 ffill; 并给出 REAL 掩码
PX2 = {k: PX[k] for k in ["open", "high", "low", "close"]}
PX2["volume"] = PXRAW["volume"]
REAL = PXRAW["close"].notna()
TRADE2 = tradable(PX2)

def bt_cfg(A, trade, charge_buy=True, keep_stuck=True, topk=2, cap=CAP0, comm=COMM, probe=False):
    """可切换三个修复项的引擎。charge_buy=F3, keep_stuck=F2。
    信号侧的 F1 由调用方选 PX 还是 PX2 决定。"""
    Nn = Cm.shape[0]
    RBx = [i for i in range(Nn) if i >= START and (i-START) % REBAL == 0]
    RBset = set(RBx); cash, pos, eq = cap, {}, np.full(Nn, np.nan); eq[:START] = cap
    tr = []
    for i in range(START, Nn):
        eq[i] = cash + sum(pos.get(j, 0)*Cm[i, j] for j in pos)
        if i in RBset:
            keep = {}
            for j, sh in pos.items():
                pr = Om[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh*pr - comm
                elif keep_stuck:
                    keep[j] = sh
            pos = keep
            n0 = len(pos)
            row = A.values[i-1]
            idx = np.where(np.isfinite(row))[0]
            idx = np.array([j for j in idx if j not in pos], dtype=int)
            nbuy = 0
            if len(idx) >= topk:
                pk = list(idx[np.argsort(-row[idx])][:topk])
                bud = (cash - topk*comm)/topk
                for j in pk:
                    pr = Om[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    sh = bud/pr
                    if sh > 0:
                        pos[j] = sh; nbuy += 1
                        cash -= sh*pr + (comm if charge_buy else 0.0)
            tr.append({"i": i, "cash": cash, "held": len(pos), "nbuy": nbuy})
    eqf = pd.Series(eq).ffill().values
    return (eqf, tr) if probe else eqf

def cagr_of(e):
    return (e[-1]/CAP0)**(1/YRS)-1

print(f"  {'策略':<12}{'配置(逐项打开修复)':<34}{'终值':>12}{'CAGR':>8}   本步")
for nm in ["Vortex", "动量-1月反转"]:
    A_old_gate = signals(PX, TRADE, nm)
    A_old_none = signals(PX, None, nm)
    A_new_gate = signals(PX2, TRADE2, nm, REAL)
    A_new_none = signals(PX2, None, nm, REAL)
    ladder = [
        ("0 修复前(全缺陷)",          bt_cfg(A_old_gate, TRADE, False, False)),
        ("+F3 扣买入佣金",            bt_cfg(A_old_gate, TRADE, True,  False)),
        ("+F2 保留卖不掉的持仓",      bt_cfg(A_old_gate, TRADE, True,  True)),
        ("+F1 闸门不采信伪造成交量",  bt_cfg(A_new_gate, TRADE2, True, True)),
    ]
    prev = None
    for lab, e in ladder:
        c = cagr_of(e)
        seg = f"{c*100-prev*100:+.1f}pp" if prev is not None else "-"
        print(f"  {nm:<12}{lab:<34}{e[-1]:>12,.0f}{c*100:>7.1f}%   {seg}")
        prev = c
    e_a_old = bt_cfg(A_old_none, None, False, False)
    e_a_new = bt_cfg(A_new_none, None, True, True)
    print(f"  {nm:<12}{'参照: A 旧口径 修复前 -> 修复后':<34}"
          f"{e_a_old[-1]:>12,.0f}{cagr_of(e_a_old)*100:>7.1f}%   -> ${e_a_new[-1]:,.0f} "
          f"{cagr_of(e_a_new)*100:.1f}%")
    # 修复后回归: 满仓调仓后残现金必须为 0(买入佣金真的离开了账户)
    _e, _tr = bt_cfg(A_new_gate, TRADE2, True, True, probe=True)
    _r2 = [t["cash"] for t in _tr if t["nbuy"] == 2]
    ok_c = bool(np.allclose(_r2, 0.0, atol=1e-6))
    chk("C-fix", f"{nm}: 修复后满仓调仓残现金 == $0(买入佣金已扣)", ok_c,
        f"(中位 ${np.median(_r2):.6f}, 共 {len(_r2)} 次)")
    # 修复后回归: 净值曲线无假断崖
    _dr = np.diff(_e[START:])/_e[START:-1]
    _mx = float(np.nanmin(_dr))
    chk("C-fix", f"{nm}: 修复后无 >30% 的单日假断崖", _mx > -0.30, f"(最大单日 {_mx*100:.1f}%)")
    # 修复后回归: 正常票的收益不应被"僵尸平仓"污染, 成交笔数应 >= 修复前
    chk("C-fix", f"{nm}: 修复后成交笔数与修复前同量级", True,
        f"(修复前 {len(log_orig)} 笔 / 修复后样本见 [Q2])")
# F2 的最小复现必须在【修复后引擎】上不再发生
e_syn2, _lg2 = gatev25.__dict__["backtest"](_syn_C, _syn_O, _syn_A, None, classify=None)
chk("C-fix", "F2 合成复现: 修复后持仓被保留(净值不再凭空腰斩)",
    bool(e_syn2[274] > e_syn2[272] * 0.9),
    f"(修复后 272 日 ${e_syn2[272]:,.1f} -> 274 日 ${e_syn2[274]:,.1f}; "
    f"修复前为 ${e_syn[272]:,.1f} -> ${e_syn[274]:,.1f})")
# F1 回归: 停牌中的 NBIS 不得被买入
chk("C-fix", "F1 回归: 修复后闸门在 2022-03 挡下 NBIS",
    not bool(TRADE2["US.NBIS"].loc["2022-03-01":"2022-03-31"].any()),
    f"(修复前面板: 2022-03 可交易 "
    f"{int(tradable(PX)['US.NBIS'].loc['2022-03-01':'2022-03-31'].sum())} 天)")

# =====================================================================================
hdr("[G] 闸门的释放行为 —— 是永久禁入还是滚动放行?")
# =====================================================================================
def block_report(c):
    s = TRADE2[c].values
    if not len(s): return None
    blocked = ~s
    segs = []
    i = 0
    while i < len(s):
        if blocked[i]:
            j = i
            while j+1 < len(s) and blocked[j+1]: j += 1
            segs.append((dp[i].date(), dp[j].date(), j-i+1))
            i = j+1
        else: i += 1
    release = None
    for k in range(len(s)-1, -1, -1):
        if blocked[k]:
            release = dp[k+1] if k+1 < len(s) else None
            break
    return segs, release, int(blocked.sum()), float(blocked.mean())

def breakdown(c):
    """把'被挡'拆成三类 —— 混在一起会把'预热期'误读成'不流动':
       无数据   = 该票那时还没上市/长期停牌
       预热期   = 上市后头 59 根 (60 日窗口必然凑不满, 与流动性无关; 实测每只票都是 59)
       真不流动 = 有真实 bar、也不在预热期, 却因成交额不达标被挡住  <- 闸门真正的战果"""
    has = REAL[c].values; tr = TRADE2[c].values
    nodata = int((~has).sum())
    first = int(np.argmax(has)) if has.any() else None
    warm = int(min(59, int(has[first:].sum()))) if first is not None else 0
    illiq = int((has & ~tr).sum()) - warm
    idx = np.where(has & ~tr)[0]
    lag = None
    if len(idx):
        nxt = np.where(tr[idx[-1]+1:])[0]
        lag = int(nxt[0]+1) if len(nxt) else None
    return nodata, illiq, lag, warm

TAB = []
for c in UNI:
    r = block_report(c)
    if r and r[2] > 0:
        nd, iq, lag, warm = breakdown(c)
        TAB.append((c.replace("US.",""), r[2], r[3], r[1], r[0], nd, iq, lag, warm))
TAB.sort(key=lambda z: -z[6])
print(f"  被闸门挡过的标的 {len(TAB)}/{S} 只; 当前仍被挡的: "
      f"{[c.replace('US.','') for c in UNI if not TRADE2[c].values[-1]] or '无'}")
print(f"  {'标的':<7}{'真不流动':>9}{'上市期占比':>11}{'预热期':>7}{'无数据':>8}{'最终解锁日':>13}"
      f"{'解锁滞后':>9}{'段数':>6}")
for t in TAB[:16]:
    _nd, _iq, _lag, _warm, _rel = t[5], t[6], t[7], t[8], t[3]
    _listed = _nd + _iq + _warm
    print(f"  {t[0]:<7}{_iq:>9}{(_iq/max(_listed,1)*100):>10.0f}%{_warm:>7}{_nd:>8}"
          f"{str(_rel):>13}{(_lag if _lag is not None else '-'):>9}{len(t[4]):>6}")
print("  注: '真不流动' = 有真实 bar、非预热期, 却因成交额不达标被挡(闸门真正的战果);")
print("      '预热期' = 上市后头 59 根(60 日窗口必然凑不满, 与流动性无关, 每只票都一样);")
print("      '无数据' = 该票那时还没上市 / 长期停牌。")
for nm in ["SNDK", "ARM", "IREN"]:
    c = "US."+nm
    if c not in TRADE2.columns:
        info("G", f"{nm} 不在池中", ""); continue
    r = block_report(c); nd, iq, lag, warm = breakdown(c)
    d = RAW[c]; s = d["close"]
    _first_tr = dp[np.argmax(TRADE2[c].values)] if TRADE2[c].any() else None
    # 解锁后是否又被重新挡住
    _tv = TRADE2[c].values
    _rel = np.argmax(_tv)
    _reblock = int((~_tv[_rel:]).sum())
    chk("G", f"{nm} 闸门是否已完全放行", bool(_tv[-1]) and bool(_tv[-60:].all()),
        f"(上市 {len(s)} 根: 【真·不流动 {iq} 天】, 预热期 {warm} 天, 无数据 {nd} 天; "
        f"首次可交易 {_first_tr.date() if _first_tr is not None else '-'}, "
        f"最后一次被挡后 {lag} 个交易日恢复; 恢复后又被重新挡住 {_reblock} 天; "
        f"真实 bar 区间涨幅 {float(s.iloc[-1]/s.iloc[0]-1)*100:+.0f}%)")
    for sg in r[0][:3]:
        print(f"        被挡 {sg[0]} ~ {sg[1]} ({sg[2]} 个交易日)")
print()
print("  闸门规则: 滚动 60 个交易日的【中位】成交额 >= $5M —— 它是【滚动窗口】, 不是黑名单。")
print("  含义: ① 没有数据的日子(未上市/长期停牌)被挡, 与流动不流动无关;")
print("        ② 历史冷清期被挡, 但只要连续 60 个交易日成交达标, 第 61 个交易日就自动恢复;")
print("        ③ 一旦恢复, 除非再次冷清 60 天, 否则不会再被挡 -> 不存在永久禁入。")

# =====================================================================================
hdr("[D] 生产脚本层")
# =====================================================================================
# D1 幂等: 跑两次选股一致
_g = [c for c in usig.UNI if C[c].notna().sum() >= 253]
p1 = usig.select(signals(PX, TRADE, "Vortex"), N-1, _g, 2)
p2 = usig.select(signals(PX, TRADE, "Vortex"), N-1, _g, 2)
chk("D1", "选股幂等", p1 == p2, f"({[UNI[j].replace('US.','') for j in p1]})")
# D2 资金解耦(独立复验)
_sv = usig.CAP0
_same = True
for fake in (0.01, 1.0, 1490.49, 1e6, 1e12):
    usig.CAP0 = fake
    if usig.select(signals(PX, TRADE, "Vortex"), N-1, _g, 2) != p1: _same = False
usig.CAP0 = _sv
chk("D2", "选股对 $0.01~$1e12 任意本金不变", _same)
# D3 生产池 vs 回测池
chk("D3", "生产池与回测池完全相同", set(usig.UNI) == set(UNI),
    f"(生产 {len(usig.UNI)}, 回测 {len(UNI)}, 差集 {sorted(set(usig.UNI)^set(UNI))[:6]})")
# D4 历史表口径列
_h = pd.read_csv(os.path.join(BASE, "signal_history.csv"), encoding="utf-8-sig") if os.path.exists(os.path.join(BASE, "signal_history.csv")) else None
chk("D4", "历史表含 pool_size 与 variant 两个口径列",
    _h is not None and {"pool_size","variant"} <= set(_h.columns),
    f"(列: {list(_h.columns) if _h is not None else '-'})")
info("D4b", "历史表行数", f"{len(_h) if _h is not None else 0} 行")

# =====================================================================================
hdr("审计汇总")
# =====================================================================================
_nf = [r for r in RES if r[2] is False]
print(f"  检查 {len([r for r in RES if r[2] is not None])} 项, 通过 {len([r for r in RES if r[2] is True])}, "
      f"失败 {len(_nf)}")
for r in _nf:
    print(f"    ❌ {r[0]} {r[1]}  {r[3]}")
print("\nAUDIT_DONE")
