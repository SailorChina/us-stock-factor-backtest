# -*- coding: utf-8 -*-
"""
美股因子策略 · 一键下单助手 (v25.1 审计修复版)

用法:
    python _update_signal.py                     # 刷新行情 + 出完整下单清单
    python _update_signal.py --no-fetch          # 只出信号(不联网)
    python _update_signal.py --self-test         # 自检: 跑全部断言
    python _update_signal.py --capital 3000      # 指定本金(美元)
    python _update_signal.py --cny 10000 --fx 6.71
    python _update_signal.py --topk 3 --strategy 动量-1月反转
    python _update_signal.py --positions META:1,BE:2   # 告知实际持仓, 算真实盈亏
    python _update_signal.py --min-dv 1e7        # 放宽/收紧流动性闸门(美元)
    python _update_signal.py --no-gate           # 关闭闸门(复现旧口径, 仅用于对比)

退出码: 0 正常 / 2 数据不可用(勿下单)

v25.1 审计修复 —— 三处"不报错但算错"的缺陷(详见 美股回测深度审计_v25.1.md):
  F1 [严重] 【成交量被 ffill】是语义错误: 停牌日没有成交, 成交量应当是空的, 旧写法却把它
     填成前一天的值 -> 闸门 (收盘价 x 成交量) 在停牌后的 10 个交易日里看到的是
     "前一天的成交额" -> 把停牌票判成"可交易"。实测后果: 2022-03 买入了已停牌的 NBIS。
     修法: volume 不再 ffill; 新增 REAL 掩码("该格当天是否真有 bar"), 无 bar 的日子
     因子一律置 NaN。(闸门开启时 REAL 是冗余的 —— trade 为 True 必然 REAL 也为 True,
     它保护的是 --no-gate 这条对比路径, 以及将来放宽阈值后的边界。)
  F2 [严重] 【回测引擎卖不出去的持仓被凭空抹掉】: 调仓时若某持仓当日开盘价不可得,
     旧引擎跳过入账却仍然清空持仓表 -> 仓位价值既不进现金也不进净值, 直接消失。
     实测后果: 反转策略在 2022-04-05 出现【假的 -34.6% 单日暴跌】, 终值被低估 61%
     (CAGR 45.4% -> 54.7%)。修法: 卖不掉的持仓保留, 下个调仓日再试。
  F3 [严重] 【买入侧佣金从未扣除】: bud=(cash-topk*comm)/topk 只把佣金"预留"出来,
     真下单时写的是 cash -= sh*pr, 少扣了那笔 comm -> 每次调仓账上恰好残留 topk*$2,
     等于只收了卖出那一半。实测: 93/93 次调仓各少扣 $4; 本金 $500 时终值虚高 34.5%。
  (F2/F3 位于独立回测引擎 _liquidity_gate_v25.py / _verify_gate.py; 本脚本的 [4]/[5] 段
   佣金计算与下单清单本身正确, 不受影响 —— 但历史回测结论必须用修正后的引擎重算。)

v25 变更 —— 流动性闸门(堵住"假价格"污染):
  E1 新增 tradable_mask(): 只有【滚动 60 个交易日的中位成交额 >= $5M】的标的
     才认为"该日可交易", 否则该日因子值置 NaN, 不参与横截面排名。
     动机: 池子里存在三类"价格是假的"标的 —— 粉单壳股(BMNR, 685 天里 349 天
     中位成交额 < $1M)、长期停牌(Yandex 系 NBIS 缺 664 个交易日)、
     SPAC 躺平期(7 只贴在 $10 不动)。它们的共同后果是【波动率 ≈ 0】,
     而反转类因子的 pct(close,21) 在横盘时恰好 = 0 -> 横截面 z-score 反而偏高
     -> 策略会主动去选这些根本没法成交的票。这类错误不抛异常, 只让回测悄悄变好看。
  E2 闸门只用到【当日及之前】的滚动窗口, 无前视; 有 min_periods=60 的预热期,
     停牌复牌后要重新攒满 60 个有效日才恢复可交易。
  E3 横截面 z-score 在闸门【之后】计算 -> 均值/标准差只由可真成交的标的决定,
     不会被躺平票的低波动稀释。
  E4 新增 variant 标识并计入历史去重键 —— 闸门开关会改信号, 若去重键不含它,
     就会重演 v24 那个"静默覆盖旧记录"的坑。键 =
     (日期, 策略, TopK, 池子规模, 变体)。
  E5 自检新增 7 条闸门断言(合成僵尸票必被挡 / 无前视 / 阈值单调 /
     闸门关=复现旧口径 / 变体变更不覆盖历史 / 无 variant 列的旧表兼容)。

v24 变更 —— 股票池扩容后的可追溯性:
  D1 signal_snapshot.json 新增 pool_size / pool_codes: 池子变了信号就会变,
     不记录池子成分, 事后无法解释"同一天为什么算出两个不同结果"。
  D2 signal_history.csv 的去重键从 (日期,策略,TopK) 改为
     (日期,策略,TopK,池子规模), 并抽出 hist_merge() 单独测试。
     旧行为会把"扩池前"的记录静默覆盖 —— 实测发生过: 37 只池的 META,BE
     被 81 只池的 SWKS,META 顶掉, 历史里查不到旧信号了。
  D3 自检新增 4 条历史表断言(同池去重 / 跨池共存 / 旧记录可查 / 旧格式兼容)。

v22 变更 (相对 v19) —— 选股层与资金层结构性隔离:
  C1 选股逻辑抽成 select() 函数, 只接受 (信号, 行号, 合格池, 持股数) 四个参数,
     不接收也读不到本金/净值/佣金 -> 资金无法倒灌选股。
  C2 自检新增 3 条断言: 选股源码不含资金变量 / 选股对 $0.01~$1e12 任意本金不变 /
     函数签名无资金参数。
  C3 持股数 TopK 口径更正: TopK 由【信号本身】的横截面表现决定, 与本金无关;
     本金只影响同一笔交易的成本占比。实证见 _capital_invariance_v22b.py。
  C4 [4] 段显式打印"选股与本金无关", 避免把回测金额误读成选股标准。

v19 修复 (相对 v17):
  B1 次新股被 ffill 补齐参与截面排名 -> 面板改用 limit 填充, 加上市时长闸门
  B2 额度不足静默拉不全            -> 先查额度, 拉后校验覆盖率, 不足则退出码 2
  B3 新鲜度用日历日误判(周末)      -> 改用美股交易日 + 休市日历
  B4 夏令时硬编码                  -> 自动计算 DST, 输出正确开盘时间
  B5 未判断今天是否交易日          -> 内置 2026-2027 休市/半日市日历
  B6 无 T+1 结算提示               -> 现金账户警告 + 下单顺序建议
  B7 闲置现金无建议                -> 给出处理方案
  B8 无持久化                      -> 输出 signal_snapshot.json + 追加 signal_history.csv
  B9 极端跳变未标记                -> 自动标记近 30 日单日 >50% 的票
  B10 无自检                       -> --self-test 全链路断言
"""
import os, sys, json, time, tempfile, datetime, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
SNAP = os.path.join(BASE, "signal_snapshot.json")
HIST = os.path.join(BASE, "signal_history.csv")

REBAL = 21          # 月度调仓(交易日)
START = 252         # 预热根数
COMM = 2.0          # 富途: 买 $2/笔 + 卖 $2/笔
MIN_HIST = 253      # 参与排名所需最少真实历史(252日动量)
MAX_FFILL = 10      # 面板最多向前填充 10 根(防止上市前被假价格补齐)
STALE_DAYS = 4      # 数据超过几个日历日未更新即告警
GATE_WIN = 60       # v25 流动性闸门: 滚动窗口(交易日)
GATE_DV = 5e6       # v25 流动性闸门: 中位成交额门槛(美元)

# ==================== 参数 ====================
def arg(name, default=None, cast=str):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv) and not sys.argv[i+1].startswith("--"):
            return cast(sys.argv[i+1])
    return default

CAP0 = arg("--capital", None, float)
CNY = arg("--cny", None, float)
FX = arg("--fx", 6.7092, float)
if CAP0 is None:
    CAP0 = (CNY or 10000.0) / FX
TOPK = arg("--topk", 2, int)
STRAT = arg("--strategy", "Vortex", str)
# v25 流动性闸门: 默认开启。变体标识会写进快照与历史表 —— 闸门开关会改信号,
# 不记录"这份信号是用哪套口径算的", 事后就没法解释同一天为什么有两个结果。
MIN_DV = arg("--min-dv", GATE_DV, float)
USE_GATE = ("--no-gate" not in sys.argv) and MIN_DV > 0
VARIANT = f"gate{MIN_DV/1e6:g}M" if USE_GATE else "nogate"
def parse_positions(s):
    """CODE:股数[,CODE:股数] -> dict, 带格式校验"""
    out = {}
    for kv in s.split(","):
        kv = kv.strip()
        if ":" not in kv:
            raise SystemExit(f"  格式错误: '{kv}' —— 应为 CODE:股数 (如 META:1.15,BE:2.70)")
        c, q = kv.split(":", 1)
        try:
            out[c.strip().upper()] = float(q)
        except ValueError:
            raise SystemExit(f"  股数不是数字: '{q}' (来自 '{kv}')")
    return out

def parse_bought(s):
    """CODE:股数@成本价[,...] -> dict"""
    out = {}
    for kv in s.split(","):
        kv = kv.strip()
        if "@" not in kv or ":" not in kv:
            raise SystemExit(f"  格式错误: '{kv}' —— 应为 CODE:股数@成交价 (如 META:1.15@648.03)")
        cq, pr = kv.split("@", 1)
        c, q = cq.split(":", 1)
        try:
            out[c.strip().upper()] = {"shares": float(q), "price": float(pr)}
        except ValueError:
            raise SystemExit(f"  成交记录数值不合法: '{kv}'")
    return out

POSITIONS = {}
COSTBASIS = {}
PORTFILE = os.path.join(BASE, "portfolio.json")
_p = arg("--positions", None, str)
if _p:
    POSITIONS = parse_positions(_p)
else:
    if os.path.exists(PORTFILE):
        try:
            sh = json.load(open(PORTFILE, encoding="utf-8")).get("shares", {})
            POSITIONS = {k: float(v["shares"] if isinstance(v, dict) else v) for k, v in sh.items()}
            COSTBASIS = {k: float(v.get("price", np.nan)) for k, v in sh.items() if isinstance(v, dict)}
        except Exception as e:
            print(f"  ⚠ 读取 portfolio.json 失败: {e}")
            POSITIONS = {}
BOUGHT = arg("--bought", None, str)   # META:1.1467@648.03,BE:2.707@275.75

# ==================== 美股日历 ====================
def nth_weekday(y, m, wd, n):
    d = datetime.date(y, m, 1)
    d += datetime.timedelta(days=(wd - d.weekday()) % 7 + 7 * (n - 1))
    return d

def is_dst(d):
    """美国夏令时: 3月第二个周日 ~ 11月第一个周日"""
    s = nth_weekday(d.year, 3, 6, 2)      # 周日
    e = nth_weekday(d.year, 11, 6, 1)
    return s <= d < e

def open_time(d):
    """返回常规时段开盘的北京时间字符串"""
    return "21:30" if is_dst(d) else "22:30"

def to_et(bj_dt):
    """北京时间 -> 美东时间 (夏令时 -12h, 冬令时 -13h)"""
    off = 12 if is_dst(bj_dt.date()) else 13
    return bj_dt - datetime.timedelta(hours=off)

def us_phase(bj_now=None):
    """当前美股时段: closed / pre / regular / post"""
    et = to_et(bj_now or datetime.datetime.now())
    if not is_trading_day(et.date()):
        return "closed"
    t = et.hour + et.minute / 60.0
    if 4.0 <= t < 9.5:  return "pre"
    if 9.5 <= t < 16.0: return "regular"
    if 16.0 <= t < 20.0: return "post"
    return "closed"

def bar_is_partial(last_date, bj_now=None):
    """最后一根 bar 是否可能是【盘中未完成快照】(美东当前时刻仍在该日盘中)"""
    et = to_et(bj_now or datetime.datetime.now())
    return et.date() == last_date and 9.5 <= et.hour + et.minute / 60.0 < 16.0

def project_trading_days(d, n):
    """从 d 起往后推 n 个交易日 (用于推算尚未到达的调仓日)"""
    cur = d
    for _ in range(n):
        cur = next_trading_day(cur)
    return cur

HOLIDAYS = {
    2026: ["01-01","01-19","02-16","04-03","05-25","06-19","07-03","09-07","11-26","12-25"],
    2027: ["01-01","01-18","02-15","03-26","05-31","06-18","07-05","09-06","11-25","12-24"],
}
HALF_DAYS = {2026: ["11-27","12-24"], 2027: ["11-26"]}

def is_trading_day(d):
    if d.weekday() >= 5: return False
    if d.strftime("%m-%d") in HOLIDAYS.get(d.year, []): return False
    return True

def next_trading_day(d, inclusive=False):
    if inclusive and is_trading_day(d): return d
    d = d + datetime.timedelta(days=1)
    while not is_trading_day(d):
        d += datetime.timedelta(days=1)
    return d

# ==================== 标的池 ====================
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
try:
    mi = json.load(open(os.path.join(BASE, "market_info.json"), encoding="utf-8"))
    fetched = json.load(open(os.path.join(BASE, "fetched_codes.json"), encoding="utf-8"))
except Exception as e:
    raise SystemExit(f"无法读取标的池定义文件 (market_info.json / fetched_codes.json): {e}\n"
                     f"   这两个文件定义了 37 只标的池, 缺失则脚本无法运行。")
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

def load(codes, limit=MAX_FFILL):
    """limit=有限向前填充: 只补临时停牌, 不把上市前补成假价格。

    v25.1 修复: 成交量【不做】ffill, 并额外返回 REAL 掩码(该格当天是否真有 bar)。

    为什么成交量的 ffill 是错的: 停牌日的成交量是"没有成交", 不是"前一天的成交量"。
    旧写法把它填成前一天的值, 于是闸门算 close x volume 时在停牌后的 10 个交易日里
    看到的是"前一天的成交额" -> 把停牌票判成可交易。实测: 2022-03 买入了已停牌的 NBIS,
    随后那个仓位在净值上砸出一根假的 -34.6% 断崖(见 _audit_v25.py 的 C3/C11)。
    """
    p = {}
    for c in codes:
        d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").drop_duplicates("time_key", keep="last").set_index("time_key")
    ad = sorted(set().union(*[set(x.index) for x in p.values()])); dt = pd.to_datetime(ad)
    out = {}
    for k in ["open","high","low","close","volume"]:
        m = pd.DataFrame({c: p[c][k].reindex(dt) for c in codes})
        # volume: 没有 bar 就是没有成交 -> 保持空值, 不填充
        out[k] = m if k == "volume" else m.ffill(limit=limit)
    REAL = pd.DataFrame({c: p[c]["close"].reindex(dt).notna() for c in codes})
    return dt, out, REAL

# ==================== 拉取 ====================
def fetch_latest():
    _T = os.path.join(tempfile.gettempdir(), "futu_log_upd"); os.makedirs(_T, exist_ok=True)
    os.environ["APPDATA"] = _T
    sys.path.insert(0, r"C:/Users/sailor/.workbuddy/skills/futuapi/scripts")
    from common import create_quote_context, safe_close
    from futu import SubType, AuType, SysConfig
    SysConfig.set_all_thread_daemon(True)
    ctx = create_quote_context()
    _, q = ctx.get_history_kl_quota(get_detail=False)
    rem = q[1] if isinstance(q, (list, tuple)) else -1
    print(f"  历史K线剩余额度: {rem}  (30 天内已拉过的标的重复请求不计费, 故小额度通常仍可全量刷新)")
    today = pd.Timestamp.today().normalize()
    start = (today - pd.Timedelta(days=45)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    ok_n = 0
    for code in UNI + ["US.VOO"]:
        out = ctx.request_history_kline(code, start=start, end=end, ktype=SubType.K_DAY,
                                        autype=AuType.QFQ, max_count=90)
        if out[0] != 0 or out[1] is None or len(out[1]) == 0:
            print(f"  FAIL {code} ret={out[0]}"); time.sleep(1.0); continue
        df = out[1][["time_key","open","close","high","low","volume"]].copy()
        df["time_key"] = pd.to_datetime(df["time_key"])
        p = os.path.join(LONGDIR, code.replace(".", "_") + ".csv")
        old = pd.read_csv(p); old["time_key"] = pd.to_datetime(old["time_key"])
        m = (pd.concat([old, df], ignore_index=True)
             .drop_duplicates("time_key", keep="last").sort_values("time_key").reset_index(drop=True))
        m.to_csv(p, index=False)
        ok_n += 1
        time.sleep(0.35)
    safe_close(ctx)
    ratio = ok_n / (len(UNI) + 1)
    print(f"  已刷新 {ok_n}/{len(UNI)+1} 只")
    if ratio >= 0.95:
        return True
    # 部分失败: 只有"信号相关标的"齐全才可用
    print(f"  ⚠ 刷新不完整({ok_n}/{len(UNI)+1}) —— 半份数据会让信号失真")
    return ratio >= 0.9

# ==================== 信号 ====================
def zs(x): return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())

def build_signals(PX, trade=None, real=None):
    """trade: bool 面板, True 表示该标的该日可交易; None 表示不启用闸门。
    real : bool 面板, True 表示该日该标的有【真实 bar】; None 表示不做这层检查。

    闸门必须在【横截面标准化之前】施加: zs() 的均值/标准差是按行(横截面)算的,
    若把躺平壳股留在里面, 它们"恰好为 0"的收益会拉低标准差、垫高别人,
    等于让僵尸票参与了"什么算好"的定义。先置 NaN, 它们就被彻底移出横截面。

    v25.1: 再叠一层 REAL —— 没有 bar 的日子不可能成交, 因子在那里没有意义。
    自检里有一条断言证明"闸门开启时 trade ⊆ REAL", 所以这层在默认口径下不改变结果;
    它的作用是保护 --no-gate 对比路径不被假数据污染。
    """
    C, O, H, L = PX["close"], PX["open"], PX["high"], PX["low"]
    mom = C.shift(21) / C.shift(252) - 1.0
    rev = C / C.shift(21) - 1.0
    V = vortex(H, L, C)
    valid = trade
    if real is not None:
        valid = real if valid is None else (valid & real)
    if valid is not None:
        V, mom, rev = V.where(valid), mom.where(valid), rev.where(valid)
    return {"Vortex": V, "动量-1月反转": (zs(mom) - zs(rev)) / 2.0,
            "动量12-1": mom}

def tradable_mask(PX, min_dv=None, win=GATE_WIN):
    """v25 流动性闸门 —— 判断"某标的在某日到底能不能真的买卖"。

    判据: 该日【及之前】win 个交易日的成交额(收盘价 x 成交量)中位数 >= min_dv。

    为什么用"成交额"而不是"成交量":
      一只 $10 的壳股成交 1 万股(= $10 万) 与一只 $500 的票成交 1 万股(= $500 万)
      流动性天差地别, 只有金额可比。成交量大小本身说明不了问题。

    为什么用"中位数"而不是"均值":
      均值会被单日天量拉高 —— 壳股偶尔放量一天就能骗过均值;
      中位数要求"半数以上的日子都活跃", 这才叫"能进能出"。

    为什么 min_periods=win 强制预热:
      停牌复牌后必须重新攒满 win 个有效日, 否则复牌首日就会被当成"可交易",
      而它的前 win 日窗口里全是停牌空洞。

    无前视: rolling 默认只用【当日及之前】的窗口, 不含未来。

    v25.1 修复: 成交量取自【未填充】的原始面板。旧写法对 volume 也做 ffill(limit=10),
    于是停牌开始后的 10 个交易日里 dv 仍等于"停牌前那天的成交额" -> 闸门看不见停牌。
    实测后果: 2022-03 买入已停牌的 NBIS, 在净值上砸出假的 -34.6% 断崖。
    """
    dv = PX["close"] * PX["volume"]
    med = dv.rolling(win, min_periods=win).median()
    return med >= (GATE_DV if min_dv is None else min_dv), med

# ==================== 选股层（与资金完全无关）====================
def select(A, i, good, topk):
    """
    【铁律 v22】选股层禁止接触本金 / 净值 / 佣金 / 汇率 / 股数。
    资金量只决定"每只买多少股", 绝不决定"买哪只票"。

    输入只有 4 样东西, 没有一个是钱:
      A     : 因子得分矩阵 (T 日收盘可得)
      i     : 取第 i 行 (当前决策日)
      good  : 历史长度合格的候选池
      topk  : 持股数 —— 这是【策略参数】, 由信号本身的横截面表现决定,
              不由账户大小决定 (见 _capital_invariance_v22b.py: 零成本下
              Vortex 最优 k=2 CAGR 89.1% vs k=3 69.3%, 换任何本金排名不变)。

    排序 = 纯因子得分降序。没有任何"价格太高买不起就跳过"之类的分支 ——
    那种分支会让回测里的"Top2"退化成"Top2 里买得起的那几只", 是典型的
    资金倒灌选股, 必须杜绝。
    """
    row = A.values[i] if hasattr(A, "values") else A.iloc[i].values
    fin = np.isfinite(row)
    elig = np.array([c in good for c in UNI])
    idx = np.where(fin & elig)[0]
    if len(idx) == 0:
        return []
    return list(idx[np.argsort(-row[idx])][:topk])

# ==================== 主流程 ====================
def main():
    ok = True
    if "--no-fetch" not in sys.argv:
        print("=" * 116); print("[1] 刷新行情"); print("=" * 116)
        try:
            if not fetch_latest():
                ok = False
                print("  ⚠ 数据未更新, 以下结果基于本地数据, 请谨慎")
        except Exception as e:
            print(f"  拉取异常(用本地数据继续): {type(e).__name__}: {e}")
            ok = False

    dates, PX, REAL = load(UNI)
    C, O, V_, VOL = PX["close"], PX["open"], PX["volume"], PX["volume"]
    N, S = C.shape; dp = pd.to_datetime(dates)
    TRADE = MED = None
    if USE_GATE:
        TRADE, MED = tradable_mask(PX, MIN_DV)
    SIG = build_signals(PX, TRADE, REAL)

    print("\n" + "=" * 116); print("[2] 数据体检"); print("=" * 116)
    today = datetime.date.today()
    last_d = dp[-1].date()
    lag_days = (today - last_d).days
    lag_td = sum(1 for i in range(lag_days) if is_trading_day(last_d + datetime.timedelta(days=i+1)))
    print(f"  最后交易日: {last_d}   面板 {N} 根 x {S} 只")
    print(f"  按【交易日】计落后 {lag_td} 个交易日 (日历日 {lag_days} 天)")
    # 未完成 bar 检测: 盘中拉的 bar 有价有量, 旧版检查完全无法识别
    phase = us_phase()
    if bar_is_partial(last_d):
        print(f"  [XX] 严重: 美东当前时刻仍处于 {last_d} 的常规盘中 -> 最后一根是【未完成 bar】")
        print("       它只有部分成交量与临时价, 用来算信号必然出错。")
        print("       请等美股收盘(北京次日 04:00)后再跑, 或用 --no-fetch 查看上一份结果。")
        ok = False
    elif phase in ("pre", "post"):
        print(f"  [!] 当前处于美股{'盘前' if phase=='pre' else '盘后'}时段, 最新完整收盘为 {last_d}")
    # 覆盖度闸门 —— v25.1: 按【真实 bar 数】算, 不再把 ffill 出来的幽灵日算作历史
    cover = {c.replace("US.",""): int(REAL[c].sum()) for c in UNI}
    good = [c for c in UNI if REAL[c].sum() >= MIN_HIST]
    short = [c.replace("US.","") for c in UNI if REAL[c].sum() < MIN_HIST]
    _ghost = int((~REAL.values).sum())
    print(f"  候选池: 合格 {len(good)}/{S} 只; 历史不足被剔除: {short if short else '无'}")
    print(f"  真实 bar 覆盖率: {REAL.values.mean()*100:.1f}% (缺失 {_ghost} 格 = 停牌/未上市, "
          f"已按 NaN 处理, 不参与排名)")
    # v25 流动性闸门体检 —— 必须显式打印: "因子被悄悄置 NaN" 是看不见的变化
    if USE_GATE:
        blk = 1.0 - TRADE.mean()
        t_ok = int(TRADE.values[-1].sum())
        t_blk = [UNI[j].replace("US.", "") for j in range(S) if not TRADE.values[-1, j]]
        print(f"  流动性闸门: 滚动{GATE_WIN}日中位成交额 >= ${MIN_DV/1e6:.0f}M  [变体 {VARIANT}]")
        print(f"    本日可交易 {t_ok}/{S} 只" + (f"; 被挡下: {t_blk}" if t_blk else " (全部可交易)"))
        _w = blk.sort_values(ascending=False).head(6)
        _w = _w[_w > 0]
        if len(_w):
            print("    历史被挡比例最高: "
                  + ", ".join(f"{c.replace('US.','')} {v*100:.0f}%" for c, v in _w.items())
                  + "  <- 早期是壳股/停牌, 已移出排名")
    else:
        print("  流动性闸门: 【已关闭 --no-gate】壳股/停牌期会重新进入排名, 仅供对比")
    # 极端跳变标记
    prev = C.shift().where(lambda x: x.abs() > 1e-9)
    ret = C / prev - 1.0
    rr, cc = np.where(np.nan_to_num(ret.values[-30:] > 0.5, nan=False))
    shock = sorted(set(UNI[c].replace("US.", "") for c in cc))
    if shock:
        print(f"  ⚠ 近 30 日出现单日 >50% 暴涨: {shock}")
        print("     Vortex 用 14 日窗口受影响小; 但动量类因子会把它当成趋势 -> 谨慎")
    # 僵尸票
    dead = [c.replace("US.","") for c in UNI if C[c].values[-1] == C[c].values[-21:-1][-1]]
    if dead: print(f"  ⚠ 疑似停牌/零成交: {dead}")
    if VOL.values[-1].sum() <= 0: print("  ⚠ 最新一根成交量为 0 (休市/数据未更新)")
    # 成交量骤降启发式: 与时段判断互相独立, 双保险
    vsum = np.nansum(VOL.values, axis=1)
    v_last, v_med = vsum[-1], np.nanmedian(vsum[max(0, N - 22):N - 1])
    if np.isfinite(v_med) and v_med > 0 and v_last / v_med < 0.5:
        print(f"  ⚠ 最新一根全池成交量仅为近 20 日中位的 {v_last/v_med*100:.0f}% "
              f"-> 疑似半日市/盘中未完成/数据未更新")
    if lag_td >= 1: print(f"  ⚠ 数据落后 {lag_td} 个交易日")
    # 面板空洞: 中间断层会被 ffill(limit=10) 跳过, 相关标的静默变 NaN 并被剔除出排名
    _gap = pd.Series(dp).diff().dt.days
    _big = _gap[_gap > 12]
    if len(_big) > 0:
        print(f"  ⚠ 面板存在 {len(_big)} 处 >12 日空洞: "
              + ", ".join(f"{dp[i].date()}({int(_gap[i])}天)" for i in _big.index[:5])
              + "  -> ffill(limit=10) 跨不过去, 受影响标的会静默掉出排名")
    if not ok: print("  ❌ 本次数据不可靠 (见上方警告), 请勿据此下单")

    print("\n" + "=" * 116); print("[3] 调仓日历"); print("=" * 116)
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    is_rebal = (RB[-1] == N - 1)
    last_reb_date = dp[RB[-1]].date()
    if is_rebal:
        exec_d = next_trading_day(last_d)
        print(f"  ⚡ 最新一根({last_d})【就是调仓日】-> 下一个交易日 {exec_d} 开盘执行")
    else:
        # RB[-1] 是【已过去】的最近调仓日; 下次调仓需按交易日历往后推 REBAL 根
        exec_d = project_trading_days(last_reb_date, REBAL)
        past_td = N - 1 - RB[-1]
        print(f"  最近调仓 {last_reb_date}（{past_td} 个交易日前）-> 当前【无需操作】")
        print(f"  下次调仓约 {exec_d}（距今 {REBAL - past_td} 个交易日, 按交易日历推算）")
    if exec_d:
        print(f"  执行日: {exec_d}  北京时间 {open_time(exec_d)} 开盘")
        if exec_d.strftime("%m-%d") in HALF_DAYS.get(exec_d.year, []):
            print(f"  ⚠ {exec_d} 是半日市(美东 13:00 收盘, 北京 {open_time(exec_d)[:2]}:00+3.5h)")
        print(f"  夏令时: {'是(3/8-11/1, 21:30开盘)' if is_dst(exec_d) else '否(22:30开盘)'}")

    px_now = {UNI[j].replace("US.",""): float(C.values[N-1, j]) for j in range(len(UNI))}
    # 幽灵持仓: 拼错代码会让市值按 0 计 -> 净值/目标股数全错, 必须在算净值前拦下
    ghost = [k for k in POSITIONS if k not in px_now]
    if ghost:
        print(f"\n  ❌ 持仓中有不在标的池的代码: {ghost}")
        print("     拼错代码会让它的市值按 0 计 -> 净值被低估 -> 目标股数全错。请修正后重跑。")
        ok = False
    # 显式指定本金时以其为准, 否则用持仓市值(复利口径)
    if "--capital" in sys.argv or "--cny" in sys.argv:
        NET = CAP0
    else:
        NET = (sum(q * px_now.get(k, 0.0) for k, q in POSITIONS.items()) if POSITIONS else CAP0)
    print("\n" + "=" * 116); print(f"[4] 下单清单  净值 ${NET:,.0f}  汇率 {FX}"); print("=" * 116)
    A = SIG.get(STRAT, SIG["Vortex"])
    # 选股层调用: 只传 信号/行号/合格池/持股数 —— 不传本金, 不传净值, 不传佣金
    pick = select(A, N - 1, good, TOPK)
    names = [UNI[j].replace("US.","") for j in pick]
    print(f"  策略 {STRAT} Top{TOPK}: {', '.join(names)}")
    print(f"  （选股仅由因子得分排序决定, 与本金/价格/佣金无关; 本金只影响下面每只买多少股）")
    print(f"\n  {'标的':<8}{'现价':>11}{'目标金额':>11}{'整股':>7}{'整股金额':>11}{'碎股股数':>11}{'建议':>10}")
    print("  " + "-" * 72)
    tot = 0.0
    bud = NET / TOPK
    for j in pick:
        c = UNI[j].replace("US.",""); p = float(C.values[N-1, j])
        sh = int(bud // p) if p > 0 else 0
        tot += sh * p
        print(f"  {c:<8}${p:>10.2f}${bud:>10.0f}{sh:>7}${sh*p:>10.2f}{bud/p:>11.4f}"
              f"{'碎股' if sh==0 else '整股OK':>10}")
    cash_left = NET - tot
    n_sell, n_buy = (TOPK if POSITIONS else 0), TOPK
    fee = (n_sell + n_buy) * COMM
    print(f"\n  整股投入 ${tot:,.0f} (占净值 {tot/NET*100:.0f}%), 闲置 ${cash_left:,.0f}")
    print(f"  佣金 卖 {n_sell}x${COMM:.0f} + 买 {n_buy}x${COMM:.0f} = ${fee:.0f} (占净值 {fee/NET*100:.2f}%)")
    if tot / NET < 0.6:
        print(f"  ❌ 整股买不动 -> 必须用碎股(富途支持按金额下单), 否则 {cash_left/NET*100:.0f}% 本金空转")
    print(f"  碎股方案: 每只按金额 ${bud:,.0f} 买入, 份额 "
          + ", ".join(f"{UNI[j].replace('US.','')} {bud/float(C.values[N-1,j]):.4f}股" for j in pick))

    print("\n" + "=" * 116); print("[5] 换仓指令（最小换手，省佣金）"); print("=" * 116)
    px_now = {UNI[j].replace("US.",""): float(C.values[N-1, j]) for j in range(len(UNI))}
    if POSITIONS:
        mv = sum(q * px_now.get(k, 0.0) for k, q in POSITIONS.items())
        cost = sum(q * COSTBASIS.get(k, np.nan) for k, q in POSITIONS.items()
                   if np.isfinite(COSTBASIS.get(k, np.nan)))
        print(f"  当前持仓市值 ${mv:,.0f}" + (f"  成本 ${cost:,.0f}  盈亏 ${mv-cost:+,.0f} "
              f"({(mv/cost-1)*100:+.1f}%)" if np.isfinite(cost) and cost > 0 else ""))
        for k, q in POSITIONS.items():
            p = px_now.get(k, 0.0); cb = COSTBASIS.get(k, np.nan)
            pl = f"{(p/cb-1)*100:+.1f}%" if np.isfinite(cb) and cb > 0 else "-"
            print(f"     {k:<7}{q:>9.4f}股  现价 ${p:>9.2f}  市值 ${q*p:>9,.0f}  盈亏 {pl:>8}")
    tgt_amt = NET / TOPK
    orders = []
    for j in pick:
        c = UNI[j].replace("US.","")
        cur_sh = POSITIONS.get(c, 0.0)
        cur_amt = cur_sh * px_now.get(c, 0.0)
        delta_amt = tgt_amt - cur_amt
        delta_sh = delta_amt / px_now[c] if px_now.get(c, 0) > 0 else 0.0
        if abs(delta_amt) < max(25.0, tgt_amt * 0.12):
            orders.append((c, "持有", 0.0, 0.0, cur_sh, "偏离小, 不动(省$4)"))
        elif delta_amt > 0:
            orders.append((c, "买入", delta_sh, delta_amt, cur_sh, ""))
        else:
            orders.append((c, "卖出", -abs(delta_sh), -abs(delta_amt), cur_sh, "减仓"))
    for c in POSITIONS:
        if c not in names and c in px_now:
            orders.append((c, "清仓", 0.0, POSITIONS[c] * px_now[c], POSITIONS[c], ""))
    print(f"  {'标的':<8}{'动作':>6}{'股数':>12}{'金额':>12}{'现持':>10}  备注")
    print("  " + "-" * 76)
    fee_est = 0.0; act = 0
    for c, side, sh, amt, cur, note in orders:
        if side != "持有": act += 1; fee_est += COMM
        s = f"{sh:.4f}" if side != "持有" else f"{cur:.4f}"
        print(f"  {c:<8}{side:>6}{s:>12}{('$%.0f' % abs(amt)) if amt else '-':>12}"
              f"{cur:>10.4f}  {note}")
    lab = "首次建仓" if not POSITIONS else "最小换手"
    print(f"  预计佣金 ${fee_est:.0f}（{lab} 方案）")
    print(f"  对比: 无脑全卖全买 = ${TOPK*COMM*2:.0f}; 最小换手省下 ${TOPK*COMM*2-fee_est:.0f}")

    if BOUGHT:
        rec = parse_bought(BOUGHT)
        json.dump({"as_of": str(last_d), "shares": rec}, open(PORTFILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"  ✅ 已记录成交到 {os.path.basename(PORTFILE)}（下次自动读取算盈亏）")

    print("\n" + "=" * 116); print("[6] 执行须知 (实务约束)"); print("=" * 116)
    print(f"  1. 下单时点: {exec_d if exec_d else '下次调仓日'} 北京时间 {open_time(exec_d) if exec_d else '-'} 开盘")
    print("     回测成交价 = 开盘价; 夜盘(北京8:00-16:00)/盘前(16:00-21:30)流动性薄、价差大, 不要用")
    print("  2. 订单类型: 碎股通常只支持市价单; 整股可开盘价限价")
    print("  3. 现金账户 T+1: 卖出的钱要 T+1 才结算。同日'先卖后买'可能触发 Good Faith Violation")
    print("     -> 若是现金账户: 建议【先买后卖】(用未结算资金会被限), 或改为仅卖出/仅买入错开")
    if TOPK == 2:
        print("  4. 持股数 Top2: 由【信号本身】决定, 与本金无关。零成本下 Vortex k=2 CAGR 89.1% /")
        print("     k=3 69.3% / k=1 45.1%, 换成 $100 万本金排名一模一样 -> 是信号偏好的 k=2。")
        print("     本金只影响成本占比: 同样 366 笔交易 $732 佣金, $300 本金要吃掉 244%, $10 万只占 0.7%。")
        print("     结论: 钱少不要减票(降低分散度), 钱多也不要加票(信号更差)——闲置零头留现金。")
    else:
        print(f"  4. 持股数 Top{TOPK}: 由信号本身决定(非本金)。零头留现金, 别为凑仓位临时加一只。")
    print(f"  5. 汇率: 按 {FX} 折算; 人民币兑美元每升 1%, 折算回人民币少 1%")

    # 持久化
    snap = {"generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "data_last": str(last_d), "rebal_day": str(dp[RB[-1]].date()),
            "is_rebal_day": bool(is_rebal),
            "exec_day": str(exec_d) if exec_d else None,
            "open_time_cn": open_time(exec_d) if exec_d else None,
            "strategy": STRAT, "topk": TOPK, "capital_usd": round(CAP0, 2), "fx": FX,
            # v24: 记录池子规模与成分。池子变了信号就会变, 不记录会造成
            # "同一天两个不同结果, 却说不清哪个是哪次"的审计黑洞。
            "pool_size": len(good), "pool_codes": sorted(c.replace("US.", "") for c in good),
            # v25: 变体标识(闸门口径)。与 pool_size 是同一件事 ——
            # 让"这份信号出自哪套口径"可追溯, 否则事后无法解释同一天的两个结果。
            "variant": VARIANT,
            "min_dv": (MIN_DV if USE_GATE else None),
            "tradable_n": (int(TRADE.values[-1].sum()) if USE_GATE else None),
            "picks": names, "prices": {n: round(float(C.values[N-1, UNI.index("US."+n)]), 2) for n in names},
            "budget_each": round(bud, 2), "commission": round(fee, 2),
            "target_shares": {n: round(float(bud / float(C.values[N-1, UNI.index("US."+n)])), 4) for n in names},
            "orders": [{"code": c, "side": s, "shares": round(sh, 4), "amount": round(amt, 2)}
                       for c, s, sh, amt, _, _ in orders],
            "shock": shock, "data_ok": ok}
    json.dump(snap, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    try:
        row = pd.DataFrame([{"date": str(last_d), "strategy": STRAT, "topk": TOPK,
                             "pool_size": len(good), "variant": VARIANT,
                             "picks": ",".join(names), "exec_day": str(exec_d) if exec_d else ""}])
        if os.path.exists(HIST):
            h = hist_merge(pd.read_csv(HIST), row)
        else:
            h = row
        h.to_csv(HIST, index=False, encoding="utf-8-sig")
    except Exception as e:
        print(f"  历史写入失败: {e}")
    print(f"\n  已保存: {os.path.basename(SNAP)} | 历史(去重更新): {os.path.basename(HIST)}")
    return 0 if ok else 2

def hist_merge(h, row):
    """把一行信号并入历史表。

    去重键 = (date, strategy, topk, pool_size, variant)。
    v24: 把 pool_size 计入键 —— 扩大股票池后同一天的信号会变,
    若不区分, 旧记录会被静默覆盖, 事后无法解释"信号为什么变了"。
    v25: 再把 variant(闸门口径)计入键 —— 同一个池子、同一天,
    开闸门与关闸门是两个不同结果, 同样不能互相覆盖。
    """
    if h is None:
        return row.copy()
    h = h.copy()
    if "pool_size" not in h.columns:
        h["pool_size"] = -1
    if "variant" not in h.columns:
        h["variant"] = "-"
    rv = str(row["variant"].iloc[0]) if "variant" in row.columns else "-"
    key = (h["date"].astype(str) == str(row["date"].iloc[0])) & \
          (h["strategy"].astype(str) == str(row["strategy"].iloc[0])) & \
          (h["topk"].astype(int) == int(row["topk"].iloc[0])) & \
          (h["pool_size"].astype(int) == int(row["pool_size"].iloc[0])) & \
          (h["variant"].astype(str) == rv)
    return pd.concat([h[~key], row], ignore_index=True)


def self_test():
    print("=" * 116); print("SELF-TEST"); print("=" * 116)
    fails = []
    def chk(name, cond, extra=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name} {extra}")
        if not cond: fails.append(name)
    # 夏令时
    chk("DST: 2026-07-01 为夏令时", is_dst(datetime.date(2026,7,1)))
    chk("DST: 2026-12-01 非夏令时", not is_dst(datetime.date(2026,12,1)))
    chk("DST: 边界 3/8 起", is_dst(datetime.date(2026,3,8)))
    chk("DST: 边界 11/1 结束", not is_dst(datetime.date(2026,11,1)))
    # 交易日
    chk("休市: 2026-09-07 劳动节非交易日", not is_trading_day(datetime.date(2026,9,7)))
    chk("交易日: 2026-09-14 是交易日", is_trading_day(datetime.date(2026,9,14)))
    chk("周末非交易日", not is_trading_day(datetime.date(2026,9,12)))
    chk("next_trading_day(9/11) = 9/14", str(next_trading_day(datetime.date(2026,9,11))) == "2026-09-14")
    # 时区与时段
    chk("美东换算: 北京 9/12 03:00 -> 美东 9/11 15:00",
        to_et(datetime.datetime(2026,9,12,3,0)).strftime("%Y-%m-%d %H:%M") == "2026-09-11 15:00")
    chk("盘中判定: 北京 9/12 03:00 拉 9/11 = 未完成 bar",
        bar_is_partial(datetime.date(2026,9,11), datetime.datetime(2026,9,12,3,0)))
    chk("盘中判定: 北京 9/12 11:00 拉 9/11 = 已完成",
        not bar_is_partial(datetime.date(2026,9,11), datetime.datetime(2026,9,12,11,0)))
    chk("时段判定: 北京 9/12 03:00 = regular",
        us_phase(datetime.datetime(2026,9,12,3,0)) == "regular")
    chk("时段判定: 北京 9/12 11:00 = closed",
        us_phase(datetime.datetime(2026,9,12,11,0)) == "closed")
    chk("下次调仓推算: 9/11 + 21 交易日 = 2026-10-12",
        str(project_trading_days(datetime.date(2026,9,11), REBAL)) == "2026-10-12")
    # 数据
    dates, PX, REAL = load(UNI)
    C = PX["close"]; N, S = C.shape
    raw = {c: pd.read_csv(os.path.join(LONGDIR, c.replace(".","_")+".csv")) for c in UNI[:5]}
    chk("无重复日期", all(not pd.to_datetime(d["time_key"]).duplicated().any() for d in raw.values()))
    chk("面板列数 = 标的数", S == len(UNI), f"({S})")
    good = [c for c in UNI if REAL[c].sum() >= MIN_HIST]
    chk("合格候选 >= 25 只", len(good) >= 25, f"({len(good)})")
    chk("最后一根全部有效", C.values[-1][np.isfinite(C.values[-1])].size >= len(UNI) - 2)
    # 无未来函数 —— 闸门口径 / 无闸门口径 都要过。
    # 注意: 只比数值不够。闸门会把"不可交易"处置 NaN, 若截断前后 NaN 的【位置】
    # 变了, 说明闸门偷看了未来, 而 nanmax 会把 NaN 差异静默吃掉 -> 必须单独比 NaN 图案。
    TR, _MED = tradable_mask(PX, MIN_DV)
    SIG = build_signals(PX, TR, REAL)
    A_full = SIG["Vortex"].values
    sub = {k: v.iloc[:N-21] for k, v in PX.items()}
    R2 = REAL.iloc[:N-21]
    TR2, _ = tradable_mask(sub, MIN_DV)
    V2 = vortex(sub["high"], sub["low"], sub["close"]).where(TR2 & R2).values
    _z = slice(0, N - 21)
    _same = bool((np.isnan(A_full[_z]) == np.isnan(V2[_z])).all())
    d = np.nanmax(np.abs(A_full[_z] - V2[_z])) if np.isfinite(A_full[_z]).any() else np.inf
    chk("Vortex 无未来函数(含闸门 NaN 位置一致)", _same and d < 1e-9,
        f"(maxdiff {d:.2e}, NaN位置一致={_same})")
    A_offgen = build_signals(PX, None)["Vortex"].values
    d2 = np.nanmax(np.abs(A_offgen[_z] - vortex(sub["high"], sub["low"], sub["close"]).values[_z]))
    chk("Vortex 无未来函数(无闸门口径)", d2 < 1e-9, f"(maxdiff {d2:.2e})")
    # 调仓序列稳定
    rb1 = [i for i in range(N) if i >= START and (i-START) % REBAL == 0]
    rb2 = [i for i in range(N-21) if i >= START and (i-START) % REBAL == 0]
    chk("调仓序列不因追加数据而漂移", rb2 == [i for i in rb1 if i < N-21])
    # 佣金
    chk("佣金: Top2 换仓 = $8", 2*COMM*2 == 8.0)
    # ---- v24 历史表去重键必须含 pool_size ----
    _h = pd.DataFrame([{"date": "2026-09-11", "strategy": "Vortex", "topk": 2,
                        "pool_size": 37, "picks": "META,BE", "exec_day": "2026-09-14"}])
    _r37 = pd.DataFrame([{"date": "2026-09-11", "strategy": "Vortex", "topk": 2,
                          "pool_size": 37, "picks": "META,BE", "exec_day": "2026-09-14"}])
    _r81 = pd.DataFrame([{"date": "2026-09-11", "strategy": "Vortex", "topk": 2,
                          "pool_size": 81, "picks": "SWKS,META", "exec_day": "2026-09-14"}])
    chk("历史表: 同池子重跑只留 1 行", len(hist_merge(_h, _r37)) == 1)
    _m = hist_merge(_h, _r81)
    chk("历史表: 池子变大后新旧两条都保留", len(_m) == 2,
        f"({len(_m)} 行)")
    chk("历史表: 旧池子的选票 META,BE 仍可查",
        _m.loc[_m.pool_size == 37, "picks"].iloc[0] == "META,BE")
    chk("历史表: 无 pool_size 列的旧表也能合并不报错",
        len(hist_merge(_h.drop(columns=["pool_size"]), _r81)) == 2)
    # ---- v25 历史表去重键必须含 variant(闸门口径) ----
    _g = pd.DataFrame([{"date": "2026-09-11", "strategy": "Vortex", "topk": 2,
                        "pool_size": 81, "variant": "gate5M",
                        "picks": "SWKS,META", "exec_day": "2026-09-14"}])
    _n = pd.DataFrame([{"date": "2026-09-11", "strategy": "Vortex", "topk": 2,
                        "pool_size": 81, "variant": "nogate",
                        "picks": "META,BE", "exec_day": "2026-09-14"}])
    chk("历史表: 同池同变体重跑只留 1 行", len(hist_merge(_g, _g)) == 1)
    _m2 = hist_merge(_g, _n)
    chk("历史表: 开/关闸门两种变体都保留", len(_m2) == 2, f"({len(_m2)} 行)")
    chk("历史表: 关闸门那条的选票仍可查",
        _m2.loc[_m2.variant == "nogate", "picks"].iloc[0] == "META,BE")
    chk("历史表: 无 variant 列的旧表兼容",
        len(hist_merge(_g.drop(columns=["variant"]), _n)) == 2)
    # ---- v25 流动性闸门 ----
    chk("闸门: 输出 bool 面板且与价格面板同形",
        TR.shape == C.shape and bool(TR.dtypes.eq(bool).all()))
    chk("闸门: 阈值单调(门槛越高可交易日绝不增加)",
        all(tradable_mask(PX, hi)[0].values.sum() <= tradable_mask(PX, lo)[0].values.sum()
            for lo, hi in [(1e6, 5e6), (5e6, 2e7), (2e7, 1e9)]))
    # 合成僵尸票: 价格恒 $10, 每日成交 5 股 -> 必须被挡
    _fk = {k: v.copy() for k, v in PX.items()}
    _fk["close"].loc[:, "US.AAPL"] = 10.0
    _fk["volume"].loc[:, "US.AAPL"] = 5.0
    chk("闸门: 合成僵尸票($10 x 5股)全期被挡",
        not bool(tradable_mask(_fk, MIN_DV)[0]["US.AAPL"].any()))
    if "US.BMNR" in list(C.columns):
        _r = 1 - TR["US.BMNR"].mean()
        chk("闸门: BMNR 历史被挡 >= 40%", _r >= 0.40, f"(实测 {_r*100:.0f}%)")
    # 全 True 掩码必须等价于关闭闸门 -> 保证掩码本身不引入任何副作用
    _ones = pd.DataFrame(True, index=C.index, columns=C.columns)
    _a, _b = build_signals(PX, _ones)["Vortex"].values, build_signals(PX, None)["Vortex"].values
    chk("闸门: 全 True 掩码 == 关闭闸门",
        bool(np.allclose(np.nan_to_num(_a, nan=-9e9), np.nan_to_num(_b, nan=-9e9))))
    _a2 = build_signals(PX, _ones, REAL)["Vortex"].values
    _b2 = build_signals(PX, None, REAL)["Vortex"].values
    chk("闸门: 全 True 掩码 + REAL == 只加 REAL(两层职责可分离)",
        bool(np.allclose(np.nan_to_num(_a2, nan=-9e9), np.nan_to_num(_b2, nan=-9e9))))
    # ---- v25.1 F1 断言: 成交量不得被 ffill / 闸门不得采信伪造成交量 ----
    _fab = int(((~REAL.values) & PX["volume"].notna().values).sum())
    chk("F1: 缺 bar 处没有伪造成交量", _fab == 0,
        f"({_fab} 格 有量无 bar; 全样本缺失 {int((~REAL.values).sum())} 格)")
    chk("F1: 闸门为 True 处必有真实 bar (trade 含于 REAL)",
        int((TR.values & ~REAL.values).sum()) == 0,
        f"({int((TR.values & ~REAL.values).sum())} 处越界)")
    _fk3 = {k: v.copy() for k, v in PX.items()}
    _fk3["volume"].loc[:, "US.AAPL"] = np.nan        # 有价无量
    chk("F1: 有价无量(停牌)的日子不得判为可交易",
        not bool(tradable_mask(_fk3, MIN_DV)[0]["US.AAPL"].any()))
    _leak_r = int(((~REAL.values) & ~np.isnan(build_signals(PX, TR, REAL)["Vortex"].values)).sum())
    chk("F1: 无 bar 日的因子必为 NaN(REAL 未静默失效)", _leak_r == 0, f"({_leak_r} 处泄漏)")
    if "US.NBIS" in list(C.columns):
        _nb = TR["US.NBIS"]
        _pin = _nb.loc["2022-03-01":"2022-03-31"]
        chk("F1: NBIS 停牌期间(2022-03)已被挡下", not bool(_pin.any()),
            f"(该月 {int(_pin.sum())}/{len(_pin)} 天可交易)")
    # 闸门必须真的改动因子, 否则等于没接线(静默失效)
    _on = build_signals(PX, TR)["Vortex"].values
    _diff = int((~((_on == _b) | (np.isnan(_on) & np.isnan(_b)))).sum())
    chk("闸门: 确实改变了因子值(已接线, 非静默失效)", _diff > 0, f"({_diff} 个格子被改动)")
    chk("闸门: 不可交易处因子必为 NaN(无泄漏)",
        int(((~TR.values) & ~np.isnan(_on)).sum()) == 0,
        f"({int(((~TR.values) & ~np.isnan(_on)).sum())} 处泄漏)")
    # ---- v22 选股层 × 资金 解耦 (铁律) ----
    import inspect as _ins, ast as _ast
    _full = _ins.getsource(select)
    _fn = _ast.parse(_full).body[0]
    # 剥掉函数文档串与注释, 只扫可执行代码 -> 注释里提到"本金"不算违规
    _cut = set()
    if _fn.body and isinstance(_fn.body[0], _ast.Expr) and isinstance(_fn.body[0].value, _ast.Constant):
        _cut = set(range(_fn.body[0].lineno, _fn.body[0].end_lineno + 1))
    _code = "\n".join(l for n, l in enumerate(_full.splitlines(), 1)
                      if n not in _cut and not l.strip().startswith("#"))
    _bad = [w for w in ["CAP0", "NET", "CNY", "FX", "bud", "COMM", "cash", "capital"]
            if w in _code]
    chk("选股层可执行代码不含任何资金变量", not _bad, f"(命中 {_bad})" if _bad else "(纯净)")
    _names = set(select.__code__.co_names) | set(select.__code__.co_varnames)
    chk("选股层未读取任何资金全局量",
        not (_names & {"CAP0", "NET", "CNY", "FX", "COMM", "POSITIONS", "COSTBASIS", "BOUGHT"}),
        f"({sorted(_names)})")
    good_s = [c for c in UNI if REAL[c].sum() >= MIN_HIST]
    A_s = SIG[STRAT]
    base_s = select(A_s, N-1, good_s, TOPK)
    _saved = globals()["CAP0"]
    same = True
    for fake in (0.01, 1.0, 1490.49, 1e6, 1e12):
        globals()["CAP0"] = fake
        if select(A_s, N-1, good_s, TOPK) != base_s:
            same = False
    globals()["CAP0"] = _saved
    chk("选股结果对 $0.01 ~ $1e12 任意本金都不变", same,
        f"({', '.join(UNI[j].replace('US.','') for j in base_s)})")
    chk("选股层输入签名无资金参数",
        list(_ins.signature(select).parameters) == ["A", "i", "good", "topk"],
        f"({list(_ins.signature(select).parameters)})")
    # OHLC
    bad = 0
    for i in range(0, N, 11):
        h, l = PX["high"].values[i], PX["low"].values[i]
        m = np.isfinite(h) & np.isfinite(l)
        bad += int((h[m] < l[m]).sum())
    chk("OHLC 无 high<low 冲突", bad == 0, f"({bad} 处)")
    print("\n" + "=" * 116)
    print(f"  结果: {'✅ 全部通过' if not fails else '❌ 失败: ' + ', '.join(fails)}")
    return 0 if not fails else 1

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
