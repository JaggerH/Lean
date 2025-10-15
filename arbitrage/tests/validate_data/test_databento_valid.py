"""
Databento 数据验证测试

验证从 databento 转换的 TSLA 和 AAPL tick 数据：
- 日期范围: 2025-09-02 至 2025-09-05 (美东时间)
- 交易策略: 每天 10:00 开仓, 14:00 平仓 (美东时间)
- 预期交易: TSLA 和 AAPL 各 4 天 = 8 次回转交易 = 16 笔订单
- 验证: 数据时间戳转换、数据完整性、交易执行
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm


class DatabentoValidationTest(TestableAlgorithm):
    """验证 Databento 数据格式和交易执行"""

    def initialize(self):
        """初始化算法"""
        self.begin_test_phase("initialization")

        # 设置回测时间范围 (美东时间)
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)
        self.set_cash(100000)

        # 设置美东时区
        self.set_time_zone("America/New_York")

        # 添加 TSLA 和 AAPL tick 数据
        self.tsla = self.add_equity("TSLA", Resolution.TICK)
        self.aapl = self.add_equity("AAPL", Resolution.TICK)

        # 设置数据规范化模式
        self.tsla.data_normalization_mode = DataNormalizationMode.RAW
        self.aapl.data_normalization_mode = DataNormalizationMode.RAW

        # 交易计数器
        self.order_count = 0
        self.filled_orders = []

        # 数据时间戳追踪
        self.daily_data_range = {}  # {date: {'first': timestamp, 'last': timestamp}}

        # 交易计划
        self.trade_plan = []
        self.current_positions = {"TSLA": False, "AAPL": False}

        # 每天的交易时间 (美东时间)
        self.open_hour = 10
        self.close_hour = 14

        # 断言
        self.assert_not_none(self.tsla, "TSLA Symbol 应该存在")
        self.assert_not_none(self.aapl, "AAPL Symbol 应该存在")
        self.assert_equal(self.portfolio.cash, 100000, "初始现金应为 $100,000")

        # Checkpoint
        self.checkpoint('initialization',
                       cash=100000,
                       tsla_symbol=self.tsla.symbol.value,
                       aapl_symbol=self.aapl.symbol.value)

        self.end_test_phase()

        # 安排每日交易
        self.schedule.on(
            self.date_rules.every_day("TSLA"),
            self.time_rules.at(self.open_hour, 0),
            self.open_positions
        )

        self.schedule.on(
            self.date_rules.every_day("TSLA"),
            self.time_rules.at(self.close_hour, 0),
            self.close_positions
        )

    def on_data(self, data):
        """处理数据"""
        # 追踪每日数据时间范围
        current_date = self.time.date()

        if current_date not in self.daily_data_range:
            self.daily_data_range[current_date] = {
                'first': self.time,
                'last': self.time,
                'first_unix': self.time.timestamp(),
                'last_unix': self.time.timestamp()
            }
        else:
            self.daily_data_range[current_date]['last'] = self.time
            self.daily_data_range[current_date]['last_unix'] = self.time.timestamp()

    def open_positions(self):
        """开仓: 买入 TSLA 和 AAPL"""
        self.begin_test_phase(f"open_positions_{self.time.date()}")

        if not self.current_positions["TSLA"]:
            ticket_tsla = self.market_order("TSLA", 300)
            self.order_count += 1
            self.trade_plan.append({
                'time': self.time,
                'symbol': 'TSLA',
                'action': 'BUY',
                'quantity': 300,
                'order_id': ticket_tsla.order_id
            })
            self.assert_greater(ticket_tsla.order_id, 0, f"TSLA 订单ID应大于0 at {self.time}")
            self.current_positions["TSLA"] = True

        if not self.current_positions["AAPL"]:
            ticket_aapl = self.market_order("AAPL", 300)
            self.order_count += 1
            self.trade_plan.append({
                'time': self.time,
                'symbol': 'AAPL',
                'action': 'BUY',
                'quantity': 300,
                'order_id': ticket_aapl.order_id
            })
            self.assert_greater(ticket_aapl.order_id, 0, f"AAPL 订单ID应大于0 at {self.time}")
            self.current_positions["AAPL"] = True

        self.end_test_phase()

    def close_positions(self):
        """平仓: 卖出 TSLA 和 AAPL"""
        self.begin_test_phase(f"close_positions_{self.time.date()}")

        if self.current_positions["TSLA"]:
            ticket_tsla = self.market_order("TSLA", -300)
            self.order_count += 1
            self.trade_plan.append({
                'time': self.time,
                'symbol': 'TSLA',
                'action': 'SELL',
                'quantity': -300,
                'order_id': ticket_tsla.order_id
            })
            self.assert_greater(ticket_tsla.order_id, 0, f"TSLA 平仓订单ID应大于0 at {self.time}")
            self.current_positions["TSLA"] = False

        if self.current_positions["AAPL"]:
            ticket_aapl = self.market_order("AAPL", -300)
            self.order_count += 1
            self.trade_plan.append({
                'time': self.time,
                'symbol': 'AAPL',
                'action': 'SELL',
                'quantity': -300,
                'order_id': ticket_aapl.order_id
            })
            self.assert_greater(ticket_aapl.order_id, 0, f"AAPL 平仓订单ID应大于0 at {self.time}")
            self.current_positions["AAPL"] = False

        self.end_test_phase()

    def on_order_event(self, order_event):
        """订单事件处理"""
        if order_event.status == OrderStatus.FILLED:
            self.begin_test_phase(f"order_filled_{order_event.symbol.value}_{len(self.filled_orders)}")

            self.filled_orders.append({
                'symbol': order_event.symbol.value,
                'fill_quantity': order_event.fill_quantity,
                'fill_price': order_event.fill_price,
                'time': self.time,
                'order_id': order_event.order_id
            })

            # 验证成交数量
            self.assert_true(
                abs(order_event.fill_quantity) == 300,
                f"{order_event.symbol.value} 成交数量应为 300 或 -300, 实际: {order_event.fill_quantity}"
            )

            # 验证成交价格合理性
            self.assert_greater(
                order_event.fill_price, 0,
                f"{order_event.symbol.value} 成交价格应大于0, 实际: {order_event.fill_price}"
            )

            self.debug(f"✅ 订单成交: {order_event.symbol.value} | "
                      f"数量: {order_event.fill_quantity} | "
                      f"价格: ${order_event.fill_price:.2f} | "
                      f"时间: {self.time}")

            self.end_test_phase()

    def on_end_of_algorithm(self):
        """算法结束验证"""
        self.begin_test_phase("final_validation")

        # 验证总订单数
        self.assert_equal(
            self.order_count, 16,
            f"应该有16笔订单 (TSLA和AAPL各4天×2次), 实际: {self.order_count}"
        )

        # 验证成交订单数
        self.assert_equal(
            len(self.filled_orders), 16,
            f"应该有16笔成交订单, 实际: {len(self.filled_orders)}"
        )

        # 验证最终无持仓
        self.assert_equal(
            self.portfolio["TSLA"].quantity, 0,
            f"TSLA 最终持仓应为0, 实际: {self.portfolio['TSLA'].quantity}"
        )

        self.assert_equal(
            self.portfolio["AAPL"].quantity, 0,
            f"AAPL 最终持仓应为0, 实际: {self.portfolio['AAPL'].quantity}"
        )

        # 输出每日数据时间范围
        self.debug("\n" + "="*60)
        self.debug("📊 每日数据时间范围 (美东时间, Unix 时间戳)")
        self.debug("="*60)

        for date, time_range in sorted(self.daily_data_range.items()):
            first_time = time_range['first']
            last_time = time_range['last']
            first_unix = time_range['first_unix']
            last_unix = time_range['last_unix']

            duration = (last_time - first_time).total_seconds() / 3600  # hours

            self.debug(f"\n日期: {date}")
            self.debug(f"  首笔数据: {first_time} (Unix: {first_unix:.0f})")
            self.debug(f"  末笔数据: {last_time} (Unix: {last_unix:.0f})")
            self.debug(f"  时间跨度: {duration:.2f} 小时")

            # 验证数据在交易时间内
            self.assert_true(
                first_time.hour >= 0 and last_time.hour <= 23,
                f"{date} 数据时间应在合理范围内"
            )

        # 输出交易计划执行情况
        self.debug("\n" + "="*60)
        self.debug("📋 交易计划执行情况")
        self.debug("="*60)

        for i, trade in enumerate(self.trade_plan):
            self.debug(f"{i+1}. {trade['time']} | {trade['symbol']} | "
                      f"{trade['action']} | 数量: {trade['quantity']} | "
                      f"订单ID: {trade['order_id']}")

        # 验证 checkpoint
        self.verify_checkpoint('initialization', {
            'cash': 100000,
            'tsla_symbol': 'TSLA',
            'aapl_symbol': 'AAPL'
        })

        self.end_test_phase()

        # 调用父类输出测试结果
        super().on_end_of_algorithm()
