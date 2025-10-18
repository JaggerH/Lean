"""
Grid Strategy - 网格交易策略基类

继承 BaseStrategy，添加网格交易支持
提供网格交易的核心逻辑（进场线/出场线触发、网格持仓管理等）
"""
from AlgorithmImports import QCAlgorithm, Symbol, OrderStatus
from typing import Tuple, List, Dict, Optional, TYPE_CHECKING
from .base_strategy import BaseStrategy
from .grid_models import GridLevel, generate_grid_id
from .grid_level_manager import GridLevelManager
from .grid_position_manager import GridPositionManager
from .execution_manager import ExecutionManager
from .execution_models import ExecutionTarget

if TYPE_CHECKING:
    from spread_manager import SpreadManager


class GridStrategy(BaseStrategy):
    """
    网格交易策略基类

    特点:
    - 继承 BaseStrategy 的订单管理和状态持久化
    - 添加网格交易支持（多进场线/出场线）
    - 支持部分成交和分步建仓
    - 协调开仓/平仓判断（挂单检查 + 持仓检查）

    架构:
    - ExecutionManager: 管理挂单（active ExecutionTargets）
    - GridPositionManager: 管理持仓（actual_qty）
    - GridStrategy: 策略决策（协调挂单+持仓检查）

    子类需要实现:
    - _setup_grid_levels(): 配置网格线
    """

    def __init__(self, algorithm: QCAlgorithm, spread_manager: Optional['SpreadManager'] = None,
                 debug: bool = False, state_persistence=None):
        """
        初始化网格策略

        Args:
            algorithm: QCAlgorithm 实例
            spread_manager: SpreadManager 实例（可选）
            debug: 是否启用调试日志
            state_persistence: 状态持久化适配器（可选）
        """
        # 调用父类初始化
        super().__init__(algorithm, debug=debug, state_persistence=state_persistence)

        self.spread_manager = spread_manager

        # 初始化网格管理器
        self.grid_level_manager = GridLevelManager(algorithm)
        self.grid_position_manager = GridPositionManager(algorithm, debug=debug)

        # 初始化执行管理器
        # self.execution_manager = ExecutionManager(algorithm, debug=debug)
        self.execution_manager = ExecutionManager(algorithm, debug=True)

        self.algorithm.debug("📊 GridStrategy initialized")

    def _setup_grid_levels(self, pair_symbol: Tuple[Symbol, Symbol], levels: List[GridLevel]):
        """
        配置网格线（由子类调用）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            levels: GridLevel 列表

        Example:
            >>> levels = [
            ...     GridLevel("entry_1", "ENTRY", -0.01, "exit_1", 0.25),
            ...     GridLevel("exit_1", "EXIT", 0.02, None, 0.25)
            ... ]
            >>> self._setup_grid_levels((crypto_sym, stock_sym), levels)
        """
        # 添加网格线到管理器
        self.grid_level_manager.add_grid_levels(pair_symbol, levels)

        # 验证网格线配置
        try:
            # 获取手续费模型（简化实现：使用默认值）
            # 实际应该从 Security.FeeModel 获取
            crypto_fee_pct = 0.0026  # Kraken Maker Fee
            stock_fee_pct = 0.0005   # IBKR 估算

            self.grid_level_manager.validate_grid_levels(
                pair_symbol, crypto_fee_pct, stock_fee_pct
            )

            # 打印网格线配置摘要
            summary = self.grid_level_manager.get_summary(pair_symbol)
            self.algorithm.debug("\n" + summary)

        except ValueError as e:
            self.algorithm.error(f"❌ Grid level validation failed: {e}")
            raise

    def should_open_position(self, pair_symbol: Tuple[Symbol, Symbol],
                            spread_pct: float, level: GridLevel) -> Optional[str]:
        """
        判断是否需要开仓（策略层协调）

        检查逻辑:
        1. 市场是否同时开盘（crypto 和 stock 都必须在交易时段）
        2. 是否有active ExecutionTarget（挂单检查 - ExecutionManager）
        3. 持仓是否达到目标（持仓检查 - GridPositionManager）
        4. 是否有孤立仓位（失败重试检查）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比
            level: 触发的网格线配置

        Returns:
            grid_id if should open, None otherwise
        """
        crypto_symbol, stock_symbol = pair_symbol
        grid_id = generate_grid_id(pair_symbol, level.level_id)

        # === 1. 市场开盘检查 ===
        crypto_exchange_open = self.algorithm.securities[crypto_symbol].exchange.exchange_open
        stock_exchange_open = self.algorithm.securities[stock_symbol].exchange.exchange_open

        if not (crypto_exchange_open and stock_exchange_open):
            self.algorithm.debug(
                f"⚠️ Market not open | Grid: {grid_id} | "
                f"Crypto: {crypto_exchange_open}, Stock: {stock_exchange_open}"
            )
            return None

        # === 2. 挂单检查（ExecutionManager）===
        if self.execution_manager.has_active_execution(pair_symbol, grid_id):
            # self.algorithm.debug(f"⚠️ Grid {grid_id} has active execution, skipping")
            return None

        # === 3. 持仓检查（GridPositionManager）===
        if self.grid_position_manager.has_reached_target(pair_symbol, level):
            self.algorithm.debug(f"⚠️ Grid {grid_id} position reached target, skipping")
            return None

        # === 4. 检查失败订单，允许重试 ===
        grid_position = self.grid_position_manager.get_grid_position(pair_symbol, grid_id)

        # if grid_position:
            # 检查是否有孤立仓位（单边持仓）
            # if self.grid_position_manager._has_orphan_position(grid_position):
            #     self.algorithm.debug(
            #         f"⚠️ Grid {grid_id} has orphan position, cannot retry | "
            #         f"Crypto: {grid_position.actual_crypto_qty:.4f}, "
            #         f"Stock: {grid_position.actual_stock_qty:.4f}"
            #     )
            #     return None

            # 重置状态，允许重试
            # self.algorithm.debug(f"🔄 Retrying failed grid {grid_id}")

        # === 5. 创建 GridPosition（如果不存在）===
        # 提前创建是为了追踪后续的订单组
        if not grid_position:
            self.grid_position_manager.get_or_create_grid_position(pair_symbol, grid_id, level)

        return grid_id

    def should_close_position(self, pair_symbol: Tuple[Symbol, Symbol],
                             spread_pct: float) -> List[str]:
        """
        判断哪些网格线需要平仓（策略层协调）

        检查逻辑:
        1. 市场是否同时开盘
        2. 遍历活跃网格线（FILLED状态）
        3. 检查是否有active ExecutionTarget（跳过正在执行的）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比

        Returns:
            List of grid_ids that should be closed
        """
        crypto_symbol, stock_symbol = pair_symbol

        # === 1. 市场开盘检查 ===
        crypto_exchange_open = self.algorithm.securities[crypto_symbol].exchange.exchange_open
        stock_exchange_open = self.algorithm.securities[stock_symbol].exchange.exchange_open

        if not (crypto_exchange_open and stock_exchange_open):
            return []

        # === 2. 获取活跃网格线 ===
        pair_positions = self.grid_position_manager.grid_positions.get(pair_symbol, {})

        closable_grids = []

        for grid_id, position in pair_positions.items():
            # 只有 FILLED 状态的网格线可以平仓
            # === 3. 检查是否有active ExecutionTarget ===
            if self.execution_manager.has_active_execution(pair_symbol, grid_id):
                self.algorithm.debug(f"⚠️ Grid {grid_id} has active execution, skipping close")
                continue

            closable_grids.append(grid_id)

        return closable_grids

    def on_data(self, data):
        """
        处理数据更新 - 重新触发 active ExecutionTargets

        每个 tick 检查所有 PENDING 状态的 ExecutionTarget：
        - 重新检查 orderbook 深度
        - 重新检查价差是否满足条件
        - 尝试提交订单

        Args:
            data: Slice 数据
        """
        # 重新触发所有 New 状态的 ExecutionTargets
        for execution_key, target in list(self.execution_manager.active_targets.items()):
            if target.is_active():
                self.execution_manager.execute(target)

    def on_spread_update(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float):
        """
        处理价差更新 - 网格交易逻辑

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: Spread 百分比
        """
        crypto_symbol, stock_symbol = pair_symbol

        # === 1. 检查是否触发进场线 ===
        entry_level = self.grid_level_manager.get_triggered_entry_level(pair_symbol, spread_pct)

        if entry_level:
            # 检查是否应该开仓
            grid_id = self.should_open_position(pair_symbol, spread_pct, entry_level)

            if grid_id:
                self._open_grid_position(pair_symbol, grid_id, entry_level, spread_pct)

        # === 2. 检查是否触发出场线 ===
        # 获取可以平仓的网格线ID（策略层判断）
        closable_grid_ids = self.should_close_position(pair_symbol, spread_pct)

        if closable_grid_ids:
            # 查找被触发的出场线
            exit_levels = self.grid_level_manager.get_triggered_exit_levels(
                pair_symbol, spread_pct, closable_grid_ids
            )

            # 对每个触发的出场线，检查对应的网格线是否需要平仓
            for exit_level in exit_levels:
                # 找到配对的进场线对应的 grid_id
                # 遍历可平仓网格，检查是否匹配出场线
                for grid_id in closable_grid_ids:
                    position = self.grid_position_manager.get_grid_position(pair_symbol, grid_id)
                    if not position:
                        continue

                    # 检查是否是配对的网格线
                    if position.level.paired_exit_level_id == exit_level.level_id:
                        self._close_grid_position(pair_symbol, grid_id, spread_pct)

    def _open_grid_position(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str,
                           level: GridLevel, spread_pct: float):
        """
        开仓 - 委托给执行层

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
            level: 网格线配置
            spread_pct: 当前价差百分比
        """
        crypto_symbol, stock_symbol = pair_symbol

        # ✅ 计算目标数量（Strategy职责）
        position_size_pct = level.position_size_pct
        if level.direction == "SHORT_CRYPTO":
            position_size_pct = -position_size_pct

        target_order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct
        )

        # ✅ 构建执行目标
        execution_target = ExecutionTarget(
            pair_symbol=pair_symbol,
            grid_id=grid_id,
            target_qty=target_order_pair,
            expected_spread_pct=spread_pct,
            spread_direction=level.direction,
            algorithm=self.algorithm
        )
        
        # register execution in active target
        self.execution_manager.register_execution_target(execution_target)
        # ✅ 委托给执行层（完全交给 ExecutionManager）
        self.execution_manager.execute(execution_target)

    def _close_grid_position(self, pair_symbol: Tuple[Symbol, Symbol], grid_id: str,
                            spread_pct: float):
        """
        平仓 - 委托给执行层

        根据 GridPosition 的实际持仓数量平仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            grid_id: 网格线ID
            spread_pct: 当前价差百分比
        """
        crypto_symbol, stock_symbol = pair_symbol

        # ✅ 获取网格线持仓
        position = self.grid_position_manager.get_grid_position(pair_symbol, grid_id)
        if not position:
            self.algorithm.debug(f"⚠️ Grid position {grid_id} not found")
            return

        crypto_qty = position.actual_crypto_qty
        stock_qty = position.actual_stock_qty

        # 检查是否有足够的仓位可以平仓
        if abs(crypto_qty) < 1e-8 or abs(stock_qty) < 1e-8:
            self.algorithm.debug(
                f"⚠️ Grid {grid_id} position too small to close | "
                f"Crypto: {crypto_qty:.4f}, Stock: {stock_qty:.4f}"
            )
            return

        self.algorithm.debug(
            f"🔍 Closing grid position | Grid: {grid_id} | "
            f"Spread: {spread_pct*100:.2f}% | "
            f"Crypto: {crypto_qty:.2f} | Stock: {stock_qty:.2f}"
        )

        # ✅ 构建执行目标（平仓目标 = 0）
        target_order_pair = {
            crypto_symbol: 0.0,
            stock_symbol: 0.0
        }

        execution_target = ExecutionTarget(
            pair_symbol=pair_symbol,
            grid_id=grid_id,
            target_qty=target_order_pair,
            expected_spread_pct=spread_pct,
            spread_direction=position.level.direction,
            grid_position_manager=self.grid_position_manager
        )

        # ✅ 标记网格线为正在平仓
        position.status = "CLOSING"

        # ✅ 委托给执行层
        self.execution_manager.execute(execution_target)

    def on_order_event(self, order_event):
        """
        处理订单事件 - 扩展版本

        事件驱动更新链：
        Order → ExecutionManager (更新 ExecutionTarget)
             → GridPositionManager (更新 GridPosition)
             → BaseStrategy (更新 positions)

        Args:
            order_event: OrderEvent 对象
        """
        # 调用父类的订单事件处理（更新 positions）
        super().on_order_event(order_event)

        # 调用 ExecutionManager 的订单事件处理（更新 ExecutionTarget）
        self.execution_manager.on_order_event(order_event)

        # 调用 GridPositionManager 的订单事件处理（更新网格持仓）
        self.grid_position_manager.on_order_event(order_event)

    # ============================================================================
    #                      统计和报告
    # ============================================================================

    def get_grid_summary(self, pair_symbol: Tuple[Symbol, Symbol]) -> str:
        """
        获取网格交易摘要

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            格式化的摘要字符串
        """
        level_summary = self.grid_level_manager.get_summary(pair_symbol)
        position_summary = self.grid_position_manager.get_summary(pair_symbol)

        return f"{level_summary}\n\n{position_summary}"
