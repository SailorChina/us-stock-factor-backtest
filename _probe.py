import os, sys
# 已知坑2/3：建 context 前设置 daemon 线程，并重定向 futu 日志写入路径避免静默退出
os.environ.setdefault('APPDATA', os.path.join(os.path.dirname(os.path.abspath('_probe.py')), 'futulog'))
from futu import *
try:
    import importlib.metadata as md
    print("futu-api version:", md.version("futu-api"))
except Exception as e:
    print("version check err:", e)
SysConfig.set_all_thread_daemon(True)
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
print("connect ok, trading days API test...")
ret, data = ctx.get_history_kline('US.AAPL', start='2026-08-25', end='2026-09-10', ktype=SubType.K_DAY, max_count=10, auth=None)
print("ret:", ret)
if ret == 0:
    print(data[['code','time_key','open','close','volume']].to_string())
else:
    print(data)
ctx.close()
print("DONE")
