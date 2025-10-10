"""
Base Strategy - 套利策略基类

提供基础的开仓/平仓逻辑，供具体策略继承和扩展
"""
from AlgorithmImports import *
from typing import Tuple, Optional, List


class BaseStrategy:
    """
    套利策略基类

    功能:
    - 提供基础的开仓/平仓方法
    - 使用 Lean 原生接口防止重复订单（Portfolio.Invested + GetOpenOrders）
    - 只检查 crypto 侧状态，避免多交易所对冲冲突
    - 可选的debug输出控制

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

        # 获取真实持仓数量
        # Crypto: 从 CashBook 获取（因为被当作"货币"处理，存储在 BaseCurrency 中）
        # Stock: 从 Portfolio 获取（传统证券持仓）
        crypto_security = self.algorithm.securities[crypto_symbol]
        crypto_base_currency_symbol = crypto_security.base_currency.symbol

        # 尝试从多账户获取
        crypto_qty = 0
        if hasattr(self.algorithm.portfolio, 'get_account'):
            try:
                # 从 Kraken 子账户获取
                kraken_account = self.algorithm.portfolio.get_account("Kraken")
                if kraken_account.cash_book.contains_key(crypto_base_currency_symbol):
                    crypto_qty = kraken_account.cash_book[crypto_base_currency_symbol].amount
                    self._debug(f"✅ Got crypto_qty from Kraken: {crypto_qty:.2f}")
                else:
                    self._debug(f"⚠️ {crypto_base_currency_symbol} not in Kraken CashBook")
            except Exception as e:
                self._debug(f"⚠️ Error accessing Kraken account: {e}")
                # 回退到主账户
                if self.algorithm.portfolio.cash_book.contains_key(crypto_base_currency_symbol):
                    crypto_qty = self.algorithm.portfolio.cash_book[crypto_base_currency_symbol].amount
                    self._debug(f"⚠️ Fallback to main CashBook: {crypto_qty:.2f}")
                else:
                    self._debug(f"❌ {crypto_base_currency_symbol} not in main CashBook either")
        else:
            # 单账户模式
            if self.algorithm.portfolio.cash_book.contains_key(crypto_base_currency_symbol):
                crypto_qty = self.algorithm.portfolio.cash_book[crypto_base_currency_symbol].amount
                self._debug(f"ℹ️ Single account mode, crypto_qty: {crypto_qty:.2f}")
            else:
                self._debug(f"❌ {crypto_base_currency_symbol} not in CashBook")

        # 获取股票数量（Holdings 是共享的）
        stock_qty = self.algorithm.portfolio[stock_symbol].quantity
        self._debug(f"🔍 Stock quantity: {stock_qty:.2f}")

        # 检查是否有足够的仓位可以平仓
        if abs(crypto_qty) < 1e-8 or abs(stock_qty) < 1e-8:
            self._debug(
                f"⚠️ Cannot close position - one or both legs have zero quantity | "
                f"Crypto: {crypto_qty:.4f}, Stock: {stock_qty:.4f}"
            )
            return None

        # 构建平仓订单对: [(crypto_symbol, -crypto_qty), (stock_symbol, stock_qty)]
        close_pair = [(crypto_symbol, -crypto_qty), (stock_symbol, stock_qty)]

        # 使用 SpreadMarketOrder 平仓
        tickets = self.algorithm.spread_market_order(
            close_pair,
            tag=f"CLOSE Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if tickets is None or len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            self._debug(f"❌ Close order submission failed")
            return None

        self._debug(
            f"📉 CLOSE | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}%"
        )

        return tickets

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
