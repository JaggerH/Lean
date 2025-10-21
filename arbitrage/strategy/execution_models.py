"""
Execution Models - 执行层数据模型

定义执行层的核心数据结构：
- ExecutionStatus: 执行状态枚举
- OrderGroupStatus: 订单组状态枚举
- OrderGroupType: 订单组类型枚举（MarketOrder/LimitOrderOneLeg/LimitOrder）
- OrderGroup: 订单组（GridLevel 触发的订单组）
- ExecutionTarget: 执行目标（Strategy传递给Executor的参数）
"""
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional, List, TYPE_CHECKING
from enum import Enum
from datetime import datetime
from AlgorithmImports import *
from .spread_matcher import SpreadMatcher

if TYPE_CHECKING:
    from .grid_position_manager import GridPositionManager
    from .grid_models import GridLevel


class ExecutionStatus(Enum):
    """
    执行状态枚举 - 对齐 OrderStatus

    状态流转:
    New → Submitted → PartiallyFilled → Filled
                   ↘ Canceled/Invalid/Failed

    状态说明:
    - New: ExecutionTarget 刚创建，未提交订单
    - Submitted: 订单已提交到交易所
    - PartiallyFilled: 部分 OrderGroup 成交，或 OrderGroup 内部分订单成交
    - Filled: 所有 OrderGroup 完全成交
    - Canceled: 订单被取消
    - Invalid: 订单无效
    - Failed: 套利特有 - 对冲失败、无法恢复的错误状态
    """
    New = 1              # 对应 OrderStatus.New
    Submitted = 2        # 对应 OrderStatus.Submitted
    PartiallyFilled = 3  # 对应 OrderStatus.PartiallyFilled
    Filled = 4           # 对应 OrderStatus.Filled
    Canceled = 5         # 对应 OrderStatus.Canceled
    Invalid = 6          # 对应 OrderStatus.Invalid
    Failed = 7           # 套利特有：对冲失败


class OrderGroupStatus(Enum):
    """
    订单组状态枚举 - 与 ExecutionStatus 完全一致

    OrderGroup 是 ExecutionTarget 的组成部分，状态定义保持一致

    状态流转:
    New → Submitted → PartiallyFilled → Filled
                   ↘ Canceled/Invalid/Failed

    状态说明:
    - New: 订单组刚创建，未提交
    - Submitted: 订单组已提交（所有订单已提交）
    - PartiallyFilled: 订单组内部分订单成交
    - Filled: 订单组内所有订单完全成交
    - Canceled: 订单组被取消
    - Invalid: 订单组无效
    - Failed: 对冲失败（部分订单失败导致对冲敞口）
    """
    New = 1              # 对应 OrderStatus.New
    Submitted = 2        # 对应 OrderStatus.Submitted
    PartiallyFilled = 3  # 对应 OrderStatus.PartiallyFilled
    Filled = 4           # 对应 OrderStatus.Filled
    Canceled = 5         # 对应 OrderStatus.Canceled
    Invalid = 6          # 对应 OrderStatus.Invalid
    Failed = 7           # 对冲失败


class OrderGroupType(Enum):
    """
    订单组类型枚举

    支持三种订单执行方式：
    - MarketOrder: 双边市价单（最快执行，无价格保证）
    - LimitOrderOneLeg: 单边限价单（一边限价锁定价差，一边市价对冲）
    - LimitOrder: 双边限价单（价格保证，但可能无法成交）
    """
    MarketOrder = 1       # 双边市价单
    LimitOrderOneLeg = 2  # 单边限价单
    LimitOrder = 3        # 双边限价单


@dataclass
class OrderGroup:
    """
    订单组（GridLevel 触发的订单组）

    代表一次 GridLevel 触发产生的配对订单（通常是2个：crypto + stock）

    核心职责：
    - 关联订单到具体的 grid_id
    - 追踪预期价差 vs 实际价差
    - 提供订单组的填充数量查询

    属于执行层概念，记录订单执行细节
    """
    # 核心字段
    grid_id: str  # 关联的网格线ID
    pair_symbol: Tuple[Symbol, Symbol]  # (crypto_symbol, stock_symbol)
    order_tickets: List[OrderTicket] = field(default_factory=list)  # 订单票据列表
    type: OrderGroupType = OrderGroupType.MarketOrder  # 订单类型（默认市价单）
    expected_ticket_count: int = 0  # 预期的 ticket 数量（双腿=2，追单后+=1）

    # 价差追踪
    expected_spread_pct: float = 0.0  # 预期执行价差（触发时的价差）
    actual_spread_pct: Optional[float] = None  # 实际执行价差（成交后计算）

    # 时间戳
    submit_time: Optional[datetime] = None  # 订单提交时间（必需参数）
    fill_time: Optional[datetime] = None    # 完全成交时间

    # 异步订单跟踪（用于解决竞态条件）

    @property
    def group_id(self) -> str:
        """
        自动生成订单组唯一ID

        格式：{grid_id}_{timestamp}
        """
        timestamp_str = self.submit_time.strftime("%Y%m%d_%H%M%S")
        return f"{self.grid_id}_{timestamp_str}"

    @property
    def order_ids(self) -> List[int]:
        """获取订单ID列表（向后兼容）"""
        return [ticket.order_id for ticket in self.order_tickets]

    @property
    def ticket_count(self) -> int:
        """
        当前已添加的 ticket 数量

        Returns:
            当前 order_tickets 列表的长度
        """
        return len(self.order_tickets) if self.order_tickets else 0

    def is_tickets_complete(self) -> bool:
        """
        检查 tickets 是否已完整

        用于异步订单场景，判断所有预期的 OrderTicket 是否都已添加

        Returns:
            True if ticket_count == expected_ticket_count, False otherwise
        """
        return self.ticket_count == self.expected_ticket_count

    @property
    def quantity_filled(self) -> Tuple[float, float]:
        """
        获取成交数量元组

        根据 pair_symbol 返回 (crypto_qty, stock_qty)

        Returns:
            (crypto_filled_qty, stock_filled_qty)
        """
        crypto_symbol, stock_symbol = self.pair_symbol
        crypto_qty = 0.0
        stock_qty = 0.0

        for ticket in self.order_tickets:
            if ticket.symbol == crypto_symbol:
                crypto_qty += ticket.quantity_filled
            elif ticket.symbol == stock_symbol:
                stock_qty += ticket.quantity_filled

        return (crypto_qty, stock_qty)

    @property
    def status(self) -> OrderGroupStatus:
        """
        订单组状态 - 从 order_tickets 实时计算

        状态逻辑:
        - 无订单 → New
        - 有任何 Canceled/Invalid → Failed
        - 所有订单 Filled → Filled
        - 至少一个订单 Filled/PartiallyFilled，但不全是 → PartiallyFilled
        - 所有订单 Submitted → Submitted
        - 否则 → Submitted (默认)

        Returns:
            OrderGroupStatus 枚举值
        """
        if not self.order_tickets:
            return OrderGroupStatus.New

        # 检查失败订单（优先级最高）
        if any(t.status in [OrderStatus.Canceled, OrderStatus.Invalid] for t in self.order_tickets):
            return OrderGroupStatus.Failed

        # 检查是否全部成交
        if all(t.status == OrderStatus.Filled for t in self.order_tickets):
            return OrderGroupStatus.Filled

        # 检查部分成交
        if any(t.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled] for t in self.order_tickets):
            return OrderGroupStatus.PartiallyFilled

        # 检查是否全部提交
        if all(t.status == OrderStatus.Submitted for t in self.order_tickets):
            return OrderGroupStatus.Submitted

        # 默认状态
        return OrderGroupStatus.Submitted

    def is_filled(self) -> bool:
        """
        判断订单组是否完全成交

        仅支持 MarketOrder 类型，其他类型抛出错误

        Returns:
            True if all order tickets are filled, False otherwise

        Raises:
            NotImplementedError: 如果订单类型不是 MarketOrder
        """
        if self.type != OrderGroupType.MarketOrder:
            raise NotImplementedError(
                f"is_filled() only supports MarketOrder, got {self.type}"
            )

        if not self.order_tickets:
            return False

        return all(t.status == OrderStatus.Filled for t in self.order_tickets)

    def is_submitted(self) -> bool:
        """
        判断订单组是否已提交

        Returns:
            True if all order tickets are submitted, False otherwise
        """
        if not self.order_tickets:
            return False

        return all(t.status == OrderStatus.Submitted for t in self.order_tickets)

    def is_partially_filled(self) -> bool:
        """
        判断订单组是否部分成交

        仅支持 MarketOrder 类型，其他类型抛出错误

        Returns:
            True if at least one order is filled/partially filled but not all, False otherwise

        Raises:
            NotImplementedError: 如果订单类型不是 MarketOrder
        """
        if self.type != OrderGroupType.MarketOrder:
            raise NotImplementedError(
                f"is_partially_filled() only supports MarketOrder, got {self.type}"
            )

        if not self.order_tickets:
            return False

        # 至少有一个订单成交或部分成交，但不是全部成交
        has_filled = any(t.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled] for t in self.order_tickets)
        all_filled = all(t.status == OrderStatus.Filled for t in self.order_tickets)

        return has_filled and not all_filled

    def is_failed(self) -> bool:
        """
        判断订单组是否失败

        Returns:
            True if any order ticket is canceled or invalid, False otherwise
        """
        if not self.order_tickets:
            return False

        return any(t.status in [OrderStatus.Canceled, OrderStatus.Invalid] for t in self.order_tickets)


@dataclass
class ExecutionTarget:
    """
    执行目标 - GridStrategy传递给ExecutionManager的参数（有状态）

    包含目标数量、预期价差、方向等信息

    Attributes:
        pair_symbol: (crypto_symbol, stock_symbol)
        grid_id: 网格线ID（用于日志，人类可读）
        level: GridLevel 对象（用于生成订单 tag = hash(level)）
        target_qty: 目标数量字典 {Symbol: float}（从calculate_order_pair返回）
        expected_spread_pct: 预期价差百分比
        spread_direction: "LONG_SPREAD" or "SHORT_SPREAD"
        algorithm: QCAlgorithm实例（依赖注入）
        status: 执行状态（默认 PENDING）
        created_time: 创建时间
        order_group_id: 关联的订单组ID
        anchor_time: 首次提交时间（用于超时检查）
        timeout_minutes: 超时时间（默认5分钟）
    """
    pair_symbol: Tuple[Symbol, Symbol]
    grid_id: str  # 人类可读标识（用于日志）
    level: 'GridLevel'  # GridLevel 对象（用于订单标记）
    target_qty: Dict[Symbol, float]  # 从calculate_order_pair返回
    expected_spread_pct: float
    spread_direction: str  # "LONG_SPREAD" or "SHORT_SPREAD"
    algorithm: QCAlgorithm  # 依赖注入

    # 状态字段
    status: ExecutionStatus = field(default=ExecutionStatus.New)
    created_time: Optional[datetime] = field(default=None)
    order_groups: List['OrderGroup'] = field(default_factory=list)  # 关联的订单组列表（支持多次提交）

    # 超时控制字段
    anchor_time: Optional[datetime] = field(default=None)  # 首次提交时间
    timeout_minutes: int = 5  # 超时时间（默认5分钟）

    @property
    def quantity_filled(self) -> Tuple[float, float]:
        """
        获取当前已成交数量

        从 order_groups 实时计算，累加所有订单组的成交数量

        Returns:
            (crypto_qty, stock_qty) 元组
        """
        if not self.order_groups:
            return (0.0, 0.0)

        # 累加所有 OrderGroup 的成交数量
        total_crypto = 0.0
        total_stock = 0.0

        for order_group in self.order_groups:
            crypto_qty, stock_qty = order_group.quantity_filled
            total_crypto += crypto_qty
            total_stock += stock_qty

        return (total_crypto, total_stock)

    @property
    def quantity_remaining(self) -> Tuple[float, float]:
        """
        计算剩余需要执行的数量

        Returns:
            (crypto_remaining_qty, stock_remaining_qty) 元组
        """
        crypto_symbol, stock_symbol = self.pair_symbol
        crypto_filled, stock_filled = self.quantity_filled

        crypto_remaining = self.target_qty[crypto_symbol] - crypto_filled
        stock_remaining = self.target_qty[stock_symbol] - stock_filled

        return (crypto_remaining, stock_remaining)


    def is_active(self) -> bool:
        """是否为活跃状态（New/Submitted/PartiallyFilled）"""
        return self.status in [ExecutionStatus.New, ExecutionStatus.Submitted, ExecutionStatus.PartiallyFilled]

    def is_terminal(self) -> bool:
        """是否为终止状态（Filled/Canceled/Invalid/Failed）"""
        return self.status in [ExecutionStatus.Filled, ExecutionStatus.Canceled, ExecutionStatus.Invalid, ExecutionStatus.Failed]

    def is_expired(self, current_time: datetime) -> bool:
        """
        检查 ExecutionTarget 是否超时

        超时策略：从首次提交时间（anchor_time）开始计时，超过 timeout_minutes 视为超时

        Args:
            current_time: 当前时间

        Returns:
            True if expired, False otherwise
        """
        if not self.anchor_time:
            return False

        elapsed_minutes = (current_time - self.anchor_time).total_seconds() / 60
        return elapsed_minutes > self.timeout_minutes

    def is_all_orders_filled(self) -> bool:
        """
        检查所有订单是否都已成交

        Returns:
            True if all order groups are filled, False otherwise
        """
        if not self.order_groups:
            return False
        return all(order_group.is_filled() for order_group in self.order_groups)

    def add_ticket(self, order_event: OrderEvent) -> bool:
        """
        将 OrderTicket 添加到最新的 OrderGroup

        用于异步订单场景，在 on_order_event 中动态绑定 OrderTicket

        Args:
            order_event: OrderEvent 对象

        Returns:
            True if ticket added successfully, False otherwise
        """
        if not self.order_groups:
            self.algorithm.error(
                f"❌ CRITICAL: Cannot add ticket - no order_groups exist | "
                f"Order ID: {order_event.order_id} | Grid: {self.grid_id}"
            )
            return False

        latest_order_group = self.order_groups[-1]

        # 检查是否还需要添加 ticket
        if latest_order_group.is_tickets_complete():
            return False

        # 从 order_event 获取 OrderTicket
        order_ticket = self.algorithm.transactions.get_order_ticket(order_event.order_id)

        # 添加到 order_tickets
        if order_ticket not in latest_order_group.order_tickets:
            latest_order_group.order_tickets.append(order_ticket)

        return True

    def should_fill_remaining_orders(self) -> bool:
        """
        检查是否应该执行剩余订单填充（基于市值判断）

        前提条件：所有订单都已成交（避免订单pending时误判）
        判断逻辑：
        1. 计算两腿的剩余市值
        2. 计算最小对冲单位市值 = max(crypto_lot_mv, stock_lot_mv)
        3. 如果任意一腿的剩余市值 < 最小对冲单位市值，则触发填充

        Returns:
            True if any leg's remaining market value is below min hedge unit
        """
        # 前提：所有订单都已成交
        if not self.is_all_orders_filled():
            return False

        crypto_symbol, stock_symbol = self.pair_symbol
        crypto_remaining, stock_remaining = self.quantity_remaining

        # 获取价格和 lot size
        crypto_price = self.algorithm.securities[crypto_symbol].price
        stock_price = self.algorithm.securities[stock_symbol].price
        crypto_lot = self.algorithm.securities[crypto_symbol].symbol_properties.lot_size
        stock_lot = self.algorithm.securities[stock_symbol].symbol_properties.lot_size

        # 计算剩余市值
        crypto_remaining_mv = abs(crypto_remaining) * crypto_price
        stock_remaining_mv = abs(stock_remaining) * stock_price

        # 计算最小对冲单位市值（取两个 lot size 市值的较大值）
        crypto_lot_mv = crypto_lot * crypto_price
        stock_lot_mv = stock_lot * stock_price
        min_hedge_unit_mv = max(crypto_lot_mv, stock_lot_mv)

        # 任意一腿剩余市值小于最小对冲单位时，触发填充
        return crypto_remaining_mv < min_hedge_unit_mv or stock_remaining_mv < min_hedge_unit_mv
    
    def fill_remaining_orders(self):
        """
        填充剩余订单（单腿追单）

        逻辑：
        1. 检查哪一腿还有剩余
        2. 增加预期 ticket 数量（在提交订单前）
        3. 对剩余腿下市价单
        4. ticket 在 on_order_event 中动态绑定
        """
        crypto_symbol, stock_symbol = self.pair_symbol
        crypto_remaining, stock_remaining = self.quantity_remaining

        # 检查 crypto 腿
        if crypto_remaining != 0.0:
            crypto_lot = self.algorithm.securities[crypto_symbol].symbol_properties.lot_size
            # 使用 SpreadMatcher._round_to_lot 对齐到 lot size，避免 BrokerageTransactionHandler 警告
            crypto_qty = SpreadMatcher._round_to_lot(crypto_remaining, crypto_lot)
            if abs(crypto_qty) >= crypto_lot:
                # 提交订单前，增加预期 ticket 数量
                if self.order_groups:
                    self.order_groups[-1].expected_ticket_count += 1

                # 使用 level hash 作为 tag（唯一标识）
                self.algorithm.market_order(
                    crypto_symbol,
                    crypto_qty,
                    asynchronous=True,
                    tag=str(hash(self.level))
                )
                self.algorithm.debug(
                    f"🎯 One-leg sweep | {crypto_symbol.value}: {crypto_qty:.4f} | "
                    f"Reason: {stock_symbol.value} filled"
                )

        # 检查 stock 腿
        if stock_remaining != 0.0:
            stock_lot = self.algorithm.securities[stock_symbol].symbol_properties.lot_size
            # 使用 SpreadMatcher._round_to_lot 对齐到 lot size，避免 BrokerageTransactionHandler 警告
            stock_qty = SpreadMatcher._round_to_lot(stock_remaining, stock_lot)
            if abs(stock_qty) >= stock_lot:
                # 提交订单前，增加预期 ticket 数量
                if self.order_groups:
                    self.order_groups[-1].expected_ticket_count += 1

                # 使用 level hash 作为 tag（唯一标识）
                self.algorithm.market_order(
                    stock_symbol,
                    stock_qty,
                    asynchronous=True,
                    tag=str(hash(self.level))
                )
                self.algorithm.debug(
                    f"🎯 One-leg sweep | {stock_symbol.value}: {stock_qty:.4f} | "
                    f"Reason: {crypto_symbol.value} filled"
                )
            
    def is_quantity_filled(self) -> bool:
        """
        检查是否完全填充（严格判定）

        直接检查 quantity_remaining 元组的两个值是否都为 0

        Returns:
            True if both crypto_remaining and stock_remaining are exactly 0
        """
        crypto_remaining, stock_remaining = self.quantity_remaining
        return crypto_remaining == 0.0 and stock_remaining == 0.0

    def calculate_executable_quantity(
        self,
        debug: bool = False
    ) -> Optional[Tuple[Tuple[Symbol, float], Tuple[Symbol, float]]]:
        """
        计算本次可执行数量（基于 orderbook 深度和价差）

        这是 ExecutionTarget 的核心方法：
        - 获取剩余需执行数量
        - 检查最小交易单位
        - 调用 SpreadMatcher 计算实际可执行数量

        Args:
            debug: 是否调试模式

        Returns:
            ((crypto_symbol, crypto_qty), (stock_symbol, stock_qty)) 或 None（无法执行时）
        """

        crypto_symbol, stock_symbol = self.pair_symbol
        crypto_remaining, stock_remaining = self.quantity_remaining

        # 检查最小交易单位
        if self.is_quantity_filled():
            return None  # 已填满

        # 使用 SpreadMatcher 计算可执行数量
        crypto_price = self.algorithm.securities[crypto_symbol].price
        target_usd = abs(crypto_remaining) * crypto_price

        match_result = SpreadMatcher.match_pair(
            algorithm=self.algorithm,
            symbol1=crypto_symbol,
            symbol2=stock_symbol,
            target_usd=target_usd,
            direction=self.spread_direction,  # 直接使用 LONG_SPREAD/SHORT_SPREAD
            expected_spread_pct=self.expected_spread_pct,  # 转换为百分比
            debug=False
        )

        if not match_result or not match_result.executable:
            return None

        return tuple(match_result.legs)

    def is_completely_filled(self) -> bool:
        """
        检查是否完全成交

        基于剩余数量是否低于最小交易单位来判断
        如果数量已填满但订单组未全部成交，记录错误日志

        Returns:
            True if remaining quantity is below min lot size, False otherwise
        """
        if not self.order_groups:
            return False

        # 检查是否低于最小交易单位（视为已填满）
        quantity_filled = self.is_quantity_filled()
        all_groups_filled = all(order_group.is_filled() for order_group in self.order_groups)

        # 如果数量已填满但订单组未全部成交，记录错误
        if quantity_filled and not all_groups_filled:
            crypto_symbol, stock_symbol = self.pair_symbol
            crypto_target = self.target_qty[crypto_symbol]
            stock_target = self.target_qty[stock_symbol]
            crypto_remaining, stock_remaining = self.quantity_remaining

            # 收集未成交的订单信息
            unfilled_orders = []
            for order_group in self.order_groups:
                if not order_group.is_filled():
                    for ticket in order_group.order_tickets:
                        if ticket.status != OrderStatus.Filled:
                            unfilled_orders.append(
                                f"  Order {ticket.order_id}: {ticket.symbol.value} | "
                                f"Status: {ticket.status} | Qty: {ticket.quantity} | "
                                f"Filled: {ticket.quantity_filled}"
                            )

            self.algorithm.error(
                f"\n{'='*50}\n"
                f"⚠️ WARNING: Quantity filled but order groups not all filled\n"
                f"Grid: {self.grid_id}\n"
                f"Target Qty: {crypto_symbol.value}={crypto_target:.4f}, {stock_symbol.value}={stock_target:.4f}\n"
                f"Remaining Qty: {crypto_symbol.value}={crypto_remaining:.4f}, {stock_symbol.value}={stock_remaining:.4f}\n"
                f"Order Groups: {len(self.order_groups)} total, {sum(1 for og in self.order_groups if og.is_filled())} filled\n"
                f"Unfilled Orders:\n" + "\n".join(unfilled_orders) +
                f"\n{'='*50}"
            )

        return quantity_filled

    def is_completely_failed(self) -> bool:
        """
        检查是否完全失败

        遍历所有 order_groups，检查是否都已失败

        Returns:
            True if all order groups failed, False otherwise
        """
        if not self.order_groups:
            return True

        return all(order_group.is_failed() for order_group in self.order_groups)
