# -*- coding: utf-8 -*-
"""缺陷取证: 逐项实测剩余风险, 不猜"""
import os, sys, json, time, tempfile, datetime
import numpy as np, pandas as pd
import warnings; warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
pd.set_option("display.width", 200)

print("=" * 110)
print("缺陷取证 A: 前复权(QFQ)增量合并 -> 是否留下'基准断层'")
print("=" * 110)
_T = os.path.join(tempfile.gettempdir(), "futu_log_probe"); os.makedirs(_T, exist_ok=True)
os.environ["APPDATA"] = _T
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SubType, AuType, SysConfig
SysConfig.set_all_thread_daemon(True)

# 挑 3 只有分红的大盘股, 取长窗口重拉, 与本地重叠区逐日比对
TESTS = ["US.AAPL", "US.MSFT", "US.META"]
ctx = create_quote_context()
try:
    _, q = ctx.get_history_kl_quota(get_detail=False)
    print(f"  额度剩余: {q[1] if isinstance(q,(list,tuple)) else q}")
    for code in TESTS:
        loc = pd.read_csv(os.path.join(LONGDIR, code.replace(".", "_") + ".csv"))
        loc["time_key"] = pd.to_datetime(loc["time_key"])
        loc = loc.set_index("time_key").sort_index()
        st = (loc.index[-1] - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        out = ctx.request_history_kline(code, start=st, end=loc.index[-1].strftime("%Y-%m-%d"),
                                        ktype=SubType.K_DAY, autype=AuType.QFQ, max_count=500)
        if out[0] != 0 or out[1] is None or len(out[1]) == 0:
            print(f"  {code}: 拉取失败 ret={out[0]}"); time.sleep(0.5); continue
        fresh = out[1].set_index(pd.to_datetime(out[1]["time_key"])).sort_index()
        ov = loc.index.intersection(fresh.index)
        a = loc.loc[ov, "close"].astype(float).values
        b = fresh.loc[ov, "close"].astype(float).values
        rel = np.abs(a - b) / np.maximum(np.abs(a), 1e-9)
        nz = rel > 1e-6
        print(f"  {code}: 重叠 {len(ov)} 日, 最大相对差 {rel.max():.8f}, 有差异天数 {nz.sum()}")
        if nz.sum() in (0, len(ov)):
            print(f"     -> {'完全一致(该窗口无复权基准变化)' if nz.sum()==0 else '整段都不同(存在系统性基准漂移!)'}")
        else:
            # 局部差异: 找出断层位置 —— 这是最危险的情形
            idx_nz = np.where(nz)[0]
            print(f"     -> ⚠ 局部差异! 首次不同在第 {idx_nz[0]} 天 ({ov[idx_nz[0]].date()}), "
                  f"末次在第 {idx_nz[-1]} 天 ({ov[idx_nz[-1]].date()})")
            print(f"        本地{b[0]:.2f} vs 新拉{a[0]:.2f}  (首日)")
        time.sleep(0.4)
finally:
    safe_close(ctx)

print()
print("=" * 110)
print("缺陷取证 B: 合并后的历史序列里是否存在'接缝跳变'")
print("=" * 110)
for code in TESTS:
    d = pd.read_csv(os.path.join(LONGDIR, code.replace(".", "_") + ".csv"))
    d["time_key"] = pd.to_datetime(d["time_key"])
    d = d.sort_values("time_key").reset_index(drop=True)
    r = d["close"].pct_change()
    big = np.where(np.abs(r.values) > 0.15)[0]
    if len(big) == 0:
        print(f"  {code}: 全程无 |单日涨跌|>15% 的跳变 -> 无接缝迹象")
    else:
        print(f"  {code}: 有 {len(big)} 处 >15% 跳变:")
        for i in big[-6:]:
            print(f"     {d['time_key'][i].date()}  {r[i]*100:+.1f}%  "
                  f"({d['close'][i-1]:.2f} -> {d['close'][i]:.2f})")

print()
print("=" * 110)
print("缺陷取证 C: 调仓日历分支 (非调仓日时会说什么?)")
print("=" * 110)
mi = json.load(open(os.path.join(BASE, "market_info.json")))
fc = json.load(open(os.path.join(BASE, "fetched_codes.json")))
tpl = pd.read_csv(os.path.join(LONGDIR, "US_AAPL.csv"))
N_full = len(tpl)
START, REBAL = 252, 21
for drop in [0, 3, 7, 15]:
    N = N_full - drop
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    is_reb = (RB[-1] == N - 1)
    nxt = RB[-1] + REBAL
    print(f"  面板裁掉最后 {drop:>2} 根 -> N={N}, 最后调仓索引={RB[-1]} (N-1={N-1}), "
          f"is_rebal={is_reb}, 下次调仓索引={nxt} {'(已在面板内)' if nxt < N else '(尚未到来)'}")
    if not is_reb:
        print(f"     ⚠ 脚本 else 分支会打印: 上次调仓=[RB[-2]], 下次调仓=[RB[-1]]  <- RB[-1] 其实是【过去】的调仓日")

print()
print("=" * 110)
print("缺陷取证 D: 标的池与元数据的时效性")
print("=" * 110)
print(f"  market_info.json 标的数: {len(mi)}, fetched_codes.json: {len(fc)}")
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fc if not is_etf(mi.get(c, {}).get("name", "")) and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]
print(f"  过滤后 UNI: {len(UNI)} 只")
miss = [c for c in fc if c not in mi]
if miss: print(f"  ⚠ 无元数据的代码: {miss}")
# 池子集中度
print(f"  市值门槛 10e9 是【2026 年快照】, 不是动态更新 -> 幸存者偏差无法消除")

print()
print("=" * 110)
print("缺陷取证 E: 未使用的变量 / 死代码 / 潜在崩溃点")
print("=" * 110)
src = open(os.path.join(BASE, "_update_signal.py"), encoding="utf-8").read()
for name, pat in [("V_ (赋值后从未使用)", "V_ = PX"),
                  ("lines (赋值后从未使用)", "lines = []"),
                  ("market_info 无异常保护", 'json.load(open(os.path.join(BASE, "market_info.json")))')]:
    print(f"  {'⚠' if pat in src else '✓'} {name}: {'存在' if pat in src else '未见'}")
# 检查 exec_d 在 else 分支的取值
print("  检查: else 分支 exec_d 赋值条件 RB[-1]+REBAL < N")
for drop in [3, 7, 15]:
    N = N_full - drop
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    cond = RB[-1] + REBAL < N
    print(f"     裁掉{drop:>2}根: RB[-1]+REBAL={RB[-1]+REBAL}, N={N} -> 条件={cond} "
          f"-> exec_d={'有值' if cond else 'None (永远拿不到执行日!)'}")
