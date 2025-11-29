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
using System.Reflection;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Tests for refactored GridArbitrageAlphaModel (Tag-based pairing)
    /// This model generates 1 Insight per signal (Leg1 only) with Tag containing pairing info
    /// </summary>
    [TestFixture]
    public class GridArbitrageAlphaModelTests
    {
        private AQCAlgorithm _algorithm;
        private GridArbitrageAlphaModel _alphaModel;
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;
        private Security _btcSecurity;
        private Security _mstrSecurity;

        [SetUp]
        public void Setup()
        {
            // Create fresh algorithm instance for each test
            _algorithm = new AQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(
                new DataManagerStub(_algorithm));

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            // Add securities
            _btcSecurity = _algorithm.AddSecurity(_btcSymbol);
            _mstrSecurity = _algorithm.AddSecurity(_mstrSymbol);

            // Create and set alpha model
            _alphaModel = new GridArbitrageAlphaModel(
                insightPeriod: TimeSpan.FromMinutes(5),
                confidence: 1.0,
                requireValidPrices: true);

            // Set AlphaModel to algorithm for framework integration
            _algorithm.SetAlpha(_alphaModel);
        }

        #region Category 1: Single Insight Generation

        [Test]
        public void Test_EntrySignal_GeneratesSingleInsight()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            // Set prices to trigger LONG_SPREAD entry (spread <= -0.02)
            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - Must generate exactly 1 insight (Leg1 only, not 2)
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count, "Must generate exactly 1 insight for entry signal");

            // Verify it's for Leg1 (crypto)
            Assert.AreEqual(pair.Leg1Symbol, insights[0].Symbol, "Insight must be for Leg1 (crypto)");
        }

        [Test]
        public void Test_ExitSignal_GeneratesSingleInsight()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            // Create invested position
            var position = CreateInvestedPosition(pair, levelPair, 1.0m, -100m);

            // Set prices to trigger exit
            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 39600m, 39700m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - Must generate exactly 1 insight (Leg1 only, not 2)
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count, "Must generate exactly 1 insight for exit signal");

            // Verify it's for Leg1 (crypto)
            Assert.AreEqual(pair.Leg1Symbol, insights[0].Symbol, "Insight must be for Leg1 (crypto)");
        }

        [Test]
        public void Test_MultipleEntries_EachGeneratesSingleInsight()
        {
            // Arrange - Add 3 grid levels
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.03m, 0.01m, SpreadDirection.LongSpread, 0.25m);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);
            pair.AddLevelPair(-0.01m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            // Set prices to trigger all 3 levels
            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41500m, 41600m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - Must generate 3 insights (NOT 6), one per level
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(3, insights.Count, "Must generate 3 insights (1 per level), not 6");

            // Verify all are for Leg1Symbol
            Assert.IsTrue(insights.All(i => i.Symbol == pair.Leg1Symbol),
                "All insights must be for Leg1Symbol");
        }

        #endregion

        #region Category 2: Tag Encoding Validation

        [Test]
        public void Test_InsightTag_ContainsGridConfiguration()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);
            var tag = insights[0].Tag;

            // Tag should be encoded by TradingPairManager.EncodeGridTag()
            Assert.IsNotNull(tag, "Tag must not be null");
            Assert.IsNotEmpty(tag, "Tag must not be empty");

            // Tag should match expected encoding
            var expectedTag = TradingPairManager.EncodeGridTag(
                pair.Leg1Symbol, pair.Leg2Symbol, levelPair);
            Assert.AreEqual(expectedTag, tag, "Tag must match EncodeGridTag output");
        }

        [Test]
        public void Test_TagEncodesSymbolIds()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);
            var insights = _algorithm.Insights.ToList();

            // Assert
            var tag = insights[0].Tag;

            // Tag should contain both symbol IDs
            Assert.IsTrue(tag.Contains(_btcSymbol.ID.ToString()),
                $"Tag must contain Leg1 symbol ID: {_btcSymbol.ID}");
            Assert.IsTrue(tag.Contains(_mstrSymbol.ID.ToString()),
                $"Tag must contain Leg2 symbol ID: {_mstrSymbol.ID}");
        }

        [Test]
        public void Test_TagEncodesLevelConfig()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);
            var insights = _algorithm.Insights.ToList();

            // Assert
            var tag = insights[0].Tag;

            // Tag should encode entry/exit levels
            Assert.IsTrue(tag.Contains("-0.02") || tag.Contains("-0.0200"),
                "Tag must contain entry level");
            Assert.IsTrue(tag.Contains("0.01") || tag.Contains("0.0100"),
                "Tag must contain exit level");
        }

        [Test]
        public void Test_MultipleInsights_UniqueTagsPerLevel()
        {
            // Arrange - 3 different grid levels
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.03m, 0.01m, SpreadDirection.LongSpread, 0.25m);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);
            pair.AddLevelPair(-0.01m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41500m, 41600m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - Each level should have unique Tag
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(3, insights.Count);
            var tags = insights.Select(i => i.Tag).ToList();
            Assert.AreEqual(3, tags.Distinct().Count(), "Each insight must have unique Tag");
        }

        #endregion

        #region Category 3: Insight Direction Mapping

        [Test]
        public void Test_LongSpread_Entry_Leg1DirectionIsUp()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - LONG_SPREAD entry: Leg1 (crypto) Up (PCM will determine Leg2 Down)
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);
            Assert.AreEqual(InsightDirection.Up, insights[0].Direction,
                "LONG_SPREAD entry: Leg1 (crypto) must be Up");
        }

        [Test]
        public void Test_ShortSpread_Entry_Leg1DirectionIsDown()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(0.02m, -0.01m, SpreadDirection.ShortSpread, 0.25m);

            SetPrices(_btcSecurity, 41000m, 41100m);
            SetPrices(_mstrSecurity, 40000m, 40100m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);

            // Assert - SHORT_SPREAD entry: Leg1 (crypto) Down (PCM will determine Leg2 Up)
            Assert.AreEqual(1, insights.Count);
            var insight = insights[0];
            Assert.AreEqual(InsightDirection.Down, insight.Direction,
                "SHORT_SPREAD entry: Leg1 (crypto) must be Down");
        }

        [Test]
        public void Test_Exit_DirectionIsFlat()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            CreateInvestedPosition(pair, levelPair, 1.0m, -100m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 39600m, 39700m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert - Exit: Leg1 Flat (PCM will also make Leg2 Flat)
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count, "Must generate exactly 1 exit insight");
            Assert.AreEqual(InsightDirection.Flat, insights[0].Direction,
                "Exit signal must have Flat direction");
        }

        #endregion

        #region Category 4: Timestamp Validation

        [Test]
        public void Test_InsightTimestamps_SetCorrectly()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            var expectedTimeUtc = _algorithm.UtcTime;

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);
            var insight = insights[0];

            Assert.AreEqual(expectedTimeUtc, insight.GeneratedTimeUtc,
                "GeneratedTimeUtc must match algorithm.UtcTime");

            var expectedCloseTime = expectedTimeUtc.Add(TimeSpan.FromMinutes(5));
            Assert.AreEqual(expectedCloseTime, insight.CloseTimeUtc,
                "CloseTimeUtc must equal GeneratedTimeUtc + insightPeriod");
        }

        #endregion

        #region Category 5: Configuration Options

        [Test]
        public void Test_InsightPeriod_DefaultValue()
        {
            // Arrange
            _alphaModel = new GridArbitrageAlphaModel(); // Use defaults
            _algorithm.SetAlpha(_alphaModel);

            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);

            // Assert - Default is 5 minutes
            Assert.AreEqual(1, insights.Count);
            Assert.AreEqual(TimeSpan.FromMinutes(5), insights[0].Period,
                "Default insight period should be 5 minutes");
        }

        [Test]
        public void Test_Confidence_CustomValue()
        {
            // Arrange
            var customConfidence = 0.75;
            _alphaModel = new GridArbitrageAlphaModel(confidence: customConfidence);
            _algorithm.SetAlpha(_alphaModel);

            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);

            Assert.AreEqual(customConfidence, insights[0].Confidence,
                "Confidence should match custom value");
        }


        #endregion

        #region Category 6: Duplicate Detection

        [Test]
        public void Test_SameLevel_SecondCall_NoDuplicate()
        {
            // Arrange
            _algorithm.SetAlpha(_alphaModel);

            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act - First call generates insight (via framework)
            var slice1 = CreateSlice();
            _algorithm.OnFrameworkData(slice1);
            var insightsAfterFirst = _algorithm.Insights.Count;

            // Act - Second call with same conditions
            var slice2 = CreateSlice();
            _algorithm.OnFrameworkData(slice2);
            var insightsAfterSecond = _algorithm.Insights.Count;

            // Assert - First call generates 1, second call generates 0 (no duplicates)
            Assert.AreEqual(1, insightsAfterFirst, "First call should generate 1 insight");
            Assert.AreEqual(1, insightsAfterSecond, "Second call should not generate duplicate");
        }

        #endregion

        #region Category 7: Insight Properties

        [Test]
        public void Test_InsightProperties_SetCorrectly()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);
            var insight = insights[0];

            Assert.AreEqual("GridArbitrageAlphaModel", insight.SourceModel,
                "SourceModel must be GridArbitrageAlphaModel");
            Assert.AreEqual(InsightType.Price, insight.Type,
                "Insight type must be Price");
            Assert.IsNotNull(insight.Id, "Insight Id must be set");
            Assert.AreEqual(pair.Leg1Symbol, insight.Symbol, "Symbol must be Leg1Symbol");
        }

        #endregion

        #region Category 8: Tag Decoding by PCM

        [Test]
        public void Test_TagCanBeDecodedByPCM()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 41100m, 41200m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            _algorithm.OnFrameworkData(slice);

            // Assert
            var insights = _algorithm.Insights.ToList();
            Assert.AreEqual(1, insights.Count);

            // Assert - Verify PCM can decode the Tag
            Assert.AreEqual(1, insights.Count);
            var tag = insights[0].Tag;

            bool decoded = TradingPairManager.TryDecodeGridTag(
                tag, out var leg1Symbol, out var leg2Symbol, out var decodedLevelPair);

            Assert.IsTrue(decoded, "PCM must be able to decode Tag");
            Assert.AreEqual(pair.Leg1Symbol, leg1Symbol, "Decoded Leg1Symbol must match");
            Assert.AreEqual(pair.Leg2Symbol, leg2Symbol, "Decoded Leg2Symbol must match");
            Assert.AreEqual(levelPair.Entry.SpreadPct, decodedLevelPair.Entry.SpreadPct,
                "Decoded entry level must match");
            Assert.AreEqual(levelPair.Exit.SpreadPct, decodedLevelPair.Exit.SpreadPct,
                "Decoded exit level must match");
        }

        #endregion

        #region Helper Methods

        /// <summary>
        /// Sets bid/ask prices for a security using QuoteBar
        /// </summary>
        private void SetPrices(Security security, decimal bid, decimal ask)
        {
            security.SetMarketPrice(new QuoteBar
            {
                Symbol = security.Symbol,
                Time = _algorithm.UtcTime,
                Bid = new Bar(bid, bid, bid, bid),
                Ask = new Bar(ask, ask, ask, ask)
            });
        }

        /// <summary>
        /// Creates a Slice with current security prices at algorithm.UtcTime
        /// </summary>
        private Slice CreateSlice()
        {
            var data = new List<BaseData>();

            // Add current market data for all securities
            if (_btcSecurity?.Cache?.GetData() != null)
            {
                data.Add(_btcSecurity.Cache.GetData());
            }
            if (_mstrSecurity?.Cache?.GetData() != null)
            {
                data.Add(_mstrSecurity.Cache.GetData());
            }

            return new Slice(_algorithm.UtcTime, data, _algorithm.UtcTime);
        }

        /// <summary>
        /// Uses reflection to set GridPosition private backing field
        /// </summary>
        private void SetPositionQuantity(GridPosition position, string propertyName, decimal value)
        {
            var field = typeof(GridPosition).GetField($"<{propertyName}>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            field.SetValue(position, value);
        }

        /// <summary>
        /// Creates an invested position and adds it to the trading pair
        /// </summary>
        private GridPosition CreateInvestedPosition(TradingPair pair, GridLevelPair levelPair,
            decimal leg1Qty, decimal leg2Qty)
        {
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", leg1Qty);
            SetPositionQuantity(position, "Leg2Quantity", leg2Qty);

            var tag = TradingPairManager.EncodeGridTag(pair.Leg1Symbol, pair.Leg2Symbol, levelPair);
            pair.GridPositions[tag] = position;

            return position;
        }

        #endregion
    }
}
