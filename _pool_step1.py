# -*- coding: utf-8 -*-
"""
扩展标的池 第一步: 摸清额度 + 热度榜到底有多深 + 补齐市值信息
只读, 不改动任何数据文件。
"""
import os, sys, json, time, tempfile

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_pool")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig, Market, HotListSortField, RankSortDir

SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()

print("=" * 84)
print("[1] 历史 K 线额度 (决定性约束)")
print("=" * 84)
ret, q = ctx.get_history_kl_quota(get_detail=True)
print("   ret =", ret)
used = rem = None
detail = []
if isinstance(q, (list, tuple)):
    used, rem = q[0], q[1]
    if len(q) > 2:
        d = q[2]
        detail = d if isinstance(d, list) else []
print(f"   已用 = {used}   剩余 = {rem}   已用明细条数 = {len(detail)}")
if detail:
    name = detail[0].get("name") if isinstance(detail[0], dict) else None
    print(f"   明细前 3 条: {detail[:3]}")
print(f"   >> 结论: 本次最多能新拉 {rem} 只标的的历史 K 线")

print()
print("=" * 84)
print("[2] 热度榜能拉多深 (offset 扫描)")
print("=" * 84)
allrows = []
seen = set()
for off in range(0, 600, 100):
    try:
        ret, data = ctx.get_hot_list(Market.US, sort_field=HotListSortField.AVERAGE_HEAT,
                                     sort_dir=RankSortDir.DESCENDING, count=100, offset=off)
    except Exception as e:
        print(f"   offset={off} 异常 {e}"); break
    if ret != 0:
        print(f"   offset={off} ret={ret} -> {str(data)[:90]}")
        break
    _, df = data
    if df is None or len(df) == 0:
        print(f"   offset={off} 返回 0 条 -> 榜单到底了")
        break
    got = 0
    for _, r in df.iterrows():
        code = r["security"]
        if code in seen:
            continue
        seen.add(code)
        allrows.append({"rank": off + got + 1, "code": code,
                        "name": r.get("name", ""), "heat": r.get("average_heat", None)})
        got += 1
    print(f"   offset={off} 返回 {len(df)} 条, 新增 {got} 条 (累计 {len(allrows)})")
    time.sleep(1.0)

print(f"\n   热度榜共取到 {len(allrows)} 条去重后记录")

print()
print("=" * 84)
print("[3] 给新代码补 name + total_market_val (get_market_snapshot)")
print("=" * 84)
mi_path = os.path.join(BASE, "market_info.json")
mi = json.load(open(mi_path, encoding="utf-8"))
need = [r["code"] for r in allrows if r["code"] not in mi]
print(f"   已有市值信息 {len(mi)} 条, 需补 {len(need)} 条")
BATCH = 100
for i in range(0, len(need), BATCH):
    chunk = need[i:i + BATCH]
    try:
        ret, snap = ctx.get_market_snapshot(chunk)
    except Exception as e:
        print(f"   批次 {i} 异常 {e}"); continue
    if ret != 0:
        print(f"   批次 {i} ret={ret} {str(snap)[:100]}"); continue
    for _, r in snap.iterrows():
        mv = r.get("total_market_val")
        try:
            mv = float(mv)
        except Exception:
            mv = None
        mi[r["code"]] = {"name": r.get("name", ""), "total_market_val": mv}
    print(f"   批次 {i}..{i+len(chunk)} 取到 {len(snap)} 条 (累计 market_info {len(mi)})")
    time.sleep(1.0)

json.dump(mi, open(os.path.join(BASE, "_market_info_ext.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
json.dump(allrows, open(os.path.join(BASE, "_heat_ext.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("   已存 _market_info_ext.json / _heat_ext.json (临时, 供下一步判断)")

print()
print("=" * 84)
print("[4] 逐层收窄: 从榜单往下取, 到第几名能凑满 100 只合格标的")
print("=" * 84)
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG",
                                " -3X","3XS","BEAR","BULL ","INDEX","TRUST"])
qual, dropped = [], []
for r in allrows:
    c = r["code"]; d = mi.get(c, {})
    nm = d.get("name") or r.get("name") or ""
    mv = d.get("total_market_val") or 0
    if is_etf(nm):
        dropped.append((r["rank"], c, nm, mv, "ETF/杠杆/指数"))
    elif mv < 10e9:
        dropped.append((r["rank"], c, nm, mv, "市值<$100亿" if mv else "市值未知"))
    else:
        qual.append((r["rank"], c, nm, mv))
print(f"   合格 {len(qual)} 只 / 淘汰 {len(dropped)} 只")
if qual:
    print(f"   第 100 只合格标的出现在榜单第 {qual[min(99, len(qual)-1)][0]} 名")
print()
print(f"   {'排名':>4} {'代码':<9} {'名称':<30} {'市值亿$':>9}")
for rk, c, nm, mv in qual[:130]:
    print(f"   {rk:>4} {c.replace('US.',''):<9} {nm[:28]:<30} {mv/1e8:>9,.0f}")

safe_close(ctx)
print("\nSTEP1_DONE")
