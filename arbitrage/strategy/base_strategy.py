"""
Base Strategy - 套利策略基类

提供基础的开仓/平仓逻辑，供具体策略继承和扩展
"""
from AlgorithmImports import *
from typing import Tuple, Optional, List, Dict


class BaseStrategy:
    """
    套利策略基类

    功能:
    - 提供基础的开仓/平仓方法
    - 使用 Lean 原生接口防止重复订单（Portfolio.Invested + GetOpenOrders）
    - 只检查 crypto 侧状态，避免多交易所对冲冲突
    - 可选的debug输出控制
    - 管理交易对的仓位和订单追踪

    子类需要实现:
    - on_spread_update(): 处理价差更新的具体逻辑
    """

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False):
        """
        初始化基础策略

        Args:
            algorithm: QCAlgorithm实例
            debug: 是否输出debug日志 (默认False)
        """
        self.algorithm = algorithm
        self.debug = debug

        # Position tracking: {(crypto_symbol, stock_symbol): (token_qty, stock_qty)}
        # 维护每个交易对的仓位，解决多对一映射问题
        # Example: {(TSLAxUSD, TSLA): (300, -290)}
        self.positions: Dict[Tuple[Symbol, Symbol], Tuple[float, float]] = {}

        # Order to pair mapping: {order_id: (crypto_symbol, stock_symbol)}
        # 用于在 on_order_event 时精确查找订单所属的交易对
        self.order_to_pair: Dict[int, Tuple[Symbol, Symbol]] = {}

    def _debug(self, message: str):
        """
        条件debug输出

        Args:
            message: Debug消息
        """
        if self.debug:
            self.algorithm.debug(message)

    def _should_open_position(self, crypto_symbol: Symbol, stock_symbol: Symbol) -> bool:
        """
        判断是否应该开仓

        检查逻辑（只检查 crypto 侧）：
        1. 检查 crypto 是否有持仓（Invested 基于 LotSize，自动忽略残留持仓）
        2. 检查 crypto 是否有未完成订单

        为什么只检查 crypto 侧：
        - 组合订单是原子性的，检查一个leg即可
        - 多个 crypto 交易所可能共享同一个 stock 对冲账户
        - 检查 crypto 侧确保每个 pair 独立管理

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol (保留参数，便于未来扩展)

        Returns:
            True if should open position, False otherwise
        """
        # 1. 检查 crypto 是否有持仓
        # Invested = abs(Quantity) >= LotSize
        # Lean 已经处理了残留持仓问题（如 0.02 < 0.01 LotSize）
        if self.algorithm.portfolio[crypto_symbol].invested:
            self._debug(
                f"⚠️ Cannot open - crypto already invested | "
                f"{crypto_symbol.value}: {self.algorithm.portfolio[crypto_symbol].quantity:.4f}"
            )
            return False

        # 2. 检查 crypto 是否有未完成订单
        open_orders = self.algorithm.transactions.get_open_orders(crypto_symbol)
        if len(open_orders) > 0:
            self._debug(
                f"⚠️ Cannot open - crypto has {len(open_orders)} open order(s) | "
                f"{crypto_symbol.value}"
            )
            return False

        # 3. 都通过 → 可以开仓
        return True

    def _should_close_position(self, crypto_symbol: Symbol, stock_symbol: Symbol) -> bool:
        """
        判断是否应该平仓

        检查逻辑（只检查 crypto 侧）：
        1. 检查 crypto 是否有持仓（必须有持仓才能平仓）
        2. 检查 crypto 是否有未完成订单（避免重复平仓）

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol (保留参数，便于未来扩展)

        Returns:
            True if should close position, False otherwise
        """
        # 1. 检查 crypto 是否有持仓
        if not self.algorithm.portfolio[crypto_symbol].invested:
            self._debug(f"⚠️ Cannot close - no crypto position | {crypto_symbol.value}")
            return False

        # 2. 检查 crypto 是否有未完成订单（避免重复平仓）
        open_orders = self.algorithm.transactions.get_open_orders(crypto_symbol)
        if len(open_orders) > 0:
            self._debug(
                f"⚠️ Cannot close - crypto has {len(open_orders)} open order(s) | "
                f"{crypto_symbol.value}"
            )
            return False

        # 3. 都通过 → 可以平仓
        return True

    def _open_position(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float,
                      crypto_quote, stock_quote, position_size_pct: float) -> Optional[List]:
        """
        开仓 - 使用 CalculateOrderPair + SpreadMarketOrder 实现市值对冲

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
            position_size_pct: 仓位大小百分比 (e.g., 0.25 = 25%)

        Returns:
            订单tickets列表，如果失败返回None
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 检查是否应该开仓（基于 Lean 原生状态）
        if not self._should_open_position(crypto_symbol, stock_symbol):
            return None

        # 使用 CalculateOrderPair 计算对冲订单对 (市值严格相等，自动适配资金较少的账户)
        # 返回格式: [(symbol1, qty1), (symbol2, qty2)]
        order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct,
            opposite_direction=True  # 对冲: long crypto, short stock
        )

        if order_pair is None:
            self._debug(f"⚠️ Cannot build order pair - insufficient buying power or invalid prices")
            return None

        # 验证数量有效性（解包仅用于验证）
        (sym1, qty1), (sym2, qty2) = order_pair
        if int(qty1) == 0 or int(qty2) == 0:
            self._debug(f"⚠️ Invalid quantity after rounding: qty1={qty1:.2f}, qty2={qty2:.2f}")
            return None

        # 日志：显示计算的订单对
        self._debug(
            f"📊 Order Pair Calculated | Target: {position_size_pct*100}% | "
            f"{sym1.value}: {qty1:.2f} | {sym2.value}: {qty2:.2f}"
        )

        # 直接使用 order_pair 下单 - 无需手动重组
        tickets = self.algorithm.spread_market_order(
            order_pair,
            tag=f"OPEN Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if tickets is None or len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            self._debug(f"❌ Order submission failed")
            return None

        # ✅ 注册订单 (用于 on_order_event 路由)
        self.register_orders(tickets, pair_symbol)

        self._debug(
            f"📈 OPEN | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}%"
        )

        return tickets

    def _close_position(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float,
                       crypto_quote, stock_quote) -> Optional[List]:
        """
        平仓 - 使用 SpreadMarketOrder 平掉当前持仓

        ⚠️ 重要: 使用 SpreadManager 追踪的仓位,而非 Portfolio 总量
        这样可以正确处理多对一场景 (多个 crypto → 同一个 stock)

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价

        Returns:
            订单tickets列表，如果失败返回None
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 检查是否应该平仓（基于 Lean 原生状态）
        if not self._should_close_position(crypto_symbol, stock_symbol):
            return None

        # ✅ 获取这个交易对追踪的仓位 (不是 Portfolio 总量!)
        pair_position = self.get_pair_position(pair_symbol)
        if not pair_position:
            self._debug(f"⚠️ No tracked position for {crypto_symbol.value} <-> {stock_symbol.value}")
            return None

        crypto_qty, stock_qty = pair_position

        # 检查是否有足够的仓位可以平仓
        if abs(crypto_qty) < 1e-8 or abs(stock_qty) < 1e-8:
            self._debug(
                f"⚠️ Position too small to close | "
                f"Crypto: {crypto_qty:.4f}, Stock: {stock_qty:.4f}"
            )
            return None

        # 构建平仓订单对 (使用追踪的数量,取反平仓)
        # 注意: crypto_qty 可能是正或负,stock_qty 可能是正或负
        # 平仓就是完全反向操作
        close_pair = [(crypto_symbol, -crypto_qty), (stock_symbol, -stock_qty)]

        # 使用 SpreadMarketOrder 平仓
        tickets = self.algorithm.spread_market_order(
            close_pair,
            tag=f"CLOSE Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if tickets is None or len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            self._debug(f"❌ Close order submission failed")
            return None

        # ✅ 注册订单 (用于 on_order_event 路由)
        self.register_orders(tickets, pair_symbol)

        self._debug(
            f"📉 CLOSE | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}%"
        )

        return tickets

    # ============================================================================
    #                      Position and Order Management
    # ============================================================================

    def get_pair_position(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[Tuple[float, float]]:
        """
        获取交易对的仓位

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            (crypto_qty, stock_qty) tuple, or None if no position
        """
        return self.positions.get(pair_symbol)

    def update_pair_position(self, pair_symbol: Tuple[Symbol, Symbol],
                            crypto_qty: float, stock_qty: float):
        """
        更新交易对仓位 (累加)

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            crypto_qty: Crypto数量变化
            stock_qty: Stock数量变化
        """
        current_crypto, current_stock = self.positions.get(pair_symbol, (0.0, 0.0))
        new_crypto = current_crypto + crypto_qty
        new_stock = current_stock + stock_qty
        self.positions[pair_symbol] = (new_crypto, new_stock)

        self._debug(
            f"Updated position: {pair_symbol[0].value} ({new_crypto}) <-> "
            f"{pair_symbol[1].value} ({new_stock})"
        )

    def register_orders(self, tickets: List, pair_symbol: Tuple[Symbol, Symbol]):
        """
        注册订单ID到交易对的映射关系

        在创建 SpreadMarketOrder (开仓/平仓) 后调用此方法,建立订单到交易对的映射。
        这样在 on_order_event 时可以精确查找订单所属的交易对。

        Args:
            tickets: SpreadMarketOrder 返回的 OrderTicket 列表
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
        """
        if not tickets:
            return

        for ticket in tickets:
            self.order_to_pair[ticket.order_id] = pair_symbol

        self._debug(
            f"📝 Registered {len(tickets)} orders for pair: "
            f"{pair_symbol[0].value} <-> {pair_symbol[1].value}"
        )

    def get_pair_by_order_id(self, order_id: int) -> Optional[Tuple[Symbol, Symbol]]:
        """
        通过订单ID查找对应的交易对

        在 on_order_event 中使用,将订单事件路由到正确的交易对。

        Args:
            order_id: 订单ID

        Returns:
            (crypto_symbol, stock_symbol) 或 None (如果订单不是被追踪的订单)
        """
        return self.order_to_pair.get(order_id)

    def on_order_event(self, order_event):
        """
        处理订单事件 - 更新追踪的仓位

        通过 order_id 查找对应的交易对,然后根据成交数量更新该交易对的仓位。
        这样可以正确处理多对一场景 (多个 crypto → 同一个 stock)。

        Args:
            order_event: OrderEvent 对象
        """
        # 查找订单所属的交易对
        pair_symbol = self.get_pair_by_order_id(order_event.order_id)

        if not pair_symbol:
            # 不是此策略追踪的订单,忽略
            return

        # 只在成交时更新仓位
        if order_event.status not in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
            return

        crypto_symbol, stock_symbol = pair_symbol
        fill_qty = order_event.fill_quantity

        # 根据 symbol 判断是 crypto 还是 stock 的订单
        if order_event.symbol == crypto_symbol:
            # 更新 crypto 仓位
            self.update_pair_position(
                pair_symbol,
                crypto_qty=fill_qty,
                stock_qty=0.0
            )
            self._debug(
                f"📊 Crypto filled: {crypto_symbol.value} "
                f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
            )

        elif order_event.symbol == stock_symbol:
            # 更新 stock 仓位
            self.update_pair_position(
                pair_symbol,
                crypto_qty=0.0,
                stock_qty=fill_qty
            )
            self._debug(
                f"📊 Stock filled: {stock_symbol.value} "
                f"{'+' if fill_qty > 0 else ''}{fill_qty:.2f} @ {order_event.fill_price:.2f}"
            )

    def on_spread_update(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                        spread_pct: float, crypto_quote, stock_quote,
                        crypto_bid_price: float, crypto_ask_price: float):
        """
        处理spread更新 - 由子类实现具体策略逻辑

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            spread_pct: Spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
            crypto_bid_price: 我们的卖出限价
            crypto_ask_price: 我们的买入限价
        """
        raise NotImplementedError("Subclass must implement on_spread_update()")
