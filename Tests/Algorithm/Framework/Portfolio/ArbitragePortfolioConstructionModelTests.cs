/*
 * QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
 * Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
*/

using System;
using System.Collections.Generic;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data.Market;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Securities.MultiAccount;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Tests for refactored ArbitragePortfolioConstructionModel (Tag-based pairing)
    /// This PCM decodes Tags from single Leg1 insights and generates paired ArbitragePortfolioTargets
    /// with ABSOLUTE quantities calculated via multi-account PortfolioTarget.Percent logic
    /// </summary>
    [TestFixture]
    public class ArbitragePortfolioConstructionModelTests
    {
        private AQCAlgorithm _algorithm;
        private ArbitragePortfolioConstructionModel _pcm;
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;
        private SecurityPortfolioManager _account1;
        private SecurityPortfolioManager _account2;

        [SetUp]
        public void Setup()
        {
            // Create algorithm instance
            _algorithm = new AQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(
                new DataManagerStub(_algorithm));

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            // Setup multi-account portfolio
            SetupMultiAccountPortfolio();

            // Add securities to algorithm
            var btcSecurity = _algorithm.AddSecurity(_btcSymbol);
            var mstrSecurity = _algorithm.AddSecurity(_mstrSymbol);

            // Set prices for securities (required for PortfolioTarget.Percent to work)
            btcSecurity.SetMarketPrice(new QuoteBar
            {
                Symbol = _btcSymbol,
                Time = _algorithm.UtcTime,
                Bid = new Bar(50000m, 50000m, 50000m, 50000m),
                Ask = new Bar(50001m, 50001m, 50001m, 50001m)
            });

            mstrSecurity.SetMarketPrice(new TradeBar
            {
                Symbol = _mstrSymbol,
                Time = _algorithm.UtcTime,
                Open = 300m,
                High = 300m,
                Low = 300m,
                Close = 300m,
                Volume = 1000
            });

            _pcm = new ArbitragePortfolioConstructionModel();
            _algorithm.SetArbitragePortfolioConstruction(_pcm);
        }

        /// <summary>
        /// Setup multi-account portfolio with two accounts:
        /// - Account1: $100,000 for crypto (BTCUSD)
        /// - Account2: $100,000 for equity (MSTR)
        /// </summary>
        private void SetupMultiAccountPortfolio()
        {
            // Create account configurations
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "Account1", 100000m },
                { "Account2", 100000m }
            };

            // Create router: BTCUSD -> Account1, MSTR -> Account2
            var router = new SimpleOrderRouter(new Dictionary<SecurityType, string>
            {
                { SecurityType.Crypto, "Account1" },
                { SecurityType.Equity, "Account2" }
            });

            // Create multi-account portfolio using reflection to replace algorithm's portfolio
            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                _algorithm.Securities,
                _algorithm.Transactions,
                new AlgorithmSettings(),
                null,  // defaultOrderProperties
                _algorithm.TimeKeeper);

            // Use reflection to set the portfolio (SetPortfolio doesn't exist on QCAlgorithm)
            var portfolioField = typeof(QCAlgorithm).GetField("_portfolio",
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);
            portfolioField?.SetValue(_algorithm, multiPortfolio);

            // Store references to sub-accounts for test manipulation
            _account1 = multiPortfolio.GetAccount("Account1");
            _account2 = multiPortfolio.GetAccount("Account2");
        }

        #region Category 1: Direction Calculation

        [Test]
        public void Test_LongSpread_Entry_OppositeDirections()
        {
            // Arrange - LONG_SPREAD: Leg1 Up, Leg2 Down
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            // LONG_SPREAD entry: Leg1 Up (positive quantity), Leg2 Down (negative quantity)
            Assert.Greater(target.Leg1Quantity, 0, "LONG_SPREAD: Leg1 quantity must be positive");
            Assert.Less(target.Leg2Quantity, 0, "LONG_SPREAD: Leg2 quantity must be negative");
        }

        [Test]
        public void Test_ShortSpread_Entry_OppositeDirections()
        {
            // Arrange - SHORT_SPREAD: Leg1 Down, Leg2 Up
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(0.02m, -0.01m, "SHORT_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Down, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            // SHORT_SPREAD entry: Leg1 Down (negative quantity), Leg2 Up (positive quantity)
            Assert.Less(target.Leg1Quantity, 0, "SHORT_SPREAD: Leg1 quantity must be negative");
            Assert.Greater(target.Leg2Quantity, 0, "SHORT_SPREAD: Leg2 quantity must be positive");
        }

        [Test]
        public void Test_Exit_BothZero()
        {
            // Arrange - Exit signal (Flat direction)
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Flat, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            // Exit: Both legs should have 0 quantity
            Assert.AreEqual(0, target.Leg1Quantity, "Exit: Leg1 quantity must be 0");
            Assert.AreEqual(0, target.Leg2Quantity, "Exit: Leg2 quantity must be 0");
        }

        #endregion

        #region Category 2: Quantity Calculation (CRITICAL TESTS)

        [Test]
        public void Test_SingleInsight_CalculatesAbsoluteQuantities()
        {
            // Arrange
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - PositionSizePct=0.25 (25% of each account)
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            // Account1 (crypto): $100,000 * 25% = $25,000 / $50,000 per BTC ≈ 0.5 BTC
            // PortfolioTarget.Percent() may apply fees/lot sizes, so we use reasonable tolerance
            decimal expectedBtcQty = 0.5m;
            Assert.AreEqual((double)expectedBtcQty, (double)target.Leg1Quantity, (double)0.02m,
                "Leg1 (BTC): $100k * 25% / $50k ≈ 0.5 BTC");

            // Account2 (equity): $100,000 * 25% = $25,000 / $300 per MSTR ≈ -83.33 shares
            decimal expectedMstrQty = -83.33m;
            Assert.AreEqual((double)expectedMstrQty, (double)target.Leg2Quantity, (double)2m,
                "Leg2 (MSTR): -($100k * 25% / $300) ≈ -83.33 shares");
        }

        [Test]
        public void Test_MultipleInsights_EachUsesFullPositionSize()
        {
            // Arrange - 2 insights, EACH with 25% PositionSizePct
            // IMPORTANT: After refactoring, each insight uses its FULL PositionSizePct,
            // NOT divided by insight count
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var level1 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));
            var level2 = new GridLevelPair(-0.03m, 0.015m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));

            var insights = new[]
            {
                CreateInsight(_btcSymbol, InsightDirection.Up, level1),
                CreateInsight(_btcSymbol, InsightDirection.Up, level2)
            };

            foreach (var i in insights)
                _algorithm.Insights.Add(i);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, insights);

            // Assert - Each insight gets FULL 25% allocation (NOT divided)
            Assert.AreEqual(2, targets.Length, "Should generate 2 ArbitragePortfolioTargets");

            foreach (var target in targets)
            {
                // Each target: approximately 0.5 BTC (same as single insight test)
                Assert.AreEqual((double)0.5m, (double)target.Leg1Quantity, (double)0.02m,
                    "Each insight uses FULL 25% PositionSizePct: ≈0.5 BTC per position");

                // Each target: approximately -83.33 MSTR shares
                Assert.AreEqual((double)-83.33m, (double)target.Leg2Quantity, (double)2m,
                    "Each insight uses FULL 25% PositionSizePct: ≈-83.33 MSTR per position");
            }
        }

        [Test]
        public void Test_DifferentPositionSizes_CalculatedIndependently()
        {
            // Arrange - 2 insights with DIFFERENT PositionSizePct (30% vs 40%)
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var level1 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.30m, (_btcSymbol, _mstrSymbol));
            var level2 = new GridLevelPair(-0.03m, 0.015m, "LONG_SPREAD", 0.40m, (_btcSymbol, _mstrSymbol));

            var insight1 = CreateInsight(_btcSymbol, InsightDirection.Up, level1);
            var insight2 = CreateInsight(_btcSymbol, InsightDirection.Up, level2);

            _algorithm.Insights.Add(insight1);
            _algorithm.Insights.Add(insight2);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight1, insight2 });

            // Assert
            Assert.AreEqual(2, targets.Length, "Should generate 2 ArbitragePortfolioTargets");

            var target1 = targets[0];
            var target2 = targets[1];

            // First insight: 30% -> approximately 0.6 BTC, -100 MSTR
            Assert.AreEqual((double)0.6m, (double)target1.Leg1Quantity, (double)0.02m,
                "Insight1 (30%): $100k * 30% / $50k ≈ 0.6 BTC");
            Assert.AreEqual((double)-100m, (double)target1.Leg2Quantity, (double)2m,
                "Insight1 (30%): -($100k * 30% / $300) ≈ -100 MSTR");

            // Second insight: 40% -> approximately 0.8 BTC, -133.33 MSTR
            Assert.AreEqual((double)0.8m, (double)target2.Leg1Quantity, (double)0.02m,
                "Insight2 (40%): $100k * 40% / $50k ≈ 0.8 BTC");
            Assert.AreEqual((double)-133.33m, (double)target2.Leg2Quantity, (double)2m,
                "Insight2 (40%): -($100k * 40% / $300) ≈ -133.33 MSTR");
        }

        [Test]
        public void Test_QuantityCalculation_WithDifferentPositionSize()
        {
            // Test that different PositionSizePct values produce different quantities
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);

            // Test with 50% allocation
            var levelPair50 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.50m,
                                               (_btcSymbol, _mstrSymbol));
            var insight50 = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair50);
            _algorithm.Insights.Add(insight50);

            var targets50 = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight50 });
            Assert.AreEqual(1, targets50.Length);
            var qty50 = Math.Abs(targets50[0].Leg1Quantity);

            // Clear insights by removing the previous one
            _algorithm.Insights.Remove(insight50);

            // Test with 25% allocation
            var levelPair25 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                               (_btcSymbol, _mstrSymbol));
            var insight25 = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair25);
            _algorithm.Insights.Add(insight25);

            var targets25 = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight25 });
            Assert.AreEqual(1, targets25.Length);
            var qty25 = Math.Abs(targets25[0].Leg1Quantity);

            // 50% allocation should produce roughly 2x the quantity of 25%
            Assert.Greater((double)qty50, (double)qty25 * 1.8, "50% allocation should be significantly larger than 25%");
            Assert.Less((double)qty50, (double)qty25 * 2.2, "50% allocation should be approximately 2x of 25%");
        }

        [Test]
        public void Test_QuantityCalculation_RespectsBuyingPower()
        {
            // This test verifies that CalculateMaxTradableMarketValue considers buying power
            // In the default setup, both accounts use CashBuyingPowerModel with 1x leverage
            // So buying power = cash balance for long positions

            // Arrange
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 1.0m,  // 100% allocation
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert
            Assert.AreEqual(1, targets.Length);
            var target = targets[0];

            // With 100% allocation and 1x leverage:
            // Account1: $100k available -> can buy approximately $100k worth of BTC (~2 BTC)
            // Account2: $100k available -> can short approximately $100k worth of MSTR (~-333 shares)
            // PortfolioTarget.Percent() may account for fees, margin, lot sizes

            Console.WriteLine($"100% allocation - Leg1: {target.Leg1Quantity}, Leg2: {target.Leg2Quantity}");

            Assert.Greater((double)target.Leg1Quantity, 1.9d, "Should allocate close to 2 BTC");
            Assert.Less((double)target.Leg1Quantity, 2.1d, "Should not significantly exceed 2 BTC");

            Assert.Less((double)target.Leg2Quantity, -320d, "Should short close to 333 MSTR");
            Assert.Greater((double)target.Leg2Quantity, -345d, "Should not significantly exceed -333 MSTR");
        }

        [Test]
        public void Test_QuantityCalculation_ReturnsAbsoluteNotDelta()
        {
            // Arrange - Create initial position first
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            // Simulate existing holdings in accounts
            _account1.Securities[_btcSymbol].Holdings.SetHoldings(50000m, 0.3m);  // Already hold 0.3 BTC
            _account2.Securities[_mstrSymbol].Holdings.SetHoldings(300m, -50m);   // Already short 50 MSTR

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - Target quantities are ABSOLUTE, not deltas
            Assert.AreEqual(1, targets.Length);
            var target = targets[0];

            // With existing holdings (0.3 BTC at $15k value, -50 MSTR at $15k value):
            // Account1 cash: $100k - $15k = $85k remaining, TPV still ~$100k
            // Account2 cash: $100k + $15k = $115k (from short proceeds), TPV still ~$100k
            // 25% of TPV is still ~$25k per account, but available cash differs

            Console.WriteLine($"With Holdings - Account1 Cash: {_account1.Cash}, Account2 Cash: {_account2.Cash}");
            Console.WriteLine($"Leg1Quantity: {target.Leg1Quantity}, Leg2Quantity: {target.Leg2Quantity}");

            // The key test: target should be ABSOLUTE quantity, not delta
            // Verify it's NOT close to delta (0.2 BTC or -33.33 MSTR)
            Assert.That((double)Math.Abs(target.Leg1Quantity - 0.2m), Is.GreaterThan(0.1d),
                "Leg1 should be ABSOLUTE target, not delta from existing 0.3 BTC");

            Assert.That((double)Math.Abs(target.Leg2Quantity + 33.33m), Is.GreaterThan(10d),
                "Leg2 should be ABSOLUTE target, not delta from existing -50 MSTR");
        }

        #endregion

        #region Category 3: Tag Decoding

        [Test]
        public void Test_InvalidTag_SkipsTarget()
        {
            // Arrange - Create insight with invalid Tag
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = new GridInsight(
                _btcSymbol,
                TimeSpan.FromMinutes(5),
                InsightDirection.Up,
                levelPair.Entry,
                1.0,
                "INVALID_TAG");  // Invalid Tag
            insight.GeneratedTimeUtc = _algorithm.UtcTime;

            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - Should skip this insight (no targets generated)
            Assert.AreEqual(0, targets.Length, "Invalid Tag should result in no targets");
        }

        [Test]
        public void Test_TagDecoding_RecoversLeg2Symbol()
        {
            // Arrange
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - PCM correctly decoded Leg2Symbol from Tag
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");
            var target = targets[0];

            Assert.AreEqual(_btcSymbol, target.Leg1Symbol, "Must have Leg1Symbol");
            Assert.AreEqual(_mstrSymbol, target.Leg2Symbol, "Must have Leg2Symbol (decoded from Tag)");
        }

        [Test]
        public void Test_TagDecoding_RecoversPositionSizePct()
        {
            // Arrange - PositionSizePct = 0.35 (35%)
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.35m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - PCM correctly decoded PositionSizePct and used it for calculation
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");
            var target = targets[0];

            // 35% of $100k / $50k = 0.7 BTC
            Assert.AreEqual((double)0.7m, (double)target.Leg1Quantity, (double)0.01m,
                "PCM decoded PositionSizePct=0.35: $100k * 35% / $50k = 0.7 BTC");

            // -35% of $100k / $300 = -116.67 MSTR
            Assert.AreEqual((double)-116.67m, (double)target.Leg2Quantity, (double)1m,
                "PCM decoded PositionSizePct=0.35: -($100k * 35% / $300) = -116.67 MSTR");
        }

        #endregion

        #region Category 4: Expired Insights

        [Test]
        public void Test_ExpiredInsight_DoesNotGenerateTargets()
        {
            // Arrange - Create expired entry insight
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            insight.CloseTimeUtc = _algorithm.UtcTime.AddHours(-1);  // Expired 1 hour ago

            _algorithm.Insights.Add(insight);

            // Act - PCM processes expired insights
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - Expired Entry insights should NOT generate targets
            // Insight expiration means prediction window ended, NOT close position
            // Positions remain open until explicit Exit signal (Direction=Flat)
            Assert.AreEqual(0, targets.Length,
                "Expired Entry insights should NOT generate targets (no auto-flatten)");
        }

        [Test]
        public void Test_ExitSignal_GeneratesZeroTargets()
        {
            // Arrange - Create Exit signal (Direction=Flat)
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Flat, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - Exit signals (Direction=Flat) should generate flatten targets
            Assert.AreEqual(1, targets.Length, "Exit signal should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            Assert.AreEqual(0, target.Leg1Quantity, "Exit signal: Leg1 should flatten to 0");
            Assert.AreEqual(0, target.Leg2Quantity, "Exit signal: Leg2 should flatten to 0");
        }

        #endregion

        #region Helper Methods

        /// <summary>
        /// Creates a GridInsight with proper Tag encoding
        /// </summary>
        private GridInsight CreateInsight(Symbol symbol, InsightDirection direction, GridLevelPair levelPair)
        {
            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);

            var insight = new GridInsight(
                symbol,
                TimeSpan.FromMinutes(5),
                direction,
                levelPair.Entry,
                1.0,
                tag);

            insight.GeneratedTimeUtc = _algorithm.UtcTime;
            insight.CloseTimeUtc = _algorithm.UtcTime.Add(TimeSpan.FromMinutes(5));
            insight.SourceModel = "ArbitrageAlphaModel";

            return insight;
        }

        #endregion
    }

    /// <summary>
    /// Simple order router for testing that routes by SecurityType
    /// </summary>
    public class SimpleOrderRouter : IOrderRouter
    {
        private readonly Dictionary<SecurityType, string> _routingMap;

        public SimpleOrderRouter(Dictionary<SecurityType, string> routingMap)
        {
            _routingMap = routingMap;
        }

        public string Route(Order order)
        {
            if (_routingMap.TryGetValue(order.Symbol.SecurityType, out var accountName))
            {
                return accountName;
            }
            throw new InvalidOperationException($"No routing found for {order.Symbol.SecurityType}");
        }

        public bool Validate()
        {
            return _routingMap != null && _routingMap.Count > 0;
        }
    }
}
