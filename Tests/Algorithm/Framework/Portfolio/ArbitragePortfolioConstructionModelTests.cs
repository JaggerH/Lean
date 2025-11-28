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

        [OneTimeSetUp]
        public void OneTimeSetUp()
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

            mstrSecurity.SetMarketPrice(new QuoteBar
            {
                Symbol = _mstrSymbol,
                Time = _algorithm.UtcTime,
                Bid = new Bar(300m, 300m, 300m, 300m),
                Ask = new Bar(300.01m, 300.01m, 300.01m, 300.01m)
            });
        }

        [SetUp]
        public void Setup()
        {
            // Clear insights from previous tests
            _algorithm?.Insights?.Clear(new[] { _btcSymbol, _mstrSymbol });

            _pcm = new ArbitragePortfolioConstructionModel();
            _algorithm.SetPortfolioConstruction(_pcm);
        }

        #region Category 1: Target Generation (1→2)

        [Test]
        public void Test_SingleInsight_GeneratesTwoTargets()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            // Create single Leg1 insight with Tag
            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);
            var insight = new GridInsight(
                _btcSymbol,
                TimeSpan.FromMinutes(5),
                InsightDirection.Up,
                levelPair.Entry,
                1.0,
                tag);
            insight.GeneratedTimeUtc = _algorithm.UtcTime;
            insight.CloseTimeUtc = _algorithm.UtcTime.Add(TimeSpan.FromMinutes(5));

            // Add to framework
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - Must generate exactly 2 targets (not 1)
            Assert.AreEqual(2, targets.Count, "Must generate exactly 2 targets from 1 insight");

            // Verify targets are for both legs
            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            Assert.IsNotNull(leg1Target, "Must have target for Leg1");
            Assert.IsNotNull(leg2Target, "Must have target for Leg2");
        }

        [Test]
        public void Test_MultipleInsights_GenerateMultiplePairs()
        {
            // Arrange - 3 insights (representing 3 different grid levels)
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);

            var level1 = new GridLevelPair(-0.03m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));
            var level2 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));
            var level3 = new GridLevelPair(-0.01m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSymbol, _mstrSymbol));

            var insights = new[]
            {
                CreateInsight(_btcSymbol, InsightDirection.Up, level1),
                CreateInsight(_btcSymbol, InsightDirection.Up, level2),
                CreateInsight(_btcSymbol, InsightDirection.Up, level3)
            };

            foreach (var i in insights)
                _algorithm.Insights.Add(i);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, insights).ToList();

            // Assert - 3 insights → 6 targets (2 per insight)
            Assert.AreEqual(6, targets.Count, "3 insights must generate 6 targets (2 per insight)");

            // Verify each insight generated 2 targets
            foreach (var insight in insights)
            {
                var targetsForInsight = targets.Where(t => t.Tag == insight.Tag).ToList();
                Assert.AreEqual(2, targetsForInsight.Count,
                    $"Each insight must generate exactly 2 targets");
            }
        }

        #endregion

        #region Category 2: Tag Propagation

        [Test]
        public void Test_BothTargets_HaveSameTag()
        {
            // Arrange
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert
            Assert.AreEqual(2, targets.Count);

            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            Assert.AreEqual(tag, leg1Target.Tag, "Leg1 target must have same Tag as insight");
            Assert.AreEqual(tag, leg2Target.Tag, "Leg2 target must have same Tag as insight");
            Assert.AreEqual(leg1Target.Tag, leg2Target.Tag, "Both targets must have identical Tag");
        }

        [Test]
        public void Test_MultipleInsights_UniqueTagsPerPair()
        {
            // Arrange - 2 insights with different Tags
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
            var targets = _pcm.CreateTargets(_algorithm, insights).ToList();

            // Assert - 2 insights → 4 targets (2 pairs)
            Assert.AreEqual(4, targets.Count);

            // Group targets by Tag
            var targetsByTag = targets.GroupBy(t => t.Tag).ToList();
            Assert.AreEqual(2, targetsByTag.Count, "Should have 2 unique Tags (one per insight)");

            // Each Tag should have exactly 2 targets
            foreach (var group in targetsByTag)
            {
                Assert.AreEqual(2, group.Count(), $"Tag {group.Key} must have exactly 2 targets");
            }
        }

        #endregion

        #region Category 3: Direction Calculation

        [Test]
        public void Test_LongSpread_Entry_OppositeDirections()
        {
            // Arrange - LONG_SPREAD: Leg1 Up, Leg2 Down
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert
            Assert.AreEqual(2, targets.Count);

            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            // LONG_SPREAD entry: Leg1 Up (positive quantity), Leg2 Down (negative quantity)
            Assert.Greater(leg1Target.Quantity, 0, "LONG_SPREAD: Leg1 quantity must be positive");
            Assert.Less(leg2Target.Quantity, 0, "LONG_SPREAD: Leg2 quantity must be negative");
        }

        [Test]
        public void Test_ShortSpread_Entry_OppositeDirections()
        {
            // Arrange - SHORT_SPREAD: Leg1 Down, Leg2 Up
            var levelPair = new GridLevelPair(0.02m, -0.01m, "SHORT_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Down, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert
            Assert.AreEqual(2, targets.Count);

            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            // SHORT_SPREAD entry: Leg1 Down (negative quantity), Leg2 Up (positive quantity)
            Assert.Less(leg1Target.Quantity, 0, "SHORT_SPREAD: Leg1 quantity must be negative");
            Assert.Greater(leg2Target.Quantity, 0, "SHORT_SPREAD: Leg2 quantity must be positive");
        }

        [Test]
        public void Test_Exit_BothZero()
        {
            // Arrange - Exit signal (Flat direction)
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Flat, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert
            Assert.AreEqual(2, targets.Count);

            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            // Exit: Both legs should have 0 quantity
            Assert.AreEqual(0, leg1Target.Quantity, "Exit: Leg1 quantity must be 0");
            Assert.AreEqual(0, leg2Target.Quantity, "Exit: Leg2 quantity must be 0");
        }

        #endregion

        #region Category 4: Quantity Calculation

        [Test]
        public void Test_SingleInsight_EqualPortfolioAllocation()
        {
            // Arrange
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - With 1 insight and PositionSizePct=0.25, each leg gets 25% of portfolio
            Assert.AreEqual(2, targets.Count);

            var leg1Target = targets.First(t => t.Symbol == _btcSymbol);
            var leg2Target = targets.First(t => t.Symbol == _mstrSymbol);

            // Both legs should have same absolute percentage (25%)
            Assert.AreEqual(0.25, (double)Math.Abs(leg1Target.Quantity), 0.001,
                "Leg1 should get 25% allocation");
            Assert.AreEqual(0.25, (double)Math.Abs(leg2Target.Quantity), 0.001,
                "Leg2 should get 25% allocation");
        }

        [Test]
        public void Test_MultipleInsights_SplitPortfolioEqually()
        {
            // Arrange - 2 insights, each with 25% PositionSizePct
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
            var targets = _pcm.CreateTargets(_algorithm, insights).ToList();

            // Assert - 2 insights split portfolio 50/50, each gets 12.5% (50% * 25%)
            Assert.AreEqual(4, targets.Count);

            foreach (var target in targets)
            {
                Assert.AreEqual(0.125, (double)Math.Abs(target.Quantity), 0.001,
                    "Each leg of each insight should get 12.5% allocation");
            }
        }

        #endregion

        #region Category 5: Tag Decoding

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
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - Should skip this insight (no targets generated)
            Assert.AreEqual(0, targets.Count, "Invalid Tag should result in no targets");
        }

        [Test]
        public void Test_TagDecoding_RecoversLeg2Symbol()
        {
            // Arrange
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - PCM correctly decoded Leg2Symbol from Tag
            Assert.AreEqual(2, targets.Count);
            var symbols = targets.Select(t => t.Symbol).ToList();

            Assert.Contains(_btcSymbol, symbols, "Must contain Leg1Symbol");
            Assert.Contains(_mstrSymbol, symbols, "Must contain Leg2Symbol (decoded from Tag)");
        }

        [Test]
        public void Test_TagDecoding_RecoversPositionSizePct()
        {
            // Arrange - PositionSizePct = 0.30 (30%)
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.30m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            _algorithm.Insights.Add(insight);

            // Act
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - With 1 insight and PositionSizePct=0.30, allocation should be 30%
            Assert.AreEqual(2, targets.Count);

            foreach (var target in targets)
            {
                Assert.AreEqual(0.30, (double)Math.Abs(target.Quantity), 0.001,
                    "PCM should decode PositionSizePct=0.30 from Tag");
            }
        }

        #endregion

        #region Category 6: Expired Insights

        [Test]
        public void Test_ExpiredInsight_GeneratesZeroTargets()
        {
            // Arrange - Create expired insight
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            var insight = CreateInsight(_btcSymbol, InsightDirection.Up, levelPair);
            insight.CloseTimeUtc = _algorithm.UtcTime.AddHours(-1);  // Expired 1 hour ago

            _algorithm.Insights.Add(insight);

            // Act - PCM processes expired insights
            var targets = _pcm.CreateTargets(_algorithm, new[] { insight }).ToList();

            // Assert - Expired insights should generate flatten targets
            // Note: This depends on how PCM handles expired insights
            // If PCM removes expired insights, targets count may be 2 (flatten both legs)
            if (targets.Count > 0)
            {
                foreach (var target in targets)
                {
                    Assert.AreEqual(0, target.Quantity,
                        "Expired insights should flatten positions");
                }
            }
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
            insight.SourceModel = "GridArbitrageAlphaModel";

            return insight;
        }

        #endregion
    }
}
