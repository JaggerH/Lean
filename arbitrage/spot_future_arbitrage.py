# region imports
from AlgorithmImports import *
from QuantConnect.Configuration import Config

import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import GateSymbolManager
from spread_manager import SpreadManager
from strategy.both_side_grid_strategy import BothSideGridStrategy


class SpotFutureArbitrage(QCAlgorithm):
    """
    Spot-Future Arbitrage algorithm for crypto basis trading

    单账户Margin模式期现套利版本:
    - 数据源: Gate crypto spot + crypto futures (basis pairs)
    - 账户配置:
      * Gate统一账户: 同时交易现货和期货
      * Futures: Margin模式 10x杠杆
      * Spot: 1x杠杆
    - 策略: BothSideGridStrategy (双边网格: long crypto futures + short crypto futures)
    - 测试阶段: 仅使用 BTCUSDT 和 ETHUSDT 两个交易对
    """

    def initialize(self):
        """Initialize algorithm with single-account spot-future arbitrage settings"""
        # Set start date for live trading
        self.set_start_date(2025, 1, 1)
        # Note: Cash will be set via initial-cash in config.json

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
        self.debug(f"📈 Subscribed to {len(self.spread_manager.get_all_pairs())} spot-future pairs")
        self.debug("="*60)

    def _subscribe_trading_pairs(self):
        """动态订阅交易对 - 使用 SpreadManager.subscribe_trading_pair"""
        manager = self.sources["gate"]  # Only Gate exchange needed

        try:
            # ✅ 获取现货-期货交易对（仅取前3个用于测试）
            # all_pairs = manager.get_crypto_basis_pairs(min_volume_usdt=300000)
            all_pairs = [
                ((Symbol.Create('BTCUSDT', SecurityType.CryptoFuture, "gate"), Symbol.Create('BTCUSDT', SecurityType.Crypto, "gate"))),
                ((Symbol.Create('ETHUSDT', SecurityType.CryptoFuture, "gate"), Symbol.Create('ETHUSDT', SecurityType.Crypto, "gate"))),
            ]
            trade_pairs = all_pairs[:3]  # 只取前3个交易对

            self.debug(f"Found {len(all_pairs)} total spot-future pairs from gate (using first {len(trade_pairs)} for testing)")

            # ✅ 运行时注册 symbol properties（关键！CSV写入仅用于重启预加载）
            # 使用LEAN运行时API立即注册到内存，无需重新加载CSV
            registered_count = manager.register_symbol_properties_runtime(self, trade_pairs)
            self.debug(f"Registered {registered_count} symbols to LEAN runtime database")

            # Subscribe to each pair using SpreadManager
            for futures_symbol, spot_symbol in trade_pairs:
                try:
                    # Use SpreadManager's subscribe_trading_pair for consistent setup
                    # Note: For crypto, extended_market_hours is not applicable
                    futures_security, spot_security = self.spread_manager.subscribe_trading_pair(
                        pair_symbol=(futures_symbol, spot_symbol),
                        extended_market_hours=False  # Not applicable for crypto 24/7 markets
                    )
                    # Initialize grid levels for this trading pair
                    self.strategy.initialize_pair((futures_security.Symbol, spot_security.Symbol))
                except Exception as e:
                    self.debug(f"❌ Failed to subscribe to {futures_symbol.value}/{spot_symbol.value}: {str(e)}")
        except Exception as e:
            self.debug(f"❌ Error initializing gate data source: {str(e)}")

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.Ticks or len(data.Ticks) == 0:
            return

        # 📊 Log incoming data with SecurityType
        symbols_with_data = [f"{symbol.Value}({symbol.SecurityType})" for symbol in data.Ticks.Keys]
        self.debug(f"📊 on_data received ticks for: {', '.join(symbols_with_data)}")

        self.strategy.on_data(data)

        # 📈 Log before spread calculation
        self.debug(f"📈 Calling spread_manager.on_data() to calculate spreads...")
        self.spread_manager.on_data(data)
        self.debug(f"✅ spread_manager.on_data() completed")

    def on_order_event(self, order_event: OrderEvent):
        """
        订单事件处理（最简化）

        只需转发给 Strategy，剩下的自动流转：
        ExecutionManager → GridStrategy.on_execution_event → MonitoringContext
        """
        self.strategy.on_order_event(order_event)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息"""

        # === 导出 OrderTracker 数据 ===
        if self.strategy.monitoring_context and self.strategy.monitoring_context.order_tracker:
            self.debug("=" * 60)
            self.debug("📊 Exporting OrderTracker Data")
            self.debug("=" * 60)

            try:
                # 导出 JSON 数据
                json_filepath = "order_tracker_data_spot_future_live.json"
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

        # === 输出最终单账户状态 ===
        self.debug("" + "="*60)
        self.debug("💰 最终账户状态 (Spot-Future Arbitrage - Live)")
        self.debug("="*60)

        try:
            self.debug(f"Gate统一账户 (Futures 10x Leverage, Spot 1x):")
            self.debug(f"  现金 (USDT): {self.portfolio.CashBook['USDT'].Amount:,.2f}")
            self.debug(f"  Margin Used: ${self.portfolio.TotalMarginUsed:,.2f}")
            self.debug(f"  总价值: ${self.portfolio.TotalPortfolioValue:,.2f}")

            # Show positions
            self.debug(f"\n持仓汇总:")
            for kvp in self.portfolio:
                symbol = kvp.Key
                holding = kvp.Value
                if holding.Quantity != 0:
                    self.debug(f"  {symbol.Value}: {holding.Quantity:,.4f} @ ${holding.AveragePrice:,.2f}")

        except Exception as e:
            self.debug(f"无法访问账户信息: {e}")

        self.debug("" + "="*60)
        self.debug("✅ 现货-期货套利算法完成")
        self.debug("="*60)
