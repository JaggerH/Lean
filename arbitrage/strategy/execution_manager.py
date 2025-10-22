"""
Executor - 执行管理器

负责根据ExecutionTarget执行订单，包括：
1. 验证执行前置条件（市场开盘、价格有效、价差方向）
2. 管理 ExecutionTarget 生命周期
3. 提交订单并注册到GridPositionManager
4. 处理订单事件，更新ExecutionTarget状态

计算可执行数量的职责已移到 ExecutionTarget
"""
from AlgorithmImports import QCAlgorithm, Symbol, OrderEvent, OrderStatus
from typing import Tuple, Dict, List, Optional
from .execution_models import ExecutionTarget, ExecutionStatus, OrderGroup, OrderGroupType


class ExecutionManager:
    """
    执行管理器

    核心职责:
    - 验证执行前置条件
    - 检查pending订单
    - 根据OrderbookDepth计算可执行数量
    - 提交订单并注册OrderGroup

    关键原则:
    - 一个tick最多提交一组订单（一个OrderGroup）
    - 如果有pending订单，跳过执行（等待超时或成交）
    - 下一个tick会用更新的orderbook重新计算
    """

    def __init__(self, algorithm: QCAlgorithm, order_tracker=None, debug: bool = False):
        """
        初始化ExecutionManager

        Args:
            algorithm: QCAlgorithm实例
            debug: 是否启用调试日志
            order_tracker: GridOrderTracker实例（可选）
        """
        self.algorithm = algorithm
        self.debug_enabled = debug
        self.order_tracker = order_tracker
        # Track active ExecutionTargets: key = hash(GridLevel)
        self.active_targets: Dict[int, ExecutionTarget] = {}
        
    # ============================================================================
    #                      注册和查找
    # ============================================================================
    
    def register_execution_target(self, target: ExecutionTarget):
        """
        注册 ExecutionTarget 到活跃列表

        使用 hash(level) 作为索引键

        Args:
            target: ExecutionTarget 对象
        """
        hash_key = hash(target.level)
        target.created_time = self.algorithm.UtcTime
        self.active_targets[hash_key] = target
        self._debug(
            f"📝 Registered ExecutionTarget | Level: {target.grid_id} (hash={hash_key}) | "
            f"Active count: {len(self.active_targets)} \n"
            f"📝 Total Target: {target.pair_symbol[0]}: {target.target_qty[target.pair_symbol[0]]:.4f}, {target.pair_symbol[1].value}: {target.target_qty[target.pair_symbol[1]]:.4f}"
        )

        # 通知 OrderTracker（如果可用）
        if self.order_tracker:
            self.order_tracker.on_execution_target_registered(target)

    def get_active_target_by_order_event(self, order_event: OrderEvent) -> Optional[ExecutionTarget]:
        """
        通过订单事件查找对应的 ExecutionTarget

        使用 Order.Tag (hash(GridLevel)) 直接查找

        Args:
            order_event: OrderEvent对象

        Returns:
            ExecutionTarget 对象，如果找不到返回 None
        """
        order_id = order_event.order_id

        # 通过 Transactions 获取 Order 对象
        order = self.algorithm.transactions.get_order_by_id(order_id)

        # Order.tag 现在是 hash(GridLevel) 的字符串形式
        try:
            hash_key = int(order.tag)
        except (ValueError, AttributeError, TypeError):
            self.algorithm.error(
                f"❌ Order {order_id} has invalid tag: {order.tag} (expected hash value)"
            )
            return None

        # 直接通过 hash 查找 ExecutionTarget
        target = self.active_targets.get(hash_key)
        if not target:
            self.algorithm.error(
                f"❌ CRITICAL: Cannot find ExecutionTarget for order {order_id} | "
                f"Hash: {hash_key} | Symbol: {order_event.symbol.value} | "
                f"Status: {order_event.status} | Active targets: {len(self.active_targets)}"
            )

        return target

    def execute(self, target: ExecutionTarget):
        """
        执行目标仓位 - 优先级分层执行

        执行优先级:
        1. 验证前置条件（市场开盘、价格有效）
        2. 单腿满填检测 → 追单补平（最高优先级）
        3. 双腿市值误差检测 → 标记完成（误差容忍退出）
        4. 常规执行 → 计算可执行数量并提交订单

        Args:
            target: ExecutionTarget对象，包含目标数量和执行参数
        """
        pair_symbol = target.pair_symbol
        level_id = target.grid_id  # 人类可读标识（用于日志）
        crypto_symbol, stock_symbol = pair_symbol

        hash_key = hash(target.level)

        # 注册新的ExecutionTarget
        self.active_targets[hash_key] = target

        # === 步骤 1: 验证前置条件 ===
        if not self._validate_preconditions(pair_symbol):
            return

        # === 步骤 1.5: 记录锚定时间（首次执行时）===
        if target.anchor_time is None:
            target.anchor_time = self.algorithm.UtcTime
            # self._debug(f"⏱️ Anchored ExecutionTarget for level {level_id} at {target.anchor_time}")

        # === 步骤 2: 填补剩余订单（最高优先级）===
        if target.should_fill_remaining_orders():
            self._debug(f"🎯 Detected should_fill_remaining_orders filled for level {level_id}, handling sweep order")
            target.fill_remaining_orders()
            return

        # === 步骤 3: 双腿市值误差检测（优先于超时检查）===
        if target.is_quantity_filled():
            # self._debug(f"✅ Level {level_id} reached target with acceptable error, marking as completed")
            target.status = ExecutionStatus.Filled
            self.on_execution_event(target)
            del self.active_targets[hash_key]
            return

        # === 步骤 4: 超时检查（只对未完成的 target）===
        if target.is_expired():
            target.status = ExecutionStatus.Canceled
            self.on_execution_event(target)
            del self.active_targets[hash_key]
            return
        
        # === 步骤 5: 计算可执行数量（委托给 ExecutionTarget）===
        result = target.calculate_executable_quantity(self.debug_enabled)

        if not result:
            # if target.spread_direction == "SHORT_SPREAD":
                # self._debug(f"⏸️ Level {level_id} no valid execution opportunity this tick")
            return

        leg1, leg2 = result

        # === 步骤 6: 预先创建 OrderGroup（占位，解决异步竞态条件）===
        order_group = OrderGroup(
            grid_id=level_id,
            pair_symbol=pair_symbol,
            order_tickets=[],  # 空列表，稍后在 on_order_event 中填充
            type=OrderGroupType.MarketOrder,
            expected_spread_pct=target.expected_spread_pct,
            expected_ticket_count=2,  # 双腿订单，预期 2 个 tickets
            submit_time=self.algorithm.time
        )
        target.order_groups.append(order_group)  # 立即添加

        # === 步骤 7: 提交订单（不保存 tickets 返回值）===
        self._place_order(leg1, leg2, target.level)

        # === 步骤 8: 更新ExecutionTarget状态（仅首次提交）===
        if target.status == ExecutionStatus.New:
            target.status = ExecutionStatus.Submitted

    def _validate_preconditions(self, pair_symbol: Tuple[Symbol, Symbol]) -> bool:
        """
        验证执行前置条件

        检查:
        1. 两个市场是否同时开盘
        2. 价格数据是否有效

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            True if valid, False otherwise
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 检查市场是否开盘
        crypto_open = self.algorithm.securities[crypto_symbol].exchange.exchange_open
        stock_open = self.algorithm.securities[stock_symbol].exchange.exchange_open

        if not (crypto_open and stock_open):
            self._debug(f"⚠️ Market not open | Crypto: {crypto_open}, Stock: {stock_open}")
            return False

        # 检查价格数据
        crypto_sec = self.algorithm.securities[crypto_symbol]
        stock_sec = self.algorithm.securities[stock_symbol]

        if not crypto_sec.has_data or crypto_sec.price <= 0:
            self._debug(f"⚠️ Invalid crypto price: {crypto_sec.price}")
            return False

        if not stock_sec.has_data or stock_sec.price <= 0:
            self._debug(f"⚠️ Invalid stock price: {stock_sec.price}")
            return False

        return True

    def _place_order(
        self,
        leg1: Tuple[Symbol, float],
        leg2: Tuple[Symbol, float],
        level
    ):
        """
        提交订单对

        使用 hash(level) 作为订单 tag，实现语义化的订单追踪

        注意：不再返回 tickets，tickets 在 on_order_event 中动态绑定

        Args:
            leg1: (Symbol, Quantity) 第一腿
            leg2: (Symbol, Quantity) 第二腿
            level: GridLevel 对象（用于生成订单 tag）
        """
        symbol1, qty1 = leg1
        symbol2, qty2 = leg2

        # 使用 hash(GridLevel) 作为 tag（语义化标识）
        tag = str(hash(level))

        self.algorithm.debug(
            f"📝 Placing orders | Level: {level.level_id} (hash={hash(level)}) | "
            f"{symbol1.value} x {qty1:.2f}, {symbol2.value} x {qty2:.2f}"
        )

        self.algorithm.market_order(
            symbol1,
            qty1,
            asynchronous=True,
            tag=tag
        )

        self.algorithm.market_order(
            symbol2,
            qty2,
            asynchronous=True,
            tag=tag
        )

    def has_active_execution(self, level) -> bool:
        """
        检查是否有活跃的ExecutionTarget

        Args:
            level: GridLevel 对象（包含 pair_symbol 和 level_id）

        Returns:
            True if has active ExecutionTarget, False otherwise
        """
        hash_key = hash(level)
        return hash_key in self.active_targets

    def on_execution_event(self, target: ExecutionTarget):
        """
        统一处理 ExecutionTarget 状态变化事件

        通知 order_tracker 记录状态变化
        order_tracker 会根据 target.status 自行判断事件类型

        Args:
            target: ExecutionTarget 对象
        """
        if self.order_tracker:
            self.order_tracker.on_execution_target_update(target)

    def on_order_event(self, order_event: OrderEvent):
        """
        处理订单事件，更新ExecutionTarget状态

        事件驱动更新链：
        Order → OrderGroup → ExecutionTarget

        Args:
            order_event: OrderEvent对象
        """
        # === 步骤 1: 查找 ExecutionTarget ===
        target = self.get_active_target_by_order_event(order_event)
        if target is None:
            # 找不到对应的 ExecutionTarget，错误已记录
            return

        hash_key = hash(target.level)

        # === 步骤 1.5: 更新手续费 ===
        target.update_fee(order_event)

        # === 步骤 2: 添加 ticket 到 OrderGroup（解决异步竞态条件）===
        target.add_ticket(order_event)

        # === 步骤 3: 根据订单状态更新 ExecutionTarget ===
        if order_event.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
            # 委托给 ExecutionTarget 检查状态
            if target.is_completely_filled():
                target.status = ExecutionStatus.Filled
                self.on_execution_event(target)
                del self.active_targets[hash_key]
                self._debug(f"✅ ExecutionTarget for level {target.grid_id} completed (Filled)")
            else:
                # 至少有一个 OrderGroup 部分成交
                target.status = ExecutionStatus.PartiallyFilled

                # 根据 OrderTracker 模式决定是否触发事件
                # Live 模式：需要实时更新 UI，触发所有事件包括 PartiallyFilled
                # Backtest 模式：只记录终态，跳过 PartiallyFilled 以避免重复记录
                if self.order_tracker and self.order_tracker.realtime_mode:
                    self.on_execution_event(target)
                    self._debug(f"📊 ExecutionTarget for level {target.grid_id} partially filled (Live mode - UI updated)")
                else:
                    self._debug(f"📊 ExecutionTarget for level {target.grid_id} partially filled (Backtest mode - skipped)")

        elif order_event.status in [OrderStatus.Canceled, OrderStatus.Invalid]:
            # 订单失败 - 检查对冲敞口
            self._handle_order_failure(target, order_event)

    def _handle_order_failure(self, target: ExecutionTarget, order_event: OrderEvent):
        """
        处理订单失败情况

        检查对冲敞口，决定是否标记为 Failed

        Args:
            target: ExecutionTarget对象
            order_event: OrderEvent对象
        """
        hash_key = hash(target.level)
        level_id = target.grid_id  # 人类可读标识（用于日志）
        pair_symbol = target.pair_symbol

        self.algorithm.debug(
            f"⚠️ Order {order_event.order_id} failed: {order_event.status} | "
            f"Level: {level_id} | Symbol: {order_event.symbol.value}"
        )

        # # 检查是否有对冲敞口
        # grid_position = target.grid_position_manager.get_grid_position(pair_symbol, grid_id)
        # if grid_position and target.grid_position_manager._has_orphan_position(grid_position):
        #     # 有对冲敞口，标记为 Failed
        #     target.status = ExecutionStatus.Failed
        #     del self.active_targets[execution_key]
        #     self.algorithm.debug(f"❌ ExecutionTarget for grid {grid_id} failed (hedging exposure)")
        # else:
        #     # 委托给 ExecutionTarget 检查是否完全失败
        #     if target.is_completely_failed():
        #         target.status = ExecutionStatus.Failed
        #         del self.active_targets[execution_key]
        #         self.algorithm.debug(f"❌ ExecutionTarget for grid {grid_id} failed (all orders failed)")
        #     else:
        #         # 部分失败，保持 PartiallyFilled 或 Submitted 状态
        #         self._debug(f"⚠️ Partial failure for grid {grid_id}, waiting for other orders")

    def _debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(f"[{self.algorithm.time:%Y-%m-%d %H:%M:%S}]" + message)
