"""
Both Side Strategy - 双边套利策略

继承 BaseStrategy 的开/平仓逻辑和位置追踪
支持双向交易:
1. Long Crypto + Short Stock (spread <= -1%, exit >= 2%)
2. Short Crypto + Long Stock (spread >= 3%, exit <= -0.9%)
根据当前持仓方向选择平仓条件
"""
from AlgorithmImports import *
from strategy.base_strategy import BaseStrategy
from SpreadManager import SpreadManager


class BothSideStrategy(BaseStrategy):
    """
    双边套利策略 - 继承 BaseStrategy

    特点:
    - 继承 BaseStrategy 的开/平仓逻辑和位置追踪
    - 支持双向交易:
      1. Long Crypto + Short Stock (spread <= -1%, exit >= 2%)
      2. Short Crypto + Long Stock (spread >= 3%, exit <= -0.9%)
    - 根据当前持仓方向选择平仓条件
    """

    def __init__(self, algorithm: QCAlgorithm, spread_manager: SpreadManager,
                 long_crypto_entry: float = -0.01,
                 long_crypto_exit: float = 0.02,
                 short_crypto_entry: float = 0.03,
                 short_crypto_exit: float = -0.009,
                 position_size_pct: float = 0.25):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            spread_manager: SpreadManager实例
            long_crypto_entry: Long crypto开仓阈值 (负数, 默认-1%)
            long_crypto_exit: Long crypto平仓阈值 (正数, 默认2%)
            short_crypto_entry: Short crypto开仓阈值 (正数, 默认3%)
            short_crypto_exit: Short crypto平仓阈值 (负数, 默认-0.9%)
            position_size_pct: 仓位大小百分比 (默认25%)
        """
        # 调用父类初始化 (debug=False)
        super().__init__(algorithm, debug=False)

        self.spread_manager = spread_manager
        self.long_crypto_entry = long_crypto_entry
        self.long_crypto_exit = long_crypto_exit
        self.short_crypto_entry = short_crypto_entry
        self.short_crypto_exit = short_crypto_exit
        self.position_size_pct = position_size_pct

        # 持仓方向追踪: {pair_symbol: 'long_crypto' or 'short_crypto'}
        self.position_direction = {}

        # 持仓时间追踪
        self.open_times = {}  # {pair_symbol: open_time}
        self.holding_times = []  # 每次回转交易的持仓时间 (timedelta)

        self.algorithm.debug(
            f"BothSideStrategy initialized | "
            f"Long Crypto: entry <= {self.long_crypto_entry*100:.2f}%, exit >= {self.long_crypto_exit*100:.2f}% | "
            f"Short Crypto: entry >= {self.short_crypto_entry*100:.2f}%, exit <= {self.short_crypto_exit*100:.2f}% | "
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
            crypto_bid_price: 我们的卖出限价
            crypto_ask_price: 我们的买入限价
        """
        pair_symbol = (crypto_symbol, stock_symbol)

        # 使用 BaseStrategy 的方法检查是否应该开/平仓
        can_open = self._should_open_position(crypto_symbol, stock_symbol)
        can_close = self._should_close_position(crypto_symbol, stock_symbol)

        # 获取当前持仓方向
        current_direction = self.position_direction.get(pair_symbol)

        # === 开仓逻辑 ===
        if can_open:
            # Long Crypto + Short Stock (spread <= -1%)
            if spread_pct <= self.long_crypto_entry:
                tickets = self._open_position(
                    pair_symbol, spread_pct, crypto_quote, stock_quote,
                    self.position_size_pct
                )
                if tickets:
                    self.position_direction[pair_symbol] = 'long_crypto'
                    self.open_times[pair_symbol] = self.algorithm.time
                    self.algorithm.debug(
                        f"📈 Long Crypto opened | Spread: {spread_pct*100:.2f}%"
                    )

            # Short Crypto + Long Stock (spread >= 3%)
            elif spread_pct >= self.short_crypto_entry:
                tickets = self._open_position(
                    pair_symbol, spread_pct, crypto_quote, stock_quote,
                    -self.position_size_pct  # 负数: short crypto + long stock
                )
                if tickets:
                    self.position_direction[pair_symbol] = 'short_crypto'
                    self.open_times[pair_symbol] = self.algorithm.time
                    self.algorithm.debug(
                        f"📉 Short Crypto opened | Spread: {spread_pct*100:.2f}%"
                    )

        # === 平仓逻辑 ===
        elif can_close and current_direction:
            should_close = False

            # Long Crypto position -> exit when spread >= 2%
            if current_direction == 'long_crypto' and spread_pct >= self.long_crypto_exit:
                should_close = True
                self.algorithm.debug(
                    f"📈 Long Crypto closing | Spread: {spread_pct*100:.2f}%"
                )

            # Short Crypto position -> exit when spread <= -0.9%
            elif current_direction == 'short_crypto' and spread_pct <= self.short_crypto_exit:
                should_close = True
                self.algorithm.debug(
                    f"📉 Short Crypto closing | Spread: {spread_pct*100:.2f}%"
                )

            if should_close:
                tickets = self._close_position(pair_symbol, spread_pct, crypto_quote, stock_quote)
                if tickets:
                    # 计算持仓时间
                    if pair_symbol in self.open_times:
                        holding_time = self.algorithm.time - self.open_times[pair_symbol]
                        self.holding_times.append(holding_time)
                        del self.open_times[pair_symbol]

                    # 清除方向记录
                    del self.position_direction[pair_symbol]
