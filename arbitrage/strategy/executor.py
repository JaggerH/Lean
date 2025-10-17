"""
Executor - 执行管理器

负责根据ExecutionTarget执行订单，包括：
1. 验证执行前置条件（市场开盘、价格有效、价差方向）
2. 检查是否有pending订单（避免重复下单）
3. 根据OrderbookDepth计算可执行数量
4. 提交订单并注册到GridPositionManager

不使用中间结构，直接使用OrderGroup追踪订单
"""
from AlgorithmImports import QCAlgorithm, Symbol
from typing import Tuple, Dict, List, Optional
from .execution_models import ExecutionTarget, ExecutionStatus


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

    def __init__(self, algorithm: QCAlgorithm, debug: bool = False):
        """
        初始化ExecutionManager

        Args:
            algorithm: QCAlgorithm实例
            debug: 是否启用调试日志
        """
        self.algorithm = algorithm
        self.debug_enabled = debug
        # Track active ExecutionTargets: key = (pair_symbol, grid_id)
        self.active_targets: Dict[Tuple[Tuple[Symbol, Symbol], str], ExecutionTarget] = {}

    def register_execution_target(self, target: ExecutionTarget):
        grid_id = target.grid_id
        execution_key = target.get_execution_key()
        target.created_time = self.algorithm.UtcTime
        self.active_targets[execution_key] = target
        self._debug(f"📝 Registered ExecutionTarget for grid {grid_id}")
        
    def execute(self, target: ExecutionTarget):
        """
        执行目标仓位 - 单次tick只提交一组订单

        关键原则:
        1. 一个tick最多提交一组订单（一个OrderGroup）
        2. 如果有pending订单，跳过（等待超时或成交）
        3. 下一个tick会用更新的orderbook重新计算

        Args:
            target: ExecutionTarget对象，包含目标数量和执行参数
        """
        pair_symbol = target.pair_symbol
        grid_id = target.grid_id
        crypto_symbol, stock_symbol = pair_symbol

        execution_key = target.get_execution_key()

        # 注册新的ExecutionTarget
        self.active_targets[execution_key] = target

        # === 步骤 1: 验证前置条件 ===
        if not self._validate_preconditions(crypto_symbol, stock_symbol):
            return

        # === 步骤 2: 计算剩余需要执行的数量 ===
        remaining_qty = target.get_remaining_qty()

        crypto_remaining = remaining_qty[crypto_symbol]
        stock_remaining = remaining_qty[stock_symbol]

        # 如果剩余数量小于最小交易单位，说明已经填满
        crypto_lot_size = self.algorithm.securities[crypto_symbol].symbol_properties.lot_size
        stock_lot_size = self.algorithm.securities[stock_symbol].symbol_properties.lot_size

        if abs(crypto_remaining) < crypto_lot_size or abs(stock_remaining) < stock_lot_size:
            self._debug(f"✅ Grid {grid_id} position already filled")
            return

        # === 步骤 3: 根据当前orderbook计算本次可执行数量 ===
        # 返回 (crypto_qty, stock_qty, expected_spread)
        executable_qty = self._calculate_executable_quantity(
            pair_symbol,
            remaining_qty,
            target.expected_spread_pct,
            target.spread_direction
        )

        if not executable_qty:
            self._debug(f"⏸️ Grid {grid_id} no valid execution opportunity this tick")
            return

        crypto_qty, stock_qty, actual_spread = executable_qty

        # === 步骤 4: 提交订单 ===
        tickets = self._submit_orders(
            crypto_symbol, crypto_qty,
            stock_symbol, stock_qty,
            grid_id, actual_spread
        )

        if not tickets or len(tickets) < 2:
            self.algorithm.debug(f"❌ Order submission failed for grid {grid_id}")
            # Mark ExecutionTarget as FAILED and remove from active_targets
            target.status = ExecutionStatus.FAILED
            del self.active_targets[execution_key]
            return

        # === 步骤 5: 注册OrderGroup到grid_position_manager ===
        target.grid_position_manager.register_order_group(
            pair_symbol, grid_id, tickets, actual_spread
        )

        # === 步骤 6: 更新ExecutionTarget状态 ===
        target.status = ExecutionStatus.EXECUTING
        target.order_group_id = target.grid_position_manager.order_group_to_grid.get(
            (tickets[0].order_id, tickets[1].order_id)
        )

        self.algorithm.debug(
            f"📤 Submitted orders for grid {grid_id} | "
            f"Crypto: {crypto_qty:.4f}, Stock: {stock_qty:.4f} | "
            f"Spread: {actual_spread*100:.2f}%"
        )

    def _validate_preconditions(self, crypto_symbol: Symbol, stock_symbol: Symbol) -> bool:
        """
        验证执行前置条件

        检查:
        1. 两个市场是否同时开盘
        2. 价格数据是否有效

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol

        Returns:
            True if valid, False otherwise
        """
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

    def _calculate_executable_quantity(
        self,
        pair_symbol: Tuple[Symbol, Symbol],
        remaining_qty: Dict[Symbol, float],
        expected_spread_pct: float,
        spread_direction: str
    ) -> Optional[Tuple[float, float, float]]:
        """
        根据当前orderbook计算可执行数量

        核心逻辑:
        1. 获取Crypto的OrderbookDepth（最多10档）
        2. 获取Stock的BestBid/BestAsk（取决于方向）
        3. 遍历Crypto深度，检查每档价格与Stock价格的spread
        4. 如果spread不满足方向条件，停止累积
        5. 计算对冲的Stock数量（市值相等）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            remaining_qty: 剩余需要执行的数量
            expected_spread_pct: 预期价差百分比
            spread_direction: "LONG_CRYPTO" or "SHORT_CRYPTO"

        Returns:
            (crypto_qty, stock_qty, actual_spread) 或 None
        """
        crypto_symbol, stock_symbol = pair_symbol
        crypto_remaining = remaining_qty[crypto_symbol]
        stock_remaining = remaining_qty[stock_symbol]

        # 获取Stock的参考价格（BestBid for short, BestAsk for long）
        stock_price = self._get_stock_reference_price(stock_symbol, spread_direction)
        if not stock_price:
            return None

        # 获取Crypto的OrderbookDepth
        orderbook = self._get_orderbook_depth(crypto_symbol, spread_direction)
        if not orderbook or len(orderbook) == 0:
            # 没有orderbook数据，使用简化逻辑（直接使用剩余数量）
            return self._calculate_simple_qty(
                crypto_symbol, stock_symbol,
                crypto_remaining, stock_remaining,
                expected_spread_pct, spread_direction
            )

        # 遍历深度，累积可执行数量
        cumulative_crypto_qty = 0.0
        cumulative_crypto_value = 0.0
        valid_levels = 0

        for i, (price, available_qty) in enumerate(orderbook[:10]):
            # 计算当前档位的价差
            spread = (price - stock_price) / price

            # 检查价差是否满足方向条件
            if not self._is_spread_valid(spread, expected_spread_pct, spread_direction):
                # 不满足条件，停止累积
                break

            # 限制不超过剩余需要执行的数量
            executable_qty = min(available_qty, abs(crypto_remaining) - cumulative_crypto_qty)

            if executable_qty <= 1e-8:
                break

            # 累积
            cumulative_crypto_qty += executable_qty
            cumulative_crypto_value += executable_qty * price
            valid_levels += 1

        if cumulative_crypto_qty < 1e-8:
            return None

        # 计算对冲的Stock数量（市值相等）
        hedge_stock_value = cumulative_crypto_value
        hedge_stock_qty = hedge_stock_value / stock_price

        # 限制不超过剩余需要执行的数量
        if hedge_stock_qty > abs(stock_remaining):
            # 按Stock的限制重新计算Crypto数量
            hedge_stock_qty = abs(stock_remaining)
            hedge_stock_value = hedge_stock_qty * stock_price
            cumulative_crypto_qty = hedge_stock_value / (cumulative_crypto_value / cumulative_crypto_qty)

        # 根据方向调整符号
        if spread_direction == "LONG_CRYPTO":
            final_crypto_qty = cumulative_crypto_qty  # 买入crypto（正数）
            final_stock_qty = -hedge_stock_qty        # 卖出stock（负数）
        else:  # SHORT_CRYPTO
            final_crypto_qty = -cumulative_crypto_qty  # 卖出crypto（负数）
            final_stock_qty = hedge_stock_qty          # 买入stock（正数）

        # 计算加权平均价差
        avg_crypto_price = cumulative_crypto_value / cumulative_crypto_qty
        actual_spread = (avg_crypto_price - stock_price) / avg_crypto_price

        self._debug(
            f"📊 Calculated executable qty | "
            f"Crypto: {final_crypto_qty:.4f} @ ${avg_crypto_price:.2f} | "
            f"Stock: {final_stock_qty:.4f} @ ${stock_price:.2f} | "
            f"Spread: {actual_spread*100:.2f}% | "
            f"Valid levels: {valid_levels}"
        )

        return (final_crypto_qty, final_stock_qty, actual_spread)

    def _calculate_simple_qty(
        self,
        crypto_symbol: Symbol,
        stock_symbol: Symbol,
        crypto_remaining: float,
        stock_remaining: float,
        expected_spread_pct: float,
        spread_direction: str
    ) -> Optional[Tuple[float, float, float]]:
        """
        简化版数量计算（没有orderbook数据时使用）

        直接使用剩余数量和当前价格计算

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            crypto_remaining: Crypto剩余数量
            stock_remaining: Stock剩余数量
            expected_spread_pct: 预期价差百分比
            spread_direction: "LONG_CRYPTO" or "SHORT_CRYPTO"

        Returns:
            (crypto_qty, stock_qty, actual_spread) 或 None
        """
        crypto_price = self.algorithm.securities[crypto_symbol].price
        stock_price = self.algorithm.securities[stock_symbol].price

        if crypto_price <= 0 or stock_price <= 0:
            return None

        # 计算当前价差
        current_spread = (crypto_price - stock_price) / crypto_price

        # 检查价差是否满足条件
        if not self._is_spread_valid(current_spread, expected_spread_pct, spread_direction):
            return None

        # 直接使用剩余数量
        return (crypto_remaining, stock_remaining, current_spread)

    def _is_spread_valid(self, spread: float, expected_spread: float, direction: str) -> bool:
        """
        检查价差是否满足方向条件

        Args:
            spread: 当前价差百分比
            expected_spread: 预期价差百分比
            direction: "LONG_CRYPTO" or "SHORT_CRYPTO"

        Returns:
            True if valid, False otherwise
        """
        if direction == "LONG_CRYPTO":
            # 做多crypto：价差越低越好（spread <= expected）
            return spread <= expected_spread
        else:  # SHORT_CRYPTO
            # 做空crypto：价差越高越好（spread >= expected）
            return spread >= expected_spread

    def _get_stock_reference_price(self, stock_symbol: Symbol, direction: str) -> Optional[float]:
        """
        获取Stock的参考价格

        LONG_CRYPTO: 使用BestAsk（买入股票时的卖价）
        SHORT_CRYPTO: 使用BestBid（卖出股票时的买价）

        Args:
            stock_symbol: Stock Symbol
            direction: "LONG_CRYPTO" or "SHORT_CRYPTO"

        Returns:
            参考价格 或 None
        """
        # 简化实现：使用当前price（实际应该从OrderbookDepth获取BestBid/Ask）
        # TODO: 实现真实的BestBid/BestAsk获取
        price = self.algorithm.securities[stock_symbol].price

        if price <= 0:
            return None

        # 根据方向调整（简化实现，实际需要bid/ask spread）
        if direction == "LONG_CRYPTO":
            # 买入stock，使用ask price（保守估计+0.01%）
            return price * 1.0001
        else:
            # 卖出stock，使用bid price（保守估计-0.01%）
            return price * 0.9999

    def _get_orderbook_depth(self, symbol: Symbol, direction: str) -> Optional[List[Tuple[float, float]]]:
        """
        获取OrderbookDepth

        Args:
            symbol: Symbol
            direction: "LONG_CRYPTO" or "SHORT_CRYPTO"

        Returns:
            [(price, quantity), ...] 列表，按价格排序
            LONG_CRYPTO: asks（从低到高）
            SHORT_CRYPTO: bids（从高到低）
        """
        # TODO: 实现真实的OrderbookDepth获取
        # 现在返回None（使用简化逻辑）
        return None

    def _submit_orders(
        self,
        crypto_symbol: Symbol, crypto_qty: float,
        stock_symbol: Symbol, stock_qty: float,
        grid_id: str, spread_pct: float
    ) -> List:
        """
        提交订单对

        Args:
            crypto_symbol: Crypto Symbol
            crypto_qty: Crypto数量（带符号）
            stock_symbol: Stock Symbol
            stock_qty: Stock数量（带符号）
            grid_id: 网格线ID
            spread_pct: 价差百分比

        Returns:
            OrderTicket列表
        """
        tag = f"Grid {grid_id} | Spread={spread_pct*100:.2f}%"

        ticket_1 = self.algorithm.market_order(
            crypto_symbol,
            crypto_qty,
            asynchronous=True,
            tag=tag
        )

        ticket_2 = self.algorithm.market_order(
            stock_symbol,
            stock_qty,
            asynchronous=True,
            tag=tag
        )

        return [ticket_1, ticket_2]

    def has_active_execution(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str) -> bool:
        """
        检查是否有活跃的ExecutionTarget

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID

        Returns:
            True if has active ExecutionTarget, False otherwise
        """
        execution_key = (pair_symbol, grid_id)
        return execution_key in self.active_targets

    def on_execution_completed(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str):
        """
        执行完成回调 - 由GridPositionManager调用

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
        """
        execution_key = (pair_symbol, grid_id)
        target = self.active_targets.get(execution_key)

        if target:
            target.status = ExecutionStatus.COMPLETED
            del self.active_targets[execution_key]
            self._debug(f"✅ ExecutionTarget for grid {grid_id} completed and removed")
        else:
            self._debug(f"⚠️ No active ExecutionTarget found for grid {grid_id}")

    def on_execution_failed(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str):
        """
        执行失败回调 - 由GridPositionManager调用

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
        """
        execution_key = (pair_symbol, grid_id)
        target = self.active_targets.get(execution_key)

        if target:
            target.status = ExecutionStatus.FAILED
            del self.active_targets[execution_key]
            self._debug(f"❌ ExecutionTarget for grid {grid_id} failed and removed")
        else:
            self._debug(f"⚠️ No active ExecutionTarget found for grid {grid_id}")

    def _debug(self, message: str):
        """条件debug输出"""
        if self.debug_enabled:
            self.algorithm.debug(f"[{self.algorithm.time}]" + message)
