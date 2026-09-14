# -*- coding: utf-8 -*-
"""
美股因子策略 · 一键下单助手 (v33 双频版)

用法:
    python _update_signal.py                     # 刷新行情 + 出完整下单清单 (默认 21 日调仓)
    python _update_signal.py --rebal 10          # 切到 10 日调仓 (v26 风险调整最优)
    python _update_signal.py --rebal 10 --anchor 2026-09-14   # 从指定日起算调仓节奏
    python _update_signal.py --no-fetch          # 只出信号(不联网)
    python _update_signal.py --self-test         # 自检: 跑全部断言
    python _update_signal.py --capital 3000      # 指定本金(美元)
    python _update_signal.py --cny 10000 --fx 6.71
    python _update_signal.py --topk 3 --strategy 动量-1月反转
    python _update_signal.py --positions META:1,BE:2   # 告知实际持仓, 算真实盈亏
    python _update_signal.py --min-dv 1e7        # 放宽/收紧流动性闸门(美元)
    python _update_signal.py --no-gate           # 关闭闸门(复现旧口径, 仅用于对比)

退出码: 0 正常 / 2 数据不可用(勿下单)

v33 变更 —— 审流水线里最后一个"冻住"的参数: 流动性闸门阈值 GATE_DV = 5e6:
  M1 先厘清身份: 每腿只下 $745, 只占 $5M 的 0.0149%(放宽到 $0.5M 也只有 0.149%)
     => 【它不是容量约束, 是质量过滤器】—— 挡住 IREN/BMNR/ASTS/SMCI 这类薄流动性高波动票
     (28/81 只标的有过被挡记录, 平均每日被挡 10.9 只)。
  M2 闸门确实有价值但很小: 每个阈值都好于"无闸门"(胜率 52.4%~58.0%);
     $5M 对无闸门胜 55.0%(平均差 +2.5pp)。
  M3 闸门几乎不改变选股: $5M 只挡住 10/388 = 2.6% 的 Top-2 选票(194 个信号日里只有 9 天);
     平均只排除 1.8 只(71.9 -> 70.1, 池子 81 只) => 非常温和的过滤器。
  M4 ★ 阈值是【最小的自由度】: 10 日中位 72.9%~81.0%, 极差仅 8.1pp。
     三个自由度排序: 相位 108.7pp >> 窗口 42.5pp(v32) >> 阈值 8.1pp => 不值得调。
  M5 ★★ 「10 日 > 21 日」在 8/8 个阈值下【全部】成立 —— 与 v32 的窗口(4/8)形成对比:
     周期结论的脆弱性来自【窗口】, 不来自【闸门阈值】。重新验证冠军时盯窗口, 不盯闸门。
  M6 机制: 严闸门 = 偏大盘蓝筹 = 熊市抗跌(2022: -2.0% -> +16.6%)、
     牛市跑输(2020: +199.2% -> +89.0%)。这是风格暴露, 不是优劣。
  M7 [6] 段新增闸门纪律提示; 自检 95 -> 98 项。

v32 变更 —— 审【信号本身的参数】: Vortex 的窗口 n=14 从未被扫描过:
  L1 动机: v30 的教训是"凡是冻在某一个值上、从未扫过的参数, 都可能藏着未计价的自由度"。
     顺着这条线查主策略的【信号本身】—— Vortex 的窗口 n=14 是全项目写死的习惯值
     (69 个策略共用 vort14), 来源是技术分析惯例, 不是实测。
  L2 窗口确实是个自由度: 10 日调仓下相位中位从 38.5%(n=5) 走到 81.0%(n=14),
     极差 42.5pp。但【小于相位】—— 同窗口内相位极差最大 108.7pp > 窗口间 42.5pp。
     => v30 的相位问题仍是第一位, 窗口排第二。
  L3 ✅ n=14 在 10 日调仓下是【最优窗口】(排 1/8), 对其它 7 个窗口全胜(57%~94%)
     => 14 不是随手定的, 冠军参数经得起这次扫描, 不需要改。
  L4 ⚠ 但 n=14 在 21 日调仓下只排 5/8(落后最优 n=63 19.6pp) => 窗口最优值依赖周期。
  L5 ★ 「10 日 > 21 日」只在 4/8 个窗口下成立(在 n=5/7/42/63 下 21 日反而赢);
     而 n=14 恰好是 10 日领先幅度最大的窗口(+21.9pp) => 周期结论与窗口存在交互,
     「10 日是冠军」带一点"在 n=14 上看"的选择性。换因子/换窗口后必须重跑周期比较。
  L6 [6] 段新增窗口纪律提示; 自检 92 -> 95 项。

v31 变更 —— 试了"零成本"的替代分散方案(错开两腿调仓日), 结论是【不是免费午餐】:
  K1 动机: v30 证明相位风险大(极差 49pp), 而拆本金做相位分散买不起(拆本金=持股数翻倍)。
     看起来零成本的替代是【错开两腿调仓日】: 每只票仍持 $745、仍每 10 天调一次,
     只是两腿相差几天调 -> 10 天总成交仍是 2 卖 + 2 买 = $8, 成本不变。
  K2 成本前提【成立】: offset=0 时腿机械的成交笔数与 v27 复刻引擎【逐相位完全相同】(0 差异),
     且 phase=0 终值 $231,899.60 逐位一致 -> 腿机械本身不产生额外交易。
  K3 ⚠ 但错开引入一个【新的风险源】—— 两腿不等权。基线在"两只票同时换掉"时会把权重
     【免费调回等权】, 错开版做不到。实测两腿权重偏离 50/50 平均 32.3%(最小 11.3%)。
     这解释了为什么 offset=0(腿机械、不等权)的离散度反而【高于】基线: 极差 70.8pp vs 45.1pp。
  K4 ★ 【没有任何 offset 是免费午餐】。全部是"用中位换下限/换离散度"的互换。
     互换幅度最大的 offset=2: 最差 +8.1pp / IQR -20.6pp / std -6.1pp, 代价是中位 -3.7pp。
     滚动 252 日窗口里 offset=4/5/6 的离散度收窄在【前后半段同向】(稳健), 但中位也都下降。
     21 日调仓方向【相反】: 错开把中位从 58.6% 抬到 ~65-67%, 但离散度同步放大(60.8pp -> 70~83pp)。
  K5 等权版错开【买不起】: 若每次调仓同时把两腿调回等权 -> 每事件 4 条腿、事件频率翻倍
     -> 佣金 ~2.3 倍(683 -> ~1570 笔), 按 v28 拖累律再吃掉两位数 pp。
     => 相位风险在 $1,490 本金下【没有免费的对冲手段】。
  K6 [6] 段新增错开纪律提示; 自检 90 -> 92 项。

v30 变更 —— 补上【周期相位】这一层(此前所有 CAGR 都只是"某一个相位"的结果):
  J1 调仓周期不是一个连续参数, 它是一个【相位】: RB = {i | i >= anchor, (i-anchor)%rebal == 0}。
     anchor 固定取面板第 252 根 -> 换一天起步, 调仓日整体平移, 选票/成交价/持有期全变。
  J2 ★ 相位噪声极大: 把 anchor 取遍 10 个偏移, 10 日调仓 CAGR 在 51.3% ~ 100.6% 之间摆动
     (口径B共同窗口, 本金 $1,490, 极差 49.3pp / 标准差 17.2pp)。这比 v27~v29 讨论的
     任何一项交易成本都大一个量级 —— 也正面解释了 v29 里"晚一天"为什么一正一负。
     周期越长相位噪声越大: 42 日极差 99.8pp、最差相位 CAGR 仅 6.4%。
  J3 但【10 日冠军不是相位运气】, 四项证据一致:
       中位领先 21 日 +21.9pp(口径B) / +16.3pp(口径A); 标准差 17.2 vs 18.5pp(不更高);
       随机配对胜率 161/210 = 76.7%; 4 种执行口径(全换手/最小换手 x $1,490/$3,000)结论一致。
  J4 ⚠ 优势有边界: 最差 10 日(51.3%)仍低于最好 21 日(96.0%), 分布重叠 44.6pp;
     逐年只在 6/8 年领先, 2020、2021 两年明显跑输; 滚动 252 日窗口胜率 70.5%,
     且输的窗口全部落在 2020-03 ~ 2021-05(疫情后单边强趋势)。
     -> 机制: 10 日 = 更快跟上动量, 震荡/轮动市占优; 21 日 = 持仓更久, 单边强趋势占优。
  J5 正确读法: 「10 日调仓期望约 81%, 但你会落在 51%~101% 的哪个位置, 取决于起步日」,
     而不是「10 日能跑出 97%」(那只是最好的那个相位 #3)。
  J6 相位分散化在 $1,490 本金下【买不起】: 拆成 N 份 -> N=2 中位 -6.2pp, N=3 -20.1pp,
     N=5 -71.8pp 且 15% 的组合直接归零。因为 $2/笔是绝对金额成本, 拆 N 份就乘 N 倍。
  J7 [6] 段新增相位纪律提示; 自检 86 -> 90 项。

v29 变更 —— 补上【执行时点】的代价(此前只假设"成交价 = 开盘价"):
  I1 滑点其实不是问题: 每腿 $745 的订单只占池内最差一只股票成交额的 0.0009%
     (判据 order/ADV < 0.1% 即可忽略) -> 小资金在流动性上是绝对安全的。
     但滑点很"陡": 每 1bp 单边滑点约 -0.87pp CAGR(10 日), 因为一年换手 25 次。
  I2 ★ 时点才是真成本: 调仓日历不变、只把成交价从【开盘】换成【收盘】,
     10 日调仓 CAGR 93.1% -> 88.9% (-4.21pp), 21 日只 -0.93pp
     -> 代价与换手频率成正比。每「晚 1/4 个交易日」约 -1.36pp(10 日)。
  I3 ⚠ 别用「次日开盘」当"晚一天的成本": 那会把调仓日历整体后移, 混进【相位变化】
     (实测 10 日 -7.05pp 而 21 日 +2.31pp —— 一个变差一个变好, 显然不是时点效应)。
  I4 机制已核验(不是猜的): 调仓日【新买票的日内收益】系统性高于【卖出票】
     (ID(新)-ID(旧) = +0.0806% / 190 个样本; 21 日 +0.0852% / 92 个样本)
     -> 买在开盘 = 吃到这部分日内上涨。
  I5 综合口径: 理想(零佣金零滑点开盘) 98.5% -> 加佣金 93.1% -> 加 2bp 滑点 91.4%
     -> 若改收盘执行 87.2%。全部执行摩擦合计约 -7pp。
  I6 [6] 段新增时点纪律提示; 自检 83 -> 86 项。

v28 变更 —— 补上【本金维度】的成本口径(此前只有"单次佣金占净值"):
  H1 v27 报过"$1,490 时佣金占本金/年 11.6%~13.57%"。那个数字把本金【固定在 $1,490】
     来算, 而本策略年化 ~93%, 本金一年就翻倍 -> 佣金占【当期本金】的比例会迅速衰减。
     拿"第 1 年的比例"去和 CAGR 并列, 属口径混用, 成本被高估约 2 倍。
  H2 真正能和 CAGR 比较的是【拖累 pp】= CAGR(零佣金) - CAGR(实佣金)。实测:
     $1,490 -> 10 日 5.45pp / 21 日 2.88pp;  $3,000 -> 2.58 / 1.39pp。
  H3 拖累的成因只有一个: 那 $2/笔【固定】佣金不随本金缩放。碎股口径下策略本身是
     【尺度不变】的(零佣金 CAGR 对 $500~$50,000 极差 < 1e-13pp, 见 _v28_smallcap.py [2b]),
     所以本金对结果的【全部】影响都来自佣金 -> 经验律: 拖累(pp) ≈ 7,700 ÷ 本金($) (10 日)。
  H4 [4] 段新增本金维度提示 + 拖累告警; 自检 76 -> 83 项。
  H5 结论: 在本金 $1,490 下冠军【仍是 10 日】(CAGR 93.1% vs 58.4%, 领先 34.7pp),
     换手成本差 2.57pp 不构成换周期的理由。整股口径额外损失仅 0.71pp 且 0 条腿买不起
     -> 碎股不是瓶颈, 可以放心用。
  H6 修掉 hist_merge() 的【静默重复行】缺陷: 旧写法只给历史表补齐缺失列(pool_size/
     variant/rebal/anchor), 没给【新行】补 -> 新行这几列是 NaN, 而去重键用的是默认值,
     NaN != "-" => 该记录永远匹配不上, 每跑一次追加一次, 历史表静默堆重复。
     同时把行序改成按去重键【稳定排序】—— 否则用不同参数跑的先后顺序会让同一份数据
     产生不同行序, 制造无意义的 git diff 并破坏可复现性。配 3 条断言回归。

v27 变更 —— 调仓周期成为可调参数(--rebal):
  G1 v26 全策略总排名显示: 同一个 Vortex 信号, 21 日调仓 CAGR 59.9% / 回撤 -65.0%,
     10 日调仓 CAGR 94.8% / 回撤 -35.8% / 夏普 1.67 / Calmar 2.65 / 8 年全正。
     但生产脚本此前把 REBAL 写死为 21 -> 榜单上的最优策略在工具里【下不了单】。
  G2 --rebal 是【日历参数】, 不改变"选什么": 选股永远取最新一根的因子排序
     (select() 只看第 N-1 行), REBAL 只决定"今天算不算调仓日"和"下次哪天调"。
     自检里有一条断言专门证明这一点。
  G3 代价必须一起说: 10 日调仓的佣金是 21 日的【两倍】。实测(本金 $3,000, $2/笔):
     21 日每年约 $96 (占本金 3.2%), 10 日每年约 $202 (占本金 6.7%)。
     本金越小负担越重 —— 10 日每年约 25.3 次调仓 x $8 = $202:
         $1,490 -> 13.6%   $3,000 -> 6.7%   $10,000 -> 2.0%   $30,000 -> 0.7%
     ⚠ 上面是【全换手上限】(回测口径: 每次卖光再买回)。实盘用【最小换手】只动变了的
     那几条腿, 实测选票相同率仅 1.5%(10日) -> 省 14% -> 每年约 $173, $1,490 时 11.6%。
     两个数都要说清楚, 别混用。详见 美股Vortex10日实盘方案_v27.md。
  G4 留痕: rebal 计入 signal_snapshot.json 与 signal_history.csv 的【去重键】。
     同一天、同池子、同闸门口径下, 21 日与 10 日是两个不同结果(执行时点不同),
     不加进键就会重演 v24(池子规模)、v25(闸门变体)那两次"静默覆盖"。
  G5 --anchor: 调仓日历的起点。默认仍是面板第 START(252) 根, 与 v26 回测口径一致。
     作用: 换周期时"重新锚定"到你的实际起步日 —— 否则刚切到 10 日时, 工具会告诉你
     "今天无需操作", 把建仓日挡掉。v21 已实证【相位只解释 4~7% 的差异, 93% 是运气】,
     所以锚在哪天都行, 关键是有个确定的节奏。anchor 同样计入历史去重键。
  G6 [v27.1 修正] 日历 off-by-one: 引擎口径是"第 i-1 根收盘出信号 -> 第 i 根【开盘】成交"
     (见 _v27_cost.py engine()), 所以 RB 里的索引是【执行日】。v27 初版把"最后一根是
     执行日"误当成"最后一根是信号日", 报出 next_trading_day(last_d) —— 实测引擎在
     2026-09-11 开盘成交, 初版却报 2026-09-14, 晚 1 个交易日。按初版下单 = 在一个引擎
     不会成交的日子下单, 用的还是晚一根的信号 -> 跑的不是回测过的那套策略。
     修法: next_exec_offset() 纯函数统一口径, 自检 7 条断言(含遍历全样本命中率)。


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

REBAL_DEFAULT = 21  # 月度调仓(交易日) —— 默认值; 实际取值由 --rebal 决定(见下方参数段)
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
# v27 调仓周期: 日历参数, 与选股无关。默认 21 保持向后兼容; 10 日 = v26 风险调整最优。
REBAL = arg("--rebal", REBAL_DEFAULT, int)
if not isinstance(REBAL, int) or REBAL < 1:
    raise SystemExit(f"  --rebal 必须是 >= 1 的整数(交易日), 收到 {REBAL!r}")
if REBAL > 252:
    raise SystemExit(f"  --rebal {REBAL} 超过一年(252 交易日), 没有意义; v26 实测年频是最差的。")
# v27 调仓日历起点。None = 面板第 START(252) 根, 与 v26 回测口径完全一致。
ANCHOR = arg("--anchor", None, str)
# "-" 表示"用默认起点"。旧历史表没有 anchor 列, 按 "-" 处理 -> 用默认口径重跑仍能
# 原地更新旧行(结果确实相同), 而 --anchor 指定过日期的会另存一行。
ANCHOR_TAG = ANCHOR.strip() if ANCHOR else "-"
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

def dw(s):
    """字符串的【终端显示宽度】: CJK / 全角 / emoji 占 2 列, 其余占 1 列。

    Python 的 f-string 对齐按【字符数】算, 但终端按【显示宽度】渲染 ——
    中文标头("现价"=2 字符但 4 列宽)与数字("88.35"=5 字符 5 列)用同一格式串
    就必然错位。所有含中文标头的表格必须走 pad(), 不能用 f"{x:>11}"。
    """
    n = 0
    for ch in str(s):
        o = ord(ch)
        if (0x1100 <= o <= 0x115F) or (0x2E80 <= o <= 0xA4CF) or (0xAC00 <= o <= 0xD7A3) \
           or (0xF900 <= o <= 0xFAFF) or (0xFE30 <= o <= 0xFE6F) or (0xFF00 <= o <= 0xFF60) \
           or (0xFFE0 <= o <= 0xFFE6) or (0x1F300 <= o <= 0x1FAFF):
            n += 2
        else:
            n += 1
    return n

def pad(s, w, align="l"):
    """按显示宽度填充到 w 列 (align: 'l' 左对齐 / 'r' 右对齐)"""
    s = str(s)
    n = w - dw(s)
    if n <= 0:
        return s
    return (" " * n + s) if align == "r" else (s + " " * n)


def floor_shares(x, nd=4):
    """目标股数**向下取整**到 nd 位小数 —— 碎股预算必须 floor, 不能 round。

    预算 `bud` 是【已扣佣金】的可投金额, 所以 Σ(股数×价) 只要向上溢出 1 美分,
    加上佣金就 > 净值 ⇒ 智能体侧风控以「留现金 < 0」把**整个建仓**拒绝
    (不是少买一点, 是整单不做)。

    2026-09-14 实测 (v27.1 快照, 本金 $1500 Top2):
      round 口径 → META 1.1543×648.03 = $748.0210 ⇒ 合计 $1496.0186 + $4 = $1500.0186
                   ⇒ 超 1.9 美分 ⇒ 建仓被风控整单拒绝
      floor 口径 → META 1.1542×648.03 = $747.9562 ⇒ 合计 $1495.9600 + $4 = $1499.9600 ✓

    注意同文件的整股口径早已是 `int(bud // p)`(就是 floor) —— 这里与它对齐,
    不再让"整股用 floor、碎股用 round"两种口径并存。

    `round(..., 6)` 只为消掉浮点噪声 (1.1542*1e4 可能算成 11541.999999),
    否则会把本来精确的值无故降一档。股数非负 ⇒ int() 截断即向下取整。
    """
    f = float(10 ** nd)
    return int(round(float(x) * f, 6)) / f

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

def next_exec_offset(last_i, anchor_i, rebal):
    """最后一根是 last_i 时, 距【下一次执行】还有几个交易日 (恒在 [1, rebal])。

    引擎口径 (见 _v27_cost.py engine()): 第 i 根【开盘】成交, 信号取第 i-1 根收盘 ——
        RB = {i | (i - anchor_i) % rebal == 0} 里的索引是【执行日】, 不是信号日。
    工具手上只有到 last_i 的数据, 最早能执行的是 last_i + 1; 从它开始往后数,
    数到第一个执行日为止。故:
        offset = rebal - ((last_i - anchor_i) % rebal)
    边界: last_i 本身就是执行日 -> offset = rebal (本日开盘已成交, 要再等一整轮);
          last_i 是执行日的前一根 -> offset = 1 (下一交易日开盘就该动手)。
    """
    return rebal - ((last_i - anchor_i) % rebal)

# ---- v28: 佣金拖累的经验律 (本金维度) ----
# 数据来源: _v28_smallcap.py / _v28_smallcap.json（复刻引擎, $2/笔, 最小换手, 碎股口径）。
# 关键前提: 碎股口径下策略本身是【尺度不变】的 —— 零佣金 CAGR 对 $500~$50,000 任意本金
#   极差 < 1e-13pp（自检有断言）。所以【本金对结果的唯一影响, 就是那 $2/笔固定佣金】。
# 实测「拖累(pp) x 本金($)」在 $1,490 以上稳定:
#   21 日调仓 ≈ 4,200   10 日调仓 ≈ 7,700
# 于是拖累(pp) ≈ K / 本金($)。本金翻倍 -> 拖累减半。本金 < $1,000 时该近似失效(拖累涨得更快)。
DRAG_K = {21: 4200.0, 10: 7700.0}
DRAG_K_DEFAULT = 4200.0

def comm_drag_pp(capital, rebal=21):
    """按本金估算【佣金拖累】, 单位 pp(百分点)。

    定义: 拖累 = CAGR(零佣金) - CAGR(实佣金)。这与"每年佣金 ÷ 本金"【不是一回事】——
    后者把本金固定在当期不动, 而本策略年化很高, 本金一年就翻倍, 佣金占当期本金的比例
    会迅速衰减。拿"第 1 年的比例"去和 CAGR 比较会严重高估成本(约 2 倍), 见 v28 报告勘误。
    """
    if capital is None or capital <= 0:
        return float("nan")
    k = DRAG_K.get(int(rebal))
    if k is None:
        # 未实测的周期: 按"拖累近似线性于调仓频率"外推(21 日为基准)。仅作数量级提示。
        k = DRAG_K_DEFAULT * (21.0 / int(rebal))
    return k / float(capital)

# ---- v29: 执行时点的代价（实测, 来源 _v29_slippage.py / .json）----
# 调仓日历不变、只改成交价 -> 这是【纯时点】效应。
# 「开盘成交」相对「收盘成交」多出来的 CAGR（单位 pp，正数表示开盘更好）:
#   10 日 +4.21pp   21 日 +0.93pp      <- 代价与换手频率成正比
# 「每晚 1/4 个交易日」的代价（pp，负数）:
#   10 日 -1.36pp   21 日 -0.29pp
# ⚠ 不要用「次日开盘」的差来当"晚一天的成本"——那会把调仓日历整体后移,
#   混进【相位变化】(实测 10 日 -7.05pp 而 21 日 +2.31pp, 一个变差一个变好,
#   显然不是时点效应)。v21/v26 已确认相位对收益的解释力有 4~7%。
EXEC_TIME_COST = {10: 4.21, 21: 0.93}
EXEC_TIME_COST_PER_QUARTER = {10: -1.36, 21: -0.29}

# ---- v30: 周期【相位】的量级（实测, 来源 _v30_phase.py / _v30_phase.json）----
#   anchor 取遍全部偏移后, 各周期 CAGR 的分布（口径B 共同窗口, 本金 $1,490, 最小换手）:
#     周期   最差    中位    最好    极差
#     10日  51.3%  81.0%  100.6%  49.3pp
#     21日  33.1%  59.0%   96.0%  62.9pp
#   -> 相位噪声远大于 v27~v29 讨论的任何一项成本。但冠军结论不变:
#      10 日 vs 21 日 随机配对胜率 161/210 = 76.7%, 4 种执行口径一致。
PHASE_SPAN = {10: 49.3, 21: 62.9}        # 相位极差(pp, 口径B)
PHASE_MEDIAN = {10: 81.0, 21: 59.0}      # 相位中位 CAGR(%)
PHASE_MN = {10: 51.3, 21: 33.1}          # 最差相位 CAGR(%)
PHASE_MX = {10: 100.6, 21: 96.0}         # 最好相位 CAGR(%)
PHASE_WIN_RATE = 76.7                    # 10日 vs 21日 随机配对胜率(%)

# ---- v31: 错开调仓的代价（实测, 来源 _v31_stagger.py / _v31_stagger.json）----
# 「把 2 只票拆成 2 条腿、错开调仓日」看起来零成本(10 天总成交仍是 2 卖 + 2 买 = $8),
# 实测【不是免费午餐】:
#   1) 引入【两腿不等权】—— 基线在"两只票同时换掉"时会把权重免费调回等权, 错开版做不到。
#      实测两腿权重偏离 50/50 平均 32.3%(最小 11.3%)。这是错开的固有代价。
#      (这也解释了 offset=0 的离散度反而【高于】基线: 极差 70.8pp vs 45.1pp)
#   2) 没有任何 offset 能同时改善中位/最差/离散度 —— 全部是"用中位换下限/换离散度"的互换。
#      互换幅度最大 offset=2: 最差 +8.1pp / IQR -20.6pp / std -6.1pp, 代价是中位 -3.7pp。
#   3) 若每次调仓同时把两腿调回等权 -> 每事件 4 条腿、事件频率翻倍 -> 佣金 ~2.3 倍
#      (基线 683 笔 -> ~1570 笔), 按 v28 拖累律会再吃掉两位数 pp。=> 等权版错开买不起。
STAGGER_WDEV_AVG = 32.3      # 两腿权重偏离 50/50 的平均值(%)
STAGGER_WDEV_MIN = 11.3      # 最小偏离(%)
STAGGER_EQW_MULT = 2.3       # 等权版错开的佣金倍数(基线 683 笔 -> ~1570 笔)
STAGGER_SWAP = {             # 互换幅度最大的 offset=2 的四项变化(pp)
    "offset": 2, "d_median": -3.7, "d_worst": 8.1, "d_iqr": -20.6, "d_std": -6.1,
}

# ---- v32: 因子【窗口】的自由度（实测, 来源 _v32_window.py / _v32_window.json）----
# Vortex 的窗口 n=14 是全项目写死的【习惯值】, v32 才第一次被扫描(8 个窗口 x 2 周期 x 全相位)。
#   1) 窗口确实是个自由度: 10 日调仓下相位中位 38.5%(n=5) ~ 81.0%(n=14), 极差 42.5pp。
#   2) 但【小于相位】: 同窗口内相位极差最大 108.7pp > 窗口间中位极差 42.5pp
#      -> v30 的相位问题仍是第一位的, 窗口排第二。
#   3) ✅ n=14 在 10 日调仓下是【最优窗口】(排 1/8), 对其它 7 个窗口全胜(57%~94%)
#      -> 14 不是随手定的, 冠军参数经得起扫描, 不需要改。
#   4) ⚠ 但 n=14 在 21 日调仓下只排 5/8(落后最优 n=63 19.6pp) -> 窗口最优值依赖周期。
#   5) ★ 「10 日 > 21 日」只在 4/8 个窗口下成立(在 n=5/7/42/63 下 21 日反而赢);
#      而 n=14 恰好是 10 日领先幅度最大的窗口(+21.9pp) -> 周期结论与窗口存在交互,
#      「10 日是冠军」带一点"在 n=14 上看"的选择性。
WIN_SPAN = 42.5              # 10 日中位在 8 个窗口间的极差(pp)
WIN_MAX_PHASE_SPAN = 108.7   # 同窗口内相位极差最大值(pp) —— 大于窗口间极差
WIN_N = 8                    # 扫描的窗口数
WIN_BEST10 = 14              # 10 日调仓下的最优窗口
WIN_RANK14_10 = 1            # n=14 在 10 日下的排名
WIN_BEST21 = 63              # 21 日调仓下的最优窗口
WIN_RANK14_21 = 5            # n=14 在 21 日下的排名
WIN_14_VS_ALL = 7            # n=14 在 10 日下对其它窗口全胜(7/7)
WIN_10D_WINS = 4             # 「10 日 > 21 日」成立的窗口数(共 8)

# ---- v33: 流动性闸门【阈值】的自由度（实测, 来源 _v33_gate.py / _v33_gate.json）----
# GATE_DV = 5e6 是流水线里最后一个"冻在一个值上、从未扫过"的参数。实测:
#   1) ⚠ 它【不是容量约束】: 每腿只下 $745, 占 $5M 的 0.0149%(放宽到 $0.5M 也只有 0.149%)。
#      真实身份是【质量过滤器】—— 挡住 IREN/BMNR/ASTS/SMCI 这类薄流动性高波动票
#      (28/81 只标的有过被挡记录, 平均每日被挡 10.9 只)。
#   2) 闸门确实有价值但很小: 每个阈值都好于"无闸门"(胜率 52.4%~58.0%);
#      $5M 对无闸门胜 55.0%(平均差 +2.5pp)。
#   3) 闸门几乎不改变选股: $5M 只挡住 10/388 = 2.6% 的 Top-2 选票(194 个信号日里只有 9 天)。
#      平均只排除 1.8 只(池子 81 只: 71.9 -> 70.1) => 非常温和的过滤器。
#   4) ★ 阈值是【最小的自由度】: 10 日中位 72.9%~81.0%, 极差仅 8.1pp。
#      三个自由度排序: 相位 108.7pp >> 窗口 42.5pp(v32) >> 阈值 8.1pp => 不值得调。
#   5) ★★ 「10 日 > 21 日」在 8/8 个阈值下【全部】成立 —— 与 v32 的窗口(4/8)对比:
#      周期结论的脆弱性来自【窗口】, 不来自【闸门阈值】。
#   6) 机制: 严闸门 = 偏大盘蓝筹 = 熊市抗跌(2022: -2.0% -> +16.6%)、
#      牛市跑输(2020: +199.2% -> +89.0%)。这是风格暴露, 不是优劣。
GATE_SPAN = 8.1              # 10 日中位在 8 个阈值间的极差(pp)
GATE_N = 8                   # 扫描的阈值数
GATE_MEDIAN_LO = 72.9        # 10 日中位下限(%)
GATE_MEDIAN_HI = 81.0        # 10 日中位上限(%)
GATE_BLOCKED_PCT = 2.6       # $5M 挡住 Top-2 选票的比例(%)
GATE_BREADTH_CUT = 1.8       # $5M 平均排除的标的数
GATE_ORDER_RATIO = 0.0149    # 单笔占闸门的比例(%) —— 证明它不是容量约束
GATE_WIN10_WINS = 8          # 「10 日 > 21 日」成立的阈值数(共 8)

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
LAST_FETCH_FAILED = []      # [(code, ret)] —— 供主流程提示「哪几只还在用旧数据」


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
    failed = []
    RETRY, COOL = 2, (2.0, 5.0)
    for code in UNI + ["US.VOO"]:
        out = (1, None)
        # 富途接口限额有两层, 频率那层(约 60 次/30 秒)超限是【立即失败且不抛异常】的:
        # 不冷却重试就会把「扫全池」静默变成「扫了一部分」, 而它不会崩溃、只会给出
        # 看起来合理的错答案 —— 比报错危险得多。所以失败必须重试, 不能直接放弃。
        for attempt in range(RETRY + 1):
            out = ctx.request_history_kline(code, start=start, end=end, ktype=SubType.K_DAY,
                                            autype=AuType.QFQ, max_count=90)
            if out[0] == 0 and out[1] is not None and len(out[1]) > 0:
                break
            if attempt < RETRY:
                print(f"  RETRY {code} ret={out[0]} (第 {attempt + 1} 次, 冷却 {COOL[attempt]}s)")
                time.sleep(COOL[attempt])
        if out[0] != 0 or out[1] is None or len(out[1]) == 0:
            print(f"  FAIL {code} ret={out[0]}（已重试 {RETRY} 次仍失败）")
            failed.append((code, out[0]))
            continue
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
    total = len(UNI) + 1
    ratio = ok_n / total
    print(f"  已刷新 {ok_n}/{total} 只")
    if failed:
        # 光说「不完整」没用 —— 必须点名是哪几只、它们停在哪个交易日,
        # 否则用户无法判断这份信号能不能信(这正是「不报错、只让结果悄悄变差」的缺陷)
        print(f"  ⚠ 刷新不完整({ok_n}/{total}) —— 下面 {len(failed)} 只仍在用【旧数据】:")
        for code, _ in failed:
            p = os.path.join(LONGDIR, code.replace(".", "_") + ".csv")
            try:
                _s = pd.read_csv(p, usecols=["time_key"])["time_key"].dropna()
                last = str(_s.iloc[-1])[:10] if len(_s) else "-"
            except Exception:
                last = "无本地文件"
            print(f"      {code.replace('US.', ''):<6} 本地最后交易日 {last}")
        print(f"     半份数据会让信号失真: 这些票的因子滞后 {len(failed)} 只, 排名不可全信")
    LAST_FETCH_FAILED[:] = failed
    if ratio >= 0.95:
        return True
    # 部分失败: 只有"信号相关标的"齐全才可用
    return ratio >= 0.9

# ==================== 信号 ====================
def zs(x):
    """与 _rank_all_strategies.zs 逐字一致: 必须把 ±inf 转成 NaN。

    横截面标准差为 0 时 (该行所有有效标的取值完全相同) div 会给出 ±inf,
    argsort 会把 inf 排到最前面 -> 选出一个"得分无穷大"的票。
    回测引擎一直有 .replace([inf,-inf], nan), 生产脚本原先没有 —— 口径不一致, 已对齐。
    """
    m, s = x.mean(axis=1), x.std(axis=1)
    return x.sub(m, axis=0).div(s, axis=0).replace([np.inf, -np.inf], np.nan)
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
            elif LAST_FETCH_FAILED:
                # 刷新率达标但仍有零星失败: 不能因为"整体够了"就当没发生过
                print(f"  ⚠ {len(LAST_FETCH_FAILED)} 只标的本次未刷新成功, 它们参与排名的是【旧数据】")
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

    print("\n" + "=" * 116)
    print(f"[3] 调仓日历   （周期 {REBAL} 个交易日"
          + ("，默认月频" if REBAL == REBAL_DEFAULT else "，非默认：佣金约为月频的 "
             f"{REBAL_DEFAULT/REBAL:.1f} 倍") + "）")
    print("=" * 116)
    # v27: 日历起点。默认 = 面板第 START 根(与 v26 回测口径一致);
    # --anchor 用于换周期时"重新锚定"到实际起步日, 否则刚切周期会告诉你"今天无需操作"。
    # 支持【未来日期】: 比如"把 9/14 当起点", 而面板最后一根还是 9/11 ——
    # 这种锚点没法映射成索引, 但可以按交易日历投影, 首次调仓就是投影出来的那天。
    anchor_i = START
    anchor_virtual = False
    if ANCHOR:
        try:
            _ad = datetime.date.fromisoformat(ANCHOR.strip())
        except ValueError:
            print(f"  ❌ --anchor 格式应为 YYYY-MM-DD, 收到 '{ANCHOR}'")
            return 2
        _cand = [i for i in range(N) if dp[i].date() >= _ad]
        if not _cand:
            _k, _d = 0, last_d
            while _d < _ad:
                _d = next_trading_day(_d); _k += 1
            anchor_i = (N - 1) + _k
            anchor_virtual = True
            print(f"  日历起点(anchor): {_ad} -> 投影到面板之后 {_d}（首次调仓）")
        elif _cand[0] < START:
            print(f"  ❌ --anchor {_ad} 落在预热期内(须 >= {dp[START].date()}); "
                  f"该区间净值恒为本金, 不能当调仓起点")
            return 2
        else:
            anchor_i = _cand[0]
            if dp[anchor_i].date() != _ad:
                print(f"  [!] --anchor {_ad} 不是交易日 -> 顺延到 {dp[anchor_i].date()}")
            print(f"  日历起点(anchor): {dp[anchor_i].date()}"
                  + ("   (默认: 面板第 252 根)" if anchor_i == START else ""))
    # v27.1 日历修正 —— 旧写法有 off-by-one, 会把执行日报晚 1 个交易日。
    # 引擎口径: 第 i 根【开盘】成交, 信号取第 i-1 根收盘 (见 _v27_cost.py engine())。
    # 所以 RB 里的索引是【执行日】。旧写法 is_rebal = (N-1 in RB) 把"最后一根是执行日"
    # 当成了"最后一根是信号日", 于是报 next_trading_day(last_d) —— 实测: 引擎 2026-09-11
    # 开盘成交, 旧写法却报 2026-09-14。按旧写法下单 = 在一个引擎不会成交的日子下单,
    # 用的还是晚一根的信号 -> 跑的根本不是回测过的那套策略。
    RB = [i for i in range(anchor_i, N) if (i - anchor_i) % REBAL == 0]
    days_to_next = next_exec_offset(N - 1, anchor_i, REBAL)   # ∈ [1, REBAL]
    act_next_open = (days_to_next == 1)          # 下一交易日开盘就该动手
    just_exec = (days_to_next == REBAL)          # 最后一根本身是执行日 -> 其开盘已成交
    is_rebal = just_exec                         # 保留旧字段名(语义: 最后一根是执行日)
    last_reb_date = dp[RB[-1]].date() if RB else None
    exec_d = project_trading_days(last_d, days_to_next)
    if act_next_open:
        print(f"  ⚡ 信号日就是最后一根({last_d}) -> 下一交易日 {exec_d} 开盘执行")
        if anchor_virtual:
            print(f"     (anchor 在面板之后, 这是锚定后的【首次建仓】)")
    elif anchor_virtual:
        print(f"  锚点在面板之后: 首次调仓 {exec_d}（{days_to_next} 个交易日后）"
              f" -> 当前【无需操作】")
    elif just_exec:
        print(f"  ⚠ 最新一根({last_d})是调仓日: 它的【开盘】已按前一日收盘信号成交完毕")
        print(f"     -> 当前【无需操作】; 下次调仓约 {exec_d}（{days_to_next} 个交易日后）")
    else:
        past_td = N - 1 - RB[-1]
        print(f"  最近调仓 {last_reb_date}（{past_td} 个交易日前）-> 当前【无需操作】")
        print(f"  下次调仓约 {exec_d}（{days_to_next} 个交易日后, 按交易日历推算）")
        # 最常被问: "为什么不是下一个交易日 / 下周一?" —— 周期是【交易日栅格】,
        # 不是自然日、也不是"每周一"。从 anchor 起每 REBAL 个交易日一格, 中间一律不动。
        print(f"     = 上次调仓 {last_reb_date} + {REBAL} 个交易日"
              f"（已过 {past_td} + 还需 {days_to_next} = {REBAL}）")
        _nd = next_trading_day(last_d)
        print(f"     为什么不是最近一个交易日 {_nd}: 调仓日是 anchor({dp[anchor_i].date()}) 起"
              f" 每 {REBAL} 个交易日一格的固定栅格 —— 周期数的是【交易日】不是自然日, "
              f"也不是\"每周一\"。栅格外的日子一律不动。")
    if not act_next_open:
        print("     (下面 [4] 的选票是【最新一根】的信号, 仅供预览; "
              "真正下单要等 ⚡ 那一天重跑本工具)")
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
    # 佣金必须【先扣】: 目标金额若按 净值/TOPK 算, 碎股方案合计正好等于净值,
    # 再付佣金就超支了($1,500 下超 $4; 本金越小/票数越多越明显)。
    n_sell, n_buy = (TOPK if POSITIONS else 0), TOPK
    fee = (n_sell + n_buy) * COMM
    avail = max(0.0, NET - fee)            # 真正能投出去的钱
    print(f"\n  可投 ${avail:,.0f} = 净值 ${NET:,.0f} − 预留佣金 ${fee:.0f}"
          f"（{n_sell} 卖 + {n_buy} 买 x ${COMM:.0f}）")
    print("  " + pad("标的", 8) + pad("现价", 11, "r") + pad("目标金额", 11, "r")
          + pad("整股", 7, "r") + pad("整股金额", 11, "r")
          + pad("碎股股数", 11, "r") + pad("建议", 10, "r"))
    print("  " + "-" * 72)
    tot = 0.0
    bud = avail / TOPK
    for j in pick:
        c = UNI[j].replace("US.",""); p = float(C.values[N-1, j])
        sh = int(bud // p) if p > 0 else 0
        tot += sh * p
        print("  " + pad(c, 8) + pad(f"${p:,.2f}", 11, "r") + pad(f"${bud:,.0f}", 11, "r")
              + pad(str(sh), 7, "r") + pad(f"${sh*p:,.2f}", 11, "r")
              + pad(f"{bud/p:.4f}" if p > 0 else "-", 11, "r")
              + pad("碎股" if sh == 0 else "整股OK", 10, "r"))
    cash_left = avail - tot
    print(f"\n  整股投入 ${tot:,.0f} (占净值 {tot/NET*100:.0f}%), 闲置 ${cash_left:,.0f}"
          f" (其中已含未投出的佣金预留)")
    print(f"  佣金 卖 {n_sell}x${COMM:.0f} + 买 {n_buy}x${COMM:.0f} = ${fee:.0f} (占净值 {fee/NET*100:.2f}%)")
    if tot / NET < 0.6:
        print(f"  ❌ 整股买不动 -> 必须用碎股(富途支持按金额下单), 否则 {cash_left/NET*100:.0f}% 本金空转")
    print(f"  碎股方案: 每只按金额 ${bud:,.0f} 买入, 份额 "
          + ", ".join(f"{UNI[j].replace('US.','')} {bud/float(C.values[N-1,j]):.4f}股" for j in pick))

    # ---- v28: 本金维度 —— 佣金拖累 ----
    # 上面那句"佣金占净值 x%"是【单次】比例, 不是年费率。能拿来和 CAGR 比较的是
    # 【拖累 pp】= CAGR(零佣金) - CAGR(实佣金)。用"每年佣金÷本金"会高估约 2 倍 ——
    # 因为它把本金固定在当期, 而本策略年化很高, 本金一年就翻倍。见 v28 报告勘误。
    _drag = comm_drag_pp(NET, REBAL)
    _reb_yr = 252.0 / REBAL
    _k = DRAG_K.get(int(REBAL), DRAG_K_DEFAULT * 21.0 / int(REBAL))
    print(f"\n  【本金维度】佣金 ${COMM:.0f}/笔是【固定费】, 不随本金缩放 -> 本金越小, 拖累越重")
    print(f"    本周期 {REBAL} 日调仓 ≈ 每年 {_reb_yr:.1f} 次; 全换手年佣金 ≈ "
          f"${_reb_yr * TOPK * 2 * COMM:,.0f}")
    print(f"    预期佣金拖累 ≈ {_drag:.2f}pp   经验律: 拖累(pp) ≈ {_k:,.0f} ÷ 本金($); "
          f"本金翻倍, 拖累减半")
    if _drag > 5.0:
        print(f"    ⚠ 拖累 {_drag:.2f}pp > 5pp —— 本金偏小, 换手成本被放大。"
              f"(10 日调仓要到 $8,000 左右才能压到 1pp 以内)")
    if int(REBAL) != REBAL_DEFAULT:
        _d21 = comm_drag_pp(NET, REBAL_DEFAULT)
        print(f"    对照 {REBAL_DEFAULT} 日调仓: 拖累约 {_d21:.2f}pp —— 两周期换手成本只差 "
              f"{_drag - _d21:+.2f}pp, 远小于它们本身的 CAGR 差, 不构成换周期的理由")

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
    else:
        # 没持仓时下面一律按"首次建仓"算 —— 若用户其实已在上次调仓日买入却没录入,
        # 就会算出【重复买入同一只票】。这不会报错, 只会悄悄把仓位加倍, 必须显式提醒。
        print("  ⚠ 未检测到持仓(portfolio.json 缺失/为空) -> 下面按【首次建仓】计算。")
        print("     若你已在上次调仓日建仓, 请先录入, 否则这里会让你把同一只票再买一遍:")
        print("     python _update_signal.py --bought \"SWKS:8.4663@88.35,META:1.1543@648.03\"")
        print("     (格式 CODE:股数@成本价, 逗号分隔; 录入后自动算盈亏与最小换手)")
    tgt_amt = avail / TOPK        # 与 [4] 同口径: 已预留佣金, 否则两处加总都超净值
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
    print("  " + pad("标的", 8) + pad("动作", 6, "r") + pad("股数", 12, "r")
          + pad("金额", 12, "r") + pad("现持", 12, "r") + "   备注")
    print("  " + "-" * 76)
    fee_est = 0.0; act = 0
    for c, side, sh, amt, cur, note in orders:
        if side != "持有": act += 1; fee_est += COMM
        s = f"{sh:.4f}" if side != "持有" else f"{cur:.4f}"
        print("  " + pad(c, 8) + pad(side, 6, "r") + pad(s, 12, "r")
              + pad(("$%.0f" % abs(amt)) if amt else "-", 12, "r")
              + pad(f"{cur:.4f}", 12, "r") + "   " + note)
    lab = "首次建仓" if not POSITIONS else "最小换手"
    print(f"  预计佣金 ${fee_est:.0f}（{lab} 方案）")
    print(f"  对比: 无脑全卖全买 = ${TOPK*COMM*2:.0f}; 最小换手省下 ${TOPK*COMM*2-fee_est:.0f}")
    _buy_tot = sum(amt for _, side, _, amt, _, _ in orders if side == "买入")
    print(f"  买入合计 ${_buy_tot:,.0f} + 佣金 ${fee_est:.0f} = ${_buy_tot+fee_est:,.0f} "
          f"≤ 净值 ${NET:,.0f}" + ("  ✅" if _buy_tot + fee_est <= NET + 1e-9 else "  ❌ 超支!"))

    if BOUGHT:
        rec = parse_bought(BOUGHT)
        json.dump({"as_of": str(last_d), "shares": rec}, open(PORTFILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(f"  ✅ 已记录成交到 {os.path.basename(PORTFILE)}（下次自动读取算盈亏）")

    print("\n" + "=" * 116); print("[6] 执行须知 (实务约束)"); print("=" * 116)
    print(f"  1. 下单时点: {exec_d if exec_d else '下次调仓日'} 北京时间 {open_time(exec_d) if exec_d else '-'} 开盘")
    print("     回测成交价 = 开盘价; 夜盘(北京8:00-16:00)/盘前(16:00-21:30)流动性薄、价差大, 不要用")
    print("  2. 订单类型: 碎股通常只支持市价单; 整股可开盘价限价")
    # v29: 执行时点是有价格的。实测 10 日调仓「买在开盘」vs「买在收盘」差 -4.21pp CAGR,
    # 且每「晚 1/4 个交易日」约 -1.36pp; 21 日只差 -0.93pp（代价与换手频率成正比）。
    _cur = EXEC_TIME_COST.get(int(REBAL), EXEC_TIME_COST[10])
    _oth = 21 if int(REBAL) == 10 else 10
    _pq = EXEC_TIME_COST_PER_QUARTER.get(int(REBAL), EXEC_TIME_COST_PER_QUARTER[10])
    print(f"  2b. ⚡ 时点纪律(v29 实测): 「开盘成交」比「收盘成交」在本周期({REBAL} 日)下多 "
          f"{_cur:.2f}pp CAGR")
    print(f"      （对照 {_oth} 日 {EXEC_TIME_COST[_oth]:.2f}pp）。每「晚 1/4 个交易日」约 "
          f"{_pq:.2f}pp。拖到收盘 = 白丢这么多收益。")
    # 两段是独立实测, 不是同一个数的 4 等分: 4 x 1/4 日累计与"整日"差 ~1.2pp(非线性)。
    # 不明说会被当成数字打架 —— 按 4.21/4=1.05 反推是错的, 1.36 才是实测值。
    print(f"      注: 两者是独立实测而非四等分, 4×1/4 日累计 {-_pq*4:.2f}pp vs 整日 "
          f"{_cur:.2f}pp（差 {abs(_pq*4+_cur):.2f}pp, 非线性）。")
    print(f"      滑点反而无所谓：$745 订单只占成交额 0.0009%（order/ADV < 0.1% 即可忽略）。")
    # v30: 相位纪律 —— 周期是个"相位", 不是参数; 换 anchor 会让结果不可比。
    _pm = PHASE_MEDIAN.get(int(REBAL), PHASE_MEDIAN[10])
    _pn = PHASE_MN.get(int(REBAL), PHASE_MN[10])
    _px = PHASE_MX.get(int(REBAL), PHASE_MX[10])
    _ps = PHASE_SPAN.get(int(REBAL), PHASE_SPAN[10])
    _po = 21 if int(REBAL) == 10 else 10
    print(f"  2c. 🎲 相位纪律(v30 实测): 本周期({REBAL} 日)的 CAGR 不是一个数, 而是一段区间 ——")
    print(f"      anchor 取遍 {REBAL} 个偏移后: 最差 {_pn:.1f}% / 中位 {_pm:.1f}% / 最好 {_px:.1f}%"
          f"（极差 {_ps:.1f}pp）")
    print(f"      相位噪声比上面所有交易成本都大一个量级。但周期选择本身仍有优势:")
    print(f"      {REBAL} 日中位 {_pm:.1f}% vs {_po} 日 {PHASE_MEDIAN[_po]:.1f}%"
          f"，随机配对胜率 {PHASE_WIN_RATE:.1f}%。")
    print(f"      ⇒ 别在换周期时改 anchor(否则新旧结果不可比); 也别试图挑「好日子」起步 ——")
    print(f"        相位收益事前无法判断。用默认起点, 接受这段区间。")
    print(f"      ⇒ 相位分散化在本金 ${NET:,.0f} 下买不起: 拆 N 份 -> N=2 中位 -6.2pp、"
          f"N=3 -20.1pp、N=5 -71.8pp(15% 归零)。")
    # v31: 错开纪律 —— "错开两腿调仓日"不是免费午餐。
    _sw = STAGGER_SWAP
    print(f"  2d. 🔀 错开纪律(v31 实测): 别为了摊薄相位风险而把两腿调仓日错开 ——")
    print(f"      它成本不变(笔数确实一样), 但会引入【两腿不等权】(偏离 50/50 平均 "
          f"{STAGGER_WDEV_AVG:.1f}%)。")
    print(f"      实测没有任何 offset 是免费午餐, 全部是互换。最大互换 offset={_sw['offset']}: "
          f"最差 {_sw['d_worst']:+.1f}pp、IQR {_sw['d_iqr']:+.1f}pp, 代价中位 {_sw['d_median']:+.1f}pp。")
    print(f"      ⇒ 保持两腿等权。把权重调回等权的成本是佣金 ~{STAGGER_EQW_MULT:.1f} 倍"
          f"(683 -> ~1570 笔), 比它带来的好处更贵。")
    # v32: 窗口纪律 —— 信号窗口(14)也是一个自由度, 且周期结论依赖窗口。
    _wb = WIN_BEST10 if int(REBAL) == 10 else WIN_BEST21
    _wr = WIN_RANK14_10 if int(REBAL) == 10 else WIN_RANK14_21
    print(f"  2e. 🔬 窗口纪律(v32 实测): 信号窗口(14)也是一个自由度 ——")
    print(f"      10 日中位在 {WIN_N} 个窗口间从 38.5% 走到 81.0%（极差 {WIN_SPAN:.1f}pp），"
          f"但小于相位极差 {WIN_MAX_PHASE_SPAN:.1f}pp。")
    print(f"      ✅ 本周期({REBAL} 日)下最优窗口 = n={_wb}"
          f"（n=14 排 {_wr}/{WIN_N}）；n=14 在 10 日下对其它窗口 {WIN_14_VS_ALL}/7 全胜。")
    print(f"      ⚠ 但「10 日 > 21 日」只在 {WIN_10D_WINS}/{WIN_N} 个窗口下成立 ——"
          f" 换因子/换窗口后必须重跑周期比较, 别沿用「10 日更好」。")
    # v33: 闸门纪律 —— 闸门是"质量过滤器"不是"容量约束", 且阈值这个自由度很小。
    if USE_GATE and MIN_DV > 0:
        _leg = NET / max(int(TOPK), 1)
        print(f"  2f. 🧱 闸门纪律(v33 实测): 闸门(${MIN_DV/1e6:.1f}M)不是容量约束 ——")
        print(f"      每腿 ${_leg:,.0f} 只占阈值的 {_leg/MIN_DV*100:.4f}%，真实身份是"
              f"【质量过滤器】（挡住薄流动性高波动票, 如 IREN/BMNR/ASTS）。")
        print(f"      阈值自由度仅 {GATE_SPAN:.1f}pp（相位 {WIN_MAX_PHASE_SPAN:.1f}pp / "
              f"窗口 {WIN_SPAN:.1f}pp）⇒ 不值得调；「10 日 > 21 日」在 "
              f"{GATE_WIN10_WINS}/{GATE_N} 个阈值下全成立。")
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
            "data_last": str(last_d), "rebal_day": (str(dp[RB[-1]].date()) if RB else None),
            "is_rebal_day": bool(is_rebal),
            # v27.1: 最后一根是否执行日(is_rebal_day 的新语义) + 还要等几个交易日。
            # 消费者不该再靠 is_rebal_day 推执行日 —— 那正是 off-by-one 的来源。
            "act_next_open": bool(act_next_open), "days_to_next": int(days_to_next),
            "exec_day": str(exec_d) if exec_d else None,
            "open_time_cn": open_time(exec_d) if exec_d else None,
            "strategy": STRAT, "topk": TOPK, "capital_usd": round(CAP0, 2), "fx": FX,
            # v27: 调仓周期。与 pool_size/variant 同理 —— 同一天、同池子、同闸门,
            # 21 日与 10 日的执行时点不同, 是两个不同结果, 必须能区分。
            "rebal": REBAL,
            "anchor": ANCHOR_TAG, "anchor_date": str(dp[anchor_i].date()),
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
            # 【2026-09-14】目标股数**向下取整**：bud 已经是"扣掉佣金"的可投金额,
            # 四舍五入向上会让 Σ(股数×价)+佣金 > 净值 ⇒ 智能体侧风控以「留现金 < 0」
            # 把整个建仓**整单拒绝**(实测超 1.9 美分, 推导见 floor_shares 的 docstring)。
            "target_shares": {n: floor_shares(bud / float(C.values[N-1, UNI.index("US."+n)]))
                              for n in names},
            # orders 只作展示/留档。买入与 target_shares 同口径(floor);
            # 卖出保持 round —— 卖出向上取整只会多卖一点点, 用 floor 反而留残渣,
            # 而残渣要等下一个调仓日才清得掉。
            "orders": [{"code": c, "side": s,
                        "shares": (floor_shares(sh) if sh > 0 else round(sh, 4)),
                        "amount": round(amt, 2)}
                       for c, s, sh, amt, _, _ in orders],
            "shock": shock, "data_ok": ok}
    json.dump(snap, open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    try:
        row = pd.DataFrame([{"date": str(last_d), "strategy": STRAT, "topk": TOPK,
                             "pool_size": len(good), "variant": VARIANT, "rebal": REBAL,
                             "anchor": ANCHOR_TAG,
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

    去重键 = (date, strategy, topk, pool_size, variant, rebal, anchor)。
    v24: 把 pool_size 计入键 —— 扩大股票池后同一天的信号会变,
    若不区分, 旧记录会被静默覆盖, 事后无法解释"信号为什么变了"。
    v25: 再把 variant(闸门口径)计入键 —— 同一个池子、同一天,
    开闸门与关闸门是两个不同结果, 同样不能互相覆盖。
    v27: 再把 rebal(调仓周期)与 anchor(日历起点)计入键 —— 同一个池子、同一天、
    同闸门口径, 21 日与 10 日的"执行时点/下次调仓日"不同, 也是两个不同结果。
    没有 rebal 列的旧表按 21 处理、没有 anchor 列的旧表按 "-"(默认起点)处理
    —— v27 之前这两个值本来就是写死的, 所以用默认口径重跑会原地更新旧行
    (结果确实相同), 而 --rebal 10 / --anchor 会新增一行而不是覆盖它。
    """
    if h is None:
        return row.copy()
    h = h.copy()
    if "pool_size" not in h.columns:
        h["pool_size"] = -1
    if "variant" not in h.columns:
        h["variant"] = "-"
    if "rebal" not in h.columns:
        h["rebal"] = REBAL_DEFAULT
    if "anchor" not in h.columns:
        h["anchor"] = "-"
    # v28: 【新行也要补齐同样的列】。旧写法只补 h 不补 row -> 新行在这几列上是 NaN,
    # 而下面的 key 比较用的是【默认值】(ra="-", rr=REBAL_DEFAULT), NaN != "-"
    # => 这条记录【永远匹配不上】, 于是每跑一次就被追加一次, 静默堆成多行重复。
    # 不抛异常、不影响单次结果, 只让历史表慢慢变脏 —— 正是本项目最在意的那类缺陷。
    # 触发条件: h 已有该列而 row 没有(例如手工构造的行、或上游改了写入口径)。
    row = row.copy()
    if "pool_size" not in row.columns:
        row["pool_size"] = -1
    if "variant" not in row.columns:
        row["variant"] = "-"
    if "rebal" not in row.columns:
        row["rebal"] = REBAL_DEFAULT
    if "anchor" not in row.columns:
        row["anchor"] = "-"
    rv = str(row["variant"].iloc[0]) if "variant" in row.columns else "-"
    rr = int(row["rebal"].iloc[0]) if "rebal" in row.columns else REBAL_DEFAULT
    ra = str(row["anchor"].iloc[0]) if "anchor" in row.columns else "-"
    key = (h["date"].astype(str) == str(row["date"].iloc[0])) & \
          (h["strategy"].astype(str) == str(row["strategy"].iloc[0])) & \
          (h["topk"].astype(int) == int(row["topk"].iloc[0])) & \
          (h["pool_size"].astype(int) == int(row["pool_size"].iloc[0])) & \
          (h["variant"].astype(str) == rv) & \
          (h["rebal"].astype(int) == rr) & \
          (h["anchor"].astype(str) == ra)
    out = pd.concat([h[~key], row], ignore_index=True)
    # v28: 行序必须【与运行顺序无关】。旧写法把新行追加到末尾, 于是用不同参数跑
    # (例如先 `--rebal 10` 再默认 21) 会让【同一份数据】产生不同行序 ——
    # 制造无意义的 git diff, 也让"历史表"失去可复现性。
    # 按去重键稳定排序后, 文件内容成为【数据】的函数, 而不是【数据, 运行顺序】的函数。
    _cols = ["date", "strategy", "topk", "pool_size", "variant", "rebal", "anchor"]
    out = out.sort_values(_cols, kind="mergesort").reset_index(drop=True)
    return out


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
        str(project_trading_days(datetime.date(2026,9,11), REBAL_DEFAULT)) == "2026-10-12")
    chk("下次调仓推算: 9/11 + 10 交易日 = 2026-09-25",
        str(project_trading_days(datetime.date(2026,9,11), 10)) == "2026-09-25")
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
    # ---- v27 调仓周期 --rebal ----
    chk("调仓周期: 默认值仍是 21(向后兼容)", REBAL_DEFAULT == 21, f"({REBAL_DEFAULT})")
    _n21 = len([i for i in range(N) if i >= START and (i - START) % REBAL_DEFAULT == 0])
    _n10 = len([i for i in range(N) if i >= START and (i - START) % 10 == 0])
    chk("调仓周期: 10 日的调仓日数约为 21 日的 2.0~2.2 倍",
        2.0 <= _n10 / _n21 <= 2.2, f"({_n10}/{_n21} = {_n10/_n21:.2f})")
    # 两个周期的调仓日交集 = LCM(10,21)=210 日的倍数。
    # 注意 10 日【不是】21 日的超集 —— 切换周期会改变相位, 这是运维事实, 不是 bug:
    # 从 21 日切到 10 日时, "下一个调仓日"可能反而更近或更远, 必须重新锚定。
    _rb10 = [i for i in range(N) if i >= START and (i - START) % 10 == 0]
    chk("调仓周期: 10 日与 21 日的调仓日交集恰为 210 日的倍数",
        set(_rb10) & set(i for i in range(N) if i >= START and (i - START) % 21 == 0)
        == set(i for i in range(N) if i >= START and (i - START) % 210 == 0))
    # 【最重要的一条】频率只决定"何时执行", 绝不改变"选什么"
    import inspect as _ins27
    _saved_r = globals()["REBAL"]
    _base_r = select(SIG[STRAT], N - 1, good, TOPK)
    _same_r = True
    for _fr in (1, 2, 5, 10, 15, 21, 42, 63, 252):
        globals()["REBAL"] = _fr
        if select(SIG[STRAT], N - 1, good, TOPK) != _base_r:
            _same_r = False
    globals()["REBAL"] = _saved_r
    chk("调仓周期不改变选股结果(频率只管何时执行, 不管选什么)", _same_r,
        f"({', '.join(UNI[j].replace('US.','') for j in _base_r)})")
    chk("选股层未读取调仓周期",
        not (set(select.__code__.co_names) & {"REBAL", "REBAL_DEFAULT"}),
        f"({sorted(set(select.__code__.co_names) & {'REBAL','REBAL_DEFAULT'})})")
    chk("选股层输入签名无调仓周期参数",
        list(_ins27.signature(select).parameters) == ["A", "i", "good", "topk"])
    # 历史表: rebal 必须计入去重键, 否则 21 日与 10 日互相覆盖
    _old = _g.copy()                                   # 无 rebal 列 = v27 之前的旧表
    _g21 = _g.assign(rebal=21)
    _g10 = _g.assign(rebal=10, exec_day="2026-09-24")
    chk("历史表: 同池同变体同 rebal 重跑只留 1 行", len(hist_merge(_g21, _g21)) == 1)
    _mr = hist_merge(_g21, _g10)
    chk("历史表: 21 日与 10 日两条都保留(不互相覆盖)", len(_mr) == 2, f"({len(_mr)} 行)")
    chk("历史表: 10 日那条的执行日可查",
        _mr.loc[_mr.rebal == 10, "exec_day"].iloc[0] == "2026-09-24")
    chk("历史表: 无 rebal 列旧表按 21 处理 -> 用 21 重跑只留 1 行",
        len(hist_merge(_old, _g21)) == 1)
    chk("历史表: 无 rebal 列旧表 + 10 日新行 -> 两条共存(旧记录不被覆盖)",
        len(hist_merge(_old, _g10)) == 2)
    # v28: 行序不得依赖运行顺序 —— 否则同一份数据会因"先跑哪个参数"产生不同文件
    _ab = hist_merge(hist_merge(_g21, _g10), _g21)
    _ba = hist_merge(hist_merge(_g10, _g21), _g10)
    chk("历史表: 行序与合并顺序无关(文件内容是数据的函数, 不是运行顺序的函数)",
        _ab.to_csv(index=False) == _ba.to_csv(index=False))
    chk("历史表: 排序稳定(同键行不因重复合并而漂移)",
        hist_merge(_ab, _g10).to_csv(index=False) == _ab.to_csv(index=False))
    # v28 缺陷回归: h 有 anchor 列而 row 没有时, 旧写法给新行留下 NaN anchor,
    # 与 key 用的默认值 "-" 不相等 -> 同一条记录被反复追加, 静默堆成多行。
    _nan_bug = hist_merge(_ab, _g10.drop(columns=["anchor"]) if "anchor" in _g10.columns else _g10)
    chk("历史表: 新行缺 anchor 列时不得产生重复行(v28 缺陷回归)",
        len(_nan_bug) == 2, f"({len(_nan_bug)} 行, 期望 2)")
    # ---- v27 日历起点 --anchor ----
    # 注意: 面板最后一根是 2026-09-11, 9/14 还没发生 -> 不能用未来日期做锚点。
    _dp = pd.to_datetime(dates)
    _tgt_i = N - 30
    _tgt_d = _dp[_tgt_i].date()
    _ai = next(i for i in range(N) if _dp[i].date() >= _tgt_d)
    chk("anchor: 给定面板内的交易日 -> 精确落到该索引", _ai == _tgt_i, f"({_tgt_d})")
    # 面板里只有交易日, 找不到周六 -> 自己从某个交易日往后推到最近的周六
    _base = _dp[N - 30].date()
    _sat = _base + datetime.timedelta(days=(5 - _base.weekday()) % 7 or 7)
    _ai_s = next(i for i in range(N) if _dp[i].date() >= _sat)
    chk("anchor: 给定周六(非交易日) -> 顺延到下一个交易日",
        _dp[_ai_s].date() > _sat and _dp[_ai_s].weekday() < 5,
        f"({_sat} -> {_dp[_ai_s].date()})")
    _rb_a = [i for i in range(_ai, N) if (i - _ai) % 10 == 0]
    chk("anchor: 锚定后第一个调仓日就是锚点本身", _rb_a[0] == _ai)
    chk("anchor: 锚定后相邻调仓日间隔恒为 REBAL",
        all(b - a == 10 for a, b in zip(_rb_a, _rb_a[1:])))
    chk("anchor: 未指定 --anchor 时标签为 '-'(默认起点)",
        (ANCHOR_TAG == "-") == (ANCHOR is None),
        f"(ANCHOR={ANCHOR!r}, tag={ANCHOR_TAG!r})")
    # 未来锚点(如"把 9/14 当起点"而面板只到 9/11)靠交易日历投影, 测这条机制
    chk("anchor: 未来锚点按交易日历投影(9/11 之后第 1 个交易日 = 9/14)",
        str(project_trading_days(datetime.date(2026, 9, 11), 1)) == "2026-09-14")
    chk("anchor: 未来锚点投影幂等(9/11 + 1 再回推仍落在 9/11 之后)",
        project_trading_days(datetime.date(2026, 9, 11), 1) > datetime.date(2026, 9, 11))
    _old2 = _g21.copy()                    # 无 anchor 列 = v27 之前的旧表
    _dflt = _g21.assign(anchor="-")
    _anch = _g21.assign(anchor="2026-09-14")
    chk("历史表: 无 anchor 列旧表按 '-' 处理 -> 与默认口径同键(只留 1 行)",
        len(hist_merge(_old2, _dflt)) == 1)
    chk("历史表: 同 rebal 不同 anchor 两条都保留",
        len(hist_merge(_dflt, _anch)) == 2)
    # ---- v27.1 日历一致性: 工具报出的执行日必须落在【引擎的执行日】上 ----
    # 引擎执行日索引 = {i >= START : (i-START) % REBAL == 0}, 且用第 i 根【开盘】价成交。
    # 这是本次修正的核心断言: 旧写法把"最后一根是执行日"误当成"最后一根是信号日",
    # 报出的执行日全部比引擎晚 1 个交易日。
    chk("日历: next_exec_offset 纯函数 —— 执行日的前一根 -> 1",
        next_exec_offset(9, 0, 10) == 1, f"({next_exec_offset(9, 0, 10)})")
    chk("日历: next_exec_offset 纯函数 —— 最后一根本身是执行日 -> rebal",
        next_exec_offset(10, 0, 10) == 10, f"({next_exec_offset(10, 0, 10)})")
    _off_all = [next_exec_offset(_t, START, REBAL) for _t in range(START, N)]
    chk("日历: 距下次执行的交易日数恒在 [1, REBAL]",
        all(1 <= o <= REBAL for o in _off_all), f"(max={max(_off_all)})")
    _exec_set = set(i for i in range(START, N) if (i - START) % REBAL == 0)
    _hit = [(t, t + o) for t, o in zip(range(START, N), _off_all) if t + o < N]
    chk("日历: 面板内的执行日索引 100% 命中引擎调仓日",
        all(nx in _exec_set for _, nx in _hit), f"({len(_hit)} 个样本)")
    chk("日历: 报出的执行日索引随数据前进单调不减(不跳空也不回退)",
        all(a + oa <= b + ob for (a, oa), (b, ob) in zip(_hit, _hit[1:])))
    chk("日历: act_next_open 等价于『下一根索引是执行日』",
        all((next_exec_offset(t, START, REBAL) == 1) == ((t + 1 - START) % REBAL == 0)
            for t in range(START, N)))
    # 回归: 9/11 是引擎执行日 -> 下次执行 = 9/11 + 21 交易日 = 10/12;
    # 旧写法(把最后一根当信号日)会错报 next_trading_day(9/11) = 9/14。
    if str(_dp[N - 1].date()) == "2026-09-11":
        _off_last = next_exec_offset(N - 1, START, REBAL_DEFAULT)
        chk("日历回归: 9/11 是执行日 -> 工具报 2026-10-12 (旧写法错报 2026-09-14)",
            _off_last == REBAL_DEFAULT
            and str(project_trading_days(datetime.date(2026, 9, 11), _off_last)) == "2026-10-12"
            and str(next_trading_day(datetime.date(2026, 9, 11))) == "2026-09-14",
            f"(offset={_off_last})")
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
    # ---- v28 本金维度: 佣金拖累 ----
    # 前提在 _v28_smallcap.py [2b] 断言过: 碎股 + 零佣金下策略【尺度不变】(极差 < 1e-13pp),
    # 所以本金对结果的唯一影响就是那 $2/笔固定佣金 -> 拖累 ≈ K / 本金。
    chk("v28: 佣金拖累随本金单调递减, 本金翻倍 -> 拖累减半",
        all(abs(comm_drag_pp(c, 10) / comm_drag_pp(2 * c, 10) - 2.0) < 1e-12
            for c in (1000.0, 1490.49, 10000.0)))
    # 参考表逐点来自 _v28_smallcap.json(复刻引擎实测, 最小换手, $2/笔, 碎股)
    _ref = {(1490.49, 10): 5.45, (1490.49, 21): 2.88,
            (3000.0, 10): 2.58, (3000.0, 21): 1.39,
            (10000.0, 10): 0.75, (10000.0, 21): 0.41}
    _dev = max(abs(comm_drag_pp(c, r) - v) for (c, r), v in _ref.items())
    chk("v28: 拖累经验律对上实测参考表(容差 0.35pp)", _dev <= 0.35, f"(最大偏差 {_dev:.3f}pp)")
    _k10 = [5.45 * 1490.49, 2.58 * 3000.0, 0.75 * 10000.0]
    chk("v28: 实测「拖累x本金」在 $1,490 以上近似恒定(1/本金 律成立)",
        max(_k10) / min(_k10) < 1.15, f"(K10 = {min(_k10):,.0f} ~ {max(_k10):,.0f})")
    # 反例保护: 极小本金下不得给出荒谬的负值或 NaN
    chk("v28: 拖累函数对 0/负本金返回 NaN, 不抛异常",
        all(np.isnan(comm_drag_pp(c, 10)) for c in (0.0, -1.0)))
    # ---- v29 执行时点 ----
    chk("v29: 时点代价表覆盖 10/21 日两个周期",
        set(EXEC_TIME_COST) == {10, 21} and set(EXEC_TIME_COST_PER_QUARTER) == {10, 21},
        f"({sorted(EXEC_TIME_COST)})")
    # 线性一致性: 4 个「1/4 交易日」的累计代价应约等于「整整拖到收盘」的代价
    _lin = {r: abs(EXEC_TIME_COST_PER_QUARTER[r] * 4 - (-EXEC_TIME_COST[r])) for r in (10, 21)}
    chk("v29: 时点代价在 t 上近似线性(4 x 1/4 日 ≈ 拖到收盘)",
        all(v <= 1.5 for v in _lin.values()), f"({_lin})")
    chk("v29: 换手越勤时点代价越大(10 日 > 21 日)",
        EXEC_TIME_COST[10] > EXEC_TIME_COST[21],
        f"({EXEC_TIME_COST[10]} vs {EXEC_TIME_COST[21]})")
    # ---- v30 周期相位 ----
    chk("v30: 相位表覆盖 10/21 日, 且最差<=中位<=最好",
        set(PHASE_SPAN) == {10, 21} and set(PHASE_MEDIAN) == {10, 21}
        and all(PHASE_MN[r] <= PHASE_MEDIAN[r] <= PHASE_MX[r] for r in (10, 21)),
        f"(10日 {PHASE_MN[10]}/{PHASE_MEDIAN[10]}/{PHASE_MX[10]})")
    chk("v30: 相位极差远大于 v27~v29 的任何单项成本(>= 40pp)",
        min(PHASE_SPAN.values()) >= 40.0, f"({PHASE_SPAN})")
    chk("v30: 10 日相位中位高于 21 日, 且配对胜率 > 50%",
        PHASE_MEDIAN[10] > PHASE_MEDIAN[21] and PHASE_WIN_RATE > 50.0,
        f"({PHASE_MEDIAN[10]} vs {PHASE_MEDIAN[21]}, 胜率 {PHASE_WIN_RATE}%)")
    chk("v30: 相位极差与最差/最好相位自洽",
        all(abs((PHASE_MX[r] - PHASE_MN[r]) - PHASE_SPAN[r]) < 0.05 for r in (10, 21)),
        f"({PHASE_SPAN})")
    # ---- v31 错开调仓 ----
    chk("v31: 错开引入两腿不等权(偏离 > 0), 且等权版佣金倍数 > 2",
        STAGGER_WDEV_AVG > STAGGER_WDEV_MIN > 0 and STAGGER_EQW_MULT > 2.0,
        f"(偏离 {STAGGER_WDEV_AVG}% / 倍数 {STAGGER_EQW_MULT}x)")
    chk("v31: 最大互换 offset 仍是互换(中位下降, 只换来最差/离散度改善)",
        STAGGER_SWAP["d_median"] < 0 and STAGGER_SWAP["d_worst"] > 0
        and STAGGER_SWAP["d_iqr"] < 0 and STAGGER_SWAP["d_std"] < 0,
        f"(offset={STAGGER_SWAP['offset']}, Δ中位 {STAGGER_SWAP['d_median']}pp)")
    # ---- v32 因子窗口 ----
    chk("v32: 窗口极差 < 相位极差(相位仍是更大的自由度)",
        WIN_SPAN < WIN_MAX_PHASE_SPAN, f"({WIN_SPAN} vs {WIN_MAX_PHASE_SPAN}pp)")
    chk("v32: n=14 是 10 日最优窗口, 且对其它窗口全胜",
        WIN_BEST10 == 14 and WIN_RANK14_10 == 1 and WIN_14_VS_ALL == WIN_N - 1,
        f"(排 {WIN_RANK14_10}/{WIN_N}, 全胜 {WIN_14_VS_ALL})")
    chk("v32: 「10 日 > 21 日」不是普适结论(只在部分窗口成立)",
        0 < WIN_10D_WINS < WIN_N and WIN_RANK14_21 > 1,
        f"({WIN_10D_WINS}/{WIN_N} 个窗口; n=14 在 21 日排 {WIN_RANK14_21})")
    # ---- v33 流动性闸门阈值 ----
    chk("v33: 闸门不是容量约束(单笔占阈值 < 0.1%)",
        GATE_ORDER_RATIO < 0.1, f"(单笔占阈值 {GATE_ORDER_RATIO}%)")
    chk("v33: 三个自由度排序 阈值 < 窗口 < 相位",
        GATE_SPAN < WIN_SPAN < WIN_MAX_PHASE_SPAN,
        f"({GATE_SPAN} < {WIN_SPAN} < {WIN_MAX_PHASE_SPAN}pp)")
    chk("v33: 「10 日 > 21 日」在全部阈值下成立(对比窗口只 4/8)",
        GATE_WIN10_WINS == GATE_N and GATE_WIN10_WINS > WIN_10D_WINS,
        f"(闸门 {GATE_WIN10_WINS}/{GATE_N} vs 窗口 {WIN_10D_WINS}/{WIN_N})")
    # OHLC
    bad = 0
    for i in range(0, N, 11):
        h, l = PX["high"].values[i], PX["low"].values[i]
        m = np.isfinite(h) & np.isfinite(l)
        bad += int((h[m] < l[m]).sum())
    chk("OHLC 无 high<low 冲突", bad == 0, f"({bad} 处)")

    # ---- v35: 展示层(中文标头对齐 / 佣金预留) ----
    # 这两条都是"不报错、只让人看错"的缺陷: 前者让表格错位, 后者让方案超支。
    chk("v35: dw() 中文按 2 列、ASCII 按 1 列 (对齐错位的根因)",
        dw("现价") == 4 and dw("88.35") == 5 and dw("碎股股数") == 8,
        f"(现价={dw('现价')} 88.35={dw('88.35')} 碎股股数={dw('碎股股数')})")
    _hdr = pad("现价", 11, "r")
    chk("v35: pad() 按显示宽度补齐, 与数字列同宽 (f-string 按字符数会对不齐)",
        dw(_hdr) == 11 and dw(pad("$88.35", 11, "r")) == 11,
        f"(标头宽={dw(_hdr)} 数据宽={dw(pad('$88.35', 11, 'r'))})")
    # 佣金预留: 目标金额必须扣掉佣金, 否则碎股方案合计 > 净值。
    # 【2026-09-14 修正】旧断言用**连续金额** `_bud*_topk + _fee <= _net` 验证 ——
    #   但运行时落盘的是 `floor(_bud/价, 4)` 这样的**离散股数**, 两个口径不同 ⇒ 断言恒真
    #   ⇒ 真缺陷从它眼皮底下走过去。实测就漏掉了: 本金 $1500 满仓建仓时
    #   Σ(round(股数×价)) = $1496.02, 加 $4 佣金 = $1500.02, 超 2 美分,
    #   被智能体侧风控以「留现金 < 0」**整单拒绝**(不是少买一点, 是整个建仓不做)。
    #   现在按**真实落盘口径**断言(含 round(股数×价, 2) —— 风控与券商都按分收钱)。
    for _net, _topk, _comm, _px in ((1500.0, 2, 2.0, (88.35, 648.03)),
                                    (3000.0, 2, 2.0, (88.35, 648.03)),
                                    (500.0, 3, 2.0, (12.34, 56.78, 9.99))):
        _fee = (0 + _topk) * _comm
        _bud = max(0.0, _net - _fee) / _topk
        _amt = sum(round(floor_shares(_bud / p) * p, 2) for p in _px)
        chk(f"v35: 碎股方案不超支 (净值 ${_net:.0f} Top{_topk})",
            _amt + _fee <= _net + 1e-9,
            f"({_amt:.4f} + {_fee:.0f} vs {_net:.0f})")
    # 判别力前置: 上面那组用例若"本来就没事", 断言等于没测 —— 必须证明
    #   $1500 Top2(2026-09-14 真实场景)的**旧 round 口径确实超支**。
    _net, _topk, _comm, _px = 1500.0, 2, 2.0, (88.35, 648.03)
    _bud = max(0.0, _net - _topk * _comm) / _topk
    _old = sum(round(round(_bud / p, 4) * p, 2) for p in _px)
    chk("v35: 用例有判别力 ($1500 Top2 的旧 round 口径确实超支, 即建仓被拒的真实成因)",
        _old + _topk * _comm > _net + 1e-9,
        f"({_old:.4f} + {_topk*_comm:.0f} = {_old+_topk*_comm:.4f} vs {_net:.0f})")
    print("\n" + "=" * 116)
    print(f"  结果: {'✅ 全部通过' if not fails else '❌ 失败: ' + ', '.join(fails)}")
    return 0 if not fails else 1

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    sys.exit(main())
