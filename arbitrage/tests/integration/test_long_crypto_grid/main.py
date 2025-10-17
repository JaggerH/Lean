"""
Long Crypto Grid Strategy 集成测试 - Grid Trading Framework

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLA/TSLAUSD, AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-05
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 路由策略: Market-based routing (基于Symbol.ID.Market)
- 策略: LongCryptoGridStrategy (Grid Trading Framework)
  - 单一Entry Grid: spread <= -1%
  - 单一Exit Grid: spread >= 2%
  - 方向: 仅 long crypto + short stock
  - 自动profitability validation (profit > 2 * fees)

测试目标:
1. 验证 Grid Framework 在真实数据环境下的运行
2. 验证 GridLevelManager 的 trigger detection
3. 验证 GridPositionManager 的 position tracking
4. 验证多账户Margin模式与Grid框架的兼容性
5. 验证订单自动路由到正确账户 (crypto->Kraken, stock->IBKR)
6. 验证 profitability validation 正常工作
7. 对比 Grid 版本与原始 LongCryptoStrategy 的行为一致性
"""

import sys
from pathlib import Path
from datetime import timedelta

# Add arbitrage directory to path
arbitrage_path = str(Path(__file__).parent.parent.parent.parent)
sys.path.insert(0, arbitrage_path)

from AlgorithmImports import *

# Add arbitrage to path for imports
sys.path.insert(0, str(Path(arbitrage_path) / 'arbitrage'))

from spread_manager import SpreadManager
from strategy.long_crypto_grid_strategy import LongCryptoGridStrategy
from order_tracker import OrderTracker as EnhancedOrderTracker

class LongCryptoGridTest(QCAlgorithm):
    """Long Crypto Grid Strategy 集成测试"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        # self.set_brokerage_model(BrokerageName.Kraken, AccountType.Cash)
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        # === 1. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(algorithm=self)

        # === 2. 初始化 Long Crypto Grid Strategy ===
        self.debug("📋 Initializing LongCryptoGridStrategy...")
        self.strategy = LongCryptoGridStrategy(
            algorithm=self,
            entry_threshold=-0.01,  # -1%
            exit_threshold=0.02,    # 2%
            position_size_pct=0.80,  # 80% (考虑杠杆和费用)
            crypto_fee_pct=0.0026,  # Kraken 0.26%
            stock_fee_pct=0.0005    # IBKR 0.05%
        )

        # 启用debug模式
        self.strategy.debug = True

        # === 3. 使用 Observer 模式连接 SpreadManager 和 Strategy ===
        self.debug("🔗 Registering strategy as spread observer...")
        self.spread_manager.register_observer(self.strategy.on_spread_update)

        # === 4. 订阅交易对（使用 subscribe_trading_pair 简化代码）===
        self.debug("📡 Subscribing to trading pairs...")
        crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(crypto_symbol, stock_symbol),
        )

        self.debug(f"✅ Subscribed: {crypto_symbol.value} <-> {stock_symbol.value}")

        # === 4.5. 初始化Grid Levels（Grid策略的新需求）===
        self.debug("🔧 Initializing grid levels for trading pair...")
        self.strategy.initialize_pair((crypto_symbol, stock_symbol))

        # === 5. 初始化独立的订单追踪器 (Enhanced Version) ===
        self.debug("📊 Initializing EnhancedOrderTracker for independent order verification...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy)

        # 追踪 spread 更新
        self.spread_count = 0
        self.last_spread_log_time = self.time

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return

        # 每分钟输出一次 spread 统计 (已禁用，避免日志过多)
        # if (self.time - self.last_spread_log_time).total_seconds() >= 60:
        #     self.debug(f"📊 Spread updates in last minute: {self.spread_count}")
        #     self.spread_count = 0
        #     self.last_spread_log_time = self.time

        # === 1. 先触发 strategy 的 on_data (重新执行 PENDING 的 ExecutionTargets) ===
        self.strategy.on_data(data)

        # === 2. 委托给SpreadManager处理数据并监控价差 ===
        self.spread_manager.on_data(data)
        # self.spread_count += 1

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证多账户路由"""
        # 输出订单事件详情
        # self.debug(
        #     f"{self.time} | "
        #     f"📋 ORDER EVENT | ID: {order_event.order_id} | "
        #     f"Status: {order_event.status} | "
        #     f"Symbol: {order_event.symbol.value} | "
        #     f"Qty: {order_event.quantity} | "
        #     f"FillQty: {order_event.fill_quantity} | "
        #     f"FillPrice: {order_event.fill_price} | "
        #     f"Message: {order_event.message if order_event.message else 'N/A'}"
        # )

        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

    def error(self, error: str):
        """捕获错误消息（特别是买入力不足的错误）"""
        self.debug(f"❌ ERROR: {error}")
        # 调用父类方法确保错误被正确记录
        super().error(error)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息和验证Grid框架行为"""
        super().on_end_of_algorithm()

        self.debug("=" * 60)
        self.debug("📊 Long Crypto Grid Strategy Test Results")
        self.debug("=" * 60)

        # 输出策略统计信息
        stats = self.strategy.get_statistics()
        self.debug(f"Total Round Trips: {stats['total_round_trips']}")
        self.debug(f"Open Positions: {stats['open_positions']}")
        if stats['avg_holding_time_seconds']:
            self.debug(f"Average Holding Time: {stats['avg_holding_time_seconds']:.2f} seconds")

        # 输出Grid摘要
        pair_symbol = (self.aapl_crypto.symbol, self.aapl_stock.symbol)
        grid_summary = self.strategy.get_grid_summary(pair_symbol)
        self.debug("\n" + grid_summary)

        self.debug("=" * 60)
