"""
Execution Models - 执行层数据模型

定义执行层的核心数据结构：
- ExecutionStatus: 执行状态枚举
- ExecutionTarget: 执行目标（Strategy传递给Executor的参数）
"""
from dataclasses import dataclass, field
from typing import Tuple, Dict, Optional, TYPE_CHECKING
from enum import Enum
from datetime import datetime
from AlgorithmImports import Symbol

if TYPE_CHECKING:
    from .grid_position_manager import GridPositionManager


class ExecutionStatus(Enum):
    """
    执行状态枚举

    状态流转:
    PENDING → EXECUTING → COMPLETED/FAILED
    """
    PENDING = "PENDING"         # 待执行
    EXECUTING = "EXECUTING"     # 执行中（订单已提交）
    COMPLETED = "COMPLETED"     # 已完成
    FAILED = "FAILED"          # 失败


@dataclass
class ExecutionTarget:
    """
    执行目标 - GridStrategy传递给ExecutionManager的参数（有状态）

    包含目标数量、预期价差、方向等信息
    通过依赖注入grid_position_manager来查询当前持仓

    Attributes:
        pair_symbol: (crypto_symbol, stock_symbol)
        grid_id: 网格线ID
        target_qty: 目标数量字典 {Symbol: float}（从calculate_order_pair返回）
        expected_spread_pct: 预期价差百分比
        spread_direction: "LONG_CRYPTO" or "SHORT_CRYPTO"
        grid_position_manager: GridPositionManager实例（依赖注入）
        status: 执行状态（默认 PENDING）
        created_time: 创建时间
        order_group_id: 关联的订单组ID
    """
    pair_symbol: Tuple[Symbol, Symbol]
    grid_id: str
    target_qty: Dict[Symbol, float]  # 从calculate_order_pair返回
    expected_spread_pct: float
    spread_direction: str  # "LONG_CRYPTO" or "SHORT_CRYPTO"
    grid_position_manager: 'GridPositionManager'  # 依赖注入

    # 状态字段
    status: ExecutionStatus = field(default=ExecutionStatus.PENDING)
    created_time: Optional[datetime] = field(default=None)
    order_group_id: Optional[str] = field(default=None)

    def get_current_qty(self) -> Dict[Symbol, float]:
        """
        获取当前持仓数量

        Returns:
            {crypto_symbol: qty, stock_symbol: qty}
        """
        crypto_symbol, stock_symbol = self.pair_symbol

        position = self.grid_position_manager.get_grid_position(
            self.pair_symbol, self.grid_id
        )

        if not position:
            return {crypto_symbol: 0.0, stock_symbol: 0.0}

        return {
            crypto_symbol: position.actual_crypto_qty,
            stock_symbol: position.actual_stock_qty
        }

    def get_remaining_qty(self) -> Dict[Symbol, float]:
        """
        计算剩余需要执行的数量

        Returns:
            {crypto_symbol: remaining_qty, stock_symbol: remaining_qty}
        """
        current_qty = self.get_current_qty()
        crypto_symbol, stock_symbol = self.pair_symbol

        return {
            crypto_symbol: self.target_qty[crypto_symbol] - current_qty[crypto_symbol],
            stock_symbol: self.target_qty[stock_symbol] - current_qty[stock_symbol]
        }

    def get_execution_key(self) -> Tuple[Tuple[Symbol, Symbol], str]:
        """
        获取执行唯一键

        Returns:
            (pair_symbol, grid_id) 作为唯一标识
        """
        return (self.pair_symbol, self.grid_id)

    def is_pending(self) -> bool:
        """是否为待执行状态"""
        return self.status == ExecutionStatus.PENDING

    def is_executing(self) -> bool:
        """是否为执行中状态"""
        return self.status == ExecutionStatus.EXECUTING

    def is_completed(self) -> bool:
        """是否已完成"""
        return self.status == ExecutionStatus.COMPLETED

    def is_failed(self) -> bool:
        """是否失败"""
        return self.status == ExecutionStatus.FAILED
