# -*- coding: utf-8 -*-
"""
全策略统一重跑与总排名 (v26)
================================================================================
目的: 把项目历史上验证过的【全部策略】放到【同一套引擎、同一池子、同一区间、同一成本】
      下重跑, 然后从高到低排序。

为什么必须"统一重跑"而不是"汇总旧报告":
  旧报告的数字来自【四代不同的引擎】——
    v8~v11  收盘价成交 + 佣金 max(0.01/股, $1.5) + ffill 到极致
    v14     开盘价成交, 但第二只票买不进(分配 BUG)
    v21~v22 月频, 仍带 ffill 幽灵成交量
    v25     ffill 幽灵成交量 + 停牌持仓被抹掉 + 买入佣金漏扣
  把它们并列排名等于拿四种尺子量身高。本脚本一律用 v25.1 修复后的引擎重算。

引擎口径 (v25.1 修复版, 与 _liquidity_gate_v25.py / _update_signal.py 一致):
  * T 日收盘算信号 -> T+1 开盘价成交 (可成交性最接近实盘)
  * 佣金 $2/笔, 买卖双边各收 (用户富途实盘口径, 与股数无关)
  * volume 不做 ffill; 无真 bar 的日子因子置 NaN (REAL 掩码)
  * 卖不掉的持仓【保留】而不是清空 (F2 修复)
  * 买入佣金显式扣除 (F3 修复)

两套口径并列输出:
  口径A 无闸门 —— 纯信号能力 (但会买到当天没法成交的票)
  口径B 有闸门 —— 可实盘口径 (滚动60日中位成交额 >= $5M)

用法:
  python _rank_all_strategies.py            # 全量
  python _rank_all_strategies.py --fast     # 跳过 AI(walk-forward 随机森林), 省几分钟
"""
import os, sys, json, time, warnings, datetime
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
IDXDIR = os.path.join(BASE, "data_index_long")
OUT_JSON = os.path.join(BASE, "_rank_all_1500.json")

START, REBAL, COMM, CAP0 = 252, 21, 2.0, 1500.0
GATE_WIN, GATE_DV = 60, 5e6
MAX_FFILL = 10
FAST = "--fast" in sys.argv

mi = json.load(open(os.path.join(BASE, "market_info.json"), encoding="utf-8"))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json"), encoding="utf-8"))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]


# ============================================================================
# 1. 数据层 (v25.1: volume 不 ffill + REAL 掩码)
# ============================================================================
def read_csv_dir(dirpath, codes):
    p = {}
    for c in codes:
        f = os.path.join(dirpath, c.replace(".", "_") + ".csv")
        d = pd.read_csv(f)
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").drop_duplicates("time_key", keep="last").set_index("time_key")
    return p

_raw = read_csv_dir(LONGDIR, UNI)
_all = sorted(set().union(*[set(x.index) for x in _raw.values()]))
DT = pd.to_datetime(_all)

PX, REAL = {}, {}
for k in ["open", "high", "low", "close", "volume"]:
    m = pd.DataFrame({c: _raw[c][k].reindex(DT) for c in UNI})
    # volume 例外: 停牌日没有成交, 不是"昨天的成交量"
    PX[k] = m if k == "volume" else m.ffill(limit=MAX_FFILL)
REAL = pd.DataFrame({c: _raw[c]["close"].reindex(DT).notna() for c in UNI})

O, H, L, C, V = PX["open"], PX["high"], PX["low"], PX["close"], PX["volume"]
Ov, Cv, Rv = O.values, C.values, REAL.values
# 【标记专用价】多天停牌(超过 MAX_FFILL)时 Cv/Ov 会变 NaN, 但持仓还在。
# 若此时把它的市值记成 0, 净值就会出现"凭空少一块"的假断崖 —— 这正是 F2 的家族缺陷,
# 只不过位置从"清仓"挪到了"计净值"。停牌期间按【停牌前最后价】计入才是正确口径。
CSv = C.ffill().values
N = len(DT)

# 基准与择时用的指数 (data_index_long 里有 TLT/GLD/SHY/IEF)
IDX = read_csv_dir(IDXDIR, ["US.VOO", "US.SPY", "US.GLD", "US.TLT", "US.SHY"])
def idx_close(code):
    return IDX[code]["close"].reindex(DT).ffill()
VOO_RAW, SPY_RAW, GLD_RAW = idx_close("US.VOO"), idx_close("US.SPY"), idx_close("US.GLD")
VOO_C = VOO_RAW.values


def panel_gate():
    """与 _update_signal.tradable_mask / _liquidity_gate_v25.tradable 同一条规则。

    注意: close 是前复权(QFQ)价, 历史成交额被同比例缩小(F4, 全池实测只翻转 4 格)。
    这里有意保留与生产脚本完全一致的口径, 不在这里发明新规则。
    """
    return (PX["close"] * PX["volume"]).rolling(GATE_WIN, min_periods=GATE_WIN).median() >= GATE_DV


TRADE = panel_gate()                       # 闸门(可交易)表
GMASK = TRADE.values & Rv                  # 闸门 与 真有bar 的交集


# ============================================================================
# 2. 指标库 (与 _deep_indicators_v11.py / _liquidity_gate_v25.py 逐字一致)
# ============================================================================
def true_range(h, l, c):
    pc = c.shift()
    return np.maximum(np.maximum(h - l, (h - pc).abs()), (l - pc).abs())

def zs(x):
    m, s = x.mean(axis=1), x.std(axis=1)
    return x.sub(m, axis=0).div(s, axis=0).replace([np.inf, -np.inf], np.nan)

def ens(zlist):
    arr = np.stack([z.values for z in zlist], axis=0)
    with np.errstate(invalid="ignore"):
        m = np.nanmean(arr, axis=0)
    return pd.DataFrame(m, index=zlist[0].index, columns=zlist[0].columns)

def rsi(c, n=14):
    d = c.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(alpha=1/n, adjust=False).mean(); al = l.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + ag/al)

def cci(h, l, c, n=20):
    tp = (h + l + c)/3; sma = tp.rolling(n).mean()
    mad = (tp - sma).abs().rolling(n).mean()
    return (tp - sma)/(0.015*mad)

def stochastic(h, l, c, n=14):
    ll, hh = l.rolling(n).min(), h.rolling(n).max()
    return (c - ll)/(hh - ll)*100

def williamsR(h, l, c, n=14):
    hh, ll = h.rolling(n).max(), l.rolling(n).min()
    return (hh - c)/(hh - ll)*-100

def bollinger_pctB(c, n=20, k=2):
    m, s = c.rolling(n).mean(), c.rolling(n).std()
    return (c - (m - k*s))/((m + k*s) - (m - k*s))

def macd_hist(c, f=12, s=26, sig=9):
    ml = c.ewm(span=f, adjust=False).mean() - c.ewm(span=s, adjust=False).mean()
    return ml - ml.ewm(span=sig, adjust=False).mean()

def adx_di(h, l, c, n=14):
    up, dn = h.diff(), -l.diff()
    pdm = ((up > dn) & (up > 0))*up; mdm = ((dn > up) & (dn > 0))*dn
    atr = true_range(h, l, c).ewm(alpha=1/n, adjust=False).mean()
    pdi = (pdm.ewm(alpha=1/n, adjust=False).mean()/atr)*100
    mdi = (mdm.ewm(alpha=1/n, adjust=False).mean()/atr)*100
    return pdi - mdi

def roc(c, n): return c/c.shift(n) - 1.0
def donchian(c, n=55): return c/c.rolling(n).max() - 1.0

def obv(c, v):
    sign = np.sign(c.diff()).replace(0, np.nan).fillna(0.0)
    return (sign*v).cumsum()

def cmf(h, l, c, v, n=20):
    den = (h - l).replace(0, np.nan)
    m = ((c - l) - (h - c))/den*v
    return m.rolling(n).sum()/v.rolling(n).sum()

def mfi(h, l, c, v, n=14):
    tp = (h + l + c)/3; rmf = tp*v
    up, dn = tp.diff() > 0, tp.diff() < 0
    pos = rmf.where(up, 0.0).rolling(n).sum(); neg = rmf.where(dn, 0.0).rolling(n).sum()
    return 100 - 100/(1 + pos/neg.replace(0, np.nan))

def ad_line(h, l, c, v):
    den = (h - l).replace(0, np.nan)
    return (((c - l) - (h - c))/den*v).cumsum()

def chaikin_adosc(h, l, c, v, s=3, l2=10):
    den = (h - l).replace(0, np.nan)
    cl = ((c - l) - (h - c))/den*v
    return cl.ewm(span=s, adjust=False).mean() - cl.ewm(span=l2, adjust=False).mean()

def accel(c, v, n=5, w=60):
    up = (c.pct_change(n) > 0).astype(float)
    return up*(v/v.rolling(w).mean())

def aroon(h, l, n=25):
    up = h.rolling(n).apply(lambda x: ((n-1) - x[::-1].argmax())/(n-1)*100, raw=True)
    dn = l.rolling(n).apply(lambda x: ((n-1) - x[::-1].argmin())/(n-1)*100, raw=True)
    return up - dn

def psar(h, l, af=0.02, max_af=0.20):
    n = len(h)
    sar = np.full(n, np.nan); ep = np.full(n, np.nan)
    upt = np.zeros(n, bool); afc = np.zeros(n)
    ep[0] = h[0]; sar[0] = l[0]; upt[0] = True; afc[0] = af
    for i in range(1, n):
        ps = sar[i-1]
        if upt[i-1]:
            sar[i] = ps + afc[i-1]*(ep[i-1] - ps)
            if l[i] < sar[i]:
                upt[i] = False; sar[i] = ep[i-1]; ep[i] = l[i]; afc[i] = af
            else:
                upt[i] = True
                if h[i] > ep[i-1]: ep[i] = h[i]; afc[i] = min(afc[i-1] + af, max_af)
                else: ep[i] = ep[i-1]; afc[i] = afc[i-1]
        else:
            sar[i] = ps - afc[i-1]*(ps - ep[i-1])
            if h[i] > sar[i]:
                upt[i] = True; sar[i] = ep[i-1]; ep[i] = h[i]; afc[i] = af
            else:
                upt[i] = False
                if l[i] < ep[i-1]: ep[i] = l[i]; afc[i] = min(afc[i-1] + af, max_af)
                else: ep[i] = ep[i-1]; afc[i] = afc[i-1]
    return sar

def sar_dist(c, h, l):
    out = pd.DataFrame(index=h.index, columns=h.columns, dtype=float)
    for col in h.columns:
        a, b = h[col].values, l[col].values
        if np.isnan(a).all(): continue
        out[col] = c[col].values/psar(a, b) - 1.0
    return out

def keltner(h, l, c, n=20, m=2):
    ema = c.ewm(span=n, adjust=False).mean()
    atr = true_range(h, l, c).ewm(span=n, adjust=False).mean()
    return c/(ema + m*atr) - 1.0

def ichimoku(c, h, l):
    ten = (h.rolling(9).max() + l.rolling(9).min())/2
    kij = (h.rolling(26).max() + l.rolling(26).min())/2
    sena = (ten + kij)/2
    senb = (h.rolling(52).max() + l.rolling(52).min())/2
    return c/np.maximum(sena, senb) - 1.0

def cmo(c, n=20):
    d = c.diff()
    su = d.clip(lower=0).rolling(n).sum(); sd = (-d.clip(upper=0)).rolling(n).sum()
    return (su - sd)/(su + sd)*100

def tsi(c, r=25, s=13):
    m = c.diff()
    e2 = m.ewm(span=r, adjust=False).mean().ewm(span=s, adjust=False).mean()
    a2 = m.abs().ewm(span=r, adjust=False).mean().ewm(span=s, adjust=False).mean()
    return e2/a2*100

def vortex(h, l, c, n=14):
    tr = true_range(h, l, c)
    vp = (h - l.shift()).abs().rolling(n).sum()
    vn = (l - h.shift()).abs().rolling(n).sum()
    ts = tr.rolling(n).sum()
    return vp/ts - vn/ts


# ============================================================================
# 3. 引擎 (v25.1 修复版 + 可选 regime / 止损 / 趋势组合)
# ============================================================================
def engine(A=None, elig=None, topk=2, gate=None, stop=0.0, regime=None, safe_px=None,
           cap=CAP0, comm=COMM, keep_stuck=True, charge_buy=True, rebal=REBAL,
           anchor=START, trace=False):
    """调仓: 第 i 日开盘执行, 信号取第 i-1 日收盘。

    A       : 打分表 (NaN = 不可选)。与 elig 二选一。
    elig    : 趋势组合模式, 传函数 i -> [列索引...] (等权持有全部合格标的)。
    gate    : 可交易掩码; 参与打分/买入的标的必须同时有真 bar。
    stop    : 日内止损比例 (0=不启用)。收盘价跌破"持仓期最高收盘价*(1-stop)" ->
              次日开盘卖出, 持现金到下一个调仓日。
    regime  : 逐日布尔数组; 信号日为 False 时清仓并转为持有 safe_px (或空仓)。
    rebal   : 调仓周期(交易日)。必须显式传入 —— 频率变体就靠它, 不能读全局。
    anchor  : 调仓日历的相位起点。默认 START(与历史口径一致, 不改变任何既有结果);
              相位扫描时取遍 [START, START+rebal) 看看结论是不是只属于某一天起步。
    """
    RB = set(i for i in range(N) if i >= anchor and (i - anchor) % rebal == 0)
    gm = None if gate is None else (gate.values & Rv)
    cash, pos = cap, {}
    eq = np.full(N, np.nan); eq[:START] = cap
    cashf = np.full(N, np.nan); npos = np.zeros(N, int)
    pk_close, pending, log = {}, set(), []
    safe_sh = 0.0
    dead, bankrupt_i = False, None
    recon, n_stuck, resid = [], 0, []
    casharr = np.full(N, np.nan); hold = [None]*N
    for i in range(START, N):
        if not dead:
            # --- A) 开盘: 执行昨日收盘登记的止损单 ---
            for j in list(pending):
                if j in pos:
                    pr = Ov[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += pos.pop(j)*pr - comm
                        pk_close.pop(j, None)
                    # 卖不掉 -> 保留, B 段会再清一次, 绝不会凭空消失
            pending = set()

            # --- B) 调仓 ---
            if i in RB:
                js = i - 1
                # 结算价: 开盘价优先; 开盘不可得(长期停牌)时退到停牌前最后价。
                def _sx(j):
                    p = Ov[i, j]
                    if np.isfinite(p) and p > 0: return float(p)
                    q = CSv[i, j]
                    return float(q) if np.isfinite(q) else np.nan
                def _val():
                    v = cash
                    for j, sh in pos.items():
                        p = _sx(j)
                        if np.isfinite(p): v += sh*p
                    if safe_sh > 0 and safe_px is not None:
                        s = float(safe_px[i])
                        if np.isfinite(s): v += safe_sh*s
                    return v
                # 清仓 (v25.1 F2: 卖不掉的保留; keep_stuck=False 复现旧缺陷用于回归)
                v_before = _val()
                n_sell_c = 0            # 卖出侧实际收取的佣金笔数(含安全资产)
                keep = {}
                for j, sh in pos.items():
                    pr = Ov[i, j]
                    if np.isfinite(pr) and pr > 0:
                        cash += sh*pr - comm; n_sell_c += 1
                    elif keep_stuck:
                        keep[j] = sh
                        if not (np.isfinite(CSv[i, j]) and CSv[i, j] > 0):
                            n_stuck += 1          # 连最后价都没有 -> 真·无法估值(理论不可达)
                    else:
                        pass                      # 旧缺陷: 价值凭空消失
                pos = keep if keep_stuck else {}
                for j in list(pk_close):
                    if j not in pos: pk_close.pop(j, None)
                if safe_sh > 0:
                    sp = float(safe_px[i]) if safe_px is not None else np.nan
                    if np.isfinite(sp) and sp > 0:
                        cash += safe_sh*sp - comm; safe_sh = 0.0; n_sell_c += 1
                    # 安全资产也拿不到价 -> 保留(同一条原则: 价值绝不凭空消失)
                want_safe = (regime is not None) and (not bool(regime[js]))
                v_after_sell = _val()
                n_buy_c = 0             # 买入侧实际收取的佣金笔数(含安全资产)
                n_intend = 0            # 本次调仓【计划】买入笔数 (供"满仓后残现金==0"自检用)
                if want_safe and safe_sh == 0.0:
                    if safe_px is not None:
                        sp = float(safe_px[i])
                        if np.isfinite(sp) and sp > 0:
                            sh = (cash - comm)/sp
                            if sh > 0:
                                n_intend = 1
                                safe_sh = sh
                                cash -= sh*sp
                                # ⚠ 修正: 旧版把 n_buy_c += 1 写在 charge_buy 之外,
                                # 导致 charge_buy=False 时"记账收了佣金、现金却没扣" ->
                                # 价值守恒恒等式会凭空多出 comm。与权益分支的口径对齐。
                                if charge_buy: cash -= comm; n_buy_c += 1
                elif not want_safe:
                    if elig is not None:
                        cand = [j for j in elig(js)]
                        if gm is not None and len(cand):
                            cand = [j for j in cand if gm[js, j]]
                        cand = [j for j in cand if j not in pos]
                        if len(cand) >= topk:
                            bud = max(0.0, (cash - len(cand)*comm)/len(cand))
                            n_intend = len(cand)
                            for j in cand:
                                pr = Ov[i, j]
                                if not np.isfinite(pr) or pr <= 0: continue
                                sh = bud/pr
                                if sh > 0:
                                    pos[j] = sh; pk_close[j] = Cv[i, j]
                                    cash -= sh*pr
                                    if charge_buy: cash -= comm; n_buy_c += 1
                                    log.append({"i": i, "j": j})
                    else:
                        row = A.values[js]
                        idx = np.where(np.isfinite(row))[0]
                        if gm is not None and len(idx):
                            idx = idx[gm[js, idx]]
                        idx = np.array([j for j in idx if j not in pos], dtype=int)
                        if len(idx) >= topk:
                            pk = list(idx[np.argsort(-row[idx])][:topk])
                            bud = max(0.0, (cash - topk*comm)/topk)
                            n_intend = topk
                            for j in pk:
                                pr = Ov[i, j]
                                if not np.isfinite(pr) or pr <= 0: continue
                                sh = bud/pr
                                if sh > 0:
                                    pos[j] = sh; pk_close[j] = Cv[i, j]
                                    cash -= sh*pr
                                    if charge_buy: cash -= comm; n_buy_c += 1
                                    log.append({"i": i, "j": j})

                # 价值守恒恒等式 (在【开盘价】口径上结算, 不在收盘价上 —— 否则会把
                # 当日开盘->收盘的漂移混进佣金里, 得出 $24,932 这种荒唐数字):
                #   卖出前总值 - 卖出后总值 == 卖出佣金笔数 × 佣金
                #   卖出后总值 - 买入后总值 == 买入佣金笔数 × 佣金
                # 佣金笔数必须把【安全资产那一次买卖】也算进去, 否则 regime 变体
                # 会每次都留下恰好 $2 的假残差(实测 264 处)。
                v_after_buy = _val()
                recon.append((i,
                              v_before - v_after_sell - n_sell_c*comm,
                              v_after_sell - v_after_buy - n_buy_c*comm,
                              max(abs(v_before), 1.0)))
                # "佣金只被预留、没真扣走" 的通用探针: 一次【计划笔数全部成交】的调仓
                # 结束后, 账上残现金必须恰好为 0。若恒等于 k×佣金, 就是买入佣金没扣(F3)。
                if n_intend > 0 and n_buy_c == n_intend:
                    resid.append((i, cash))

                # 破产判定: 清仓佣金超过账户总价值 -> 这笔调仓在现实中根本执行不了
                if cash < -1e-6:
                    dead, bankrupt_i = True, i
                    pos, safe_sh, cash = {}, 0.0, 0.0
                    pk_close, pending = {}, set()

            # --- C) 收盘: 更新持仓期峰值 + 登记明日止损 ---
            if not dead and stop > 0:
                for j in list(pos):
                    cc = CSv[i, j]          # 停牌期间用最后价, 不制造假止损
                    if np.isfinite(cc):
                        pk_close[j] = max(pk_close.get(j, cc), cc)
                        if cc <= pk_close[j]*(1 - stop):
                            pending.add(j)
        else:
            pos, safe_sh, cash = {}, 0.0, 0.0

        # --- D) 记净值 (收盘价口径; 停牌持仓按最后价计入, 不得记 0) ---
        mv = 0.0
        for j, sh in pos.items():
            cc = CSv[i, j]
            if np.isfinite(cc):
                mv += sh*cc
        safe_mv = safe_sh*float(safe_px[i]) if (safe_sh > 0 and safe_px is not None) else 0.0
        eq[i] = cash + mv + safe_mv
        casharr[i] = cash
        if trace:
            hold[i] = {j: sh for j, sh in pos.items()}
            if safe_sh > 0: hold[i][-1] = safe_sh     # -1 = 安全资产(VOO/GLD/现金)
        cashf[i] = cash/eq[i] if eq[i] > 0 else np.nan
        npos[i] = len(pos) + (1 if safe_sh > 0 else 0)
    out = {"eq": eq, "cashf": cashf, "npos": npos, "log": log, "cash_end": cash,
           "bankrupt_i": bankrupt_i, "recon": recon, "n_stuck": n_stuck, "resid": resid}
    if trace:
        out["casharr"] = casharr; out["hold"] = hold
    return out


# ============================================================================
# 4. 指标计算
# ============================================================================
PHASES = [
    ("2018牛市",      "2018-01-02", "2018-09-20"),
    ("2018Q4回落",    "2018-09-21", "2018-12-24"),
    ("2019-20.2牛",   "2019-01-01", "2020-02-19"),
    ("2020崩盘",      "2020-02-19", "2020-03-23"),
    ("2020-21牛",     "2020-03-24", "2021-12-31"),
    ("2022熊市",      "2022-01-03", "2022-10-12"),
    ("2023-26牛",     "2023-01-01", "2026-09-10"),
]
_YRS = (DT[-1] - DT[START]).days/365.25


def metrics(res, dt=None):
    dt = DT if dt is None else dt
    s = pd.Series(res["eq"], index=pd.DatetimeIndex(dt)).iloc[START:]
    final = float(s.iloc[-1])
    bankrupt_i = res.get("bankrupt_i")
    bdate = str(pd.DatetimeIndex(dt)[bankrupt_i].date()) if bankrupt_i is not None else None
    total = final/CAP0 - 1
    # 破产(清仓佣金吞掉账户)时终值为 0 -> CAGR 记 -100%, 不产生复数
    cagr = ((final/CAP0)**(1/_YRS) - 1) if final > 0 else -1.0
    r = s.pct_change().dropna()
    sd = r.std()
    sharpe = float(r.mean()/sd*np.sqrt(252)) if sd > 0 else np.nan
    dnr = r[r < 0]
    sortino = float(r.mean()/dnr.std()*np.sqrt(252)) if len(dnr) > 2 and dnr.std() > 0 else np.nan
    peak = s.cummax(); dd = s/peak - 1
    mdd = float(dd.min()); mdd_date = str(dd.idxmin().date())
    calmar = cagr/abs(mdd) if mdd < 0 else np.nan
    daily_min = float(r.min()) if len(r) else np.nan
    # 月/年收益
    mo = s.groupby([s.index.year, s.index.month]).last()
    mo = pd.Series(np.concatenate([[CAP0], mo.values])).pct_change().dropna()
    yr = s.groupby(s.index.year).last()
    yrs_idx = sorted(yr.index)
    yr_ret = {}
    prev = CAP0
    for y in yrs_idx:
        yr_ret[int(y)] = float(yr[y]/prev - 1); prev = float(yr[y])
    # 分阶段
    ph = {}
    for nm, a, b in PHASES:
        m = (s.index >= a) & (s.index <= b)
        seg = s[m]
        if len(seg) < 2: ph[nm] = None; continue
        ph[nm] = float(seg.iloc[-1]/seg.iloc[0] - 1)
    npos_arr = res["npos"][START:]
    cash_arr = np.nan_to_num(res["cashf"][START:], nan=0.0)
    return {
        "final": final, "total": total, "cagr": cagr, "years": _YRS,
        "mdd": mdd, "mdd_date": mdd_date, "sharpe": sharpe, "sortino": sortino,
        "calmar": calmar, "daily_min": daily_min,
        "bankrupt": bankrupt_i is not None, "bankrupt_date": bdate,
        "vol": float(sd*np.sqrt(252)) if sd > 0 else np.nan,
        "mo_win": float((mo > 0).mean()), "mo_best": float(mo.max()), "mo_worst": float(mo.min()),
        "yr_win": float(np.mean([v > 0 for v in yr_ret.values()])) if yr_ret else np.nan,
        "yr_ret": yr_ret, "phases": ph,
        "n_trades": len(res["log"]), "turnover_yr": len(res["log"])/_YRS,
        "avg_pos": float(npos_arr.mean()), "avg_cash": float(cash_arr.mean()),
        "monthly": [float(x) for x in mo.values],
    }


# ============================================================================
# 5. 信号构建
# ============================================================================
SV = lambda df: df.where(REAL)      # 口径无关的兜底掩码(只叠 REAL)

pct = lambda a, n: a/a.shift(n) - 1.0
mom12_1 = C.shift(21)/C.shift(252) - 1.0
rev21 = C/C.shift(21) - 1.0
vort14 = vortex(H, L, C, 14)
ma50, ma200 = C.rolling(50).mean(), C.rolling(200).mean()
golden = ma50 > ma200
ma_dist50 = C/ma50 - 1.0
ma_dist200 = C/ma200 - 1.0
ma_slope200 = ma200.pct_change(20)
above200 = C > ma200
donch55 = donchian(C, 55)

rsi14, rsi7 = rsi(C, 14), rsi(C, 7)
cci20, cci14 = cci(H, L, C, 20), cci(H, L, C, 14)
stochK = stochastic(H, L, C, 14); willR = williamsR(H, L, C, 14)
bbB = bollinger_pctB(C, 20, 2); macdH = macd_hist(C)
di_diff = adx_di(H, L, C, 14); roc60 = roc(C, 60); roc120 = roc(C, 120)

obv_s = obv(C, V).pct_change(20)
cmf20 = cmf(H, L, C, V, 20)
mfi14 = mfi(H, L, C, V, 14)
ad_s = ad_line(H, L, C, V).pct_change(20)
adosc = chaikin_adosc(H, L, C, V)
acc = accel(C, V)

aroon25 = aroon(H, L, 25)
sard = sar_dist(C, H, L)
kelt = keltner(H, L, C)
ichi = ichimoku(C, H, L)

cmo20 = cmo(C, 20); tsi13 = tsi(C)
mom_multi = 0.1*pct(C, 21) + 0.2*pct(C, 63) + 0.3*pct(C, 126) + 0.4*pct(C, 252)

VOO_MA200 = VOO_RAW.rolling(200).mean()
REGIME = (VOO_RAW > VOO_MA200).values
SPY_MA200 = SPY_RAW.rolling(200).mean()
REGIME_SPY = (SPY_RAW > SPY_MA200).values

AI_A = AI_C = None
if not FAST:
    try:
        from sklearn.ensemble import RandomForestClassifier
        def build_ai(win=756, seed=0, HOR=21, warmup=378, n_est=120):
            """walk-forward 随机森林。

            两个必须对齐的点(都会静默给出"看起来合理"的错答案):
            1. 得分必须落在【信号日】= 执行日前一根, 不是执行日当天。
               本引擎读 A[i-1], 若把得分写在 i 上, 策略永远拿不到分数 ->
               净值恒等于本金(实测表现: 收益 0.0%、回撤 0.0%、夏普 nan)。
            2. 训练目标不得越界: t1 = i - HOR 保证用到的 fwd 收益在信号日已知。
               (v11 原版用【执行日当天收盘】打分并在当天开盘成交, 属前视偏差, 这里已改正。)
            """
            feat = np.stack([pct(C, 21).values, pct(C, 63).values, pct(C, 126).values,
                             pct(C, 252).values, C.pct_change().rolling(20).std().values,
                             rsi(C, 14).values, macd_hist(C).values,
                             (V/V.rolling(60).mean()).values, bbB.values,
                             (C/C.rolling(50).mean() - 1).values], axis=-1)
            fwd = (C.shift(-HOR)/C - 1.0).values
            vf = (~np.any(np.isnan(feat), axis=2)) & Rv   # 无真 bar 的格子不得进入特征/预测
            vt = ~np.isnan(fwd)
            rf = RandomForestClassifier(n_estimators=n_est, max_depth=4, min_samples_leaf=30,
                                        class_weight="balanced", n_jobs=-1, random_state=seed)
            score = np.full((N, C.shape[1]), np.nan)
            exec_days = [x for x in range(N) if x >= START and (x - START) % REBAL == 0]
            for i in [x - 1 for x in exec_days if x - 1 >= 0]:      # <- 信号日, 不是执行日
                if i < warmup + HOR: continue
                t0, t1 = max(warmup, i - win), i - HOR
                m = vf[t0:t1+1] & vt[t0:t1+1]
                if m.sum() < 200: continue
                X, y = feat[t0:t1+1][m], (fwd[t0:t1+1][m] > 0).astype(int)
                if y.sum() == 0 or y.sum() == len(y): continue
                rf.fit(X, y)
                mp = vf[i]
                if mp.sum() == 0: continue
                pr = np.full(C.shape[1], np.nan); pr[mp] = rf.predict_proba(feat[i][mp])[:, 1]
                score[i] = pr
            n_ok = int(np.sum(~np.isnan(score).all(axis=1)))
            first = str(DT[int(np.argmax(~np.isnan(score).all(axis=1)))].date()) if n_ok else "—"
            print(f"  [AI] win={win} seed={seed}: 有效信号日 {n_ok} 天 (首个 {first})")
            return pd.DataFrame(score, index=DT, columns=C.columns)
        t_ai = time.time()
        AI_A = build_ai(756, 0)
        AI_C = build_ai(504, 0)
        print(f"  [AI] walk-forward 随机森林构建完成 ({time.time()-t_ai:.0f}s)")
    except Exception as e:
        print(f"  [AI] 跳过 (sklearn 不可用或失败: {e})")


# ---- 信号"按口径延迟构建" ----
# 【关键一致性约束】横截面统计量(z-score 的均值/标准差)必须在【掩码之后】计算 ——
# 否则躺平票"恰好为 0"的收益仍会参与"什么算好"的定义, 闸门就白开了。
# 这与 _update_signal.build_signals 的做法逐字一致(生产脚本同样先 where(valid) 再 zs)。
# 所以每个信号都写成 f(valid) -> DataFrame, 两种口径各构建一次。
def TS(df):
    """纯时序因子: 掩码顺序不影响数值, 但也统一走这条路径。"""
    return lambda v: df.where(v)

XS_REV = lambda v: (zs(mom12_1.where(v)) - zs(rev21.where(v)))/2.0
XS_SMART = lambda v: ens([zs(obv_s.where(v)), zs(cmf20.where(v)), zs(mfi14.where(v)),
                          zs(ad_s.where(v)), zs(adosc.where(v)), zs(acc.where(v))])
XS_TA = lambda v: ens([zs(aroon25.where(v)), zs(sard.where(v)),
                       zs(kelt.where(v)), zs(ichi.where(v))])
XS_TECHX = lambda v: ens([zs(cmo20.where(v)), zs(tsi13.where(v)), zs(vort14.where(v))])
XS_MA = lambda v: ens([zs(ma_dist50.where(v)), zs(ma_slope200.where(v))])


# ============================================================================
# 6. 策略注册表
# ============================================================================
STRATS = []
def add(name, family, sig=None, elig=None, topk=2, stop=0.0, regime=None, safe=None, rebal=REBAL):
    """sig: f(valid) -> DataFrame。延迟构建, 保证两种口径各按自己的掩码算横截面统计量。"""
    STRATS.append(dict(name=name, family=family, sig=sig, elig=elig, topk=topk,
                       stop=stop, regime=regime, safe=safe, rebal=rebal))

# ---- I. 因子家族 ----
add("Vortex Top2", "因子", sig=TS(vort14))
add("动量-1月反转 Top2", "因子", sig=XS_REV)
add("经典12-1动量 Top2", "因子", sig=TS(mom12_1))
add("多周期动量加权 Top2", "因子", sig=TS(mom_multi))
add("双动量(12-1+个股MA200门) Top2", "因子", sig=TS(mom12_1.where(above200)))
add("Vortex Top1", "因子", sig=TS(vort14), topk=1)
add("Vortex Top3", "因子", sig=TS(vort14), topk=3)
add("动量-1月反转 Top1", "因子", sig=XS_REV, topk=1)
add("动量-1月反转 Top3", "因子", sig=XS_REV, topk=3)

# ---- II. 均线系统 ----
add("MA50距离 Top2", "均线", sig=TS(ma_dist50))
add("MA200距离 Top2", "均线", sig=TS(ma_dist200))
add("MA50距离 Top3", "均线", sig=TS(ma_dist50), topk=3)
add("金叉+MA50距离 Top2", "均线", sig=TS(ma_dist50.where(golden)))
add("MA200斜率 Top2", "均线", sig=TS(ma_slope200))
add("均线距离组合(MA50+斜率) Top2", "均线", sig=XS_MA)
# 趋势组合 (纯择时, 无 TopK): elig 返回列索引列表
add("趋势组合 >MA200等权", "均线",
    elig=lambda i: [k for k in range(len(UNI)) if bool(above200.iloc[i].values[k])], topk=1)
add("趋势组合 金叉个股等权", "均线",
    elig=lambda i: [k for k in range(len(UNI)) if bool(golden.iloc[i].values[k])], topk=1)
# 【新增】佣金感知版: 原版"持有全部合格标的"在 $2/笔 固定佣金下会被吃穿(见总榜破产标记)。
# 这里把宽度压到 Top10 / Top5, 用来隔离"是信号不好"还是"是宽度太贵"。
add("趋势组合 >MA200 Top10等权(新增)", "均线", sig=TS(ma_dist50.where(above200)), topk=10)
add("趋势组合 >MA200 Top5等权(新增)", "均线", sig=TS(ma_dist50.where(above200)), topk=5)

# ---- III. 技术指标 ----
# 注意: Vortex 在 v11 里归入"技术指标", v25 起归入"因子"(它就是主策略)。
# 只列一次, 避免榜单出现同名重复项。
for nm, df in [("RSI14", rsi14), ("RSI7", rsi7), ("CCI20", cci20), ("CCI14", cci14),
               ("Stochastic%K", stochK), ("Williams%R", willR), ("Bollinger%B", bbB),
               ("MACD柱", macdH), ("DI差", di_diff), ("ROC60", roc60), ("ROC120", roc120),
               ("Donchian55", donch55), ("CMO20", cmo20), ("TSI", tsi13)]:
    add(f"{nm} Top2", "技术指标", sig=TS(df))
add("技术指标组合(TSI+Vortex+CMO) Top2", "技术指标", sig=XS_TECHX)

# ---- IV. 技术分析 ----
for nm, df in [("Aroon25", aroon25), ("SAR距离", sard), ("Keltner突破", kelt),
               ("Ichimoku云", ichi)]:
    add(f"{nm} Top2", "技术分析", sig=TS(df))
add("技术分析组合(4合1) Top2", "技术分析", sig=XS_TA)

# ---- V. 聪明钱 ----
for nm, df in [("OBV斜率", obv_s), ("CMF20", cmf20), ("MFI14", mfi14), ("AD线斜率", ad_s),
               ("Chaikin ADOsc", adosc), ("放量加速度", acc)]:
    add(f"{nm} Top2", "聪明钱", sig=TS(df))
add("聪明钱组合(6合1) Top2", "聪明钱", sig=XS_SMART)

# ---- VI. AI ----
if AI_A is not None:
    add("AI随机森林(窗口756) Top2", "AI", sig=TS(AI_A))
    add("AI随机森林(窗口504) Top2", "AI", sig=TS(AI_C))
    add("AI+动量 Top2", "AI",
        sig=lambda v: ens([zs(AI_A.where(v)), zs(mom12_1.where(v))]))
    add("AI+聪明钱 Top2", "AI",
        sig=lambda v: ens([zs(AI_A.where(v)), XS_SMART(v)]))
    add("全家桶混合(动量+聪明钱+技术+AI) Top2", "AI",
        sig=lambda v: ens([zs(mom12_1.where(v)), XS_SMART(v), XS_TA(v), zs(AI_A.where(v))]))

# ---- VII. 风控变体 (止损 + 熊市防御) ----
add("Vortex +15%止损 +200DMA(熊持VOO)", "风控", sig=TS(vort14), stop=0.15,
    regime=REGIME, safe=VOO_C)
add("动量-1月反转 +15%止损 +200DMA(熊持VOO)", "风控", sig=XS_REV, stop=0.15,
    regime=REGIME, safe=VOO_C)
add("经典12-1 +15%止损 +200DMA(熊持VOO)", "风控", sig=TS(mom12_1), stop=0.15,
    regime=REGIME, safe=VOO_C)
add("聪明钱组合 +15%止损 +200DMA(熊持VOO)", "风控", sig=XS_SMART, stop=0.15,
    regime=REGIME, safe=VOO_C)
add("技术分析组合 +15%止损 +200DMA(熊持VOO)", "风控", sig=XS_TA, stop=0.15,
    regime=REGIME, safe=VOO_C)
add("Vortex +200DMA空仓(无止损)", "风控", sig=TS(vort14), regime=REGIME, safe=None)
add("Vortex +200DMA(熊持黄金GLD)", "风控", sig=TS(vort14), regime=REGIME,
    safe=GLD_RAW.reindex(DT).ffill().values)
add("Vortex +100DMA空仓", "风控", sig=TS(vort14),
    regime=(VOO_RAW > VOO_RAW.rolling(100).mean()).values, safe=None)

# ---- VIII. 调仓频率变体 (对两个主策略) ----
for rb in [5, 10, 15, 42, 63]:
    add(f"Vortex Top2 @{rb}日调仓", "频率", sig=TS(vort14), rebal=rb)
    add(f"动量-1月反转 Top2 @{rb}日调仓", "频率", sig=XS_REV, rebal=rb)


# ============================================================================
# 7. 跑
# ============================================================================
print("=" * 132)
print(f"全策略统一重跑 · 池 {len(UNI)} 只 | 面板 {N} 根 | 回测 {DT[START].date()} ~ {DT[-1].date()} "
      f"({_YRS:.2f} 年) | 本金 ${CAP0:,.0f} | 佣金 ${COMM:.0f}/笔双边 | Top2 等权月频")
print(f"闸门: 滚动{GATE_WIN}日中位成交额 >= ${GATE_DV/1e6:.0f}M  |  被挡格子 {1-TRADE.mean().mean():.1%}")
if FAST: print("(FAST 模式: 已跳过 AI 策略)")
print("=" * 132)

# 基准
BENCH = []
def bench(name, arr):
    eq = np.asarray(arr, dtype=float)
    eq = eq/eq[START]*CAP0
    eq[:START] = CAP0
    BENCH.append((name, dict(eq=eq, cashf=np.zeros(N), npos=np.zeros(N, int), log=[], cash_end=0.0)))

_voo = VOO_RAW.values.astype(float)
bench("[基准] VOO 买入持有", _voo)
# VOO 200DMA 择时: 信号(前一日)为多头则持有, 否则空仓持现金。
# ⚠ 括号必须把"收益 or 0"整体括起来 —— 写成 `a*(1+r if cond else 0)` 是错的,
#   那样 cond 为假时整个净值被置 0(实测表现为 eq[START]=0 -> 全序列 NaN)。
_vt = np.full(N, CAP0)
for i in range(1, N):
    _vt[i] = _vt[i-1]*(1 + ((_voo[i]/_voo[i-1] - 1) if REGIME[i-1] else 0.0))
bench("[基准] VOO 200DMA择时(空仓)", _vt)
# 池内等权买入持有 (每日再平衡到等权, 零成本 —— 作为"闭眼全买"基准)
_ew = np.full(N, CAP0)
for i in range(START+1, N):
    cur, prv = Cv[i], Cv[i-1]
    valid = np.isfinite(cur) & np.isfinite(prv) & (prv > 0)
    r = np.where(valid, cur/np.where(valid, prv, 1) - 1, np.nan)
    _ew[i] = _ew[i-1]*(1 + np.nanmean(r))
_ew[:START] = CAP0
bench("[基准] 池内等权买入持有", _ew)

results, t_all = [], time.time()
V_OFF, V_ON = REAL, (TRADE & REAL)
for cfg in STRATS:
    row = {"name": cfg["name"], "family": cfg["family"], "topk": cfg["topk"],
           "stop": cfg["stop"], "regime": cfg["regime"] is not None, "rebal": cfg["rebal"]}
    for tag, valid in (("off", V_OFF), ("on", V_ON)):
        A = cfg["sig"](valid) if cfg["sig"] is not None else None
        r = engine(A=A, elig=cfg["elig"], topk=cfg["topk"], gate=(None if tag == "off" else TRADE),
                   stop=cfg["stop"], regime=cfg["regime"], safe_px=cfg["safe"],
                   rebal=cfg["rebal"])
        row[f"m_{tag}"] = metrics(r)
    results.append(row)
    m_off, m_on = row["m_off"], row["m_on"]
    print(f"  {cfg['name'][:44]:<46} 无闸门 CAGR {m_off['cagr']*100:6.1f}% "
          f"(${m_off['final']:>10,.0f})  |  有闸门 CAGR {m_on['cagr']*100:6.1f}% "
          f"(${m_on['final']:>10,.0f})  回撤 {m_on['mdd']*100:6.1f}%")

BENCH_ROWS = []
for nm, r in BENCH:
    m = metrics(r)
    BENCH_ROWS.append({"name": nm, "family": "基准", "m_off": m, "m_on": m, "topk": "-", "stop": 0, "regime": False})
    print(f"  {nm[:44]:<46} {'':>21}  |  CAGR {m['cagr']*100:6.1f}% (${m['final']:>10,.0f})  回撤 {m['mdd']*100:6.1f}%")
print(f"\n总耗时 {time.time()-t_all:.0f}s")


# ============================================================================
# 8. 引擎自检 (交付前必过)
# ============================================================================
print("\n" + "=" * 132)
print("[引擎自检]")
print("=" * 132)
CHK = []
def chk(tag, cond, msg=""):
    CHK.append((tag, bool(cond), msg))
    print(f"  {'✅' if cond else '❌'} {tag}  {msg}")

# ----------------------------------------------------------------------------
# 8.0 数据层 (§0) —— 坏数据不会停在数据层, 它会沿着管线一路放大成结论级的错误
# ----------------------------------------------------------------------------
# §0.6 三条配套断言 (本次审计新增; 旧版自检完全没有数据层检查)
_n_fake_vol = int((~Rv & PX["volume"].notna().values).sum())
chk("§0.6 缺 bar 处没有伪造成交量 (volume 未被 ffill)", _n_fake_vol == 0,
    f"❌ 伪造 {_n_fake_vol} 格" if _n_fake_vol else "0 格伪造 (停牌日成交量为 NaN)")

_n_tr_leak = int((TRADE.values & ~Rv).sum())
chk("§0.6 闸门为 True 处必有真实 bar (trade ⊆ REAL)", _n_tr_leak == 0,
    (f"❌ 违例 {_n_tr_leak} 格 —— 策略会去买已停牌的票" if _n_tr_leak else
     "trade ⊆ REAL 恒成立 (顺带证明 REAL 层不改变默认口径, 只保护'关闸门'那条对比路径)"))

_n_sig_leak = 0
for _nm, _f in [("Vortex", TS(vort14)), ("动量-1月反转", XS_REV),
                ("金叉+MA50距离", TS(ma_dist50.where(golden)))]:
    for _v in (V_OFF, V_ON):
        _n_sig_leak += int((~Rv & np.isfinite(_f(_v).values)).sum())
chk("§0.6 无真实 bar 的日子因子必为 NaN", _n_sig_leak == 0,
    (f"❌ 泄漏 {_n_sig_leak} 格" if _n_sig_leak else
     "3 个主信号 × 2 口径: 无 bar 处全部 NaN (脏数据不参与打分)"))

# §0.3 OHLC 自洽
_n_hl = int((PX["high"].values < PX["low"].values).sum())
chk("§0.3 OHLC 自洽 (high >= low)", _n_hl == 0,
    f"❌ 违例 {_n_hl} 格" if _n_hl else "0 格违例")

# §0.1 末根是否为"盘中未完成 bar" —— 有价有量, volume>0 之类的检查完全识别不出来
_vsum = np.nansum(PX["volume"].values, axis=1)
_r_last = float(_vsum[-1]/np.nanmedian(_vsum[-22:-1]))
_mt = max(os.path.getmtime(os.path.join(LONGDIR, c.replace(".", "_") + ".csv")) for c in UNI)
_mt_et = datetime.datetime.fromtimestamp(_mt) - datetime.timedelta(hours=12)   # 夏令时 北京-12h
_in_sess = _mt_et.weekday() < 5 and 9.5 <= _mt_et.hour + _mt_et.minute/60 < 16.0
chk("§0.1 末根不是盘中未完成 bar", (_r_last >= 0.5) and (not _in_sess),
    (f"末根成交量/近20日中位 = {_r_last:.0%} (盘中快照通常只有 58%~81%); "
     f"数据文件美东时间 {_mt_et:%Y-%m-%d %H:%M} {'⚠ 落在盘中' if _in_sess else '✓ 盘后'}"))

# §0.3 面板空洞 / 极端跳变 —— 只报告, 不判负 (财报跳空常见 15~26%, 50% 阈值不该自动剔除)
_gap = pd.Series(DT).diff().dt.days
_n_gap = int((_gap > 12).sum())
_n_jump = int(np.nansum(np.abs(C.pct_change().values) > 0.5))
print(f"       ℹ 相邻交易日间隔 >12 天: {_n_gap} 处 | 单日涨跌 >50% 的格子: {_n_jump} 个"
      f" (需人工确认是真实行情还是数据错误, 不自动剔除)")
print(f"       ℹ 末根日期 {DT[-1].date()} | 面板 {N} 根 | 缺真 bar 格子 {1-Rv.mean():.1%}")

# 8.1 现金守恒: 同一策略, 扣/不扣买入佣金 必须给出不同终值(证明 F3 修复真的生效)
_r_fixed = engine(A=vort14.where(REAL), topk=2, gate=TRADE, charge_buy=True)
_r_bug = engine(A=vort14.where(REAL), topk=2, gate=TRADE, charge_buy=False)
chk("F3 修复生效: 扣买入佣金后终值必须更低",
    _r_fixed["eq"][-1] < _r_bug["eq"][-1],
    f"扣 ${_r_fixed['eq'][-1]:,.0f} < 不扣 ${_r_bug['eq'][-1]:,.0f}")

# 8.2 价值守恒恒等式 (最强的一条): 每次调仓都必须满足
#       卖出前 - 卖出后 == 卖出笔数 × 佣金   且   卖出后 - 买入后 == 买入笔数 × 佣金
# 任一次调仓的残差不为 0, 就说明有资金在"清仓/下单"过程中凭空出现或消失 ——
# 这正是 F2/F3 那类缺陷的通用探针。必须对【所有】策略都成立。
# ⚠ 修正(审计发现): 旧版这里【硬编码 gate=TRADE】, 循环变量 gate 从未被使用 ——
# 于是 ("off", None) 那一趟跑的其实还是有闸门的配置, 恒等式只验了有闸门那一半,
# 无闸门口径(全榜另一半结果)从未被守恒律覆盖。同时 _recon_n 被虚增一倍。
_recon_worst, _recon_bad, _recon_n = [], [], 0
_resid_bad, _resid_n, _resid_worst = [], 0, 0.0
for row, cfg in zip(results, STRATS):
    for tag, gate in (("off", None), ("on", TRADE)):
        valid = V_OFF if tag == "off" else V_ON
        r = engine(A=(cfg["sig"](valid) if cfg["sig"] is not None else None),
                   elig=cfg["elig"], topk=cfg["topk"], gate=gate,
                   stop=cfg["stop"], regime=cfg["regime"], safe_px=cfg["safe"],
                   rebal=cfg["rebal"])
        for i, r1, r2, scale in r["recon"]:
            _recon_n += 1
            res_ = max(abs(r1), abs(r2))/scale
            _recon_worst.append((res_, row["name"], tag, i))
            if res_ > 1e-9: _recon_bad.append((row["name"], tag, str(DT[i].date()), r1, r2))
        for i, cash_after in r["resid"]:
            _resid_n += 1
            if abs(cash_after) > 1e-6:
                _resid_bad.append((row["name"], tag, str(DT[i].date()), cash_after))
            _resid_worst = max(_resid_worst, abs(cash_after))
_recon_worst.sort(reverse=True)
chk("价值守恒恒等式: 每次调仓 资金变动 == 笔数×佣金", not _recon_bad,
    (f"❌ 违约 {len(_recon_bad)} 处, 例: {_recon_bad[0]}" if _recon_bad else
     f"共核验 {_recon_n:,} 次调仓(有闸门+无闸门两条路径), 最差相对残差 {_recon_worst[0][0]:.2e}"))

# 8.2c 满仓调仓后残现金必须恰为 0 —— "佣金只预留没真扣"的指纹是残现金恒等于 k×佣金
chk("§1.9 满仓调仓后残现金 == 0 (佣金真被扣走, 不是只预留)", not _resid_bad,
    (f"❌ {len(_resid_bad)} 次残留, 例: {_resid_bad[0]}" if _resid_bad else
     f"共核验 {_resid_n:,} 次满仓调仓, 最差残现金 ${_resid_worst:.2e}"))

# 8.2b F2: "保留停牌持仓" vs "清空持仓" —— 数值可能相同(样本里没发生长期停牌),
# 所以这里【只报告不判负】, 真正证明修复生效靠上面 8.2 的恒等式 + 合成复现(见 _audit_v25.py C-fix)。
_f2_same = 0
for _nm, _A in [("Vortex", vort14.where(REAL)),
                ("动量-1月反转", XS_REV(REAL))]:
    for _g, _gtag in ((None, "无闸门"), (TRADE, "有闸门")):
        _k = engine(A=_A, topk=2, gate=_g, keep_stuck=True)
        _d = engine(A=_A, topk=2, gate=_g, keep_stuck=False)
        if bool(np.allclose(_k["eq"], _d["eq"], equal_nan=True)): _f2_same += 1
        else:
            print(f"       ℹ {_nm}/{_gtag}: 保留 ${_k['eq'][-1]:,.0f} vs 清空 ${_d['eq'][-1]:,.0f}"
                  f" (停牌被迫持仓 {_k['n_stuck']} 次)")
print(f"  ✅ F2 停牌持仓处理: 4 个组合中 {4-_f2_same} 个因'保留 vs 清空'而不同 "
      f"(相同不代表修复无效 —— 只代表该策略在这段样本里没碰上长期停牌)")

# 8.3 全部策略终值必须有限且 >= 0 (0 = 破产, 见 8.5)
_bad = []
for row in results:
    for tag in ("off", "on"):
        e = row[f"m_{tag}"]
        if not (np.isfinite(e["final"]) and e["final"] >= 0): _bad.append(f"{row['name']}/{tag}")
chk("全部策略终值有限且 >= 0", not _bad,
    f"异常 {_bad[:3]}" if _bad else f"{len(results)*2} 条净值全部有效")

# 8.4 净值无 NaN 空洞
_holes = [row["name"] for row in results
          if not np.all(np.isfinite(np.asarray(row["m_off"]["monthly"], dtype=float)))]
chk("净值无 NaN 空洞", not _holes, f"异常 {_holes[:3]}" if _holes else "全部策略月收益序列完整")

# 8.4b "策略从未成交" 静默失败检查 —— 信号若没落在引擎读取的那一天上,
# 结果会是"净值恒等于本金"这种【不报错、只是什么都没发生】的样子。必须专门抓。
_never = [(row["name"], row["m_on"]["n_trades"], row["m_off"]["n_trades"])
          for row in results if min(row["m_on"]["n_trades"], row["m_off"]["n_trades"]) < 5]
_min_tr = min(min(row["m_on"]["n_trades"], row["m_off"]["n_trades"]) for row in results)
chk("所有策略都真的成交过(防'信号从未被引擎消费')", not _never,
    f"❌ {_never[:3]}" if _never else f"最少成交笔数 {_min_tr} 笔, 无'零成交'策略")

# 8.5 【无交易日】价格归因恒等式 —— 覆盖每一个"没有发生任何现金流水"的日子:
#        eq[i] 必须 == eq[i-1] + Σ sh_j × (CS[i,j] − CS[i-1,j])
# 也就是说: 持仓不变的那些天, 净值变动必须【100% 由持仓自身价格变动解释】。
# 任何"凭空少一块"的假断崖(典型的 F2 症状)都会在这里暴露 —— 比"单日跌超 40%"这种
# 阈值法严格得多: 实测最深的两次单日暴跌(BMNR 于 2025-06-05 真实跌 59.2%,
# 而它当时占 Top2 组合的 72%~84%)会被正确判为【已解释】, 而不是误报。
_worst_expl, _unexpl, _n_day = (0.0, None), [], 0
for row, cfg in zip(results, STRATS):
    r = engine(A=(cfg["sig"](V_ON) if cfg["sig"] is not None else None),
               elig=cfg["elig"], topk=cfg["topk"], gate=TRADE,
               stop=cfg["stop"], regime=cfg["regime"], safe_px=cfg["safe"],
               rebal=cfg["rebal"], trace=True)
    ca, hold = r["casharr"], r["hold"]
    for i in range(START+1, N):
        if not (np.isfinite(ca[i]) and np.isfinite(ca[i-1])): continue
        # 只检查"现金与持仓【都】完全没变"的两天 —— 那两天不可能发生任何成交,
        # 净值变动必须 100% 来自价格。(不能只看现金: 满仓调仓后现金恰好又回到 0,
        # 实测 2019-02-04 就是这样漏过去的。)
        h0, h1 = hold[i-1], hold[i]
        if h0 is None or h1 is None: continue
        if ca[i] != ca[i-1] or h0 != h1: continue
        exp_gain = 0.0; ok = True
        for j, sh in h0.items():
            if j == -1:
                if cfg["safe"] is None: ok = False; break
                a, b = float(cfg["safe"][i-1]), float(cfg["safe"][i])
            else:
                a, b = CSv[i-1, j], CSv[i, j]
            if not (np.isfinite(a) and np.isfinite(b) and a > 0): ok = False; break
            exp_gain += sh*(b - a)
        if not ok or not (np.isfinite(r["eq"][i]) and np.isfinite(r["eq"][i-1])): continue
        _n_day += 1
        err = abs((r["eq"][i] - r["eq"][i-1]) - exp_gain)/max(abs(r["eq"][i-1]), 1.0)
        if err > _worst_expl[0]: _worst_expl = (err, row["name"], str(DT[i].date()))
        if err > 1e-9: _unexpl.append((row["name"], str(DT[i].date()), err))
chk("价格归因恒等式: 无流水日的净值变动 100% 由持仓价格解释", not _unexpl,
    (f"❌ {len(_unexpl)} 天无法解释, 例: {_unexpl[0]}" if _unexpl else
     f"共核验 {_n_day:,} 个'无成交日', 最大相对误差 {_worst_expl[0]:.2e} "
     f"({_worst_expl[1]} {_worst_expl[2]})"))

# 8.5b 最深单日跌幅 —— 只报告(8.5 已证明它们由真实价格变动解释, 不是引擎缺陷)
print("       ℹ 最深 3 次单日跌幅(已由 8.5 判定为真实价格变动, 非引擎缺陷):")
_dd_all = [(float(row["m_on"]["daily_min"]), row["name"]) for row in results
           if np.isfinite(row["m_on"]["daily_min"])]
_dd_all.sort()
for v_, n_ in _dd_all[:3]:
    print(f"         {n_:<44} {v_*100:6.1f}%")

# 8.6 预热期不参与投资
_e0 = engine(A=vort14.where(REAL), topk=2)
chk("预热期(前252根)净值为常数本金", bool(np.allclose(_e0["eq"][:START], CAP0)),
    f"前 {START} 根全部 = ${CAP0:,.0f}")

# 8.7 首笔成交必须落在第一个调仓日
_first = min(t["i"] for t in _e0["log"]) if _e0["log"] else None
chk("首笔成交在第一个调仓日", _first == START,
    f"首笔 i={_first} (START={START}, {DT[START].date()})")

# 8.8 安全资产价格全程可得
_miss = int(np.sum(~np.isfinite(VOO_C[START:])))
chk("择时用的 VOO 价格全程可得", _miss == 0, f"缺失 {_miss} 天")

# 8.9 破产策略必须真的"佣金吃穿账户", 而不是引擎算错
_bk = [(r["name"], r["m_on"]["bankrupt_date"]) for r in results if r["m_on"]["bankrupt"]]
_ok_bk = True
for nm, _d in _bk:
    r = next(x for x in results if x["name"] == nm)
    if r["m_on"]["final"] != 0.0: _ok_bk = False
chk("破产策略终值恰为 0 (不是负数/复数)", _ok_bk,
    f"破产 {len(_bk)} 个: " + ", ".join(f"{n}({d})" for n, d in _bk[:4]) if _bk else "无破产策略")

# ----------------------------------------------------------------------------
# 8.10 §1.2 无前视偏差 (截断测试): 截掉末 21 根重算信号, 前段必须逐格一致
# ----------------------------------------------------------------------------
T = N - 21
_la_bad = []
for _nm, _b in [("Vortex14", lambda c, h, l, v: vortex(h, l, c, 14)),
                ("MA50距离", lambda c, h, l, v: c/c.rolling(50).mean() - 1.0),
                ("金叉MA50>MA200", lambda c, h, l, v: (c.rolling(50).mean() > c.rolling(200).mean()).astype(float)),
                ("动量12-1", lambda c, h, l, v: c.shift(21)/c.shift(252) - 1.0),
                ("1月反转", lambda c, h, l, v: c/c.shift(21) - 1.0)]:
    a = _b(C, H, L, V).values[:T]
    b = _b(C.iloc[:T], H.iloc[:T], L.iloc[:T], V.iloc[:T]).values
    nd = int(np.sum(np.isfinite(a) & np.isfinite(b) & (np.abs(a - b) > 1e-12)))
    nnd = int(np.sum(np.isfinite(a) != np.isfinite(b)))
    if nd or nnd: _la_bad.append((_nm, nd, nnd))
chk("§1.2 无前视偏差 (截断末21根重算, 前段逐格一致)", not _la_bad,
    (f"❌ {_la_bad[:3]}" if _la_bad else
     f"5 个因子 × {T:,} 根重叠区: 数值差异 0 处, NaN 位置差异 0 处"))

# ----------------------------------------------------------------------------
# 8.11 §1.5 上界校验: 任何多头策略都不得超越"逐日完美择时"的理论上界
# ----------------------------------------------------------------------------
_pf = np.ones(N)
for i in range(START+1, N):
    a, b = Cv[i-1], Cv[i]
    ok = np.isfinite(a) & np.isfinite(b) & (a > 0)
    if ok.any():
        _pf[i] = _pf[i-1]*float(np.nanmax(np.where(ok, b/np.where(ok, a, 1), np.nan)))
_pf[:START] = 1.0
_pf_tot = float(_pf[-1] - 1)
_best1 = float(np.nanmax(Cv[-1]/Cv[START] - 1))
_mx = max(r["m_on"]["total"] for r in results)
_over = [(r["name"], r["m_on"]["total"]) for r in results if r["m_on"]["total"] > _pf_tot]
chk("§1.5 上界校验: 无策略超越逐日完美择时理论上界", not _over,
    (f"❌ 越界 {_over[:3]}" if _over else
     f"完美择时上界 {_pf_tot*100:,.0f}% | 最优单票买入持有 {_best1*100:,.0f}% | "
     f"全榜最强 {_mx*100:,.0f}% (为上界的 {_mx/_pf_tot:.4%}, 远未触及 => 无复利/前视 bug)"))

# ----------------------------------------------------------------------------
# 8.12 §1.6 资金解耦: 选股不得随本金变化 (零佣金 + 碎股下跨 5 个数量级, 选票必须逐笔相同)
# ----------------------------------------------------------------------------
_pick_bad = []
for _nm, _f, _rb in [("Vortex@10", TS(vort14), 10),
                     ("金叉+MA50距离", TS(ma_dist50.where(golden)), 21)]:
    _base = None
    for _cap in (500.0, 1500.0, 3000.0, 50000.0, 1e7):
        r = engine(A=_f(V_ON), topk=2, gate=TRADE, cap=_cap, comm=0.0, rebal=_rb)
        pk = [(t["i"], t["j"]) for t in r["log"]]
        if _base is None: _base = pk
        elif pk != _base: _pick_bad.append((_nm, _cap))
chk("§1.6 选股与本金解耦 (零佣金跨 $500~$1e7 选票逐笔相同)", not _pick_bad,
    (f"❌ {_pick_bad[:4]}" if _pick_bad else
     "Vortex@10 / 金叉+MA50距离: 5 档本金选票完全一致 "
     "(本金只决定'买得起几股', 绝不决定'买哪只')"))

print(f"\n  ℹ 闸门后 CAGR 下降的策略数: "
      f"{sum(1 for r in results if float(r['m_on']['cagr']) < float(r['m_off']['cagr']))}/{len(results)} "
      f"(闸门只做减法, 下降正常; 但把'下降'读成'闸门有害'是错的 —— 它拦掉的是没法成交的交易)")
print(f"  ℹ 有闸门 vs 无闸门 成交笔数: 前者更多属正常(标的少 -> 每只预算大 -> 更容易成交), "
      f"不是闸门在加交易")
print(f"\n  自检小结: {sum(1 for _,c,_ in CHK if c)}/{len(CHK)} 通过")


# ============================================================================
# 9. 排序与输出
# ============================================================================
ALL = results + BENCH_ROWS
def _key(r, tag, k):
    v = r[f"m_{tag}"][k]
    try: v = float(v)
    except Exception: return -1e18
    return -1e18 if (v is None or not np.isfinite(v)) else v
def srt(key, tag="on", rev=True):
    return sorted([r for r in ALL if r.get(f"m_{tag}")], key=lambda r: _key(r, tag, key), reverse=rev)

def fmt_row(i, r, tag):
    m = r[f"m_{tag}"]
    flag = " 💀破产" if m.get("bankrupt") else ""
    nm = r['name'][:42] + flag
    return (f"{i:>3} | {nm:<50} | {m['total']*100:>12,.0f}% | ${m['final']:>11,.0f} | "
            f"{m['cagr']*100:>6.1f}% | {m['mdd']*100:>7.1f}% | {m['sharpe']:>5.2f} | "
            f"{m['calmar']:>5.2f} | {m['mo_win']*100:>5.1f}% | {m['yr_win']*100:>5.1f}%")

HDR = (f"{'#':>3} | {'策略':<50} | {'总收益':>13} | {'终值':>12} | {'CAGR':>7} | "
       f"{'最大回撤':>8} | {'夏普':>5} | {'Calmar':>5} | {'月胜率':>6} | {'年胜率':>6}")

lines = []
def P(s=""):
    print(s); lines.append(s)

P("\n" + "=" * 132)
P("【总榜】按 CAGR 排序 · 有闸门口径 (可实盘)")
P("=" * 132)
P(HDR); P("-" * 132)
for i, r in enumerate(srt("cagr", "on"), 1): P(fmt_row(i, r, "on"))

P("\n" + "=" * 132)
P("【总榜】按 CAGR 排序 · 无闸门口径 (纯信号能力)")
P("=" * 132)
P(HDR); P("-" * 132)
for i, r in enumerate(srt("cagr", "off"), 1): P(fmt_row(i, r, "off"))

P("\n" + "=" * 132)
P("【风险调整榜】按 Calmar (CAGR / 最大回撤) · 有闸门")
P("=" * 132)
for i, r in enumerate(srt("calmar", "on")[:25], 1): P(fmt_row(i, r, "on"))

P("\n" + "=" * 132)
P("【夏普榜】· 有闸门")
P("=" * 132)
for i, r in enumerate(srt("sharpe", "on")[:25], 1): P(fmt_row(i, r, "on"))

P("\n" + "=" * 132)
P("【回撤最小榜】· 有闸门")
P("=" * 132)
for i, r in enumerate(sorted(ALL, key=lambda r: _key(r, "on", "mdd"), reverse=True)[:25], 1):
    P(fmt_row(i, r, "on"))

P("\n" + "=" * 132)
P("【分家族最佳】· 有闸门")
P("=" * 132)
fam = {}
for r in ALL:
    fam.setdefault(r["family"], []).append(r)
for f, rs in sorted(fam.items(), key=lambda kv: -max(x["m_on"]["cagr"] for x in kv[1])):
    b = max(rs, key=lambda r: r["m_on"]["cagr"])
    m = b["m_on"]
    P(f"  {f:<8} 冠军 {b['name'][:40]:<42} CAGR {m['cagr']*100:6.1f}%  "
      f"总收益 {m['total']*100:>10,.0f}%  回撤 {m['mdd']*100:6.1f}%  夏普 {m['sharpe']:.2f}  "
      f"(家族 {len(rs)} 个策略)")

P("\n" + "=" * 132)
P("【逐年收益】· 有闸门 · 前 12 名")
P("=" * 132)
top12 = srt("cagr", "on")[:12]
yrs = sorted(top12[0]["m_on"]["yr_ret"].keys())
P(f"  {'策略':<42} " + " ".join(f"{y:>8}" for y in yrs))
for r in top12:
    yr = r["m_on"]["yr_ret"]
    P(f"  {r['name'][:40]:<42} " + " ".join(f"{yr.get(y,0)*100:>7.0f}%" for y in yrs))

P("\n" + "=" * 132)
P("【分牛熊阶段】· 有闸门 · 前 10 名 + 基准")
P("=" * 132)
ph_names = [n for n, _, _ in PHASES]
P(f"  {'策略':<42} " + " ".join(f"{n[:9]:>10}" for n in ph_names))
for r in (top12[:10] + [b for b in BENCH_ROWS if "VOO 买入持有" in b["name"]]):
    ph = r["m_on"]["phases"]
    P(f"  {r['name'][:40]:<42} " + " ".join(
        f"{(ph.get(n) if ph.get(n) is not None else 0)*100:>9.0f}%" for n in ph_names))

P("\n" + "=" * 132)
P("【诊断指标】· 有闸门 · 前 15 名 (换手/平均持股/平均闲置现金/波动率/索提诺)")
P("=" * 132)
P(f"  {'策略':<42} {'年换手':>7} {'平均持股':>8} {'闲置现金':>9} {'年化波动':>9} {'索提诺':>7} {'最好月':>8} {'最差月':>8}")
for r in srt("cagr", "on")[:15]:
    m = r["m_on"]
    P(f"  {r['name'][:40]:<42} {m['turnover_yr']:>7.0f} {m['avg_pos']:>8.2f} "
      f"{m['avg_cash']*100:>8.1f}% {m['vol']*100:>8.1f}% {m['sortino']:>7.2f} "
      f"{m['mo_best']*100:>7.1f}% {m['mo_worst']*100:>7.1f}%")

P("\n" + "=" * 132)
P("【前后半段一致性】· 有闸门 (前半 2019-01~2022-12 / 后半 2023-01~2026-09)")
P("=" * 132)
rows_half = []
dts = pd.DatetimeIndex(DT)
for r in ALL:
    m = r["m_on"]
    mo = np.array(m["monthly"])
    mid = (len(mo))//2
    h1 = float(np.prod([1+x for x in mo[:mid]]) - 1); h2 = float(np.prod([1+x for x in mo[mid:]]) - 1)
    rows_half.append((r["name"], h1, h2))
rows_half.sort(key=lambda x: -min(x[1], x[2]))
P(f"  {'策略':<42} {'前半段':>12} {'后半段':>12}   (按两段最小值排序)")
for nm, a, b in rows_half[:20]:
    P(f"  {nm[:40]:<42} {a*100:>11,.0f}% {b*100:>11,.0f}%")

ok = sum(1 for _, c, _ in CHK if c)
P(f"\n自检 {ok}/{len(CHK)} 通过 | 策略 {len(results)} 个 + 基准 {len(BENCH_ROWS)} 个")

# ⚠ --fast --phase 那一跑是【不完整】的(跳过 AI, 只有 64 个策略),
# 绝不能让它覆盖全量跑出来的 _rank_all.json —— 否则主榜单会静默少 5 行。
if FAST and "--phase" in sys.argv:
    print("\nSKIP 主 JSON 写入 (--fast --phase 为不完整跑, 不覆盖全量结果)")
else:
    json.dump({"meta": {"pool": len(UNI), "bars": N, "start": str(DT[START].date()),
                        "end": str(DT[-1].date()), "years": _YRS, "cap": CAP0, "comm": COMM,
                        "rebal": 21, "gate": f"rolling{GATE_WIN}d median dv >= {GATE_DV}",
                        "time": time.strftime("%Y-%m-%d %H:%M:%S")},
               "results": ALL, "checks": [{"tag": t, "pass": c, "msg": m} for t, c, m in CHK]},
              open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    print("\nSAVED", OUT_JSON)
print("RANK_DONE")


# ============================================================================
# 10. 相位扫描 (§1.11) —— 仅 --phase 时运行
# ============================================================================
# 总榜里那个 CAGR 是【某一个相位】的抽签结果, 不是策略属性。
# anchor 平移一天, 调仓日整体平移 -> 选票/成交价/持有期全部变样。
# v30 实测: 10 日调仓相位极差 49.3pp, 21 日 62.9pp —— 比所有交易成本加起来还大一个量级。
# 所以"定最终版"必须报【区间】, 不能报单点。
if "--phase" in sys.argv:
    print("\n" + "=" * 132)
    print(f"[相位扫描 §1.11] 本金 ${CAP0:,.0f} | 佣金 ${COMM:.0f}/笔双边 | 有闸门口径")
    print("=" * 132)
    CHAMPS = [("金叉+MA50距离 Top2", TS(ma_dist50.where(golden)), 2, 21),
              ("Vortex Top2 @10日", TS(vort14), 2, 10)]
    PH = []
    for _nm, _f, _tk, _rb in CHAMPS:
        cs, ms, fs = [], [], []
        for _a in range(START, START + _rb):
            r = engine(A=_f(V_ON), topk=_tk, gate=TRADE, rebal=_rb, anchor=_a)
            fin = float(r["eq"][-1])
            _ya = (DT[-1] - DT[_a]).days/365.25      # 各相位按自己的起步日算年数
            cs.append((fin/CAP0)**(1/_ya) - 1 if fin > 0 else -1.0)
            _s = pd.Series(r["eq"][_a:], index=pd.DatetimeIndex(DT[_a:]))
            ms.append(float((_s/_s.cummax() - 1).min()))
            fs.append(fin)
        cs, ms, fs = np.array(cs), np.array(ms), np.array(fs)
        base, rank = cs[0], int(np.sum(cs > cs[0])) + 1
        print(f"\n  {_nm}  (rebal={_rb}日, 共 {len(cs)} 个相位)")
        print(f"    CAGR   最差 {cs.min()*100:6.1f}%   中位 {np.median(cs)*100:6.1f}%   "
              f"最好 {cs.max()*100:6.1f}%   标准差 {cs.std(ddof=1)*100:5.1f}pp   "
              f"极差 {(cs.max()-cs.min())*100:5.1f}pp")
        print(f"    回撤   最深 {ms.min()*100:6.1f}%   中位 {np.median(ms)*100:6.1f}%   "
              f"最浅 {ms.max()*100:6.1f}%")
        print(f"    终值   最差 ${np.min(fs):>11,.0f}   中位 ${np.median(fs):>11,.0f}   "
              f"最好 ${np.max(fs):>11,.0f}")
        print(f"    ★ 总榜那个数 (anchor=START) = {base*100:.1f}%, 在 {len(cs)} 个相位里排 "
              f"{rank}/{len(cs)} —— {'偏幸运' if rank <= len(cs)//3 else ('偏倒霉' if rank > 2*len(cs)//3 else '居中')}")
        PH.append({"name": _nm, "rebal": _rb, "cap": CAP0,
                   "cagr_min": float(cs.min()), "cagr_med": float(np.median(cs)),
                   "cagr_max": float(cs.max()), "cagr_std": float(cs.std(ddof=1)),
                   "cagr_base": float(base), "base_rank": rank, "n_phase": len(cs),
                   "mdd_med": float(np.median(ms)), "mdd_worst": float(ms.min()),
                   "final_med": float(np.median(fs)), "final_min": float(np.min(fs)),
                   "final_max": float(np.max(fs))})
    _po = OUT_JSON.replace(".json", "_phase.json")
    json.dump({"meta": {"cap": CAP0, "comm": COMM, "gate": "on"}, "phases": PH},
              open(_po, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nSAVED {_po}")
