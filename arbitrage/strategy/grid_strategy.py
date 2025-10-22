"""
Grid Strategy - 网格交易策略基类

继承 BaseStrategy，添加网格交易支持
提供网格交易的核心逻辑（进场线/出场线触发、网格持仓管理等）
"""
from AlgorithmImports import QCAlgorithm, Symbol, OrderStatus
from typing import Tuple, List, Dict, Optional, TYPE_CHECKING
from .base_strategy import BaseStrategy
from .grid_models import GridLevel, GridPosition, generate_order_tag
from .grid_level_manager import GridLevelManager
from .grid_position_manager import GridPositionManager
from .execution_manager import ExecutionManager
from .execution_models import ExecutionTarget, ExecutionStatus

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
        self.grid_level_manager = GridLevelManager(algorithm, debug=False)
        self.grid_position_manager = GridPositionManager(
            algorithm,
            self.grid_level_manager,  # 注入依赖
            debug=debug
        )

        # 初始化执行管理器
        # self.execution_manager = ExecutionManager(algorithm, debug=debug)
        self.execution_manager = ExecutionManager(algorithm, debug=True)

        # order_tracker 初始化为 None，稍后通过 setter 设置
        self._order_tracker = None

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

    def should_open_position(self, level: GridLevel) -> Optional[str]:
        """
        判断是否需要开仓（策略层协调）

        检查逻辑:
        1. 市场是否同时开盘（crypto 和 stock 都必须在交易时段）
        2. 是否有active ExecutionTarget（挂单检查 - ExecutionManager）
        3. 持仓是否达到目标（持仓检查 - GridPositionManager）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比
            level: 触发的网格线配置

        Returns:
            True if should open, False otherwise
        """
        crypto_symbol, stock_symbol = level.pair_symbol
        level_id = level.level_id

        # === 1. 挂单检查（ExecutionManager）===
        if self.execution_manager.has_active_execution(level):
            # self.algorithm.debug(f"⚠️ Level {level_id} has active execution, skipping open")
            return False

        # === 2. 持仓检查（GridPositionManager）===
        if self.grid_position_manager.has_reached_target(level):
            self.algorithm.debug(f"⚠️ Level {level_id} position reached target, skipping open")
            return False

        return True

    def should_close_position(self, level: GridLevel) -> bool:
        """
        判断是否需要平仓（策略层协调）

        检查逻辑:
        1. 市场是否同时开盘（crypto 和 stock 都必须在交易时段）
        2. 是否有对应的持仓（通过 get_grid_position）
        3. 是否有active ExecutionTarget（挂单检查 - ExecutionManager）

        Args:
            level: 触发的出场线配置 (EXIT level)

        Returns:
            True if should close, False otherwise
        """
        crypto_symbol, stock_symbol = level.pair_symbol

        # === 1. 检查是否有对应的持仓 ===
        position = self.grid_position_manager.get_grid_position(level)
        if not position:
            return False
        elif abs(position.quantity[0]) < 1e-8 and abs(position.quantity[1]) < 1e-8:
            return False

        # === 3. 挂单检查（ExecutionManager）===
        has_active = self.execution_manager.has_active_execution(level)
        if has_active:
            return False

        return True

    def _open_grid_position(self, level: GridLevel, spread_pct):
        """
        开仓 - 委托给执行层

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            level: 网格线配置
            spread_pct: 当前价差百分比
        """
        crypto_symbol, stock_symbol = level.pair_symbol

        # ✅ 计算目标数量（Strategy职责）
        position_size_pct = level.position_size_pct
        if level.direction == "SHORT_SPREAD":
            position_size_pct = -position_size_pct

        target_order_pair = self.algorithm.calculate_order_pair(
            crypto_symbol,
            stock_symbol,
            position_size_pct
        )

        # ✅ 计算增量数量（delta = 目标 - 当前持仓）
        grid_position = self.grid_position_manager.get_or_create_grid_position(level)
        current_leg1_qty, current_leg2_qty = grid_position.quantity

        delta_order_pair = {
            crypto_symbol: target_order_pair[crypto_symbol] - current_leg1_qty,
            stock_symbol: target_order_pair[stock_symbol] - current_leg2_qty
        }

        self.algorithm.debug(
            f"📥 _open_grid_position | ENTRY Level: {level.level_id} | "
            f"Current Position: {current_leg1_qty:.2f}/{current_leg2_qty:.2f} | "
            f"Delta: {delta_order_pair[crypto_symbol]:.2f}/{delta_order_pair[stock_symbol]:.2f} | "
            f"current Spread Pct: {spread_pct}"
        )

        # ✅ 构建执行目标
        execution_target = ExecutionTarget(
            pair_symbol=level.pair_symbol,
            grid_id=level.level_id,  # 人类可读标识（用于日志）
            level=level,  # GridLevel 对象（用于订单 tag = hash(level)）
            target_qty=delta_order_pair,
            expected_spread_pct=level.spread_pct,
            spread_direction=level.direction,  # 直接使用 LONG_SPREAD/SHORT_SPREAD
            algorithm=self.algorithm
        )

        # register execution in active target
        self.execution_manager.register_execution_target(execution_target)
        # ✅ 委托给执行层（完全交给 ExecutionManager）
        self.execution_manager.execute(execution_target)

    def _close_grid_position(self, exit_level: GridLevel, spread_pct):
        """
        平仓 - 委托给执行层

        根据 GridPosition 的实际持仓数量平仓

        Args:
            position: GridPosition 对象
            exit_level: 触发平仓的 EXIT GridLevel（用于生成 ExecutionTarget 的 grid_id）
            spread_pct: 当前价差百分比
        """
        position = self.grid_position_manager.get_grid_position(exit_level)
        pair_symbol = position.pair_symbol
        level_id = exit_level.level_id  # 使用 EXIT level 的 ID（而不是 position.grid_id）

        self.algorithm.debug(
            f"📤 _close_grid_position | EXIT Level: {level_id} | "
            f"ENTRY Position: {position.grid_id} | Qty: {position.quantity[0]:.2f}/{position.quantity[1]:.2f} | "
            f"current Spread Pct: {spread_pct}"
        )
        # 🐛 DEBUG: 打印 ExecutionTarget 初始化参数和持仓
        crypto_symbol, stock_symbol = pair_symbol
        crypto_holdings = self.algorithm.Portfolio[crypto_symbol].Quantity
        stock_holdings = self.algorithm.Portfolio[stock_symbol].Quantity
        self.algorithm.debug(
            f"expected_spread_pct={exit_level.spread_pct:.4f} | spread_direction={exit_level.direction} | "
            f"Portfolio Holdings: {crypto_symbol.value}={crypto_holdings:.4f}, {stock_symbol.value}={stock_holdings:.4f}"
        )
        
        # ✅ 构建执行目标（平仓目标 = 0）
        target_order_pair = {
            exit_level.pair_symbol[0]: -position.quantity[0],
            exit_level.pair_symbol[1]: -position.quantity[1]
        }


        # 直接使用 exit_level.direction（已在初始化时设置为正确的平仓方向）
        execution_target = ExecutionTarget(
            pair_symbol=pair_symbol,
            grid_id=level_id,  # 人类可读标识（用于日志）
            level=exit_level,  # GridLevel 对象（用于订单 tag）
            target_qty=target_order_pair,
            expected_spread_pct=exit_level.spread_pct,
            spread_direction=exit_level.direction,  # 直接使用 EXIT level 的方向
            algorithm=self.algorithm
        )

        self.execution_manager.register_execution_target(execution_target)
        # ✅ 委托给执行层
        self.execution_manager.execute(execution_target)

    def on_spread_update(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float):
        """
        处理价差更新 - 网格交易逻辑（简化版）

        核心逻辑：
        1. 获取当前活跃的网格线（唯一的 ENTRY 或 EXIT level）
        2. 如果是 ENTRY，检查是否应该开仓
        3. 如果是 EXIT，检查是否应该平仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: Spread 百分比
        """
        # 获取当前活跃的网格线（唯一）
        level = self.grid_level_manager.get_active_level(pair_symbol, spread_pct)

        if not level:
            # 没有活跃的网格线
            return

        # 根据 level 类型执行相应操作
        if level.type == "ENTRY":
            # 检查是否应该开仓
            if self.should_open_position(level):
                self._open_grid_position(level, spread_pct)

        elif level.type == "EXIT":
            # 检查是否应该平仓
            if self.should_close_position(level):
                self._close_grid_position(level, spread_pct)
                
    def on_data(self, data):
        """
        处理数据更新 - 重新触发 active ExecutionTargets

        每个 tick 执行：
        重新触发：重新检查 orderbook 深度并尝试提交订单

        Args:
            data: Slice 数据
        """
        # 遍历所有 active targets，重新触发执行
        for target in list(self.execution_manager.active_targets.values()):
            if target.is_active():
                self.execution_manager.execute(target)
                
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

        # 调用 GridPositionManager 的订单事件处理（更新网格持仓）
        self.grid_position_manager.on_order_event(order_event)
        
        # 调用 ExecutionManager 的订单事件处理（更新 ExecutionTarget）
        self.execution_manager.on_order_event(order_event)



    # ============================================================================
    #                      统计和报告
    # ============================================================================
    
    @property
    def order_tracker(self):
        """获取 order_tracker"""
        return self._order_tracker

    @order_tracker.setter
    def order_tracker(self, value):
        """设置 order_tracker 并同步到 ExecutionManager"""
        self._order_tracker = value
        self.execution_manager.order_tracker = value


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
