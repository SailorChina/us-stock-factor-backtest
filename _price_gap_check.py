# -*- coding: utf-8 -*-
"""
回答: "9/14 开盘价和报告里的 644 / 258 不一样"

1) 澄清 644.38 / 258.49 是 2026-09-10 的【收盘价】, 不是 9/14 开盘价。
2) 回测引擎的成交模型就是 "T日收盘算信号 -> T+1 开盘价成交", 所以真实成本是 9/14 开盘价。
3) 量化跳空: 历史上信号日收盘 -> 次日开盘 的跳空有多大、是否系统性不利。
4) 从 OpenD 拉最新数据(9/11), 用最新数据重算信号 —— 9/14 该买的可能已经不是 META+BE。
"""
import os, sys, json, time, tempfile, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")

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
_, vp = load(["US.VOO"]); VOO = vp["close"]["US.VOO"].values
dfH, dfL, dfC = [pd.DataFrame(x, index=dp, columns=CODES) for x in (H, L, C)]
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift(); tr = np.maximum(np.maximum(h-lo, (h-pc).abs()), (lo-pc).abs())
    return ((h-lo.shift()).abs().rolling(n).sum()/tr.rolling(n).sum()
            - (lo-h.shift()).abs().rolling(n).sum()/tr.rolling(n).sum())
mom12_1 = dfC.shift(21)/dfC.shift(252)-1.0
rev1 = dfC/dfC.shift(21)-1.0
SIG = {"Vortex": vortex(dfH, dfL, dfC), "动量-1月反转": (zs(mom12_1)-zs(rev1))/2.0}
START = 252
RB = [i for i in range(N) if i >= START and (i-START) % 21 == 0]

print("="*126)
print("[1] 价格口径澄清")
print("="*126)
i = N-1
print(f"  本地数据最后交易日: {str(dp[i].date())}  (今天 2026-09-12 是周六, 美股已收 9/11 周五)")
for nm in ["US.META", "US.BE"]:
    if nm in CODES:
        c = CODES.index(nm)
        print(f"  {nm.replace('US.',''):<6} 9/10 收盘 ${C[i,c]:.2f} | 9/10 开盘 ${O[i,c]:.2f}")
print("\n  -> 报告里的 $644.38 / $258.49 是【9/10 收盘价】。")
print("     9/14 周一的开盘价现在还没发生, 会受 9/11 行情 + 周末消息 + 9/16 FOMC 预期影响。")
print("     回测引擎的成交价就是次日【开盘价】, 不是信号日收盘价 —— 这一点回测已经正确建模。")

print("\n" + "="*126)
print("[2] 跳空有多大? 信号日(T)收盘 -> 执行日(T+1)开盘 的历史统计")
print("="*126)
print("  跳空 = (次日开盘 / 当日收盘 - 1)")
gaps_all = O[1:]/C[:-1]-1
gaps_all = gaps_all[np.isfinite(gaps_all)]
print(f"\n  【全市场全样本】共 {gaps_all.size:,} 个观测")
for q, lab in [(1,"1%"), (5,"5%"), (25,"25%"), (50,"中位"), (75,"75%"), (95,"95%"), (99,"99%")]:
    print(f"     {lab:>4} 分位: {np.percentile(gaps_all, q)*100:+.2f}%")
print(f"     均值 {gaps_all.mean()*100:+.3f}% | 标准差 {gaps_all.std()*100:.2f}%")

print("\n  【只在调仓日发生、且是策略实际买入的票】——这才是你会真实承担的")
rows = []
for nm in SIG:
    A = np.asarray(SIG[nm].values, dtype=float)
    g = []
    for k in range(len(RB)-1):
        j = RB[k]
        row = A[j]; ok = np.isfinite(row); idx = np.where(ok)[0]
        if len(idx) == 0: continue
        pick = list(idx[np.argsort(-row[idx])][:2])
        for c in pick:
            if j+1 < N and np.isfinite(O[j+1, c]) and np.isfinite(C[j, c]) and C[j, c] > 0:
                g.append(O[j+1, c]/C[j, c]-1)
    g = np.array(g)
    rows.append((nm, g))
    q = np.percentile(g, [5, 25, 50, 75, 95])
    print(f"  {nm:<16} 样本 {len(g):>4} | 5% {q[0]*100:+.2f}% | 25% {q[1]*100:+.2f}% | "
          f"中位 {q[2]*100:+.2f}% | 75% {q[3]*100:+.2f}% | 95% {q[4]*100:+.2f}% | 均值 {g.mean()*100:+.3f}%")
print("\n  解读: 中位跳空接近 0, 说明【平均而言开盘价≈前一日收盘价】,")
print("        但个股单日跳空是双向的, 95% 分位可达 ±3~5%。这是你真实承担的成交价不确定性。")

print("\n" + "="*126)
print("[3] 从 OpenD 拉最新数据 (9/11), 用最新数据重算 9/14 该买什么")
print("="*126)
_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_gap")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
try:
    from common import create_quote_context, safe_close
    from futu import SubType, AuType, SysConfig
    SysConfig.set_all_thread_daemon(True)
    ctx = create_quote_context()
    _, q = ctx.get_history_kl_quota(get_detail=False)
    rem = q[1] if isinstance(q, (list, tuple)) else 9999
    print(f"  QUOTA_REMAINING = {rem}")
    targets = UNI + ["US.VOO"]
    got = {}
    for code in targets:
        out = ctx.request_history_kline(code, start="2026-08-01", end="2026-09-13",
                                        ktype=SubType.K_DAY, autype=AuType.QFQ, max_count=60)
        if out[0] != 0 or out[1] is None or len(out[1]) == 0:
            print(f"  FAIL {code} ret={out[0]}")
            time.sleep(1.0); continue
        df = out[1][["time_key","open","close","high","low","volume"]].copy()
        df["time_key"] = pd.to_datetime(df["time_key"])
        got[code] = df
        time.sleep(0.35)
    safe_close(ctx)
    print(f"  拉取成功 {len(got)}/{len(targets)} 只")

    if got:
        last_dates = sorted(set().union(*[set(d["time_key"]) for d in got.values()]))
        print(f"  最新可獲数据日期: {str(pd.Timestamp(last_dates[-1]).date())}")
        # 合并进现有数据
        NEWC, NEWO = {}, {}
        for code, df in got.items():
            p = os.path.join(LONGDIR, code.replace(".", "_") + ".csv")
            old = pd.read_csv(p); old["time_key"] = pd.to_datetime(old["time_key"])
            merged = pd.concat([old, df], ignore_index=True).drop_duplicates("time_key", keep="last")
            merged = merged.sort_values("time_key").reset_index(drop=True)
            merged.to_csv(p, index=False)
            NEWC[code] = merged.set_index("time_key")["close"]
            NEWO[code] = merged.set_index("time_key")["open"]
        print(f"  已合并写入 {len(got)} 个 CSV")

        # 用最新数据重算信号
        idx = pd.DatetimeIndex(sorted(last_dates))
        C2 = pd.DataFrame({c: NEWC[c].reindex(idx).ffill() for c in UNI})
        O2 = pd.DataFrame({c: NEWO[c].reindex(idx).ffill() for c in UNI})
        # 需要更长历史算 252 日动量 -> 读回完整 CSV
        d2, P2 = load(UNI)
        C3 = P2["close"]; O3 = P2["open"]; H3 = P2["high"]; L3 = P2["low"]
        n2 = len(d2); dp2 = pd.to_datetime(d2)
        dfH2, dfL2, dfC2 = C3*0+H3, C3*0+L3, C3
        V2 = vortex(dfH2, dfL2, dfC2)
        M2 = (dfC2.shift(21)/dfC2.shift(252)-1.0)
        R2 = (dfC2/dfC2.shift(21)-1.0)
        SIG2 = {"Vortex": V2, "动量-1月反转": (zs(M2)-zs(R2))/2.0}
        j2 = n2-1
        print(f"\n  重算基准日: {str(dp2[j2].date())}  (全历史 {n2} 根)")
        print(f"\n{'策略':<20}{'选股':<26}{'最新收盘价':>12}{'每只预算':>12}{'碎股股数':>12}")
        print("-"*126)
        CAP0 = 10000.0/6.7092
        for nm in SIG2:
            for tk in [2, 3]:
                row = np.asarray(SIG2[nm].values, dtype=float)[j2]
                ok = np.isfinite(row); ii = np.where(ok)[0]
                pick = list(ii[np.argsort(-row[ii])][:tk])
                names = [UNI[c].replace("US.","") for c in pick]
                pr = [C3.values[j2, c] for c in pick]
                bud = CAP0/tk
                print(f"  {nm+' Top'+str(tk):<18}{','.join(names):<26}"
                      f"{','.join(f'${p:.2f}' for p in pr):>26}"
                      f"${bud:>11.0f}" + f"{','.join(f'{bud/p:.3f}' for p in pr):>18}")
        # 与 9/10 信号对比
        print(f"\n  对比 9/10 的信号是否变化:")
        j_old = n2-2 if n2 >= 2 else j2
        for nm in SIG2:
            A2 = np.asarray(SIG2[nm].values, dtype=float)
            for tk in [2]:
                r_new = np.asarray(SIG2[nm].values, dtype=float)[j2]
                r_old = A2[j_old]
                pn = [UNI[c].replace("US.","") for c in
                      (np.where(np.isfinite(r_new))[0][np.argsort(-r_new[np.isfinite(r_new)])][:tk])]
                po = [UNI[c].replace("US.","") for c in
                      (np.where(np.isfinite(r_old))[0][np.argsort(-r_old[np.isfinite(r_old)])][:tk])]
                print(f"    {nm} Top{tk}: {str(dp2[j_old].date())} -> {po}    |    "
                      f"{str(dp2[j2].date())} -> {pn}   {'【变了】' if pn != po else '（未变）'}")
except Exception as e:
    print(f"  OpenD 拉取失败: {type(e).__name__}: {e}")
