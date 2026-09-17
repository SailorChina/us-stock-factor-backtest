# -*- coding: utf-8 -*-
"""【已迁移 · 墓碑】这里原先是美股因子策略的信号生成器（一键下单助手 v33 双频版）。

2026-09-17（P2-AH）整条运行链已迁入智能体私有仓的 strategy/ 子目录：
    C:/Users/sailor/us-stock-live-agent/strategy/_update_signal.py
（原文件内容完整保留在同目录的 _update_signal.py.2026-09-17-moved.bak，
  也在 C:\\Users\\sailor\\Backups\\strategy-session-backup-20260917.zip 里。）

为什么留一个「会报错」的墓碑，而不是删掉、也不是原样保留：
  原样保留 = 最大的坑。它**仍然能跑通**、**仍然会打印「已保存 signal_snapshot.json」**，
  但快照写在**这个目录**，而下游（us-stock-live-agent 的预检第 5 项、决策层的
  signal_stale 守卫）读的是**新目录**。于是结果就是「跑成功了，什么都没变」
  —— 不报错、只让结果悄悄过期。这正是本项目反复吃亏的那一类缺陷
  （退出码 0 ≠ 生效；能力存在 ≠ 能力可达）。
  ⇒ 让它**响亮地失败**，而不是安静地骗人。

如果你确实需要旧口径（例如复现历史回测），用 .bak 那份 + 显式指定 BASE，
不要把这个墓碑改回去 —— 那等于重新埋下同一个坑。

注：本文件刻意**不用 str.format()** —— 正文里有 {"=" * 78} 这样的花括号，
    会被 format 当成占位符（实测 KeyError: '"=" * 78'）。用 % 或直接拼接。
"""
import sys

NEW = "C:/Users/sailor/us-stock-live-agent/strategy"
BAR = "=" * 78

print(BAR)
print("[已迁移] _update_signal.py 不在这个目录了（2026-09-17 P2-AH 迁移）。")
print("  新位置: %s/_update_signal.py" % NEW)
print("  跑法  : cd \"%s\"" % NEW)
print("          python _update_signal.py --rebal 10 --capital 1500")
print("  原因  : 本目录是 WorkBuddy 的【会话目录】（按会话创建、可能被清理），")
print("          而整条链（信号生成 + 股池维护 + 智能体预检 + 05:30 无人值守）")
print("          全挂在这个绝对路径上 —— 是全链最脆的一环。已收进私有仓。")
print("  注意  : 在这里跑**不会报错**、也会打印「已保存快照」，但快照写在本目录、")
print("          没有任何读方 —— 那种「静默过期」正是本次迁移要消灭的东西，")
print("          所以这里直接拒绝执行（退出码 2）。")
print(BAR)
sys.exit(2)
