"""
Long Crypto Strategy - 做多加密货币套利策略

继承 BaseStrategy 的开/平仓逻辑和位置追踪
- 开仓条件: spread <= -1% 且无持仓
- 平仓条件: spread >= 2% 且有持仓
- 方向限制: 仅 long crypto + short stock
"""
from AlgorithmImports import *
from strategy.base_strategy import BaseStrategy
from spread_manager import SpreadManager


class LongCryptoStrategy(BaseStrategy):
    """
    做多加密货币套利策略 - 继承 BaseStrategy

    特点:
    - 继承 BaseStrategy 的开/平仓逻辑和位置追踪
    - 开仓条件: spread <= -1% 且无持仓
    - 平仓条件: spread >= 2% 且有持仓
    - 方向限制: 仅 long crypto + short stock
    """

    def __init__(self, algorithm: QCAlgorithm, spread_manager: SpreadManager = None,
                 entry_threshold: float = -0.01,
                 exit_threshold: float = 0.02,
                 position_size_pct: float = 0.25,
                 state_persistence=None):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            spread_manager: SpreadManager实例 (可选)
            entry_threshold: 开仓阈值 (负数, spread <= entry_threshold 时开仓, 默认-1%)
            exit_threshold: 平仓阈值 (正数, spread >= exit_threshold 时平仓, 默认2%)
            position_size_pct: 仓位大小百分比 (默认25%)
            state_persistence: 状态持久化适配器 (可选)
        """
        # 调用父类初始化 (debug=False, state_persistence)
        super().__init__(algorithm, debug=False, state_persistence=state_persistence)

        self.spread_manager = spread_manager
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

    def on_spread_update(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                        spread_pct: float, crypto_quote, stock_quote,
                        crypto_bid_price: float, crypto_ask_price: float):
        """
        处理spread更新 - 使用 BaseStrategy 的方法判断开/平仓

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            spread_pct: Spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
            crypto_bid_price: 我们的卖出限价 (未使用)
            crypto_ask_price: 我们的买入限价 (未使用)
        """
        pair_symbol = (crypto_symbol, stock_symbol)

        # 使用 BaseStrategy 的方法检查是否应该开/平仓
        can_open = self._should_open_position(crypto_symbol, stock_symbol)
        can_close = self._should_close_position(crypto_symbol, stock_symbol)

        # 🔍 调试日志：仅在接近阈值时输出（±0.5%范围内）
        # if abs(spread_pct - self.entry_threshold) < 0.005 or abs(spread_pct - self.exit_threshold) < 0.005:
        #     self.algorithm.debug(
        #         f"🔍 Spread Update | {crypto_symbol.value}<->{stock_symbol.value} | "
        #         f"Spread: {spread_pct*100:.3f}% | "
        #         f"Entry Threshold: {self.entry_threshold*100:.2f}% | "
        #         f"Exit Threshold: {self.exit_threshold*100:.2f}% | "
        #         f"can_open={can_open}, can_close={can_close}"
        #     )

        # 开仓逻辑: spread <= entry_threshold (负数) 且可以开仓
        if can_open and spread_pct <= self.entry_threshold:
            tickets = self._open_position(
                pair_symbol, spread_pct, crypto_quote, stock_quote,
                self.position_size_pct
            )
            if tickets:
                self.open_times[pair_symbol] = self.algorithm.time

        # 平仓逻辑: spread >= exit_threshold (正数) 且可以平仓
        elif can_close and spread_pct >= self.exit_threshold:
            tickets = self._close_position(pair_symbol, spread_pct, crypto_quote, stock_quote)
            if tickets:
                # 计算持仓时间
                if pair_symbol in self.open_times:
                    holding_time = self.algorithm.time - self.open_times[pair_symbol]
                    self.holding_times.append(holding_time)
                    del self.open_times[pair_symbol]
