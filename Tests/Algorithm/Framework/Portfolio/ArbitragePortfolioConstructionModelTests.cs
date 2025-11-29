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
using System.Linq;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Tests for refactored ArbitragePortfolioConstructionModel (Tag-based pairing)
    /// This PCM decodes Tags from single Leg1 insights and generates 2 PortfolioTargets per insight
    /// </summary>
    [TestFixture]
    public class ArbitragePortfolioConstructionModelTests
    {
        private AQCAlgorithm _algorithm;
        private ArbitragePortfolioConstructionModel _pcm;
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;

        [SetUp]
        public void Setup()
        {
            // Create algorithm instance
            _algorithm = new AQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(
                new DataManagerStub(_algorithm));

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            // Add securities
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

            // Equity securities need TradeBar, not QuoteBar
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

        #region Category 2: Quantity Calculation

        [Test]
        public void Test_SingleInsight_EqualPortfolioAllocation()
        {
            // Arrange
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - With 1 insight and PositionSizePct=0.25, each leg gets 25% of portfolio
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");

            var target = targets[0];

            // Both legs should have same absolute percentage (25%)
            Assert.AreEqual(0.25, (double)Math.Abs(target.Leg1Quantity), 0.001,
                "Leg1 should get 25% allocation");
            Assert.AreEqual(0.25, (double)Math.Abs(target.Leg2Quantity), 0.001,
                "Leg2 should get 25% allocation");
        }

        [Test]
        public void Test_MultipleInsights_SplitPortfolioEqually()
        {
            // Arrange - 2 insights, each with 25% PositionSizePct
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var level1 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));
            var level2 = new GridLevelPair(-0.03m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));

            var insights = new[]
            {
                CreateInsight(_btcSymbol, InsightDirection.Up, level1),
                CreateInsight(_btcSymbol, InsightDirection.Up, level2)
            };

            foreach (var i in insights)
                _algorithm.Insights.Add(i);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, insights);

            // Assert - 2 insights split portfolio 50/50, each gets 12.5% (50% * 25%)
            Assert.AreEqual(2, targets.Length, "Should generate 2 ArbitragePortfolioTargets");

            foreach (var target in targets)
            {
                Assert.AreEqual(0.125, (double)Math.Abs(target.Leg1Quantity), 0.001,
                    "Each leg1 should get 12.5% allocation");
                Assert.AreEqual(0.125, (double)Math.Abs(target.Leg2Quantity), 0.001,
                    "Each leg2 should get 12.5% allocation");
            }
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
            // Arrange - PositionSizePct = 0.30 (30%)
            _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.30m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - With 1 insight and PositionSizePct=0.30, allocation should be 30%
            Assert.AreEqual(1, targets.Length, "Should generate 1 ArbitragePortfolioTarget");
            var target = targets[0];

            Assert.AreEqual(0.30, (double)Math.Abs(target.Leg1Quantity), 0.001,
                "PCM should decode PositionSizePct=0.30 from Tag for Leg1");
            Assert.AreEqual(0.30, (double)Math.Abs(target.Leg2Quantity), 0.001,
                "PCM should decode PositionSizePct=0.30 from Tag for Leg2");
        }

        #endregion

        #region Category 4: Expired Insights

        [Test]
        public void Test_ExpiredInsight_DoesNotGenerateTargets()
        {
            // Arrange - Create expired entry insight
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            insight.CloseTimeUtc = _algorithm.UtcTime.AddHours(-1);  // Expired 1 hour ago

            _algorithm.Insights.Add(insight);

            // Act - PCM processes expired insights
            var targets = _pcm.CreateArbitrageTargets(_algorithm, new[] { insight });

            // Assert - For grid arbitrage strategy, expired Entry insights should NOT generate
            // flatten targets. Positions should only be closed by explicit Exit signals (Direction=Flat).
            // Insight expiration just means no new grid level has been triggered, but existing
            // positions should remain open until an exit signal is received.
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
}
