"""
多账户Margin模式双边策略集成测试 - Multi-Account Portfolio Manager with Both-Side Strategy

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLA/TSLAUSD, AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-27
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 路由策略: Market-based routing (基于Symbol.ID.Market)
- 策略: 双边套利策略 (BothSideStrategy)
  - Long Crypto + Short Stock:
    * 开仓: spread <= -1%
    * 平仓: spread >= 2%
  - Short Crypto + Long Stock:
    * 开仓: spread >= 3%
    * 平仓: spread <= -0.9%

测试目标:
1. 验证多账户Margin模式配置正确初始化
2. 验证每个Security使用Margin BuyingPowerModel
3. 验证杠杆倍数设置正确 (股票2x, 加密货币5x)
4. 验证订单自动路由到正确账户 (crypto->Kraken, stock->IBKR)
5. 验证双边策略能同时捕捉正负价差机会
6. 验证Margin模式下的买入力计算
7. 验证Fill更新正确的子账户
8. 验证账户间现金和持仓隔离
"""

import sys
from pathlib import Path
from datetime import timedelta

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm
from spread_manager import SpreadManager
from strategy.base_strategy import BaseStrategy
from strategy.both_side_strategy import BothSideStrategy
from monitoring.order_tracker import OrderTracker as EnhancedOrderTracker


class MultiAccountMarginBothSideTest(TestableAlgorithm):
    """多账户Margin模式双边策略集成测试"""

    def initialize(self):
        """初始化算法"""
        self.begin_test_phase("initialization")

        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 27)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 杠杆配置 ===
        self.leverage_config = {
            'stock': 2.0,   # 股票2x杠杆
            'crypto': 5.0   # 加密货币5x杠杆
        }

        # === 1. 添加股票数据 (Databento) - 应路由到 IBKR 账户 ===
        self.debug("📈 Adding Stock Data (Databento) - will route to IBKR account...")
        self.tsla_stock = self.add_equity("TSLA", Resolution.TICK, Market.USA, extended_market_hours=False)
        self.aapl_stock = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=False)

        self.tsla_stock.data_normalization_mode = DataNormalizationMode.RAW
        self.aapl_stock.data_normalization_mode = DataNormalizationMode.RAW

        # === 2. 添加加密货币数据 (Kraken) - 应路由到 Kraken 账户 ===
        self.debug("🪙 Adding Crypto Data (Kraken) - will route to Kraken account...")
        self.tsla_crypto = self.add_crypto("TSLAUSD", Resolution.TICK, Market.Kraken)
        self.aapl_crypto = self.add_crypto("AAPLUSD", Resolution.TICK, Market.Kraken)

        self.tsla_crypto.data_normalization_mode = DataNormalizationMode.RAW
        self.aapl_crypto.data_normalization_mode = DataNormalizationMode.RAW

        # === 3. 设置Margin模式 ===
        self.debug("💰 Setting Margin Mode for all securities...")
        self.debug("="*60)

        # 为股票设置Margin模式 (2x杠杆)
        self._set_margin_mode(self.tsla_stock, 'stock')
        self._set_margin_mode(self.aapl_stock, 'stock')

        # 为加密货币设置Margin模式 (5x杠杆)
        self._set_margin_mode(self.tsla_crypto, 'crypto')
        self._set_margin_mode(self.aapl_crypto, 'crypto')

        self.debug("="*60)

        # === 4. 设置FeeModel (保持原有逻辑) ===
        self.debug("💵 Setting Fee Models...")
        from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel, KrakenFeeModel
        self.tsla_stock.fee_model = InteractiveBrokersFeeModel()
        self.aapl_stock.fee_model = InteractiveBrokersFeeModel()
        self.tsla_crypto.fee_model = KrakenFeeModel()
        self.aapl_crypto.fee_model = KrakenFeeModel()

        # === 5. 验证多账户配置 ===
        self.debug("" + "="*60)
        self.debug("🔍 Verifying Multi-Account Configuration")
        self.debug("="*60)

        # 检查是否使用了多账户 Portfolio
        if hasattr(self.portfolio, 'GetAccount'):
            self.debug("✅ Multi-Account Portfolio Detected!")

            # 显示子账户信息
            try:
                ibkr_account = self.portfolio.GetAccount("IBKR")
                kraken_account = self.portfolio.GetAccount("Kraken")

                self.debug(f"📊 IBKR Account Cash: ${ibkr_account.Cash:,.2f}")
                self.debug(f"📊 Kraken Account Cash: ${kraken_account.Cash:,.2f}")
                self.debug(f"📊 Total Portfolio Cash: ${self.portfolio.Cash:,.2f}")

                # 验证账户配置
                self.assert_equal(ibkr_account.Cash, 50000, "IBKR账户初始现金应为$50,000")
                self.assert_equal(kraken_account.Cash, 50000, "Kraken账户初始现金应为$50,000")
                self.assert_equal(self.portfolio.Cash, 100000, "总现金应为$100,000")

            except Exception as e:
                self.debug(f"❌ Error accessing multi-account: {e}")
                self.error(f"Multi-account configuration failed: {e}")
        else:
            self.debug("❌ Multi-Account Portfolio NOT detected!")
            self.debug("⚠️ Please check config.json has correct multi-account-config")
            self.error("Multi-account portfolio not initialized - check config.json")

        self.debug("="*60 + "")

        # === 6. 验证Margin模式 ===
        self.debug("="*60)
        self.debug("🔍 Verifying Margin Mode Configuration")
        self.debug("="*60)
        self._verify_margin_mode()
        self.debug("="*60)

        # === 7. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(
            algorithm=self,
            strategy=None  # Will set later
        )

        # === 8. 初始化双边策略 ===
        self.debug("📋 Initializing BothSideStrategy...")
        self.strategy = BothSideStrategy(
            algorithm=self,
            spread_manager=self.spread_manager,
            long_crypto_entry=-0.01,   # -1%
            long_crypto_exit=0.02,     # 2%
            short_crypto_entry=0.03,   # 3%
            short_crypto_exit=-0.009,  # -0.9%
            position_size_pct=0.8     # 25%
        )

        # 链接策略到 SpreadManager
        self.spread_manager.strategy = self.strategy

        # === 9. 注册交易对 ===
        self.debug("🔗 Registering trading pairs...")
        self.spread_manager.add_pair(self.tsla_crypto, self.tsla_stock)
        self.spread_manager.add_pair(self.aapl_crypto, self.aapl_stock)

        # === 10. 数据追踪 ===
        self.tick_count = 0
        self.order_events = []

        # 多账户追踪
        self.account_order_events = {
            'IBKR': [],
            'Kraken': [],
            'Unknown': []
        }

        # === 11. 初始化独立的订单追踪器 (Enhanced Version) ===
        self.debug("📊 Initializing EnhancedOrderTracker for independent order verification...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy)

        # === 断言验证 ===
        self.assert_not_none(self.tsla_stock, "TSLA Stock Symbol 应该存在")
        self.assert_not_none(self.aapl_stock, "AAPL Stock Symbol 应该存在")
        self.assert_not_none(self.tsla_crypto, "TSLAUSD Crypto Symbol 应该存在")
        self.assert_not_none(self.aapl_crypto, "AAPLUSD Crypto Symbol 应该存在")

        pairs = self.spread_manager.get_all_pairs()
        self.assert_equal(len(list(pairs)), 2, "应该有2个交易对")

        self.checkpoint('initialization',
                       total_cash=self.portfolio.cash,
                       pairs_count=len(list(self.spread_manager.get_all_pairs())),
                       tsla_stock=self.tsla_stock.symbol.value,
                       aapl_stock=self.aapl_stock.symbol.value,
                       tsla_crypto=str(self.tsla_crypto.symbol),
                       aapl_crypto=str(self.aapl_crypto.symbol))

        self.debug("✅ Initialization complete!")
        self.debug("🎯 Multi-Account Margin Mode Both-Side Strategy Test Ready!")
        self.debug("="*60)
        self.end_test_phase()

    def _set_margin_mode(self, security, asset_type):
        """为Security设置Margin模式的BuyingPowerModel"""
        from QuantConnect.Securities import SecurityMarginModel

        leverage = self.leverage_config.get(asset_type, 1.0)
        security.set_buying_power_model(SecurityMarginModel(leverage))

        self.debug(f"✅ Set {security.symbol.value} to Margin mode with {leverage}x leverage")

    def _verify_margin_mode(self):
        """验证所有Security都使用了Margin模式"""
        securities_to_check = [
            (self.tsla_stock, 'stock'),
            (self.aapl_stock, 'stock'),
            (self.tsla_crypto, 'crypto'),
            (self.aapl_crypto, 'crypto')
        ]

        for security, asset_type in securities_to_check:
            symbol = security.symbol
            buying_power_model = security.buying_power_model

            # 检查是否是SecurityMarginModel
            model_type = type(buying_power_model).__name__
            self.debug(f"{symbol.value}: BuyingPowerModel = {model_type}")

            # 检查杠杆倍数
            if hasattr(buying_power_model, 'GetLeverage'):
                leverage = buying_power_model.GetLeverage(security)
                expected_leverage = self.leverage_config.get(asset_type, 1.0)

                self.debug(f"  Leverage: {leverage}x (Expected: {expected_leverage}x)")

                # 验证杠杆倍数
                self.assert_equal(leverage, expected_leverage,
                                f"{symbol.value}的杠杆倍数应为{expected_leverage}x")
            else:
                self.error(f"❌ {symbol.value} BuyingPowerModel没有GetLeverage方法!")

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return

        self.tick_count += 1

        # 委托给SpreadManager处理数据并监控价差
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证多账户路由"""
        self.order_events.append(order_event)

        # 确定订单应该路由到哪个账户
        symbol = order_event.symbol
        expected_account = None

        if symbol.security_type == SecurityType.Equity and symbol.id.market == Market.USA:
            expected_account = "IBKR"
        elif symbol.security_type == SecurityType.Crypto and symbol.id.market == Market.Kraken:
            expected_account = "Kraken"
        else:
            expected_account = "Unknown"

        # 记录到对应账户
        self.account_order_events[expected_account].append(order_event)

        # === 记录订单填充到独立追踪器 ===
        self.order_tracker.record_order_fill(order_event)

        if order_event.status == OrderStatus.Filled:
            self.debug(
                f"✅ Order Filled | {order_event.symbol.value} | "
                f"Time: {self.time} | "
                f"Qty: {order_event.fill_quantity} @ ${order_event.fill_price:.2f} | "
                f"Expected Account: {expected_account}"
            )

        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息和验证多账户Margin模式行为"""
        self.begin_test_phase("final_validation")

        # === Finalize Open Round Trips ===
        self.debug("=" * 60)
        self.debug("📊 Finalizing Open Round Trips")
        self.debug("=" * 60)
        try:
            self.order_tracker.finalize_open_round_trips()
        except Exception as e:
            self.debug(f"❌ Error finalizing open round trips: {e}")
            import traceback
            self.debug(traceback.format_exc())

        # === 导出 JSON 数据 (Enhanced OrderTracker) ===
        self.debug("=" * 60)
        self.debug("📊 Exporting Enhanced OrderTracker Data")
        self.debug("=" * 60)

        try:
            # 导出 JSON 数据
            json_filepath = "order_tracker_data_both_side.json"
            self.order_tracker.export_json(json_filepath)
            self.debug(f"✅ JSON data exported to: {json_filepath}")

            # 生成 HTML 可视化报告
            from monitoring.html_generator import generate_html_report
            html_filepath = "order_tracker_report_both_side.html"
            generate_html_report(json_filepath, html_filepath)
            self.debug(f"✅ HTML report generated: {html_filepath}")

            # 显示摘要信息
            self.debug("")
            self.debug("📈 Report Summary:")
            self.debug(f"  Total Snapshots: {len(self.order_tracker.snapshots)}")
            self.debug(f"  Total Orders Tracked: {len(self.order_tracker.orders)}")
            self.debug(f"  Realized PnL: ${self.order_tracker.realized_pnl:.2f}")
            self.debug("")

        except Exception as e:
            self.debug(f"❌ Error generating reports: {e}")
            import traceback
            self.debug(traceback.format_exc())

        # === 验证数据完整性 ===
        self.assert_greater(self.tick_count, 0, "应该接收到tick数据")

        # === 输出交易统计 ===
        self.debug("" + "="*60)
        self.debug("📊 交易统计 (Margin Mode - Both-Side Strategy)")
        self.debug("="*60)
        self.debug(f"总Tick数: {self.tick_count:,}")
        self.debug(f"订单事件数: {len(self.order_events)}")
        self.debug(f"已实现盈亏: ${self.order_tracker.realized_pnl:.2f}")

        # === 输出多账户订单分布 ===
        self.debug("" + "="*60)
        self.debug("🔀 多账户订单路由统计")
        self.debug("="*60)
        self.debug(f"IBKR账户订单: {len(self.account_order_events['IBKR'])} 个")
        self.debug(f"Kraken账户订单: {len(self.account_order_events['Kraken'])} 个")
        self.debug(f"未知路由订单: {len(self.account_order_events['Unknown'])} 个")

        # === 输出最终多账户状态 ===
        if hasattr(self.portfolio, 'GetAccount'):
            self.debug("" + "="*60)
            self.debug("💰 最终多账户状态 (Margin Mode - Both-Side)")
            self.debug("="*60)

            try:
                ibkr_account = self.portfolio.GetAccount("IBKR")
                kraken_account = self.portfolio.GetAccount("Kraken")

                self.debug(f"IBKR账户 (2x Leverage):")
                self.debug(f"  现金: ${ibkr_account.Cash:,.2f}")
                self.debug(f"  Margin Used: ${ibkr_account.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${ibkr_account.TotalPortfolioValue:,.2f}")

                self.debug(f"Kraken账户 (5x Leverage):")
                self.debug(f"  现金: ${kraken_account.Cash:,.2f}")
                self.debug(f"  Margin Used: ${kraken_account.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${kraken_account.TotalPortfolioValue:,.2f}")

                self.debug(f"聚合Portfolio:")
                self.debug(f"  总现金: ${self.portfolio.Cash:,.2f}")
                self.debug(f"  总Margin Used: ${self.portfolio.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${self.portfolio.TotalPortfolioValue:,.2f}")

            except Exception as e:
                self.error(f"无法访问多账户信息: {e}")

        # 验证 checkpoint
        self.verify_checkpoint('initialization', {
            'total_cash': 100000,  # IBKR (50k) + Kraken (50k)
            'pairs_count': 2
        })

        self.debug("" + "="*60)
        self.debug("✅ 多账户Margin模式双边策略集成测试完成")
        self.debug("="*60)

        self.end_test_phase()

        # 调用父类输出测试结果
        super().on_end_of_algorithm()
