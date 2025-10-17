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
from datetime import datetime
from .grid_models import GridLevel, GridPosition, OrderGroup, generate_grid_id, generate_order_group_id


class GridPositionManager:
    """
    网格持仓追踪管理器

    职责:
    - 管理每个交易对的多个网格线持仓
    - 追踪订单组到网格线的映射
    - 根据订单事件更新网格线持仓
    - 提供持仓状态查询接口（持仓数量、是否达到目标等）
    """

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False, order_timeout_seconds: int = 5):
        """
        初始化 GridPositionManager

        Args:
            algorithm: QCAlgorithm 实例
            debug: 是否启用调试日志
            order_timeout_seconds: Market Order 超时时间（秒），默认 5 秒
        """
        self.algorithm = algorithm
        self.debug_enabled = debug
        self.order_timeout_seconds = order_timeout_seconds

        # ExecutionManager reference (will be set by GridStrategy)
        self.execution_manager = None

        # 网格线持仓追踪
        # {pair_symbol: {grid_id: GridPosition}}
        self.grid_positions: Dict[Tuple[Symbol, Symbol], Dict[str, GridPosition]] = {}

        # 订单组到网格线的映射
        # {order_group_id: (pair_symbol, grid_id)}
        self.order_group_to_grid: Dict[str, Tuple[Tuple[Symbol, Symbol], str]] = {}

        # 订单ID到订单组的映射（用于快速查找）
        # {order_id: order_group_id}
        self.order_to_group: Dict[int, str] = {}

        # 订单提交时间追踪（用于超时检测）
        # {order_id: submit_time}
        self.order_submit_times: Dict[int, datetime] = {}

    def debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(message)

    # ============================================================================
    #                      持仓状态查询
    # ============================================================================

    def has_reached_target(self, pair_symbol: Tuple[Symbol, Symbol], level: GridLevel) -> bool:
        """
        检查持仓是否达到目标市值

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            level: 网格线配置

        Returns:
            True if position reached target, False otherwise
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 获取当前持仓市值（双账户中较大的）
        current_value = self._get_max_holdings_value(pair_symbol)

        # 计算目标市值（使用 CalculateOrderQuantity 模拟）
        qty1 = self.algorithm.calculate_order_quantity(crypto_symbol, level.position_size_pct)
        price1 = self.algorithm.securities[crypto_symbol].price
        target_value1 = abs(qty1 * price1) if price1 > 0 else 0

        qty2 = self.algorithm.calculate_order_quantity(stock_symbol, -level.position_size_pct)
        price2 = self.algorithm.securities[stock_symbol].price
        target_value2 = abs(qty2 * price2) if price2 > 0 else 0

        # 双账户的最大目标市值
        max_target_value = max(target_value1, target_value2)

        # 如果当前持仓已达到 99% 目标，返回 True
        if max_target_value > 0 and current_value >= max_target_value * 0.99:
            self.debug(
                f"⚠️ Position reached target | "
                f"Current: ${current_value:.2f} / Target: ${max_target_value:.2f}"
            )
            return True

        return False

    def _get_max_holdings_value(self, pair_symbol: Tuple[Symbol, Symbol]) -> float:
        """
        获取双账户中较大的持仓市值

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            较大账户的持仓市值（绝对值）
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 获取持仓市值
        crypto_holdings = self.algorithm.portfolio[crypto_symbol]
        crypto_value = abs(crypto_holdings.holdings_value)

        stock_holdings = self.algorithm.portfolio[stock_symbol]
        stock_value = abs(stock_holdings.holdings_value)

        return max(crypto_value, stock_value)

    # ============================================================================
    #                      订单组注册和追踪
    # ============================================================================

    def register_order_group(self, pair_symbol: Tuple[Symbol, Symbol],
                            grid_id: str, order_tickets: List,
                            expected_spread_pct: float):
        """
        注册订单组到网格线

        在创建订单后调用此方法，建立订单到网格线的映射

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
            order_tickets: OrderTicket 列表
            expected_spread_pct: 预期价差百分比
        """
        if not order_tickets:
            return

        # 生成订单组ID
        group_id = generate_order_group_id(grid_id, self.algorithm.time)

        # 提取订单ID
        order_ids = [ticket.order_id for ticket in order_tickets]

        # 创建 OrderGroup
        order_group = OrderGroup(
            group_id=group_id,
            order_ids=order_ids,
            expected_spread_pct=expected_spread_pct,
            submit_time=self.algorithm.time,
            status="SUBMITTED"
        )

        # 添加到 GridPosition
        grid_position = self.get_grid_position(pair_symbol, grid_id)
        if grid_position:
            grid_position.add_order_group(order_group)

        # 建立映射关系
        self.order_group_to_grid[group_id] = (pair_symbol, grid_id)

        for order_id in order_ids:
            self.order_to_group[order_id] = group_id
            # 记录订单提交时间（用于超时检测）
            self.order_submit_times[order_id] = self.algorithm.time

        self.debug(
            f"📝 Registered order group {group_id} | Grid: {grid_id} | "
            f"Orders: {order_ids} | Expected Spread: {expected_spread_pct*100:.2f}%"
        )

    def on_order_event(self, order_event: OrderEvent):
        """
        处理订单事件，更新对应网格线的持仓

        通过 order_id 查找对应的订单组和网格线，然后更新持仓

        Args:
            order_event: OrderEvent 对象
        """
        order_id = order_event.order_id
        event_time = self.algorithm.time  # 获取事件触发时间

        # 查找订单所属的订单组
        group_id = self.order_to_group.get(order_id)
        if not group_id:
            # 不是此管理器追踪的订单，忽略
            return

        # 查找网格线
        grid_info = self.order_group_to_grid.get(group_id)
        if not grid_info:
            self.debug(f"⚠️ Order group {group_id} not found in mapping")
            return

        pair_symbol, grid_id = grid_info
        crypto_symbol, stock_symbol = pair_symbol

        # 获取 GridPosition 和 OrderGroup
        grid_position = self.get_grid_position(pair_symbol, grid_id)
        if not grid_position:
            self.debug(f"⚠️ Grid position {grid_id} not found")
            return

        order_group = self._get_order_group(grid_position, group_id)
        if not order_group:
            self.debug(f"⚠️ Order group {group_id} not found in grid {grid_id}")
            return

        # === 处理成交事件 ===
        if order_event.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
            fill_qty = order_event.fill_quantity

            # 根据 symbol 判断是 crypto 还是 stock 的订单
            if order_event.symbol == crypto_symbol:
                # 更新 crypto 持仓
                grid_position.update_filled_qty(crypto_qty=fill_qty, stock_qty=0.0)
                order_group.crypto_filled_qty += fill_qty

                self.debug(
                    f"[{event_time}] 📊 Crypto filled: {crypto_symbol.value} | Grid: {grid_id} | "
                    f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
                )

            elif order_event.symbol == stock_symbol:
                # 更新 stock 持仓
                grid_position.update_filled_qty(crypto_qty=0.0, stock_qty=fill_qty)
                order_group.stock_filled_qty += fill_qty

                self.debug(
                    f"[{event_time}] 📊 Stock filled: {stock_symbol.value} | Grid: {grid_id} | "
                    f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
                )

            # 更新订单组状态
            if order_event.status == OrderStatus.PartiallyFilled:
                order_group.status = "PARTIALLY_FILLED"
            elif order_event.status == OrderStatus.Filled:
                # 检查订单组是否完全成交（所有订单都 Filled）
                all_filled = self._check_order_group_filled(order_group)
                if all_filled:
                    order_group.status = "FILLED"
                    order_group.fill_time = self.algorithm.time

                    # 计算实际执行价差
                    actual_spread = self._calculate_actual_spread(
                        order_group, crypto_symbol, stock_symbol
                    )
                    order_group.actual_spread_pct = actual_spread

                    self.debug(
                        f"[{event_time}] ✅ Order group {group_id} fully filled | "
                        f"Expected Spread: {order_group.expected_spread_pct*100:.2f}% | "
                        f"Actual Spread: {actual_spread*100:.2f}% if actual_spread else 'N/A'"
                    )

                    # 通知ExecutionManager执行完成
                    if self.execution_manager:
                        self.execution_manager.on_execution_completed(pair_symbol, grid_id)

        # === 处理失败/取消事件 ===
        elif order_event.status in [OrderStatus.Canceled, OrderStatus.Invalid]:
            # 使用algorithm.debug确保一定能看到日志
            self.algorithm.debug(
                f"[{event_time}] ❌ Order {order_id} failed: {order_event.status} | "
                f"Grid: {grid_id} | Symbol: {order_event.symbol.value} | "
                f"Message: {order_event.message if order_event.message else 'N/A'}"
            )

            # 检查订单组中所有订单的状态
            all_failed = self._check_all_orders_failed(order_group)

            if all_failed:
                # 所有订单都失败了，标记整个订单组为FAILED
                order_group.status = "FAILED"
                grid_position._update_status()  # 更新GridPosition状态
                self.algorithm.debug(f"[{event_time}] 🚫 Order group {group_id} completely failed")

                # 通知ExecutionManager执行失败
                if self.execution_manager:
                    self.execution_manager.on_execution_failed(pair_symbol, grid_id)
            else:
                # 部分订单失败 → 对冲敞口！
                order_group.status = "PARTIALLY_FAILED"
                grid_position._update_status()  # 更新GridPosition状态
                self._handle_hedging_exposure(pair_symbol, grid_id, order_group)

                # 部分失败也通知ExecutionManager
                if self.execution_manager:
                    self.execution_manager.on_execution_failed(pair_symbol, grid_id)

        # 清理已完成的订单
        if order_event.status in [OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid]:
            if order_id in self.order_to_group:
                # 只有当订单组的所有订单都完成时，才清理映射
                # 这里简化实现：不清理（保留历史记录）
                pass

    def _check_order_group_filled(self, order_group: OrderGroup) -> bool:
        """
        检查订单组是否完全成交

        Args:
            order_group: OrderGroup 对象

        Returns:
            True if all orders are filled, False otherwise
        """
        for order_id in order_group.order_ids:
            ticket = self.algorithm.transactions.get_order_ticket(order_id)
            if not ticket or ticket.status != OrderStatus.Filled:
                return False
        return True

    def _calculate_actual_spread(self, order_group: OrderGroup,
                                crypto_symbol: Symbol, stock_symbol: Symbol) -> Optional[float]:
        """
        计算订单组的实际执行价差

        使用成交价格计算实际价差

        Args:
            order_group: OrderGroup 对象
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol

        Returns:
            实际价差百分比，如果无法计算返回 None
        """
        crypto_price = None
        stock_price = None

        for order_id in order_group.order_ids:
            ticket = self.algorithm.transactions.get_order_ticket(order_id)
            if not ticket:
                continue

            if ticket.symbol == crypto_symbol:
                crypto_price = float(ticket.average_fill_price)
            elif ticket.symbol == stock_symbol:
                stock_price = float(ticket.average_fill_price)

        if crypto_price and stock_price:
            # 简化计算：(crypto - stock) / crypto
            return (crypto_price - stock_price) / crypto_price

        return None

    def _get_order_group(self, position: GridPosition, group_id: str) -> Optional[OrderGroup]:
        """
        从 GridPosition 中查找订单组

        Args:
            position: GridPosition 对象
            group_id: 订单组ID

        Returns:
            OrderGroup 或 None
        """
        return next((g for g in position.order_groups if g.group_id == group_id), None)

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
            level=level,
            status="OPEN"
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
        获取活跃的网格线ID列表（状态为 FILLED）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            grid_id 列表
        """
        pair_positions = self.grid_positions.get(pair_symbol, {})
        return [
            grid_id for grid_id, position in pair_positions.items()
            if position.status == "FILLED"
        ]

    def close_grid_position(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str):
        """
        标记网格线为已平仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
        """
        position = self.get_grid_position(pair_symbol, grid_id)
        if position:
            position.status = "CLOSED"
            position.close_time = self.algorithm.time

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
            summary_lines.append(
                f"  {grid_id}:"
            )
            summary_lines.append(
                f"    Status: {position.status}"
            )
            summary_lines.append(
                f"    Actual Holdings: {position.actual_crypto_qty:.2f} / {position.actual_stock_qty:.2f}"
            )
            summary_lines.append(
                f"    Order Groups: {len(position.order_groups)}"
            )

        return "\n".join(summary_lines)

    # ============================================================================
    #                      对冲敞口检测和处理
    # ============================================================================

    def _check_all_orders_failed(self, order_group: OrderGroup) -> bool:
        """
        检查订单组中所有订单是否都失败了

        Args:
            order_group: OrderGroup 对象

        Returns:
            True if all orders failed, False otherwise
        """
        for order_id in order_group.order_ids:
            ticket = self.algorithm.transactions.get_order_ticket(order_id)
            if not ticket:
                continue

            # 如果有任何订单成功或pending，返回False
            if ticket.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled,
                                OrderStatus.Submitted, OrderStatus.New]:
                return False

        return True

    def _handle_hedging_exposure(self, pair_symbol: Tuple[Symbol, Symbol],
                                 grid_id: str, order_group: OrderGroup):
        """
        处理对冲敞口（部分订单失败的情况）

        记录敞口信息，为未来的自动补单/平仓功能预留接口

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
            order_group: OrderGroup 对象
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 计算敞口
        crypto_filled = order_group.crypto_filled_qty
        stock_filled = order_group.stock_filled_qty

        crypto_price = self.algorithm.securities[crypto_symbol].price
        stock_price = self.algorithm.securities[stock_symbol].price

        crypto_value = abs(crypto_filled * crypto_price) if crypto_price > 0 else 0
        stock_value = abs(stock_filled * stock_price) if stock_price > 0 else 0

        exposure = abs(crypto_value - stock_value)

        self.algorithm.debug(
            f"⚠️ HEDGING EXPOSURE DETECTED | Grid: {grid_id}\n"
            f"  Crypto filled: {crypto_filled:.4f} (${crypto_value:.2f})\n"
            f"  Stock filled: {stock_filled:.4f} (${stock_value:.2f})\n"
            f"  Exposure: ${exposure:.2f}"
        )

        # TODO: 实现自动补单或降级平仓机制
        # 当前仅记录日志，后续可以在这里触发容错逻辑

    def _has_orphan_position(self, position: GridPosition) -> bool:
        """
        检查是否有孤立仓位（单边持仓）

        如果crypto和stock持仓不匹配（对冲比例<90%），说明存在敞口

        Args:
            position: GridPosition 对象

        Returns:
            True if has orphan position, False otherwise
        """
        crypto_qty = abs(position.actual_crypto_qty)
        stock_qty = abs(position.actual_stock_qty)

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

    # ============================================================================
    #                      订单超时检测
    # ============================================================================

    def check_order_timeouts(self):
        """
        检查所有订单是否超时，如果超时则主动取消

        Market Order 在 SUBMITTED 状态超过 order_timeout_seconds 秒视为超时
        取消订单后，会触发 OrderStatus.Canceled 事件，进而触发对冲敞口检测

        应在 OnData 或其他定期调用的地方调用此方法
        """
        current_time = self.algorithm.time
        timeout_orders = []

        # 调试：输出追踪的订单数量（每100次调用输出一次）
        if not hasattr(self, '_timeout_check_count'):
            self._timeout_check_count = 0
        self._timeout_check_count += 1

        if self._timeout_check_count % 100 == 0 and len(self.order_submit_times) > 0:
            self.algorithm.debug(
                f"⏰ Timeout check #{self._timeout_check_count} | "
                f"Tracking {len(self.order_submit_times)} order(s): {list(self.order_submit_times.keys())}"
            )

        # 遍历所有追踪的订单
        for order_id, submit_time in list(self.order_submit_times.items()):
            # 检查订单是否还在 SUBMITTED 状态
            ticket = self.algorithm.transactions.get_order_ticket(order_id)
            if not ticket:
                # 订单不存在，清理记录
                del self.order_submit_times[order_id]
                continue

            # 只检查 SUBMITTED 状态的订单
            if ticket.status != OrderStatus.Submitted:
                # 订单已经不是 SUBMITTED 状态，清理记录
                del self.order_submit_times[order_id]
                continue

            # 计算订单已提交时长
            elapsed = (current_time - submit_time).total_seconds()

            # 如果超时，标记为需要取消
            if elapsed > self.order_timeout_seconds:
                timeout_orders.append((order_id, elapsed, ticket))

        # 批量取消超时订单
        if timeout_orders:
            self.algorithm.debug(
                f"⏰ Detected {len(timeout_orders)} timeout order(s) (>{self.order_timeout_seconds}s)"
            )

            for order_id, elapsed, ticket in timeout_orders:
                # 取消订单
                cancel_response = ticket.cancel(f"Order timeout after {elapsed:.1f}s")

                self.algorithm.debug(
                    f"⏰ Canceling timeout order {order_id} | "
                    f"Symbol: {ticket.symbol.value} | "
                    f"Elapsed: {elapsed:.1f}s | "
                    f"Response: {cancel_response}"
                )

                # 清理提交时间记录
                if order_id in self.order_submit_times:
                    del self.order_submit_times[order_id]
