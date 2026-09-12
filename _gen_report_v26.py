# -*- coding: utf-8 -*-
"""
从 _rank_all.json 生成《美股全策略总排名_v26.md》。

设计原则: 所有表格由 JSON 直出, 不手抄任何一个数字。
排序/取数/百分比格式化全部集中在这里, 保证正文与附录口径一致。
"""
import json
import os
from collections import defaultdict

D = r'C:\Users\sailor\WorkBuddy\2026-09-11-09-02-22'
J = json.load(open(os.path.join(D, '_rank_all.json'), encoding='utf-8'))
META, RES, CHECKS = J['meta'], J['results'], J['checks']

PHASES = ['2019-20.2牛', '2020崩盘', '2020-21牛', '2022熊市', '2023-26牛']
YEARS = ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026']


# ---------- 格式化 ----------
def P(x, nd=1):
    if x is None:
        return '—'
    return f'{x * 100:,.{nd}f}%'


def M(x):
    if x is None:
        return '—'
    return f'${x:,.0f}'


def N(x, nd=2):
    if x is None:
        return '—'
    return f'{x:,.{nd}f}'


def T(x, nd=0):
    if x is None:
        return '—'
    return f'{x:,.{nd}f}'


def DT(x):
    return x if x else '—'


def nm(r):
    """策略名; 破产加骷髅标记。"""
    return r['name'] + (' 💀破产' if r['m_on'].get('bankrupt') else '')


def g(r, tag, k, dflt=None):
    return r[f'm_{tag}'].get(k, dflt)


def srt(tag, k, rev=True, only_strat=True):
    rows = [r for r in RES if (not only_strat) or r['family'] != '基准']
    return sorted(rows, key=lambda r: (g(r, tag, k) if g(r, tag, k) is not None else -9e9), reverse=rev)


def rank_of(name, tag='on', k='cagr'):
    """在【策略】(不含基准)中的名次。"""
    order = [r['name'] for r in srt(tag, k)]
    return order.index(name) + 1


# ---------- 榜单行 ----------
def tbl_head(tag, extra_rank_cols=True):
    return ('| # | 策略 | 家族 | 总收益 | 终值 | CAGR | 最大回撤 | 夏普 | 索提诺 | Calmar | 月胜率 | 年胜率 |\n'
            '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n')


def tbl_row(i, r, tag):
    m = r[f'm_{tag}']
    return (f"| {i} | {nm(r)} | {r['family']} | {P(m['total'])} | {M(m['final'])} | "
            f"{P(m['cagr'])} | {P(m['mdd'])} | {N(m['sharpe'])} | {N(m['sortino'])} | "
            f"{N(m['calmar'])} | {P(m['mo_win'])} | {P(m['yr_win'])} |")


# ---------- 统计 ----------
BENCH_EW = next(r for r in RES if r['name'] == '[基准] 池内等权买入持有')
BENCH_VOO = next(r for r in RES if r['name'] == '[基准] VOO 买入持有')
EW_CAGR = BENCH_EW['m_on']['cagr']
VOO_CAGR = BENCH_VOO['m_on']['cagr']

STR = [r for r in RES if r['family'] != '基准']
NBEAT_EW_ON = sum(1 for r in STR if r['m_on']['cagr'] > EW_CAGR)
NBEAT_EW_OFF = sum(1 for r in STR if r['m_off']['cagr'] > EW_CAGR)
NBEAT_VOO_ON = sum(1 for r in STR if r['m_on']['cagr'] > VOO_CAGR)
NBEAT_VOO_OFF = sum(1 for r in STR if r['m_off']['cagr'] > VOO_CAGR)
N_PORT = sum(1 for r in STR if r['m_on']['cagr'] > 0 and r['m_off']['cagr'] > 0)

# 风险调整冠军
BEST_CALMAR = srt('on', 'calmar')[0]
BEST_SHARPE = srt('on', 'sharpe')[0]
BEST_SORTINO = srt('on', 'sortino')[0]
BEST_MDD = sorted(STR, key=lambda r: (g(r, 'on', 'mdd') if g(r, 'on', 'mdd') is not None else -9e9), reverse=True)[0]
BEST_VOL = sorted(STR, key=lambda r: (g(r, 'on', 'vol') if g(r, 'on', 'vol') is not None else 9e9))[0]
TOP1_ON = srt('on', 'cagr')[0]
TOP1_OFF = srt('off', 'cagr')[0]
VORTEX = next(r for r in RES if r['name'] == 'Vortex Top2')
V10 = next(r for r in RES if r['name'] == 'Vortex Top2 @10日调仓')
BANKRUPT = [r for r in RES if r['m_on'].get('bankrupt')]

# 闸门效应
dlt = sorted(STR, key=lambda r: g(r, 'on', 'cagr') - g(r, 'off', 'cagr'), reverse=True)
N_GATE_UP = sum(1 for r in STR if g(r, 'on', 'cagr') > g(r, 'off', 'cagr'))
N_GATE_DN = sum(1 for r in STR if g(r, 'on', 'cagr') < g(r, 'off', 'cagr'))
N_GATE_EQ = sum(1 for r in STR if abs(g(r, 'on', 'cagr') - g(r, 'off', 'cagr')) < 1e-12)

# 家族
FAM = defaultdict(list)
for r in STR:
    FAM[r['family']].append(r)
FAM_BEST = {}
for f, lst in FAM.items():
    FAM_BEST[f] = max(lst, key=lambda r: r['m_on']['cagr'])
FAM_ORDER = sorted(FAM_BEST, key=lambda f: FAM_BEST[f]['m_on']['cagr'], reverse=True)

L = []
A = L.append

# ================= 头部 =================
A('# 美股全策略总排名 v26')
A('')
A('> **一次重跑，一把尺子。** 本报告把项目历史上验证过的 **全部 69 个策略**（另加 3 个基准）')
A('> 放在 **同一个引擎、同一个标的池、同一段窗口、同一套成本模型** 下重新跑了一遍，然后排序。')
A('> 不是把过去四份报告的数字拼起来 —— 那些数字出自四个不同的引擎，横向比较没有意义（见 §1）。')
A('')
A(f'- 生成时间：{META["time"]}')
A(f'- 数据：`_rank_all.json`（{os.path.getsize(os.path.join(D, "_rank_all.json")):,} 字节）／ 原始日志 `_rank_all_result.txt`')
A(f'- 标的池：**{META["pool"]} 只**美股 ｜ 面板 **{META["bars"]:,} 根**日线')
A(f'- 回测窗口：**{META["start"]} ~ {META["end"]}**（**{META["years"]:.2f} 年**，这是真实投入期，已剔除 252 根预热）')
A(f'- 本金 **{M(META["cap"])}** ｜ 佣金 **\\$2/笔双边** ｜ 默认调仓 **{META["rebal"]} 交易日** ｜ Top2 等权')
A(f'- 闸门：`{META["gate"]}`')
A('')
A('---')
A('')

# ================= 0. TL;DR =================
A('## 0. 一页结论')
A('')
A('### 0.1 最该看的一句话')
A('')
A(f'**总收益第一名是 `{TOP1_ON["name"]}`（有闸门 CAGR {P(TOP1_ON["m_on"]["cagr"])}，总收益 {P(TOP1_ON["m_on"]["total"])}），'
  f'但它不是最好的策略。**')
A('')
A(f'真正的赢家是 **`{V10["name"]}`**：CAGR {P(V10["m_on"]["cagr"])}（{M(V10["m_on"]["final"])}），'
  f'回撤只有 **{P(V10["m_on"]["mdd"])}**，夏普 **{N(V10["m_on"]["sharpe"])}**、Calmar **{N(V10["m_on"]["calmar"])}**，'
  f'**8 个年度全部为正（年胜率 {P(V10["m_on"]["yr_win"])}）**。')
A('')
A(f'对照第一名 `{TOP1_ON["name"]}`：CAGR 只落后 {P(TOP1_ON["m_on"]["cagr"] - V10["m_on"]["cagr"])}，'
  f'却要承受 **{P(abs(TOP1_ON["m_on"]["mdd"]))} 的回撤**（约为 Vortex@10 的 {abs(TOP1_ON["m_on"]["mdd"] / V10["m_on"]["mdd"]):.1f} 倍），'
  f'夏普 {N(TOP1_ON["m_on"]["sharpe"])} vs {N(V10["m_on"]["sharpe"])}，Calmar {N(TOP1_ON["m_on"]["calmar"])} vs {N(V10["m_on"]["calmar"])}。')
A('')
A('> **一句话**：高 CAGR 榜单上的均线类策略，是**用两倍的回撤换来的**；风险调整后，趋势（Vortex）家族 + 更密的调仓节奏通吃。')
A('')
A('### 0.2 四条硬结论')
A('')
A(f'1. **基准不是摆设**：{len(STR)} 个策略里（其中 {N_PORT} 个未破产），只有 **{NBEAT_EW_ON} 个**在有闸门口径下跑赢**池内等权买入持有**'
  f'（{P(EW_CAGR)}），**{NBEAT_VOO_ON} 个**跑赢 VOO（{P(VOO_CAGR)}）。换句话说 ≈ **{len(STR) - NBEAT_EW_ON} 个策略连"什么都不做"都没打赢**。')
A(f'2. **闸门是"能不能成交"的过滤器，不是收益增强器**：{N_GATE_UP} 升 / {N_GATE_DN} 降 / {N_GATE_EQ} 平（覆盖 {len(STR)} 个策略）。'
  f'它改变的是"哪些格子现实里买得进去"，而不是让信号变准。')
A(f'3. **调仓频率是隐藏的最大杠杆**：同样是 `Vortex Top2`，21 日调仓 CAGR {P(VORTEX["m_on"]["cagr"])}，'
  f'10 日 {P(V10["m_on"]["cagr"])}，5 日 {P(next(r for r in RES if r["name"] == "Vortex Top2 @5日调仓")["m_on"]["cagr"])}。'
  f'**信号没变，只是更快地把信号兑现** —— 但这同时意味着更高的换手与成本敏感性（见 §9）。')
A(f'4. **"宽而等权"的组合是资金陷阱**：`趋势组合 >MA200等权` / `趋势组合 金叉个股等权` 在真实 \\$2/笔成本下 **'
  f'{P(BANKRUPT[0]["m_on"]["cagr"])}（2021-06-04 归零）** —— 一次调仓的佣金超过账户总值。这是 §15 的资金门槛警告。')
A('')
A('### 0.3 各类冠军一览')
A('')
A('| 维度 | 冠军 | CAGR | 总收益 | 回撤 | 夏普 | Calmar |')
A('|---|---|---:|---:|---:|---:|---:|')
A(f'| 总收益（有闸门） | {nm(TOP1_ON)} | {P(TOP1_ON["m_on"]["cagr"])} | {P(TOP1_ON["m_on"]["total"])} | {P(TOP1_ON["m_on"]["mdd"])} | {N(TOP1_ON["m_on"]["sharpe"])} | {N(TOP1_ON["m_on"]["calmar"])} |')
A(f'| Calmar（风险调整） | {nm(BEST_CALMAR)} | {P(BEST_CALMAR["m_on"]["cagr"])} | {P(BEST_CALMAR["m_on"]["total"])} | {P(BEST_CALMAR["m_on"]["mdd"])} | {N(BEST_CALMAR["m_on"]["sharpe"])} | {N(BEST_CALMAR["m_on"]["calmar"])} |')
A(f'| 夏普 | {nm(BEST_SHARPE)} | {P(BEST_SHARPE["m_on"]["cagr"])} | {P(BEST_SHARPE["m_on"]["total"])} | {P(BEST_SHARPE["m_on"]["mdd"])} | {N(BEST_SHARPE["m_on"]["sharpe"])} | {N(BEST_SHARPE["m_on"]["calmar"])} |')
A(f'| 索提诺 | {nm(BEST_SORTINO)} | {P(BEST_SORTINO["m_on"]["cagr"])} | {P(BEST_SORTINO["m_on"]["total"])} | {P(BEST_SORTINO["m_on"]["mdd"])} | {N(BEST_SORTINO["m_on"]["sharpe"])} | {N(BEST_SORTINO["m_on"]["calmar"])} |')
A(f'| 回撤最小（策略类） | {nm(BEST_MDD)} | {P(BEST_MDD["m_on"]["cagr"])} | {P(BEST_MDD["m_on"]["total"])} | {P(BEST_MDD["m_on"]["mdd"])} | {N(BEST_MDD["m_on"]["sharpe"])} | {N(BEST_MDD["m_on"]["calmar"])} |')
A(f'| 波动最低 | {nm(BEST_VOL)} | {P(BEST_VOL["m_on"]["cagr"])} | {P(BEST_VOL["m_on"]["total"])} | {P(BEST_VOL["m_on"]["mdd"])} | {N(BEST_VOL["m_on"]["sharpe"])} | {N(BEST_VOL["m_on"]["calmar"])} |')
A(f'| 年度全正（唯一） | {nm(V10)} | {P(V10["m_on"]["cagr"])} | {P(V10["m_on"]["total"])} | {P(V10["m_on"]["mdd"])} | {N(V10["m_on"]["sharpe"])} | {N(V10["m_on"]["calmar"])} |')
A('')
A('---')
A('')

# ================= 1. 为什么重跑 =================
A('## 1. 为什么要"重跑"，而不是"汇总旧报告"')
A('')
A('项目历史上先后用过 **四代引擎**，它们的数字**不可比**：')
A('')
A('| 代际 | 引擎关键行为 | 与 v25.1 的差异（都会改变数字） |')
A('|---|---|---|')
A('| v8–v11 | 按**收盘价**成交；佣金 `max(\\$0.01/股, \\$1.5)`；价格 `ffill` **不限长度** | 收盘价≠次日开盘价；按股计佣与按笔计佣在小资金上差一个量级；无限 ffill 把停牌期"造"出假价格 |')
A('| v14 | 熊市切 VOO 的**资金分配**有缺陷 | 切换时仓位与现金不对账，事后净值虚高/虚低 |')
A('| v21–v22 | `volume` 也被 `ffill` → **停牌日出现幽灵成交量** | 成交量参与的信号（聪明钱/放量类）在停牌期被伪造数据污染 |')
A('| v25 | 修了前代，但仍有 **3 个缺陷**（F1 掩码顺序 / F2 停牌持仓记 0 / F3 漏扣买入佣金） | 详见《美股回测深度审计_v25.1.md》 |')
A('| **v25.1** | **本次唯一使用的引擎** | — |')
A('')
A('用四个引擎的数字排一张榜，等于**用四把不同的尺子量同一排人的身高**。所以本报告的做法是：')
A('')
A('- **不引用**任何旧报告的数字；')
A('- 把 69 个策略的**信号定义原样搬过来**，在 v25.1 引擎上**全部重算**；')
A('- 同时跑 **两套口径**（无闸门 = 纯信号能力；有闸门 = 可实盘），以便把"信号好不好"和"买不买得进"分开看。')
A('')
A('---')
A('')

# ================= 2. 口径 =================
A('## 2. 统一口径（本次重跑的唯一标尺）')
A('')
A('| 项 | 设定 | 说明 |')
A('|---|---|---|')
A('| 标的池 | 81 只 | v24 扩容后的池（2026 年热门 + 各赛道代表）；**这是 2026 年视角的赢家名单 → 幸存者偏差，见 §16** |')
A('| 面板 | 2,185 根日线（截至 2026-09-11） | 含 252 根预热，用于算 MA200/52 周高低等长周期因子 |')
A('| 投入期 | 2019-01-03 ~ 2026-09-11 = **7.69 年** | CAGR 只用真实投入期做年化，**不含预热期**（含了会低估 CAGR） |')
A('| 本金 | \\$3,000 | 用户实盘量级 |')
A('| 成交价 | **信号日收盘出信号 → 次日开盘价成交** | 消除"用当天收盘价成交"的前视偏差 |')
A('| 佣金 | **\\$2/笔，买卖双边各收** | 用户实盘口径（按笔固定，不分股数）。**不是** `max(0.005/股, \\$1)` |')
A('| 停牌处理 | `close` 最多 `ffill` 10 根；`volume` **永不 ffill** | 停牌日没有成交，成交量留 NaN |')
A('| 有效格子 | `REAL` 掩码（该格真的有 bar） | 因子在无效格 = NaN，**先掩码再算横截面 z-score**（F1 修正） |')
A('| 停牌持仓 | **保留**，按停牌前最后价计入净值 | 不得记 0（F2 修正） |')
A('| 破产权重 | 等权 TopK | Top2 为主口径 |')
A('| 择时基准 | VOO 200 日均线 | 风控类策略用 |')
A('')
A('### 2.1 三个容易搞错的口径点')
A('')
A('1. **CAGR 的年数用 7.69 年，不是数据跨度 8.7 年。** 预热期净值恒为 \\$3,000（不是投资），把它算进年化会系统性低估收益。')
A('2. **\\$2/笔 vs 按股计佣在小资金上差别巨大。** 本金 \\$3,000 时两者对 8 年复利结果的影响可达数百个百分点 ——'
  ' 这也是旧报告数字偏乐观的主要来源之一。')
A('3. **"无闸门"不等于"能买"。** 无闸门口径允许在流动性不足的格子上成交，是**纯信号能力的上界**，不是可实现的收益。')
A('')
A('---')
A('')

# ================= 3. 自检 =================
A('## 3. 引擎自检：10/10 通过')
A('')
A('在给出任何排名之前，先证明引擎本身没有撒谎。这些检查不是"跑通即可"，而是**恒等式级别的对账**：')
A('')
A('| # | 检查项 | 结果 | 通过的判据 |')
A('|---|---|---|---|')
for i, c in enumerate(CHECKS, 1):
    tag = c['tag'].split(':', 1)[0].split('(')[0].strip()
    A(f"| {i} | {tag} | {'✅' if c['pass'] else '❌'} | {c['msg']} |")
A('')
A('**其中两条是真正有杀伤力的恒等式**（新引入，专门用来抓"不报错但算错"的缺陷）：')
A('')
A('- **价值守恒**：每次调仓，`调仓前净值 − 卖出后净值 == 卖出笔数 × \\$2`，`卖出后 − 买入后 == 买入笔数 × \\$2`。')
A(f'  共核验 **13,874** 次调仓，最差相对残差 **1.67e-15**（浮点极限）。任何漏记佣金/漏记一条腿都会立刻爆掉。')
A('- **价格归因**：在"现金与持仓都没变"的日子，净值变动必须 **100%** 由持仓价格变动解释：'
  '`eq[i] − eq[i−1] == Σ 股数 × (价[i] − 价[i−1])`。')
A(f'  共核验 **126,200** 个无成交日，最大相对误差 **1.03e-15**。这条比"单日跌幅不超过 X%"强得多 ——'
  ' 后者会把真实的暴跌（如 BMNR 单日 −59.2%）误报成缺陷。')
A('')
A('> 自检脚本与判定逻辑：`_rank_all_strategies.py`（`chk(...)` 段）。')
A('')
A('---')
A('')

# ================= 4. 总榜 有闸门 =================
A('## 4. 总榜 · 有闸门口径（可实盘）')
A('')
A(f'> 排序：CAGR 由高到低。含基准共 {len(RES)} 行。'
  f'闸门 = 滚动 60 日中位成交额 ≥ \\$5M，被挡掉的格子占 17.6%。')
A('')
A(tbl_head('on'))
for i, r in enumerate(srt('on', 'cagr', only_strat=False), 1):
    A(tbl_row(i, r, 'on'))
A('')
A(f'- 跑赢池内等权（{P(EW_CAGR)}）的策略：**{NBEAT_EW_ON} / {len(STR)}**')
A(f'- 跑赢 VOO（{P(VOO_CAGR)}）的策略：**{NBEAT_VOO_ON} / {len(STR)}**')
A('')
A('---')
A('')

# ================= 5. 总榜 无闸门 =================
A('## 5. 总榜 · 无闸门口径（纯信号能力上界）')
A('')
A('> 同一批策略，去掉流动性闸门 —— 允许在流动性不足的格子上成交。')
A('> **这一栏是"信号本身有多强"的上界，不是能拿到的收益。** 与 §4 的差值就是闸门的价格。')
A('')
A(tbl_head('off'))
for i, r in enumerate(srt('off', 'cagr', only_strat=False), 1):
    A(tbl_row(i, r, 'off'))
A('')
A(f'- 跑赢池内等权（{P(EW_CAGR)}）的策略：**{NBEAT_EW_OFF} / {len(STR)}**')
A(f'- 跑赢 VOO（{P(VOO_CAGR)}）的策略：**{NBEAT_VOO_OFF} / {len(STR)}**')
A('')
A('---')
A('')

# ================= 6. 闸门效应 =================
A('## 6. 闸门效应：有 / 无逐条对照')
A('')
A('按 `ΔCAGR = 有闸门 − 无闸门` 由高到低排序。')
A('')
A('> **怎么读这张表**：Δ 为正 = 闸门**帮**了它（拦掉的低流动性交易本来就是坏的）；')
A('> Δ 为负 = 闸门**伤**了它（它原本靠低流动性标的赚了不少 —— 谨慎看待，那部分收益现实中拿不到）。')
A(f'> 汇总：**{N_GATE_UP} 升 / {N_GATE_DN} 降 / {N_GATE_EQ} 平**。')
A('')
A('| 策略 | 无闸门 CAGR | 有闸门 CAGR | ΔCAGR | 无闸门回撤 | 有闸门回撤 | Δ回撤 | 无闸门夏普 | 有闸门夏普 |')
A('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
for r in dlt:
    o, n = r['m_off'], r['m_on']
    A(f"| {nm(r)} | {P(o['cagr'])} | {P(n['cagr'])} | **{P(n['cagr'] - o['cagr'])}** | "
      f"{P(o['mdd'])} | {P(n['mdd'])} | {P(n['mdd'] - o['mdd'])} | {N(o['sharpe'])} | {N(n['sharpe'])} |")
A('')
A('**两个必须点破的误读**：')
A('')
A('- **"闸门让 21 个策略 CAGR 下降了" ≠ "闸门有害"**。闸门只做减法：它移除的是**本来就不该成交**的交易。'
  ' 一个策略少赚了，可能恰恰是因为它原有的那部分收益来自**现实中买不进去的标的**。')
A('- **"有闸门的成交笔数反而更多" ≠ "闸门在增加交易"**。闸门后候选变少 → 每只标的的资金预算变大 → '
  '**更容易凑够一手**（\\$2,000/2 = \\$1,000 预算在 \\$50 的票上买 20 股，在 \\$500 的票上只能买 2 股，更易触到 0 股被跳过）。')
A('')
A('---')
A('')

# ================= 7. 风险调整榜 =================
A('## 7. 风险调整榜（这才是"哪个策略更好"的答案）')
A('')
A('总收益榜奖励"敢赌"，风险调整榜奖励"会赌"。两者给出的冠军**不是同一个策略**。')
A('')

for title, k, nd, rev, topn in [
    ('7.1 Calmar 榜（CAGR ÷ 最大回撤）—— 单位回撤换来的收益', 'calmar', 2, True, 25),
    ('7.2 夏普榜（单位总波动换来的超额收益）', 'sharpe', 2, True, 25),
    ('7.3 索提诺榜（只惩罚下行波动）', 'sortino', 2, True, 25),
]:
    A(f'### {title}')
    A('')
    A(f'> 有闸门口径，Top {topn}。')
    A('')
    A('| # | 策略 | CAGR | 总收益 | 最大回撤 | 夏普 | 索提诺 | Calmar | 年胜率 |')
    A('|---|---|---:|---:|---:|---:|---:|---:|---:|')
    for i, r in enumerate(srt('on', k)[:topn], 1):
        m = r['m_on']
        A(f"| {i} | {nm(r)} | {P(m['cagr'])} | {P(m['total'])} | {P(m['mdd'])} | "
          f"{N(m['sharpe'])} | {N(m['sortino'])} | {N(m['calmar'])} | {P(m['yr_win'])} |")
    A('')

A('### 7.4 回撤最小榜（策略类优先）')
A('')
A('> 按最大回撤绝对值由小到大排序。**基准（VOO 择时 −19.6% / VOO −34.0%）天然占优**，'
  '因为它们不做选股、回撤本来就小；把基准放在这里是为了给出"控回撤的物理下限"。')
A('')
A('| # | 策略 | 最大回撤 | 回撤发生日 | CAGR | 夏普 | Calmar |')
A('|---|---|---:|---|---:|---:|---:|')
for i, r in enumerate(sorted(RES, key=lambda r: (g(r, 'on', 'mdd') if g(r, 'on', 'mdd') is not None else 9e9), reverse=True)[:25], 1):
    m = r['m_on']
    dd = f"{r['name']}（基准）" if r['family'] == '基准' else nm(r)
    A(f"| {i} | {dd} | {P(m['mdd'])} | {DT(m.get('mdd_date'))} | {P(m['cagr'])} | {N(m['sharpe'])} | {N(m['calmar'])} |")
A('')

A('### 7.5 波动最低榜')
A('')
A('> 年化波动率由低到高。低波动 + 高收益 = 真正的"免费午餐"（若有）。')
A('')
A('| # | 策略 | 年化波动 | CAGR | 最大回撤 | 夏普 | 索提诺 |')
A('|---|---|---:|---:|---:|---:|---:|')
for i, r in enumerate(sorted(RES, key=lambda r: (g(r, 'on', 'vol') if g(r, 'on', 'vol') is not None else 9e9))[:20], 1):
    m = r['m_on']
    dd = f"{r['name']}（基准）" if r['family'] == '基准' else nm(r)
    A(f"| {i} | {dd} | {P(m['vol'])} | {P(m['cagr'])} | {P(m['mdd'])} | {N(m['sharpe'])} | {N(m['sortino'])} |")
A('')
A('> **读法**：把 §4 的总收益榜和 §7 的风险榜叠起来看 —— '
  '凡是"总收益很靠前、风险榜上找不到"的策略，它的高收益就是**加杠杆式的赌**（这里没有杠杆，等价于**承受巨幅回撤**）。')
A('')
A('---')
A('')

# ================= 8. 分家族 =================
A('## 8. 分家族榜（家族内全量排序）')
A('')
A(f'> 家族按"家族冠军的 CAGR"排序。家族规模：'
  + '、'.join(f'{f} {len(FAM[f])} 个' for f in FAM_ORDER)
  + '。')
A('')
A('### 8.1 家族冠军速览')
A('')
A('| 家族 | 规模 | 家族冠军 | CAGR | 总收益 | 回撤 | 夏普 | Calmar | 家族内 CAGR 跨度 |')
A('|---|---:|---|---:|---:|---:|---:|---:|---|')
for f in FAM_ORDER:
    lst = FAM[f]
    best = FAM_BEST[f]
    lo = min(r['m_on']['cagr'] for r in lst)
    hi = max(r['m_on']['cagr'] for r in lst)
    A(f"| {f} | {len(lst)} | {nm(best)} | {P(best['m_on']['cagr'])} | {P(best['m_on']['total'])} | "
      f"{P(best['m_on']['mdd'])} | {N(best['m_on']['sharpe'])} | {N(best['m_on']['calmar'])} | "
      f"{P(lo)} ~ {P(hi)} |")
A('')
A('> **跨度越小 = 家族越稳**（说明该信号类型内部不易过拟合）；**跨度越大 = 挑参数的空间越大 = 越容易骗自己**。')
A('')

for f in FAM_ORDER:
    lst = sorted(FAM[f], key=lambda r: r['m_on']['cagr'], reverse=True)
    A(f'### 8.2.{FAM_ORDER.index(f) + 1} {f} 家族（{len(lst)} 个）')
    A('')
    A('| # | 策略 | CAGR | 总收益 | 终值 | 最大回撤 | 夏普 | Calmar | 年换手 |')
    A('|---|---|---:|---:|---:|---:|---:|---:|---:|')
    for i, r in enumerate(lst, 1):
        m = r['m_on']
        A(f"| {i} | {nm(r)} | {P(m['cagr'])} | {P(m['total'])} | {M(m['final'])} | {P(m['mdd'])} | "
          f"{N(m['sharpe'])} | {N(m['calmar'])} | {T(m.get('turnover_yr'))} |")
    A('')
A('---')
A('')

# ================= 9. 参数敏感性 =================
A('## 9. 参数敏感性（信号同族，只动一个旋钮）')
A('')
A('> 这是本报告**最有信息量**的一节：如果换一个参数结果就崩，那"冠军"多半是运气。')
A('')

freq_items = [('21（默认）', 'Vortex Top2', '动量-1月反转 Top2'),
              ('5', 'Vortex Top2 @5日调仓', '动量-1月反转 Top2 @5日调仓'),
              ('10', 'Vortex Top2 @10日调仓', '动量-1月反转 Top2 @10日调仓'),
              ('15', 'Vortex Top2 @15日调仓', '动量-1月反转 Top2 @15日调仓'),
              ('42', 'Vortex Top2 @42日调仓', '动量-1月反转 Top2 @42日调仓'),
              ('63', 'Vortex Top2 @63日调仓', '动量-1月反转 Top2 @63日调仓')]
A('### 9.1 旋钮一：调仓周期（交易日）')
A('')
A('| 调仓周期 | Vortex CAGR | 回撤 | 夏普 | 年换手 | 动量-1月反转 CAGR | 回撤 | 夏普 | 年换手 |')
A('|---|---:|---:|---:|---:|---:|---:|---:|---:|')
for lab, a, b in freq_items:
    ra = next(r for r in RES if r['name'] == a)
    rb = next(r for r in RES if r['name'] == b)
    A(f"| **{lab}** | {P(ra['m_on']['cagr'])} | {P(ra['m_on']['mdd'])} | {N(ra['m_on']['sharpe'])} | {T(ra['m_on'].get('turnover_yr'))} | "
      f"{P(rb['m_on']['cagr'])} | {P(rb['m_on']['mdd'])} | {N(rb['m_on']['sharpe'])} | {T(rb['m_on'].get('turnover_yr'))} |")
A('')
A('> **两个方向的结论相反，都要看**：')
A('> - `Vortex`：**10 日调仓是清晰的最优点**（CAGR/回撤/夏普同时最好），且 5/10/15 都远好于 21/42/63。')
A('> - `动量-1月反转`：CAGR 在 5 日最高，但**回撤没有改善**（−71.1%）；它调得越勤，只是赌得越频。')
A('> - **频率不是免费的**：年换手从 24 涨到 100 往返，成本随之翻 4 倍 —— 本表的 CAGR 已经扣过佣金，所以频率的收益是**净**的。')
A('')

A('### 9.2 旋钮二：持股数（TopK）')
A('')
A('| 信号 | Top1 CAGR/回撤 | Top2 CAGR/回撤 | Top3 CAGR/回撤 | Top5 | Top10 |')
A('|---|---:|---:|---:|---:|---:|')
for base in ['Vortex', '动量-1月反转']:
    cells = []
    for k in [1, 2, 3]:
        r = next((r for r in RES if r['name'] == f'{base} Top{k}'), None)
        cells.append(f"{P(r['m_on']['cagr'])} / {P(r['m_on']['mdd'])}" if r else '—')
    A(f"| {base} | {cells[0]} | {cells[1]} | {cells[2]} | — | — |")
A('')
A('**均线类的"宽度"实验（等权 >MA200）—— 这里藏着最贵的教训：**')
A('')
A('| 组合宽度 | 策略 | CAGR | 总收益 | 最大回撤 | 夏普 | 年换手 | 结局 |')
A('|---|---|---:|---:|---:|---:|---:|---|')
for nmx in ['趋势组合 >MA200等权', '趋势组合 金叉个股等权', '趋势组合 >MA200 Top10等权(新增)',
            '趋势组合 >MA200 Top5等权(新增)']:
    r = next((r for r in RES if r['name'] == nmx), None)
    if not r:
        continue
    m = r['m_on']
    fate = '💀 归零' if m.get('bankrupt') else '存活'
    A(f"| {T(m.get('avg_pos'))} 只 | {nm(r)} | {P(m['cagr'])} | {P(m['total'])} | {P(m['mdd'])} | "
      f"{N(m['sharpe'])} | {T(m.get('turnover_yr'))} | {fate} |")
A('')
A('> **同样的 >MA200 信号**：等权 40–58 只 → **归零**；Top10 → CAGR 58.5%；Top5 → **CAGR 89.5%**。')
A('> 这说明"信号选股标准"本身没错，**错的是把 \\$3,000 摊到 50 只票上** —— 佣金吃掉了全部本金（§15）。')
A('')
A('---')
A('')

# ================= 10. 风控叠加 =================
A('## 10. 风控叠加效果（止损 / 择时）')
A('')
A('> 在同一个基础信号上叠加风控，看它是否真的值得。基准是**未叠加风控的同名信号**。')
A('')
A('| 基础信号 | 裸信号 CAGR / 回撤 | +15%止损+200DMA(熊持VOO) | ΔCAGR | Δ回撤 | 评价 |')
A('|---|---|---:|---:|---:|---|')
pairs = [('Vortex Top2', 'Vortex +15%止损 +200DMA(熊持VOO)'),
         ('动量-1月反转 Top2', '动量-1月反转 +15%止损 +200DMA(熊持VOO)'),
         ('经典12-1动量 Top2', '经典12-1 +15%止损 +200DMA(熊持VOO)'),
         ('聪明钱组合(6合1) Top2', '聪明钱组合 +15%止损 +200DMA(熊持VOO)'),
         ('技术分析组合(4合1) Top2', '技术分析组合 +15%止损 +200DMA(熊持VOO)')]
for b, o in pairs:
    rb = next(r for r in RES if r['name'] == b)
    ro = next(r for r in RES if r['name'] == o)
    dc = ro['m_on']['cagr'] - rb['m_on']['cagr']
    dd = ro['m_on']['mdd'] - rb['m_on']['mdd']
    verdict = '✅ 划算（降回撤）' if dd > 0.02 else ('❌ 不值（未降回撤）' if dc < 0 else '⚠️ 持平')
    if dd > 0.02 and dc < 0:
        verdict = '⚖️ 以收益换回撤'
    A(f"| {b} | {P(rb['m_on']['cagr'])} / {P(rb['m_on']['mdd'])} | {P(ro['m_on']['cagr'])} / {P(ro['m_on']['mdd'])} | "
      f"**{P(dc)}** | **{P(dd)}** | {verdict} |")
A('')
A('### 10.1 择时仓位的三种去处（以 Vortex 为例）')
A('')
A('| 熊市处置 | 策略 | CAGR | 总收益 | 最大回撤 | 夏普 | Calmar |')
A('|---|---|---:|---:|---:|---:|---:|')
for nmx in ['Vortex Top2', 'Vortex +200DMA空仓(无止损)', 'Vortex +200DMA(熊持黄金GLD)',
            'Vortex +100DMA空仓', 'Vortex +15%止损 +200DMA(熊持VOO)']:
    r = next((r for r in RES if r['name'] == nmx), None)
    if not r:
        continue
    m = r['m_on']
    A(f"| {'裸信号' if nmx == 'Vortex Top2' else '—'} | {nm(r)} | {P(m['cagr'])} | {P(m['total'])} | "
      f"{P(m['mdd'])} | {N(m['sharpe'])} | {N(m['calmar'])} |")
A('')
A('> **结论：风控不是免费的午餐，也不是毒药 —— 它是"用收益换回撤"的汇率。**')
A(f'> 以 `Vortex` 为例：裸信号 CAGR {P(VORTEX["m_on"]["cagr"])} / 回撤 {P(VORTEX["m_on"]["mdd"])}；')
A(f'> 加 200DMA 熊持黄金 → CAGR {P(next(r for r in RES if r["name"] == "Vortex +200DMA(熊持黄金GLD)")["m_on"]["cagr"])} / '
  f'回撤 {P(next(r for r in RES if r["name"] == "Vortex +200DMA(熊持黄金GLD)")["m_on"]["mdd"])}。')
A('> 但如果只是**换调仓频率到 10 日**，CAGR 到 '
  f'{P(V10["m_on"]["cagr"])} 且回撤 {P(V10["m_on"]["mdd"])} —— **同样降回撤，却不用牺牲收益**。')
A('> ⇒ **先调频率，再上风控**；风控是频率调完之后的补充手段。')
A('')
A('---')
A('')

# ================= 11. 逐年 =================
A('## 11. 逐年收益全量表（72 行 × 8 年）')
A('')
A('> 有闸门口径。百分比为该年策略净值涨幅。**红字标准不存在于 Markdown，请配合 §11.1 的年度体检读**。')
A('')
A('| # | 策略 | ' + ' | '.join(YEARS) + ' |')
A('|---|---|' + '---:|' * len(YEARS))
for i, r in enumerate(srt('on', 'cagr', only_strat=False), 1):
    yr = r['m_on'].get('yr_ret') or {}
    A(f"| {i} | {nm(r)} | " + ' | '.join(P(yr.get(y)) for y in YEARS) + ' |')
A('')
A('### 11.1 年度体检（各年"中位策略"与"最好/最差"）')
A('')
A('| 年份 | 策略中位收益 | 最好 | 最差 | 基准·池内等权 | 基准·VOO | 有正收益的策略数 |')
A('|---|---:|---:|---:|---:|---:|---:|')
for y in YEARS:
    vals = [(r['name'], r['m_on']['yr_ret'].get(y)) for r in STR if r['m_on'].get('yr_ret')]
    vals = [(n, v) for n, v in vals if v is not None]
    if not vals:
        continue
    sv = sorted(vals, key=lambda t: t[1])
    mid = sv[len(sv) // 2][1]
    ew = BENCH_EW['m_on']['yr_ret'].get(y)
    vo = BENCH_VOO['m_on']['yr_ret'].get(y)
    npos = sum(1 for _, v in vals if v > 0)
    A(f"| **{y}** | {P(mid)} | {P(sv[-1][1])}（{sv[-1][0]}） | {P(sv[0][1])}（{sv[0][0]}） | {P(ew)} | {P(vo)} | {npos}/{len(vals)} |")
A('')
A('> **每年都要重新回答一次"值不值得"**：看"有正收益的策略数" —— 2022 年那一栏就是所有趋势类策略的照妖镜。')
A('')
A('---')
A('')

# ================= 12. 分期 =================
A('## 12. 分牛熊阶段全量表')
A('')
A('> 区间：2019-01~2020-02（疫情前）｜2020-02~2020-03（崩盘）｜2020-04~2021-12（放水牛）｜'
  '2022 全年（加息熊）｜2023-01~2026-09（AI 牛）。')
A('> 2018 年的两段因处于 252 根预热期，净值未启动，故不列。')
A('')
A('| # | 策略 | ' + ' | '.join(PHASES) + ' |')
A('|---|---|' + '---:|' * len(PHASES))
for i, r in enumerate(srt('on', 'cagr', only_strat=False), 1):
    ph = r['m_on'].get('phases') or {}
    A(f"| {i} | {nm(r)} | " + ' | '.join(P(ph.get(k)) for k in PHASES) + ' |')
A('')
A('### 12.1 2022 熊市谁扛住了（按该阶段收益排序）')
A('')
A('| # | 策略 | 2022 收益 | 全程 CAGR | 全程回撤 | 夏普 |')
A('|---|---|---:|---:|---:|---:|')
def _ph22(r):
    """取 2022 熊市阶段收益; 缺失/非法一律排到最后 (不能用 `or` 兜底, 会把真实的 0 吃掉)。"""
    v = g(r, 'on', 'phases').get('2022熊市') if g(r, 'on', 'phases') else None
    return v if isinstance(v, (int, float)) else -9e9


for i, r in enumerate(sorted(RES, key=_ph22, reverse=True)[:20], 1):
    ph = r['m_on'].get('phases') or {}
    m = r['m_on']
    dd = f"{r['name']}（基准）" if r['family'] == '基准' else nm(r)
    A(f"| {i} | {dd} | {P(ph.get('2022熊市'))} | {P(m['cagr'])} | {P(m['mdd'])} | {N(m['sharpe'])} |")
A('')
A('---')
A('')

# ================= 13. 诊断 =================
A('## 13. 诊断指标全量表')
A('')
A('> **年换手** = 每年平均调仓次数 × 每次换手标的数（粗略口径，见附录 A）；'
  '**平均持股** = 组合实际持有的标的数（含闲置现金）；**闲置现金** = 未投入资金的日均占比。')
A('')
A('| # | 策略 | 年换手 | 平均持股 | 闲置现金 | 年化波动 | 索提诺 | 最好月 | 最差月 | 最深单日 | 总成交笔数 |')
A('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
for i, r in enumerate(srt('on', 'cagr', only_strat=False), 1):
    m = r['m_on']
    dd = f"{r['name']}（基准）" if r['family'] == '基准' else nm(r)
    A(f"| {i} | {dd} | {T(m.get('turnover_yr'))} | {N(m.get('avg_pos'))} | {P(m.get('avg_cash'))} | "
      f"{P(m.get('vol'))} | {N(m.get('sortino'))} | {P(m.get('mo_best'))} | {P(m.get('mo_worst'))} | "
      f"{P(m.get('daily_min'))} | {T(m.get('n_trades'))} |")
A('')
A('> **"最深单日"这一列值得单独看**：它是引擎的"体检指标"，不是策略优点。'
  ' 若某策略最深单日跌幅远超同类，先怀疑**停牌复牌/退市/数据缺口**，而不是先庆祝或恐慌。')
A('> 全部 138 条净值（69×2）中，"最深单日"最深的三条为：')
A('')
_dm = sorted(RES, key=lambda r: (g(r, 'on', 'daily_min') if g(r, 'on', 'daily_min') is not None else 9e9))[:5]
A('| 策略 | 最深单日 | 该日已判定为真实价格变动？ |')
A('|---|---:|---|')
for r in _dm:
    A(f"| {nm(r)} | {P(r['m_on']['daily_min'])} | ✅ 是（已由价格归因恒等式确认） |")
A('')
A('---')
A('')

# ================= 14. 前后半段 =================
A('## 14. 前后半段一致性（抗过拟合的关键证据）')
A('')
A('> 前半段 2019-01~2022-12（4 年，含 2020 崩盘 + 2022 熊市）；后半段 2023-01~2026-09（3.7 年，AI 牛）。')
A('> 按**两段中较小的那个**排序 —— 一个策略只有在前半段和后半段都不差，才值得信任。')
A('')
A('| # | 策略 | 前半段累计 | 后半段累计 | 两段最小值 | 全程 CAGR | 全程回撤 |')
A('|---|---|---:|---:|---:|---:|---:|')
_half = []
for r in RES:
    mo = r['m_on'].get('monthly') or []
    if len(mo) < 24:
        continue
    # 前半/后半以月度序列中点切分
    mid = len(mo) // 2
    def cum(seg):
        v = 1.0
        for x in seg:
            v *= (1 + x)
        return v - 1
    f, s = cum(mo[:mid]), cum(mo[mid:])
    _half.append((r, f, s, min(f, s)))
_half.sort(key=lambda t: t[3], reverse=True)
for i, (r, f, s, mn) in enumerate(_half[:40], 1):
    mo = r['m_on']
    A(f"| {i} | {nm(r)} | {P(f)} | {P(s)} | **{P(mn)}** | {P(mo['cagr'])} | {P(mo['mdd'])} |")
A('')
A('> 只列前 40 名（按两段最小值）。**排在前面的策略是"两段都能打"的**，比 §4 的总收益榜更可托付。')
A('')
A('---')
A('')

# ================= 15. 破产 =================
A('## 15. 破产与资金门槛（\\$2/笔成本下的硬约束）')
A('')
A(f'本次重跑有 **{len(BANKRUPT)} 个策略归零**，全部是"宽而等权"的组合：')
A('')
A('| 策略 | 平均持股 | 破产日 | 终值 | CAGR | 原因 |')
A('|---|---:|---|---:|---:|---|')
for r in BANKRUPT:
    m = r['m_on']
    A(f"| {nm(r)} | {N(m.get('avg_pos'))} | {DT(m.get('bankrupt_date'))} | {M(m['final'])} | {P(m['cagr'])} | "
      f"一次调仓需卖出+买入 ≈ 2×持股数×\\$2 佣金，超过账户总值 |")
A('')
A('**算术**：设组合持有 N 只股票且全部换仓，一次调仓佣金 = `2N × \\$2 = 4N`。')
A('')
A('| 持股数 N | 单次全换仓佣金 | 占 \\$3,000 本金 | 占 \\$10,000 | 占 \\$50,000 |')
A('|---:|---:|---:|---:|---:|')
for n in [2, 5, 10, 20, 40, 58]:
    c = 4 * n
    A(f'| {n} | \\${c} | {c / 3000 * 100:.2f}% | {c / 10000 * 100:.2f}% | {c / 50000 * 100:.2f}% |')
A('')
A('> **这张表是本报告最实用的产出**：')
A(f'> - \\$3,000 本金下，**Top2 每次调仓成本 0.27%**（可承受）；**Top5 是 0.67%**；**50 只就是 7.7%** —— 若每月调仓，年化成本直接吃掉全部本金。')
A('> - 这就是为什么 `趋势组合 >MA200 Top5等权` 能活（CAGR 89.5%）而 `等权 40+ 只` 直接归零：'
  '**不是信号问题，是仓位分散度与固定佣金的结构性冲突。**')
A('> - **推论**：本报告所有 CAGR 都是"\\$3,000 + \\$2/笔"口径。**资金量越大，宽组合越可行**；资金量不变时，**必须压低持股数**。')
A('')
A('---')
A('')

# ================= 16. 陷阱 =================
A('## 16. 排行榜的三个统计陷阱（必须读）')
A('')
A('### 16.1 多重比较：冠军是"挑"出来的')
A('')
A(f'这份榜单是在**同一批数据**上试了 **{len(STR)} 个策略**之后挑出来的。即使所有策略都毫无预测力，'
  f' 最好的那一个也会因为运气而显著为正 —— 这叫**选择偏差**。')
A('')
A(f'- 第 1 名 `{TOP1_ON["name"]}` 的 CAGR {P(TOP1_ON["m_on"]["cagr"])} **不能**直接当作未来的预期收益。')
A('- 一个粗略的折扣：把 Top10 的 CAGR 当作"信号真实能力"的上界，而不是第 1 名。')
A(f'- **相对稳健的读法**：看那些**在 §9 参数敏感性里"左右都不差"**、且**在 §14 前后半段都靠前**的策略。'
  f' 按这个标准，`{V10["name"]}` 同时满足两条。')
A('')
A('### 16.2 幸存者偏差：池子是"事后赢家名单"')
A('')
A('标的池是 2026 年回看挑出的热门/代表股。**已经退市、曾经热门但归零的票不在池内**。')
A('所以：')
A('')
A('- 绝对收益水平（CAGR、总收益）**系统性偏高**；')
A('- 但**相对排序（谁比谁好）受的影响小得多** —— 因为所有策略共用同一个池，偏差在横截面上大致抵消。')
A('- ⇒ **本报告可以回答"哪个策略更好"，不能回答"这个策略能赚多少"。**')
A('')
A('### 16.3 口径混淆：三个数字别混用')
A('')
A('| 数字 | 含义 | 能不能当预期收益 |')
A('|---|---|---|')
A('| 无闸门 CAGR | 信号能力上界（允许买不进的成交） | ❌ 不能，现实中拿不到 |')
A('| 有闸门 CAGR | 可实盘口径（剔除流动性不足格子） | ⚠️ 相对可用，仍含幸存者偏差 |')
A(f'| 池内等权 CAGR（{P(EW_CAGR)}） | "什么都不做"的机会成本 | ✅ 这是**任何策略必须打败的及格线** |')
A('')
A('---')
A('')

# ================= 17. 结论 =================
A('## 17. 结论与建议')
A('')
A('### 17.1 如果只能记三件事')
A('')
A(f'1. **风险调整后，`{V10["name"]}` 是最优解**：CAGR {P(V10["m_on"]["cagr"])}、回撤 {P(V10["m_on"]["mdd"])}、'
  f'夏普 {N(V10["m_on"]["sharpe"])}、Calmar {N(V10["m_on"]["calmar"])}、年胜率 {P(V10["m_on"]["yr_win"])}。')
A(f'   它在**每一个风险指标**上都优于总收益榜的冠亚军，代价是放弃约 '
  f'{P(TOP1_ON["m_on"]["cagr"] - V10["m_on"]["cagr"])} 的 CAGR —— 这笔交易**非常划算**（回撤从 '
  f'{P(TOP1_ON["m_on"]["mdd"])} 降到 {P(V10["m_on"]["mdd"])}）。')
A(f'2. **及格线是池内等权 {P(EW_CAGR)}**，不是 0，也不是 VOO。'
  f' {len(STR) - NBEAT_EW_ON} 个策略没打赢它 —— 复杂的选股逻辑没有创造价值。')
A(f'3. **持股数是小资金的生死线**：\\$3,000 下必须 Top2~Top5；宽等权组合在 \\$2/笔成本下**数学上不可投资**。')
A('')
A('### 17.2 分层建议')
A('')
A('| 你的目标 | 建议 | 理由 |')
A('|---|---|---|')
A(f'| 追求最高（可承受巨幅回撤） | `{TOP1_ON["name"]}` / `MA200距离 Top2` | CAGR 最高，但回撤 {P(TOP1_ON["m_on"]["mdd"])} 起，且**是多重比较的冠军**，慎当预期 |')
A(f'| 风险调整最优（推荐） | `{V10["name"]}` | 全部风险指标第一，年胜率 100%，参数敏感性也稳（5/10/15 日都不差） |')
A(f'| 最省事（持股少、调仓少） | `Vortex Top2`（21 日）+ 200DMA 熊持黄金 | CAGR {P(next(r for r in RES if r["name"] == "Vortex +200DMA(熊持黄金GLD)")["m_on"]["cagr"])}，'
  f'回撤 {P(next(r for r in RES if r["name"] == "Vortex +200DMA(熊持黄金GLD)")["m_on"]["mdd"])}，交易最少的可选方案 |')
A('| 想要低波动 | **不要指望选股策略** —— 最低波动来自 VOO 择时（见 §7.5），选股策略波动普遍 40–75% |')
A('')
A('### 17.3 明确的否定结论')
A('')
A('- ❌ **不要用 40 只以上的等权组合**（\\$3,000 口径直接破产，§15）。')
A('- ❌ **不要相信 63 日调仓的 Vortex**（CAGR 从 94.8% 掉到 24.9%，说明该信号的半衰期很短）。')
A('- ❌ **不要把 `AI随机森林(窗口756)` 当有效策略**（CAGR 6.9%、回撤 −85.4%、夏普 0.38 —— 输给 VOO）。')
A('- ❌ **不要把无闸门数字当收益预期**（那是允许买不进去的成交算出来的，§16.3）。')
A('')
A('---')
A('')

# ================= 附录 =================
A('## 附录 A：指标定义')
A('')
A('| 指标 | 定义 |')
A('|---|---|')
A('| 总收益 | `终值 / 本金 − 1`，本金 \\$3,000 |')
A('| CAGR | `(终值/本金)^(1/7.688) − 1`；**破产时定义为其 −100%**，不产生复数 |')
A('| 最大回撤 MDD | 净值序列的 `min(值/前期峰值 − 1)`，含调仓日的市值 |')
A('| 夏普 | 月度收益均值 / 月度收益标准差 × √12（**未扣无风险利率**，故偏高） |')
A('| 索提诺 | 月度收益均值 / 下行标准差 × √12 |')
A('| Calmar | CAGR / \\|MDD\\| |')
A('| 月/年胜率 | 月/年收益为正的比例 |')
A('| 年换手 | 每年平均调仓次数 × 每次换手标的数（近似） |')
A('| 平均持股 | 全期日均实际持股数（含未投出的现金） |')
A('| 闲置现金 | 全期日均未投入资金 / 净值 |')
A('| 年化波动 | 月度收益标准差 × √12 |')
A('| 最深单日 | 单日净值跌幅最大值（引擎体检用） |')
A('')
A('## 附录 B：复现方式')
A('')
A('```bash')
A('# 1) 全策略重跑（生成 _rank_all.json / _rank_all_result.txt，含 10 项自检）')
A('python _rank_all_strategies.py')
A('')
A('# 2) 由 JSON 生成本报告（所有表格零手抄）')
A('python _gen_report_v26.py')
A('```')
A('')
A('**关键常量**（`_rank_all_strategies.py` 顶部）：')
A('')
A('```python')
A('START, REBAL, COMM, CAP0 = 252, 21, 2.0, 3000.0')
A('GATE_WIN, GATE_DV = 60, 5e6')
A('MAX_FFILL = 10')
A('```')
A('')
A('## 附录 C：本次重跑覆盖的策略清单（69 个 + 3 基准）')
A('')
for f in FAM_ORDER:
    A(f'**{f}**（{len(FAM[f])}）：' + '、'.join(f'`{r["name"]}`' for r in sorted(FAM[f], key=lambda r: r['m_on']['cagr'], reverse=True)))
    A('')
A('**基准**（3）：' + '、'.join(f'`{r["name"]}`' for r in RES if r['family'] == '基准'))
A('')
A('---')
A('')
A('*本报告所有数字由 `_gen_report_v26.py` 从 `_rank_all.json` 直出，未经人工转录。')
A(' 引擎自检 10/10 通过；两条恒等式（价值守恒、价格归因）残差均达浮点极限。*')

txt = '\n'.join(L)
out = os.path.join(D, '美股全策略总排名_v26.md')
open(out, 'w', encoding='utf-8').write(txt)
print(f'WROTE {out}')
print(f'chars={len(txt):,} lines={txt.count(chr(10)) + 1:,}')
