import sys, os, json
sys.path.insert(0, r"C:\Users\sailor\.workbuddy\skills\futuapi\scripts")
from common import create_quote_context, check_ret, safe_close
from futu import *

ctx = create_quote_context()
for code in ["US.AAPL", "US.NVDA"]:
    print("="*50, code)
    ret, data = ctx.get_financials_statements(code, statement_type=4, financial_type=7, num=1)  # 年报关键指标
    print("RET", ret)
    if ret != 0:
        print(data); continue
    if isinstance(data, dict):
        sl = data.get("structure_list", [])
        rl = data.get("report_list", [])
        print("FIELDS:", [(f.get("field_id"), f.get("display_name")) for f in sl][:30])
        if rl:
            rep = rl[0]
            print("PERIOD", rep.get("period_text"), "CUR", rep.get("currency_code"))
            items = rep.get("item_list", [])
            for it in items[:30]:
                print("  ", it.get("field_id"), it.get("data"))
    else:
        print(type(data), str(data)[:300])
safe_close(ctx)
print("PROBE_DONE")
