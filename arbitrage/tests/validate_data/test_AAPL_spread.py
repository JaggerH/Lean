"""
AAPL 价差分析 - 可视化 AAPLUSD vs AAPL 价差走势

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-27
- 目标: 绘制价差走势图
"""

import sys
from pathlib import Path
from datetime import datetime

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
# Import C# OrderbookDepth type
from QuantConnect.Data.Market import OrderbookDepth
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


class SpreadCollector:
    """简单的策略 - 仅收集价差数据用于分析"""

    def __init__(self, algorithm: QCAlgorithm):
        self.algorithm = algorithm
        self.spread_data = []  # [(timestamp, spread_pct)]

    def add_spread_data(self, timestamp: datetime, spread_pct: float):
        """
        添加价差数据点

        Args:
            timestamp: 时间戳
            spread_pct: 价差百分比
        """
        self.spread_data.append((timestamp, spread_pct))


class AAPLSpreadAnalysis(QCAlgorithm):
    """AAPL价差分析算法"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)
        self.set_cash(100000)

        # 设置 Kraken Brokerage Model（确保 Crypto 市场映射到 Kraken）
        # 这样 AAPLX 货币转换查找会在 Kraken 市场中进行，而不是默认的 Coinbase
        self.set_brokerage_model(BrokerageName.Kraken, AccountType.Cash)

        # 禁用基准（benchmark）以避免查找 BTCUSD trade 数据
        self.set_benchmark(lambda x: 0)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 1. 添加股票数据 (Databento) ===
        self.debug("📈 Adding Stock Data (Databento)...")
        self.aapl_stock = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=False)
        self.aapl_stock.data_normalization_mode = DataNormalizationMode.RAW

        # === 2. 添加 OrderbookDepth 数据 (Kraken) ===
        # Note: Now using C# OrderbookDepth type which supports TICK resolution
        # IMPORTANT: Must specify Market.Kraken to match data file path: Data/crypto/kraken/tick/aaplxusd/
        self.debug("📊 Adding OrderbookDepth Data (Kraken)...")
        symbol = Symbol.create("AAPLxUSD", SecurityType.CRYPTO, Market.KRAKEN)
        self.debug(f"   Created Symbol: {symbol}, Market: {symbol.ID.Market}")
        self.aapl_depth = self.add_data(OrderbookDepth, symbol, Resolution.TICK)
        self.debug(f"   Added OrderbookDepth subscription for: {self.aapl_depth.Symbol}")
        self.debug(f"   Subscription returned type: {type(self.aapl_depth).__name__}")
        # self.aapl_depth = self.add_crypto("AAPLUSD", Resolution.TICK, Market.KRAKEN)
        # self.aapl_stock.data_normalization_mode = DataNormalizationMode.RAW

        # === 3. 创建数据收集器 ===
        self.debug("📊 Initializing Spread Collector...")
        self.collector = SpreadCollector(self)

        # === 4. 数据追踪 ===
        self.tick_count = 0
        self.depth_count = 0
        self.last_log_time = None

        # 缓存最新报价
        self.latest_stock_quote = None
        self.latest_depth = None

        self.debug("✅ Initialization complete!")

    def on_data(self, data: Slice):
        """处理数据 - 使用 OrderbookDepth"""
        try:
            # 调试：在第一次调用时打印OrderbookDepths的内容
            if self.tick_count == 0 and self.depth_count == 0:
                self.debug(f"First OnData call - OrderbookDepths count: {data.OrderbookDepths.Count}")
                if data.OrderbookDepths.Count > 0:
                    for symbol in data.OrderbookDepths.Keys:
                        self.debug(f"  OrderbookDepth available for: {symbol}")

            # 更新股票报价
            if self.aapl_stock.symbol in data.ticks:
                for tick in data.ticks[self.aapl_stock.symbol]:
                    if tick.tick_type == TickType.Quote and tick.bid_price > 0 and tick.ask_price > 0:
                        self.latest_stock_quote = tick
                        self.tick_count += 1

            # 更新 OrderbookDepth - 使用C#类型从Slice.OrderbookDepths访问
            if data.OrderbookDepths.ContainsKey(self.aapl_depth.Symbol):
                depth = data.OrderbookDepths[self.aapl_depth.Symbol]
                # C# OrderbookDepth对象，验证数据有效性
                if depth is not None and len(depth.Bids) > 0 and len(depth.Asks) > 0:
                    self.latest_depth = depth
                    self.depth_count += 1

                    # 如果有股票报价，计算价差
                    if self.latest_stock_quote is not None:
                        self.calculate_and_record_spread()
            elif self.depth_count == 0 and self.tick_count < 100:  # 前100个ticks期间检查
                # 调试：数据不存在
                if data.OrderbookDepths.Count == 0:
                    if self.tick_count == 10:  # 只打印一次
                        self.debug(f"⚠️ No OrderbookDepths in slice. Expected symbol: {self.aapl_depth.Symbol}")

            # 每小时输出一次状态
            if len(self.collector.spread_data) > 0:
                if self.last_log_time is None or (self.time - self.last_log_time).total_seconds() >= 3600:
                    _, spread_pct = self.collector.spread_data[-1]
                    self.debug(
                        f"📊 {self.time} | Stock Ticks: {self.tick_count:,} | "
                        f"Depth Updates: {self.depth_count:,} | "
                        f"Spread: {spread_pct*100:.2f}%"
                    )
                    self.last_log_time = self.time

        except Exception as e:
            self.error(f"❌ Error in on_data: {str(e)}")
            import traceback
            self.debug(traceback.format_exc())

    def calculate_and_record_spread(self):
        """
        计算并记录价差

        价差计算方式：
        - 使用 mid-price 计算，因为这是市场的真实中间价
        - Spread % = (Crypto Mid - Stock Mid) / Stock Mid

        交易逻辑：
        - 当 Spread < -1% 时：Crypto 相对便宜 -> Long Crypto, Short Stock
        - 当 Spread > 2% 时：Crypto 相对贵 -> 平仓获利
        """
        if self.latest_depth is None or self.latest_stock_quote is None:
            return

        # 获取 crypto 最佳 bid/ask (使用 C# OrderbookDepth 的属性)
        # C# OrderbookDepth.Bids 和 Asks 是 List<OrderbookLevel>
        # Bids[0] and Asks[0] 是最佳报价 (OrderbookLevel 对象)
        if len(self.latest_depth.Bids) == 0 or len(self.latest_depth.Asks) == 0:
            return

        best_bid = self.latest_depth.Bids[0]
        best_ask = self.latest_depth.Asks[0]

        crypto_bid_price = best_bid.Price
        crypto_ask_price = best_ask.Price

        # 获取 stock bid/ask
        stock_bid = self.latest_stock_quote.bid_price
        stock_ask = self.latest_stock_quote.ask_price

        # 数据验证
        if crypto_bid_price <= 0 or crypto_ask_price <= 0:
            return
        if stock_bid <= 0 or stock_ask <= 0:
            return
        if crypto_bid_price >= crypto_ask_price:  # 交叉报价检查
            return
        if stock_bid >= stock_ask:
            return

        # 计算 mid-price (或直接使用 C# 的 GetMidPrice() 方法)
        crypto_mid = float(self.latest_depth.GetMidPrice())
        stock_mid = (stock_bid + stock_ask) / 2

        # 计算价差百分比
        spread_pct = (crypto_mid - stock_mid) / stock_mid
        self.collector.add_spread_data(self.time, spread_pct)

    def on_end_of_algorithm(self):
        """算法结束 - 绘制价差走势图"""
        self.debug("\n" + "="*60)
        self.debug("📊 价差分析统计")
        self.debug("="*60)
        self.debug(f"股票Tick数: {self.tick_count:,}")
        self.debug(f"Depth更新数: {self.depth_count:,}")
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
        above_2 = sum(1 for s in spreads if s >= 2.0)
        total = len(spreads)

        self.debug(f"\n价差分布:")
        self.debug(f"  Spread <= -1%: {below_neg1:,} ({below_neg1/total*100:.1f}%) - 开仓机会")
        self.debug(f"  Spread >= 2%: {above_2:,} ({above_2/total*100:.1f}%) - 平仓机会")

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
            ax.axhline(y=2.0, color='red', linestyle='--', linewidth=1.5, label='Exit Threshold (2%)')

            # 填充区域
            ax.fill_between(timestamps, spreads, -1.0, where=[s <= -1.0 for s in spreads],
                           alpha=0.3, color='green', label='Entry Zone')
            ax.fill_between(timestamps, spreads, 2.0, where=[s >= 2.0 for s in spreads],
                           alpha=0.3, color='red', label='Exit Zone')

            # 格式化x轴日期
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.xaxis.set_minor_locator(mdates.HourLocator(interval=6))
            plt.xticks(rotation=45, ha='right')

            # 设置标签和标题
            ax.set_xlabel('Time (UTC)', fontsize=12)
            ax.set_ylabel('Spread %', fontsize=12)
            ax.set_title('AAPLUSD vs AAPL Spread Analysis (2025-09-02 to 2025-09-27)', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.legend(loc='best')

            # 调整布局
            plt.tight_layout()

            # 保存图表 - 使用绝对路径
            output_path = Path(r"C:\Users\Jagger\Documents\Code\Lean\arbitrage\tests\validate_data\AAPL_spread_analysis.png")
            plt.savefig(str(output_path), dpi=150, bbox_inches='tight')
            plt.close()

            self.debug(f"✅ 图表已保存至: {output_path}")

        except Exception as e:
            self.debug(f"❌ 绘图失败: {str(e)}")
            import traceback
            self.debug(traceback.format_exc())
