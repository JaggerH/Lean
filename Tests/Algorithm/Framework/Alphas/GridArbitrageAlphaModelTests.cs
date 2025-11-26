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
using System.Linq;
using System.Reflection;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Algorithm.Framework.Alphas
{
    [TestFixture]
    public class GridArbitrageAlphaModelTests
    {
        private AQCAlgorithm _algorithm;
        private GridArbitrageAlphaModel _alphaModel;
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;
        private Security _btcSecurity;
        private Security _mstrSecurity;

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
            _btcSecurity = _algorithm.AddSecurity(_btcSymbol);
            _mstrSecurity = _algorithm.AddSecurity(_mstrSymbol);
        }

        [SetUp]
        public void Setup()
        {
            _alphaModel = new GridArbitrageAlphaModel(
                insightPeriod: TimeSpan.FromMinutes(5),
                confidence: 1.0,
                allowMultipleEntriesPerLevel: false,
                requireValidPrices: true);
        }

        #region Entry Signal Blocking for Pending Removal

        [Test]
        public void Test_CheckEntrySignal_PendingRemovalPair_ReturnsNull()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            pair.AddLevelPair(-0.02m, 0.01m, SpreadDirection.LongSpread, 0.25m);

            // Mark as pending removal
            var position = AddActivePosition(pair, 1.0m, -100m);
            _algorithm.TradingPairs.RemovePair(_btcSymbol, _mstrSymbol);

            SetPrices(_btcSecurity, 40000m, 40100m);
            SetPrices(_mstrSecurity, 40600m, 40700m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            var insights = _alphaModel.Update(_algorithm, slice).ToList();

            // Assert - No entry insights should be generated
            var entryInsights = insights.Where(i => i.Type == SignalType.Entry);
            Assert.IsEmpty(entryInsights);
        }

        #endregion

        #region Exit Signal Generation for Pending Removal

        [Test]
        public void Test_CheckExitSignal_PendingRemovalPair_GeneratesExit()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(levelPair);

            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", 1.0m);
            SetPositionQuantity(position, "Leg2Quantity", -100m);

            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);
            pair.GridPositions[tag] = position;

            // Mark as pending removal
            _algorithm.TradingPairs.RemovePair(_btcSymbol, _mstrSymbol);

            // Set prices to trigger exit (spread >= 0.01)
            SetPrices(_btcSecurity, 41000m, 41100m);
            SetPrices(_mstrSecurity, 40000m, 40100m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            var insights = _alphaModel.Update(_algorithm, slice).ToList();

            // Assert - Exit insight should be generated despite pending removal
            var exitInsights = insights.Where(i => i.Type == SignalType.Exit);
            Assert.AreEqual(1, exitInsights.Count());
        }

        #endregion

        #region CheckExitSignal Using Position.LevelPair

        [Test]
        public void Test_CheckExitSignal_UsesPositionLevelPair()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSymbol, _mstrSymbol));

            // Create position with specific LevelPair
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", 1.0m);
            SetPositionQuantity(position, "Leg2Quantity", -100m);

            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);
            pair.GridPositions[tag] = position;

            // Clear pair's LevelPairs to verify position uses its own
            pair.LevelPairs.Clear();

            // Set prices to trigger exit
            SetPrices(_btcSecurity, 41000m, 41100m);
            SetPrices(_mstrSecurity, 40000m, 40100m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            var insights = _alphaModel.Update(_algorithm, slice).ToList();

            // Assert - Exit should still be generated using position's LevelPair
            var exitInsights = insights.Where(i => i.Type == SignalType.Exit);
            Assert.AreEqual(1, exitInsights.Count());
            Assert.AreEqual(0.01m, exitInsights.First().LevelPair.Exit.SpreadPct);
        }

        [Test]
        public void Test_CheckExitSignal_PositionLevelPairIndependentOfPairConfig()
        {
            // Arrange
            var pair = _algorithm.TradingPairs.AddPair(_btcSymbol, _mstrSymbol);

            // Original level pair with 0.01m exit
            var originalLevelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                                      (_btcSymbol, _mstrSymbol));

            // Create position with original level pair
            var position = new GridPosition(pair, originalLevelPair);
            SetPositionQuantity(position, "Leg1Quantity", 1.0m);
            SetPositionQuantity(position, "Leg2Quantity", -100m);

            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, originalLevelPair);
            pair.GridPositions[tag] = position;

            // Modify pair's LevelPairs (simulating user changing config)
            pair.LevelPairs.Clear();
            var newLevelPair = new GridLevelPair(-0.02m, 0.02m, "LONG_SPREAD", 0.25m,
                                                 (_btcSymbol, _mstrSymbol));
            pair.AddLevelPair(newLevelPair);

            // Set prices to trigger exit at 0.01 (original) but NOT at 0.02 (new)
            SetPrices(_btcSecurity, 40500m, 40600m);
            SetPrices(_mstrSecurity, 40000m, 40100m);
            _algorithm.TradingPairs.UpdateAll();

            // Act
            var slice = CreateSlice();
            var insights = _alphaModel.Update(_algorithm, slice).ToList();

            // Assert - Exit should be generated using position's original LevelPair (0.01m exit)
            var exitInsights = insights.Where(i => i.Type == SignalType.Exit);
            Assert.AreEqual(1, exitInsights.Count());
            Assert.AreEqual(0.01m, exitInsights.First().LevelPair.Exit.SpreadPct);
        }

        #endregion

        #region Helper Methods

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

        private Slice CreateSlice()
        {
            var data = new BaseData[0];
            return new Slice(_algorithm.UtcTime, data, _algorithm.UtcTime);
        }

        private GridPosition AddActivePosition(TradingPair pair, decimal leg1Qty, decimal leg2Qty)
        {
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (pair.Leg1Symbol, pair.Leg2Symbol));
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", leg1Qty);
            SetPositionQuantity(position, "Leg2Quantity", leg2Qty);

            var tag = TradingPairManager.EncodeGridTag(pair.Leg1Symbol, pair.Leg2Symbol, levelPair);
            pair.GridPositions[tag] = position;

            return position;
        }

        private void SetPositionQuantity(GridPosition position, string propertyName, decimal value)
        {
            var field = typeof(GridPosition).GetField($"<{propertyName}>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            field.SetValue(position, value);
        }

        #endregion
    }
}
