"""
TSLA 价差分析 - 可视化 TSLAUSD vs TSLA 价差走势

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
from spread_manager import SpreadManager
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class SpreadCollector:
    """简单的策略 - 仅收集价差数据用于分析"""

    def __init__(self, algorithm: QCAlgorithm):
        self.algorithm = algorithm
        self.spread_data = []  # [(timestamp, spread_pct)]

    def on_spread_update(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                        spread_pct: float, crypto_quote, stock_quote,
                        crypto_bid_price: float, crypto_ask_price: float):
        """
        接收价差更新并收集数据

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            spread_pct: Spread百分比 (已经计算好的)
            crypto_quote: Crypto报价 (未使用)
            stock_quote: Stock报价 (未使用)
            crypto_bid_price: 我们的卖出限价 (未使用)
            crypto_ask_price: 我们的买入限价 (未使用)
        """
        # 记录价差数据 (只需要时间戳和价差百分比)
        self.spread_data.append((self.algorithm.Time, spread_pct))


class TSLASpreadAnalysis(QCAlgorithm):
    """TSLA价差分析算法"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)
        self.set_cash(100000)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 1. 添加股票数据 (Databento) ===
        self.debug("📈 Adding Stock Data (Databento)...")
        self.tsla_stock = self.add_equity("TSLA", Resolution.TICK, Market.USA, extended_market_hours=False)
        self.tsla_stock.data_normalization_mode = DataNormalizationMode.RAW

        # === 2. 添加加密货币数据 (Kraken) ===
        self.debug("🪙 Adding Crypto Data (Kraken)...")
        self.tsla_crypto = self.add_crypto("TSLAUSD", Resolution.TICK, Market.Kraken)
        self.tsla_crypto.data_normalization_mode = DataNormalizationMode.RAW

        # === 3. 初始化 SpreadManager 和策略 ===
        self.debug("📊 Initializing SpreadManager...")

        # 创建SpreadCollector策略
        self.collector = SpreadCollector(self)

        # 创建SpreadManager并链接策略
        self.spread_manager = SpreadManager(
            algorithm=self,
            strategy=self.collector
        )

        # 注册交易对
        self.debug("🔗 Registering TSLA trading pair...")
        self.spread_manager.add_pair(self.tsla_crypto, self.tsla_stock)

        # === 4. 数据追踪 ===
        self.tick_count = 0
        self.last_log_time = None

        self.debug("✅ Initialization complete!")

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager"""
        if not data.ticks or len(data.ticks) == 0:
            return

        self.tick_count += 1

        # 委托给SpreadManager处理数据并监控价差
        self.spread_manager.on_data(data)

        # 每小时输出一次状态
        if len(self.collector.spread_data) > 0:
            if self.last_log_time is None or (self.time - self.last_log_time).total_seconds() >= 3600:
                timestamp, spread_pct = self.collector.spread_data[-1]
                self.debug(
                    f"📊 {self.time} | Ticks: {self.tick_count:,} | "
                    f"Spread: {spread_pct*100:.2f}%"
                )
                self.last_log_time = self.time

    def on_end_of_algorithm(self):
        """算法结束 - 绘制价差走势图"""
        self.debug("\n" + "="*60)
        self.debug("📊 价差分析统计")
        self.debug("="*60)
        self.debug(f"总Tick数: {self.tick_count:,}")
        self.debug(f"价差数据点数: {len(self.collector.spread_data):,}")

        if len(self.collector.spread_data) == 0:
            self.debug("⚠️ 无价差数据，无法绘图")
            return

        # 计算统计数据
        spreads = [s[1] * 100 for s in self.collector.spread_data]  # 转换为百分比
        min_spread = min(spreads)
        max_spread = max(spreads)
        avg_spread = sum(spreads) / len(spreads)

        self.debug(f"\n价差统计:")
        self.debug(f"  最小价差: {min_spread:.2f}%")
        self.debug(f"  最大价差: {max_spread:.2f}%")
        self.debug(f"  平均价差: {avg_spread:.2f}%")

        # 统计价差分布
        below_neg1 = sum(1 for s in spreads if s <= -1.0)
        above_0 = sum(1 for s in spreads if s >= 0.0)
        total = len(spreads)

        self.debug(f"\n价差分布:")
        self.debug(f"  Spread <= -1%: {below_neg1:,} ({below_neg1/total*100:.1f}%) - 开仓机会")
        self.debug(f"  Spread >= 0%: {above_0:,} ({above_0/total*100:.1f}%) - 平仓机会")

        # 绘制价差走势图
        self.debug("\n📈 绘制价差走势图...")
        self._plot_spread_chart()

        self.debug("="*60)
        self.debug("✅ 价差分析完成")
        self.debug("="*60)

    def _plot_spread_chart(self):
        """绘制价差走势图"""
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
            ax.set_title('TSLAUSD vs TSLA Spread Analysis (2025-09-02 to 2025-09-27)', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='best')

            # 调整布局
            plt.tight_layout()

            # 保存图表 - 使用绝对路径
            output_path = Path(r"C:\Users\Jagger\Documents\Code\Lean\arbitrage\tests\validate_data\TSLA_spread_analysis.png")
            plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
            plt.close()

            self.debug(f"✅ 图表已保存至: {output_path}")

        except Exception as e:
            self.debug(f"❌ 绘图失败: {str(e)}")
            import traceback
            self.debug(traceback.format_exc())
