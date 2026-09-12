import sys, os, json, time, numpy as np
sys.path.insert(0, r"C:\Users\sailor\.workbuddy\skills\futuapi\scripts")
from common import create_quote_context, safe_close
from futu import *

codes = json.load(open("fetched_codes.json"))
minfo = json.load(open("market_info.json"))
univ = {u['code']: u['name'] for u in json.load(open("universe_hot100.json"))}
# 与 v3/v5 同口径：仅大盘个股
def keep(code):
    n = (univ.get(code) or "")
    if any(k in n.upper() for k in ("ETF","ETN")): return False
    if (minfo.get(code) or {}).get("total_market_val",0) < 1e10: return False
    return True
fcodes = [c for c in codes if keep(c)]

ctx = create_quote_context()
raw = {}
for code in fcodes:
    try:
        ret, data = ctx.get_financials_statements(code, statement_type=4, financial_type=7, num=1)
    except Exception as e:
        print("ERR", code, str(e)[:40]); time.sleep(1.1); continue
    if ret != 0:
        print("RET", code, ret); time.sleep(1.1); continue
    d = {}
    if isinstance(data, dict):
        rl = data.get("report_list", [])
        if rl:
            items = rl[0].get("item_list", [])
            for it in items:
                d[it.get("field_id")] = it.get("data")
    raw[code] = d
    print(code, "ROE", d.get(14029), "GM", d.get(14002), "NM", d.get(14005),
          "Lev", d.get(14018), "Debt", d.get(14019))
    time.sleep(1.1)   # 遵守 30/30s
safe_close(ctx)
json.dump(raw, open("qmj_raw.json","w"), ensure_ascii=False, indent=2)
print("FETCHED", len(raw), "SAVED qmj_raw.json")
