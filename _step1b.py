import sys, json
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, check_ret, safe_close
from futu import *
ctx = create_quote_context()
ret, data = ctx.get_hot_list(Market.US, sort_field=HotListSortField.AVERAGE_HEAT,
                             sort_dir=RankSortDir.DESCENDING, count=5, offset=0)
check_ret(ret, data, ctx, "hot")
all_count, df = data
print("COLS:", list(df.columns))
print(df.head(5).to_string())
safe_close(ctx)
