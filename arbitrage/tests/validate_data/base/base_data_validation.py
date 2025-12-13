"""
Base Data Validation Algorithm

Provides reusable logic for validating data quality through actual trading execution.
"""

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm
from abc import abstractmethod


class BaseDataValidation(TestableAlgorithm):
    """数据验证基类 - 基于 leg1/leg2 通用设计

    通过执行真实交易来验证数据质量，包括：
    - 时间戳正确性
    - 订单执行
    - 数据完整性
    - 持仓计算
    """

    @abstractmethod
    def get_config(self) -> dict:
        """子类必须实现：返回验证配置

        Returns:
            {
                # === Leg 1/2 配置 ===
                'leg1_symbol': str,
                'leg1_security_type': SecurityType,
                'leg1_market': Market,
                'leg1_resolution': Resolution,
                'leg1_data_normalization': DataNormalizationMode,  # 可选
                'leg2_symbol': str,
                'leg2_security_type': SecurityType,
                'leg2_market': Market,
                'leg2_resolution': Resolution,
                'leg2_data_normalization': DataNormalizationMode,  # 可选

                # === 回测配置 ===
                'start_date': tuple,  # (year, month, day)
                'end_date': tuple,
                'initial_cash': int,  # 可选，默认 100000
                'timezone': str,  # 可选，默认 'UTC'
                'brokerage': BrokerageName,  # 可选
                'account_type': AccountType,  # 可选

                # === 交易配置 ===
                'open_hour': int,  # 开仓时间（小时）
                'close_hour': int,  # 平仓时间（小时）
                'trade_quantity': int,  # 交易数量
                'expected_order_count': int,  # 预期订单数
                'allow_fee_variance': bool,  # 是否允许手续费导致的数量误差
            }
        """
        raise NotImplementedError

    def initialize(self):
        """通用初始化"""
        self.begin_test_phase("initialization")

        # 获取配置
        self.config = self.get_config()
        cfg = self.config

        # 设置回测参数
        self.set_start_date(*cfg['start_date'])
        self.set_end_date(*cfg['end_date'])
        self.set_cash(cfg.get('initial_cash', 100000))
        self.set_time_zone(cfg.get('timezone', 'UTC'))

        # 设置经纪商
        if 'brokerage' in cfg:
            self.set_brokerage_model(cfg['brokerage'], cfg.get('account_type', AccountType.Cash))

        # 添加证券
        self.leg1 = self._add_security(
            cfg['leg1_symbol'],
            cfg['leg1_security_type'],
            cfg['leg1_resolution'],
            cfg['leg1_market']
        )

        self.leg2 = self._add_security(
            cfg['leg2_symbol'],
            cfg['leg2_security_type'],
            cfg['leg2_resolution'],
            cfg['leg2_market']
        )

        # 数据规范化
        self.leg1.data_normalization_mode = cfg.get('leg1_data_normalization', DataNormalizationMode.Raw)
        self.leg2.data_normalization_mode = cfg.get('leg2_data_normalization', DataNormalizationMode.Raw)

        # 交易追踪
        self.order_count = 0
        self.filled_orders = []
        self.daily_data_range = {}
        self.current_positions = {cfg['leg1_symbol']: False, cfg['leg2_symbol']: False}

        # 断言
        self.assert_not_none(self.leg1, f"{cfg['leg1_symbol']} should exist")
        self.assert_not_none(self.leg2, f"{cfg['leg2_symbol']} should exist")

        self.checkpoint('initialization',
                       cash=cfg.get('initial_cash', 100000),
                       leg1_symbol=str(self.leg1.symbol),
                       leg2_symbol=str(self.leg2.symbol))

        self.end_test_phase()

        # 安排交易
        self.schedule.on(
            self.date_rules.every_day(self.leg1.symbol),
            self.time_rules.at(cfg.get('open_hour', 10), 0),
            self.open_positions
        )

        self.schedule.on(
            self.date_rules.every_day(self.leg1.symbol),
            self.time_rules.at(cfg.get('close_hour', 14), 0),
            self.close_positions
        )

    def _add_security(self, symbol, security_type, resolution, market):
        """添加证券

        Args:
            symbol: 证券代码
            security_type: 证券类型
            resolution: 分辨率
            market: 市场

        Returns:
            Security object
        """
        if security_type == SecurityType.Equity:
            return self.add_equity(symbol, resolution)
        elif security_type == SecurityType.Crypto:
            return self.add_crypto(symbol, resolution, market)
        else:
            raise ValueError(f"Unsupported security type: {security_type}")

    def on_data(self, data):
        """追踪数据时间范围"""
        current_date = self.time.date()

        if current_date not in self.daily_data_range:
            self.daily_data_range[current_date] = {
                'first': self.time,
                'last': self.time,
                'tick_count': 0
            }

        self.daily_data_range[current_date]['last'] = self.time
        self.daily_data_range[current_date]['tick_count'] += 1

    def open_positions(self):
        """开仓 - 通用逻辑"""
        cfg = self.config
        qty = cfg.get('trade_quantity', 100)

        for symbol_name, leg in [(cfg['leg1_symbol'], self.leg1),
                                  (cfg['leg2_symbol'], self.leg2)]:
            if not self.current_positions[symbol_name]:
                ticket = self.market_order(leg.symbol, qty, tag=f"Open_{symbol_name}")
                self.order_count += 1
                self.assert_greater(ticket.order_id, 0, f"{symbol_name} order ID > 0")
                self.current_positions[symbol_name] = True

    def close_positions(self):
        """平仓 - 通用逻辑"""
        cfg = self.config

        for symbol_name, leg in [(cfg['leg1_symbol'], self.leg1),
                                  (cfg['leg2_symbol'], self.leg2)]:
            if self.current_positions[symbol_name]:
                # 根据是否允许手续费误差决定平仓数量
                if cfg.get('allow_fee_variance', False):
                    # 使用实际持仓数量（考虑手续费）
                    quantity = self.portfolio[leg.symbol].quantity
                else:
                    # 使用固定数量
                    quantity = cfg.get('trade_quantity', 100)

                if quantity > 0:
                    ticket = self.market_order(leg.symbol, -quantity, tag=f"Close_{symbol_name}")
                    self.order_count += 1
                    self.current_positions[symbol_name] = False

    def on_order_event(self, order_event):
        """订单事件验证"""
        if order_event.status == OrderStatus.Filled:
            order = self.transactions.get_order_by_id(order_event.order_id)
            self.begin_test_phase(order.tag)

            self.filled_orders.append({
                'symbol': order_event.symbol.value,
                'fill_quantity': order_event.fill_quantity,
                'fill_price': order_event.fill_price,
                'time': self.time,
                'order_id': order_event.order_id
            })

            # 验证价格合理性
            self.assert_greater(
                order_event.fill_price, 0,
                f"{order_event.symbol.value} fill price > 0"
            )

            self.debug(f"✅ Filled: {order_event.symbol.value} | "
                      f"Qty: {order_event.fill_quantity} | "
                      f"Price: ${order_event.fill_price:.2f}")

            self.end_test_phase()

    def on_end_of_algorithm(self):
        """最终验证"""
        self.begin_test_phase("final_validation")

        cfg = self.config

        # 验证订单数
        expected_orders = cfg.get('expected_order_count', 16)
        self.assert_equal(
            self.order_count, expected_orders,
            f"Expected {expected_orders} orders, got {self.order_count}"
        )

        # 验证成交数
        self.assert_equal(
            len(self.filled_orders), expected_orders,
            f"Expected {expected_orders} fills, got {len(self.filled_orders)}"
        )

        # 输出数据统计
        self._print_data_statistics()

        # 验证 checkpoint
        self.verify_checkpoint('initialization', {
            'cash': cfg.get('initial_cash', 100000)
        })

        self.end_test_phase()
        super().on_end_of_algorithm()

    def _print_data_statistics(self):
        """输出数据统计"""
        self.debug("\n" + "="*60)
        self.debug(f"📊 Data Statistics: {self.config['leg1_symbol']} & {self.config['leg2_symbol']}")
        self.debug("="*60)

        for date, stats in sorted(self.daily_data_range.items()):
            duration = (stats['last'] - stats['first']).total_seconds() / 3600
            self.debug(f"\n{date}:")
            self.debug(f"  First: {stats['first']}")
            self.debug(f"  Last: {stats['last']}")
            self.debug(f"  Duration: {duration:.2f} hours")
            self.debug(f"  Ticks: {stats['tick_count']:,}")
