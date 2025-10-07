"""
简单策略集成测试 - 市价单版本

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLA/TSLAUSD, AAPL/AAPLUSD
- 日期范围: 2025-09-02 至 2025-09-05
- 策略: 简化版市价单套利
  - 开仓: spread <= -1% 时双市价单开仓 (long crypto + short stock)
  - 平仓: spread >= 2% 时双市价单平仓
  - 限制: 仅支持 long crypto + short stock (符合Kraken限制)
"""

import sys
from pathlib import Path
import math
from datetime import timedelta

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm
from SpreadManager import SpreadManager


class SimpleStrategy:
    """
    简单套利策略 - 市价单版本

    特点:
    - 仅使用市价单 (Kraken + IBKR 均为市价单)
    - 开仓条件: spread <= -1% 且无持仓
    - 平仓条件: spread >= 2% 且有持仓
    - 方向限制: 仅 long crypto + short stock
    """

    def __init__(self, algorithm: QCAlgorithm, spread_manager: SpreadManager,
                 entry_threshold: float = -0.01,
                 exit_threshold: float = 0.02,
                 position_size_pct: float = 0.25):
        """
        初始化策略

        Args:
            algorithm: QCAlgorithm实例
            spread_manager: SpreadManager实例
            entry_threshold: 开仓阈值 (负数, spread <= entry_threshold 时开仓, 默认-1%)
            exit_threshold: 平仓阈值 (正数, spread >= exit_threshold 时平仓, 默认2%)
            position_size_pct: 仓位大小百分比 (默认25%)
        """
        self.algorithm = algorithm
        self.spread_manager = spread_manager
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.position_size_pct = position_size_pct

        # 交易统计
        self.trade_count = 0
        self.open_count = 0
        self.close_count = 0
        self.trade_history = []

        # 持仓时间追踪
        self.open_times = {}  # {pair_symbol: open_time}
        self.holding_times = []  # 每次回转交易的持仓时间 (timedelta)

        # Pending orders tracking - 防止重复开仓/平仓
        self.pending_orders = {}  # {pair_symbol: {'type': 'OPEN'/'CLOSE', 'tickets': [...], 'time': ...}}

        self.algorithm.debug(
            f"SimpleStrategy initialized | "
            f"Entry: spread <= {self.entry_threshold*100:.2f}% | "
            f"Exit: spread >= {self.exit_threshold*100:.2f}% | "
            f"Position: {self.position_size_pct*100:.1f}%"
        )
        self.debug_count = 0

    def on_spread_update(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                        spread_pct: float, crypto_quote, stock_quote,
                        crypto_bid_price: float, crypto_ask_price: float):
        """
        处理spread更新

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            spread_pct: Spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
            crypto_bid_price: 我们的卖出限价 (未使用)
            crypto_ask_price: 我们的买入限价 (未使用)
        """
        pair_symbol = (crypto_symbol, stock_symbol)

        # 检查是否有pending订单 - 有pending就跳过，防止重复提交
        if pair_symbol in self.pending_orders:
            return

        # 检查真实持仓（使用portfolio）
        crypto_holding = self.algorithm.portfolio[crypto_symbol].quantity
        stock_holding = self.algorithm.portfolio[stock_symbol].quantity
        has_position = abs(crypto_holding) > 1.0 or abs(stock_holding) > 1.0

        # 开仓逻辑: spread <= entry_threshold (负数) 且无持仓
        if not has_position and spread_pct <= self.entry_threshold:
            self._open_position(pair_symbol, spread_pct, crypto_quote, stock_quote)

        # 平仓逻辑: spread >= exit_threshold (正数) 且有持仓
        elif has_position and spread_pct >= self.exit_threshold:
            self._close_position(pair_symbol, spread_pct, crypto_quote, stock_quote)
        
        self.debug_count += 1

    def cal_legs_and_multiple(self, pair_symbol: tuple, quantity: tuple, action: str = "TRADE"):
        quantity_int = (int(quantity[0]), int(quantity[1]))
        quantity_abs = (abs(quantity_int[0]), abs(quantity_int[1]))
        gcd = math.gcd(quantity_abs[0], quantity_abs[1])
        ratio = (quantity_int[0] // gcd, quantity_int[1] // gcd)

        legs = [
            Leg.create(pair_symbol[0], ratio[0]),
            Leg.create(pair_symbol[1], ratio[1]),
        ]

        # Debug输出
        self.algorithm.debug(
            f"🔧 cal_legs_and_multiple [{action}] | "
            f"Symbol: ({pair_symbol[0]}, {pair_symbol[1]}) | "
            f"Input: ({quantity[0]}, {quantity[1]}) | "
            f"GCD: {gcd} | "
            f"Ratio: ({ratio[0]}, {ratio[1]}) | "
            f"Result: {gcd}x({ratio[0]} {pair_symbol[0].value}, {ratio[1]} {pair_symbol[1].value})"
        )

        return legs, gcd
        
    def _open_position(self, pair_symbol: tuple, spread_pct: float,
                      crypto_quote, stock_quote):
        """
        开仓 - 使用 SpreadMarketOrder 实现市值对冲

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 计算仓位大小
        portfolio_value = self.algorithm.portfolio.total_portfolio_value
        target_value = portfolio_value * self.position_size_pct

        # 获取crypto价格 (使用ask价格，因为我们要买入)
        crypto_price = crypto_quote.ask_price
        stock_price = stock_price = stock_quote.bid_price

        if crypto_price == 0 or stock_price == 0:
            self.algorithm.debug(f"⚠️ Invalid prices: Crypto={crypto_price}, Stock={stock_price}")
            return

        crypto_qty = int(target_value / crypto_price)
        stock_qty = int(target_value / stock_price)

        # 调试日志：显示计算的数量
        self.algorithm.debug(
            f"📊 Order Calculation | "
            f"Portfolio: ${portfolio_value:,.0f} | Target: ${target_value:,.0f} ({self.position_size_pct*100}%) | "
            f"Crypto: {crypto_qty} @ ${crypto_price:.2f} | Stock: {stock_qty} @ ${stock_price:.2f}"
        )

        if crypto_qty == 0 or stock_qty == 0:
            self.algorithm.debug(f"⚠️ Invalid quantity: crypto_qty={crypto_qty}, stock_qty={stock_qty}")
            return

        legs, gcd = self.cal_legs_and_multiple(pair_symbol, (crypto_qty, -stock_qty), action="OPEN")
        # 提交 SpreadMarketOrder (全局倍数 = GCD)
        tickets = self.algorithm.spread_market_order(
            legs,
            gcd,
            tag=f"OPEN Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            # 提交失败，静默跳过（LEAN已输出Error日志）
            return

        # 记录pending订单，防止重复提交
        self.pending_orders[pair_symbol] = {
            'type': 'OPEN',
            'tickets': tickets,
            'time': self.algorithm.time
        }

        crypto_ticket = tickets[0]
        stock_ticket = tickets[1]

        # 记录交易
        self.open_count += 1
        self.trade_count += 1

        # 记录开仓时间
        self.open_times[pair_symbol] = self.algorithm.time

        self.trade_history.append({
            'time': self.algorithm.time,
            'type': 'OPEN',
            'pair': f"{crypto_symbol.value} <-> {stock_symbol.value}",
            'spread_pct': spread_pct,
            'crypto_qty': crypto_qty,
            'stock_qty': stock_qty,
            'crypto_price': crypto_price,
            'stock_price': stock_price,
            'crypto_order_id': crypto_ticket.order_id,
            'stock_order_id': stock_ticket.order_id
        })

        self.algorithm.debug(
            f"📈 OPEN #{self.open_count} | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}% | "
            f"Crypto: BUY {crypto_qty} @ ${crypto_price:.2f} = ${crypto_qty * crypto_price:,.0f} | "
            f"Stock: SELL {stock_qty} @ ${stock_price:.2f} = ${stock_qty * stock_price:,.0f}"
        )

    def _close_position(self, pair_symbol: tuple, spread_pct: float,
                       crypto_quote, stock_quote):
        """
        平仓 - 使用 SpreadMarketOrder 实现市值对冲

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前spread百分比
            crypto_quote: Crypto报价
            stock_quote: Stock报价
        """
        crypto_symbol, stock_symbol = pair_symbol

        # 从portfolio获取真实持仓数量
        crypto_qty = self.algorithm.portfolio[crypto_symbol].quantity
        stock_qty = self.algorithm.portfolio[stock_symbol].quantity

        if abs(crypto_qty) < 1.0 and abs(stock_qty) < 1.0:
            self.algorithm.debug(f"⚠️ No significant position to close for {pair_symbol}")
            return

        legs, gcd = self.cal_legs_and_multiple(pair_symbol, (-crypto_qty, -stock_qty), action="CLOSE")
        # 提交 SpreadMarketOrder (全局倍数 = GCD)
        tickets = self.algorithm.spread_market_order(
            legs,
            gcd,  # 全局倍数 = GCD (e.g., 75)
            tag=f"CLOSE Spread | {crypto_symbol.value}<->{stock_symbol.value} | Spread={spread_pct*100:.2f}%"
        )

        # 检查订单是否成功提交
        if len(tickets) < 2 or any(ticket.status == OrderStatus.Invalid for ticket in tickets):
            # 提交失败，静默跳过（LEAN已输出Error日志）
            return

        # === Debug: Order Value 详细信息 ===
        for ticket in tickets:
            order = self.algorithm.transactions.get_order_by_id(ticket.order_id)
            security = self.algorithm.securities[order.symbol]
            order_value = order.get_value(security)
            self.algorithm.debug(
                f"🔍 CLOSE Order Debug | {order.symbol.value} | "
                f"Qty={order.quantity} | Price=${order.price:.2f} | "
                f"OrderValue=${order_value:,.0f} | "
                f"Leverage={security.leverage} | "
                f"ContractMultiplier={security.symbol_properties.contract_multiplier} | "
                f"QuoteCurrency={security.quote_currency.symbol}"
            )

        # 记录pending订单，防止重复提交
        self.pending_orders[pair_symbol] = {
            'type': 'CLOSE',
            'tickets': tickets,
            'time': self.algorithm.time
        }

        crypto_ticket = tickets[0]
        stock_ticket = tickets[1]

        # 记录交易
        self.close_count += 1
        self.trade_count += 1

        # 计算持仓时间
        if pair_symbol in self.open_times:
            holding_time = self.algorithm.time - self.open_times[pair_symbol]
            self.holding_times.append(holding_time)
            del self.open_times[pair_symbol]

        self.trade_history.append({
            'time': self.algorithm.time,
            'type': 'CLOSE',
            'pair': f"{crypto_symbol.value} <-> {stock_symbol.value}",
            'spread_pct': spread_pct,
            'crypto_qty': crypto_qty,
            'stock_qty': stock_qty,
            'crypto_order_id': crypto_ticket.order_id,
            'stock_order_id': stock_ticket.order_id
        })

        # Get prices from quote data (use BID for selling crypto, ASK for buying stock)
        crypto_price = crypto_quote.bid_price  # Selling crypto at bid
        stock_price = stock_quote.ask_price    # Buying stock at ask
        crypto_qty_abs = abs(crypto_qty)
        stock_qty_abs = abs(stock_qty)

        self.algorithm.debug(
            f"📉 CLOSE #{self.close_count} | {self.algorithm.time} | "
            f"{crypto_symbol.value} <-> {stock_symbol.value} | "
            f"Spread: {spread_pct*100:.2f}% | "
            f"Crypto: SELL {crypto_qty_abs} @ ${crypto_price:.2f} = ${crypto_qty_abs * crypto_price:,.0f} | "
            f"Stock: BUY {stock_qty_abs} @ ${stock_price:.2f} = ${stock_qty_abs * stock_price:,.0f}"
        )

        # 立即设置仓位为0，防止重复平仓
        # on_order_event 会在订单成交时进一步更新（累加负数），但由于已经是0，结果仍接近0
        self.spread_manager.positions[pair_symbol] = {
            'token_qty': 0.0,
            'stock_qty': 0.0
        }


class SimpleStrategyTest(TestableAlgorithm):
    """简单策略集成测试"""

    def initialize(self):
        """初始化算法"""
        self.begin_test_phase("initialization")

        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 27)
        self.set_cash(100000)

        # 设置时区为UTC
        self.set_time_zone("UTC")

        # === 1. 添加股票数据 (Databento) ===
        self.debug("📈 Adding Stock Data (Databento)...")
        self.tsla_stock = self.add_equity("TSLA", Resolution.TICK, Market.USA, extended_market_hours=False)
        self.aapl_stock = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=False)

        self.tsla_stock.data_normalization_mode = DataNormalizationMode.RAW
        self.aapl_stock.data_normalization_mode = DataNormalizationMode.RAW

        # === 2. 添加加密货币数据 (Kraken) ===
        self.debug("🪙 Adding Crypto Data (Kraken)...")
        self.tsla_crypto = self.add_crypto("TSLAUSD", Resolution.TICK, Market.Kraken)
        self.aapl_crypto = self.add_crypto("AAPLUSD", Resolution.TICK, Market.Kraken)

        self.tsla_crypto.data_normalization_mode = DataNormalizationMode.RAW
        self.aapl_crypto.data_normalization_mode = DataNormalizationMode.RAW

        # === 3. 为加密货币设置 Kraken Fee Model ===
        self.debug("💰 Setting Crypto Fee Models (Kraken)...")
        from QuantConnect.Orders.Fees import KrakenFeeModel
        self.tsla_crypto.fee_model = KrakenFeeModel()
        self.aapl_crypto.fee_model = KrakenFeeModel()

        # === 4. 为股票设置 IBKR Fee Model ===
        self.debug("💵 Setting Stock Fee Models (Interactive Brokers)...")
        from QuantConnect.Orders.Fees import InteractiveBrokersFeeModel
        self.tsla_stock.fee_model = InteractiveBrokersFeeModel()
        self.aapl_stock.fee_model = InteractiveBrokersFeeModel()

        # === 5. 初始化 SpreadManager ===
        self.debug("📊 Initializing SpreadManager...")
        self.spread_manager = SpreadManager(
            algorithm=self,
            strategy=None,  # Will set later
            aggression=0.6
        )

        # === 6. 初始化简单策略 ===
        self.debug("📋 Initializing SimpleStrategy...")
        self.strategy = SimpleStrategy(
            algorithm=self,
            spread_manager=self.spread_manager,
            entry_threshold=-0.01,  # -1%
            exit_threshold=0.02,    # 2%
            position_size_pct=0.25  # 25%
        )

        # 链接策略到 SpreadManager
        self.spread_manager.strategy = self.strategy

        # === 7. 注册交易对 ===
        self.debug("🔗 Registering trading pairs...")
        self.spread_manager.add_pair(self.tsla_crypto, self.tsla_stock)
        self.spread_manager.add_pair(self.aapl_crypto, self.aapl_stock)

        # === 8. 数据追踪 ===
        self.tick_count = 0
        self.order_events = []

        # === 断言验证 ===
        self.assert_not_none(self.tsla_stock, "TSLA Stock Symbol 应该存在")
        self.assert_not_none(self.aapl_stock, "AAPL Stock Symbol 应该存在")
        self.assert_not_none(self.tsla_crypto, "TSLAUSD Crypto Symbol 应该存在")
        self.assert_not_none(self.aapl_crypto, "AAPLUSD Crypto Symbol 应该存在")

        pairs = self.spread_manager.get_all_pairs()
        self.assert_equal(len(list(pairs)), 2, "应该有2个交易对")

        self.checkpoint('initialization',
                       cash=100000,
                       pairs_count=len(list(self.spread_manager.get_all_pairs())),
                       tsla_stock=self.tsla_stock.symbol.value,
                       aapl_stock=self.aapl_stock.symbol.value,
                       tsla_crypto=str(self.tsla_crypto.symbol),
                       aapl_crypto=str(self.aapl_crypto.symbol))

        self.debug("✅ Initialization complete!")
        self.end_test_phase()

    def on_data(self, data: Slice):
        """处理数据 - 委托给SpreadManager处理"""
        if not data.ticks or len(data.ticks) == 0:
            return

        self.tick_count += 1

        # 委托给SpreadManager处理数据并监控价差
        self.spread_manager.on_data(data)

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        self.order_events.append(order_event)

        if order_event.status == OrderStatus.Filled:
            self.debug(
                f"✅ Order Filled | {order_event.symbol.value} | "
                f"Qty: {order_event.fill_quantity} @ ${order_event.fill_price:.2f}"
            )

            # === 打印 CashBook 信息 ===
            self.debug(f"💵 CashBook Status:")
            for currency, cash in self.portfolio.cash_book.items():
                self.debug(
                    f"  {currency}: Amount={cash.amount:,.2f}, "
                    f"ValueInAccountCurrency=${cash.value_in_account_currency:,.2f}, "
                    f"ConversionRate={cash.conversion_rate:.6f}"
                )

            # === 打印持仓信息 ===
            self.debug(f"📦 Portfolio Holdings:")
            for symbol, holding in self.portfolio.items():
                if holding.quantity != 0:
                    self.debug(
                        f"  {symbol.value}: Qty={holding.quantity}, "
                        f"AvgPrice=${holding.average_price:.2f}, "
                        f"MarketPrice=${holding.price:.2f}, "
                        f"MarketValue=${holding.holdings_value:,.2f}, "
                        f"UnrealizedPnL=${holding.unrealized_profit:,.2f}"
                    )

            # 更新仓位到SpreadManager
            # 查找对应的pair
            pair_symbol = None
            for crypto_sym, stock_sym in self.spread_manager.get_all_pairs():
                if order_event.symbol == crypto_sym or order_event.symbol == stock_sym:
                    pair_symbol = (crypto_sym, stock_sym)
                    break

            if pair_symbol:
                if pair_symbol not in self.spread_manager.positions:
                    self.spread_manager.positions[pair_symbol] = {
                        'token_qty': 0.0,
                        'stock_qty': 0.0
                    }

                # 更新仓位
                if order_event.symbol.security_type == SecurityType.Crypto:
                    self.spread_manager.positions[pair_symbol]['token_qty'] += order_event.fill_quantity
                elif order_event.symbol.security_type == SecurityType.Equity:
                    self.spread_manager.positions[pair_symbol]['stock_qty'] += order_event.fill_quantity

        # 检查并清除已完成的pending订单
        for pair_symbol, pending in list(self.strategy.pending_orders.items()):
            all_done = all(
                self.transactions.get_order_by_id(ticket.order_id).status in [
                    OrderStatus.Filled, OrderStatus.Canceled, OrderStatus.Invalid
                ]
                for ticket in pending['tickets']
            )
            if all_done:
                del self.strategy.pending_orders[pair_symbol]

    def on_end_of_algorithm(self):
        """算法结束 - 输出统计信息"""
        self.begin_test_phase("final_validation")

        # === 验证数据完整性 ===
        self.assert_greater(self.tick_count, 0, "应该接收到tick数据")

        # === 输出交易统计 ===
        self.debug("\n" + "="*60)
        self.debug("📊 交易统计")
        self.debug("="*60)
        self.debug(f"总Tick数: {self.tick_count:,}")
        self.debug(f"总交易次数: {self.strategy.trade_count}")
        self.debug(f"开仓次数: {self.strategy.open_count}")
        self.debug(f"平仓次数: {self.strategy.close_count}")
        self.debug(f"订单事件数: {len(self.order_events)}")

        # === 输出持仓时间统计 ===
        if self.strategy.holding_times:
            self.debug("\n" + "="*60)
            self.debug("⏱️  持仓时间统计")
            self.debug("="*60)

            # 计算统计数据
            min_holding = min(self.strategy.holding_times)
            max_holding = max(self.strategy.holding_times)
            avg_holding = sum(self.strategy.holding_times, timedelta()) / len(self.strategy.holding_times)

            self.debug(f"回转交易次数: {len(self.strategy.holding_times)}")
            self.debug(f"最短持仓时间: {min_holding}")
            self.debug(f"最长持仓时间: {max_holding}")
            self.debug(f"平均持仓时间: {avg_holding}")

            # 输出每次回转交易的持仓时间
            self.debug("\n详细持仓时间:")
            for i, holding_time in enumerate(self.strategy.holding_times, 1):
                self.debug(f"  #{i}: {holding_time}")
        else:
            self.debug("\n⚠️ 无持仓时间数据 (无完整的回转交易)")

        # === 输出交易历史 ===
        if self.strategy.trade_history:
            self.debug("\n" + "="*60)
            self.debug("📋 交易历史")
            self.debug("="*60)

            for trade in self.strategy.trade_history:
                self.debug(
                    f"{trade['time']} | {trade['type']} | {trade['pair']} | "
                    f"Spread: {trade['spread_pct']*100:.2f}%"
                )

        # === 输出最终仓位 ===
        self.debug("\n" + "="*60)
        self.debug("📦 最终仓位")
        self.debug("="*60)
        for pair_symbol, position in self.spread_manager.positions.items():
            crypto_sym, stock_sym = pair_symbol
            self.debug(
                f"{crypto_sym.value} <-> {stock_sym.value} | "
                f"Crypto: {position['token_qty']:.2f} | Stock: {position['stock_qty']:.2f}"
            )

        # === 输出账户状态 ===
        self.debug("\n" + "="*60)
        self.debug("💰 账户状态")
        self.debug("="*60)
        self.debug(f"Cash: ${self.portfolio.cash:,.2f}")
        self.debug(f"Total Portfolio Value: ${self.portfolio.total_portfolio_value:,.2f}")
        self.debug(f"Total Profit: ${self.portfolio.total_profit:,.2f}")

        # 验证 checkpoint
        self.verify_checkpoint('initialization', {
            'cash': 100000,
            'pairs_count': 2
        })

        self.debug("\n" + "="*60)
        self.debug("✅ 简单策略测试完成")
        self.debug("="*60)

        self.end_test_phase()

        # 调用父类输出测试结果
        super().on_end_of_algorithm()
