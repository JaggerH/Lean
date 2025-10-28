"""
Long Crypto Grid Strategy - 使用Grid框架重构的做多加密货币策略

使用GridStrategy框架重构LongCryptoStrategy:
- 单一入场线 + 单一出场线
- 仅支持 Long Crypto + Short Stock
- 保持与原始LongCryptoStrategy相同的行为
- 利用Grid框架的position tracking和validation
"""
from AlgorithmImports import *
from typing import Tuple, Optional
from strategy.grid_strategy import GridStrategy
from strategy.grid_models import GridLevel


class LongCryptoGridStrategy(GridStrategy):
    """
    做多加密货币网格策略 - 使用Grid框架重构

    特点:
    - 使用GridStrategy框架实现单一grid策略
    - Entry: spread <= -1% (可配置)
    - Exit: spread >= 2% (可配置)
    - Direction: 仅 Long Crypto + Short Stock
    - 利用Grid框架的profitability validation
    """

    def __init__(self, algorithm: QCAlgorithm,
                 entry_threshold: float = -0.01,
                 exit_threshold: float = 0.02,
                 position_size_pct: float = 0.25):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            entry_threshold: 开仓阈值 (负数, spread <= entry_threshold 时开仓, 默认-1%)
            exit_threshold: 平仓阈值 (正数, spread >= exit_threshold 时平仓, 默认2%)
            position_size_pct: 仓位大小百分比 (默认25%)

        Note:
            状态持久化现在由 MonitoringContext 通过事件机制处理，
            不再需要通过构造函数注入
        """
        # 调用父类GridStrategy初始化
        super().__init__(algorithm, debug=False)

        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.position_size_pct = position_size_pct

        # 持仓时间追踪 (与原始策略保持一致)
        self.open_times = {}  # {pair_symbol: open_time}
        self.holding_times = []  # 每次回转交易的持仓时间 (timedelta)

        # GridOrderTracker (可选，从外部注入)
        self.order_tracker = None

        self.algorithm.debug(
            f"LongCryptoGridStrategy initialized | "
            f"Entry: spread <= {self.entry_threshold*100:.2f}% | "
            f"Exit: spread >= {self.exit_threshold*100:.2f}% | "
            f"Position: {self.position_size_pct*100:.1f}%"
        )

    def initialize_pair(self, pair_symbol: Tuple[Symbol, Symbol]):
        """
        Initialize grid levels for a trading pair

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 创建单一entry/exit grid level
        entry_level = GridLevel(
            level_id="entry_long_crypto",
            type="ENTRY",
            pair_symbol=pair_symbol,
            spread_pct=self.entry_threshold,
            paired_exit_level_id="exit_long_crypto",
            position_size_pct=self.position_size_pct,
            direction="LONG_SPREAD"
        )

        exit_level = GridLevel(
            level_id="exit_long_crypto",
            type="EXIT",
            pair_symbol=pair_symbol,
            spread_pct=self.exit_threshold,
            direction="SHORT_SPREAD"  # 平仓方向：卖crypto + 买stock
        )

        # 使用GridStrategy的setup方法配置grid levels
        # 这会自动进行profitability validation
        try:
            self._setup_grid_levels(
                pair_symbol,
                [entry_level, exit_level]
            )

            self.algorithm.debug(
                f"✅ Grid levels initialized for {crypto_symbol.value} <-> {stock_symbol.value} | "
                f"Entry: {self.entry_threshold*100:.2f}%, Exit: {self.exit_threshold*100:.2f}%"
            )

        except ValueError as e:
            # Profitability validation failed
            self.algorithm.error(
                f"❌ Grid validation failed for {crypto_symbol.value} <-> {stock_symbol.value}: {e}"
            )
            raise

    def get_statistics(self) -> dict:
        """
        获取策略统计信息 (与原始策略保持一致)

        Returns:
            dict: 包含holding_times等统计信息
        """
        avg_holding_time = None
        if self.holding_times:
            total_seconds = sum(ht.total_seconds() for ht in self.holding_times)
            avg_holding_time = total_seconds / len(self.holding_times)

        return {
            'total_round_trips': len(self.holding_times),
            'holding_times': self.holding_times,
            'avg_holding_time_seconds': avg_holding_time,
            'open_positions': len(self.open_times)
        }
