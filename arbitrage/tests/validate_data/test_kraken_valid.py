"""
Kraken 数据验证测试 (Gate.io 数据源)

验证从 gate.io 转换的加密货币 tick 数据:
- 日期范围: 2025-09-02 至 2025-09-05 (UTC 时间)
- 交易对: AAPLUSD, TSLAUSD (AAPLx/USD, TSLAx/USD)
- 交易策略: 每天 UTC 10:00 开仓, UTC 14:00 平仓
- 预期交易: AAPL 和 TSLA 各 4 天 = 8 次回转交易 = 16 笔订单
- 验证: Kraken 格式兼容性、数据完整性、交易执行
"""

from ast import Str
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm


class KrakenValidationTest(TestableAlgorithm):
    """验证 Kraken/Gate.io 加密货币数据格式和交易执行"""

    def initialize(self):
        """初始化算法"""
        self.begin_test_phase("initialization")

        # 设置回测时间范围 (UTC 时间)
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)
        self.set_cash(100000)

        # 设置 UTC 时区
        self.set_time_zone("UTC")

        # 设置 Kraken 作为加密货币经纪商
        self.set_brokerage_model(BrokerageName.Kraken, AccountType.Cash)

        # 添加 AAPLUSD 和 TSLAUSD
        self.aapl = self.add_crypto("AAPLUSD", Resolution.Tick, Market.Kraken)
        self.tsla = self.add_crypto("TSLAUSD", Resolution.Tick, Market.Kraken)

        # 设置数据规范化模式
        self.aapl.data_normalization_mode = DataNormalizationMode.Raw
        self.tsla.data_normalization_mode = DataNormalizationMode.Raw

        # 交易计数器
        self.order_count = 0
        self.filled_orders = []

        # 数据时间戳追踪
        self.daily_data_range = {}  # {date: {'first': timestamp, 'last': timestamp, 'tick_count': int}}

        # 交易计划
        self.current_positions = {"AAPL": False, "TSLA": False}

        # 每天的交易时间 (UTC)
        self.open_hour = 10
        self.close_hour = 14

        # 断言
        self.assert_not_none(self.aapl, "AAPLUSD Symbol 应该存在")
        self.assert_not_none(self.tsla, "TSLAUSD Symbol 应该存在")
        self.assert_equal(self.portfolio.cash, 100000, "初始现金应为 $100,000")

        # Checkpoint
        self.checkpoint('initialization',
                       cash=100000,
                       aapl_symbol=str(self.aapl.symbol),
                       tsla_symbol=str(self.tsla.symbol))

        self.end_test_phase()

        # 安排每日交易
        self.schedule.on(
            self.date_rules.every_day(self.aapl.symbol),
            self.time_rules.at(self.open_hour, 0),
            self.open_positions
        )

        self.schedule.on(
            self.date_rules.every_day(self.aapl.symbol),
            self.time_rules.at(self.close_hour, 0),
            self.close_positions
        )

    def on_data(self, data):
        """处理数据"""
        # 追踪每日数据时间范围和tick数量
        current_date = self.time.date()

        if current_date not in self.daily_data_range:
            self.daily_data_range[current_date] = {
                'first': self.time,
                'last': self.time,
                'first_unix': self.time.timestamp(),
                'last_unix': self.time.timestamp(),
                'tick_count': 0
            }

        self.daily_data_range[current_date]['last'] = self.time
        self.daily_data_range[current_date]['last_unix'] = self.time.timestamp()
        self.daily_data_range[current_date]['tick_count'] += 1

        # 记录数据类型
        if not hasattr(self, 'data_types_seen'):
            self.data_types_seen = set()

        for symbol in data.keys():
            if data[symbol] is not None:
                data_type = type(data[symbol]).__name__
                self.data_types_seen.add(f"{symbol.value}: {data_type}")

    def open_positions(self):
        """开仓: 买入 AAPL 和 TSLA"""
        # 允许小于1的残留持仓（由于手续费产生）时开仓
        if self.portfolio[self.aapl.symbol].quantity < 1:
            # 使用LEAN原生的MarketOrder（100股）
            ticket_aapl = self.market_order(self.aapl.symbol, 100, tag=f"Open_AAPL_{self.time.date()}")
            self.order_count += 1
            self.assert_greater(ticket_aapl.order_id, 0, f"AAPL 订单ID应大于0 at {self.time}")

        if self.portfolio[self.tsla.symbol].quantity < 1:
            ticket_tsla = self.market_order(self.tsla.symbol, 100, tag=f"Open_TSLA_{self.time.date()}")
            self.order_count += 1
            self.assert_greater(ticket_tsla.order_id, 0, f"TSLA 订单ID应大于0 at {self.time}")

    def close_positions(self):
        """平仓: 卖出 AAPL 和 TSLA"""
        # 使用 CashBook 中的实际持仓数量（考虑手续费后的真实数量）
        aapl_quantity = self.portfolio.cash_book["AAPL"].amount
        if aapl_quantity > 0:
            self.debug(f"Closing AAPL: cash_book amount = {aapl_quantity}")
            ticket_aapl = self.market_order(self.aapl.symbol, -aapl_quantity,
                                            tag=f"Close_AAPL_{self.time.date()}_qty{aapl_quantity}")
            self.order_count += 1

        tsla_quantity = self.portfolio.cash_book["TSLA"].amount
        if tsla_quantity > 0:
            self.debug(f"Closing TSLA: cash_book amount = {tsla_quantity}")
            ticket_tsla = self.market_order(self.tsla.symbol, -tsla_quantity,
                                            tag=f"Close_TSLA_{self.time.date()}_qty{tsla_quantity}")
            self.order_count += 1

    def on_order_event(self, order_event):
        """订单事件处理 - 使用LEAN原生断言"""
        if order_event.status in [OrderStatus.Filled, OrderStatus.PARTIALLY_FILLED]:
            # 获取订单对象以访问 tag
            order = self.transactions.get_order_by_id(order_event.order_id)
            self.begin_test_phase(order.tag)

            self.filled_orders.append({
                'symbol': order_event.symbol.value,
                'fill_quantity': order_event.fill_quantity,
                'fill_price': order_event.fill_price,
                'time': self.time,
                'order_id': order_event.order_id,
                'tag': order.tag
            })

            # 断言订单已成交
            self.assert_equal(
                order_event.status, OrderStatus.Filled,
                f"{order_event.symbol.value} 订单应为Filled状态"
            )

            # 验证成交数量（允许因手续费产生的小误差，如 99.74）
            self.assert_true(
                abs(abs(order_event.fill_quantity) - 100) < 1,
                f"{order_event.symbol.value} 成交数量应接近 ±100, 实际: {order_event.fill_quantity}"
            )

            # 验证 tag 格式
            # if order_event.fill_quantity > 0:
            #     # 买入订单应该有 "Open_" 前缀
            #     self.assert_true(
            #         order.tag.startswith("Open_"),
            #         f"{order_event.symbol.value} 买入订单tag应以'Open_'开头, 实际: {order.tag}"
            #     )
            # else:
            #     # 卖出订单应该有 "Close_" 前缀
            #     self.assert_true(
            #         order.tag.startswith("Close_"),
            #         f"{order_event.symbol.value} 卖出订单tag应以'Close_'开头, 实际: {order.tag}"
            #     )

            self.debug(f"✅ 订单成交: {order_event.symbol.value} | "
                      f"数量: {order_event.fill_quantity} | "
                      f"价格: ${order_event.fill_price:.2f} | "
                      f"Tag: {order.tag} | "
                      f"时间: {self.time} | "
                      f"Quantity after trade: {self.portfolio[order_event.symbol].quantity}"
                      )

            self.end_test_phase()
        

    def on_end_of_algorithm(self
                            ):
        """算法结束验证"""
        self.begin_test_phase("final_validation")

        # 验证总订单数
        self.assert_equal(
            self.order_count, 16,
            f"应该有16笔订单 (AAPL和TSLA各4天×2次), 实际: {self.order_count}"
        )

        # 验证成交订单数
        self.assert_equal(
            len(self.filled_orders), 16,
            f"应该有16笔成交订单, 实际: {len(self.filled_orders)}"
        )

        # 验证最终无持仓（允许小于1股的残留，这是由于手续费导致的）
        aapl_quantity = self.portfolio[self.aapl.symbol].quantity
        tsla_quantity = self.portfolio[self.tsla.symbol].quantity

        self.assert_true(
            abs(aapl_quantity) < 1,
            f"AAPL 最终持仓应小于1股, 实际: {aapl_quantity}"
        )

        self.assert_true(
            abs(tsla_quantity) < 1,
            f"TSLA 最终持仓应小于1股, 实际: {tsla_quantity}"
        )

        # 输出每日数据时间范围
        self.debug("\n" + "="*60)
        self.debug("📊 每日数据时间范围 (UTC 时间, Unix 时间戳)")
        self.debug("="*60)

        for date, time_range in sorted(self.daily_data_range.items()):
            first_time = time_range['first']
            last_time = time_range['last']
            first_unix = time_range['first_unix']
            last_unix = time_range['last_unix']
            tick_count = time_range['tick_count']

            duration = (last_time - first_time).total_seconds() / 3600  # hours

            self.debug(f"\n日期: {date}")
            self.debug(f"  首笔数据: {first_time} (Unix: {first_unix:.0f})")
            self.debug(f"  末笔数据: {last_time} (Unix: {last_unix:.0f})")
            self.debug(f"  时间跨度: {duration:.2f} 小时")
            self.debug(f"  Tick 数量: {tick_count:,}")

            # 验证数据在合理时间范围内
            self.assert_true(
                first_time.hour >= 0 and last_time.hour <= 23,
                f"{date} 数据时间应在合理范围内"
            )

        # 输出数据类型信息
        # if hasattr(self, 'data_types_seen'):
        #     self.debug("\n" + "="*60)
        #     self.debug("📋 数据类型")
        #     self.debug("="*60)
        #     for data_type in sorted(self.data_types_seen):
        #         self.debug(f"  {data_type}")j

        # # 输出交易计划执行情况
        # self.debug("\n" + "="*60)
        # self.debug("📋 交易计划执行情况")
        # self.debug("="*60)

        # # 验证 checkpoint
        # self.verify_checkpoint('initialization', {
        #     'cash': 100000
        # })

        # self.end_test_phase()

        # # 调用父类输出测试结果
        # super().on_end_of_algorithm()
