"""
账户状态持久化测试 - Account State Persistence Test

第一次运行：执行简单的4小时轮换交易策略，建立持仓，并保存状态到文件

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD, TSLA/TSLAxUSD
- 时间范围: 2025-09-02 至 2025-09-04
- 账户配置:
  * IBKR账户: $50,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Kraken账户: $50,000 - 交易加密货币 (Kraken market) - Margin模式 5x杠杆
- 交易策略: 每10秒轮换方向的简单策略
  - 0-10s: 不下单（等待数据稳定）
  - 10-20s: 开仓 Long Crypto + Short Stock
  - 20-30s: 切换到 Short Crypto + Long Stock
  - 30-40s: 切换回 Long Crypto + Short Stock
  - 以此类推，来回切换
- 从第20秒起始终保持持仓状态

测试目标:
- 执行简单的交易策略建立持仓
- 在算法结束时保存多账户状态到文件
- 为第二次运行（recovery.py）准备状态文件
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


class AccountPersistenceTest(QCAlgorithm):
    """账户状态持久化测试 - 第一次运行"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 4)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        self.debug("=" * 80)
        self.debug("💾 PERSISTENCE TEST - First Run")
        self.debug("=" * 80)

        # === 订阅交易对 ===
        self.debug("📡 Subscribing to trading pairs...")

        # 订阅 AAPL 交易对
        self.aapl_crypto = self.add_crypto("AAPLxUSD", Resolution.TICK, Market.Kraken)
        self.aapl_stock = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=True)
        self.debug(f"✅ Subscribed: AAPLxUSD (Kraken) <-> AAPL (USA)")

        # 订阅 TSLA 交易对
        self.tsla_crypto = self.add_crypto("TSLAxUSD", Resolution.TICK, Market.Kraken)
        self.tsla_stock = self.add_equity("TSLA", Resolution.TICK, Market.USA, extended_market_hours=True)
        self.debug(f"✅ Subscribed: TSLAxUSD (Kraken) <-> TSLA (USA)")

        # === 交易控制变量 ===
        self.trade_interval = timedelta(seconds=10)
        self.last_trade_time = None
        self.trade_count = 0

        # 当前目标持仓状态 (1 = Long Crypto + Short Stock, -1 = Short Crypto + Long Stock)
        self.target_position = 0

        self.debug("")
        self.debug("⏰ Trading Schedule:")
        self.debug("   0-10s:   No trading (waiting for data)")
        self.debug("   10-20s:  Open Long Crypto + Short Stock")
        self.debug("   20-30s:  Flip to Short Crypto + Long Stock")
        self.debug("   30-40s:  Flip to Long Crypto + Short Stock")
        self.debug("   ... continue flipping every 10 seconds")
        self.debug(f"✅ SaveState API available: {hasattr(self, 'save_state')}")
        self.debug("=" * 80)

    def on_data(self, data: Slice):
        """处理数据 - 每10秒执行一次交易"""
        # 添加日志：每5秒输出一次数据接收情况
        if not hasattr(self, '_last_log_time'):
            self._last_log_time = self.time
            self.debug(f"📊 First on_data call at {self.time}")
            self.debug(f"   Data count: {data.Count}")
            self.debug(f"   Has AAPL: {data.ContainsKey(self.aapl_stock.symbol)}")
            self.debug(f"   Has AAPLxUSD: {data.ContainsKey(self.aapl_crypto.symbol)}")
            self.debug(f"   Has TSLA: {data.ContainsKey(self.tsla_stock.symbol)}")
            self.debug(f"   Has TSLAxUSD: {data.ContainsKey(self.tsla_crypto.symbol)}")

        if (self.time - self._last_log_time).total_seconds() >= 5:
            self.debug(f"📊 on_data called at {self.time} | Data count: {data.Count} | Keys: {[str(k) for k in data.Keys]}")
            self._last_log_time = self.time

        # 检查是否到了交易时间
        if self.last_trade_time is None:
            self.last_trade_time = self.time
            return

        time_since_last_trade = self.time - self.last_trade_time

        if time_since_last_trade >= self.trade_interval:
            self.execute_trade()
            self.last_trade_time = self.time
            self.trade_count += 1

    def execute_trade(self):
        """执行交易"""
        self.debug("")
        self.debug("=" * 80)
        self.debug(f"⏰ Trade Interval #{self.trade_count} - Time: {self.time}")
        self.debug("=" * 80)

        if self.trade_count == 0:
            # 第一次不下单
            self.debug("🚫 First interval - No trading (waiting for data)")
            return

        if self.trade_count == 1:
            # 第二次开仓: Long Crypto + Short Stock
            self.debug("📈 Opening positions: Long Crypto + Short Stock")
            self.market_order(self.aapl_crypto.symbol, 1)
            self.market_order(self.aapl_stock.symbol, -1)
            self.market_order(self.tsla_crypto.symbol, 1)
            self.market_order(self.tsla_stock.symbol, -1)
            self.target_position = 1
        else:
            # 之后每次反向切换
            if self.target_position == 1:
                # 从 Long Crypto + Short Stock 切换到 Short Crypto + Long Stock
                self.debug("🔄 Flipping to: Short Crypto + Long Stock")
                self.market_order(self.aapl_crypto.symbol, -2)  # +1 -> -1
                self.market_order(self.aapl_stock.symbol, 2)    # -1 -> +1
                self.market_order(self.tsla_crypto.symbol, -2)
                self.market_order(self.tsla_stock.symbol, 2)
                self.target_position = -1
            else:
                # 从 Short Crypto + Long Stock 切换到 Long Crypto + Short Stock
                self.debug("🔄 Flipping to: Long Crypto + Short Stock")
                self.market_order(self.aapl_crypto.symbol, 2)   # -1 -> +1
                self.market_order(self.aapl_stock.symbol, -2)   # +1 -> -1
                self.market_order(self.tsla_crypto.symbol, 2)
                self.market_order(self.tsla_stock.symbol, -2)
                self.target_position = 1

        self.debug(f"✅ Orders placed for interval #{self.trade_count}")

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        if order_event.Status == OrderStatus.Filled:
            order = self.transactions.get_order_by_id(order_event.order_id)
            # Use new C# SaveState API
            self.save_state()
            self.debug(
                f"✅ Order Filled: {order.symbol.value} | "
                f"Qty: {order_event.fill_quantity} | "
                f"Price: ${order_event.fill_price:.2f} | "
                f"Account: {order_event.account_name if hasattr(order_event, 'account_name') else 'N/A'}"
            )
        elif order_event.Status == OrderStatus.Invalid:
            self.error(f"❌ Order Invalid: {order_event.message}")
            sys.exit(1)

    def on_end_of_algorithm(self):
        """算法结束 - 保存状态"""
        self.debug("")
        self.debug("=" * 80)
        self.debug("📊 Algorithm Ending - Saving State")
        self.debug("=" * 80)

        # 打印最终账户状态
        self.print_final_account_state()

        # 保存状态
        self.save_state_for_recovery()

        super().on_end_of_algorithm()

    def save_state_for_recovery(self):
        """保存状态以供恢复测试"""
        self.debug("")
        self.debug("=" * 80)
        self.debug("💾 Saving Multi-Account State (using C# SaveState)")
        self.debug("=" * 80)

        try:
            # Use new C# SaveState API
            self.save_state()

            # 读取并显示保存的内容
            from QuantConnect.Configuration import Config
            import json
            state_path = Config.Get("multi-account-persistence", "")

            if state_path:
                with open(state_path, 'r') as f:
                    saved_state = json.load(f)

                self.debug("")
                self.debug("📄 Saved State Summary:")
                self.debug(f"   File: {state_path}")
                self.debug(f"   Timestamp: {saved_state.get('Timestamp', 'N/A')}")
                self.debug(f"   Accounts: {list(saved_state.get('Accounts', {}).keys())}")

                for account_name, account_data in saved_state.get('Accounts', {}).items():
                    self.debug(f"   - {account_name}:")
                    self.debug(f"     Cash entries: {len(account_data.get('cash', []))}")
                    self.debug(f"     Holdings: {len(account_data.get('holdings', []))}")

                self.debug("")
                self.debug("📌 Next step: Run recovery.py to verify state recovery")

        except Exception as e:
            self.debug(f"❌ Error saving state: {e}")
            import traceback
            self.debug(traceback.format_exc())

        self.debug("=" * 80)

    def print_final_account_state(self):
        """打印最终账户状态"""
        self.debug("")
        self.debug("=" * 80)
        self.debug("💰 Final Multi-Account State")
        self.debug("=" * 80)

        if hasattr(self.Portfolio, 'SubAccounts'):
            multi_portfolio = self.Portfolio

            for account_name in multi_portfolio.SubAccounts.Keys:
                sub_account = multi_portfolio.GetAccount(account_name)

                self.debug(f"\n📊 Account: {account_name}")
                self.debug("-" * 80)

                # 现金
                self.debug("  💰 Cash:")
                for currency in sub_account.CashBook.Keys:
                    cash = sub_account.CashBook[currency]
                    self.debug(f"    {currency}: ${cash.Amount:,.2f}")

                # 持仓 - 使用全局Securities字典按market过滤
                self.debug("  📦 Holdings:")
                account_market = "kraken" if account_name == "Kraken" else "usa"
                holdings_count = 0

                for symbol in self.Securities.Keys:
                    security = self.Securities[symbol]
                    market_str = str(symbol.ID.Market).lower()

                    # Skip crypto (它们的持仓在现金中)
                    if symbol.SecurityType == SecurityType.Crypto:
                        continue

                    # 按market过滤
                    if market_str == account_market and security.Holdings.AbsoluteQuantity > 0:
                        holdings_count += 1
                        self.debug(
                            f"    {symbol.Value}: Qty={security.Holdings.Quantity}, "
                            f"AvgPrice=${security.Holdings.AveragePrice:.2f}, "
                            f"Value=${security.Holdings.HoldingsValue:,.2f}"
                        )

                if holdings_count == 0:
                    self.debug("    (No holdings)")

                # 账户价值
                self.debug(f"  💼 Total Portfolio Value: ${sub_account.TotalPortfolioValue:,.2f}")

        self.debug("=" * 80)
