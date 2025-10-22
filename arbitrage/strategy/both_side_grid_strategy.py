"""
Both Side Grid Strategy - 双边网格套利策略

使用GridStrategy框架实现双向交易:
- Long Crypto + Short Stock (entry <= -1%, exit >= 2%)
- Short Crypto + Long Stock (entry >= 3%, exit <= -0.9%)
- 利用Grid框架的position tracking、profitability validation和execution management
"""
from AlgorithmImports import *
from typing import Tuple, Optional
from strategy.grid_strategy import GridStrategy
from strategy.grid_models import GridLevel


class BothSideGridStrategy(GridStrategy):
    """
    双边网格套利策略 - 使用Grid框架实现

    特点:
    - 使用GridStrategy框架实现双向网格策略
    - Long Crypto Direction:
      - Entry: spread <= -1% (可配置)
      - Exit: spread >= 2% (可配置)
    - Short Crypto Direction:
      - Entry: spread >= 3% (可配置)
      - Exit: spread <= -0.9% (可配置)
    - 利用Grid框架的profitability validation
    - 自动防止冲突持仓（不能同时做多和做空）
    """

    def __init__(self, algorithm: QCAlgorithm,
                 long_crypto_entry: float = -0.01,
                 long_crypto_exit: float = 0.02,
                 short_crypto_entry: float = 0.03,
                 short_crypto_exit: float = -0.009,
                 position_size_pct: float = 0.25,
                 state_persistence=None):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            long_crypto_entry: Long crypto开仓阈值 (负数, spread <= threshold 时开仓, 默认-1%)
            long_crypto_exit: Long crypto平仓阈值 (正数, spread >= threshold 时平仓, 默认2%)
            short_crypto_entry: Short crypto开仓阈值 (正数, spread >= threshold 时开仓, 默认3%)
            short_crypto_exit: Short crypto平仓阈值 (负数, spread <= threshold 时平仓, 默认-0.9%)
            position_size_pct: 仓位大小百分比 (默认25%)
            state_persistence: 状态持久化适配器 (可选)
        """
        # 调用父类GridStrategy初始化
        super().__init__(algorithm, debug=False, state_persistence=state_persistence)

        self.long_crypto_entry = long_crypto_entry
        self.long_crypto_exit = long_crypto_exit
        self.short_crypto_entry = short_crypto_entry
        self.short_crypto_exit = short_crypto_exit
        self.position_size_pct = position_size_pct

        # 持仓时间追踪 (与原始策略保持一致)
        self.open_times = {}  # {(pair_symbol, direction): open_time}
        self.holding_times = []  # 每次回转交易的持仓时间 (timedelta)

        # GridOrderTracker (可选，从外部注入)
        self.order_tracker = None

        self.algorithm.debug(
            f"BothSideGridStrategy initialized | "
            f"Long Crypto: entry <= {self.long_crypto_entry*100:.2f}%, exit >= {self.long_crypto_exit*100:.2f}% | "
            f"Short Crypto: entry >= {self.short_crypto_entry*100:.2f}%, exit <= {self.short_crypto_exit*100:.2f}% | "
            f"Position: {self.position_size_pct*100:.1f}%"
        )

    def initialize_pair(self, pair_symbol: Tuple[Symbol, Symbol]):
        """
        Initialize grid levels for a trading pair

        Creates 4 grid levels:
        1. Long Crypto Entry (LONG_SPREAD)
        2. Long Crypto Exit (SHORT_SPREAD)
        3. Short Crypto Entry (SHORT_SPREAD)
        4. Short Crypto Exit (LONG_SPREAD)

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
        """
        crypto_symbol, stock_symbol = pair_symbol

        # ===== Long Crypto Grid Levels =====
        # Entry: Buy crypto + Short stock when spread <= -1%
        long_crypto_entry_level = GridLevel(
            level_id="entry_long_crypto",
            type="ENTRY",
            pair_symbol=pair_symbol,
            spread_pct=self.long_crypto_entry,
            paired_exit_level_id="exit_long_crypto",
            position_size_pct=self.position_size_pct,
            direction="LONG_SPREAD"
        )

        # Exit: Sell crypto + Buy stock when spread >= 2%
        long_crypto_exit_level = GridLevel(
            level_id="exit_long_crypto",
            type="EXIT",
            pair_symbol=pair_symbol,
            spread_pct=self.long_crypto_exit,
            direction="SHORT_SPREAD"  # 平仓方向：卖crypto + 买stock
        )

        # ===== Short Crypto Grid Levels =====
        # Entry: Sell crypto + Buy stock when spread >= 3%
        short_crypto_entry_level = GridLevel(
            level_id="entry_short_crypto",
            type="ENTRY",
            pair_symbol=pair_symbol,
            spread_pct=self.short_crypto_entry,
            paired_exit_level_id="exit_short_crypto",
            position_size_pct=self.position_size_pct,
            direction="SHORT_SPREAD"
        )

        # Exit: Buy crypto + Short stock when spread <= -0.9%
        short_crypto_exit_level = GridLevel(
            level_id="exit_short_crypto",
            type="EXIT",
            pair_symbol=pair_symbol,
            spread_pct=self.short_crypto_exit,
            direction="LONG_SPREAD"  # 平仓方向：买crypto + 卖stock
        )

        # 使用GridStrategy的setup方法配置grid levels
        # 这会自动进行profitability validation
        try:
            self._setup_grid_levels(
                pair_symbol,
                [
                    long_crypto_entry_level,
                    long_crypto_exit_level,
                    short_crypto_entry_level,
                    short_crypto_exit_level
                ]
            )

            self.algorithm.debug(
                f"✅ Both-side grid levels initialized for {crypto_symbol.value} <-> {stock_symbol.value} | "
                f"Long Entry: {self.long_crypto_entry*100:.2f}%, Long Exit: {self.long_crypto_exit*100:.2f}% | "
                f"Short Entry: {self.short_crypto_entry*100:.2f}%, Short Exit: {self.short_crypto_exit*100:.2f}%"
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
