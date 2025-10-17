"""
Base Strategy - 套利策略基类

提供基础的开仓/平仓逻辑，供具体策略继承和扩展
"""
from AlgorithmImports import *
from typing import Tuple, Optional, List, Dict, TYPE_CHECKING

# 避免循环导入，仅用于类型检查
if TYPE_CHECKING:
    from arbitrage.monitoring.state_persistence import StatePersistence


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

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False,
                 state_persistence: Optional['StatePersistence'] = None):
        """
        初始化基础策略

        Args:
            algorithm: QCAlgorithm实例
            debug: 是否输出debug日志 (默认False)
            state_persistence: 状态持久化适配器实例 (可选，如 StatePersistence)
        """
        self.algorithm = algorithm
        self.debug = debug
        self.state_persistence = state_persistence  # 状态持久化适配器（依赖注入）

        # Position tracking: {(crypto_symbol, stock_symbol): (token_qty, stock_qty)}
        # 维护每个交易对的仓位，解决多对一映射问题
        # Example: {(TSLAxUSD, TSLA): (300, -290)}
        self.positions: Dict[Tuple[Symbol, Symbol], Tuple[float, float]] = {}

        # Order to pair mapping (扩展版本，包含 filled_qty_snapshot):
        # {order_id: {"pair": (crypto_symbol, stock_symbol), "filled_qty_snapshot": float}}
        # 用于在 on_order_event 时精确查找订单所属的交易对，并追踪已成交数量
        self.order_to_pair: Dict[int, Dict] = {}

        # 日志输出
        if self.state_persistence:
            self.algorithm.Debug("📊 BaseStrategy: 状态持久化适配器已启用")
        else:
            self.algorithm.Debug("📊 BaseStrategy: 状态持久化适配器未启用")

    def _debug(self, message: str):
        """
        条件debug输出

        Args:
            message: Debug消息
        """
        if self.debug:
            self.algorithm.debug(message)

    def _validate_order_preconditions(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                                       action: str = "order") -> Tuple[bool, str]:
        """
        验证下单前置条件

        检查项:
        1. Crypto security 是否有数据 (HasData)
        2. Stock security 是否有数据 (HasData)
        3. 价格是否有效 (> 0)

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            action: 操作描述 (用于日志，如 "open" / "close")

        Returns:
            (is_valid, error_message): 验证通过返回 (True, "")，失败返回 (False, "原因")
        """
        # 1. 检查 crypto 是否有数据
        crypto_security = self.algorithm.securities[crypto_symbol]
        if not crypto_security.has_data:
            msg = f"⚠️ Cannot {action} - crypto {crypto_symbol.value} has no data yet"
            self._debug(msg)
            return (False, msg)

        # 2. 检查 stock 是否有数据
        stock_security = self.algorithm.securities[stock_symbol]
        if not stock_security.has_data:
            msg = f"⚠️ Cannot {action} - stock {stock_symbol.value} has no data yet"
            self._debug(msg)
            return (False, msg)

        # 3. 检查价格是否有效
        if crypto_security.price <= 0 or stock_security.price <= 0:
            msg = f"⚠️ Cannot {action} - invalid prices (crypto: {crypto_security.price}, stock: {stock_security.price})"
            self._debug(msg)
            return (False, msg)

        # 所有检查通过
        return (True, "")

    def _should_open_position(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                              target_position_size_pct: float = 0.25) -> bool:
        """
        判断是否应该开仓

        检查逻辑（只检查 crypto 侧）：
        1. 检查当前持仓是否已达到目标持仓（支持增量建仓）
        2. 检查 crypto 是否有未完成订单

        为什么只检查 crypto 侧：
        - 组合订单是原子性的，检查一个leg即可
        - 多个 crypto 交易所可能共享同一个 stock 对冲账户
        - 检查 crypto 侧确保每个 pair 独立管理

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol (保留参数，便于未来扩展)
            target_position_size_pct: 目标仓位百分比（默认25%）

        Returns:
            True if should open position, False otherwise
        """
        # 1. 检查当前持仓是否已达到目标持仓
        portfolio_value = self.algorithm.portfolio.total_portfolio_value
        if portfolio_value <= 0:
            self._debug("⚠️ Cannot open - portfolio value is zero or negative")
            return False

        crypto_value = abs(self.algorithm.portfolio[crypto_symbol].holdings_value)
        current_position_pct = crypto_value / portfolio_value

        # 允许5%误差，避免因为价格波动导致无法继续开仓
        if current_position_pct >= target_position_size_pct * 0.95:
            self._debug(
                f"⚠️ Cannot open - position already at target | "
                f"{crypto_symbol.value}: {current_position_pct*100:.2f}% / {target_position_size_pct*100:.1f}%"
            )
            return False

        # 2. 检查 crypto 是否有未完成订单
        open_orders_crypto = self.algorithm.transactions.get_open_orders(crypto_symbol)
        if len(open_orders_crypto) > 0:
            self._debug(
                f"⚠️ Cannot open - crypto has {len(open_orders_crypto)} open order(s) | "
                f"{crypto_symbol.value}"
            )
            return False

        # 3. 检查 stock 是否有未完成订单
        open_orders_stock = self.algorithm.transactions.get_open_orders(stock_symbol)
        if len(open_orders_stock) > 0:
            self._debug(
                f"⚠️ Cannot open - stock has {len(open_orders_stock)} open order(s) | "
                f"{stock_symbol.value}"
            )
            return False

        # 4. 都通过 → 可以开仓
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
            # self._debug(f"⚠️ Cannot close - no crypto position | {crypto_symbol.value}")
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
                      position_size_pct: float) -> Optional[List]:
        """
        开仓 - 使用 CalculateOrderPair + SpreadMarketOrder 实现市值对冲

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比
            position_size_pct: 仓位大小百分比 (e.g., 0.25 = 25%)

        Returns:
            订单tickets列表，如果失败返回None
        """
        crypto_symbol, stock_symbol = pair_symbol

        # ✅ 第一步：验证前置条件（数据和价格）
        is_valid, error_msg = self._validate_order_preconditions(crypto_symbol, stock_symbol, "open")
        if not is_valid:
            return None

        # ✅ 第二步：检查是否应该开仓（基于 Lean 原生状态）
        if not self._should_open_position(crypto_symbol, stock_symbol):
            return None

        # 使用 CalculateOrderPair 计算对冲订单对 (市值严格相等，自动适配资金较少的账户)
        # 返回格式: [(symbol1, qty1), (symbol2, qty2)]
        # useOrderbookConstraint=True (默认): 限制订单大小在 orderbook depth 内，避免过度滑点
        self.algorithm.debug(
            f"🔍 Calling CalculateOrderPair | {crypto_symbol.value}<->{stock_symbol.value} | "
            f"Target: {position_size_pct*100:.1f}%"
        )

        order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct
        )

        if order_pair is None:
            self.algorithm.debug(
                f"❌ CalculateOrderPair returned None | "
                f"{crypto_symbol.value}<->{stock_symbol.value} | "
                f"Possible reasons: insufficient buying power, invalid prices"
            )
            return None

        # ✅ 新版本: order_pair 是 Dictionary<Symbol, decimal>
        # 可以直接通过 symbol 作为 key 访问
        qty1 = float(order_pair[crypto_symbol])  # decimal -> float
        qty2 = float(order_pair[stock_symbol])   # decimal -> float

        self.algorithm.debug(
            f"🔍 CalculateOrderPair result | "
            f"{crypto_symbol.value}: {qty1:.6f} (int={int(qty1)}) | "
            f"{stock_symbol.value}: {qty2:.6f} (int={int(qty2)})"
        )

        # if int(qty1) == 0 or int(qty2) == 0:
        #     self.algorithm.debug(
        #         f"❌ Quantity validation failed | "
        #         f"{sym1.value}: float={qty1:.6f}, int={int(qty1)} | "
        #         f"{sym2.value}: float={qty2:.6f}, int={int(qty2)}"
        #     )
        #     return None

        # 日志：显示计算的订单对
        self._debug(
            f"📊 Order Pair | Target: {position_size_pct*100}% | "
            f"{crypto_symbol.value}: {qty1:.2f} | {stock_symbol.value}: {qty2:.2f}"
        )

        # 直接使用 order_pair 下单 - 无需手动重组
        # ✅ 使用异步订单，避免 5 秒超时阻塞
        tickets = self.algorithm.spread_market_order(
            order_pair,
            asynchronous=True,
            tag=f"OPEN Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if tickets is None:
            self.algorithm.debug(f"❌ SpreadMarketOrder returned None")
            return None

        if len(tickets) < 2:
            self.algorithm.debug(f"❌ SpreadMarketOrder returned {len(tickets)} tickets (expected 2)")
            return None

        invalid_tickets = [t for t in tickets if t.status == OrderStatus.Invalid]
        if invalid_tickets:
            self.algorithm.debug(
                f"❌ Order submission failed - {len(invalid_tickets)} invalid ticket(s) | "
                f"Details: {', '.join([f'{t.symbol.value}={t.status}' for t in invalid_tickets])}"
            )
            return None

        # ✅ 注册订单 (用于 on_order_event 路由)
        self.register_orders(tickets, pair_symbol)

        self.algorithm.debug(
            f"📈 OPEN | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}%"
        )

        return tickets

    def _close_position(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float) -> Optional[List]:
        """
        平仓 - 使用 SpreadMarketOrder 平掉当前持仓

        ⚠️ 重要:
        - Crypto数量从 Portfolio.CashBook 获取实际持仓（因为可能有部分成交/滑点）
        - Stock数量从 pair_position 获取（追踪的数量是可靠的）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比

        Returns:
            订单tickets列表，如果失败返回None
        """
        crypto_symbol, stock_symbol = pair_symbol

        # ✅ 第一步：验证前置条件（数据和价格）
        is_valid, error_msg = self._validate_order_preconditions(crypto_symbol, stock_symbol, "close")
        if not is_valid:
            return None

        # ✅ 第二步：检查是否应该平仓（基于 Lean 原生状态）
        if not self._should_close_position(crypto_symbol, stock_symbol):
            return None

        # ✅ 获取这个交易对追踪的stock仓位
        pair_position = self.get_pair_position(pair_symbol)
        if not pair_position:
            self._debug(f"⚠️ No tracked position for {crypto_symbol.value} <-> {stock_symbol.value}")
            return None

        crypto_qty, stock_qty = pair_position

        # ✅ 获取 crypto 实际持仓（从 CashBook）
        # 使用 Lean 官方方法: Security.BaseCurrency.Symbol
        # crypto_security = self.algorithm.securities[crypto_symbol]
        # crypto_asset = crypto_security.base_currency.symbol
        # crypto_qty = self.algorithm.portfolio.cash_book[crypto_asset].amount

        # 检查是否有足够的仓位可以平仓
        if abs(crypto_qty) < 1e-8 or abs(stock_qty) < 1e-8:
            # self._debug(
            #     f"⚠️ Position too small to close | "
            #     f"Crypto: {crypto_qty:.4f}, Stock: {stock_qty:.4f}"
            # )
            return None

        # 构建平仓订单对 (使用实际数量,取反平仓)
        # crypto_qty 来自 CashBook (实际持仓)
        # stock_qty 来自 pair_position (追踪的数量)
        close_pair = [(crypto_symbol, -crypto_qty), (stock_symbol, -stock_qty)]

        # 使用 SpreadMarketOrder 平仓
        # ✅ 使用异步订单，避免 5 秒超时阻塞
        tickets = self.algorithm.spread_market_order(
            close_pair,
            asynchronous=True,
            tag=f"CLOSE Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if tickets is None or len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            self._debug(f"❌ Close order submission failed")
            return None

        # ✅ 注册订单 (用于 on_order_event 路由)
        self.register_orders(tickets, pair_symbol)

        self.algorithm.debug(
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
        主要作用是更新 position 中的对应持仓，其实就是stock的持仓是多对一的，这样可以明确知道哪个订单归属于哪个持仓

        在创建 SpreadMarketOrder (开仓/平仓) 后调用此方法,建立订单到交易对的映射。
        这样在 on_order_event 时可以精确查找订单所属的交易对。

        Args:
            tickets: SpreadMarketOrder 返回的 OrderTicket 列表
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
        """
        if not tickets:
            return

        for ticket in tickets:
            # 扩展数据结构：包含 pair 和 filled_qty_snapshot
            self.order_to_pair[ticket.order_id] = {
                "pair": pair_symbol,
                "filled_qty_snapshot": 0.0  # 初始化为 0（刚创建订单）
            }

        self._debug(
            f"📝 Registered {len(tickets)} orders for pair: "
            f"{pair_symbol[0].Value} <-> {pair_symbol[1].Value}"
        )

        # 持久化状态（通过适配器）
        if self.state_persistence:
            self.state_persistence.persist(self.positions, self.order_to_pair)

    def get_pair_by_order_id(self, order_id: int) -> Optional[Tuple[Symbol, Symbol]]:
        """
        通过订单ID查找对应的交易对

        在 on_order_event 中使用,将订单事件路由到正确的交易对。

        Args:
            order_id: 订单ID

        Returns:
            (crypto_symbol, stock_symbol) 或 None (如果订单不是被追踪的订单)
        """
        order_info = self.order_to_pair.get(order_id)
        if order_info:
            return order_info["pair"]
        return None

    def on_order_event(self, order_event):
        """
        处理订单事件 - 更新追踪的仓位

        通过 order_id 查找对应的交易对,然后根据成交数量更新该交易对的仓位。
        这样可以正确处理多对一场景 (多个 crypto → 同一个 stock)。

        Args:
            order_event: OrderEvent 对象
        """
        # 查找订单所属的交易对
        order_info = self.order_to_pair.get(order_event.order_id)

        if not order_info:
            # 不是此策略追踪的订单,忽略
            return

        pair_symbol = order_info["pair"]

        # 只在成交时更新仓位
        if order_event.status in [OrderStatus.Filled, OrderStatus.PartiallyFilled]:
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

            # 更新 filled_qty_snapshot（只在 PartiallyFilled 时更新，Filled 时会删除）
            if order_event.status == OrderStatus.PartiallyFilled:
                ticket = self.algorithm.transactions.get_order_ticket(order_event.order_id)
                if ticket:
                    order_info["filled_qty_snapshot"] = float(ticket.quantity_filled)
                    self._debug(
                        f"📊 Updated snapshot: Order {order_event.order_id} | "
                        f"Filled: {order_info['filled_qty_snapshot']:.2f}"
                    )

        # 清理已完成的订单（终态状态）
        # 直接比较枚举值（官方扩展方法 is_closed() 在当前环境不可用）
        if order_event.status in [OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid]:
            if order_event.order_id in self.order_to_pair:
                del self.order_to_pair[order_event.order_id]
                self._debug(
                    f"🗑️ Cleaned order {order_event.order_id} "
                    f"(status: {order_event.status}) from order_to_pair"
                )

        # 持久化状态（通过适配器，在事件末尾）
        if self.state_persistence:
            self.state_persistence.persist(self.positions, self.order_to_pair)

    def on_spread_update(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float):
        """
        处理spread更新 - 由子类实现具体策略逻辑

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
            spread_pct: Spread百分比
        """
        raise NotImplementedError("Subclass must implement on_spread_update()")

    # ============================================================================
    #                      State Persistence and Recovery
    # ============================================================================

    def restore_state(self):
        """
        恢复状态（公共方法，在 Algorithm.Initialize() 末尾调用）

        步骤:
        1. 从 Redis/ObjectStore 加载数据（对比时间戳，选择最新的）
        2. 反序列化 positions 和 order_to_pair
        3. 同步活跃订单的增量成交
        4. 重新持久化（更新 snapshot）
        """
        # 如果没有状态持久化适配器，跳过恢复
        if not self.state_persistence:
            self.algorithm.Debug("ℹ️ No state persistence adapter, skipping state restoration")
            return

        self.algorithm.Debug("=" * 60)
        self.algorithm.Debug("🔄 Restoring strategy state...")
        self.algorithm.Debug("=" * 60)

        # Step 1: 从 Redis/ObjectStore 加载（对比时间戳）
        state_data = self.state_persistence.restore()

        if not state_data:
            self.algorithm.Debug("ℹ️ No saved state found, starting fresh")
            self.algorithm.Debug("=" * 60)
            return

        # Step 2: 反序列化（使用 lambda 作为 symbol_resolver）
        symbol_resolver = lambda symbol_str: self._get_symbol_from_string(symbol_str)

        self.positions = self.state_persistence.deserialize_positions(
            state_data.get("positions", {}),
            symbol_resolver
        )
        self.order_to_pair = self.state_persistence.deserialize_order_to_pair(
            state_data.get("order_to_pair", {}),
            symbol_resolver
        )

        self.algorithm.Debug(
            f"✅ Loaded state from {state_data.get('source', 'unknown')} "
            f"(saved at {state_data.get('timestamp')})"
        )
        self.algorithm.Debug(f"   {len(self.positions)} positions, {len(self.order_to_pair)} active orders")

        # 显示恢复的 positions
        for pair, (crypto_qty, stock_qty) in self.positions.items():
            self.algorithm.Debug(
                f"  Position: {pair[0].Value} ({crypto_qty:.2f}) <-> "
                f"{pair[1].Value} ({stock_qty:.2f})"
            )

        # Step 3: 同步活跃订单的增量成交
        self._sync_open_orders()

        # Step 4: 重新持久化（更新 snapshot）
        self.state_persistence.persist(self.positions, self.order_to_pair)

        self.algorithm.Debug("=" * 60)

    def _get_symbol_from_string(self, symbol_str: str) -> Optional[Symbol]:
        """
        从字符串查找 Symbol 对象（用于状态恢复）

        通过遍历 algorithm.securities 查找匹配的 Symbol

        Args:
            symbol_str: Symbol 字符串表示

        Returns:
            匹配的 Symbol 对象，或 None
        """
        for symbol in self.algorithm.Securities.Keys:
            if symbol.Value == symbol_str:
                return symbol
        return None

    def _sync_open_orders(self):
        """
        同步活跃订单的增量成交

        对于 order_to_pair 中的每个订单:
        1. 主动查询 OrderTicket.QuantityFilled（不依赖事件）
        2. 计算增量 = current_filled - snapshot_filled
        3. 增量更新 positions
        4. 更新 snapshot
        5. 清理已完成订单
        """
        if not self.order_to_pair:
            self.algorithm.debug("ℹ️ No active orders to sync")
            return

        self.algorithm.debug(f"🔄 Syncing {len(self.order_to_pair)} active orders...")

        synced_count = 0

        for order_id, order_info in list(self.order_to_pair.items()):
            pair_symbol = order_info["pair"]
            snapshot_filled = order_info["filled_qty_snapshot"]

            # 主动查询订单当前状态
            ticket = self.algorithm.transactions.get_order_ticket(order_id)

            if not ticket:
                self.algorithm.debug(f"⚠️ Order {order_id} not found, removing")
                del self.order_to_pair[order_id]
                continue

            # 获取当前累计成交数量
            current_filled = float(ticket.quantity_filled)

            # 计算增量（断线期间的新成交）
            delta = current_filled - snapshot_filled

            if abs(delta) > 1e-8:
                # 增量更新 positions
                crypto_symbol, stock_symbol = pair_symbol

                if ticket.symbol == crypto_symbol:
                    self.update_pair_position(
                        pair_symbol,
                        crypto_qty=delta,
                        stock_qty=0.0
                    )
                elif ticket.symbol == stock_symbol:
                    self.update_pair_position(
                        pair_symbol,
                        crypto_qty=0.0,
                        stock_qty=delta
                    )

                # 更新 snapshot 为当前值
                order_info["filled_qty_snapshot"] = current_filled

                self.algorithm.debug(
                    f"  ✓ Synced Order {order_id} | {ticket.symbol.value} | "
                    f"Delta: {delta:+.2f} (Snapshot: {snapshot_filled:.2f} → Current: {current_filled:.2f})"
                )

                synced_count += 1

            # 清理已完成订单
            # 直接比较枚举值（官方扩展方法 is_closed() 在当前环境不可用）
            if ticket.status in [OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid]:
                del self.order_to_pair[order_id]
                self.algorithm.debug(f"  🗑️ Cleaned completed order {order_id}")

        if synced_count > 0:
            self.algorithm.debug(f"✅ Synced {synced_count} orders with new fills")
        else:
            self.algorithm.debug("ℹ️ No new fills during disconnect")
