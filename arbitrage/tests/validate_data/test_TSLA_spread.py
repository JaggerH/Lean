"""
TSLA 价差分析 - 可视化 TSLAUSD vs TSLA 价差走势（Framework版本）

更新内容 (2025-12-13):
- 改用 TradingPair Framework API
- 继承自 AQCAlgorithm
- 直接访问 TradingPair.TheoreticalSpread
- 保留原有的可视化功能

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLA/TSLAUSD
- 日期范围: 2025-09-02 至 2025-09-27
- 目标: 绘制价差走势图
"""

import sys
from pathlib import Path
from datetime import datetime

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class SpreadCollector:
    """简单的数据收集器 - 仅收集价差数据用于分析（Framework版本）"""

    def __init__(self, algorithm: QCAlgorithm):
        self.algorithm = algorithm
        self.spread_data = []  # [(timestamp, spread_pct)]

    def collect_spread_data(self, pair):
        """
        从 TradingPair 对象收集价差数据

        Args:
            pair: TradingPair 对象
        """
        if not pair.HasValidPrices:
            return

        timestamp = self.algorithm.Time

        # 记录理论价差
        self.spread_data.append((timestamp, pair.TheoreticalSpread))


class TSLASpreadAnalysis(AQCAlgorithm):
    """TSLA价差分析算法（Framework版本）"""

    def Initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.SetStartDate(2025, 9, 2)
        self.SetEndDate(2025, 9, 5)
        self.SetCash(100000)

        # 设置 Kraken Brokerage Model
        self.SetBrokerageModel(BrokerageName.Kraken, AccountType.Cash)

        # 禁用基准
        self.SetBenchmark(lambda x: 0)

        # 设置时区为UTC
        self.SetTimeZone("UTC")

        # === 1. 创建 SpreadCollector ===
        self.Debug("📊 Initializing Spread Collector...")
        self.collector = SpreadCollector(self)

        # === 2. 添加证券 ===
        self.Debug("📈 Adding securities...")

        # 创建 Symbol
        crypto_symbol = Symbol.Create("TSLAUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA)

        # 添加证券（使用Framework推荐的Resolution）
        self.tsla_crypto = self.AddCrypto("TSLAUSD", Resolution.Tick, Market.Kraken)
        self.tsla_stock = self.AddEquity("TSLA", Resolution.Tick, Market.USA, extendedMarketHours=False)

        # Set raw normalization
        self.tsla_crypto.DataNormalizationMode = DataNormalizationMode.Raw
        self.tsla_stock.DataNormalizationMode = DataNormalizationMode.Raw

        self.Debug(f"   Crypto: {self.tsla_crypto.Symbol}")
        self.Debug(f"   Stock: {self.tsla_stock.Symbol}")

        # === 3. 添加交易对到 TradingPairs 集合 ===
        self.Debug("📊 Adding trading pair to TradingPairs...")
        self.tsla_pair = self.TradingPairs.AddPair(
            crypto_symbol,
            stock_symbol,
            "crypto_stock"  # pair type
        )

        self.Debug(f"   Pair: {self.tsla_pair.Key}")

        # === 4. 数据追踪 ===
        self.tick_count = 0
        self.last_log_time = None

        self.Debug("✅ Initialization complete!")

    def OnData(self, data: Slice):
        """处理数据 - 调用base class来更新TradingPairs，然后收集spread数据"""
        if not data.Ticks or len(data.Ticks) == 0:
            return

        self.tick_count += 1

        try:
            # CRITICAL: 调用base class的OnData来触发Framework更新
            # 这会自动更新TradingPairs的spread计算
            super().OnData(data)

            # 从TradingPair收集spread数据
            self.collector.collect_spread_data(self.tsla_pair)

            # 每小时输出一次状态
            if len(self.collector.spread_data) > 0:
                if self.last_log_time is None or (self.Time - self.last_log_time).total_seconds() >= 3600:
                    timestamp, spread_pct = self.collector.spread_data[-1]
                    self.Debug(
                        f"📊 {self.Time} | Ticks: {self.tick_count:,} | "
                        f"Spread: {spread_pct*100:.2f}%"
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
        self.Debug(f"总Tick数: {self.tick_count:,}")
        self.Debug(f"价差数据点数: {len(self.collector.spread_data):,}")

        if len(self.collector.spread_data) == 0:
            self.Debug("⚠️ 无价差数据，无法绘图")
            return

        # 计算统计数据
        spreads = [s[1] * 100 for s in self.collector.spread_data]  # 转换为百分比
        min_spread = min(spreads)
        max_spread = max(spreads)
        avg_spread = sum(spreads) / len(spreads)

        self.Debug(f"\n价差统计:")
        self.Debug(f"  最小价差: {min_spread:.2f}%")
        self.Debug(f"  最大价差: {max_spread:.2f}%")
        self.Debug(f"  平均价差: {avg_spread:.2f}%")

        # 统计价差分布
        below_neg1 = sum(1 for s in spreads if s <= -1.0)
        above_0 = sum(1 for s in spreads if s >= 0.0)
        total = len(spreads)

        self.Debug(f"\n价差分布:")
        self.Debug(f"  Spread <= -1%: {below_neg1:,} ({below_neg1/total*100:.1f}%) - 开仓机会")
        self.Debug(f"  Spread >= 0%: {above_0:,} ({above_0/total*100:.1f}%) - 平仓机会")

        # 绘制价差走势图
        self.Debug("\n📈 绘制价差走势图...")
        self._plot_spread_chart()

        self.Debug("="*60)
        self.Debug("✅ 价差分析完成")
        self.Debug("="*60)

    def _plot_spread_chart(self):
        """绘制价差走势图（Framework版本）"""
        try:
            # 准备数据
            timestamps = [s[0] for s in self.collector.spread_data]
            spreads = [s[1] * 100 for s in self.collector.spread_data]  # 转换为百分比

            # 创建图表
            fig, ax = plt.subplots(figsize=(16, 8))

            # 绘制价差曲线
            ax.plot(timestamps, spreads, linewidth=0.5, color='blue', alpha=0.6, label='Spread %')

            # 添加关键阈值线
            ax.axhline(y=-1.0, color='green', linestyle='--', linewidth=1.5, label='Entry Threshold (-1%)')
            ax.axhline(y=0.0, color='red', linestyle='--', linewidth=1.5, label='Exit Threshold (0%)')

            # 填充区域
            ax.fill_between(timestamps, spreads, -1.0, where=[s <= -1.0 for s in spreads],
                           alpha=0.3, color='green', label='Entry Zone')
            ax.fill_between(timestamps, spreads, 0.0, where=[s >= 0.0 for s in spreads],
                           alpha=0.3, color='red', label='Exit Zone')

            # 格式化x轴日期
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            plt.xticks(rotation=45, ha='right')

            # 设置标签和标题
            ax.set_xlabel('Time (UTC)', fontsize=12)
            ax.set_ylabel('Spread %', fontsize=12)
            ax.set_title('TSLAUSD vs TSLA Spread Analysis (Framework API)', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='best')

            # 调整布局
            plt.tight_layout()

            # 保存图表 - 使用绝对路径
            output_path = Path(r"C:\Users\Jagger\Documents\Code\Lean\arbitrage\tests\validate_data\TSLA_spread_analysis_framework.png")
            plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
            plt.close()

            self.Debug(f"✅ 图表已保存至: {output_path}")

        except Exception as e:
            self.Debug(f"❌ 绘图失败: {str(e)}")
            import traceback
            self.Debug(traceback.format_exc())
