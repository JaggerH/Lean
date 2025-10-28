"""
State Persistence 测试 - 阶段1

测试目标:
1. 在 Backtest 环境下触发 state_persistence
2. 在 ExecutionTarget PartiallyFilled 时保存状态并退出
3. 验证保存的数据格式是否正确

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD
- 日期范围: 2025-09-02 至 2025-09-05
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

class StatePersistenceTest(QCAlgorithm):
    """State Persistence 测试"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # 追踪测试状态
        self._partial_fill_detected = False
        self._state_saved = False

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

        # === 5. 初始化Grid Levels ===
        self.debug("🔧 Initializing grid levels for trading pairs...")
        self.strategy.initialize_pair((aapl_crypto_symbol, aapl_stock_symbol))

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return
        self.strategy.on_data(data)
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 在有交易活动后保存状态"""
        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

        # 在第一笔订单成交后，检查是否有需要保存的状态
        if not self._partial_fill_detected and order_event.Status == OrderStatus.Filled:
            # 检查是否有活跃的 ExecutionTarget 或 GridPosition
            has_active_targets = len(self.strategy.execution_manager.active_targets) > 0
            has_positions = len(self.strategy.grid_position_manager.grid_positions) > 0

            if has_active_targets or has_positions:
                self._partial_fill_detected = True
                self.debug("="*60)
                self.debug("🎯 Detected trading activity! Triggering state save...")
                self.debug(f"Active ExecutionTargets: {len(self.strategy.execution_manager.active_targets)}")
                self.debug(f"Grid Positions: {len(self.strategy.grid_position_manager.grid_positions)}")

                # 输出 ExecutionTarget 详情
                for hash_key, target in self.strategy.execution_manager.active_targets.items():
                    crypto_filled, stock_filled = target.quantity_filled
                    crypto_symbol, stock_symbol = target.pair_symbol
                    crypto_target = target.target_qty[crypto_symbol]
                    stock_target = target.target_qty[stock_symbol]
                    # target.status 是 ExecutionStatus enum
                    status_name = target.status.name if hasattr(target.status, 'name') else str(target.status)
                    self.debug(f"  Target {target.grid_id}: Status={status_name}, "
                              f"Filled={crypto_filled:.4f}/{crypto_target:.4f}, {stock_filled:.4f}/{stock_target:.4f}")

                self.debug("="*60)

                # 立即保存状态（订单已成交）
                self._save_state_and_exit()

        if order_event.Status == OrderStatus.Invalid:
            self.error(f"Order failed: {order_event.Message}")
            sys.exit(1)

    def _save_state_and_exit(self):
        """保存状态并验证数据格式"""
        if self._state_saved:
            return

        self._state_saved = True

        self.debug("="*60)
        self.debug("💾 Saving state and verifying format...")
        self.debug("="*60)

        try:
            # 1. 触发持久化（检查 state_persistence 是否可用，而不是 is_enabled）
            if self.strategy.monitoring_context and self.strategy.monitoring_context.state_persistence:
                # 调用 persist() 并传入当前状态
                self.strategy.monitoring_context.state_persistence.persist(
                    grid_positions=self.strategy.grid_position_manager.grid_positions,
                    execution_targets=self.strategy.execution_manager.active_targets
                )

                # 2. 读取保存的数据
                state_data = self.strategy.monitoring_context.state_persistence.restore()

                if not state_data:
                    self.error("❌ No state data found after persistence!")
                    self.Quit()
                    return

                # 3. 验证数据格式
                self._verify_persistence_format(state_data)

                # 4. 输出详细快照
                self._output_state_snapshot(state_data)

            else:
                self.error("❌ StatePersistence not available!")

        except Exception as e:
            self.error(f"❌ Error during state persistence: {e}")
            import traceback
            self.error(traceback.format_exc())

        finally:
            # 5. 退出算法
            self.debug("="*60)
            self.debug("✅ State persistence test completed, exiting...")
            self.debug("="*60)
            self.Quit()

    def _verify_persistence_format(self, state_data: dict):
        """验证持久化数据格式"""
        self.debug("\n📋 Verifying persistence format...")

        errors = []

        # 检查 timestamp
        if "timestamp" not in state_data:
            errors.append("Missing 'timestamp' field")
        else:
            self.debug(f"  ✅ timestamp: {state_data['timestamp']}")

        # 检查 grid_positions
        if "grid_positions" not in state_data:
            errors.append("Missing 'grid_positions' field")
        else:
            grid_positions = state_data["grid_positions"]
            self.debug(f"  ✅ grid_positions: {len(grid_positions)} positions")

            for hash_key, position_data in grid_positions.items():
                if "level_data" not in position_data:
                    errors.append(f"GridPosition {hash_key} missing 'level_data'")
                if "leg1_qty" not in position_data:
                    errors.append(f"GridPosition {hash_key} missing 'leg1_qty'")
                if "leg2_qty" not in position_data:
                    errors.append(f"GridPosition {hash_key} missing 'leg2_qty'")

        # 检查 execution_targets
        if "execution_targets" not in state_data:
            errors.append("Missing 'execution_targets' field")
        else:
            execution_targets = state_data["execution_targets"]
            self.debug(f"  ✅ execution_targets: {len(execution_targets)} targets")

            for hash_key, target_data in execution_targets.items():
                # 检查必需字段
                required_fields = ['grid_id', 'target_qty', 'status', 'order_groups']
                for field in required_fields:
                    if field not in target_data:
                        errors.append(f"ExecutionTarget {hash_key} missing '{field}'")

                # 检查 order_groups 结构
                if "order_groups" in target_data:
                    for idx, og_data in enumerate(target_data["order_groups"]):
                        if "completed_tickets_json" not in og_data:
                            errors.append(f"OrderGroup {idx} missing 'completed_tickets_json'")
                        if "active_broker_ids" not in og_data:
                            errors.append(f"OrderGroup {idx} missing 'active_broker_ids'")

        # 输出验证结果
        if errors:
            self.error("\n❌ Format validation FAILED:")
            for error in errors:
                self.error(f"  - {error}")
        else:
            self.debug("\n✅ Format validation PASSED!")

    def _output_state_snapshot(self, state_data: dict):
        """输出状态快照详情"""
        self.debug("\n" + "="*60)
        self.debug("📊 State Snapshot Details")
        self.debug("="*60)

        # 输出 GridPositions
        grid_positions = state_data.get("grid_positions", {})
        self.debug(f"\n📦 GridPositions ({len(grid_positions)} total):")
        for hash_key, position_data in grid_positions.items():
            level_data = position_data.get("level_data", {})
            self.debug(f"  Hash: {hash_key}")
            self.debug(f"    Level ID: {level_data.get('level_id')}")
            self.debug(f"    Type: {level_data.get('type')}")
            self.debug(f"    Spread: {level_data.get('spread_pct'):.4f}")
            self.debug(f"    Direction: {level_data.get('direction')}")
            self.debug(f"    Leg1 Qty: {position_data.get('leg1_qty', 0):.4f}")
            self.debug(f"    Leg2 Qty: {position_data.get('leg2_qty', 0):.4f}")

        # 输出 ExecutionTargets
        execution_targets = state_data.get("execution_targets", {})
        self.debug(f"\n🎯 ExecutionTargets ({len(execution_targets)} total):")
        for hash_key, target_data in execution_targets.items():
            self.debug(f"  Hash: {hash_key}")
            self.debug(f"    Grid ID: {target_data.get('grid_id')}")
            self.debug(f"    Status: {target_data.get('status')}")
            self.debug(f"    Target Qty: {target_data.get('target_qty')}")
            self.debug(f"    Spread Direction: {target_data.get('spread_direction')}")

            order_groups = target_data.get("order_groups", [])
            self.debug(f"    OrderGroups: {len(order_groups)}")
            for idx, og_data in enumerate(order_groups):
                completed_count = len(og_data.get("completed_tickets_json", []))
                active_count = len(og_data.get("active_broker_ids", []))
                self.debug(f"      Group {idx}: {completed_count} completed, {active_count} active")

        self.debug("="*60)

    def error(self, error: str):
        """捕获错误消息"""
        self.debug(f"❌ ERROR: {error}")
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束"""
        super().on_end_of_algorithm()
        self.debug("="*60)
        self.debug("📊 State Persistence Test Completed")
        self.debug("="*60)
