"""
Grid Position Manager - 网格持仓追踪管理器

功能:
1. 管理多个网格线的持仓状态
2. 关联订单组到具体网格线
3. 提供查询接口：判断是否需要开/平仓
4. 处理订单事件，更新对应网格线的持仓
"""
from AlgorithmImports import QCAlgorithm, Symbol, OrderEvent, OrderStatus
from typing import Dict, List, Tuple, Optional, TYPE_CHECKING
from .grid_models import GridLevel, GridPosition
from .grid_level_manager import GridLevelManager


class GridPositionManager:
    """
    网格持仓追踪管理器

    职责:
    - 管理每个交易对的多个网格线持仓（以 Entry GridLevel 为索引）
    - 追踪订单组到网格线的映射
    - 根据订单事件更新网格线持仓
    - 提供持仓状态查询接口（持仓数量、是否达到目标等）
    """

    def __init__(self, algorithm: QCAlgorithm, grid_level_manager: GridLevelManager, debug: bool = False):
        """
        初始化 GridPositionManager

        Args:
            algorithm: QCAlgorithm 实例
            grid_level_manager: GridLevelManager 实例（用于配对查找和 hash 查找）
            debug: 是否启用调试日志
        """
        self.algorithm = algorithm
        self.grid_level_manager = grid_level_manager
        self.debug_enabled = debug

        # 核心索引：Entry GridLevel → GridPosition
        # 只用 Entry GridLevel 作为键，Exit 通过配对关系查找
        self.grid_positions: Dict[GridLevel, GridPosition] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

    # ============================================================================
    #                      持仓状态查询
    # ============================================================================

    def has_reached_target(self, level: GridLevel) -> bool:
        """
        检查指定网格线的持仓是否达到目标

        使用 CalculateOrderPair + IsPairQuantitySufficient 判断：
        - 计算目标持仓（复用 CalculateOrderPair）
        - 从 GridPosition 获取当前持仓（单网格级别）
        - 计算 delta = 目标 - 当前
        - 检查 delta 是否低于 lot_size（低于则认为已达到目标）

        Args:
            level: 网格线配置（包含 pair_symbol 和 level_id）

        Returns:
            True if position reached target, False otherwise
        """
        pair_symbol = level.pair_symbol
        crypto_symbol, stock_symbol = pair_symbol
        level_id = level.level_id  # 直接使用 level_id

        # 1. 计算目标持仓（使用 CalculateOrderPair）
        position_size_pct = level.position_size_pct
        if level.direction == "SHORT_SPREAD":
            position_size_pct = -position_size_pct

        target_order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct
        )

        if not target_order_pair:
            # 无法计算目标（可能是买入力不足），认为已达到目标
            self.debug(f"⚠️ Grid {level_id} cannot calculate target, treating as reached")
            return True

        # 2. 获取该网格线的当前持仓（从 GridPosition）
        grid_position = self.get_grid_position(level)

        if not grid_position:
            # 网格线不存在，说明还没有持仓，可以开仓
            return False


        # 4. 检查 delta 是否低于 lot_size（使用 IsPairQuantityFilled）
        is_filled = self.algorithm.is_pair_quantity_filled(
            crypto_symbol, target_order_pair[crypto_symbol], grid_position.quantity[0],
            stock_symbol, target_order_pair[stock_symbol], grid_position.quantity[1],
            1
        )

        # 如果 delta 低于 lot_size，说明该网格线已达到目标
        if is_filled:
            self.debug(
                f"⚠️ Grid {level_id} reached target | "
                f"Current: {grid_position.quantity[0]:.4f}/{grid_position.quantity[1]:.4f} | "
                f"Target: {target_order_pair[crypto_symbol]:.4f}/{target_order_pair[stock_symbol]:.4f} | "
                f"Delta: {target_order_pair[crypto_symbol] - grid_position.quantity[0]:.4f}/{target_order_pair[stock_symbol] - grid_position.quantity[1]:.4f}"
            )

        return is_filled

    # ============================================================================
    #                      订单事件处理
    # ============================================================================

    def on_order_event(self, order_event: OrderEvent):
        """
        处理订单事件，更新对应网格线的持仓

        通过订单的 tag 解析 grid_id，然后更新持仓

        Args:
            order_event: OrderEvent 对象
        """
        order_id = order_event.order_id
        event_time = self.algorithm.time  # 获取事件触发时间

        # 使用新方法查找对应的 GridPosition
        grid_position = self.get_grid_position_by_order_event(order_event)

        if not grid_position:
            # 未找到对应的网格持仓，可能是新的网格线或非网格订单
            # 这种情况下无法更新持仓，跳过
            return

        pair_symbol = grid_position.pair_symbol
        crypto_symbol, stock_symbol = pair_symbol
        grid_id = grid_position.level.level_id

        # === 处理成交事件 ===
        if order_event.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
            fill_qty = order_event.fill_quantity

            # 根据 symbol 判断是 leg1 还是 leg2 的订单
            if order_event.symbol == crypto_symbol:
                # 更新 leg1 (crypto) 持仓
                grid_position.update_filled_qty(leg1_qty=fill_qty, leg2_qty=0.0)

                self.debug(
                    f"[{event_time}] 📊 Leg1 filled: {crypto_symbol.value} | Grid: {grid_id} | "
                    f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
                )

            elif order_event.symbol == stock_symbol:
                # 更新 leg2 (stock) 持仓
                grid_position.update_filled_qty(leg1_qty=0.0, leg2_qty=fill_qty)

                self.debug(
                    f"[{event_time}] 📊 Leg2 filled: {stock_symbol.value} | Grid: {grid_id} | "
                    f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
                )

        # === 处理失败/取消事件 ===
        elif order_event.status in [OrderStatus.Canceled, OrderStatus.Invalid]:
            # 使用algorithm.debug确保一定能看到日志
            self.algorithm.debug(
                f"[{event_time}] ❌ Order {order_id} failed: {order_event.status} | "
                f"Grid: {grid_id} | Symbol: {order_event.symbol.value} | "
                f"Message: {order_event.message if order_event.message else 'N/A'}"
            )


    # ============================================================================
    #                      GridPosition 管理
    # ============================================================================

    def get_or_create_grid_position(self, level: GridLevel) -> GridPosition:
        """
        获取或创建 GridPosition

        重要：只接受 Entry GridLevel 作为参数
        - Entry GridLevel 直接作为索引键
        - Exit GridLevel 需要先通过配对关系找到 Entry

        Args:
            level: Entry GridLevel（必须是 ENTRY 类型）

        Returns:
            GridPosition 对象

        Raises:
            AssertionError: 如果传入的不是 Entry GridLevel
        """
        assert level.type == "ENTRY", f"Must use Entry GridLevel as key, got {level.type}"

        # 直接用 GridLevel 作为键查找
        if level in self.grid_positions:
            return self.grid_positions[level]

        # 创建新的 GridPosition
        position = GridPosition(level=level)

        self.grid_positions[level] = position

        self.debug(f"🆕 Created grid position {level.level_id} (hash={hash(level)})")

        return position

    def get_grid_position(self, level: GridLevel) -> Optional[GridPosition]:
        """
        获取指定网格线的持仓

        支持 Entry 和 Exit GridLevel：
        - Entry: 直接查找 self.grid_positions[entry_level]
        - Exit: 先通过配对关系找到 Entry，再查找持仓

        Args:
            level: GridLevel（ENTRY 或 EXIT）

        Returns:
            GridPosition 或 None

        Example:
            >>> # 通过 Entry 查找
            >>> position = manager.get_grid_position(entry_level)

            >>> # 通过 Exit 查找
            >>> position = manager.get_grid_position(exit_level)
        """
        if level.type == "ENTRY":
            # Entry: 直接查找
            return self.grid_positions.get(level)

        elif level.type == "EXIT":
            # Exit: 先找配对的 Entry，再查找持仓
            entry_level = self.grid_level_manager.find_paired_level(level)
            if entry_level:
                return self.grid_positions.get(entry_level)

        return None

    def find_position_by_level(self, level: GridLevel) -> Optional[GridPosition]:
        """
        通过 GridLevel 查找对应的 GridPosition

        DEPRECATED: 使用 get_grid_position() 替代
        保留此方法用于向后兼容

        Args:
            level: GridLevel 对象（ENTRY 或 EXIT）

        Returns:
            GridPosition 或 None
        """
        return self.get_grid_position(level)

    def get_all_grid_positions(self, pair_symbol: Tuple[Symbol, Symbol]) -> Dict[GridLevel, GridPosition]:
        """
        获取交易对的所有网格持仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            {Entry GridLevel: GridPosition} 字典
        """
        return {
            entry_level: position
            for entry_level, position in self.grid_positions.items()
            if entry_level.pair_symbol == pair_symbol
        }

    def get_active_grids(self, pair_symbol: Tuple[Symbol, Symbol]) -> List[str]:
        """
        获取活跃的网格线ID列表（有持仓的网格）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            level_id 列表（返回 level_id 方便日志阅读）
        """
        active_grids = []

        for entry_level, position in self.grid_positions.items():
            if entry_level.pair_symbol == pair_symbol:
                leg1_qty, leg2_qty = position.quantity
                # 如果有任何一边持仓>0.01，认为是活跃的
                if abs(leg1_qty) > 0.01 or abs(leg2_qty) > 0.01:
                    active_grids.append(entry_level.level_id)

        return active_grids

    # ============================================================================
    #                      统计和报告
    # ============================================================================

    def get_summary(self, pair_symbol: Tuple[Symbol, Symbol]) -> str:
        """
        生成网格持仓摘要

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            格式化的摘要字符串
        """
        pair_positions = self.get_all_grid_positions(pair_symbol)

        if not pair_positions:
            return f"No grid positions for {pair_symbol[0].value} <-> {pair_symbol[1].value}"

        summary_lines = [
            f"Grid Positions for {pair_symbol[0].value} <-> {pair_symbol[1].value}:",
            f"  Total Grids: {len(pair_positions)}",
            ""
        ]

        for entry_level, position in pair_positions.items():
            leg1_qty, leg2_qty = position.quantity
            summary_lines.append(
                f"  {entry_level.level_id} (hash={hash(entry_level)}):"
            )
            summary_lines.append(
                f"    Holdings: {leg1_qty:.2f} / {leg2_qty:.2f}"
            )

        return "\n".join(summary_lines)

    # ============================================================================
    #                      对冲敞口检测
    # ============================================================================

    def get_grid_position_by_order_event(self, order_event: OrderEvent) -> Optional[GridPosition]:
        """
        通过订单事件查找对应的 GridPosition

        流程：
        1. 从 order.tag 提取 hash 值
        2. 通过 hash 查找 GridLevel（可能是 Entry 或 Exit）
        3. 如果是 Exit，找到配对的 Entry
        4. 用 Entry GridLevel 查找 GridPosition

        Args:
            order_event: OrderEvent 对象

        Returns:
            GridPosition 对象，如果找不到返回 None
        """
        order_id = order_event.order_id

        # 通过 Transactions 获取 Order 对象
        order = self.algorithm.transactions.get_order_by_id(order_id)

        # Order.tag 现在是 hash(GridLevel) 的字符串形式
        try:
            hash_value = int(order.tag)
        except (ValueError, AttributeError, TypeError):
            self.algorithm.error(
                f"❌ Order {order_id} has invalid tag: {order.tag} (expected hash value)"
            )
            return None

        # 1. 通过 hash 查找 GridLevel
        level = self.grid_level_manager.find_level_by_hash(hash_value)
        if not level:
            self.algorithm.error(
                f"❌ Cannot find GridLevel for hash {hash_value} "
                f"(order {order_id}, symbol {order_event.symbol.value})"
            )
            return None

        # 2. 如果是 Exit，找到配对的 Entry
        if level.type == "EXIT":
            entry_level = self.grid_level_manager.find_paired_level(level)
            if not entry_level:
                self.algorithm.error(
                    f"❌ Cannot find paired Entry for {level.level_id} "
                    f"(hash={hash_value}, order {order_id})"
                )
                return None
            level = entry_level

        # 3. 用 Entry GridLevel 查找 GridPosition
        position = self.grid_positions.get(level)
        if not position:
            self.algorithm.error(
                f"❌ CRITICAL: GridPosition not found for {level.level_id} "
                f"(hash={hash(level)}, order {order_id})"
            )

        return position

    # ============================================================================
    #                      对冲敞口检测
    # ============================================================================

    def _has_orphan_position(self, position: GridPosition) -> bool:
        """
        检查是否有孤立仓位（单边持仓）

        如果crypto和stock持仓不匹配（对冲比例<90%），说明存在敞口

        Args:
            position: GridPosition 对象

        Returns:
            True if has orphan position, False otherwise
        """
        leg1_qty, leg2_qty = position.quantity
        leg1_qty = abs(leg1_qty)
        leg2_qty = abs(leg2_qty)

        # 如果双边都没有仓位，不算孤立
        if leg1_qty < 0.01 and leg2_qty < 0.01:
            return False

        # 如果只有一边有仓位，肯定是孤立
        if leg1_qty < 0.01 or leg2_qty < 0.01:
            return True

        # 计算市值比例（考虑价格）
        leg1_symbol, leg2_symbol = position.pair_symbol
        leg1_price = self.algorithm.securities[leg1_symbol].price
        leg2_price = self.algorithm.securities[leg2_symbol].price

        if leg1_price <= 0 or leg2_price <= 0:
            # 价格无效，无法判断,保守起见认为有敞口
            return True

        leg1_value = leg1_qty * leg1_price
        leg2_value = leg2_qty * leg2_price

        # 对冲比例 = 较小市值 / 较大市值
        hedge_ratio = min(leg1_value, leg2_value) / max(leg1_value, leg2_value)

        # 如果对冲比例 < 90%，认为有敞口
        return hedge_ratio < 0.9

