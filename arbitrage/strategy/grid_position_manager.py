"""
Grid Position Manager - 网格持仓追踪管理器

功能:
1. 管理多个网格线的持仓状态
2. 关联订单组到具体网格线
3. 提供查询接口：判断是否需要开/平仓
4. 处理订单事件，更新对应网格线的持仓
"""
from AlgorithmImports import QCAlgorithm, Symbol, OrderEvent, OrderStatus
from typing import Dict, List, Tuple, Optional
from .grid_models import GridLevel, GridPosition, generate_grid_id


class GridPositionManager:
    """
    网格持仓追踪管理器

    职责:
    - 管理每个交易对的多个网格线持仓
    - 追踪订单组到网格线的映射
    - 根据订单事件更新网格线持仓
    - 提供持仓状态查询接口（持仓数量、是否达到目标等）
    """

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False):
        """
        初始化 GridPositionManager

        Args:
            algorithm: QCAlgorithm 实例
            debug: 是否启用调试日志
        """
        self.algorithm = algorithm
        self.debug_enabled = debug

        # 网格线持仓追踪
        # {pair_symbol: {grid_id: GridPosition}}
        self.grid_positions: Dict[Tuple[Symbol, Symbol], Dict[str, GridPosition]] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

    # ============================================================================
    #                      持仓状态查询
    # ============================================================================

    def has_reached_target(self, pair_symbol: Tuple[Symbol, Symbol], level: GridLevel) -> bool:
        """
        检查指定网格线的持仓是否达到目标

        使用 CalculateOrderPair + IsPairQuantitySufficient 判断：
        - 计算目标持仓（复用 CalculateOrderPair）
        - 从 GridPosition 获取当前持仓（单网格级别）
        - 计算 delta = 目标 - 当前
        - 检查 delta 是否低于 lot_size（低于则认为已达到目标）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            level: 网格线配置

        Returns:
            True if position reached target, False otherwise
        """
        crypto_symbol, stock_symbol = pair_symbol
        grid_id = generate_grid_id(pair_symbol, level.level_id)

        # 1. 计算目标持仓（使用 CalculateOrderPair）
        position_size_pct = level.position_size_pct
        if level.direction == "SHORT_CRYPTO":
            position_size_pct = -position_size_pct

        target_order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct
        )

        if not target_order_pair:
            # 无法计算目标（可能是买入力不足），认为已达到目标
            self.debug(f"⚠️ Grid {grid_id} cannot calculate target, treating as reached")
            return True

        # 2. 获取该网格线的当前持仓（从 GridPosition）
        grid_position = self.get_grid_position(pair_symbol, grid_id)

        if not grid_position:
            # 网格线不存在，说明还没有持仓，可以开仓
            return False


        # 4. 检查 delta 是否低于 lot_size（使用 IsPairQuantityFilled）
        is_below_lotsize = self.algorithm.is_pair_quantity_filled(
            crypto_symbol, target_order_pair[crypto_symbol], grid_position.quantity[0],
            stock_symbol, target_order_pair[stock_symbol], grid_position.quantity[1],
            1
        )

        # 如果 delta 低于 lot_size，说明该网格线已达到目标
        if is_below_lotsize:
            self.debug(
                f"⚠️ Grid {grid_id} reached target | "
                f"Current: {grid_position.quantity[0]:.4f}/{grid_position.quantity[1]:.4f} | "
                f"Target: {target_order_pair[crypto_symbol]:.4f}/{target_order_pair[stock_symbol]:.4f} | "
                f"Delta: {target_order_pair[crypto_symbol] - grid_position.quantity[0]:.4f}/{target_order_pair[stock_symbol] - grid_position.quantity[1]:.4f}"
            )

        return is_below_lotsize

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

        # 从订单 ticket 获取 tag 来解析 grid_id
        ticket = self.algorithm.transactions.get_order_ticket(order_id)
        if not ticket or not ticket.tag:
            # 不是网格订单，忽略
            return

        # Tag 就是 grid_id（唯一标识）
        if not ticket.tag:
            # 没有 tag，忽略
            return

        grid_id = ticket.tag

        # 查找包含此订单symbol的所有pair_symbol
        # 遍历所有已知的 grid_positions 查找匹配的 grid_id
        grid_position = None
        pair_symbol = None

        for ps, positions in self.grid_positions.items():
            if grid_id in positions:
                # 检查订单symbol是否属于这个pair
                if order_event.symbol in ps:
                    pair_symbol = ps
                    grid_position = positions[grid_id]
                    break

        if not grid_position or not pair_symbol:
            # 未找到对应的网格持仓，可能是新的网格线
            # 这种情况下无法更新持仓，跳过
            return

        crypto_symbol, stock_symbol = pair_symbol

        # === 处理成交事件 ===
        if order_event.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
            fill_qty = order_event.fill_quantity

            # 根据 symbol 判断是 crypto 还是 stock 的订单
            if order_event.symbol == crypto_symbol:
                # 更新 crypto 持仓
                grid_position.update_filled_qty(crypto_qty=fill_qty, stock_qty=0.0)

                self.debug(
                    f"[{event_time}] 📊 Crypto filled: {crypto_symbol.value} | Grid: {grid_id} | "
                    f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
                )

            elif order_event.symbol == stock_symbol:
                # 更新 stock 持仓
                grid_position.update_filled_qty(crypto_qty=0.0, stock_qty=fill_qty)

                self.debug(
                    f"[{event_time}] 📊 Stock filled: {stock_symbol.value} | Grid: {grid_id} | "
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

    def get_or_create_grid_position(self, pair_symbol: Tuple[Symbol, Symbol],
                                    grid_id: str, level: GridLevel) -> GridPosition:
        """
        获取或创建 GridPosition

        如果网格线不存在，创建新的 GridPosition

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
            level: 网格线配置

        Returns:
            GridPosition 对象
        """
        if pair_symbol not in self.grid_positions:
            self.grid_positions[pair_symbol] = {}

        if grid_id in self.grid_positions[pair_symbol]:
            return self.grid_positions[pair_symbol][grid_id]

        # 创建新的 GridPosition
        position = GridPosition(
            grid_id=grid_id,
            pair_symbol=pair_symbol,
            level=level
        )

        self.grid_positions[pair_symbol][grid_id] = position

        self.debug(f"🆕 Created grid position {grid_id}")

        return position

    def get_grid_position(self, pair_symbol: Tuple[Symbol, Symbol],
                         grid_id: str) -> Optional[GridPosition]:
        """
        获取指定网格线的持仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID

        Returns:
            GridPosition 或 None
        """
        pair_positions = self.grid_positions.get(pair_symbol, {})
        return pair_positions.get(grid_id)

    def get_all_grid_positions(self, pair_symbol: Tuple[Symbol, Symbol]) -> Dict[str, GridPosition]:
        """
        获取交易对的所有网格持仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            {grid_id: GridPosition} 字典
        """
        return self.grid_positions.get(pair_symbol, {})

    def get_active_grids(self, pair_symbol: Tuple[Symbol, Symbol]) -> List[str]:
        """
        获取活跃的网格线ID列表（有持仓的网格）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            grid_id 列表
        """
        pair_positions = self.grid_positions.get(pair_symbol, {})
        active_grids = []

        for grid_id, position in pair_positions.items():
            crypto_qty, stock_qty = position.quantity
            # 如果有任何一边持仓>0.01，认为是活跃的
            if abs(crypto_qty) > 0.01 or abs(stock_qty) > 0.01:
                active_grids.append(grid_id)

        return active_grids

    def close_grid_position(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str):
        """
        清除网格线持仓（将持仓归零）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
        """
        position = self.get_grid_position(pair_symbol, grid_id)
        if position:
            # 将持仓归零（通过更新负数量）
            crypto_qty, stock_qty = position.quantity
            position.update_filled_qty(-crypto_qty, -stock_qty)

            self.debug(f"✅ Closed grid position {grid_id}")

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
        pair_positions = self.grid_positions.get(pair_symbol, {})

        if not pair_positions:
            return f"No grid positions for {pair_symbol[0].value} <-> {pair_symbol[1].value}"

        summary_lines = [
            f"Grid Positions for {pair_symbol[0].value} <-> {pair_symbol[1].value}:",
            f"  Total Grids: {len(pair_positions)}",
            ""
        ]

        for grid_id, position in pair_positions.items():
            crypto_qty, stock_qty = position.quantity
            summary_lines.append(
                f"  {grid_id}:"
            )
            summary_lines.append(
                f"    Holdings: {crypto_qty:.2f} / {stock_qty:.2f}"
            )

        return "\n".join(summary_lines)

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
        crypto_qty, stock_qty = position.quantity
        crypto_qty = abs(crypto_qty)
        stock_qty = abs(stock_qty)

        # 如果双边都没有仓位，不算孤立
        if crypto_qty < 0.01 and stock_qty < 0.01:
            return False

        # 如果只有一边有仓位，肯定是孤立
        if crypto_qty < 0.01 or stock_qty < 0.01:
            return True

        # 计算市值比例（考虑价格）
        crypto_symbol, stock_symbol = position.pair_symbol
        crypto_price = self.algorithm.securities[crypto_symbol].price
        stock_price = self.algorithm.securities[stock_symbol].price

        if crypto_price <= 0 or stock_price <= 0:
            # 价格无效，无法判断，保守起见认为有敞口
            return True

        crypto_value = crypto_qty * crypto_price
        stock_value = stock_qty * stock_price

        # 对冲比例 = 较小市值 / 较大市值
        hedge_ratio = min(crypto_value, stock_value) / max(crypto_value, stock_value)

        # 如果对冲比例 < 90%，认为有敞口
        return hedge_ratio < 0.9

