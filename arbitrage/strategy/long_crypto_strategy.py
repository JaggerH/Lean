"""
Long Crypto Strategy - 做多加密货币套利策略

继承 BaseStrategy 的开/平仓逻辑和位置追踪
- 开仓条件: spread <= -1% 且无持仓
- 平仓条件: spread >= 2% 且有持仓
- 方向限制: 仅 long crypto + short stock
"""
from AlgorithmImports import *
from typing import Tuple
from strategy.base_strategy import BaseStrategy


class LongCryptoStrategy(BaseStrategy):
    """
    做多加密货币套利策略 - 继承 BaseStrategy

    特点:
    - 继承 BaseStrategy 的开/平仓逻辑和位置追踪
    - 开仓条件: spread <= -1% 且无持仓
    - 平仓条件: spread >= 2% 且有持仓
    - 方向限制: 仅 long crypto + short stock
    """

    def __init__(self, algorithm: QCAlgorithm,
                 entry_threshold: float = -0.01,
                 exit_threshold: float = 0.02,
                 position_size_pct: float = 0.25,
                 state_persistence=None):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            entry_threshold: 开仓阈值 (负数, spread <= entry_threshold 时开仓, 默认-1%)
            exit_threshold: 平仓阈值 (正数, spread >= exit_threshold 时平仓, 默认2%)
            position_size_pct: 仓位大小百分比 (默认25%)
            state_persistence: 状态持久化适配器 (可选)
        """
        # 调用父类初始化 (debug=False, state_persistence)
        super().__init__(algorithm, debug=False, state_persistence=state_persistence)

        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.position_size_pct = position_size_pct

        # 持仓时间追踪
        self.open_times = {}  # {pair_symbol: open_time}
        self.holding_times = []  # 每次回转交易的持仓时间 (timedelta)

        self.algorithm.debug(
            f"LongCryptoStrategy initialized | "
            f"Entry: spread <= {self.entry_threshold*100:.2f}% | "
            f"Exit: spread >= {self.exit_threshold*100:.2f}% | "
            f"Position: {self.position_size_pct*100:.1f}%"
        )

    def on_spread_update(self, pair_symbol: Tuple[Symbol, Symbol], spread_pct: float):
        """
        处理spread更新 - 使用 BaseStrategy 的方法判断开/平仓

        Args:
            pair_symbol: (crypto_symbol, stock_symbol) 交易对
            spread_pct: Spread百分比
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 使用 BaseStrategy 的方法检查是否应该开/平仓
        can_open = self._should_open_position(crypto_symbol, stock_symbol, self.position_size_pct)
        can_close = self._should_close_position(crypto_symbol, stock_symbol)


        # 开仓逻辑: spread <= entry_threshold (负数) 且可以开仓
        if can_open and spread_pct <= self.entry_threshold:
            tickets = self._open_position(pair_symbol, spread_pct, self.position_size_pct)
            if tickets:
                self.open_times[pair_symbol] = self.algorithm.time

        # 平仓逻辑: spread >= exit_threshold (正数) 且可以平仓
        elif can_close and spread_pct >= self.exit_threshold:
            tickets = self._close_position(pair_symbol, spread_pct)
            if tickets:
                # 计算持仓时间
                if pair_symbol in self.open_times:
                    holding_time = self.algorithm.time - self.open_times[pair_symbol]
                    self.holding_times.append(holding_time)
                    del self.open_times[pair_symbol]
