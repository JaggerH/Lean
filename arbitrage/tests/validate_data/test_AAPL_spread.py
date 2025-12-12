"""
AAPL 价差分析 - 可视化 AAPLUSD vs AAPL 价差走势（Framework版本）

更新内容 (2025-12-13):
- 改用 TradingPair Framework API
- 继承自 AQCAlgorithm
- 直接访问 TradingPair.TheoreticalSpread 和 TradingPair.ExecutableSpread
- 使用 TradingPair.MarketState 获取市场状态
- 保留原有的可视化功能

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-05
- 目标: 绘制价差走势图（包含市场状态分类）
"""

import sys
from pathlib import Path
from datetime import datetime

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm
from QuantConnect.TradingPairs import MarketState
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class SpreadCollector:
    """
    价差数据收集器（Framework版本）

    收集两类数据：
    1. 理论价差（连续，用于可视化）
    2. 可执行价差（稀疏，用于标记交易机会）
    """

    def __init__(self, algorithm: QCAlgorithm):
        self.algorithm = algorithm

        # 理论价差数据（连续）
        self.theoretical_spread_data = []  # [(timestamp, spread_pct)]

        # 可执行价差数据（稀疏，只在有机会时记录）
        self.executable_spread_data = []  # [(timestamp, spread_pct, market_state, direction)]

        # 市场状态统计
        self.state_counts = {
            MarketState.Crossed: 0,
            MarketState.LimitOpportunity: 0,
            MarketState.NoOpportunity: 0
        }

    def collect_spread_data(self, pair):
        """
        从 TradingPair 对象收集价差数据

        Args:
            pair: TradingPair 对象
        """
        if not pair.HasValidPrices:
            return

        timestamp = self.algorithm.Time

        # 1. 记录理论价差（连续）
        self.theoretical_spread_data.append((timestamp, pair.TheoreticalSpread))

        # 2. 记录可执行价差（只在有机会时）
        if pair.ExecutableSpread is not None:
            self.executable_spread_data.append((
                timestamp,
                pair.ExecutableSpread,
                pair.MarketState,
                pair.Direction
            ))

        # 3. 更新市场状态统计
        self.state_counts[pair.MarketState] += 1


class AAPLSpreadAnalysis(AQCAlgorithm):
    """AAPL价差分析算法（Framework版本）"""

    def Initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.SetStartDate(2025, 9, 2)
        self.SetEndDate(2025, 9, 27)
        self.SetCash(100000)

        # 设置 Kraken Brokerage Model（确保 Crypto 市场映射到 Kraken）
        self.SetBrokerageModel(BrokerageName.Kraken, AccountType.Cash)

        # 禁用基准（benchmark）以避免查找 BTCUSD trade 数据
        self.SetBenchmark(lambda x: 0)

        # 设置时区为UTC
        self.SetTimeZone("UTC")

        # === 1. 创建 SpreadCollector ===
        self.Debug("📊 Initializing Spread Collector...")
        self.collector = SpreadCollector(self)

        # === 2. 添加证券 ===
        self.Debug("📈 Adding securities...")

        # 创建 Symbol
        crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        # 添加证券（使用Framework推荐的Resolution）
        self.aapl_crypto = self.AddCrypto("AAPLxUSD", Resolution.Orderbook, Market.Kraken)
        self.aapl_stock = self.AddEquity("AAPL", Resolution.Tick, Market.USA, extendedMarketHours=False)

        self.Debug(f"   Crypto: {self.aapl_crypto.Symbol}")
        self.Debug(f"   Stock: {self.aapl_stock.Symbol}")

        # === 3. 添加交易对到 TradingPairs 集合 ===
        self.Debug("📊 Adding trading pair to TradingPairs...")
        self.aapl_pair = self.TradingPairs.AddPair(
            crypto_symbol,
            stock_symbol,
            "crypto_stock"  # pair type
        )

        self.Debug(f"   Pair: {self.aapl_pair.Key}")

        # === 4. 数据追踪 ===
        self.last_log_time = None

        self.Debug("✅ Initialization complete!")

    def OnData(self, data: Slice):
        """处理数据 - 调用base class来更新TradingPairs，然后收集spread数据"""
        try:
            # CRITICAL: 调用base class的OnData来触发Framework更新
            # 这会自动更新TradingPairs的spread计算
            super().OnData(data)

            # 从TradingPair收集spread数据
            self.collector.collect_spread_data(self.aapl_pair)

            # 每小时输出一次状态
            if len(self.collector.theoretical_spread_data) > 0:
                if self.last_log_time is None or (self.Time - self.last_log_time).total_seconds() >= 3600:
                    _, theoretical_spread = self.collector.theoretical_spread_data[-1]
                    executable_count = len(self.collector.executable_spread_data)

                    self.Debug(
                        f"📊 {self.Time} | "
                        f"Theoretical Spread: {theoretical_spread*100:.2f}% | "
                        f"Executable Opportunities: {executable_count:,}"
                    )
                    self.last_log_time = self.Time

        except Exception as e:
            self.Error(f"❌ Error in OnData: {str(e)}")
            import traceback
            self.Debug(traceback.format_exc())

    def OnEndOfAlgorithm(self):
        """算法结束 - 绘制价差走势图（Framework版本）"""
        self.Debug("\n" + "="*60)
        self.Debug("📊 价差分析统计（Framework版本）")
        self.Debug("="*60)

        # 1. 基本统计
        theoretical_count = len(self.collector.theoretical_spread_data)
        executable_count = len(self.collector.executable_spread_data)

        self.Debug(f"理论价差数据点数: {theoretical_count:,}")
        self.Debug(f"可执行机会数量: {executable_count:,}")

        if theoretical_count == 0:
            self.Debug("⚠️ 无价差数据，无法绘图")
            return

        # 2. 理论价差统计
        theoretical_spreads = [s[1] * 100 for s in self.collector.theoretical_spread_data]
        min_spread = min(theoretical_spreads)
        max_spread = max(theoretical_spreads)
        avg_spread = sum(theoretical_spreads) / len(theoretical_spreads)

        self.Debug(f"\n理论价差统计:")
        self.Debug(f"  最小价差: {min_spread:.2f}%")
        self.Debug(f"  最大价差: {max_spread:.2f}%")
        self.Debug(f"  平均价差: {avg_spread:.2f}%")

        # 3. 市场状态统计
        total_signals = sum(self.collector.state_counts.values())
        self.Debug(f"\n市场状态分布 (总信号数: {total_signals:,}):")
        for state, count in self.collector.state_counts.items():
            percentage = (count / total_signals * 100) if total_signals > 0 else 0
            state_name = str(state).split('.')[-1]  # Get enum name
            self.Debug(f"  {state_name}: {count:,} ({percentage:.1f}%)")

        # 4. 可执行机会详细统计
        if executable_count > 0:
            crossed_count = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                              if state == MarketState.Crossed)
            limit_count = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                            if state == MarketState.LimitOpportunity)

            self.Debug(f"\n可执行机会详细:")
            self.Debug(f"  CROSSED Market: {crossed_count:,} ({crossed_count/executable_count*100:.1f}%)")
            self.Debug(f"  LIMIT_OPPORTUNITY: {limit_count:,} ({limit_count/executable_count*100:.1f}%)")

        # 5. 绘制价差走势图
        self.Debug("\n📈 绘制价差走势图...")
        self._plot_spread_chart()

        self.Debug("="*60)
        self.Debug("✅ 价差分析完成")
        self.Debug("="*60)

    def _plot_spread_chart(self):
        """
        绘制价差走势图（Framework版本）

        图表包含：
        1. 理论价差线（连续，灰色）
        2. CROSSED Market 可执行价差线（连续，红色）
        3. 两条阈值横线：-1% 和 2%
        """
        try:
            # 1. 准备理论价差数据（连续）
            theoretical_timestamps = [s[0] for s in self.collector.theoretical_spread_data]
            theoretical_spreads = [s[1] * 100 for s in self.collector.theoretical_spread_data]

            # 2. 准备 CROSSED Market 可执行价差数据
            crossed_timestamps = []
            crossed_spreads = []
            for timestamp, spread_pct, market_state, direction in self.collector.executable_spread_data:
                if market_state == MarketState.Crossed:
                    crossed_timestamps.append(timestamp)
                    crossed_spreads.append(spread_pct * 100)

            # 3. 创建图表
            fig, ax = plt.subplots(figsize=(16, 9))

            # 4. 绘制理论价差线（灰色）
            ax.plot(theoretical_timestamps, theoretical_spreads,
                   linewidth=1.0, color='gray', alpha=0.6,
                   label=f'Theoretical Spread ({len(theoretical_spreads):,} points)',
                   zorder=2)

            # 5. 绘制 CROSSED Market 可执行价差线（红色）
            if len(crossed_timestamps) > 0:
                ax.plot(crossed_timestamps, crossed_spreads,
                       linewidth=1.2, color='red', alpha=0.8,
                       label=f'CROSSED Market Executable Spread ({len(crossed_spreads):,} points)',
                       zorder=3)

            # 6. 添加零线
            ax.axhline(y=0, color='black', linestyle='-', linewidth=1.5, alpha=0.5, zorder=1)

            # 7. 添加阈值横线
            ax.axhline(y=-1.0, color='green', linestyle='--', linewidth=1.5, alpha=0.7,
                      label='Threshold: -1%', zorder=1)
            ax.axhline(y=2.0, color='blue', linestyle='--', linewidth=1.5, alpha=0.7,
                      label='Threshold: +2%', zorder=1)

            # 8. 格式化x轴日期
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=3))
            plt.xticks(rotation=45, ha='right')

            # 9. 设置标签和标题
            ax.set_xlabel('Time (UTC)', fontsize=12)
            ax.set_ylabel('Spread %', fontsize=12)
            ax.set_title(
                'AAPLxUSD vs AAPL Spread Analysis (Framework API)\n'
                'Gray: Theoretical Spread | Red: CROSSED Market Executable Spread',
                fontsize=14, fontweight='bold'
            )
            ax.grid(True, alpha=0.3, zorder=0)
            ax.legend(loc='best', fontsize=10)

            # 10. 调整布局
            plt.tight_layout()

            # 11. 保存图表 - 使用绝对路径
            output_path = Path(r"C:\Users\Jagger\Documents\Code\Lean\arbitrage\tests\validate_data\AAPL_spread_analysis_framework.png")
            plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
            plt.close()

            self.Debug(f"✅ 图表已保存至: {output_path}")

        except Exception as e:
            self.Debug(f"❌ 绘图失败: {str(e)}")
            import traceback
            self.Debug(traceback.format_exc())
