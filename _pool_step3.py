# -*- coding: utf-8 -*-
"""
扩展标的池 第三步 (不消耗任何 K 线额度):
  用 get_stock_basicinfo 拿上市日期 -> 反推是否有足够历史 -> 锁定"目标 100 只"名单
"""
import os, sys, json, time, tempfile, glob, datetime

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_pool3")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig, Market, SecurityType

qual = json.load(open(os.path.join(BASE, "_qualified_ext.json"), encoding="utf-8"))
longset = {os.path.basename(f)[:-4].replace("_", ".")
           for f in glob.glob(os.path.join(BASE, "data_kline_long", "*.csv"))}
print(f"合格标的 {len(qual)} 只, 其中已有长线数据 {len([q for q in qual if q['code'] in longset])} 只")

SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()

codes = [q["code"] for q in qual]
info = {}
B = 200
for i in range(0, len(codes), B):
    chunk = codes[i:i + B]
    try:
        ret, df = ctx.get_stock_basicinfo(Market.US, SecurityType.STOCK, chunk)
    except Exception as e:
        print("  异常", e); continue
    if ret != 0:
        print(f"  ret={ret} {str(df)[:110]}"); continue
    for _, r in df.iterrows():
        info[r["code"]] = {"listing_date": str(r.get("listing_date", ""))[:10],
                           "lot_size": r.get("lot_size"),
                           "stock_name": r.get("stock_name", "")}
    print(f"  basicinfo {i}..{i+len(chunk)} -> {len(df)} 条")
    time.sleep(0.6)
safe_close(ctx)

TODAY = datetime.date(2026, 9, 12)
# 反推: 要有 >=253 根日线, 上市日需早于"今天往前 253 个交易日"约 1 年
MIN_LIST = datetime.date(2025, 8, 1)      # 上市早于此 -> 大概率满 253 根
print(f"\n上市日期阈值: 早于 {MIN_LIST} 视为历史足够 (>=253 根日线)")
print(f"\n{'名次':>4} {'代码':<9} {'名称':<26} {'市值亿$':>9} {'上市日':>12} {'历史':>6} {'已有':>5}")
print("-" * 84)
target, lacking = [], []
for q in qual:
    c = q["code"]; d = info.get(c, {})
    ld = d.get("listing_date", "") or ""
    try:
        ldv = datetime.date.fromisoformat(ld)
        enough = ldv <= MIN_LIST
    except Exception:
        enough = None
    rec = {**q, "listing_date": ld, "lot_size": d.get("lot_size"),
           "enough_hist": enough, "has_long": c in longset}
    if enough is False:
        lacking.append(rec)
    else:
        target.append(rec)
    if len(target) <= 120:
        print(f"{q['rank']:>4} {c.replace('US.',''):<9} {q['name'][:24]:<26} "
              f"{q['mktcap']/1e8:>9,.0f} {ld:>12} "
              f"{'够' if enough else ('不够' if enough is False else '?'):>6} "
              f"{'有' if c in longset else '缺':>5}")

print(f"\n历史足够 {len(target)} 只 / 历史不足 {len(lacking)} 只")
print("历史不足的:", ", ".join(f"{r['code'].replace('US.','')}({r['listing_date']})" for r in lacking[:40]))

need = [r for r in target if not r["has_long"]]
print(f"\n目标池取前 100 只 -> 需要新拉 {len([r for r in target[:100] if not r['has_long']])} 只")

out = {
    "generated": TODAY.isoformat(),
    "source": "Futu US 热门榜 (HotListSortField.AVERAGE_HEAT, DESC), offset 0..600, 2026-09-12 抓取",
    "rule": "非 ETF/ETN/杠杆 + 总市值 >= $100亿 + 上市日期满足 >=253 根日线",
    "qualified_total": len(qual),
    "target100": [dict(rank=r["rank"], code=r["code"], name=r["name"],
                       mktcap_usd=r["mktcap"], listing_date=r["listing_date"],
                       has_long=r["has_long"]) for r in target[:100]],
    "dropped_short_history": [dict(rank=r["rank"], code=r["code"], name=r["name"],
                                   mktcap_usd=r["mktcap"], listing_date=r["listing_date"])
                              for r in lacking],
    "backup_beyond_100": [dict(rank=r["rank"], code=r["code"], name=r["name"],
                               mktcap_usd=r["mktcap"], listing_date=r["listing_date"],
                               has_long=r["has_long"]) for r in target[100:]],
}
json.dump(out, open(os.path.join(BASE, "universe_heat100_target.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("\n已保存 universe_heat100_target.json")
print("STEP3_DONE")
