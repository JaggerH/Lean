"""
AAPL 价差分析 - 可视化 AAPLUSD vs AAPL 价差走势（重构版）

重构内容 (2025-10-23):
- 使用 SpreadManager 的 observer 模式
- 使用新的两层价差信号系统（理论价差 + 可执行价差）
- 区分三种市场状态: CROSSED / LIMIT_OPPORTUNITY / NO_OPPORTUNITY
- 同时绘制理论价差（连续）和可执行价差（稀疏标记）

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
# Import C# OrderbookDepth type
from QuantConnect.Data.Market import OrderbookDepth
from spread_manager import SpreadManager, MarketState, SpreadSignal
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class SpreadCollector:
    """
    价差数据收集器（重构版）- 作为 SpreadManager 的 Observer

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
            MarketState.CROSSED: 0,
            MarketState.LIMIT_OPPORTUNITY: 0,
            MarketState.NO_OPPORTUNITY: 0
        }

    def on_spread_update(self, pair_symbol, signal: SpreadSignal):
        """
        SpreadManager 的 observer 回调

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            signal: SpreadSignal 对象（包含理论价差和可执行价差）
        """
        timestamp = self.algorithm.time

        # 1. 记录理论价差（连续）
        self.theoretical_spread_data.append((timestamp, signal.theoretical_spread))

        # 2. 记录可执行价差（只在有机会时）
        if signal.executable_spread is not None:
            self.executable_spread_data.append((
                timestamp,
                signal.executable_spread,
                signal.market_state,
                signal.direction
            ))

        # 3. 更新市场状态统计
        self.state_counts[signal.market_state] += 1


class AAPLSpreadAnalysis(QCAlgorithm):
    """AAPL价差分析算法（重构版 - 使用 SpreadManager）"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 27)
        self.set_cash(100000)

        # 设置 Kraken Brokerage Model（确保 Crypto 市场映射到 Kraken）
        self.set_brokerage_model(BrokerageName.Kraken, AccountType.Cash)

        # 禁用基准（benchmark）以避免查找 BTCUSD trade 数据
        self.set_benchmark(lambda x: 0)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 1. 创建 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(self)

        # === 2. 创建 SpreadCollector 并注册为 observer ===
        self.debug("📊 Initializing Spread Collector...")
        self.collector = SpreadCollector(self)
        self.spread_manager.register_observer(self.collector.on_spread_update)

        # === 3. 订阅交易对（使用 SpreadManager 的统一接口）===
        self.debug("📈 Subscribing AAPL/AAPLxUSD trading pair...")

        # 创建 Symbol
        crypto_symbol = Symbol.create("AAPLxUSD", SecurityType.CRYPTO, Market.KRAKEN)
        stock_symbol = Symbol.create("AAPL", SecurityType.EQUITY, Market.USA)

        # 使用 SpreadManager 订阅交易对
        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(crypto_symbol, stock_symbol),
            resolution=(Resolution.ORDERBOOK, Resolution.TICK),  # Crypto用Orderbook，Stock用Tick
            extended_market_hours=False
        )

        self.debug(f"   Crypto: {self.aapl_crypto.Symbol}")
        self.debug(f"   Stock: {self.aapl_stock.Symbol}")

        # === 4. 数据追踪 ===
        self.last_log_time = None

        self.debug("✅ Initialization complete!")

    def on_data(self, data: Slice):
        """处理数据 - 委托给 SpreadManager"""
        try:
            # 将数据传递给 SpreadManager，它会自动计算价差并通知 observers
            self.spread_manager.on_data(data)

            # 每小时输出一次状态
            if len(self.collector.theoretical_spread_data) > 0:
                if self.last_log_time is None or (self.time - self.last_log_time).total_seconds() >= 3600:
                    _, theoretical_spread = self.collector.theoretical_spread_data[-1]
                    executable_count = len(self.collector.executable_spread_data)

                    self.debug(
                        f"📊 {self.time} | "
                        f"Theoretical Spread: {theoretical_spread*100:.2f}% | "
                        f"Executable Opportunities: {executable_count:,}"
                    )
                    self.last_log_time = self.time

        except Exception as e:
            self.error(f"❌ Error in on_data: {str(e)}")
            import traceback
            self.debug(traceback.format_exc())

    def on_end_of_algorithm(self):
        """算法结束 - 绘制价差走势图（重构版）"""
        self.debug("\n" + "="*60)
        self.debug("📊 价差分析统计（重构版 - 两层价差系统）")
        self.debug("="*60)

        # 1. 基本统计
        theoretical_count = len(self.collector.theoretical_spread_data)
        executable_count = len(self.collector.executable_spread_data)

        self.debug(f"理论价差数据点数: {theoretical_count:,}")
        self.debug(f"可执行机会数量: {executable_count:,}")

        if theoretical_count == 0:
            self.debug("⚠️ 无价差数据，无法绘图")
            return

        # 2. 理论价差统计
        theoretical_spreads = [s[1] * 100 for s in self.collector.theoretical_spread_data]
        min_spread = min(theoretical_spreads)
        max_spread = max(theoretical_spreads)
        avg_spread = sum(theoretical_spreads) / len(theoretical_spreads)

        self.debug(f"\n理论价差统计:")
        self.debug(f"  最小价差: {min_spread:.2f}%")
        self.debug(f"  最大价差: {max_spread:.2f}%")
        self.debug(f"  平均价差: {avg_spread:.2f}%")

        # 3. 市场状态统计
        total_signals = sum(self.collector.state_counts.values())
        self.debug(f"\n市场状态分布 (总信号数: {total_signals:,}):")
        for state, count in self.collector.state_counts.items():
            percentage = (count / total_signals * 100) if total_signals > 0 else 0
            self.debug(f"  {state.value.upper()}: {count:,} ({percentage:.1f}%)")

        # 4. 可执行机会详细统计
        if executable_count > 0:
            crossed_count = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                              if state == MarketState.CROSSED)
            limit_count = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                            if state == MarketState.LIMIT_OPPORTUNITY)

            self.debug(f"\n可执行机会详细:")
            self.debug(f"  CROSSED Market: {crossed_count:,} ({crossed_count/executable_count*100:.1f}%)")
            self.debug(f"  LIMIT_OPPORTUNITY: {limit_count:,} ({limit_count/executable_count*100:.1f}%)")

        # 5. 绘制价差走势图
        self.debug("\n📈 绘制价差走势图...")
        self._plot_spread_chart()

        self.debug("="*60)
        self.debug("✅ 价差分析完成")
        self.debug("="*60)

    def _plot_spread_chart(self):
        """
        绘制价差走势图（简化版 - 两条线）

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
                if market_state == MarketState.CROSSED:
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
                'AAPLxUSD vs AAPL Spread Analysis\n'
                'Gray: Theoretical Spread | Red: CROSSED Market Executable Spread',
                fontsize=14, fontweight='bold'
            )
            ax.grid(True, alpha=0.3, zorder=0)
            ax.legend(loc='best', fontsize=10)

            # 10. 调整布局
            plt.tight_layout()

            # 11. 保存图表 - 使用绝对路径
            output_path = Path(r"C:\Users\Jagger\Documents\Code\Lean\arbitrage\tests\validate_data\AAPL_spread_analysis_v2.png")
            plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
            plt.close()

            self.debug(f"✅ 图表已保存至: {output_path}")

        except Exception as e:
            self.debug(f"❌ 绘图失败: {str(e)}")
            import traceback
            self.debug(traceback.format_exc())
