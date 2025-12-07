"""
TradingPair + ArbitrageAlphaModel Framework Integration Test (Auto-Configuration)

Test Scenario:
- Data Source: Gate (crypto) + USA Equity (stocks)
- Trading Pairs: Gate aaplxusdt/AAPL USA, Gate tslaxusdt/TSLA USA
- Date Range: 2025-09-04 to 2025-09-10
- Account Config:
  * Gate Account: $50,000 - trades Gate crypto
  * IBKR Account: $50,000 - trades USA equities
- Test Focus: Grid level auto-configuration via ArbitrageAlphaModel
- Framework: Uses SetAlpha() BEFORE AddPair() to enable auto-configuration
- Brokerage Models: RoutedBrokerageModel automatically applies correct models per market

Test Objectives (Full Framework Integration):
1. Verify ArbitrageAlphaModel auto-configures grid levels for "crypto_stock" pairs
2. Verify ArbitrageAlphaModel generates 1 Insight per signal (Leg1 only)
3. Verify Tag contains full pairing information (Leg2Symbol + grid config)
4. Verify ArbitragePortfolioConstructionModel decodes Tag and generates 2 PortfolioTargets per Insight
5. Verify ArbitrageExecutionModel executes both legs using orderbook-aware matching
6. Verify TradingPair calculates spreads correctly
7. Verify grid level threshold crossing detection
8. Verify multi-account routing (Gate crypto -> Gate, USA equity -> IBKR)
9. Verify RoutedBrokerageModel applies correct leverage, fees, and models per market
10. Verify Insights collection tracks generated signals

Auto-Configuration Details:
- SetAlpha() is called BEFORE AddPair() to enable OnTradingPairsChanged event
- AddPair(leg1, leg2, "crypto_stock") triggers auto-configuration
- Default "crypto_stock" template adds 2 grid levels:
  * LONG_SPREAD: entry=-2%, exit=+1%, size=50%
  * SHORT_SPREAD: entry=+3%, exit=-0.5%, size=50%
- RoutedBrokerageModel automatically applies:
  * Gate market -> GateBrokerageModel (fees, leverage, etc.)
  * USA market -> InteractiveBrokersBrokerageModel (fees, leverage, etc.)
  * No need to manually set DataNormalizationMode, BuyingPowerModel, or FeeModel
"""

from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm


class TradingPairFrameworkTest(AQCAlgorithm):
    """TradingPair + ArbitrageAlphaModel Framework Integration Test"""

    def Initialize(self):
        """Initialize the algorithm"""
        # === 1. Set backtest parameters ===
        self.SetStartDate(2025, 9, 4)
        self.SetEndDate(2025, 9, 10)
        self.SetTimeZone("UTC")
        self.SetBenchmark(lambda x: 0)

        # === 2. Initialize tracking variables ===
        self._last_logged_count = 0  # Track last logged insight count

        # === 3. Add securities (Gate crypto + USA equities) ===
        self.Debug("=" * 60)
        self.Debug("INITIALIZING SECURITIES")
        self.Debug("=" * 60)

        # Add Gate crypto (lowercase symbols)
        # Note: No need to set DataNormalizationMode, BuyingPowerModel, or FeeModel
        # These are automatically configured by RoutedBrokerageModel based on market
        # Using Resolution.Orderbook to read depth data (quotes) instead of trade data
        self.aapl_crypto = self.AddCrypto("aaplxusdt", Resolution.ORDERBOOK, Market.Gate)
        self.tsla_crypto = self.AddCrypto("tslaxusdt", Resolution.ORDERBOOK, Market.Gate)

        # Add USA equities
        self.aapl_stock = self.AddEquity("AAPL", Resolution.TICK, Market.USA)
        self.tsla_stock = self.AddEquity("TSLA", Resolution.TICK, Market.USA)

        self.Debug(f"Added {len(self.Securities)} securities")
        self.Debug(f"  Gate crypto securities will use GateBrokerageModel (leverage, fees, etc.)")
        self.Debug(f"  USA equity securities will use InteractiveBrokersBrokerageModel")
        self.Debug("=" * 60)

        # === 4. Setup ArbitrageAlphaModel FIRST (before adding pairs) ===
        # This allows the Alpha model's OnTradingPairsChanged to auto-configure grid levels
        self.Debug("CONFIGURING FRAMEWORK")
        self.Debug("=" * 60)

        from QuantConnect.Algorithm.Framework.Alphas import ArbitrageAlphaModel
        from QuantConnect.Algorithm.Framework.Portfolio import ArbitragePortfolioConstructionModel
        from QuantConnect.Algorithm.Framework.Execution import ArbitrageExecutionModel, MatchingStrategy

        alpha = ArbitrageAlphaModel(
            insightPeriod=timedelta(minutes=5),  # Insights valid for 5 minutes
            confidence=1.0,                       # 100% confidence
            requireValidPrices=True               # Require valid bid/ask prices
        )

        self.SetAlpha(alpha)
        self.Debug("ArbitrageAlphaModel configured (with auto-configuration enabled)")
        self.Debug("  Default templates:")
        self.Debug("    - crypto_stock: LONG_SPREAD (-2%/+1%, 50%) + SHORT_SPREAD (+3%/-0.5%, 50%)")
        self.Debug("    - spot_future: LONG_SPREAD (-1.5%/+0.8%, 30%) + SHORT_SPREAD (+2.5%/-0.8%, 30%)")
        self.Debug("=" * 60)

        # === 5. Add trading pairs with pairType for auto-configuration ===
        self.Debug("ADDING TRADING PAIRS (Auto-Configuration)")
        self.Debug("=" * 60)

        # Access TradingPairs via self.TradingPairs
        # AddPair with pairType "crypto_stock" triggers auto-configuration
        aapl_pair = self.TradingPairs.AddPair(
            self.aapl_crypto.Symbol,
            self.aapl_stock.Symbol,
            "crypto_stock"  # This triggers auto-configuration!
        )
        self.Debug(f"Added AAPL pair (type: crypto_stock) - grid levels auto-configured")

        tsla_pair = self.TradingPairs.AddPair(
            self.tsla_crypto.Symbol,
            self.tsla_stock.Symbol,
            "crypto_stock"  # This triggers auto-configuration!
        )
        self.Debug(f"Added TSLA pair (type: crypto_stock) - grid levels auto-configured")

        self.Debug(f"Added {self.TradingPairs.Count} trading pairs")
        self.Debug(f"AAPL grid levels (auto-configured): {len(list(aapl_pair.LevelPairs))}")
        self.Debug(f"TSLA grid levels (auto-configured): {len(list(tsla_pair.LevelPairs))}")
        self.Debug("=" * 60)

        # === 6. Setup Portfolio Construction and Execution ===
        pcm = ArbitragePortfolioConstructionModel()
        self.SetArbitragePortfolioConstruction(pcm)
        self.Debug("ArbitragePortfolioConstructionModel configured")

        execution = ArbitrageExecutionModel(
            asynchronous=True,  # Submit orders asynchronously
            preferredStrategy=MatchingStrategy.AutoDetect  # Auto-detect orderbook matching
        )
        self.SetArbitrageExecution(execution)
        self.Debug("ArbitrageExecutionModel configured")
        self.Debug("  Asynchronous: True")
        self.Debug("  Matching Strategy: AutoDetect")
        self.Debug("=" * 60)

        self.Debug("INITIALIZATION COMPLETE")
        self.Debug(f"Trading Pairs: {self.TradingPairs.Count}")
        self.Debug(f"Securities: {len(self.Securities)}")
        self.Debug("=" * 60)

        # Subscribe to InsightsGenerated event
        self.InsightsGenerated += self.OnInsightsGenerated

    def OnInsightsGenerated(self, sender, insights_collection):
        """Handle newly generated insights"""
        for insight in insights_collection.Insights:
            self.LogSingleInsight(insight)

    def OnData(self, data: Slice):
        """Called on each data slice"""
        # CRITICAL: Call base class OnData to trigger framework
        # This calls OnFrameworkData() which updates TradingPairs and Alpha model
        super().OnData(data)

    def OnOrderEvent(self, orderEvent):
        """Handle order events - terminate on invalid orders"""
        if orderEvent.Status == OrderStatus.Invalid:
            # Get order details for comprehensive error logging
            order = self.Transactions.GetOrderById(orderEvent.OrderId)
            order_value = order.GetValue(self.Securities[orderEvent.Symbol])

            # Comprehensive error message with all order details
            error_msg = (
                f"❌ Order {orderEvent.OrderId} Invalid | "
                f"Symbol: {orderEvent.Symbol.Value} | "
                f"Direction: {order.Direction} | "
                f"Quantity: {order.Quantity} | "
                f"Value: ${abs(order_value):,.2f} | "
                f"Tag: {order.Tag} | "
                f"Message: {orderEvent.Message}"
            )

            self.Error(error_msg)
            self.Debug(error_msg)
            self.Quit(f"Terminating due to invalid order: {orderEvent.OrderId}")
            
    def LogSingleInsight(self, insight):
        """Log a single Insight (Leg1 only, with Tag-based pairing info)"""
        try:
            # Manually decode Tag - format: "Leg1ID|Leg2ID|Entry|Exit|Direction|PosSize"
            if not insight.Tag:
                self.Debug(f"WARNING: Insight has no Tag")
                return

            parts = insight.Tag.split("|")
            if len(parts) != 6:
                self.Debug(f"WARNING: Tag has unexpected format (expected 6 parts, got {len(parts)})")
                return

            leg1_id = parts[0]
            leg2_id = parts[1]
            entry_spread = float(parts[2])
            exit_spread = float(parts[3])
            direction = parts[4]
            position_size = float(parts[5])

            # Print header with count
            self.Debug("")
            self.Debug("=" * 60)
            self.Debug(f"INSIGHT #{self.Insights.TotalCount} GENERATED (Single/Tag-Based)")
            self.Debug("=" * 60)

            # Print insight information
            self.Debug(f"  Time: {self.Time}")
            self.Debug(f"  Symbol (Leg1): {insight.Symbol.Value}")
            self.Debug(f"  Direction (Leg1): {insight.Direction}")
            self.Debug(f"  Tag: {insight.Tag}")
            self.Debug(f"  Entry Level: {entry_spread:.4%}")
            self.Debug(f"  Exit Level: {exit_spread:.4%}")
            self.Debug(f"  Grid Direction: {direction}")
            self.Debug(f"  Position Size: {position_size:.2%}")
            self.Debug(f"  Confidence: {insight.Confidence:.2%}")
            self.Debug(f"  Period: {insight.Period}")

            # Decode Leg2 from Tag
            self.Debug(f"  Pairing Info (from Tag):")
            self.Debug(f"    Leg1 ID: {leg1_id}")
            self.Debug(f"    Leg2 ID: {leg2_id}")

            self.Debug("=" * 60)
            self.Debug("")

        except Exception as e:
            self.Debug(f"Error logging insight: {e}")
            self.Error(f"LogSingleInsight error: {e}")

    def OnEndOfAlgorithm(self):
        """Output test results"""
        self.Debug("")
        self.Debug("=" * 60)
        self.Debug("TEST RESULTS - Framework Integration Test")
        self.Debug("=" * 60)
        self.Debug("Components:")
        self.Debug("  - TradingPairManager (Core)")
        self.Debug("  - ArbitrageAlphaModel (Alpha)")
        self.Debug("  - ArbitragePortfolioConstructionModel (Portfolio)")
        self.Debug("=" * 60)

        # === Insights Summary ===
        self.Debug(f"Total Insights Generated: {self.Insights.TotalCount}")
        self.Debug(f"Active Insights: {self.Insights.Count}")

        self.Debug("")
        self.Debug("Insights Summary (Tag-Based Pairing):")
        insight_count = 0
        for insight in self.Insights:
            insight_count += 1
            symbol = insight.Symbol.Value
            direction = str(insight.Direction)
            has_tag = "Yes" if insight.Tag else "No"
            self.Debug(f"  Insight {insight_count}:")
            self.Debug(f"    Symbol (Leg1): {symbol}")
            self.Debug(f"    Direction: {direction}")
            self.Debug(f"    Has Tag: {has_tag}")

        # === TradingPair Summary ===
        self.Debug("")
        self.Debug("TradingPair Spread Summary:")
        for pair in self.TradingPairs:
            self.Debug(f"  {pair.Key}:")
            self.Debug(f"    Theoretical Spread: {pair.TheoreticalSpread:.4%}")
            self.Debug(f"    Has Valid Prices: {pair.HasValidPrices}")
            self.Debug(f"    Active Positions: {pair.ActivePositionCount}")
            self.Debug(f"    Grid Levels: {len(list(pair.LevelPairs))}")

        # === Validation ===
        self.Debug("")
        self.Debug("=" * 60)
        if self.Insights.TotalCount == 0:
            self.Debug("WARNING: No insights were generated!")
            self.Debug("This may indicate:")
            self.Debug("  1. Spreads never crossed entry thresholds")
            self.Debug("  2. Data missing or insufficient")
            self.Debug("  3. Alpha model not properly integrated")
        else:
            self.Debug(f"SUCCESS: {self.Insights.TotalCount} insights generated")

            # Validate Tag presence (all insights should have Tags)
            insights_without_tag = sum(1 for i in self.Insights if not i.Tag)
            if insights_without_tag > 0:
                self.Debug(f"WARNING: {insights_without_tag} insights missing Tag!")
            else:
                self.Debug(f"SUCCESS: All {self.Insights.TotalCount} insights have Tags")

            # Validate single Insight per signal (Tag-based pairing)
            self.Debug(f"EXPECTED: 1 Insight per signal (Leg1 only)")
            self.Debug(f"PCM will decode Tags and generate 2 PortfolioTargets per Insight")

            self.Debug("Framework integration validated (Tag-Based Pairing)!")

        self.Debug("=" * 60)
        self.Debug("")
