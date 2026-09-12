import sys, os, json, time
sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
from common import create_quote_context, check_ret, safe_close
from futu import *

TODAY = "2026-09-11"
os.makedirs("data_kline", exist_ok=True)

with open("universe_hot100.json") as f:
    universe = json.load(f)

# 排除杠杆/未上市类（名字含 3X/2X/Ultra 等），SpaceX 无数据会在取数时剔除
def is_leveraged(name):
    n = (name or "").upper()
    return any(k in n for k in ["3X", "2X", "ULTRA", "PROSHARES", " -3X", "3XS", "BEAR 3X", "BULL 3X"])

# 先看剩余额度
ctx = create_quote_context()
_, q = ctx.get_history_kl_quota(get_detail=False)
remaining = q[1] if isinstance(q, (list, tuple)) else 53
print("QUOTA_REMAINING", remaining)
ctx.close()

# 取数上限 = 剩余额度
cap = int(remaining)
fetched = 0
ok, skipped = [], []
ctx = create_quote_context()
for item in universe:
    if fetched >= cap:
        print("REACHED_QUOTA_CAP", cap)
        break
    code = item["code"]; name = item["name"]
    if is_leveraged(name):
        skipped.append((code, name, "leveraged"))
        continue
    fpath = os.path.join("data_kline", code.replace(".", "_") + ".csv")
    if os.path.exists(fpath):
        ok.append(code); fetched += 1
        continue
    try:
        out = ctx.request_history_kline(code, start="2023-09-01", end=TODAY,
                                        ktype=SubType.K_DAY, autype=AuType.QFQ, max_count=1000)
        ret = out[0]; kd = out[1]
    except Exception as e:
        skipped.append((code, name, "err:" + str(e)[:40])); time.sleep(1); continue
    if ret != 0:
        skipped.append((code, name, "ret%d" % ret)); time.sleep(1); continue
    kd = kd[kd["time_key"] < TODAY].copy()
    if len(kd) < 500:
        skipped.append((code, name, "rows%d" % len(kd))); time.sleep(1); continue
    kd[["time_key","open","close","high","low","volume"]].to_csv(fpath, index=False)
    ok.append(code); fetched += 1
    print("OK", code, name, "rows", len(kd), "last", kd.iloc[-1]["time_key"])
    time.sleep(1.0)  # 节流：~1/s，远低于 60/30s
ctx.close()

with open("fetched_codes.json", "w") as f:
    json.dump(ok, f, ensure_ascii=False, indent=2)
print("FETCHED", len(ok), "SKIPPED", len(skipped))
for s in skipped[:20]:
    print("SKIP", s)
print("FETCH_DONE")
