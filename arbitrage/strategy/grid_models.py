"""
Grid Trading Models - 网格交易核心数据类

定义网格交易的核心数据结构：
- GridLevel: 网格线配置（进场线/出场线）
- GridPosition: 单个网格线的持仓信息

注意：OrderGroup 已移至 execution_models.py（属于执行层）
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime
from AlgorithmImports import Symbol

if TYPE_CHECKING:
    from .execution_models import OrderGroup, OrderGroupStatus


@dataclass
class GridLevel:
    """
    网格线定义

    描述一个进场线或出场线的触发条件和仓位配置
    """
    level_id: str  # 唯一ID（如 "entry_long_crypto" 或 "grid_level_1"）
    level_type: str  # "ENTRY" 或 "EXIT"

    # 触发条件
    trigger_spread_pct: float  # 触发价差百分比（如 -0.01 表示 -1%）

    # 配对的出场线（如果是进场线）
    paired_exit_level_id: Optional[str] = None

    # 仓位配置
    position_size_pct: float = 0.25  # 仓位大小百分比（默认25%）

    # 方向（对于双向网格）
    direction: str = "LONG_CRYPTO"  # "LONG_CRYPTO" 或 "SHORT_CRYPTO"

    # 验证状态（由 GridLevelManager 填充）
    is_valid: bool = True
    validation_error: Optional[str] = None
    expected_profit_pct: float = 0.0  # 预期盈利百分比
    estimated_fee_pct: float = 0.0   # 预估手续费百分比

    def __post_init__(self):
        """验证基本参数"""
        if self.level_type not in ["ENTRY", "EXIT"]:
            raise ValueError(f"Invalid level_type: {self.level_type}, must be 'ENTRY' or 'EXIT'")

        if self.direction not in ["LONG_CRYPTO", "SHORT_CRYPTO"]:
            raise ValueError(f"Invalid direction: {self.direction}")

        if self.position_size_pct <= 0 or self.position_size_pct > 1:
            raise ValueError(f"Invalid position_size_pct: {self.position_size_pct}, must be in (0, 1]")


@dataclass
class GridPosition:
    """
    单个网格线的持仓信息

    纯粹的持仓记录，只追踪累计成交数量

    注意：
    1. 不存储 order_groups（由 ExecutionTarget 管理）
    2. 不存储 target 数量（目标市值由 GridLevelManager 实时计算）
    3. 只负责累计持仓数量的记录
    4. 不存储状态和时间戳（由外部逻辑判断）
    """
    grid_id: str  # 网格线唯一ID（格式：{pair_symbol}_{level_id}）
    pair_symbol: Tuple[Symbol, Symbol]  # (crypto_symbol, stock_symbol)
    level: GridLevel  # 关联的网格线配置

    # 实际持仓（累计成交）- 内部存储
    _crypto_qty: float = 0.0  # 实际 crypto 数量（带符号）
    _stock_qty: float = 0.0   # 实际 stock 数量（带符号）

    @property
    def quantity(self) -> Tuple[float, float]:
        """
        获取持仓数量元组

        Returns:
            (crypto_qty, stock_qty)
        """
        return (self._crypto_qty, self._stock_qty)

    def update_filled_qty(self, crypto_qty: float, stock_qty: float):
        """
        更新实际成交数量（累加）

        Args:
            crypto_qty: Crypto 数量变化（带符号）
            stock_qty: Stock 数量变化（带符号）
        """
        self._crypto_qty += crypto_qty
        self._stock_qty += stock_qty


# ============================================================================
#                      辅助函数
# ============================================================================

def generate_grid_id(pair_symbol: Tuple[Symbol, Symbol], level_id: str) -> str:
    """
    生成网格线唯一ID

    格式：{crypto_ticker}_{stock_ticker}_{level_id}

    Args:
        pair_symbol: (crypto_symbol, stock_symbol)
        level_id: 网格线配置ID

    Returns:
        网格线ID字符串

    Example:
        >>> generate_grid_id((TSLAxUSD, TSLA), "entry_long_crypto")
        "TSLAxUSD_TSLA_entry_long_crypto"
    """
    crypto_symbol, stock_symbol = pair_symbol
    crypto_ticker = crypto_symbol.value.replace("/", "").replace(" ", "")
    stock_ticker = stock_symbol.value.replace("/", "").replace(" ", "")
    return f"{crypto_ticker}_{stock_ticker}_{level_id}"
