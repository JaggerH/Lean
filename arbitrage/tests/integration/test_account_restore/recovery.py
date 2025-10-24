"""
账户状态恢复测试 - Account State Recovery Test

第二次运行：从持久化文件恢复状态，验证恢复效果，并继续执行交易

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: AAPL/AAPLxUSD, TSLA/TSLAxUSD
- 时间范围: 2025-09-04 至 2025-09-06
- 账户配置:
  * IBKR账户: 从持久化文件恢复
  * Kraken账户: 从持久化文件恢复
- 交易策略: 与 persistence.py 相同的10秒轮换策略

测试目标:
1. 从状态文件恢复现金和持仓
2. 验证恢复的状态与保存的状态一致
3. 继续执行交易策略，确保策略能正常运行

验证点:
- ✅ 多账户现金余额正确恢复
- ✅ 多账户持仓正确恢复
- ✅ 恢复后策略能继续正常运行
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


class AccountRecoveryTest(QCAlgorithm):
    """账户状态恢复测试 - 第二次运行"""

    def initialize(self):
        """初始化算法"""
        # 设置回测时间范围 - 从 persistence.py 结束的时间开始
        self.set_start_date(2025, 9, 4)
        self.set_end_date(2025, 9, 6)

        # 设置时区为UTC
        self.set_time_zone("UTC")
        self.set_benchmark(lambda x: 0)

        # 禁用最小订单过滤器，允许小额订单执行
        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.debug("⚙️ Disabled minimum order margin filter")

        self.debug("=" * 80)
        self.debug("🔄 RECOVERY TEST - Second Run")
        self.debug("=" * 80)

        # 检查状态文件是否存在
        from QuantConnect.Configuration import Config
        state_path = Config.Get("multi-account-persistence", "")
        if state_path:
            import os
            if os.path.exists(state_path):
                self.debug(f"📂 State file found: {state_path}")
                self.debug("✅ Will restore state and verify on first data slice")
            else:
                self.error(f"❌ State file not found: {state_path}")
                self.error("   Please run persistence.py first!")
                sys.exit(1)

        # === 订阅交易对 (与 persistence.py 相同) ===
        self.debug("📡 Subscribing to trading pairs...")

        # 订阅 AAPL 交易对
        self.aapl_crypto = self.add_crypto("AAPLxUSD", Resolution.TICK, Market.Kraken)
        self.aapl_stock = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=True)
        self.debug(f"✅ Subscribed: AAPLxUSD (Kraken) <-> AAPL (USA)")

        # 订阅 TSLA 交易对
        self.tsla_crypto = self.add_crypto("TSLAxUSD", Resolution.TICK, Market.Kraken)
        self.tsla_stock = self.add_equity("TSLA", Resolution.TICK, Market.USA, extended_market_hours=True)
        self.debug(f"✅ Subscribed: TSLAxUSD (Kraken) <-> TSLA (USA)")

        # === 状态验证变量 ===
        self.initial_state_captured = False
        self.initial_state_snapshot = None
        self.verification_passed = None

        # === 交易控制变量 (与 persistence.py 相同) ===
        self.trade_interval = timedelta(seconds=10)
        self.last_trade_time = None
        self.trade_count = 0

        # 当前目标持仓状态 (1 = Long Crypto + Short Stock, -1 = Short Crypto + Long Stock)
        # 注意: 这个值应该根据恢复的状态来确定
        self.target_position = 0

        # === 自动关闭设置 ===
        self.start_time = None
        self.auto_shutdown_seconds = 30
        self.debug(f"⏱️  Auto-shutdown: Algorithm will terminate after {self.auto_shutdown_seconds} seconds")

        self.debug("")
        self.debug("⏰ Trading Schedule (continuing from persistence.py):")
        self.debug("   Will continue 10-second flipping strategy")
        self.debug("=" * 80)

    def on_data(self, data: Slice):
        """处理数据 - 第一次捕获并验证状态，然后继续交易"""
        # 记录开始时间
        if self.start_time is None:
            self.start_time = self.time
            self.debug(f"⏱️  Start time recorded: {self.start_time}")

        # 检查是否到达自动关闭时间
        elapsed_seconds = (self.time - self.start_time).total_seconds()
        if elapsed_seconds >= self.auto_shutdown_seconds:
            self.debug("")
            self.debug("=" * 80)
            self.debug(f"⏱️  AUTO-SHUTDOWN: {self.auto_shutdown_seconds} seconds elapsed")
            self.debug(f"   Start: {self.start_time}")
            self.debug(f"   End: {self.time}")
            self.debug(f"   Duration: {elapsed_seconds:.1f}s")
            self.debug("=" * 80)
            self.quit()
            return

        # 第一次on_data时捕获并验证恢复的状态
        if not self.initial_state_captured:
            self.debug("")
            self.debug("📸 First data slice - Capturing and verifying restored state...")
            self.capture_and_verify_initial_state()
            self.initial_state_captured = True
            self.debug("✅ Verification complete, continuing with trading...")
            self.debug("")

        # 继续执行交易逻辑 (与 persistence.py 相同)
        if self.last_trade_time is None:
            self.last_trade_time = self.time
            return

        time_since_last_trade = self.time - self.last_trade_time

        if time_since_last_trade >= self.trade_interval:
            # self.execute_trade()
            self.last_trade_time = self.time
            self.trade_count += 1

    def capture_and_verify_initial_state(self):
        """捕获恢复后的初始状态并验证"""
        try:
            # 1. 捕获当前状态
            self.initial_state_snapshot = self.capture_current_state()

            # 2. 读取保存的状态文件
            from QuantConnect.Configuration import Config
            import json
            state_path = Config.Get("multi-account-persistence", "")

            with open(state_path, 'r') as f:
                saved_state = json.load(f)

            self.debug(f"📂 Loaded saved state from: {state_path}")
            self.debug(f"⏰ Saved state timestamp: {saved_state.get('Timestamp', 'N/A')}")

            # 3. 验证每个账户
            self.debug("")
            self.debug("=" * 80)
            self.debug("🔍 STATE RECOVERY VERIFICATION")
            self.debug("=" * 80)

            all_passed = True
            for account_name in self.initial_state_snapshot.keys():
                self.debug("")
                self.debug(f"🔍 Verifying account: {account_name}")
                self.debug("-" * 80)

                # 验证现金
                cash_passed = self.verify_cash_recovery(
                    account_name,
                    self.initial_state_snapshot[account_name]["cash"],
                    saved_state["Accounts"][account_name]["cash"]
                )

                # 验证持仓
                holdings_passed = self.verify_holdings_recovery(
                    account_name,
                    self.initial_state_snapshot[account_name]["holdings"],
                    saved_state["Accounts"][account_name]["holdings"]
                )

                # 打印恢复后的现金总值和持仓价值
                sub_account = self.Portfolio.GetAccount(account_name)

                # 调试：打印每个货币的 Amount 和 ConversionRate
                self.debug(f"  🔍 Debug - CashBook Details:")
                for currency in sub_account.CashBook.Keys:
                    cash = sub_account.CashBook[currency]
                    self.debug(f"     {currency}: Amount={cash.Amount:,.2f}, ConversionRate={cash.ConversionRate}, Value={cash.ValueInAccountCurrency:,.2f}")

                cash_value = float(sub_account.CashBook.TotalValueInAccountCurrency)

                # 计算该账户的持仓价值（从全局Securities中筛选）
                holdings_value = 0.0
                account_market = "kraken" if account_name == "Kraken" else "usa"
                for symbol in self.Securities.Keys:
                    security = self.Securities[symbol]
                    market_str = str(symbol.ID.Market).lower()
                    if symbol.SecurityType != SecurityType.Crypto and market_str == account_market:
                        holdings_value += float(security.Holdings.HoldingsValue)

                total_value = cash_value + holdings_value
                self.debug(f"  💼 Restored Account Value:")
                self.debug(f"     Cash: ${cash_value:,.2f}")
                self.debug(f"     Holdings: ${holdings_value:,.2f}")
                self.debug(f"     Total: ${total_value:,.2f}")

                if cash_passed and holdings_passed:
                    self.debug(f"✅ Account '{account_name}' - All verifications PASSED")
                else:
                    self.debug(f"❌ Account '{account_name}' - Some verifications FAILED")
                    all_passed = False

            # 打印主账户（Multi-Portfolio）的总价值
            if hasattr(self.Portfolio, 'SubAccounts'):
                self.debug("")
                self.debug("=" * 80)
                self.debug("💼 MASTER ACCOUNT (Multi-Portfolio)")
                self.debug("=" * 80)

                # 汇总所有子账户的现金和持仓
                # total_cash = 0.0
                # total_holdings = 0.0
                # for acc_name in self.Portfolio.SubAccounts.Keys:
                #     sub_acc = self.Portfolio.GetAccount(acc_name)
                #     total_cash += float(sub_acc.CashBook.TotalValueInAccountCurrency)

                # # 计算所有持仓价值（全局Securities）
                # for symbol in self.Securities.Keys:
                #     security = self.Securities[symbol]
                #     if symbol.SecurityType != SecurityType.Crypto:
                #         total_holdings += float(security.Holdings.HoldingsValue)

                # total_portfolio = total_cash + total_holdings
                
                total_cash = self.portfolio.CashBook.TotalValueInAccountCurrency
                total_holdings = 0.0
                total_portfolio = self.portfolio.total_portfolio_value
                self.debug(f"  Total Cash (All Accounts): ${total_cash:,.2f}")
                self.debug(f"  Total Holdings (All Accounts): ${total_holdings:,.2f}")
                self.debug(f"  Total Portfolio Value: ${total_portfolio:,.2f}")
                self.debug("=" * 80)

            # 最终结果
            self.debug("")
            self.debug("=" * 80)
            if all_passed:
                self.debug("✅✅✅ STATE RECOVERY TEST PASSED ✅✅✅")
                self.verification_passed = True
            else:
                self.debug("❌❌❌ STATE RECOVERY TEST FAILED ❌❌❌")
                self.verification_passed = False
            self.debug("=" * 80)

            # 4. 确定当前目标持仓状态（用于继续交易）
            self.determine_target_position()

        except Exception as e:
            self.debug(f"❌ Error during state verification: {e}")
            import traceback
            self.debug(traceback.format_exc())
            self.verification_passed = False

    def capture_current_state(self):
        """捕获当前的账户状态"""
        state_snapshot = {}

        if hasattr(self.Portfolio, 'SubAccounts'):
            multi_portfolio = self.Portfolio

            for account_name in multi_portfolio.SubAccounts.Keys:
                sub_account = multi_portfolio.GetAccount(account_name)

                # 记录现金
                cash_snapshot = {}
                for currency in sub_account.CashBook.Keys:
                    cash = sub_account.CashBook[currency]
                    cash_snapshot[currency] = float(cash.Amount)

                # 记录持仓 - 使用全局Securities字典按market过滤
                holdings_snapshot = {}
                account_market = "kraken" if account_name == "Kraken" else "usa"

                for symbol in self.Securities.Keys:
                    security = self.Securities[symbol]
                    market_str = str(symbol.ID.Market).lower()

                    # Skip crypto (它们的持仓在现金中)
                    if symbol.SecurityType == SecurityType.Crypto:
                        continue

                    # 按market过滤
                    if market_str == account_market and security.Holdings.AbsoluteQuantity > 0:
                        holdings_snapshot[str(symbol.Value)] = {
                            "quantity": float(security.Holdings.Quantity),
                            "average_price": float(security.Holdings.AveragePrice),
                            "market_value": float(security.Holdings.HoldingsValue)
                        }

                state_snapshot[account_name] = {
                    "cash": cash_snapshot,
                    "holdings": holdings_snapshot,
                    "total_portfolio_value": float(sub_account.TotalPortfolioValue)
                }

        return state_snapshot

    def verify_cash_recovery(self, account_name, restored_cash, saved_cash):
        """验证现金恢复"""
        self.debug("  💰 Cash Recovery Verification:")

        all_match = True
        for cash_entry in saved_cash:
            currency = cash_entry["Currency"]
            saved_amount = cash_entry["Amount"]
            restored_amount = restored_cash.get(currency, None)

            if restored_amount is None:
                self.debug(f"    ❌ {currency}: NOT FOUND in restored state")
                all_match = False
            elif abs(saved_amount - restored_amount) < 0.01:  # 允许微小浮点误差
                self.debug(f"    ✅ {currency}: ${saved_amount:,.2f} == ${restored_amount:,.2f}")
            else:
                self.debug(f"    ❌ {currency}: MISMATCH - Saved: ${saved_amount:,.2f}, Restored: ${restored_amount:,.2f}")
                all_match = False

        return all_match

    def verify_holdings_recovery(self, account_name, restored_holdings, saved_holdings):
        """验证持仓恢复"""
        self.debug("  📦 Holdings Recovery Verification:")

        if len(saved_holdings) == 0:
            self.debug("    ℹ️  No holdings to verify (empty portfolio)")
            return True

        all_match = True
        for holding_entry in saved_holdings:
            symbol_str = holding_entry["Symbol"]["Value"]
            saved_qty = holding_entry["Quantity"]
            saved_avg_price = holding_entry["AveragePrice"]

            restored_holding = restored_holdings.get(symbol_str, None)

            if restored_holding is None:
                self.debug(f"    ❌ {symbol_str}: NOT FOUND in restored state")
                all_match = False
            else:
                restored_qty = restored_holding["quantity"]
                restored_avg_price = restored_holding["average_price"]

                qty_match = abs(saved_qty - restored_qty) < 0.0001
                price_match = abs(saved_avg_price - restored_avg_price) < 0.01

                if qty_match and price_match:
                    self.debug(f"    ✅ {symbol_str}: Qty={saved_qty}, AvgPrice=${saved_avg_price:.2f}")
                else:
                    self.debug(f"    ❌ {symbol_str}: MISMATCH")
                    self.debug(f"       Saved: Qty={saved_qty}, AvgPrice=${saved_avg_price:.2f}")
                    self.debug(f"       Restored: Qty={restored_qty}, AvgPrice=${restored_avg_price:.2f}")
                    all_match = False

        return all_match

    def determine_target_position(self):
        """根据恢复的持仓确定当前目标持仓状态"""
        # 检查AAPL股票的持仓方向
        aapl_stock_holdings = self.Securities[self.aapl_stock.symbol].Holdings

        if aapl_stock_holdings.Quantity > 0:
            # Stock是Long -> 说明是 Short Crypto + Long Stock 状态
            self.target_position = -1
            self.debug("📊 Detected position state: Short Crypto + Long Stock")
        elif aapl_stock_holdings.Quantity < 0:
            # Stock是Short -> 说明是 Long Crypto + Short Stock 状态
            self.target_position = 1
            self.debug("📊 Detected position state: Long Crypto + Short Stock")
        else:
            # 没有持仓
            self.target_position = 0
            self.debug("📊 Detected position state: No positions")

    def execute_trade(self):
        """执行交易 (与 persistence.py 相同的逻辑)"""
        self.debug("")
        self.debug("=" * 80)
        self.debug(f"⏰ Trade Interval #{self.trade_count} - Time: {self.time}")
        self.debug("=" * 80)

        if self.trade_count == 0:
            # 第一次不下单
            self.debug("🚫 First interval - No trading (waiting for data)")
            return

        if self.target_position == 0:
            # 如果当前没有持仓，开仓
            self.debug("📈 Opening positions: Long Crypto + Short Stock")
            self.market_order(self.aapl_crypto.symbol, 1)
            self.market_order(self.aapl_stock.symbol, -1)
            self.market_order(self.tsla_crypto.symbol, 1)
            self.market_order(self.tsla_stock.symbol, -1)
            self.target_position = 1
        else:
            # 反向切换
            if self.target_position == 1:
                # 从 Long Crypto + Short Stock 切换到 Short Crypto + Long Stock
                self.debug("🔄 Flipping to: Short Crypto + Long Stock")
                self.market_order(self.aapl_crypto.symbol, -2)
                self.market_order(self.aapl_stock.symbol, 2)
                self.market_order(self.tsla_crypto.symbol, -2)
                self.market_order(self.tsla_stock.symbol, 2)
                self.target_position = -1
            else:
                # 从 Short Crypto + Long Stock 切换到 Long Crypto + Short Stock
                self.debug("🔄 Flipping to: Long Crypto + Short Stock")
                self.market_order(self.aapl_crypto.symbol, 2)
                self.market_order(self.aapl_stock.symbol, -2)
                self.market_order(self.tsla_crypto.symbol, 2)
                self.market_order(self.tsla_stock.symbol, -2)
                self.target_position = 1

        self.debug(f"✅ Orders placed for interval #{self.trade_count}")

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        if order_event.Status == OrderStatus.Filled:
            order = self.transactions.get_order_by_id(order_event.order_id)
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
        """算法结束 - 输出验证结果和最终统计"""
        self.debug("")
        self.debug("=" * 80)
        self.debug("📊 Algorithm Ending - Recovery Test Summary")
        self.debug("=" * 80)

        # 输出验证结果摘要
        if self.verification_passed is not None:
            self.debug("")
            self.debug("🔍 Verification Result:")
            if self.verification_passed:
                self.debug("   ✅ State recovery verification PASSED")
            else:
                self.debug("   ❌ State recovery verification FAILED")

        # 打印最终账户状态
        self.print_final_account_state()

        super().on_end_of_algorithm()

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

                # 账户价值（现金 + 持仓）
                cash_value = float(sub_account.CashBook.TotalValueInAccountCurrency)
                holdings_value = 0.0
                for symbol in self.Securities.Keys:
                    security = self.Securities[symbol]
                    market_str = str(symbol.ID.Market).lower()
                    if symbol.SecurityType != SecurityType.Crypto and market_str == account_market:
                        holdings_value += float(security.Holdings.HoldingsValue)

                total_value = cash_value + holdings_value
                self.debug(f"  💼 Account Value:")
                self.debug(f"     Cash: ${cash_value:,.2f}")
                self.debug(f"     Holdings: ${holdings_value:,.2f}")
                self.debug(f"     Total: ${total_value:,.2f}")

            # 打印主账户（Multi-Portfolio）的总价值
            self.debug("")
            self.debug("=" * 80)
            self.debug("💼 MASTER ACCOUNT (Multi-Portfolio)")
            self.debug("=" * 80)

            # 汇总所有子账户的现金和持仓
            total_cash = self.portfolio.CashBook.TotalValueInAccountCurrency
            total_holdings = 0.0
            # for acc_name in multi_portfolio.SubAccounts.Keys:
            #     sub_acc = multi_portfolio.GetAccount(acc_name)
            #     total_cash += float(sub_acc.CashBook.TotalValueInAccountCurrency)

            # # 计算所有持仓价值（全局Securities）
            # for symbol in self.Securities.Keys:
            #     security = self.Securities[symbol]
            #     if symbol.SecurityType != SecurityType.Crypto:
            #         total_holdings += float(security.Holdings.HoldingsValue)

            total_portfolio = self.portfolio.total_portfolio_value
            self.debug(f"  Total Cash (All Accounts): ${total_cash:,.2f}")
            self.debug(f"  Total Holdings (All Accounts): ${total_holdings:,.2f}")
            self.debug(f"  Total Portfolio Value: ${total_portfolio:,.2f}")

        self.debug("=" * 80)
