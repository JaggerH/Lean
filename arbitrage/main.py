# region imports
from AlgorithmImports import *
from QuantConnect.Orders.Fees import KrakenFeeModel
from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel
from QuantConnect.Configuration import Config

import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import KrakenSymbolManager
from spread_manager import SpreadManager
from strategy.both_side_grid_strategy import BothSideGridStrategy

# 监控模块 (Live模式需要)
try:
    from monitoring.monitoring_context import MonitoringContext
    MONITORING_AVAILABLE = True
except ImportError as e:
    MONITORING_AVAILABLE = False
    MONITORING_IMPORT_ERROR = str(e)
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
    - 策略: BothSideGridStrategy (双边网格: long crypto + short crypto)
    """

    def initialize(self):
        """Initialize algorithm with multi-account Margin mode settings"""
        # === 0. 读取市场配置 (在类初始化时只读取一次) ===
        extended_raw = Config.Get("extended-market-hours", "false")
        self.extended_market_hours = extended_raw.lower() == "true" if isinstance(extended_raw, str) else bool(extended_raw)
        self.debug(f"📊 Extended Market Hours: {self.extended_market_hours}")

        # Set start date for live trading
        self.set_start_date(2025, 1, 1)
        # Note: Cash will be set per account via multi-account-config in config.json

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 0. 初始化监控上下文 (统一管理监控组件) ===
        self.debug("="*60)
        self.debug("🔍 Initializing Monitoring Context")
        self.debug("="*60)

        # 检查监控模块是否可用
        if not MONITORING_AVAILABLE:
            error_msg = (
                f"❌ 监控模块导入失败: {MONITORING_IMPORT_ERROR}\n"
                f"   Live模式需要监控模块以避免数据丢失\n"
                f"   请检查:\n"
                f"   1. monitoring目录是否存在\n"
                f"   2. 依赖是否已安装: pip install -r arbitrage/monitoring/requirements.txt"
            )
            self.debug(error_msg)
            # Live 模式强制要求监控模块
            if self.live_mode:
                raise RuntimeError(error_msg)

        # 创建监控上下文（自动检测 Live/Backtest 模式）
        self.monitoring = MonitoringContext(
            algorithm=self,
            mode='auto',          # 自动检测模式
            fail_on_error=True    # Live 模式强制要求 Redis
        )

        self.debug("="*60)

        # === 1. 杠杆配置 ===
        self.leverage_config = {
            'stock': 2.0,   # 股票2x杠杆
            'crypto': 5.0   # 加密货币5x杠杆
        }

        # === 2. 初始化数据源 ===
        self.debug("📊 Initializing data sources...")
        self.sources = {
            "kraken": KrakenSymbolManager()
        }

        # === 3. 初始化 SpreadManager (在订阅交易对之前) ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(
            algorithm=self,
            monitor_adapter=self.monitoring.get_spread_monitor()  # 从监控上下文获取
        )

        # === 4. 初始化双边网格策略 ===
        self.debug("📋 Initializing BothSideGridStrategy...")
        self.strategy = BothSideGridStrategy(
            algorithm=self,
            long_crypto_entry=-0.01,   # -1% (long crypto entry threshold)
            long_crypto_exit=0.02,     # 2% (long crypto exit threshold)
            short_crypto_entry=0.03,   # 3% (short crypto entry threshold)
            short_crypto_exit=-0.009,  # -0.9% (short crypto exit threshold)
            position_size_pct=0.80,    # 80% (考虑杠杆和费用)
            state_persistence=self.monitoring.get_state_persistence()  # 从监控上下文获取
        )

        # === 5. 注册策略到 SpreadManager（观察者模式）===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 6. 动态订阅交易对 ===
        self._subscribe_trading_pairs()

        # === 7. 初始化订单追踪器 (通过监控上下文创建) ===
        self.debug("📊 Initializing EnhancedOrderTracker...")
        self.order_tracker = self.monitoring.create_order_tracker(
            self.strategy,
            debug=False
        )

        # 注入到策略中
        self.strategy.order_tracker = self.order_tracker

        # === 8. 捕获初始快照 ===
        self.order_tracker.capture_initial_snapshot()

        # === 9. 调试追踪器 ===
        self.last_cashbook_debug_time = self.time  # 上次打印 CashBook 的时间

        self.debug("="*60)
        self.debug("✅ Initialization complete!")
        self.debug(f"📈 Subscribed to {len(self.spread_manager.pairs)} crypto-stock pairs")
        self.debug("="*60)

    def _subscribe_trading_pairs(self):
        """动态订阅交易对 - 使用 SpreadManager.subscribe_trading_pair"""
        for exchange, manager in self.sources.items():
            try:
                # Fetch tokenized stocks from exchange
                self.debug(f"Fetching tokenized stocks from {exchange}...")
                manager.get_tokenize_stocks()

                # Get trading pairs
                trade_pairs = manager.get_trade_pairs()
                self.debug(f"Found {len(trade_pairs)} trading pairs from {exchange}")

                # Subscribe to each pair using SpreadManager
                for crypto_symbol, equity_symbol in trade_pairs:
                    try:
                        # Use SpreadManager's subscribe_trading_pair for consistent setup
                        crypto_security, stock_security = self.spread_manager.subscribe_trading_pair(
                            pair_symbol=(crypto_symbol, equity_symbol),
                            extended_market_hours=self.extended_market_hours
                        )
                        # Initialize grid levels for this trading pair
                        self.strategy.initialize_pair((crypto_security.Symbol, stock_security.Symbol))
                    except Exception as e:
                        self.debug(f"❌ Failed to subscribe to {crypto_symbol.value}/{equity_symbol.value}: {str(e)}")
            except Exception as e:
                self.debug(f"❌ Error initializing {exchange} data source: {str(e)}")

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.Ticks or len(data.Ticks) == 0:
            return

        self.strategy.on_data(data)
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证多账户路由"""
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
            from monitoring.html_generator import generate_html_report
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
