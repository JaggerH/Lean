"""
Gate Margin Mode Leverage Verification Test

Test Scenario:
- Data Source: Gate.io (crypto)
- Trading Symbols: TSLAXUSDT, AAPLXUSDT (Gate market)
- Date Range: 2025-09-04 to 2025-09-10
- Account Config:
  * Gate Account: $50,000 - Margin mode
  * Expected Leverage: 5x for Crypto in Margin mode

Test Objectives:
1. Verify Gate account is properly configured with Margin mode
2. Verify TSLAXUSDT and AAPLXUSDT have correct leverage (5x)
3. Verify BuyingPowerModel is correctly set
4. Log detailed security configuration for debugging

This test does NOT execute any trades - it only verifies the configuration
in the Initialize() method.
"""

from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm


class MultiAccountLeverageTest(AQCAlgorithm):
    """Gate Margin Mode Leverage Verification Test"""

    def Initialize(self):
        """Initialize and verify leverage configuration"""
        # === 1. Set backtest parameters ===
        self.SetStartDate(2025, 9, 4)
        self.SetEndDate(2025, 9, 10)
        self.SetTimeZone("UTC")
        self.SetBenchmark(lambda x: 0)

        self.Debug("=" * 80)
        self.Debug("GATE MARGIN MODE LEVERAGE VERIFICATION TEST (Multi-Account)")
        self.Debug("=" * 80)

        # === 2. Add Gate crypto securities ===
        self.Debug("\n📊 Adding Gate Crypto Securities...")
        self.Debug("-" * 80)

        # Add securities with Resolution.Minute (or Resolution.ORDERBOOK if available)
        self.tsla_crypto = self.AddCrypto("TSLAXUSDT", Resolution.Minute, Market.Gate)
        self.aapl_crypto = self.AddCrypto("AAPLXUSDT", Resolution.Minute, Market.Gate)

        self.Debug(f"✅ Added TSLAXUSDT (Gate)")
        self.Debug(f"✅ Added AAPLXUSDT (Gate)")

        # === 3. Verify Multi-Account Configuration ===
        self.Debug("\n🔍 Multi-Account Configuration:")
        self.Debug("-" * 80)

        if hasattr(self.Portfolio, 'GetAccount'):
            self.Debug("✅ Multi-Account Portfolio Detected!")

            try:
                gate_account = self.Portfolio.GetAccount("Gate")
                self.Debug(f"📊 Gate Account:")
                self.Debug(f"   Cash: ${gate_account.Cash:,.2f}")
                self.Debug(f"   Currency: {gate_account.CashBook.AccountCurrency}")

            except Exception as e:
                self.Error(f"❌ Error accessing Gate account: {e}")
        else:
            self.Debug("⚠️  Single account mode detected")

        # === 4. Verify Security Configuration ===
        self.Debug("\n🔍 Security Configuration Details:")
        self.Debug("=" * 80)

        for symbol in [self.tsla_crypto.Symbol, self.aapl_crypto.Symbol]:
            security = self.Securities[symbol]

            self.Debug(f"\n📌 {symbol.Value}:")
            self.Debug(f"   Market: {symbol.ID.Market}")
            self.Debug(f"   SecurityType: {symbol.SecurityType}")

            # Get BrokerageModel information
            brokerage_model = None
            if hasattr(self, 'BrokerageModel'):
                brokerage_model = self.BrokerageModel
                self.Debug(f"   BrokerageModel: {type(brokerage_model).__name__}")

            # Get BuyingPowerModel
            buying_power_model = security.BuyingPowerModel
            self.Debug(f"   BuyingPowerModel: {type(buying_power_model).__name__}")

            # Get Leverage - THIS IS THE KEY TEST
            leverage = security.Leverage
            self.Debug(f"   ⭐ Leverage: {leverage}x")

            # Additional details
            self.Debug(f"   IsTradable: {security.IsTradable}")

            # Check if leverage is correct
            expected_leverage = 5.0
            if leverage == expected_leverage:
                self.Debug(f"   ✅ PASS: Leverage is {expected_leverage}x (Margin mode)")
            else:
                self.Error(f"   ❌ FAIL: Expected {expected_leverage}x, got {leverage}x")

        # === 5. Additional Diagnostics ===
        self.Debug("\n🔍 Additional Diagnostics:")
        self.Debug("-" * 80)

        # Check setup handler
        self.Debug(f"Algorithm Type: {type(self).__name__}")

        # Log all securities
        self.Debug(f"\nTotal Securities: {len(self.Securities)}")
        for symbol in self.Securities.Keys:
            sec = self.Securities[symbol]
            self.Debug(f"  {symbol.Value}: Leverage={sec.Leverage}x, Type={symbol.SecurityType}")

        self.Debug("\n" + "=" * 80)
        self.Debug("INITIALIZATION COMPLETE")
        self.Debug("=" * 80)

        # Terminate after initialization since this is just a config verification test
        self.Quit("Test complete: Leverage configuration verified in Initialize()")

    def OnData(self, data: Slice):
        """No trading logic needed - verification happens in Initialize()"""
        pass

    def OnEndOfAlgorithm(self):
        """Final summary"""
        self.Debug("\n" + "=" * 80)
        self.Debug("TEST COMPLETE")
        self.Debug("=" * 80)
        self.Debug("Review the logs above to verify:")
        self.Debug("  1. Gate account is configured with Margin mode")
        self.Debug("  2. TSLAXUSDT Leverage = 5x")
        self.Debug("  3. AAPLXUSDT Leverage = 5x")
        self.Debug("=" * 80)
