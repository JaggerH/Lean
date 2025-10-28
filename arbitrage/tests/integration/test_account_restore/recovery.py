"""
State Recovery 测试 - 阶段2

测试目标:
1. 从 ObjectStore 恢复持久化状态
2. 验证 GridPositionManager 和 ExecutionManager 正确恢复
3. 对比恢复的数据与保存时的快照

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD
- 日期范围: 2025-09-02 至 2025-09-05 (与 persistence 相同)
- 策略: LongCryptoGridStrategy
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
from strategy.long_crypto_grid_strategy import LongCryptoGridStrategy

class StateRecoveryTest(QCAlgorithm):
    """State Recovery 测试"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围（与 persistence 相同）
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # 追踪验证状态
        self._state_verified = False
        self._saved_state_data = None

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

        # === 4. 订阅交易对 ===
        self.debug("📡 Subscribing to trading pairs...")

        # 订阅 AAPL 交易对
        aapl_crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        aapl_stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(aapl_crypto_symbol, aapl_stock_symbol),
        )

        self.debug(f"✅ Subscribed: {aapl_crypto_symbol.value} <-> {aapl_stock_symbol.value}")

        # === 5. 初始化Grid Levels（必须在 restore_state 之前）===
        self.debug("🔧 Initializing grid levels for trading pairs...")
        self.strategy.initialize_pair((aapl_crypto_symbol, aapl_stock_symbol))

        # === 6. 读取保存的状态数据（用于对比）===
        try:
            # ⚠️ 直接检查 state_persistence 是否存在（支持 Backtest 模式测试）
            if self.strategy.monitoring_context and self.strategy.monitoring_context.state_persistence:
                self._saved_state_data = self.strategy.monitoring_context.state_persistence.restore()
                if self._saved_state_data:
                    self.debug(f"✅ Loaded saved state for comparison")
                    self.debug(f"   GridPositions: {len(self._saved_state_data.get('grid_positions', {}))}")
                    self.debug(f"   ExecutionTargets: {len(self._saved_state_data.get('execution_targets', {}))}")
                else:
                    self.error("❌ No saved state data found! Run persistence.py first.")
        except Exception as e:
            self.error(f"❌ Error loading saved state: {e}")
            import traceback
            self.error(traceback.format_exc())

        # === 7. 恢复状态（必须在 initialize_pair 之后）===
        self.debug("="*60)
        self.debug("🔄 Restoring state from persistence...")
        self.debug("="*60)

        try:
            self.strategy.restore_state()
        except Exception as e:
            self.error(f"❌ Error restoring state: {e}")
            import traceback
            self.error(traceback.format_exc())

    def on_data(self, data: Slice):
        """处理数据 - 验证恢复状态"""
        # 在第一次 on_data 时验证恢复状态
        if not self._state_verified and self._saved_state_data:
            self._state_verified = True
            self._verify_restored_state()

        if not data.ticks or len(data.ticks) == 0:
            return

        self.strategy.on_data(data)
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        self.strategy.on_order_event(order_event)

        if order_event.Status == OrderStatus.Invalid:
            self.error(f"Order failed: {order_event.Message}")
            sys.exit(1)

    def _verify_restored_state(self):
        """验证恢复的状态"""
        self.debug("="*60)
        self.debug("🔍 Verifying Restored State")
        self.debug("="*60)

        errors = []

        # === 验证 GridPositions ===
        self.debug("\n📦 Verifying GridPositionManager...")

        saved_grid_positions = self._saved_state_data.get("grid_positions", {})
        current_grid_positions = self.strategy.grid_position_manager.grid_positions

        self.debug(f"  Saved: {len(saved_grid_positions)} positions")
        self.debug(f"  Current: {len(current_grid_positions)} positions")

        if len(saved_grid_positions) != len(current_grid_positions):
            errors.append(
                f"GridPosition count mismatch: saved={len(saved_grid_positions)}, "
                f"restored={len(current_grid_positions)}"
            )
        else:
            # 验证每个 position 的数量
            for hash_str, saved_data in saved_grid_positions.items():
                hash_value = int(hash_str)

                # 查找对应的 GridLevel
                grid_level = self.strategy.grid_level_manager.find_level_by_hash(hash_value)
                if not grid_level:
                    errors.append(f"GridLevel not found for hash={hash_value}")
                    continue

                # 获取恢复的 position
                current_position = self.strategy.grid_position_manager.get_grid_position(grid_level)
                if not current_position:
                    errors.append(f"GridPosition not restored for level={grid_level.level_id}")
                    continue

                # 对比数量
                saved_leg1 = float(saved_data.get("leg1_qty", 0))
                saved_leg2 = float(saved_data.get("leg2_qty", 0))
                current_leg1, current_leg2 = current_position.quantity

                if abs(saved_leg1 - current_leg1) > 0.0001:
                    errors.append(
                        f"Leg1 qty mismatch for {grid_level.level_id}: "
                        f"saved={saved_leg1:.4f}, restored={current_leg1:.4f}"
                    )
                if abs(saved_leg2 - current_leg2) > 0.0001:
                    errors.append(
                        f"Leg2 qty mismatch for {grid_level.level_id}: "
                        f"saved={saved_leg2:.4f}, restored={current_leg2:.4f}"
                    )

                self.debug(f"  ✅ {grid_level.level_id}: "
                          f"Leg1={current_leg1:.4f}, Leg2={current_leg2:.4f}")

        # === 验证 ExecutionTargets ===
        self.debug("\n🎯 Verifying ExecutionManager...")

        saved_exec_targets = self._saved_state_data.get("execution_targets", {})
        current_exec_targets = self.strategy.execution_manager.active_targets

        self.debug(f"  Saved: {len(saved_exec_targets)} targets")
        self.debug(f"  Current: {len(current_exec_targets)} targets")

        if len(saved_exec_targets) != len(current_exec_targets):
            errors.append(
                f"ExecutionTarget count mismatch: saved={len(saved_exec_targets)}, "
                f"restored={len(current_exec_targets)}"
            )
        else:
            # 验证每个 ExecutionTarget
            for hash_str, saved_data in saved_exec_targets.items():
                hash_value = int(hash_str)

                current_target = current_exec_targets.get(hash_value)
                if not current_target:
                    errors.append(f"ExecutionTarget not restored for hash={hash_value}")
                    continue

                # 对比基本字段（安全地获取 status 值）
                saved_status = saved_data.get("status")
                current_status = current_target.status.value if hasattr(current_target.status, 'value') else int(current_target.status)

                if saved_status != current_status:
                    errors.append(
                        f"Status mismatch for {current_target.grid_id}: "
                        f"saved={saved_status}, restored={current_status}"
                    )

                # 对比 order_groups
                saved_og_count = len(saved_data.get("order_groups", []))
                current_og_count = len(current_target.order_groups)

                if saved_og_count != current_og_count:
                    errors.append(
                        f"OrderGroup count mismatch for {current_target.grid_id}: "
                        f"saved={saved_og_count}, restored={current_og_count}"
                    )

                # 安全地获取 status 名称
                status_name = current_target.status.name if hasattr(current_target.status, 'name') else str(current_target.status)
                self.debug(f"  ✅ {current_target.grid_id}: "
                          f"Status={status_name}, "
                          f"OrderGroups={current_og_count}")

                # 验证 OrderGroups 的 tickets
                for idx, order_group in enumerate(current_target.order_groups):
                    saved_og = saved_data.get("order_groups", [])[idx] if idx < len(saved_data.get("order_groups", [])) else None
                    if not saved_og:
                        continue

                    saved_completed_count = len(saved_og.get("completed_tickets_json", []))
                    saved_active_count = len(saved_og.get("active_broker_ids", []))
                    current_ticket_count = len(order_group.order_tickets)

                    self.debug(f"    OrderGroup {idx}: "
                              f"{current_ticket_count} tickets "
                              f"(saved: {saved_completed_count} completed, {saved_active_count} active)")

        # === 输出验证结果 ===
        self.debug("\n" + "="*60)
        if errors:
            self.error("\n❌ State Verification FAILED:")
            for error in errors:
                self.error(f"  - {error}")
        else:
            self.debug("\n✅ State Verification PASSED!")
        self.debug("="*60)

    def error(self, error: str):
        """捕获错误消息"""
        self.debug(f"❌ ERROR: {error}")
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束"""
        super().on_end_of_algorithm()

        self.debug("="*60)
        self.debug("📊 State Recovery Test Completed")
        self.debug("="*60)

        # 输出最终统计
        if self.strategy.grid_position_manager.grid_positions:
            self.debug("\n📦 Final GridPositions:")
            for level, position in self.strategy.grid_position_manager.grid_positions.items():
                leg1, leg2 = position.quantity
                self.debug(f"  {level.level_id}: {leg1:.4f} / {leg2:.4f}")

        if self.strategy.execution_manager.active_targets:
            self.debug("\n🎯 Final ExecutionTargets:")
            for hash_key, target in self.strategy.execution_manager.active_targets.items():
                self.debug(f"  {target.grid_id}: Status={target.status.name}, "
                          f"OrderGroups={len(target.order_groups)}")
