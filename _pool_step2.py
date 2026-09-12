# -*- coding: utf-8 -*-
"""
扩展标的池 第二步:
  A) 额度明细的时间分布 -> 什么时候能腾出额度
  B) 本地已有哪些数据 (data_kline / data_kline_long)
  C) 热度榜 600 只的市值, 用小批次+逐只兜底, 避开 OTC 股污染整批
"""
import os, sys, json, time, tempfile, glob, collections, datetime

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_pool2")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig

print("=" * 84)
print("[A] 本地数据现状")
print("=" * 84)
for d in ["data_kline", "data_kline_long", "data_index_long"]:
    p = os.path.join(BASE, d)
    fs = glob.glob(os.path.join(p, "*.csv"))
    codes = sorted(os.path.basename(f)[:-4].replace("_", ".") for f in fs)
    print(f"   {d:<18} {len(fs)} 个 CSV")
    if d == "data_kline" and codes:
        print("      " + ", ".join(c.replace("US.", "") for c in codes))

heat = json.load(open(os.path.join(BASE, "_heat_ext.json"), encoding="utf-8"))
hset = {r["code"] for r in heat}
longset = {os.path.basename(f)[:-4].replace("_", ".") for f in glob.glob(os.path.join(BASE, "data_kline_long", "*.csv"))}
shortset = {os.path.basename(f)[:-4].replace("_", ".") for f in glob.glob(os.path.join(BASE, "data_kline", "*.csv"))}
print(f"\n   热度榜600 ∩ 长线数据: {len(hset & longset)} 只")
print(f"   热度榜600 ∩ 短线数据: {len(hset & shortset)} 只")
print(f"   短线数据里, 不在长线数据中的: {len(shortset - longset)} 只")
print("      " + ", ".join(sorted(c.replace('US.','') for c in (shortset - longset))))

SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()

print()
print("=" * 84)
print("[B] 历史 K 线额度明细 —— 什么时候腾出来")
print("=" * 84)
ret, q = ctx.get_history_kl_quota(get_detail=True)
used, rem, detail = q[0], q[1], (q[2] if len(q) > 2 else [])
print(f"   已用 {used} / 总 {used + rem}   剩余 {rem}")
byday = collections.Counter()
rows = []
for d in detail:
    if not isinstance(d, dict):
        continue
    t = str(d.get("request_time", ""))[:10]
    byday[t] += 1
    rows.append((t, d.get("code"), d.get("name")))
print("\n   按请求日期统计 (30 天滚动窗口, 到期即释放):")
for day in sorted(byday):
    exp = (datetime.date.fromisoformat(day) + datetime.timedelta(days=30)).isoformat()
    print(f"      {day}   {byday[day]:>4} 只   约 {exp} 释放")
print(f"\n   我们的池子占了其中: {len([r for r in rows if r[1] in longset | shortset])} 只")

# 最早/最晚
if rows:
    days = sorted({r[0] for r in rows})
    print(f"   明细日期范围: {days[0]} .. {days[-1]}")

print()
print("=" * 84)
print("[C] 补齐热度榜 600 只的市值 (小批次 + 逐只兜底)")
print("=" * 84)
mi_path = os.path.join(BASE, "market_info.json")
mi = json.load(open(mi_path, encoding="utf-8"))
need = [r["code"] for r in heat if r["code"] not in mi]
print(f"   已有 {len(mi)} 条, 需补 {len(need)} 条")

def snap_batch(codes):
    """成功返回 dict; 失败返回 None"""
    try:
        ret, snap = ctx.get_market_snapshot(codes)
    except Exception:
        return None
    if ret != 0:
        return None
    out = {}
    for _, r in snap.iterrows():
        try:
            mv = float(r.get("total_market_val"))
        except Exception:
            mv = None
        out[r["code"]] = {"name": r.get("name", ""), "total_market_val": mv}
    return out

BS = 20
ok = fail = 0
t0 = time.time()
for i in range(0, len(need), BS):
    chunk = need[i:i + BS]
    got = snap_batch(chunk)
    if got is not None and len(got) == len(chunk):
        mi.update(got); ok += len(chunk)
    else:
        # 兜底: 逐只
        for c in chunk:
            one = snap_batch([c])
            if one:
                mi.update(one); ok += 1
            else:
                fail += 1
                mi[c] = {"name": "", "total_market_val": None}
    if (i // BS) % 5 == 0:
        print(f"     进度 {i + len(chunk)}/{len(need)}  成功 {ok}  失败 {fail}  "
              f"耗时 {time.time()-t0:.0f}s")
    time.sleep(0.5)
print(f"   完成: 成功 {ok}, 失败(不可上市值) {fail}, market_info 现 {len(mi)} 条")
json.dump(mi, open(os.path.join(BASE, "_market_info_ext.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

safe_close(ctx)

print()
print("=" * 84)
print("[D] 合格标的漏斗 (非ETF + 市值>=$100亿)")
print("=" * 84)
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF", "ETN", " 3X", " 2X", "3倍", "2倍", "三倍", "二倍",
                                "ULTRA", "PROSHARES", "LEVERAG", "BEAR", "BULL ", "INDEX",
                                "TRUST", "做多", "做空"])

qual, drop = [], []
for r in heat:
    c = r["code"]; d = mi.get(c, {})
    nm = d.get("name") or r.get("name") or ""
    mv = d.get("total_market_val") or 0
    if is_etf(nm):
        drop.append((r["rank"], c, nm, mv, "ETF/杠杆"))
    elif mv < 10e9:
        drop.append((r["rank"], c, nm, mv, "市值<$100亿" if mv else "市值未知/OTC"))
    else:
        qual.append((r["rank"], c, nm, mv))
print(f"   合格 {len(qual)} / 淘汰 {len(drop)}  (共 {len(heat)})")
if len(qual) >= 100:
    print(f"   >> 第 100 只合格标的在榜单第 {qual[99][0]} 名")
print()
print(f"   {'名次':>4} {'代码':<9} {'名称':<28} {'市值亿$':>9}  {'已有长线K线':>10}")
for rk, c, nm, mv in qual[:140]:
    print(f"   {rk:>4} {c.replace('US.',''):<9} {nm[:26]:<28} {mv/1e8:>9,.0f}  "
          f"{'有' if c in longset else '缺':>10}")
json.dump([{"rank": r, "code": c, "name": nm, "mktcap": mv} for r, c, nm, mv in qual],
          open(os.path.join(BASE, "_qualified_ext.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\nSTEP2_DONE")
