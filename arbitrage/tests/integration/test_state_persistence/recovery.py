"""
State Recovery Test - 验证状态恢复功能

测试场景:
- 加载 persistence.py 保存的状态
- 初始化新的算法实例（模拟算法重启）
- 调用 strategy.restore_state() 恢复状态
- 验证恢复的准确性（严格相等性检查）

验证内容:
1. GridPositions 数量和数量值
2. ExecutionTargets 状态和 OrderGroups
3. Active orders 重连接
4. Completed orders 反序列化

测试目标:
- 确保状态恢复后完全等同于保存前的状态
- 验证 hash 匹配逻辑正确工作
- 验证 OrderTicket 序列化/反序列化正确
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

class StateRecoveryTest(QCAlgorithm):
    """State Recovery 测试 - 恢复状态"""

    def initialize(self):
        """初始化算法 - 模拟算法重启"""
        # 设置回测时间范围 (与 persistence.py 相同)
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # === 1. 读取保存的状态（在初始化之前，用于验证）===
        self.debug("=" * 80)
        self.debug("📂 Loading Saved State")
        self.debug("=" * 80)

        try:
            objectstore_path = "trade_data/state/BothSideGridStrategy/latest"

            if self.ObjectStore.ContainsKey(objectstore_path):
                saved_json = self.ObjectStore.Read(objectstore_path)
                self.saved_state = json.loads(saved_json)

                self.debug(f"✅ Loaded state from: {objectstore_path}")
                self.debug(f"   Timestamp: {self.saved_state.get('timestamp')}")
                self.debug(f"   GridPositions: {len(self.saved_state.get('grid_positions', {}))}")
                self.debug(f"   ExecutionTargets: {len(self.saved_state.get('execution_targets', {}))}")
            else:
                self.error(f"❌ No saved state found at: {objectstore_path}")
                self.error("Please run persistence.py first!")
                sys.exit(1)

        except Exception as e:
            self.error(f"❌ Error loading saved state: {e}")
            import traceback
            self.error(traceback.format_exc())
            sys.exit(1)

        # === 2. 初始化 SpreadManager ===
        self.debug("\n" + "=" * 80)
        self.debug("📊 Initializing SpreadManager...")
        self.debug("=" * 80)
        self.spread_manager = SpreadManager(algorithm=self)

        # === 3. 初始化 Both Side Grid Strategy ===
        self.debug("📋 Initializing BothSideGridStrategy...")
        self.strategy = BothSideGridStrategy(
            algorithm=self,
            long_crypto_entry=-0.01,   # -1% (same as persistence.py)
            long_crypto_exit=0.02,     # 2%
            short_crypto_entry=0.03,   # 3%
            short_crypto_exit=-0.009,  # -0.9%
            position_size_pct=0.50,    # 50% (same as persistence.py)
        )

        # 启用debug模式
        self.strategy.debug = True

        # === 4. 使用 Observer 模式连接 SpreadManager 和 Strategy ===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 5. 订阅交易对（与 persistence.py 相同）===
        self.debug("📡 Subscribing to trading pair...")

        aapl_crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        aapl_stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(aapl_crypto_symbol, aapl_stock_symbol),
        )

        self.debug(f"✅ Subscribed: {aapl_crypto_symbol.value} <-> {aapl_stock_symbol.value}")

        # === 6. 初始化Grid Levels (CRITICAL: 必须在 restore_state 之前) ===
        self.debug("🔧 Initializing grid levels for trading pair...")
        self.strategy.initialize_pair((aapl_crypto_symbol, aapl_stock_symbol))

        # === 7. 初始化订单追踪器 ===
        self.debug("📊 Initializing GridOrderTracker...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy, debug=True)
        self.strategy.order_tracker = self.order_tracker

        # === 8. 恢复状态 (CRITICAL: 在 initialize_pair 之后) ===
        self.debug("\n" + "=" * 80)
        self.debug("🔄 Restoring State from ObjectStore")
        self.debug("=" * 80)

        try:
            # 调用策略的恢复方法
            self.strategy.restore_state()
            self.debug("✅ State restoration completed")

        except Exception as e:
            self.error(f"❌ Error restoring state: {e}")
            import traceback
            self.error(traceback.format_exc())
            sys.exit(1)

        # === 9. 验证恢复的状态 ===
        self.debug("\n" + "=" * 80)
        self.debug("✅ Verifying Restored State")
        self.debug("=" * 80)

        # 追踪测试状态
        self.recovery_verified = False

        # 验证恢复的状态
        self._verify_restored_state()

    def _verify_restored_state(self):
        """验证恢复的状态与保存的状态完全一致"""

        # === 1. 验证 GridPositions ===
        self.debug("\n📊 Verifying GridPositions...")

        restored_grid_positions = self.strategy.grid_position_manager.grid_positions
        saved_grid_positions = self.saved_state.get('grid_positions', {})

        self.debug(f"  Saved count: {len(saved_grid_positions)}")
        self.debug(f"  Restored count: {len(restored_grid_positions)}")

        # 严格相等性检查：数量必须相同
        if len(restored_grid_positions) != len(saved_grid_positions):
            self.error(f"❌ GridPosition count mismatch: saved={len(saved_grid_positions)}, restored={len(restored_grid_positions)}")
            sys.exit(1)

        # 验证每个 GridPosition 的数量
        for grid_level, grid_position in restored_grid_positions.items():
            hash_key = str(hash(grid_level))
            leg1_qty, leg2_qty = grid_position.quantity

            if hash_key not in saved_grid_positions:
                self.error(f"❌ GridPosition hash not found in saved state: {hash_key}")
                sys.exit(1)

            saved_pos = saved_grid_positions[hash_key]
            saved_leg1 = saved_pos['leg1_qty']
            saved_leg2 = saved_pos['leg2_qty']

            # 严格相等性检查（允许浮点误差）
            if abs(leg1_qty - saved_leg1) > 1e-6 or abs(leg2_qty - saved_leg2) > 1e-6:
                self.error(f"❌ GridPosition quantity mismatch for {grid_level.level_id}:")
                self.error(f"   Saved: leg1={saved_leg1}, leg2={saved_leg2}")
                self.error(f"   Restored: leg1={leg1_qty}, leg2={leg2_qty}")
                sys.exit(1)

            self.debug(f"  ✅ {grid_level.level_id}: leg1={leg1_qty:.4f}, leg2={leg2_qty:.4f}")

        self.debug("✅ GridPositions verification passed")

        # === 2. 验证 ExecutionTargets ===
        self.debug("\n📊 Verifying ExecutionTargets...")

        restored_exec_targets = self.strategy.execution_manager.active_targets
        saved_exec_targets = self.saved_state.get('execution_targets', {})

        self.debug(f"  Saved count: {len(saved_exec_targets)}")
        self.debug(f"  Restored count: {len(restored_exec_targets)}")

        # 严格相等性检查：数量必须相同
        if len(restored_exec_targets) != len(saved_exec_targets):
            self.error(f"❌ ExecutionTarget count mismatch: saved={len(saved_exec_targets)}, restored={len(restored_exec_targets)}")
            sys.exit(1)

        # 验证每个 ExecutionTarget 的状态
        for hash_key, exec_target in restored_exec_targets.items():
            hash_str = str(hash_key)

            if hash_str not in saved_exec_targets:
                self.error(f"❌ ExecutionTarget hash not found in saved state: {hash_str}")
                sys.exit(1)

            saved_target = saved_exec_targets[hash_str]

            # 验证基本字段
            if exec_target.grid_id != saved_target['grid_id']:
                self.error(f"❌ ExecutionTarget grid_id mismatch: saved={saved_target['grid_id']}, restored={exec_target.grid_id}")
                sys.exit(1)

            # Handle both Enum and int status
            # If it's an Enum, get the value; otherwise use as is
            restored_status = exec_target.status.value if hasattr(exec_target.status, 'value') else exec_target.status
            if int(restored_status) != int(saved_target['status']):
                self.error(f"❌ ExecutionTarget status mismatch: saved={saved_target['status']}, restored={restored_status}")
                sys.exit(1)

            # 验证 OrderGroups 数量
            saved_og_count = len(saved_target['order_groups'])
            restored_og_count = len(exec_target.order_groups)

            if restored_og_count != saved_og_count:
                self.error(f"❌ OrderGroup count mismatch for {exec_target.grid_id}: saved={saved_og_count}, restored={restored_og_count}")
                sys.exit(1)

            # 验证每个 OrderGroup
            for idx, og in enumerate(exec_target.order_groups):
                saved_og = saved_target['order_groups'][idx]

                # 验证 OrderGroup 类型 (handle both Enum and int)
                restored_type = og.type.value if hasattr(og.type, 'value') else og.type
                if int(restored_type) != int(saved_og['type']):
                    self.error(f"❌ OrderGroup type mismatch: saved={saved_og['type']}, restored={restored_type}")
                    sys.exit(1)

                # 验证 completed_tickets 数量
                saved_completed = len(saved_og['completed_tickets_json'])
                # Count completed by filtering order_tickets
                restored_completed = sum(1 for t in og.order_tickets if t.status in [OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid])

                if restored_completed != saved_completed:
                    self.error(f"❌ Completed tickets count mismatch: saved={saved_completed}, restored={restored_completed}")
                    sys.exit(1)

                # 验证 active_broker_ids 数量
                saved_active = len(saved_og.get('active_broker_ids', []))
                restored_active = len(og.active_broker_ids) if og.active_broker_ids else 0

                if restored_active != saved_active:
                    self.error(f"❌ Active broker IDs count mismatch: saved={saved_active}, restored={restored_active}")
                    sys.exit(1)

                # Handle both Enum and int for display
                type_str = og.type.name if hasattr(og.type, 'name') else str(og.type)
                self.debug(f"  ✅ {exec_target.grid_id} - OrderGroup[{idx}]: Type={type_str}, Completed={restored_completed}, Active={restored_active}")

            # Handle both Enum and int for display
            status_str = exec_target.status.name if hasattr(exec_target.status, 'name') else str(exec_target.status)
            self.debug(f"  ✅ {exec_target.grid_id}: Status={status_str}, OrderGroups={restored_og_count}")

        self.debug("✅ ExecutionTargets verification passed")

        # === 3. 总结验证结果 ===
        self.debug("\n" + "=" * 80)
        self.debug("✅ STATE RECOVERY VERIFICATION PASSED")
        self.debug("=" * 80)
        self.debug(f"  GridPositions: {len(restored_grid_positions)} restored correctly")
        self.debug(f"  ExecutionTargets: {len(restored_exec_targets)} restored correctly")
        self.debug("  All quantities and statuses match exactly")
        self.debug("=" * 80)

        self.recovery_verified = True

    def on_data(self, data: Slice):
        """处理数据 - 不执行交易，只验证恢复"""
        # 不执行任何交易，只是为了满足算法框架要求
        pass

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        self.strategy.on_order_event(order_event)

        if order_event.Status == OrderStatus.Invalid:
            self.error(f"Order failed: {order_event.Message}")
            sys.exit(1)

    def error(self, error: str):
        """捕获错误消息"""
        self.debug(f"❌ ERROR: {error}")
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束 - 最终验证"""
        super().on_end_of_algorithm()

        self.debug("=" * 80)
        self.debug("📊 State Recovery Test Results")
        self.debug("=" * 80)

        if self.recovery_verified:
            self.debug("✅ RECOVERY TEST PASSED")
            self.debug("State was successfully restored and verified!")
        else:
            self.error("❌ RECOVERY TEST FAILED")
            self.error("State verification did not complete successfully")

        self.debug("=" * 80)
