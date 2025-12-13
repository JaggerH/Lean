"""
Spread Data Collector

Collects spread data from TradingPair for analysis and visualization.
"""

from QuantConnect.TradingPairs import MarketState


class SpreadCollector:
    """价差数据收集器（通用版本）

    收集两类数据：
    1. 理论价差（Theoretical Spread）：连续数据，用于可视化
    2. 可执行价差（Executable Spread）：稀疏数据，仅在有交易机会时记录
    """

    def __init__(self, algorithm, collect_executable=True):
        """
        Initialize spread collector

        Args:
            algorithm: QCAlgorithm instance
            collect_executable: Whether to collect executable spread data
        """
        self.algorithm = algorithm
        self.collect_executable = collect_executable

        # 理论价差数据（连续）
        self.theoretical_spread_data = []  # [(timestamp, spread_pct)]

        # 可执行价差数据（稀疏）
        self.executable_spread_data = []  # [(timestamp, spread_pct, market_state, direction)]

        # 市场状态统计
        self.state_counts = {
            MarketState.Crossed: 0,
            MarketState.LimitOpportunity: 0,
            MarketState.NoOpportunity: 0
        }

    def collect_spread_data(self, pair):
        """从 TradingPair 收集数据

        Args:
            pair: TradingPair 对象
        """
        if not pair.HasValidPrices:
            return

        timestamp = self.algorithm.Time

        # 1. 理论价差（总是收集）
        self.theoretical_spread_data.append((timestamp, pair.TheoreticalSpread))

        # 2. 可执行价差（可选）
        if self.collect_executable and pair.ExecutableSpread is not None:
            self.executable_spread_data.append((
                timestamp,
                pair.ExecutableSpread,
                pair.MarketState,
                pair.Direction
            ))

        # 3. 市场状态统计
        self.state_counts[pair.MarketState] += 1
