"""
Grid Trading Models - 网格交易核心数据类

定义网格交易的核心数据结构：
- GridLevel: 网格线配置（进场线/出场线）
- GridPosition: 单个网格线的持仓信息
- OrderGroup: 订单组（一次开仓/平仓操作）
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from datetime import datetime
from AlgorithmImports import Symbol


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
class OrderGroup:
    """
    订单组（一次开仓/平仓操作）

    一个订单组包含一次交易中的多个订单（通常是2个：crypto + stock）
    追踪预期价差 vs 实际价差，用于优化执行策略
    """
    group_id: str  # 唯一ID（格式：{pair_symbol}_{grid_id}_{timestamp}）
    order_ids: List[int] = field(default_factory=list)  # 包含的订单ID

    # 价差追踪
    expected_spread_pct: float = 0.0  # 预期执行价差（触发时的价差）
    actual_spread_pct: Optional[float] = None  # 实际执行价差（成交后计算）

    # 成交数量追踪
    crypto_filled_qty: float = 0.0  # Crypto 成交数量（带符号）
    stock_filled_qty: float = 0.0   # Stock 成交数量（带符号）

    # 时间戳
    submit_time: Optional[datetime] = None  # 订单提交时间
    fill_time: Optional[datetime] = None    # 完全成交时间

    # 状态
    status: str = "SUBMITTED"  # SUBMITTED, PARTIALLY_FILLED, FILLED, FAILED, PARTIALLY_FAILED

    def is_filled(self) -> bool:
        """判断订单组是否完全成交"""
        return self.status == "FILLED"

    def update_filled_qty(self, symbol, fill_qty: float):
        """
        更新成交数量

        Args:
            symbol: Symbol 对象（用于判断是 crypto 还是 stock）
            fill_qty: 成交数量（带符号）
        """
        # 注意：这里需要外部调用者判断 symbol 类型
        # 简化实现：假设调用者已经分类
        pass


@dataclass
class GridPosition:
    """
    单个网格线的持仓信息

    追踪一个网格线的实际持仓、以及所有相关的订单组

    注意：不再存储 target_crypto_qty/target_stock_qty，因为：
    1. 套利交易的目标是市值而非固定数量
    2. 价格变动导致固定数量不合理
    3. 目标市值由 can_open_more() 实时计算
    """
    grid_id: str  # 网格线唯一ID（格式：{pair_symbol}_{level_id}）
    pair_symbol: Tuple[Symbol, Symbol]  # (crypto_symbol, stock_symbol)
    level: GridLevel  # 关联的网格线配置

    # 实际持仓（累计成交）
    actual_crypto_qty: float = 0.0  # 实际 crypto 数量（带符号）
    actual_stock_qty: float = 0.0   # 实际 stock 数量（带符号）

    # 订单组追踪（支持多次开仓）
    order_groups: List[OrderGroup] = field(default_factory=list)

    # 状态
    status: str = "OPEN"  # OPEN, PARTIALLY_FILLED, FILLED, CLOSING, CLOSED, FAILED

    # 时间戳
    open_time: Optional[datetime] = None   # 首次开仓时间
    close_time: Optional[datetime] = None  # 完全平仓时间

    # 统计信息
    total_orders: int = 0  # 总订单数（包含所有订单组）
    filled_orders: int = 0  # 已成交订单数

    def add_order_group(self, order_group: OrderGroup):
        """添加订单组"""
        self.order_groups.append(order_group)
        self.total_orders += len(order_group.order_ids)

        # 更新首次开仓时间
        if self.open_time is None and order_group.submit_time:
            self.open_time = order_group.submit_time

    def update_filled_qty(self, crypto_qty: float, stock_qty: float):
        """
        更新实际成交数量（累加）

        Args:
            crypto_qty: Crypto 数量变化（带符号）
            stock_qty: Stock 数量变化（带符号）
        """
        self.actual_crypto_qty += crypto_qty
        self.actual_stock_qty += stock_qty

        # 更新状态
        self._update_status()

    def _update_status(self):
        """
        根据订单组状态更新 GridPosition 状态

        不再依赖 target 数量，而是根据订单组的成交情况判断
        """
        if not self.order_groups:
            self.status = "OPEN"
            return

        # 检查最新订单组的状态
        latest_group = self.order_groups[-1]

        if latest_group.status == "FILLED":
            self.status = "FILLED"
        elif latest_group.status == "PARTIALLY_FILLED":
            self.status = "PARTIALLY_FILLED"
        elif latest_group.status == "FAILED":
            self.status = "FAILED"
        elif latest_group.status == "PARTIALLY_FAILED":
            self.status = "PARTIALLY_FILLED"  # 部分失败视为部分成交
        else:
            self.status = "OPEN"

    def is_filled(self) -> bool:
        """判断是否完全成交"""
        return self.status == "FILLED"

    def is_closed(self) -> bool:
        """判断是否已平仓"""
        return self.status == "CLOSED"


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


def generate_order_group_id(grid_id: str, timestamp: datetime) -> str:
    """
    生成订单组唯一ID

    格式：{grid_id}_{timestamp}

    Args:
        grid_id: 网格线ID
        timestamp: 时间戳

    Returns:
        订单组ID字符串

    Example:
        >>> generate_order_group_id("TSLAxUSD_TSLA_entry", datetime(2025, 1, 15, 12, 0, 0))
        "TSLAxUSD_TSLA_entry_20250115_120000"
    """
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    return f"{grid_id}_{timestamp_str}"
