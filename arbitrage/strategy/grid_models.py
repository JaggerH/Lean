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
import hashlib

if TYPE_CHECKING:
    from .execution_models import OrderGroup, OrderGroupStatus


@dataclass
class GridLevel:
    """
    网格线定义

    描述一个进场线或出场线的触发条件和仓位配置
    """
    level_id: str  # 唯一ID（如 "entry_long_crypto" 或 "grid_level_1"）
    type: str  # "ENTRY" 或 "EXIT" (renamed from level_type)

    # 交易对
    pair_symbol: Tuple[Symbol, Symbol]  # (crypto_symbol, stock_symbol)

    # 触发条件
    spread_pct: float  # 触发价差百分比（如 -0.01 表示 -1%）（renamed from trigger_spread_pct）

    # 配对的出场线（如果是进场线）
    paired_exit_level_id: Optional[str] = None

    # 仓位配置
    position_size_pct: float = 0.25  # 仓位大小百分比（默认25%）

    # 方向（对于双向网格）
    direction: str = "LONG_SPREAD"  # "LONG_SPREAD" 或 "SHORT_SPREAD"

    # 验证状态（由 GridLevelManager 填充）
    is_valid: bool = True
    validation_error: Optional[str] = None
    expected_profit_pct: float = 0.0  # 预期盈利百分比
    estimated_fee_pct: float = 0.0   # 预估手续费百分比

    def __post_init__(self):
        """验证基本参数"""
        if self.type not in ["ENTRY", "EXIT"]:
            raise ValueError(f"Invalid type: {self.type}, must be 'ENTRY' or 'EXIT'")

        if self.direction not in ["LONG_SPREAD", "SHORT_SPREAD"]:
            raise ValueError(f"Invalid direction: {self.direction}")

        if self.position_size_pct <= 0 or self.position_size_pct > 1:
            raise ValueError(f"Invalid position_size_pct: {self.position_size_pct}, must be in (0, 1]")

    def __hash__(self):
        """
        基于网格线本质属性计算 hash（跨重启稳定版 - 使用确定性哈希）

        使用字符串标识符和 MD5 哈希确保跨程序重启的哈希稳定性：
        - pair_symbol: 使用 (Symbol.value, Symbol.id.market) 元组
        - type: ENTRY/EXIT
        - spread_pct: 触发价差（本质属性）
        - direction: 方向

        不包含：
        - level_id: 仅用于人类可读标识
        - position_size_pct: 可动态调整的执行参数
        - paired_exit_level_id: 配对关系由 Manager 维护
        - 运行时状态字段（is_valid 等）

        注意：
        - Symbol 对象在每次重启时内存地址不同，导致 hash 不稳定
        - Python 的 hash() 函数默认启用了 hash randomization（安全特性）
        - 使用 MD5 生成确定性哈希，保证相同输入始终产生相同输出
        """
        # 构造用于哈希的字符串
        hash_string = (
            f"{self.pair_symbol[0].value}|"
            f"{str(self.pair_symbol[0].id.market)}|"
            f"{self.pair_symbol[1].value}|"
            f"{str(self.pair_symbol[1].id.market)}|"
            f"{self.type}|"
            f"{self.spread_pct}|"
            f"{self.direction}"
        )

        # 使用 MD5 生成确定性哈希（取前8字节转为整数）
        hash_bytes = hashlib.md5(hash_string.encode('utf-8')).digest()
        result_hash = int.from_bytes(hash_bytes[:8], byteorder='big', signed=True)

        return result_hash

    def __eq__(self, other):
        """
        基于网格线本质属性判断相等（跨重启稳定版）

        使用字符串标识符比较，保证：
        - 相同触发条件的网格线被视为同一个
        - level_id 改名不影响相等性判断
        - position_size_pct 调整不影响相等性判断
        - 跨程序重启时相同逻辑网格线仍被判断为相等

        注意：
        - 必须与 __hash__() 保持一致的比较逻辑
        - 使用 Symbol.value + Symbol.id.market 而非 Symbol 对象
        """
        if not isinstance(other, GridLevel):
            return False
        return (
            self.pair_symbol[0].value == other.pair_symbol[0].value and
            str(self.pair_symbol[0].id.market) == str(other.pair_symbol[0].id.market) and
            self.pair_symbol[1].value == other.pair_symbol[1].value and
            str(self.pair_symbol[1].id.market) == str(other.pair_symbol[1].id.market) and
            self.type == other.type and
            self.spread_pct == other.spread_pct and
            self.direction == other.direction
        )

    def __repr__(self):
        """增强调试输出（同时显示 level_id 和 hash）"""
        return (
            f"GridLevel(id='{self.level_id}', hash={hash(self)}, "
            f"type={self.type}, spread={self.spread_pct*100:.2f}%)"
        )


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
    5. grid_id 直接使用 level.level_id（不再包含交易对前缀）
    6. pair_symbol 通过 level.pair_symbol 获取（避免冗余存储）
    """
    level: GridLevel  # 关联的网格线配置

    # 实际持仓（累计成交）- 内部存储
    # leg1 = pair_symbol[0], leg2 = pair_symbol[1]
    _leg1_qty: float = 0.0  # 第一条腿的数量（带符号）
    _leg2_qty: float = 0.0  # 第二条腿的数量（带符号）

    @property
    def pair_symbol(self) -> Tuple[Symbol, Symbol]:
        """
        获取交易对（从关联的 GridLevel 获取）

        Returns:
            (crypto_symbol, stock_symbol) 元组
        """
        return self.level.pair_symbol

    @property
    def grid_id(self) -> str:
        """
        获取网格线ID（直接使用 level_id）

        Returns:
            level_id 字符串
        """
        return self.level.level_id

    @property
    def quantity(self) -> Tuple[float, float]:
        """
        获取持仓数量元组

        Returns:
            (leg1_qty, leg2_qty) 对应 (pair_symbol[0], pair_symbol[1])
        """
        return (self._leg1_qty, self._leg2_qty)

    def update_filled_qty(self, leg1_qty: float, leg2_qty: float):
        """
        更新实际成交数量（累加）

        Args:
            leg1_qty: 第一条腿数量变化（带符号）
            leg2_qty: 第二条腿数量变化（带符号）
        """
        self._leg1_qty += leg1_qty
        self._leg2_qty += leg2_qty

