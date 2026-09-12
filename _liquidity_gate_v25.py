# -*- coding: utf-8 -*-
"""
v25 流动性闸门 —— 效果量化

回答三个问题:
  Q1 闸门到底改了多少历史选股? (逐调仓日比对 Top2)
  Q2 关掉闸门时, 策略一共买过多少次"当天根本不可交易"的票?
     这些"买僵尸"的交易, 事后 21 日收益是正是负?
     -> 这是闸门价值的直接度量: 如果僵尸票的已实现收益平庸甚至为负, 说明
        它们过去一直在白占仓位、并让回测显得比实盘更可行。
  Q3 8.7 年回测终值差多少? (同池子、同成本模型, 只差闸门)

注意: 本脚本【不做任何参数寻优】。它只把同一套信号在两种数据清洗口径下跑一遍,
      差异全部来自"是否把不可交易的假价格计入排名"。

v25.1 审计修复(见 美股回测深度审计_v25.1.md):
  F1 volume 不再 ffill(停牌日没有成交), 并新增 REAL 掩码 -> 闸门不再采信伪造成交量。
     实测后果曾为: 2022-03 买入已停牌的 NBIS。
  F2 卖不掉的持仓【保留】而非凭空清空。旧写法让仓位价值既不进现金也不进净值,
     在反转策略上砸出假的 -34.6% 单日断崖, 终值低估 61% (CAGR 45.4% -> 54.7%)。
  F3 买入佣金显式扣除(cash -= sh*pr + comm)。旧写法每次满仓调仓漏扣 $4,
     本金 $500 时终值虚高 34.5%。
"""
import os, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

BASE = r"c:/Users/sailor/WorkBuddy/2026-09-11-09-02-22"
LONGDIR = os.path.join(BASE, "data_kline_long")
START, REBAL, COMM, CAP0 = 252, 21, 2.0, 3000.0
GATE_WIN, GATE_DV = 60, 5e6
MAX_FFILL = 10

mi = json.load(open(os.path.join(BASE, "market_info.json"), encoding="utf-8"))
fetched = json.load(open(os.path.join(BASE, "fetched_codes.json"), encoding="utf-8"))
def is_etf(n):
    n = (n or "").upper()
    return any(k in n for k in ["ETF","ETN","3X","2X","ULTRA","PROSHARES","LEVERAG"," -3X","3XS","BEAR","BULL "])
UNI = [c for c in fetched if not is_etf(mi.get(c, {}).get("name", ""))
       and (mi.get(c, {}).get("total_market_val", 0) or 0) >= 10e9]

def panel(limit=MAX_FFILL):
    """构建对齐面板。

    v25.1 修复(F1): volume 不做 ffill, 并额外返回 REAL 掩码(该格当天是否真有 bar)。
    旧写法把停牌日的成交量填成前一天的值, 于是闸门 close x volume 在停牌后的
    10 个交易日里看到的是"前一天的成交额" -> 把停牌票判成可交易。
    实测后果: 2022-03 买入已停牌的 NBIS -> 见 _audit_v25.py 的 C3/C11。
    """
    p = {}
    for c in UNI:
        d = pd.read_csv(os.path.join(LONGDIR, c.replace(".", "_") + ".csv"))
        d["time_key"] = pd.to_datetime(d["time_key"])
        p[c] = d.sort_values("time_key").drop_duplicates("time_key", keep="last").set_index("time_key")
    ad = sorted(set().union(*[set(x.index) for x in p.values()])); dt = pd.to_datetime(ad)
    out = {}
    for k in ["open","close","high","low","volume"]:
        m = pd.DataFrame({c: p[c][k].reindex(dt) for c in UNI})
        out[k] = m if k == "volume" else m.ffill(limit=limit)
    REAL = pd.DataFrame({c: p[c]["close"].reindex(dt).notna() for c in UNI})
    return dt, out, REAL

def vortex(h, lo, cl, n=14):
    pc = cl.shift()
    tr = np.maximum(np.maximum(h - lo, (h - pc).abs()), (lo - pc).abs())
    return ((h - lo.shift()).abs().rolling(n).sum() / tr.rolling(n).sum()
            - (lo - h.shift()).abs().rolling(n).sum() / tr.rolling(n).sum())

def tradable(PX, dv=GATE_DV, win=GATE_WIN):
    """与 _update_signal.tradable_mask 完全同一条规则(有意重复实现, 便于交叉验证)。"""
    return (PX["close"] * PX["volume"]).rolling(win, min_periods=win).median() >= dv

def signals(PX, trade=None, nm="Vortex", real=None):
    """v25.1: 增加 real 掩码(该日该标的是否真有 bar)。无 bar 的日子因子置 NaN。"""
    C, H, L = PX["close"], PX["high"], PX["low"]
    V = vortex(H, L, C)
    mom = C.shift(21) / C.shift(252) - 1.0
    rev = C / C.shift(21) - 1.0
    valid = trade
    if real is not None:
        valid = real if valid is None else (valid & real)
    if valid is not None:
        V, mom, rev = V.where(valid), mom.where(valid), rev.where(valid)
    zs = lambda x: x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
    return {"Vortex": V, "动量-1月反转": (zs(mom) - zs(rev)) / 2.0}[nm]

def picks_at(A, i, k=2):
    row = A.values[i]
    idx = np.where(np.isfinite(row))[0]
    if len(idx) == 0: return []
    return list(idx[np.argsort(-row[idx])][:k])

def backtest(C, O, A, trade=None, topk=2, cap=CAP0, comm=COMM, classify=None, veto=None):
    """调仓: 第 i 日开盘执行, 信号取第 i-1 日收盘。

    三个掩码的职责必须严格分开, 否则会得出"策略从没买过僵尸票"的假结论:
      trade     —— 参与【打分】的掩码。闸门关闭时为 None。
      classify  —— 只用于【事后贴标签】, 判断"这笔买入当天是否真的可交易"。
                   关闸门那一跑也必须传开启闸门的那张表, 否则无从判断,
                   等于自证清白(v25 第一版就踩了这个坑, Q2 报 0 笔)。
      veto      —— 只用于【买入时拒单】: 打分照旧用全部标的, 但轮到不可交易的标的
                   就不买它、顺延到下一名。用来把"不许买脏票"的效应单独隔离出来。
                   顺延(而非留现金)才与真实策略一致 —— 闸门把因子置 NaN 后,
                   该标的直接退出排名, 策略本来就会去选下一名。

    返回 (净值序列, 成交记录)。
    """
    N = C.shape[0]
    RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
    RBset = set(RB)
    lab = trade if classify is None else classify
    cash, pos, eq = cap, {}, np.full(N, np.nan)
    eq[:START] = cap
    log = []
    for i in range(START, N):
        eq[i] = cash + sum(pos.get(j, 0) * C[i, j] for j in pos)
        if i in RBset:
            # v25.1 修复(F2): 卖不掉的持仓必须【保留】。
            # 旧写法在这里跳过入账, 但循环结束后仍然执行 pos = {}, 于是一笔
            # "当天开盘价不可得"的持仓既不变成现金、也不留在持仓里 —— 价值凭空消失。
            # 实测后果: 反转策略在 2022-04-05 出现假的 -34.6% 单日断崖, 终值低估 61%。
            keep = {}
            for j, sh in pos.items():
                pr = O[i, j]
                if np.isfinite(pr) and pr > 0:
                    cash += sh * pr - comm
                else:
                    keep[j] = sh
            pos = keep
            j_sig = i - 1
            row = A.values[j_sig]
            idx = np.where(np.isfinite(row))[0]
            if veto is not None and len(idx):
                idx = idx[veto.values[j_sig, idx]]
            # 卖不掉的仓位不重复买入
            idx = np.array([j for j in idx if j not in pos], dtype=int)
            if len(idx) >= topk:
                pk = list(idx[np.argsort(-row[idx])][:topk])
                bud = (cash - topk * comm) / topk
                for j in pk:
                    pr = O[i, j]
                    if not np.isfinite(pr) or pr <= 0: continue
                    sh = bud / pr
                    if sh > 0:
                        pos[j] = sh
                        # v25.1 修复(F3): 补上买入佣金。
                        # 旧写法只写 cash -= sh*pr, 那笔 comm 只是"预留"却从未离开账户
                        # -> 每次满仓调仓后账上恰好残留 topk*$2, 等于只收了卖出那一半。
                        cash -= sh * pr + comm
                        tr_ok = True if lab is None else bool(lab.values[j_sig, j])
                        log.append({"i": i, "j": j, "code": UNI[j].replace("US.", ""),
                                    "tradable": tr_ok, "px": pr})
    return pd.Series(eq).ffill().values, log

dt, PX, REAL = panel()
C, O = PX["close"], PX["open"]
N = C.shape[0]; dp = pd.to_datetime(dt)
TRADE = tradable(PX)
RB = [i for i in range(N) if i >= START and (i - START) % REBAL == 0]
YRS = (dp[-1] - dp[START]).days / 365.25

def stats(eq):
    """CAGR 必须按【实际回测年数】算: 面板含 252 根预热, 预热段不参与投资,
    把它算进年数会低报 CAGR。这个年数由日期算出来, 不写死。"""
    cagr = (eq[-1] / CAP0) ** (1 / YRS) - 1
    peak = np.maximum.accumulate(eq[START:])
    dd = (eq[START:] / peak - 1).min()
    return eq[-1], cagr, dd

print("=" * 112)
print(f"v25 流动性闸门效果量化   池子 {len(UNI)} 只 | 面板 {N} 根 | "
      f"{dp[START].date()} ~ {dp[-1].date()} | 本金 ${CAP0:,.0f} | 佣金 ${COMM:.0f}/笔")
print("=" * 112)
g_rate = 1 - TRADE.mean()
print(f"闸门规则: 滚动{GATE_WIN}日中位成交额 >= ${GATE_DV/1e6:.0f}M")
print(f"  全样本被闸门挡下的格子占比: {g_rate.mean()*100:.1f}%  "
      f"(= {int((~TRADE.values).sum()):,} 个 标的x日)")
_w = (g_rate.sort_values(ascending=False).head(8) * 100).round(0)
print("  被挡比例最高: " + ", ".join(f"{c.replace('US.','')} {v:.0f}%" for c, v in _w.items()))

for nm in ["Vortex", "动量-1月反转"]:
    print("\n" + "=" * 112)
    print(f"策略: {nm}")
    print("=" * 112)
    A_off = signals(PX, None, nm, REAL)
    A_on = signals(PX, TRADE, nm, REAL)

    # ---- Q1 选股差异 ----
    # 【关键对齐】回测是在第 i 日【开盘】执行、信号取第 i-1 日【收盘】。
    # 因此判断"选股是否不同"必须在 i-1 上比, 不是 i 上。
    # v25 第二版用了 i, 导致反转策略的归因漏掉差异日 -> 恒等式校验不过(0.905x vs 1.265x)。
    diff = [i for i in RB if picks_at(A_off, i - 1) != picks_at(A_on, i - 1)]
    print(f"[Q1] {len(RB)} 个调仓日, 选股不同 {len(diff)} 个 ({len(diff)/len(RB)*100:.1f}%)")
    if diff:
        print("     前 8 个:")
        for i in diff[:8]:
            po = ", ".join(UNI[j].replace("US.","") for j in picks_at(A_off, i - 1))
            pn = ", ".join(UNI[j].replace("US.","") for j in picks_at(A_on, i - 1))
            print(f"       执行日 {dp[i].date()} (信号 {dp[i-1].date()})  旧: {po:<22} -> 新: {pn}")

    # ---- Q2 买僵尸的次数 ----
    # 关键: 关闸门那一跑也要传 TRADE 作为【分类】掩码, 否则无法判断"这笔是否踩雷"。
    eq_off, log_off = backtest(C.values, O.values, A_off, None, classify=TRADE)
    eq_on, log_on = backtest(C.values, O.values, A_on, TRADE)
    bad = [r for r in log_off if not r["tradable"]]
    print(f"[Q2] 关闸门时共买入 {len(log_off)} 笔; 其中【{len(bad)} 笔】当天其实不可交易 "
          f"({len(bad)/max(1,len(log_off))*100:.1f}%)")
    if bad:
        from collections import Counter
        cnt = Counter(r["code"] for r in bad)
        print("     买僵尸最多的标的: " + ", ".join(f"{c}x{n}" for c, n in cnt.most_common(8)))
        # 已实现 21 日收益: 买入开盘价 -> 下一次调仓开盘价
        rets_bad, rets_good = [], []
        for grp, bag in (("bad", bad), ("good", [r for r in log_off if r["tradable"]])):
            for r in bag:
                i2 = r["i"] + REBAL
                if i2 < N and np.isfinite(O.values[r["i"], r["j"]]) and np.isfinite(O.values[i2, r["j"]]):
                    rr = O.values[i2, r["j"]] / O.values[r["i"], r["j"]] - 1
                    (rets_bad if grp == "bad" else rets_good).append(rr)
        def _s(v):
            return f"n={len(v):<4} 均值 {np.mean(v)*100:+6.2f}%  中位 {np.median(v)*100:+6.2f}%  胜率 {(np.array(v)>0).mean()*100:5.1f}%" if v else "n=0"
        print(f"     僵尸票持仓 21 日已实现收益: {_s(rets_bad)}")
        print(f"     正常票持仓 21 日已实现收益: {_s(rets_good)}")
        if len(rets_bad) < 30:
            print(f"     ⚠ 僵尸样本仅 n={len(rets_bad)}, 均值差异【不具统计显著性】。")
            print("       闸门的理由不是『它让收益变高』, 而是『这些交易在现实中根本成交不了』——")
            print("       回测里按开盘价买入一个当天只成交几股的标的, 本身就是不可能实现的假设。")
    else:
        print("     关闸门时【一笔僵尸都没买到】—— 说明它的改善跟『买到脏票』无关,")
        print("       而来自 Q3 里 B->C 那一段: 横截面 z-score 的均值/标准差被躺平票污染了。")

    # ---- Q3 回测终值: 三段分解 ----
    # A 旧口径          : 打分与买入都不设防
    # B 只拒买脏票      : 打分口径不变, 但轮到不可交易的标的就不买、顺延到下一名
    # C 新口径·闸门     : 打分阶段就把它移出横截面(策略真实行为)
    # A->B 隔离"买了不可成交的标的"的直接代价;
    # B->C 隔离"横截面统计量被躺平票污染"的代价。
    # 不拆开的话, 会把"选票分叉之后的路径运气"算成闸门的功劳 —— 那是自欺。
    eq_v, log_v = backtest(C.values, O.values, A_off, None, classify=TRADE, veto=TRADE)
    _, c_off, d_off = stats(eq_off)
    print(f"[Q3] 回测区间 {dp[START].date()} ~ {dp[-1].date()} 共 {YRS:.2f} 年 "
          f"(Top2 等权, 碎股, 佣金 ${COMM:.0f}/笔, 本金 ${CAP0:,.0f}):")
    prev_c = None
    for lab_, e in [("A 旧口径·不设防", eq_off), ("B 只拒买脏票", eq_v), ("C 新口径·闸门", eq_on)]:
        f_, c_, d_ = stats(e)
        seg = f"  <- 本段 {c_*100-prev_c*100:+.1f}pp" if prev_c is not None else ""
        print(f"       {lab_:<16} 终值 ${f_:>11,.0f} ({(f_/CAP0-1)*100:+8.0f}%)  "
              f"CAGR {c_*100:6.1f}%  最大回撤 {d_*100:6.1f}%{seg}")
        prev_c = c_
    _, c_b, _ = stats(eq_v)
    _, c_on, d_on = stats(eq_on)
    print(f"       分解: 拒买脏票 {(c_b-c_off)*100:+.1f}pp + 清洗横截面统计量 "
          f"{(c_on-c_b)*100:+.1f}pp = {(c_on-c_off)*100:+.1f}pp")
    print("       ⚠ 含选票分叉后的路径运气, 这是『把一个假收益拿掉』的结果, 不是 alpha")
    # 校验: 拒单后不得再出现脏票成交
    bad_v = [r for r in log_v if not r["tradable"]]
    print(f"       校验: 拒单后成交 {len(log_v)} 笔, 其中脏票 {len(bad_v)} 笔 -> "
          f"{'✅' if not bad_v else '❌'}")
    if not len(bad_v):
        if nm == "Vortex":
            _e = bool(np.allclose(eq_v, eq_on, equal_nan=True))
            print(f"       校验: 时序因子下『拒单』应完全等价于『闸门』 -> "
                  f"{'✅ 两条曲线逐日完全相同' if _e else '❌ 不一致'}")
        else:
            _d = abs(c_on - c_b) * 100
            print(f"       校验: 横截面因子的 B/C 应当不同(统计量被污染) -> "
                  f"差 {_d:.1f}pp {'✅' if _d > 0 else '⚠ 为 0, 需复核'}")

    # ---- 差异归因: A->B 的收益差是不是集中在少数几次幸运替换上? ----
    # 口径必须是【组合层】: 策略持有的是等权 Top2, 只换掉其中一只时,
    # 组合收益 = 两个仓位的平均, 不是被换那一只的收益。
    # 用"单腿"收益做比值会得出与实测符号相反的结论(v25 第二版就踩了这个坑:
    # 反转策略单腿累计 0.854x 但实测 1.265x)。这里用组合层口径, 并做恒等式校验。
    if diff:
        print("       [归因] 逐个差异日的等权组合 21 日已实现收益 (旧 Top2 vs 新 Top2)")
        cum = 1.0
        for i in diff:
            # 信号与选票都在 i-1 上取, 执行价与持有区间仍在 i -> i+REBAL
            pa, pb = picks_at(A_off, i - 1), picks_at(A_on, i - 1)
            i2 = i + REBAL

            def _pw(ps):
                if i2 >= N: return np.nan
                v = []
                for j in ps:
                    a, b = O.values[i, j], O.values[i2, j]
                    if np.isfinite(a) and np.isfinite(b) and a > 0:
                        v.append(b / a - 1)
                return float(np.mean(v)) if v else np.nan

            sa, sb = _pw(pa), _pw(pb)
            oa = [UNI[j].replace("US.", "") for j in pa if j not in pb]
            ob = [UNI[j].replace("US.", "") for j in pb if j not in pa]
            if not (np.isfinite(sa) and np.isfinite(sb)) or (1 + sa) <= 0:
                print(f"         {dp[i].date()}  期末未实现/停牌, 不计入归因")
                continue
            cum *= (1 + sb) / (1 + sa)
            print(f"         {dp[i].date()}  旧 {'+'.join(UNI[j].replace('US.','') for j in pa):<12} {sa*100:+7.1f}%"
                  f"  ->  新 {'+'.join(UNI[j].replace('US.','') for j in pb):<12} {sb*100:+7.1f}%"
                  f"   换: {'/'.join(oa) or '-'} -> {'/'.join(ob) or '-'}   累计 {cum:.3f}x")
        act = stats(eq_on)[0] / stats(eq_off)[0]
        _rel = abs(cum - act) / act
        print(f"       归因校验: 逐期累计 {cum:.3f}x  vs  实测终值倍数 {act:.3f}x  -> "
              f"{'✅ 自洽(恒等式成立)' if _rel < 0.05 else '⚠ 偏差 %.1f%%, 需复核' % (_rel*100)}")
        print("       读法: 逐期累计 ≈ 实测倍数 => 收益差确实全部由这几次替换驱动;")
        print("             若其中某几次的换入标的涨幅远超被换出的那只, 那是【运气】而非闸门的本事。")

# ---- 横截面样本量: 闸门之后每个调仓日还剩多少只可交易 ----
# 必要性: 闸门砍掉 17.6% 的格子, 若某些调仓日只剩个位数标的,
# 横截面 z-score 就不稳(分母是小样本标准差), 反转类因子的排名会失真。
print("\n" + "=" * 112)
print("[样本量] 闸门后每个调仓日的可交易标的数 (信号日 = 执行日前一根)")
print("=" * 112)
_cnt = TRADE.values[[i - 1 for i in RB]].sum(axis=1)
_s = pd.Series(_cnt, index=pd.DatetimeIndex([dp[i] for i in RB]))
print(f"  最小 {_s.min()} 只 ({_s.idxmin()}) | 中位 {_s.median():.0f} 只 | 最大 {_s.max()} 只")
for _y in sorted({d.year for d in _s.index}):
    _v = _s[_s.index.year == _y]
    print(f"    {_y}: 可交易数 中位 {_v.median():3.0f} 只, 最少 {_v.min():3.0f} 只")
_narrow = int((_s < 10).sum())
print(f"  可交易数 < 10 的调仓日: {_narrow} 个 "
      f"-> {'⚠ 横截面过窄, z-score 不稳, 需下调门槛或缩减池子' if _narrow else '✅ 全部 >= 10 只'}")

# ---- 闸门开关是否只影响"脏"标的: 干净标的上两口径必须完全一致 ----
print("\n" + "=" * 112)
print("[交叉验证] 闸门的作用范围 —— 它只能移出'不可交易'的格子, 不得误伤其他部分")
print("=" * 112)
ok_all = True
for nm in ["Vortex", "动量-1月反转"]:
    a = signals(PX, None, nm, REAL).values; b = signals(PX, TRADE, nm, REAL).values
    leak = int(((~TRADE.values) & ~np.isnan(b)).sum())
    tag = "纯时序因子" if nm == "Vortex" else "横截面标准化因子"
    print(f"  {nm} ({tag})")
    print(f"    ① 不可交易处残留因子: {leak} 处  -> {'✅' if leak == 0 else '❌'}")
    ok_all &= (leak == 0)
    if nm == "Vortex":
        m = TRADE.values & np.isfinite(a)
        same = bool(np.allclose(a[m], b[m], equal_nan=True))
        print(f"    ② 可交易处逐格不变  : {same}  -> {'✅' if same else '❌'}")
        ok_all &= same
    else:
        # z-score 的行内均值/标准差是按横截面算的, 移出躺平票必然改变它们,
        # 所以"可交易处的数值也变了"是设计意图(E3), 不是缺陷。
        # 真正的风险是【算 z-score 时用了全样本统计量、算完才遮蔽】——
        # 那样统计量仍被躺平票污染。用可交易子集显式重算一遍即可排除。
        Cc = PX["close"]
        mom = (Cc.shift(21) / Cc.shift(252) - 1.0).where(TRADE & REAL)
        rev = (Cc / Cc.shift(21) - 1.0).where(TRADE & REAL)
        zs = lambda x: x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)
        ref = ((zs(mom) - zs(rev)) / 2.0).values
        same = bool(np.allclose(np.nan_to_num(ref, nan=-9e9), np.nan_to_num(b, nan=-9e9)))
        print(f"    ② 等于『仅在可交易子集上重算的 z-score 之差』: {same}  -> {'✅' if same else '❌'}")
        print("       (可交易处数值会变是预期的 —— 横截面均值/标准差只由可交易标的决定)")
        ok_all &= same
print(f"\n  结论: {'✅ 全部通过' if ok_all else '❌ 有失败项'}")
print("\nGATE_DONE")
