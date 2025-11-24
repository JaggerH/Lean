# region imports
from AlgorithmImports import *
from QuantConnect.Configuration import Config
from System.Collections.Specialized import NotifyCollectionChangedAction
from dataclasses import dataclass
from typing import Tuple, Optional

import sys
import os
sys.path.append(os.path.dirname(__file__))
from data_source import GateSymbolManager
from subscription_helper import SubscriptionHelper
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

        # === 3. 初始化 SubscriptionHelper ===
        self.debug("📊 Initializing SubscriptionHelper...")
        self.subscription_helper = SubscriptionHelper(algorithm=self)

        # === 4. 订阅 TradingPairManager 集合变化事件 ===
        self.debug("🔗 Subscribing to TradingPairs.CollectionChanged event...")
        self.TradingPairs.CollectionChanged += self._on_trading_pairs_changed

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
        self.debug(f"📈 Subscribed to {self.TradingPairs.Count} spot-future pairs")
        self.debug("="*60)

    def _subscribe_trading_pairs(self):
        """动态订阅交易对 - 使用 SubscriptionHelper"""
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

            # Subscribe to each pair using SubscriptionHelper
            for futures_symbol, spot_symbol in trade_pairs:
                try:
                    # Use SubscriptionHelper's subscribe_pair for unified subscription
                    # Triggers TradingPairs.CollectionChanged event automatically
                    futures_security, spot_security = self.subscription_helper.subscribe_pair(
                        leg1_symbol=futures_symbol,
                        leg2_symbol=spot_symbol,
                        pair_type="spot_future"
                    )
                    # Note: Grid initialization moved to _on_trading_pairs_changed event handler
                except Exception as e:
                    self.debug(f"❌ Failed to subscribe to {futures_symbol.value}/{spot_symbol.value}: {str(e)}")
        except Exception as e:
            self.debug(f"❌ Error initializing gate data source: {str(e)}")

    def _on_trading_pairs_changed(self, sender, e):
        """
        处理 TradingPair 集合变化事件
        用于初始化 monitor 和 strategy
        """
        if e.Action == NotifyCollectionChangedAction.Add:
            for pair in e.NewItems:
                # 通知 monitor（配对映射）
                if self.strategy.monitoring_context:
                    spread_monitor = self.strategy.monitoring_context.get_spread_monitor()
                    if spread_monitor:
                        spread_monitor.write_pair_mapping(
                            pair.Leg1Security,
                            pair.Leg2Security
                        )

                # 初始化策略
                self.strategy.initialize_pair(
                    (pair.Leg1Symbol, pair.Leg2Symbol)
                )

                self.debug(f"✅ Trading pair added and initialized: {pair.Key}")

    def on_data(self, data: Slice):
        """
        处理数据 - TradingPairs 已在 Slice 中自动更新

        TradingPairManager.UpdateAll() 已在 AlgorithmManager 中自动调用
        可以直接访问 data.TradingPairs 或 self.TradingPairs
        """
        if not data.Ticks or len(data.Ticks) == 0:
            return

        # 📊 Log incoming data with SecurityType
        symbols_with_data = [f"{symbol.Value}({symbol.SecurityType})" for symbol in data.Ticks.Keys]
        self.debug(f"📊 on_data received ticks for: {', '.join(symbols_with_data)}")

        # 策略处理
        self.strategy.on_data(data)

        # 处理 TradingPair 更新（监控和策略通知）
        # Note: TradingPairs are accessed from algorithm, not from slice
        if hasattr(self, 'TradingPairs') and self.TradingPairs is not None:
            for pair in self.TradingPairs:
                if pair.HasValidPrices:
                    # 监控记录
                    if self.strategy.monitoring_context:
                        spread_monitor = self.strategy.monitoring_context.get_spread_monitor()
                        if spread_monitor:
                            spread_monitor.write_spread(
                                self._adapt_to_spread_signal(pair)
                            )

                    # 策略通知（仅在有套利机会时）
                    if pair.ExecutableSpread is not None:
                        self.strategy.on_spread_update(
                            self._adapt_to_spread_signal(pair)
                        )

    def _adapt_to_spread_signal(self, trading_pair):
        """临时适配层：将 C# TradingPair 转换为 Python SpreadSignal"""
        @dataclass
        class SpreadSignal:
            pair_symbol: Tuple[Symbol, Symbol]
            market_state: MarketState
            theoretical_spread: float
            executable_spread: Optional[float]
            direction: Optional[str]

        return SpreadSignal(
            pair_symbol=(trading_pair.Leg1Symbol, trading_pair.Leg2Symbol),
            market_state=trading_pair.MarketState,
            theoretical_spread=float(trading_pair.TheoreticalSpread),
            executable_spread=float(trading_pair.ExecutableSpread) if trading_pair.ExecutableSpread else None,
            direction=trading_pair.Direction
        )

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
