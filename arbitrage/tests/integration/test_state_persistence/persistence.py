"""
State Persistence Test - 验证状态保存功能

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD
- 日期范围: 2025-09-02 至 2025-09-05 (短期测试)
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 策略: BothSideGridStrategy

测试目标:
1. 触发部分成交场景（PartiallyFilled ExecutionTargets）
2. 验证 GridPositions 正确保存到 ObjectStore/Redis
3. 验证 ExecutionTargets 正确保存，包含:
   - Active orders (active_broker_ids)
   - Completed orders (completed_tickets_json)
4. 验证 JSON 格式正确性
5. 输出保存的状态供 recovery.py 使用
"""

import sys
from pathlib import Path
from datetime import timedelta
import json

# Add arbitrage directory to path
arbitrage_path = str(Path(__file__).parent.parent.parent.parent)
sys.path.insert(0, arbitrage_path)

from AlgorithmImports import *

# Add arbitrage to path for imports
sys.path.insert(0, str(Path(arbitrage_path) / 'arbitrage'))

from spread_manager import SpreadManager
from strategy.both_side_grid_strategy import BothSideGridStrategy
from monitoring.order_tracker import OrderTracker as EnhancedOrderTracker

class StatePersistenceTest(QCAlgorithm):
    """State Persistence 测试 - 保存状态"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围 (短期测试，生成部分成交)
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # === 1. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(algorithm=self)

        # === 2. 初始化 Both Side Grid Strategy ===
        self.debug("📋 Initializing BothSideGridStrategy...")
        self.strategy = BothSideGridStrategy(
            algorithm=self,
            long_crypto_entry=-0.01,   # -1% (long crypto entry threshold)
            long_crypto_exit=0.02,     # 2% (long crypto exit threshold)
            short_crypto_entry=0.03,   # 3% (short crypto entry threshold)
            short_crypto_exit=-0.009,  # -0.9% (short crypto exit threshold)
            position_size_pct=0.50,    # 50% (smaller size to increase partial fill chance)
        )

        # 启用debug模式
        self.strategy.debug = True

        # === 3. 使用 Observer 模式连接 SpreadManager 和 Strategy ===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 4. 订阅交易对（只测试 AAPL，简化测试）===
        self.debug("📡 Subscribing to trading pair...")

        # 订阅 AAPL 交易对
        aapl_crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        aapl_stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(aapl_crypto_symbol, aapl_stock_symbol),
        )

        self.debug(f"✅ Subscribed: {aapl_crypto_symbol.value} <-> {aapl_stock_symbol.value}")

        # === 4.5. 初始化Grid Levels ===
        self.debug("🔧 Initializing grid levels for trading pair...")
        self.strategy.initialize_pair((aapl_crypto_symbol, aapl_stock_symbol))

        # === 5. 初始化独立的订单追踪器 ===
        self.debug("📊 Initializing GridOrderTracker...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy, debug=True)

        # 注入到 Strategy 中
        self.strategy.order_tracker = self.order_tracker

        # 追踪测试状态
        self.execution_events_count = 0
        self.state_saved = False

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return
        self.strategy.on_data(data)
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证状态保存触发"""
        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

        if order_event.Status == OrderStatus.Invalid:
            self.error(f"Order failed: {order_event.Message}")
            sys.exit(1)

        # 追踪执行事件
        if order_event.Status in [OrderStatus.Filled, OrderStatus.PartiallyFilled, OrderStatus.Canceled]:
            self.execution_events_count += 1

    def error(self, error: str):
        """捕获错误消息"""
        self.debug(f"❌ ERROR: {error}")
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束 - 验证状态保存并输出JSON"""
        super().on_end_of_algorithm()

        self.debug("=" * 80)
        self.debug("📊 State Persistence Test Results")
        self.debug("=" * 80)

        # === 1. 输出策略统计 ===
        stats = self.strategy.get_statistics()
        self.debug(f"Total Execution Events: {self.execution_events_count}")
        self.debug(f"Total Round Trips: {stats['total_round_trips']}")
        self.debug(f"Open Positions: {stats['open_positions']}")

        # === 2. 手动触发状态持久化（Backtest模式需要手动调用）===
        self.debug("\n💾 Manually triggering state persistence...")
        if hasattr(self.strategy, 'monitoring_context') and self.strategy.monitoring_context and self.strategy.monitoring_context.state_persistence:
            self.strategy.monitoring_context.state_persistence.persist(
                grid_positions=self.strategy.grid_position_manager.grid_positions,
                execution_targets=self.strategy.execution_manager.active_targets
            )
            self.debug("✅ State manually persisted to ObjectStore")
        else:
            self.debug("⚠️ MonitoringContext or StatePersistence not available")

        # === 3. 检查 GridPositions ===
        grid_positions = self.strategy.grid_position_manager.grid_positions
        self.debug(f"\n📊 GridPositions Count: {len(grid_positions)}")

        for grid_level, grid_position in grid_positions.items():
            leg1_qty, leg2_qty = grid_position.quantity
            self.debug(f"  - {grid_level.level_id}: leg1={leg1_qty:.4f}, leg2={leg2_qty:.4f}")

        # === 4. 检查 ExecutionTargets ===
        active_targets = self.strategy.execution_manager.active_targets
        self.debug(f"\n📊 ExecutionTargets Count: {len(active_targets)}")

        for hash_key, exec_target in active_targets.items():
            # Handle both Enum and int status
            status_str = exec_target.status.name if hasattr(exec_target.status, 'name') else str(exec_target.status)
            self.debug(f"  - {exec_target.grid_id}: Status={status_str}")
            self.debug(f"    OrderGroups: {len(exec_target.order_groups)}")
            for og in exec_target.order_groups:
                # Count completed tickets by filtering order_tickets
                from AlgorithmImports import OrderStatus
                completed = sum(1 for t in og.order_tickets if t.status in [OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid])
                active = len(og.active_broker_ids) if og.active_broker_ids else 0
                # Handle both Enum and int type
                type_str = og.type.name if hasattr(og.type, 'name') else str(og.type)
                self.debug(f"      - Type={type_str}, Completed={completed}, Active={active}")

        # === 5. 验证保存的状态 (从 ObjectStore 读取) ===
        self.debug("\n" + "=" * 80)
        self.debug("💾 Verifying Saved State")
        self.debug("=" * 80)

        try:
            # 读取保存的状态
            objectstore_path = f"trade_data/state/{self.strategy.__class__.__name__}/latest"

            if self.ObjectStore.ContainsKey(objectstore_path):
                saved_json = self.ObjectStore.Read(objectstore_path)
                saved_state = json.loads(saved_json)

                self.debug(f"✅ State saved to ObjectStore: {objectstore_path}")
                self.debug(f"   Timestamp: {saved_state.get('timestamp')}")
                self.debug(f"   GridPositions: {len(saved_state.get('grid_positions', {}))}")
                self.debug(f"   ExecutionTargets: {len(saved_state.get('execution_targets', {}))}")

                # === 6. 输出完整JSON供检查 ===
                self.debug("\n" + "=" * 80)
                self.debug("📄 Saved State JSON Preview")
                self.debug("=" * 80)

                # 格式化输出 JSON (前100行)
                json_preview = json.dumps(saved_state, indent=2)
                lines = json_preview.split('\n')
                preview_lines = lines[:100] if len(lines) > 100 else lines

                for line in preview_lines:
                    self.debug(line)

                if len(lines) > 100:
                    self.debug(f"... ({len(lines) - 100} more lines)")

                # === 7. 验证 JSON 结构 ===
                self.debug("\n" + "=" * 80)
                self.debug("✅ JSON Structure Validation")
                self.debug("=" * 80)

                # 验证顶层字段
                assert 'timestamp' in saved_state, "Missing 'timestamp' field"
                assert 'grid_positions' in saved_state, "Missing 'grid_positions' field"
                assert 'execution_targets' in saved_state, "Missing 'execution_targets' field"
                self.debug("✅ Top-level fields present")

                # 验证 GridPositions 结构
                for hash_key, pos_data in saved_state['grid_positions'].items():
                    assert 'level_data' in pos_data, f"Missing 'level_data' in GridPosition {hash_key}"
                    assert 'leg1_qty' in pos_data, f"Missing 'leg1_qty' in GridPosition {hash_key}"
                    assert 'leg2_qty' in pos_data, f"Missing 'leg2_qty' in GridPosition {hash_key}"

                    level_data = pos_data['level_data']
                    assert 'level_id' in level_data, "Missing 'level_id' in level_data"
                    assert 'type' in level_data, "Missing 'type' in level_data"
                    assert 'spread_pct' in level_data, "Missing 'spread_pct' in level_data"
                    assert 'direction' in level_data, "Missing 'direction' in level_data"
                    assert 'pair_symbol' in level_data, "Missing 'pair_symbol' in level_data"

                self.debug(f"✅ GridPositions structure valid ({len(saved_state['grid_positions'])} positions)")

                # 验证 ExecutionTargets 结构
                for hash_key, target_data in saved_state['execution_targets'].items():
                    assert 'grid_id' in target_data, f"Missing 'grid_id' in ExecutionTarget {hash_key}"
                    assert 'target_qty' in target_data, f"Missing 'target_qty' in ExecutionTarget {hash_key}"
                    assert 'status' in target_data, f"Missing 'status' in ExecutionTarget {hash_key}"
                    assert 'order_groups' in target_data, f"Missing 'order_groups' in ExecutionTarget {hash_key}"

                    # 验证 OrderGroups 结构
                    for og_data in target_data['order_groups']:
                        assert 'type' in og_data, "Missing 'type' in OrderGroup"
                        assert 'completed_tickets_json' in og_data, "Missing 'completed_tickets_json' in OrderGroup"
                        assert 'active_broker_ids' in og_data, "Missing 'active_broker_ids' in OrderGroup"

                self.debug(f"✅ ExecutionTargets structure valid ({len(saved_state['execution_targets'])} targets)")

                # === 8. 成功标记 ===
                self.state_saved = True
                self.debug("\n" + "=" * 80)
                self.debug("✅ PERSISTENCE TEST PASSED")
                self.debug("=" * 80)
                self.debug(f"State successfully saved and validated at: {objectstore_path}")
                self.debug("Ready for recovery test!")

            else:
                self.error(f"❌ State not found in ObjectStore: {objectstore_path}")
                self.error("PERSISTENCE TEST FAILED")

        except Exception as e:
            self.error(f"❌ Error verifying saved state: {e}")
            import traceback
            self.error(traceback.format_exc())
            self.error("PERSISTENCE TEST FAILED")

        self.debug("=" * 80)
