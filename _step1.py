import sys, os, json
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, check_ret, safe_close
from futu import *
ctx = create_quote_context()
ret, data = ctx.get_hot_list(Market.US, sort_field=HotListSortField.AVERAGE_HEAT,
                             sort_dir=RankSortDir.DESCENDING, count=100, offset=0)
check_ret(ret, data, ctx, "获取热门榜")
all_count, df = data
codes = df['security'].tolist()
names = df['name'].tolist()
print("HOT_ALL_COUNT", all_count, "GOT", len(codes))
print("SAMPLE", codes[:15])
with open("universe_hot100.json", "w") as f:
    json.dump([{"code": c, "name": n} for c, n in zip(codes, names)], f, ensure_ascii=False, indent=2)
# quota
ret2, q = ctx.get_history_kl_quota(get_detail=False)
print("QUOTA_RAW", ret2, q)
# test one
ret3, kd = ctx.request_history_kline("US.AAPL", start="2023-09-01", end="2026-09-11",
                                     ktype=SubType.K_DAY, autype=AuType.QFQ, max_count=1000)
print("KLINE_RET", ret3, "ROWS", len(kd) if ret3 == 0 else kd)
if ret3 == 0:
    print("FIRST", kd.iloc[0]['time_key'], "LAST", kd.iloc[-1]['time_key'])
safe_close(ctx)
print("STEP1_DONE")
