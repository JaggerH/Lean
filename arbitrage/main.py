# region imports
from AlgorithmImports import *
import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import KrakenSymbolManager
from SpreadManager import SpreadManager
from strategy.long_crypto_strategy import LongCryptoStrategy
from order_tracker import OrderTracker as EnhancedOrderTracker
# endregion

class Arbitrage(QCAlgorithm):
    """
    Arbitrage algorithm for trading crypto stock tokens vs underlying stocks

    多账户Margin模式生产环境版本:
    - 数据源: 动态获取 Kraken tokenized stocks + 对应的 USA stocks
    - 账户配置:
      * IBKR账户: 交易股票 (USA market) - Margin模式 2x杠杆
      * Kraken账户: 交易加密货币 (Kraken market) - Margin模式 5x杠杆
    - 路由策略: Market-based routing (基于Symbol.ID.Market)
    - 策略: LongCryptoStrategy (long crypto + short stock)
    """

    def initialize(self):
        """Initialize algorithm with multi-account Margin mode settings"""
        # Set start date for live trading
        self.set_start_date(2025, 1, 1)
        # Note: Cash will be set per account via multi-account-config in config.json

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 杠杆配置 ===
        self.leverage_config = {
            'stock': 2.0,   # 股票2x杠杆
            'crypto': 5.0   # 加密货币5x杠杆
        }

        # === 1. 初始化数据源 ===
        self.debug("📊 Initializing data sources...")
        self.sources = {
            "kraken": KrakenSymbolManager()
        }

        # === 2. 动态订阅交易对 ===
        self.debug("🔗 Fetching and subscribing to trading pairs...")
        self._subscribe_trading_pairs()

        # === 3. 验证多账户配置 ===
        self._verify_multi_account_config()

        # === 4. 验证Margin模式 ===
        self._verify_margin_mode()

        # === 5. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(
            algorithm=self,
            strategy=None,  # Will set later
            aggression=0.6
        )

        # === 6. 初始化做多加密货币策略 ===
        self.debug("📋 Initializing LongCryptoStrategy...")
        self.strategy = LongCryptoStrategy(
            algorithm=self,
            spread_manager=self.spread_manager,
            entry_threshold=-0.01,  # -1%
            exit_threshold=0.02,    # 2%
            position_size_pct=0.80  # 80% (考虑杠杆和费用)
        )

        # 链接策略到 SpreadManager
        self.spread_manager.strategy = self.strategy

        # === 7. 数据追踪 ===
        self.tick_count = 0
        self.order_events = []

        # 多账户追踪
        self.account_order_events = {
            'IBKR': [],
            'Kraken': [],
            'Unknown': []
        }

        # === 8. 初始化独立的订单追踪器 (Enhanced Version) ===
        self.debug("📊 Initializing EnhancedOrderTracker...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy)

        self.debug("✅ Initialization complete!")
        self.debug(f"📈 Subscribed to {len(self.spread_manager.pairs)} crypto-stock pairs")
        self.debug("="*60)

    def _subscribe_trading_pairs(self):
        """动态订阅交易对 - 使用与测试一致的初始化方法"""
        for exchange, manager in self.sources.items():
            try:
                # Fetch tokenized stocks from exchange
                self.debug(f"Fetching tokenized stocks from {exchange}...")
                manager.get_tokenize_stocks()

                # Get trading pairs
                trade_pairs = manager.get_trade_pairs()
                self.debug(f"Found {len(trade_pairs)} trading pairs from {exchange}")

                # Subscribe to each pair (limit to 5 for testing)
                for crypto_symbol, equity_symbol in trade_pairs[:5]:
                    try:
                        # === 添加加密货币数据 (Kraken) - 应路由到 Kraken 账户 ===
                        crypto_security = self.add_crypto(
                            crypto_symbol.value,
                            Resolution.TICK,
                            Market.Kraken
                        )
                        crypto_security.data_normalization_mode = DataNormalizationMode.RAW

                        # 为加密货币设置Margin模式 (5x杠杆)
                        self._set_margin_mode(crypto_security, 'crypto')

                        # 为加密货币设置 Kraken Fee Model
                        from QuantConnect.Orders.Fees import KrakenFeeModel
                        crypto_security.fee_model = KrakenFeeModel()

                        # === 添加股票数据 (Databento/IBKR) - 应路由到 IBKR 账户 ===
                        # Check if stock is already subscribed
                        if equity_symbol in self.securities:
                            equity_security = self.securities[equity_symbol]
                        else:
                            equity_security = self.add_equity(
                                equity_symbol.value,
                                Resolution.TICK,
                                Market.USA,
                                extended_market_hours=False  # 保持与测试一致
                            )
                            equity_security.data_normalization_mode = DataNormalizationMode.RAW

                            # 为股票设置Margin模式 (2x杠杆)
                            self._set_margin_mode(equity_security, 'stock')

                            # 为股票设置 IBKR Fee Model
                            from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel
                            equity_security.fee_model = InteractiveBrokersFeeModel()

                        # Register the pair in SpreadManager
                        self.spread_manager.add_pair(crypto_security, equity_security)

                        self.debug(f"✅ Subscribed: {crypto_symbol.value} <-> {equity_symbol.value}")

                    except Exception as e:
                        self.debug(f"❌ Failed to subscribe to {crypto_symbol.value}/{equity_symbol.value}: {str(e)}")

            except Exception as e:
                self.debug(f"❌ Error initializing {exchange} data source: {str(e)}")

    def _set_margin_mode(self, security, asset_type):
        """为Security设置Margin模式的BuyingPowerModel"""
        from QuantConnect.Securities import SecurityMarginModel

        leverage = self.leverage_config.get(asset_type, 1.0)
        security.set_buying_power_model(SecurityMarginModel(leverage))

        self.debug(f"✅ Set {security.symbol.value} to Margin mode with {leverage}x leverage")

    def _verify_multi_account_config(self):
        """验证多账户配置"""
        self.debug("="*60)
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

            except Exception as e:
                self.debug(f"❌ Error accessing multi-account: {e}")
        else:
            self.debug("❌ Multi-Account Portfolio NOT detected!")
            self.debug("⚠️ Please check config.json has correct multi-account-config")

        self.debug("="*60)

    def _verify_margin_mode(self):
        """验证所有Security都使用了Margin模式"""
        self.debug("="*60)
        self.debug("🔍 Verifying Margin Mode Configuration")
        self.debug("="*60)

        for symbol, security in self.securities.items():
            buying_power_model = security.buying_power_model
            model_type = type(buying_power_model).__name__

            # 确定资产类型
            if symbol.security_type == SecurityType.Crypto:
                asset_type = 'crypto'
            elif symbol.security_type == SecurityType.Equity:
                asset_type = 'stock'
            else:
                continue

            self.debug(f"{symbol.value}: BuyingPowerModel = {model_type}")

            # 检查杠杆倍数
            if hasattr(buying_power_model, 'GetLeverage'):
                leverage = buying_power_model.GetLeverage(security)
                expected_leverage = self.leverage_config.get(asset_type, 1.0)
                self.debug(f"  Leverage: {leverage}x (Expected: {expected_leverage}x)")

        self.debug("="*60)

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
            json_filepath = "order_tracker_data_live.json"
            self.order_tracker.export_json(json_filepath)
            self.debug(f"✅ JSON data exported to: {json_filepath}")

            # 生成 HTML 可视化报告
            from visualization.html_generator import generate_html_report
            html_filepath = "order_tracker_report_live.html"
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

        # === 输出交易统计 ===
        self.debug("" + "="*60)
        self.debug("📊 交易统计 (Margin Mode - Live)")
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
            self.debug("💰 最终多账户状态 (Margin Mode - Live)")
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
                self.debug(f"无法访问多账户信息: {e}")

        self.debug("" + "="*60)
        self.debug("✅ 多账户Margin模式套利算法完成")
        self.debug("="*60)
