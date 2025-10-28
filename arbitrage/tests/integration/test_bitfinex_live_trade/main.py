"""
Bitfinex Live Trading Test

测试场景:
- 运行模式: Live (live-paper or live)
- 数据源: Bitfinex
- 订阅交易对: BTCUSD (Bitcoin-US Dollar)
- 主要功能:
  1. 订阅 BTCUSD 行情并打印实时数据
  2. 定期打印 CashBook 和持仓信息

测试目标:
1. 验证 Bitfinex Brokerage 连接成功
2. 验证 BTCUSD 数据订阅和接收
3. 验证账户信息（CashBook, Holdings）
"""

from AlgorithmImports import *


class BitfinexLiveTest(QCAlgorithm):
    """Bitfinex 实时交易测试算法"""

    def initialize(self):
        """初始化算法"""
        # 设置起始日期（Live模式会被忽略）
        self.set_start_date(2025, 1, 1)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        self.debug("=" * 60)
        self.debug("🚀 Bitfinex Live Trading Test - Initializing")
        self.debug("=" * 60)

        # === 1. 订阅 BTCUSD (Bitfinex) ===
        self.debug("📡 Subscribing to BTCUSD on Bitfinex...")

        # 根据 symbol-properties-database.csv，Bitfinex 上的 BTC symbol 是 BTCUSD
        # 注意: Bitfinex 只支持 Minute 及以上分辨率，不支持 Tick
        self.btc_symbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Bitfinex)
        self.btc = self.add_crypto("BTCUSD", Resolution.Minute, Market.Bitfinex)

        self.debug(f"✅ Subscribed to: {self.btc_symbol.value}")
        self.debug(f"   Market: {self.btc_symbol.id.market}")
        self.debug(f"   Security Type: {self.btc_symbol.security_type}")

        # === 2. 设置定期打印任务 ===
        # 每10秒打印一次 CashBook 和持仓信息
        self.schedule.on(
            self.date_rules.every_day(),
            self.time_rules.every(timedelta(seconds=10)),
            self.print_portfolio_status
        )

        # 追踪数据更新次数
        self.data_update_count = 0
        self.last_price = None

        self.debug("=" * 60)
        self.debug("✅ Initialization Complete")
        self.debug("=" * 60)

    def on_data(self, data: Slice):
        """处理数据更新"""
        # 检查是否有 BTCUSD 的数据（Minute 分辨率通常使用 Bars 或 QuoteBars）
        if self.btc_symbol in data.bars:
            bar = data.bars[self.btc_symbol]
            self.data_update_count += 1
            self.last_price = bar.close

            # 每10次更新打印一次行情数据
            if self.data_update_count % 10 == 0:
                self.debug("")
                self.debug(f"📊 [{self.time}] BTCUSD Trade Bar:")
                self.debug(f"   Open: ${bar.open:,.2f}")
                self.debug(f"   High: ${bar.high:,.2f}")
                self.debug(f"   Low: ${bar.low:,.2f}")
                self.debug(f"   Close: ${bar.close:,.2f}")
                self.debug(f"   Volume: {bar.volume:,.2f}")
                self.debug(f"   Total Updates: {self.data_update_count}")

        elif self.btc_symbol in data.quote_bars:
            quote_bar = data.quote_bars[self.btc_symbol]
            self.data_update_count += 1
            self.last_price = quote_bar.close

            # 每10次更新打印一次行情数据
            if self.data_update_count % 10 == 0:
                self.debug("")
                self.debug(f"📊 [{self.time}] BTCUSD Quote Bar:")
                self.debug(f"   Bid: ${quote_bar.bid.close:,.2f}")
                self.debug(f"   Ask: ${quote_bar.ask.close:,.2f}")
                self.debug(f"   Close: ${quote_bar.close:,.2f}")
                self.debug(f"   Total Updates: {self.data_update_count}")

    def print_portfolio_status(self):
        """打印 CashBook 和持仓信息"""
        self.debug("")
        self.debug("=" * 60)
        self.debug(f"💰 Portfolio Status @ {self.time}")
        self.debug("=" * 60)

        # === 1. 打印 CashBook ===
        self.debug("📚 CashBook:")
        for currency_symbol, cash in self.portfolio.cash_book.items():
            if cash.amount != 0:
                self.debug(f"   {currency_symbol}: {cash.amount:,.8f} (${cash.value_in_account_currency:,.2f})")

        self.debug(f"   Total Cash: ${self.portfolio.cash:,.2f}")

        # === 2. 打印持仓 ===
        self.debug("")
        self.debug("📈 Holdings:")
        has_holdings = False
        for holding in self.portfolio.values():
            if holding.invested:
                has_holdings = True
                self.debug(f"   {holding.symbol.value}:")
                self.debug(f"     Quantity: {holding.quantity:,.8f}")
                self.debug(f"     Average Price: ${holding.average_price:,.2f}")
                self.debug(f"     Market Price: ${holding.price:,.2f}")
                self.debug(f"     Market Value: ${holding.holdings_value:,.2f}")
                self.debug(f"     Unrealized PnL: ${holding.unrealized_profit:,.2f}")

        if not has_holdings:
            self.debug("   (No positions)")

        # === 3. 打印总体信息 ===
        self.debug("")
        self.debug("📊 Portfolio Summary:")
        self.debug(f"   Total Portfolio Value: ${self.portfolio.total_portfolio_value:,.2f}")
        self.debug(f"   Total Holdings Value: ${self.portfolio.total_holdings_value:,.2f}")
        self.debug(f"   Total Margin Used: ${self.portfolio.total_margin_used:,.2f}")
        self.debug(f"   Total Unrealized Profit: ${self.portfolio.total_unrealized_profit:,.2f}")

        # === 4. 打印最新价格 ===
        if self.last_price:
            self.debug("")
            self.debug(f"💹 Latest BTCUSD Price: ${self.last_price:,.2f}")
            self.debug(f"   Data Updates Received: {self.data_update_count}")

        self.debug("=" * 60)

    def on_end_of_algorithm(self):
        """算法结束"""
        self.debug("")
        self.debug("=" * 60)
        self.debug("🏁 Bitfinex Live Test - Ending")
        self.debug("=" * 60)
        self.debug(f"Total Data Updates: {self.data_update_count}")
        self.debug(f"Final BTCUSD Price: ${self.last_price:,.2f}" if self.last_price else "No price data received")
        self.debug("=" * 60)
