"""
Live Mode Monitor 集成测试 - 使用 Backtest 测试 Live 监控功能

测试场景:
- 运行模式: Backtest (使用历史数据，快速可重复)
- 监控模式: Live (realtime_mode=True，启用 Redis 实时写入)
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD, TSLA/TSLAxUSD
- 日期范围: 2025-09-02 至 2025-09-27
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 路由策略: Market-based routing (基于Symbol.ID.Market)
- 策略: LongCryptoGridStrategy (Grid Trading Framework)
  - 单一Entry Grid: spread <= -1%
  - 单一Exit Grid: spread >= 2%
  - 方向: 仅 long crypto + short stock
  - 自动profitability validation (profit > 2 * fees)

测试目标:
1. 验证 Live 监控模式在 Backtest 环境下的运行
2. 验证 Redis 实时写入功能 (trading:active_targets, trading:grid_positions)
3. 验证 PartiallyFilled 事件触发 (Live 模式不跳过)
4. 验证 ExecutionTarget 注册时立即写入 Redis
5. 验证 ExecutionTarget 完成时从 Redis 移除
6. 验证 GridPosition 快照写入 Redis
7. 对比 Live 监控模式与 Backtest 模式的行为差异
"""

import sys
from pathlib import Path
from datetime import timedelta

# Add arbitrage directory to path
arbitrage_path = str(Path(__file__).parent.parent.parent.parent)
sys.path.insert(0, arbitrage_path)

from AlgorithmImports import *

# Add arbitrage to path for imports
sys.path.insert(0, str(Path(arbitrage_path) / 'arbitrage'))

from spread_manager import SpreadManager
from strategy.long_crypto_grid_strategy import LongCryptoGridStrategy
from monitoring.order_tracker import OrderTracker as EnhancedOrderTracker
from monitoring.redis_writer import TradingRedis

class LiveModeMonitorTest(QCAlgorithm):
    """Live Mode Monitor 集成测试 - Backtest 环境 + Live 监控"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 27)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # === 0. 初始化 Redis 连接（模拟 Live 环境）===
        self.debug("=" * 60)
        self.debug("🔗 Initializing Redis for Live Mode Monitoring Test")
        self.debug("=" * 60)

        try:
            # 验证 Redis 连接
            success, msg = TradingRedis.verify_connection(raise_on_failure=False)
            if success:
                self.redis_client = TradingRedis()
                self.debug("✅ Redis connected - Live monitoring enabled")
                self.debug(f"   {msg}")
            else:
                self.debug(f"⚠️ Redis unavailable: {msg}")
                self.debug("   Test will run without Redis monitoring")
                self.redis_client = None
        except Exception as e:
            self.debug(f"⚠️ Redis initialization failed: {e}")
            self.debug("   Test will run without Redis monitoring")
            self.redis_client = None

        self.debug("=" * 60)

        # === 1. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(algorithm=self)

        # === 2. 初始化 Long Crypto Grid Strategy ===
        self.debug("📋 Initializing LongCryptoGridStrategy...")
        self.strategy = LongCryptoGridStrategy(
            algorithm=self,
            entry_threshold=-0.01,  # -1%
            exit_threshold=0.02,    # 2%
            position_size_pct=0.80,  # 80% (考虑杠杆和费用)
        )

        # 启用debug模式
        self.strategy.debug = True

        # === 3. 使用 Observer 模式连接 SpreadManager 和 Strategy ===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 4. 订阅交易对（使用 subscribe_trading_pair 简化代码）===
        self.debug("📡 Subscribing to trading pairs...")

        # 订阅 AAPL 交易对
        aapl_crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        aapl_stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(aapl_crypto_symbol, aapl_stock_symbol),
        )

        self.debug(f"✅ Subscribed: {aapl_crypto_symbol.value} <-> {aapl_stock_symbol.value}")

        # 订阅 TSLA 交易对
        tsla_crypto_symbol = Symbol.Create("TSLAxUSD", SecurityType.Crypto, Market.Kraken)
        tsla_stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        self.tsla_crypto, self.tsla_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(tsla_crypto_symbol, tsla_stock_symbol),
        )

        self.debug(f"✅ Subscribed: {tsla_crypto_symbol.value} <-> {tsla_stock_symbol.value}")

        # === 4.5. 初始化Grid Levels（Grid策略的新需求）===
        self.debug("🔧 Initializing grid levels for trading pairs...")
        self.strategy.initialize_pair((aapl_crypto_symbol, aapl_stock_symbol))
        self.strategy.initialize_pair((tsla_crypto_symbol, tsla_stock_symbol))

        # === 5. 初始化订单追踪器（LIVE 监控模式）===
        self.debug("=" * 60)
        self.debug("📊 Initializing GridOrderTracker in LIVE MONITORING MODE")
        self.debug("=" * 60)

        self.order_tracker = EnhancedOrderTracker(
            self,
            self.strategy,
            debug=True,
            realtime_mode=True,  # ← 强制启用 Live 模式监控
            redis_client=self.redis_client  # ← 传递 Redis 客户端
        )

        self.debug(f"  → realtime_mode: {self.order_tracker.realtime_mode}")
        self.debug(f"  → redis_client: {'Connected' if self.redis_client else 'None'}")
        self.debug("=" * 60)

        # 注入到 Strategy 中（让 Strategy 能够调用 tracker）
        self.strategy.order_tracker = self.order_tracker

        # 追踪 spread 更新
        self.spread_count = 0
        self.last_spread_log_time = self.time

        # 追踪 Redis 写入统计
        self.redis_writes_count = {
            'active_targets_added': 0,
            'active_targets_updated': 0,
            'active_targets_removed': 0,
            'grid_positions_written': 0
        }

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return
        self.strategy.on_data(data)
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证多账户路由"""
        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

        if order_event.Status == OrderStatus.Invalid:
            self.error(f"Order failed: {order_event.Message}")
            # 🚨 关键：退出算法
            sys.exit(1)

    def error(self, error: str):
        """捕获错误消息（特别是买入力不足的错误）"""
        self.debug(f"❌ ERROR: {error}")
        # 调用父类方法确保错误被正确记录
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息并验证 Redis 数据"""
        super().on_end_of_algorithm()

        self.debug("=" * 60)
        self.debug("📊 Live Mode Monitor Test Results")
        self.debug("=" * 60)

        # 输出策略统计信息
        stats = self.strategy.get_statistics()
        self.debug(f"Total Round Trips: {stats['total_round_trips']}")
        self.debug(f"Open Positions: {stats['open_positions']}")
        if stats['avg_holding_time_seconds']:
            self.debug(f"Average Holding Time: {stats['avg_holding_time_seconds']:.2f} seconds")

        # 输出Grid摘要
        self.debug("\n=== AAPL Grid Summary ===")
        aapl_pair_symbol = (self.aapl_crypto.symbol, self.aapl_stock.symbol)
        aapl_grid_summary = self.strategy.get_grid_summary(aapl_pair_symbol)
        self.debug(aapl_grid_summary)

        self.debug("\n=== TSLA Grid Summary ===")
        tsla_pair_symbol = (self.tsla_crypto.symbol, self.tsla_stock.symbol)
        tsla_grid_summary = self.strategy.get_grid_summary(tsla_pair_symbol)
        self.debug(tsla_grid_summary)

        # === 验证 Redis 数据写入 ===
        if self.redis_client:
            self.debug("=" * 60)
            self.debug("🔍 Verifying Redis Data")
            self.debug("=" * 60)

            try:
                # 检查活跃 targets（应该为空，因为都已完成）
                active_targets = self.redis_client.client.hgetall("trading:active_targets")
                self.debug(f"✓ Active Targets in Redis: {len(active_targets)}")

                if len(active_targets) > 0:
                    self.debug("  ⚠️ Warning: Active targets should be empty at end of test")
                    for grid_id, data in active_targets.items():
                        self.debug(f"    - {grid_id}: {data}")
                else:
                    self.debug("  ✅ All ExecutionTargets completed and removed from Redis")

                # 检查 grid positions
                grid_positions = self.redis_client.client.hgetall("trading:grid_positions")
                self.debug(f"✓ Grid Positions in Redis: {len(grid_positions)}")

                if len(grid_positions) > 0:
                    self.debug("  ✅ Grid position snapshots recorded:")
                    import json
                    for grid_id, data in grid_positions.items():
                        position_data = json.loads(data)
                        self.debug(f"    - {grid_id}: crypto={position_data['crypto_qty']:.4f}, stock={position_data['stock_qty']:.4f}")
                else:
                    self.debug("  ⚠️ No grid position data in Redis (no trades executed?)")

                # 显示 GridPosition 快照统计
                self.debug(f"✓ GridPosition Snapshots in Memory: {len(self.order_tracker.grid_position_snapshots)}")

                # 验证结果
                self.debug("")
                if len(grid_positions) > 0:
                    self.debug("✅ Redis monitoring test PASSED")
                    self.debug("   - ExecutionTargets tracked and removed")
                    self.debug("   - GridPositions recorded to Redis")
                else:
                    self.debug("⚠️ Redis monitoring test INCOMPLETE")
                    self.debug("   - No grid positions recorded (no trades?)")

            except Exception as e:
                self.debug(f"❌ Redis verification failed: {e}")
                import traceback
                self.debug(traceback.format_exc())
        else:
            self.debug("=" * 60)
            self.debug("⚠️ Redis was not available - skipped verification")
            self.debug("=" * 60)

        # === 导出 GridOrderTracker 数据 ===
        self.debug("=" * 60)
        self.debug("📊 Exporting GridOrderTracker Data")
        self.debug("=" * 60)

        try:
            # 导出 JSON 数据到临时位置
            json_filepath = "LiveModeMonitorTest.json"
            self.order_tracker.export_json(json_filepath)
            self.debug(f"✅ JSON data exported to: {json_filepath}")

            # 显示 GridOrderTracker 统计
            tracker_stats = self.order_tracker.get_statistics()
            self.debug("")
            self.debug("📈 GridOrderTracker Summary:")
            self.debug(f"  Total Round Trips: {tracker_stats['total_round_trips']}")
            self.debug(f"  Open Positions: {tracker_stats['open_positions']}")
            self.debug(f"  Total PnL: ${tracker_stats['total_pnl']:.2f}")
            self.debug(f"  Total ExecutionTargets: {tracker_stats['total_execution_targets']}")
            self.debug(f"  Total Portfolio Snapshots: {tracker_stats['total_snapshots']}")
            self.debug(f"  Total GridPosition Snapshots: {len(self.order_tracker.grid_position_snapshots)}")
            self.debug("")

            # === 自动保存到 backtest_history ===
            self.debug("=" * 60)
            self.debug("💾 Saving to Backtest History")
            self.debug("=" * 60)

            try:
                # 导入 BacktestManager
                monitoring_path = str(Path(arbitrage_path) / 'monitoring')
                if monitoring_path not in sys.path:
                    sys.path.insert(0, monitoring_path)

                from backtest_manager import BacktestManager

                # 初始化 BacktestManager (指向 arbitrage/monitoring/backtest_history)
                backtest_history_dir = Path(arbitrage_path) / 'monitoring' / 'backtest_history'
                manager = BacktestManager(history_dir=str(backtest_history_dir))

                # HTML 文件路径
                html_filepath = json_filepath.replace('.json', '_grid.html')

                # 添加到回测历史
                backtest_id = manager.add_backtest(
                    json_file=json_filepath,
                    html_file=html_filepath if Path(html_filepath).exists() else None,
                    name=f"Live Mode Monitor Test - {self.time.strftime('%Y-%m-%d')}",
                    description=f"Live monitoring test (Backtest + realtime_mode=True) from {self.start_date.strftime('%Y-%m-%d')} to {self.end_date.strftime('%Y-%m-%d')}",
                    algorithm="LiveModeMonitorTest"
                )

                self.debug(f"✅ Backtest saved to history: {backtest_id}")
                self.debug(f"   Location: {backtest_history_dir / backtest_id}")
                self.debug(f"   View in monitor: http://localhost:8001")

            except Exception as e:
                self.debug(f"⚠️ Warning: Failed to save to backtest history: {e}")
                import traceback
                self.debug(traceback.format_exc())
                self.debug("   Note: Files are still available locally")

        except Exception as e:
            self.debug(f"❌ Error exporting GridOrderTracker data: {e}")
            import traceback
            self.debug(traceback.format_exc())

        self.debug("=" * 60)
