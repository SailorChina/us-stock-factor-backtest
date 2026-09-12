# -*- coding: utf-8 -*-
"""
扩容前后信号对比 + 重建 signal_history.csv (带 pool_size 标签)

为什么不用"我记的旧结果": 记忆不可靠。这里把 fetched_codes.json 临时回退到
扩容前的 53 条(靠已抓清单反推, 不靠猜), 真跑一遍拿旧信号, 再恢复。
这样历史表里每一条都是真实计算产物。
"""
import os, sys, json, subprocess, shutil, re

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
PY = r"C:/Users/sailor/AppData/Local/Programs/Python/Python312/python.exe"
os.chdir(BASE)

FC, MI, HIST = "fetched_codes.json", "market_info.json", "signal_history.csv"
man = json.load(open("_fetch_pool_manifest.json", encoding="utf-8"))
added44 = [m["code"] for m in man]
fc_now = json.load(open(FC, encoding="utf-8"))
old_fc = [c for c in fc_now if c not in added44]
mi_now = json.load(open(MI, encoding="utf-8"))
print(f"当前 fetched_codes {len(fc_now)} 条; 本次新增 {len(added44)} 条 -> 扩容前应为 {len(old_fc)} 条")

def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF", "ETN", "3X", "2X", "ULTRA", "PROSHARES",
                                "LEVERAG", " -3X", "3XS", "BEAR", "BULL "])

def pool_of(fc):
    return [c for c in fc if not is_etf(mi_now.get(c, {}).get("name", ""))
            and (mi_now.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

print(f"  扩容前池子 {len(pool_of(old_fc))} 只 | 现在池子 {len(pool_of(fc_now))} 只")

def run_signal(strategy):
    r = subprocess.run([PY, "_update_signal.py", "--no-fetch", "--strategy", strategy],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=600)
    m = re.search(r"策略\s+(\S+)\s+Top(\d+):\s+(.+)", r.stdout or "")
    if not m:
        return None, None, (r.stdout or "")[-400:]
    return int(m.group(2)), m.group(3).strip(), None

results = {}
# ---- 1) 扩容前 (37 只) ----
shutil.copy(FC, "_fc_81.bak"); shutil.copy(MI, "_mi_81.bak")
json.dump(old_fc, open(FC, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n[1] 用扩容前的池子真跑一遍 ...")
for s in ["Vortex", "动量-1月反转"]:
    topk, picks, err = run_signal(s)
    results[(37, s)] = (topk, picks)
    print(f"    {s:<12} Top{topk}: {picks}" + (f"   ERR {err}" if err else ""))

# ---- 2) 恢复 81 只, 再跑一遍 ----
shutil.copy("_fc_81.bak", FC); shutil.copy("_mi_81.bak", MI)
print("\n[2] 用扩容后的池子(81 只)真跑一遍 ...")
for s in ["Vortex", "动量-1月反转"]:
    topk, picks, err = run_signal(s)
    results[(81, s)] = (topk, picks)
    print(f"    {s:<12} Top{topk}: {picks}" + (f"   ERR {err}" if err else ""))
os.remove("_fc_81.bak"); os.remove("_mi_81.bak")

# ---- 3) 重建历史表 ----
import pandas as pd
rows = []
for (psize, s), (topk, picks) in sorted(results.items()):
    if topk is None:
        continue
    rows.append({"date": "2026-09-11", "strategy": s, "topk": topk,
                 "pool_size": psize, "picks": picks, "exec_day": "2026-09-14"})
h = pd.DataFrame(rows).sort_values(["strategy", "pool_size"])
h.to_csv(HIST, index=False, encoding="utf-8-sig")
print("\n[3] 重建 signal_history.csv:")
print(h.to_string(index=False))

print("\n" + "=" * 84)
print("[4] 结论: 扩容把信号改成了什么")
print("=" * 84)
for s in ["Vortex", "动量-1月反转"]:
    a = results.get((37, s), (None, None))[1]
    b = results.get((81, s), (None, None))[1]
    same = "未变" if a == b else "**变了**"
    print(f"  {s:<14} 37只池: {str(a):<22} -> 81只池: {str(b):<22} {same}")
# v27: signal_snapshot.json 已【退出版本控制】(内含账户规模/持仓, 属个人实盘状态)
# -> 克隆后它可能不存在。这里只是顺带打印, 缺失不该让脚本失败。
try:
    snap = json.load(open("signal_snapshot.json", encoding="utf-8"))
    print(f"\n  最终 snapshot: pool_size={snap.get('pool_size')} picks={snap.get('picks')}")
except FileNotFoundError:
    print("\n  (signal_snapshot.json 不存在 —— 它已退出版本控制, 先跑一次 _update_signal.py 即可生成)")
json.dump({"before": {str(k): v for k, v in results.items() if k[0] == 37},
           "after": {str(k): v for k, v in results.items() if k[0] == 81}},
          open("_pool_signal_compare.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("COMPARE_DONE")
