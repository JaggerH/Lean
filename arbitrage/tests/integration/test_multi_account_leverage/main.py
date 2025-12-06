"""
多账户杠杆比率验证集成测试 - Multi-Account Leverage Ratio Verification

测试场景:
- 数据源: Databento (股票) + Gate.io (加密货币)
- 交易品种: TSLA (股票) + BTCUSDT (加密货币)
- 日期范围: 2025-09-02 至 2025-09-05
- 账户配置:
  * IBKR账户: $10,000 - 交易股票 (USA market) - Margin模式 2x杠杆
  * Gate账户: $10,000 - 交易加密货币 (Gate market) - Margin模式 3x杠杆

测试目标:
1. 验证各子账户的杠杆比率正确设置
2. 测试在最大杠杆时的交易能成功
3. 验证略高于杠杆比例的订单被拒绝
4. 验证略低于杠杆比例的订单成功
5. 验证每个子账户独立计算买入力
"""

import sys
from pathlib import Path
from datetime import timedelta

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from testing.testable_algorithm import TestableAlgorithm


class MultiAccountLeverageTest(TestableAlgorithm):
    """多账户杠杆比率验证测试"""

    def initialize(self):
        """初始化算法"""
        self.begin_test_phase("initialization")

        # 设置回测时间范围
        self.set_start_date(2025, 9, 2)
        self.set_end_date(2025, 9, 5)
        self.set_time_zone("UTC")

        # === 杠杆配置 ===
        self.leverage_config = {
            'IBKR': 2.0,   # IBKR 股票2x杠杆
            'Gate': 3.0    # Gate 加密货币3x杠杆
        }

        # === 1. 添加股票数据 (Databento) - 应路由到 IBKR 账户 ===
        self.debug("📈 Adding Stock Data (TSLA) - will route to IBKR account...")
        self.tsla = self.add_equity("TSLA", Resolution.MINUTE, Market.USA, extended_market_hours=False)
        self.tsla.data_normalization_mode = DataNormalizationMode.RAW

        # === 2. 添加加密货币数据 (Gate) - 应路由到 Gate 账户 ===
        self.debug("🪙 Adding Crypto Data (BTCUSDT) - will route to Gate account...")
        self.btc = self.add_crypto("BTCUSDT", Resolution.MINUTE, Market.Gate)
        self.btc.data_normalization_mode = DataNormalizationMode.RAW

        # === 3. 验证多账户配置 ===
        self.debug("="*60)
        self.debug("🔍 Verifying Multi-Account Configuration")
        self.debug("="*60)

        if hasattr(self.portfolio, 'GetAccount'):
            self.debug("✅ Multi-Account Portfolio Detected!")

            # 显示子账户信息
            try:
                ibkr_account = self.portfolio.GetAccount("IBKR")
                gate_account = self.portfolio.GetAccount("Gate")

                self.debug(f"📊 IBKR Account Cash: ${ibkr_account.Cash:,.2f} | Leverage: {self.leverage_config['IBKR']}x")
                self.debug(f"📊 Gate Account Cash: ${gate_account.Cash:,.2f} | Leverage: {self.leverage_config['Gate']}x")
                self.debug(f"📊 Total Portfolio Cash: ${self.portfolio.Cash:,.2f}")

                # 验证账户配置
                self.assert_equal(ibkr_account.Cash, 10000, "IBKR账户初始现金应为$10,000")
                self.assert_equal(gate_account.Cash, 10000, "Gate账户初始现金应为$10,000")
                self.assert_equal(self.portfolio.Cash, 20000, "总现金应为$20,000")

            except Exception as e:
                self.debug(f"❌ Error accessing multi-account: {e}")
                self.error(f"Multi-account configuration failed: {e}")
        else:
            self.error("Multi-account portfolio not initialized - check config.json")

        # === 4. 验证杠杆设置 ===
        self.debug("="*60)
        self.debug("🔍 Verifying Leverage Configuration")
        self.debug("="*60)
        self._verify_leverage()
        self.debug("="*60)

        # === 5. 测试追踪 ===
        self.test_executed = False
        self.test_results = {
            'high_leverage_order_rejected': False,
            'safe_leverage_order_accepted': False,
            'ibkr_leverage_verified': False,
            'gate_leverage_verified': False
        }

        self.debug("✅ Initialization complete!")
        self.end_test_phase()

    def _verify_leverage(self):
        """验证杠杆设置"""
        # 验证TSLA (IBKR)
        tsla_leverage = self.tsla.leverage
        self.debug(f"TSLA Leverage: {tsla_leverage}x (Expected: {self.leverage_config['IBKR']}x)")
        self.assert_equal(tsla_leverage, self.leverage_config['IBKR'],
                         f"TSLA leverage应为{self.leverage_config['IBKR']}x")

        # 验证BTC (Gate)
        btc_leverage = self.btc.leverage
        self.debug(f"BTCUSDT Leverage: {btc_leverage}x (Expected: {self.leverage_config['Gate']}x)")
        self.assert_equal(btc_leverage, self.leverage_config['Gate'],
                         f"BTCUSDT leverage应为{self.leverage_config['Gate']}x")

        self.test_results['ibkr_leverage_verified'] = True
        self.test_results['gate_leverage_verified'] = True

    def on_data(self, data: Slice):
        """测试杠杆比率"""
        if self.test_executed:
            return

        # 等待有足够的价格数据
        if not data.bars.contains_key(self.tsla.symbol) or not data.bars.contains_key(self.btc.symbol):
            return

        self.test_executed = True
        self.begin_test_phase("leverage_testing")

        tsla_price = data.bars[self.tsla.symbol].close
        btc_price = data.bars[self.btc.symbol].close

        self.debug("="*60)
        self.debug("🧪 Testing Leverage Ratios")
        self.debug("="*60)
        self.debug(f"TSLA Price: ${tsla_price:.2f}")
        self.debug(f"BTCUSDT Price: ${btc_price:.2f}")

        # === 测试 1: IBKR 略高于杠杆比例 (应失败) ===
        ibkr_account = self.portfolio.GetAccount("IBKR")
        ibkr_cash = ibkr_account.Cash
        ibkr_leverage = self.leverage_config['IBKR']

        # 计算最大买入力 = 现金 * 杠杆
        max_buying_power = ibkr_cash * ibkr_leverage

        # 尝试买入略高于最大买入力的金额 (105%)
        high_quantity = int((max_buying_power * 1.05) / tsla_price)

        self.debug(f"\n📋 Test 1: IBKR High Leverage Order")
        self.debug(f"  Cash: ${ibkr_cash:,.2f}")
        self.debug(f"  Leverage: {ibkr_leverage}x")
        self.debug(f"  Max Buying Power: ${max_buying_power:,.2f}")
        self.debug(f"  Attempting to buy {high_quantity} shares @ ${tsla_price:.2f} = ${high_quantity * tsla_price:,.2f}")

        # 这个订单应该被拒绝
        has_sufficient_capital_high = self.portfolio.GetAccount("IBKR").HasSufficientBuyingPowerForOrder(
            self.portfolio.securities[self.tsla.symbol],
            MarketOrder(self.tsla.symbol, high_quantity, self.time)
        )

        if not has_sufficient_capital_high.is_sufficient:
            self.debug(f"  ✅ Order correctly rejected: {has_sufficient_capital_high.reason}")
            self.test_results['high_leverage_order_rejected'] = True
        else:
            self.debug(f"  ❌ Order should have been rejected but was accepted!")

        # === 测试 2: IBKR 略低于杠杆比例 (应成功) ===
        safe_quantity = int((max_buying_power * 0.95) / tsla_price)

        self.debug(f"\n📋 Test 2: IBKR Safe Leverage Order")
        self.debug(f"  Attempting to buy {safe_quantity} shares @ ${tsla_price:.2f} = ${safe_quantity * tsla_price:,.2f}")

        has_sufficient_capital_safe = self.portfolio.GetAccount("IBKR").HasSufficientBuyingPowerForOrder(
            self.portfolio.securities[self.tsla.symbol],
            MarketOrder(self.tsla.symbol, safe_quantity, self.time)
        )

        if has_sufficient_capital_safe.is_sufficient:
            self.debug(f"  ✅ Order correctly accepted")
            self.test_results['safe_leverage_order_accepted'] = True
            # 执行订单
            self.market_order(self.tsla.symbol, safe_quantity)
        else:
            self.debug(f"  ❌ Order should have been accepted: {has_sufficient_capital_safe.reason}")

        # === 测试 3: Gate 略高于杠杆比例 (应失败) ===
        gate_account = self.portfolio.GetAccount("Gate")
        gate_cash = gate_account.Cash
        gate_leverage = self.leverage_config['Gate']

        max_buying_power_gate = gate_cash * gate_leverage
        high_quantity_btc = (max_buying_power_gate * 1.05) / btc_price

        self.debug(f"\n📋 Test 3: Gate High Leverage Order")
        self.debug(f"  Cash: ${gate_cash:,.2f}")
        self.debug(f"  Leverage: {gate_leverage}x")
        self.debug(f"  Max Buying Power: ${max_buying_power_gate:,.2f}")
        self.debug(f"  Attempting to buy {high_quantity_btc:.8f} BTC @ ${btc_price:.2f} = ${high_quantity_btc * btc_price:,.2f}")

        has_sufficient_capital_btc_high = self.portfolio.GetAccount("Gate").HasSufficientBuyingPowerForOrder(
            self.portfolio.securities[self.btc.symbol],
            MarketOrder(self.btc.symbol, high_quantity_btc, self.time)
        )

        if not has_sufficient_capital_btc_high.is_sufficient:
            self.debug(f"  ✅ Order correctly rejected: {has_sufficient_capital_btc_high.reason}")
        else:
            self.debug(f"  ❌ Order should have been rejected but was accepted!")

        # === 测试 4: Gate 略低于杠杆比例 (应成功) ===
        safe_quantity_btc = (max_buying_power_gate * 0.95) / btc_price

        self.debug(f"\n📋 Test 4: Gate Safe Leverage Order")
        self.debug(f"  Attempting to buy {safe_quantity_btc:.8f} BTC @ ${btc_price:.2f} = ${safe_quantity_btc * btc_price:,.2f}")

        has_sufficient_capital_btc_safe = self.portfolio.GetAccount("Gate").HasSufficientBuyingPowerForOrder(
            self.portfolio.securities[self.btc.symbol],
            MarketOrder(self.btc.symbol, safe_quantity_btc, self.time)
        )

        if has_sufficient_capital_btc_safe.is_sufficient:
            self.debug(f"  ✅ Order correctly accepted")
            # 执行订单
            self.market_order(self.btc.symbol, safe_quantity_btc)
        else:
            self.debug(f"  ❌ Order should have been accepted: {has_sufficient_capital_btc_safe.reason}")

        self.debug("="*60)
        self.end_test_phase()

    def on_order_event(self, order_event: OrderEvent):
        """处理订单事件"""
        if order_event.status == OrderStatus.Filled:
            self.debug(
                f"✅ Order Filled | {order_event.symbol.value} | "
                f"Qty: {order_event.fill_quantity} @ ${order_event.fill_price:.2f}"
            )

    def on_end_of_algorithm(self):
        """验证测试结果"""
        self.begin_test_phase("final_validation")

        self.debug("="*60)
        self.debug("📊 Test Results")
        self.debug("="*60)

        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            self.debug(f"{test_name}: {status}")

        # 验证所有测试通过
        all_passed = all(self.test_results.values())

        if all_passed:
            self.debug("\n✅ ALL TESTS PASSED!")
        else:
            self.error("\n❌ SOME TESTS FAILED!")

        self.debug("="*60)
        self.end_test_phase()
        super().on_end_of_algorithm()
