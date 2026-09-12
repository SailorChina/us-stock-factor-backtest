"""
动态热门股股票池管理器 (Futu OpenD)
==================================
思路：热门股每天在变，静态快照有前视偏差。本脚本每日运行：
  1) 拉取富途美股「综合热度」前 100 只
  2) 并入持久化池 universe_dynamic.json（并集，按代码去重）
     - 在榜 -> last_seen=今天, miss_streak=0, times_seen+1
     - 不在榜 -> miss_streak+1
  3) 连续 miss_streak >= MAX_MISS_DAYS 的标的剔除（"过几天不符合就剔除"）
  4) 存档 + 打印摘要

首次运行以 universe_hot100.json（今日快照）为种子，之后靠每日运行自然增长/淘汰。
K线取数另由 _fetch.py 负责，受 30 天额度限制，不在此脚本内。

用法：
  python universe_manager.py            # 默认 MAX_MISS_DAYS=5
  python universe_manager.py --max-miss 7
"""
import sys, os, json, argparse, datetime

# 已知坑2/3：建 context 前设置 daemon 线程 + 重定向 futu 日志写入，避免进程静默退出
LOGDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "futulog")
os.makedirs(LOGDIR, exist_ok=True)
os.environ["APPDATA"] = LOGDIR

sys.path.insert(0, r"C:\Users\sailor\.workbuddy\skills\futuapi\scripts")
from common import create_quote_context, check_ret, safe_close
from futu import SysConfig, Market, HotListSortField, RankSortDir

MAX_MISS_DAYS = 5
TODAY = datetime.date.today().isoformat()
HERE = os.path.dirname(os.path.abspath(__file__))
POOL_FILE = os.path.join(HERE, "universe_dynamic.json")
SEED_FILE = os.path.join(HERE, "universe_hot100.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-miss", type=int, default=MAX_MISS_DAYS,
                    help="连续掉出榜单达到该天数则剔除（默认 5）")
    args = ap.parse_args()
    MAX_MISS = args.max_miss

    # ---- 载入已有池；首次以今日快照为种子 ----
    pool = {"stocks": {}}
    if os.path.exists(POOL_FILE):
        try:
            pool = json.load(open(POOL_FILE, encoding="utf-8"))
        except Exception:
            pool = {"stocks": {}}
    stocks = pool.get("stocks", {})
    if not stocks and os.path.exists(SEED_FILE):
        for it in json.load(open(SEED_FILE, encoding="utf-8")):
            stocks[it["code"]] = {"name": it["name"], "first_seen": TODAY,
                                  "last_seen": TODAY, "miss_streak": 0, "times_seen": 1}

    # ---- 拉取今日前 100 热门 ----
    SysConfig.set_all_thread_daemon(True)
    ctx = create_quote_context()
    ret, data = ctx.get_hot_list(Market.US, sort_field=HotListSortField.AVERAGE_HEAT,
                                 sort_dir=RankSortDir.DESCENDING, count=100, offset=0)
    check_ret(ret, data, ctx, "获取热门榜")
    _, df = data
    cur = {r["security"]: r["name"] for _, r in df.iterrows()}
    safe_close(ctx)

    # ---- 合并 ----
    added, seen, pruned = [], [], []
    cur_codes = set(cur.keys())
    for code, name in cur.items():
        if code in stocks:
            stocks[code]["last_seen"] = TODAY
            stocks[code]["miss_streak"] = 0
            stocks[code]["times_seen"] = stocks[code].get("times_seen", 0) + 1
            stocks[code]["name"] = name
            seen.append(code)
        else:
            stocks[code] = {"name": name, "first_seen": TODAY, "last_seen": TODAY,
                            "miss_streak": 0, "times_seen": 1}
            added.append(code)
    # 不在榜的累计 miss
    for code in stocks:
        if code not in cur_codes:
            stocks[code]["miss_streak"] = stocks[code].get("miss_streak", 0) + 1
    # 剔除
    to_prune = [c for c in stocks if stocks[c]["miss_streak"] >= MAX_MISS]
    for c in to_prune:
        pruned.append({"code": c, "name": stocks[c]["name"], "miss": stocks[c]["miss_streak"]})
        del stocks[c]

    pool["stocks"] = stocks
    pool["updated"] = TODAY
    pool["max_miss_days"] = MAX_MISS
    json.dump(pool, open(POOL_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # ---- 摘要 ----
    miss_pos = [c for c in stocks if stocks[c]["miss_streak"] > 0]
    print(json.dumps({
        "today": TODAY,
        "current_top100": len(cur),
        "pool_total": len(stocks),
        "added": added,
        "pruned": pruned,
        "miss_streak_gt0": sorted(
            [{"code": c, "name": stocks[c]["name"], "miss": stocks[c]["miss_streak"]}
             for c in miss_pos], key=lambda x: -x["miss"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
