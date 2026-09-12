# -*- coding: utf-8 -*-
"""
扩展标的池 第四步: 按目标名单拉取缺失标的的长周期日线
========================================================
设计要点:
  - 目标名单来自 universe_heat100_target.json (热度榜前 200 内选出的 100 只)
  - 额度是硬约束: 每只标的 30 天内只计 1 次。已在本窗口内的标的重复请求免费。
    -> 先查明细, 算出"真正要花额度"的标的, 再按 --limit 截断
  - 坑6 翻页: request_history_kline 单次返回区间【前】N 根, 8.7 年需翻 3 页
  - 坑5 盘中假 bar: 拉完校验末根成交量 vs 近 20 日中位数
  - 坑1 日志: import futu 前重定向 APPDATA

用法:
  python _fetch_pool_ext.py --limit 10          # 只花 10 个额度
  python _fetch_pool_ext.py --limit 0 --dry-run # 只看要花多少额度
  python _fetch_pool_ext.py                     # 全部缺失都拉
"""
import os, sys, json, time, tempfile, argparse, glob, datetime

_TMPLOG = os.path.join(tempfile.gettempdir(), "futu_log_fetchpool")
os.makedirs(_TMPLOG, exist_ok=True)
os.environ["APPDATA"] = _TMPLOG

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, safe_close
from futu import SysConfig, SubType, AuType

START = "2018-01-01"
END = "2026-09-12"          # 开区间, 末根 = 2026-09-11(周五)
OUTDIR = os.path.join(BASE, "data_kline_long")
os.makedirs(OUTDIR, exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=10 ** 9, help="本次最多新花几个额度")
ap.add_argument("--dry-run", action="store_true", help="只报告, 不抓取")
ap.add_argument("--end", default=END)
args = ap.parse_args()
END = args.end

target = json.load(open(os.path.join(BASE, "universe_heat100_target.json"), encoding="utf-8"))
rows = sorted(target["target100"], key=lambda r: r["rank"])
have = {os.path.basename(f)[:-4].replace("_", ".")
        for f in glob.glob(os.path.join(OUTDIR, "*.csv"))}
missing = [r for r in rows if r["code"] not in have]
print(f"目标 100 只 | 已有 {len(rows)-len(missing)} | 缺失 {len(missing)}")
print("缺失名单(按热度名次):")
for r in missing:
    print(f"   {r['rank']:>4} {r['code'].replace('US.',''):<7} {r['name'][:24]:<26} "
          f"{r['mktcap_usd']/1e8:>8,.0f}亿")

SysConfig.set_all_thread_daemon(True)
ctx = create_quote_context()

ret, q = ctx.get_history_kl_quota(get_detail=True)
used, rem, detail = q[0], q[1], (q[2] if len(q) > 2 else [])
inwin = {d["code"] for d in detail if isinstance(d, dict) and "code" in d}
print(f"\n额度: 已用 {used} / 总 {used+rem}   剩余 {rem}   窗口内已占 {len(inwin)} 只")

free = [r for r in missing if r["code"] in inwin]      # 重复请求免费
paid = [r for r in missing if r["code"] not in inwin]  # 真正花额度
print(f"其中: 免费(本窗口已占) {len(free)} 只 | 需花额度 {len(paid)} 只")
todo = free + paid
if len(paid) > args.limit:
    keep_paid = paid[:args.limit]
    todo = free + keep_paid
    print(f"  >> --limit {args.limit}: 本次只拉 {len(todo)} 只 "
          f"(免费 {len(free)} + 花额度 {len(keep_paid)}), 余 {len(paid)-len(keep_paid)} 只留待下次")
print(f"\n本次计划抓取 {len(todo)} 只")

if args.dry_run or not todo:
    safe_close(ctx)
    print("DRY_RUN_DONE")
    sys.exit(0)

import pandas as pd

def fetch_one(code):
    chunks, start, pages = [], START, 0
    while True:
        pages += 1
        if pages > 12:
            print(f"    [ABORT] {code} 翻页超限"); break
        retry = 0
        while True:
            try:
                out = ctx.request_history_kline(code, start=start, end=END,
                                                ktype=SubType.K_DAY, autype=AuType.QFQ,
                                                max_count=1000)
                ret, kd = out[0], out[1]
            except Exception as e:
                retry += 1
                if retry > 5:
                    print(f"    [ERR] {code} 异常 {e}"); return None
                time.sleep(3); continue
            if ret != 0:
                retry += 1
                msg = str(kd)
                if retry <= 5:
                    time.sleep(5); continue
                print(f"    [ERR] {code} ret={ret} {msg[:70]}"); return None
            break
        if kd is None or len(kd) == 0:
            break
        kd = kd[kd["time_key"] < END].copy()
        if len(kd):
            chunks.append(kd)
            last = kd["time_key"].iloc[-1]
            if len(kd) < 1000:
                break
            nxt = (pd.to_datetime(last) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            if nxt <= start:
                break
            start = nxt
        else:
            break
        time.sleep(1.0)
    if not chunks:
        return None
    full = (pd.concat(chunks, ignore_index=True)
            .drop_duplicates("time_key").sort_values("time_key").reset_index(drop=True))
    return full

manifest, failed = [], []
for k, r in enumerate(todo, 1):
    code = r["code"]
    print(f"[{k}/{len(todo)}] {code} (名次 {r['rank']}) ...", flush=True)
    df = fetch_one(code)
    if df is None or len(df) < 200:
        print(f"    SKIP rows={0 if df is None else len(df)}")
        failed.append({"code": code, "rows": 0 if df is None else len(df)})
        continue
    fpath = os.path.join(OUTDIR, code.replace(".", "_") + ".csv")
    df[["time_key", "open", "close", "high", "low", "volume"]].to_csv(fpath, index=False)
    last = df["time_key"].iloc[-1]
    med = df["volume"].tail(21).iloc[:-1].median()
    ratio = (df["volume"].iloc[-1] / med) if med else float("nan")
    warn = ""
    if ratio != ratio or ratio < 0.5:
        warn = f"  <== 末根量比异常 {ratio:.2f} (疑似未完成 bar)"
    manifest.append({"code": code, "rank": r["rank"], "rows": int(len(df)),
                     "first": df["time_key"].iloc[0], "last": last,
                     "last_vol_ratio": round(float(ratio), 3) if ratio == ratio else None})
    print(f"    OK rows={len(df)} {df['time_key'].iloc[0]}..{last} 量比={ratio:.2f}{warn}")
    time.sleep(1.0)

safe_close(ctx)

print("\n" + "=" * 84)
print(f"抓取完成: 成功 {len(manifest)} 只, 失败 {len(failed)} 只")
if failed:
    print("失败:", [f["code"] for f in failed])
lasts = {}
for m in manifest:
    lasts[m["last"]] = lasts.get(m["last"], 0) + 1
print("末根日期分布:", lasts)

json.dump(manifest, open(os.path.join(BASE, "_fetch_pool_manifest.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- 更新池定义文件 (fetched_codes.json / market_info.json) ----
mi_path = os.path.join(BASE, "market_info.json")
fc_path = os.path.join(BASE, "fetched_codes.json")
mi = json.load(open(mi_path, encoding="utf-8"))
fc = json.load(open(fc_path, encoding="utf-8"))
mi_ext = json.load(open(os.path.join(BASE, "_market_info_ext.json"), encoding="utf-8"))
added_fc = []
for m in manifest:
    c = m["code"]
    if c not in fc:
        fc.append(c); added_fc.append(c)
    if c not in mi and c in mi_ext:
        mi[c] = mi_ext[c]
json.dump(fc, open(fc_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
json.dump(mi, open(mi_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"fetched_codes.json: {len(fc)} 条 (新增 {len(added_fc)})")
print(f"market_info.json  : {len(mi)} 条")

def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF", "ETN", "3X", "2X", "ULTRA", "PROSHARES",
                                "LEVERAG", " -3X", "3XS", "BEAR", "BULL "])
pool = [c for c in fc if not is_etf(mi.get(c, {}).get("name", ""))
        and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]
print(f"按老口径 (非ETF + 市值>=$100亿) 重算池子: {len(pool)} 只")
print("FETCH_POOL_DONE")
