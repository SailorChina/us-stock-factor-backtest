# -*- coding: utf-8 -*-
import sys, datetime, importlib.util
sys.argv = ['x']
spec = importlib.util.spec_from_file_location('us', '_update_signal.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

print("A) 未完成 bar 检测")
for bj, last in [(datetime.datetime(2026,9,12,3,2),  datetime.date(2026,9,11)),
                 (datetime.datetime(2026,9,12,11,7), datetime.date(2026,9,11)),
                 (datetime.datetime(2026,9,14,22,0), datetime.date(2026,9,14)),
                 (datetime.datetime(2026,9,15,9,0),  datetime.date(2026,9,14))]:
    print(f"   北京 {bj:%m-%d %H:%M} 末bar={last} -> partial={m.bar_is_partial(last,bj):<5} phase={m.us_phase(bj)}")

print()
print("B) 半日市/休市日历")
print("   2026 半日市:", m.HALF_DAYS[2026], "| 2026 休市数:", len(m.HOLIDAYS[2026]))

print()
print("C) 输入校验")
for s in ['META:1.15', 'META-1.15', 'META:abc', 'META:1.15,BE:2.70']:
    try:
        print(f"   parse_positions({s!r}) -> OK {m.parse_positions(s)}")
    except SystemExit as e:
        print(f"   parse_positions({s!r}) -> 友好报错: {str(e).strip()}")
for s in ['META:1.15@648.03', 'META:1.15', 'META:1.15@']:
    try:
        print(f"   parse_bought({s!r}) -> OK {m.parse_bought(s)}")
    except SystemExit as e:
        print(f"   parse_bought({s!r}) -> 友好报错: {str(e).strip()}")
