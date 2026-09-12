import sys, json
sys.path.insert(0, r"C:\Users\sailor\.workbuddy\skills\futuapi\scripts")
from common import create_quote_context, safe_close
from futu import *

codes = json.load(open("fetched_codes.json"))
ctx = create_quote_context()
ret, df = ctx.get_market_snapshot(codes)
if ret != 0:
    print("ERR", ret, df); safe_close(ctx); sys.exit(1)
safe_close(ctx)

# 确认市值单位：打印若干已知标的
probe = ["US.AAPL","US.NVDA","US.MU","US.NKE","US.NOK","US.AXTI","US.AAOI","US.CRDO","US.TEM"]
print("=== market_val unit check ===")
for c in probe:
    if c in df["code"].values:
        row = df[df["code"]==c].iloc[0]
        print(f"{c} {row['name']}: total_market_val={row['total_market_val']}")

out = {}
for _, r in df.iterrows():
    mv = r.get("total_market_val")
    out[r["code"]] = {"name": r.get("name"),
                      "total_market_val": float(mv) if mv is not None else None}
json.dump(out, open("market_info.json", "w"), ensure_ascii=False, indent=2)
print("SAVED market_info.json")
