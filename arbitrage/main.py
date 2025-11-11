# region imports
from AlgorithmImports import *
from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel
from QuantConnect.Configuration import Config

import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import GateSymbolManager
from spread_manager import SpreadManager
from strategy.both_side_grid_strategy import BothSideGridStrategy


class Arbitrage(QCAlgorithm):
    """
    Arbitrage algorithm for trading crypto stock tokens vs underlying stocks

    多账户Margin模式生产环境版本:
    - 数据源: 动态获取 Gate tokenized stocks 期货 + 对应的 USA stocks
    - 账户配置:
      * IBKR账户: 交易股票 (USA market) - Margin模式 2x杠杆
      * Gate账户: 交易加密货币期货 (Gate market) - Margin模式 10x杠杆（实际使用5x）
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

        # === 1. 初始化数据源 ===
        self.debug("📊 Initializing data sources...")
        self.sources = {
            "gate": GateSymbolManager()
        }

        # === 2. 创建双边网格策略（自包含所有组件）===
        self.debug("📋 Initializing BothSideGridStrategy...")
        self.strategy = BothSideGridStrategy(
            algorithm=self,
            long_crypto_entry=-0.01,   # -1% (long crypto entry threshold)
            long_crypto_exit=0.02,     # 2% (long crypto exit threshold)
            short_crypto_entry=0.03,   # 3% (short crypto entry threshold)
            short_crypto_exit=-0.009,  # -0.9% (short crypto exit threshold)
            position_size_pct=0.50,    # 50% (10x brokerage leverage * 0.50 = 5x effective leverage)
            enable_monitoring=True     # ✅ 策略内部会创建 MonitoringContext
        )

        # === 3. 初始化 SpreadManager（不再直接注入 monitor）===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(algorithm=self)

        # === 4. 注册监控系统为观察者（观察者模式）===
        if self.strategy.monitoring_context:
            spread_monitor = self.strategy.monitoring_context.get_spread_monitor()
            if spread_monitor:
                self.debug("🔗 Registering monitor as pair/spread observer...")
                self.spread_manager.register_pair_observer(spread_monitor.write_pair_mapping)
                self.spread_manager.register_observer(spread_monitor.write_spread)

        # === 5. 注册策略到 SpreadManager（观察者模式）===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 6. 动态订阅交易对（配置 grid levels）===
        self._subscribe_trading_pairs()

        # === 7. 恢复策略状态（✅ 在所有 pairs 初始化完成后）===
        self.strategy.restore_state()

        # === 8. 捕获初始快照 ===
        if self.strategy.monitoring_context and self.strategy.monitoring_context.order_tracker:
            self.strategy.monitoring_context.order_tracker.capture_initial_snapshot()
            self.debug("📸 Initial portfolio snapshot captured")

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
                # ✅ 获取tokenized stock交易对（Gate ↔ USA）with流动性筛选
                trade_pairs = manager.get_tokenized_stock_pairs(asset_type='future', min_volume_usdt=300000)
                self.debug(f"Found {len(trade_pairs)} liquid tokenized stock futures pairs from {exchange}")

                # ✅ 运行时注册 symbol properties（关键！CSV写入仅用于重启预加载）
                # 使用LEAN运行时API立即注册到内存，无需重新加载CSV
                registered_count = manager.register_symbol_properties_runtime(self, trade_pairs)
                self.debug(f"Registered {registered_count} symbols to LEAN runtime database")

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
        """
        订单事件处理（最简化）

        只需转发给 Strategy，剩下的自动流转：
        ExecutionManager → GridStrategy.on_execution_event → MonitoringContext
        """
        self.strategy.on_order_event(order_event)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息和验证多账户Margin模式行为"""

        # === 导出 OrderTracker 数据 ===
        if self.strategy.monitoring_context and self.strategy.monitoring_context.order_tracker:
            self.debug("=" * 60)
            self.debug("📊 Exporting OrderTracker Data")
            self.debug("=" * 60)

            try:
                # 导出 JSON 数据
                json_filepath = "order_tracker_data_live.json"
                self.strategy.monitoring_context.order_tracker.export_json(json_filepath)
                self.debug(f"✅ JSON data exported to: {json_filepath}")

                # 显示统计信息
                stats = self.strategy.monitoring_context.order_tracker.get_statistics()
                self.debug("")
                self.debug("📈 OrderTracker Summary:")
                self.debug(f"  Total Execution Targets: {stats['total_execution_targets']}")
                self.debug(f"  Total Portfolio Snapshots: {stats['total_snapshots']}")
                self.debug(f"  Total Grid Position Snapshots: {stats['total_grid_positions']}")
                self.debug("")

            except Exception as e:
                self.debug(f"❌ Error exporting OrderTracker data: {e}")
                import traceback
                self.debug(traceback.format_exc())

        # === 输出最终多账户状态 ===
        if hasattr(self.portfolio, 'GetAccount'):
            self.debug("" + "="*60)
            self.debug("💰 最终多账户状态 (Margin Mode - Live)")
            self.debug("="*60)

            try:
                ibkr_account = self.portfolio.GetAccount("IBKR")
                gate_account = self.portfolio.GetAccount("Gate")

                self.debug(f"IBKR账户 (2x Leverage):")
                self.debug(f"  现金: ${ibkr_account.Cash:,.2f}")
                self.debug(f"  Margin Used: ${ibkr_account.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${ibkr_account.TotalPortfolioValue:,.2f}")

                self.debug(f"Gate账户 (10x Brokerage Leverage, 5x Effective):")
                self.debug(f"  现金 (USDT): {gate_account.CashBook['USDT'].Amount:,.2f}")
                self.debug(f"  Margin Used: ${gate_account.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${gate_account.TotalPortfolioValue:,.2f}")

                self.debug(f"聚合Portfolio:")
                self.debug(f"  总现金: ${self.portfolio.Cash:,.2f}")
                self.debug(f"  总Margin Used: ${self.portfolio.TotalMarginUsed:,.2f}")
                self.debug(f"  总价值: ${self.portfolio.TotalPortfolioValue:,.2f}")

            except Exception as e:
                self.debug(f"无法访问多账户信息: {e}")

        self.debug("" + "="*60)
        self.debug("✅ 多账户Margin模式套利算法完成")
        self.debug("="*60)
