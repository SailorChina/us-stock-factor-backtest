# -*- coding: utf-8 -*-
"""
深度审计 _update_signal.py 的【数据层】与【信号层】
不拉行情, 纯本地体检; 只做 1 只标的的接口对照(验证复权基准漂移)

检查项:
  A 面板完整性: 日期单调/重复/缺失/各票长度差异
  B 数值健康: NaN/0价/负价/极端跳变(疑似拆股未复权)
  C 停牌与僵尸票: 长期不更新的标的
  D 调仓序列稳定性: RB 是否随样本长度变化而漂移(前视/可复现性)
  E 信号可复现性: 去掉最后 k 根, 前面的信号是否完全不变(检测未来函数)
  F 复权基准漂移: 同一历史日期的收盘价, 在不同时点拉取是否一致
"""
import os, sys, json, warnings, hashlib
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
START = 252; REBAL = 21

mi = json.load(open(os.path.join(BASE, "market_info.json")))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json")))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
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

print("=" * 120); print("A 面板完整性"); print("=" * 120)
raw = {}
for c in UNI + ["US.VOO"]:
    f = os.path.join(LONGDIR, c.replace(".", "_") + ".csv")
    d = pd.read_csv(f)
    raw[c] = d
lens = {c: len(d) for c, d in raw.items()}
print(f"  标的数 {len(raw)}   文件行数: min {min(lens.values())} max {max(lens.values())}")
bad = []
for c, d in raw.items():
    t = pd.to_datetime(d["time_key"])
    dup = t.duplicated().sum()
    mono = t.is_monotonic_increasing
    if dup or not mono:
        bad.append((c, dup, mono))
if bad:
    print("  ❌ 存在重复/乱序日期:")
    for c, dup, mono in bad: print(f"     {c}: 重复 {dup}, 有序 {mono}")
else:
    print("  ✅ 所有文件日期无重复且单调递增")

dates, PX = load(UNI)
N, S = PX["close"].shape; dp = pd.to_datetime(dates)
print(f"  面板: {N} 行 x {S} 列   首 {str(dp[0].date())}  末 {str(dp[-1].date())}")
gaps = pd.Series(dp).diff().dt.days.dropna()
print(f"  相邻交易日间隔: 中位 {gaps.median():.0f} 天, 最大 {gaps.max():.0f} 天 "
      f"(>5 天共 {(gaps>5).sum()} 次, 正常为周末/假日)")

print("\n" + "=" * 120); print("B 数值健康"); print("=" * 120)
C = PX["close"].values; O = PX["open"].values; H = PX["high"].values; L = PX["low"].values
nan_rate = np.isnan(C).mean()
print(f"  收盘价 NaN 占比 {nan_rate*100:.2f}%  (预热期与停牌造成)")
print(f"  非正价格格数: {(C<=0).sum()}   非有限值: {(~np.isfinite(C)).sum()}")
prev = C[:-1]                      # 上一日收盘 (N-1, S)
prev = np.where(np.abs(prev) < 1e-9, np.nan, prev)
ret = (C[1:] / prev - 1.0)         # 单日收益率 (N-1, S)
ret = ret[1:]                      # 去掉第一根(预热)
rf = ret[np.isfinite(ret)]
ext = np.abs(ret) > 0.5
print(f"  单日涨跌 >50% 的观测: {int(np.nansum(ext))} 个 "
      f"(占有效样本 {np.nansum(ext)/max(rf.size,1)*100:.4f}%)")
if np.nansum(ext) > 0:
    ii, jj = np.where(np.nan_to_num(ext, nan=False))
    cnt = {}
    for i, j in zip(ii, jj):
        cnt[UNI[j]] = cnt.get(UNI[j], 0) + 1
    top = sorted(cnt.items(), key=lambda x: -x[1])[:8]
    print("  发生次数最多的标的: " + ", ".join(f"{k.replace('US.','')}:{v}" for k, v in top))
    when = {}
    for i, j in zip(ii, jj):
        when[str(dp[i+1].date())] = when.get(str(dp[i+1].date()), 0) + 1
    wtop = sorted(when.items(), key=lambda x: -x[1])[:5]
    print("  发生最多的日期: " + ", ".join(f"{k}:{v}只" for k, v in wtop))
    print("  → 需确认是真实行情(财报跳空)还是复权/数据错误")
# OHLC 一致性
bad_ohlc = 0
for i in range(0, N, 7):
    h, l, o, cl = H[i], L[i], O[i], C[i]
    m = np.isfinite(h) & np.isfinite(l) & np.isfinite(o) & np.isfinite(cl)
    bad_ohlc += int((h[m] < l[m]).sum() + (cl[m] > h[m]*1.001).sum() + (cl[m] < l[m]*0.999).sum())
print(f"  OHLC 逻辑冲突(high<low 或 close 越界): {bad_ohlc} 处")

print("\n" + "=" * 120); print("C 停牌与僵尸票"); print("=" * 120)
tail = C[-60:]
stale = []
for j, c in enumerate(UNI):
    v = tail[:, j]
    if not np.isfinite(v).all() or np.isnan(v).any():
        stale.append((c, "含 NaN")); continue
    if np.ptp(v) == 0:
        stale.append((c, "近60日价格完全不变")); continue
    lastchg = (C[-1, j] / C[-21, j] - 1) if np.isfinite(C[-21, j]) else np.nan
    if abs(lastchg) < 1e-6:
        stale.append((c, f"近21日零变动"))
if stale:
    print(f"  ⚠ {len(stale)} 只异常:")
    for c, why in stale[:12]: print(f"     {c.replace('US.',''):<8}{why}")
else:
    print("  ✅ 近 60 日无僵尸标的")
# 尾部最新价是否同步
last_valid = {}
for j, c in enumerate(UNI):
    col = C[:, j]
    k = len(col) - 1
    while k >= 0 and not np.isfinite(col[k]): k -= 1
    last_valid[c] = k
if len(set(last_valid.values())) > 1:
    vs = sorted(set(last_valid.values()))
    print(f"  ⚠ 各票最后有效位置不一致: {vs[-3:]} (共 {len(set(last_valid.values()))} 种)")
    late = [c for c, k in last_valid.items() if k < N - 1]
    print(f"     尾部缺失的标的: {[c.replace('US.','') for c in late][:10]}")
else:
    print("  ✅ 所有标的最后一根均有有效价格")

print("\n" + "=" * 120); print("D 调仓序列稳定性(可复现性)"); print("=" * 120)
def rb_of(n): return [i for i in range(n) if i >= START and (i - START) % REBAL == 0]
full = rb_of(N)
print(f"  全样本 N={N}: 调仓索引 {len(full)} 个, 末三个 {full[-3:]}")
for cut in [0, 1, 5, 21]:
    sub = rb_of(N - cut)
    same = sub == [i for i in full if i < N - cut]
    print(f"  去掉尾部 {cut:>2} 根: 前面调仓日{'完全一致' if same else '❌ 发生变化'}")
print("  → 调仓日由绝对索引决定, 追加新数据不会改变历史决策 (无重算漂移)")

print("\n" + "=" * 120); print("E 未来函数检测"); print("=" * 120)
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())
dfH = pd.DataFrame(H, index=dp, columns=UNI); dfL = pd.DataFrame(L, index=dp, columns=UNI)
dfC = pd.DataFrame(C, index=dp, columns=UNI)
mom = dfC.shift(21) / dfC.shift(252) - 1.0
rev = dfC / dfC.shift(21) - 1.0
V = vortex(dfH, dfL, dfC)
S_vor = V; S_mom = (zs(mom) - zs(rev)) / 2.0
# 截断样本: 只用前 N-21 根重算, 与全样本在前 N-21 行的值比较
for nm, A in [("Vortex", V), ("动量-1月反转", S_mom)]:
    a_full = np.asarray(A.values, dtype=float)
    A2 = vortex(dfH.iloc[:N-21], dfL.iloc[:N-21], dfC.iloc[:N-21]) if nm == "Vortex" else \
         (zs(dfC.iloc[:N-21].shift(21)/dfC.iloc[:N-21].shift(252)-1.0) - zs(dfC.iloc[:N-21]/dfC.iloc[:N-21].shift(21)-1.0))/2.0
    a2 = np.asarray(A2.values, dtype=float)
    d = np.nanmax(np.abs(a_full[:N-21] - a2[:N-21]))
    print(f"  {nm:<16} 截断 21 根后前段最大差异 {d:.3e}  {'✅ 无未来函数' if d < 1e-9 else '❌ 受未来数据影响'}")
print("  → 滚动窗口只回看历史, 追加未来数据不改变已有信号值")

print("\n" + "=" * 120); print("F 复权基准漂移 (只拉 1 只对照, 省额度)"); print("=" * 120)
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
_T = os.path.join(os.environ.get("TEMP", "/tmp"), "futu_log_aud"); os.makedirs(_T, exist_ok=True)
os.environ["APPDATA"] = _T
try:
    from common import create_quote_context, safe_close
    from futu import SubType, AuType, SysConfig
    SysConfig.set_all_thread_daemon(True)
    ctx = create_quote_context()
    _, q = ctx.get_history_kl_quota(get_detail=False)
    rem = q[1] if isinstance(q, (list, tuple)) else -1
    print(f"  ⚠ 当前历史K线剩余额度: {rem}  (脚本必须先查额度再拉)")
    code = "US.AAPL"
    out = ctx.request_history_kline(code, start="2018-01-01", end="2026-09-13",
                                    ktype=SubType.K_DAY, autype=AuType.QFQ, max_count=1000)
    safe_close(ctx)
    if out[0] == 0 and out[1] is not None:
        nw = out[1][["time_key", "close"]].copy(); nw["time_key"] = pd.to_datetime(nw["time_key"])
        nw = nw.set_index("time_key")["close"]
        old = pd.read_csv(os.path.join(LONGDIR, "US_AAPL.csv"))
        old["time_key"] = pd.to_datetime(old["time_key"]); old = old.set_index("time_key")["close"]
        common = old.index.intersection(nw.index)
        diff = (old.loc[common] - nw.loc[common]).abs()
        rel = (diff / old.loc[common].abs()).replace([np.inf, -np.inf], np.nan).dropna()
        print(f"  对照 {len(common)} 个共同交易日, 本地 vs 新拉:")
        print(f"     绝对差 最大 {diff.max():.4f}  中位 {diff.median():.6f}")
        print(f"     相对差 最大 {rel.max()*100:.6f}%  中位 {rel.median()*100:.8f}%")
        if rel.max() < 1e-6:
            print("     ✅ 复权基准一致, 历史价格未漂移")
        else:
            print(f"     ❌ 存在漂移! 最大相对差 {rel.max()*100:.4f}% —— 增量合并会留下旧基准尾巴")
    else:
        print(f"  拉取失败 ret={out[0]}")
except Exception as e:
    print(f"  接口对照失败: {type(e).__name__}: {e}")
