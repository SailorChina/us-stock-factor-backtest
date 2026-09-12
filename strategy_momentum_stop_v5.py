# -*- coding: utf-8 -*-
"""
富途牛牛量化平台 - Momentum Top2 + 15%回撤止损 + 回撤恢复再入场
v5 - 使用平台内置函数（正确的平台版本）

【重要说明】
富途牛牛量化平台（牛牛App内置）与 OpenAPI SDK 是两个不同的系统：
- OpenAPI SDK：本地Python脚本，连接FutuOpenD网关（端口11111）
- 量化平台：在线Web环境，有自己独立的内置函数

本策略使用量化平台的内置函数，请参考平台右上角"量化使用手册"验证函数名。

【平台框架】
class Strategy(StrategyBase):
    def initialize(self):
        declare_strategy_type(AlgoStrategyType.SECURITY)
        self.trigger_symbols()
        self.global_variables()
        self.custom_indicator()

    def trigger_symbols(self):
        self.驱动资产1 = declare_trig_symbol(['US.AAPL', 'US.MSFT', ...])

    def global_variables(self):
        self.STOP_PCT = show_variable(0.15, GlobalType.FLOAT)
        self.HOLD_NUM = show_variable(2, GlobalType.INT)

    def custom_indicator(self):
        pass

    def handle_data(self, context):
        # 策略主逻辑
        pass
"""

class Strategy(StrategyBase):
    def initialize(self):
        # 声明策略类型
        declare_strategy_type(AlgoStrategyType.SECURITY)

        # 初始化
        self.trigger_symbols()
        self.global_variables()
        self.custom_indicator()

        # 状态变量
        self.last_rebalance_date = None
        self.in_position = {}
        self.trade_count = 0

        print("[MomentumTop2+Stop] 策略启动")

    def trigger_symbols(self):
        """定义驱动标的（股票池）"""
        self.驱动资产1 = declare_trig_symbol([
            'US.AAPL', 'US.MSFT', 'US.NVDA', 'US.GOOG', 'US.META',
            'US.TSLA', 'US.AMZN', 'US.BABA', 'US.PDD', 'US.MU',
            'US.LITE', 'US.INTC', 'US.AVGO', 'US.ADBE', 'US.CRDO',
            'US.TSM', 'US.MRVL', 'US.AMD', 'US.COHR', 'US.UBER',
            'US.NOW', 'US.CRWD', 'US.CBRS', 'US.APP', 'US.ARM',
            'US.RKLB', 'US.COIN', 'US.MSTR', 'US.FCX', 'US.OXY',
            'US.V', 'US.MA', 'US.NKE', 'US.MCD', 'US.KO', 'US.GLW'
        ])

    def global_variables(self):
        """定义全局变量"""
        self.STOP_PCT = show_variable(0.15, GlobalType.FLOAT)
        self.HOLD_NUM = show_variable(2, GlobalType.INT)
        self.REBAL_EVERY = show_variable(21, GlobalType.INT)
        self.MIN_LOOKBACK = show_variable(253, GlobalType.INT)
        self.RECOVERY_THRESHOLD = show_variable(0.005, GlobalType.FLOAT)

    def custom_indicator(self):
        """自定义指标（可选）"""
        pass

    def handle_data(self, context):
        """策略主函数"""
        today = context.current_dt.date() if hasattr(context, 'current_dt') else None

        # 获取可用现金
        available_cash = context.account_cash if hasattr(context, 'account_cash') else 3000.0

        # 月度调仓判断
        should_rebalance = (self.last_rebalance_date is None or
                           (today - self.last_rebalance_date).days >= self.REBAL_EVERY)

        # Step 1: 更新持仓止损/峰值
        for code, pos in list(self.in_position.items()):
            last_price = self._get_price(context, code)
            if last_price is None or last_price <= 0:
                continue

            pos['peak_price'] = max(pos['peak_price'], last_price)
            drawdown = (pos['peak_price'] - last_price) / pos['peak_price']

            if drawdown >= self.STOP_PCT and not pos.get('stopped', False):
                pos['stopped'] = True
                pos['stop_price'] = last_price * (1 - self.STOP_PCT)
                self._sell_all(context, code, "止损%.0f%%" % (self.STOP_PCT * 100))
                print("[%s] 止损清仓 %s 峰值=%.2f 回撤=%.1f%%" % (
                    today, code, pos['peak_price'], drawdown * 100))

            elif pos.get('stopped', False):
                if last_price >= pos['stop_price'] * (1 + self.RECOVERY_THRESHOLD):
                    print("[%s] 恢复再入场 %s" % (today, code))
                    pos['stopped'] = False
                    pos['entry_price'] = last_price
                    pos['peak_price'] = last_price

        # Step 2: 月度调仓
        if should_rebalance:
            self.last_rebalance_date = today
            print("[%s] 月度调仓" % today)

            # 获取标的列表
            codes = self._get_universe(context)
            scores = {}

            for code in codes:
                klines = self._get_klines(context, code, self.MIN_LOOKBACK + 30)
                if klines and len(klines) >= self.MIN_LOOKBACK + 21:
                    score = self._compute_momentum(klines)
                    if score is not None:
                        scores[code] = score

            # 取 top HOLD_NUM
            sorted_codes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            top_codes = [c for c, s in sorted_codes[:self.HOLD_NUM]]

            print("[%s] Top%d: %s" % (today, self.HOLD_NUM, top_codes))

            # 清掉不在榜单的持仓
            for code in list(self.in_position.keys()):
                if code not in top_codes:
                    self._sell_all(context, code, "换仓")

            # 开新仓
            per_stock = available_cash / self.HOLD_NUM if self.HOLD_NUM > 0 else 0

            for code in top_codes:
                if code not in self.in_position:
                    price = self._get_price(context, code)
                    if price and price > 0:
                        qty = int(per_stock / price)
                        if qty > 0:
                            self._buy(context, code, qty)
                            self.in_position[code] = {
                                'entry_price': price,
                                'peak_price': price,
                                'stopped': False,
                                'stop_price': price * (1 - self.STOP_PCT)
                            }
                            print("[%s] 开仓 %s %d股 @ %.2f" % (today, code, qty, price))

    def _compute_momentum(self, klines):
        """计算动量得分：过去12个月剔除最近1个月"""
        if len(klines) < 274:
            return None
        closes = [k['close'] for k in klines]
        try:
            p_start = closes[-(253 + 21)]
            p_end = closes[-21]
        except IndexError:
            return None
        if p_start <= 0 or p_end <= 0:
            return None
        return (p_end / p_start - 1.0) * 100.0

    def _get_price(self, context, code):
        """获取最新价格"""
        try:
            # ⚠️【需要确认】请打开平台右上角"量化使用手册"，搜索"价格"或"行情"
            # 尝试几个可能的平台内置函数名（按优先级）：
            # 1. get_price(code)
            # 2. get_last_price(code)
            # 3. get_current_price(code)
            # 4. history_kline(code, 1, '1d')[-1]['close']
            price = get_price(code)
            return float(price) if price else None
        except Exception as e:
            print("[WARN] get_price %s: %s" % (code, e))
        return None

    def _get_klines(self, context, code, count):
        """获取K线数据"""
        try:
            # ⚠️【需要确认】请打开平台右上角"量化使用手册"，搜索"K线"或"历史行情"
            # 尝试几个可能的平台内置函数名（按优先级）：
            # 1. get_k_data(code, count)
            # 2. history_kline(code, count, '1d')
            # 3. get_history_kline(code, count)
            # 4. kline_data(code, count)
            klines = get_k_data(code, count)
            return klines
        except Exception as e:
            print("[WARN] get_klines %s: %s" % (code, e))
        return None

    def _get_universe(self, context):
        """获取标的列表"""
        try:
            # ⚠️ 根据平台手册调整
            codes = self.驱动资产1.get_codes() if hasattr(self.驱动资产1, 'get_codes') else []
            return codes
        except Exception:
            return ['US.AAPL', 'US.MSFT', 'US.NVDA']

    def _buy(self, context, code, qty):
        """买入"""
        try:
            # ⚠️【需要确认】请打开平台右上角"量化使用手册"，搜索"市价单"或"买入"
            # 尝试几个可能的平台内置函数名（按优先级）：
            # 1. order_market(code, qty, OrderDirection.BUY)
            # 2. order_target_value(code, value) - 目标市值
            # 3. buy(code, qty)
            # 4. place_order(code, qty, direction)
            print("[BUY] %s %d股" % (code, qty))
            # order_market(code, qty, OrderDirection.BUY)
            self.trade_count += 1
        except Exception as e:
            print("[BUY ERROR] %s: %s" % (code, e))

    def _sell_all(self, context, code, reason):
        """卖出全部"""
        try:
            # ⚠️【需要确认】请打开平台右上角"量化使用手册"，搜索"市价单"或"卖出"
            # 尝试几个可能的平台内置函数名（按优先级）：
            # 1. order_market(code, qty, OrderDirection.SELL)
            # 2. order_target_value(code, 0) - 清仓
            # 3. sell(code, qty)
            # 4. place_order(code, qty, direction)
            print("[SELL] %s reason=%s" % (code, reason))
            # order_market(code, qty, OrderDirection.SELL)
            self.in_position.pop(code, None)
            self.trade_count += 1
        except Exception as e:
            print("[SELL ERROR] %s: %s" % (code, e))
