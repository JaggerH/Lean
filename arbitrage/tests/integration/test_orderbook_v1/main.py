"""
多账户Margin模式集成测试 - Multi-Account Portfolio Manager with Margin

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLA/TSLAUSD, AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-05
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 路由策略: Market-based routing (基于Symbol.ID.Market)
- 策略: 简化版市价单套利
  - 开仓: spread <= -1% 时双市价单开仓 (long crypto + short stock)
  - 平仓: spread >= 2% 时双市价单平仓
  - 限制: 仅支持 long crypto + short stock (符合Kraken限制)

测试目标:
1. 验证多账户Margin模式配置正确初始化
2. 验证每个Security使用Margin BuyingPowerModel
3. 验证杠杆倍数设置正确 (股票2x, 加密货币5x)
4. 验证订单自动路由到正确账户 (crypto->Kraken, stock->IBKR)
5. 验证Margin模式下的买入力计算
6. 验证Fill更新正确的子账户
7. 验证账户间现金和持仓隔离
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
from strategy.base_strategy import BaseStrategy
from strategy.long_crypto_strategy import LongCryptoStrategy
from order_tracker import OrderTracker as EnhancedOrderTracker
from QuantConnect.Data.Market import OrderbookDepth
from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel, KrakenFeeModel
from data_source import KrakenSymbolManager

class OrderBookTest(QCAlgorithm):
    """多账户Margin模式集成测试"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        # self.set_brokerage_model(BrokerageName.Kraken, AccountType.Cash)
        self.set_benchmark(lambda x: 0)

        # === 1. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(
            algorithm=self,
            strategy=None  # Will set later
        )

        # === 2. 初始化做多加密货币策略 ===
        self.debug("📋 Initializing LongCryptoStrategy...")
        self.strategy = LongCryptoStrategy(
            algorithm=self,
            spread_manager=self.spread_manager,
            entry_threshold=-0.01,  # -1%
            exit_threshold=0.02,    # 2%
            position_size_pct=0.80  # 80% (考虑杠杆和费用)
        )

        # 链接策略到 SpreadManager
        self.spread_manager.strategy = self.strategy

        # === 3. 订阅交易对（使用 subscribe_trading_pair 简化代码）===
        self.debug("🔗 Subscribing to trading pairs...")
        crypto_symbol = Symbol.Create("AAPLxUSD", SecurityType.Crypto, Market.Kraken)
        stock_symbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA)

        self.aapl_crypto, self.aapl_stock = self.spread_manager.subscribe_trading_pair(
            pair_symbol=(crypto_symbol, stock_symbol),
        )

        self.debug(f"✅ Subscribed: {crypto_symbol.value} <-> {stock_symbol.value}")

        self.tick_count = 0
        # === 11. 初始化独立的订单追踪器 (Enhanced Version) ===
        self.debug("📊 Initializing EnhancedOrderTracker for independent order verification...")
        self.order_tracker = EnhancedOrderTracker(self, self.strategy)

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return

        self.tick_count += 1

        # 委托给SpreadManager处理数据并监控价差
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件 - 验证多账户路由"""
        # 委托给 Strategy 的 on_order_event 处理订单事件
        self.strategy.on_order_event(order_event)

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息和验证多账户Margin模式行为"""
        super().on_end_of_algorithm()
        
        self.debug(f"ohhhhhh {self.tick_count}")
