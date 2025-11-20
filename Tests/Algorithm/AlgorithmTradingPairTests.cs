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
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Common;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;

namespace QuantConnect.Tests.Algorithm
{
    [TestFixture]
    public class AlgorithmTradingPairTests
    {
        private QCAlgorithm _algorithm;

        [SetUp]
        public void Setup()
        {
            _algorithm = new QCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(new DataManagerStub(_algorithm));
        }

        #region AddTradingPair Tests

        [Test]
        public void Test_AddTradingPair_CreatesNewPair()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;

            // Act
            var pair = _algorithm.AddTradingPair(spy, aapl);

            // Assert
            Assert.IsNotNull(pair);
            Assert.AreEqual(spy, pair.Leg1Symbol);
            Assert.AreEqual(aapl, pair.Leg2Symbol);
            Assert.AreEqual("spread", pair.PairType);
        }

        [Test]
        public void Test_AddTradingPair_WithCustomPairType()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var qqq = _algorithm.AddEquity("QQQ", Resolution.Minute).Symbol;

            // Act
            var pair = _algorithm.AddTradingPair(spy, qqq, "custom_spread");

            // Assert
            Assert.IsNotNull(pair);
            Assert.AreEqual("custom_spread", pair.PairType);
        }

        [Test]
        public void Test_AddTradingPair_IncrementsCount()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;
            var qqq = _algorithm.AddEquity("QQQ", Resolution.Minute).Symbol;

            // Act
            _algorithm.AddTradingPair(spy, aapl);
            _algorithm.AddTradingPair(spy, qqq);

            // Assert
            Assert.AreEqual(2, _algorithm.TradingPairs.Count);
        }

        [Test]
        public void Test_AddTradingPair_ReturnsSameInstanceIfExists()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;

            // Act
            var pair1 = _algorithm.AddTradingPair(spy, aapl);
            var pair2 = _algorithm.AddTradingPair(spy, aapl);

            // Assert
            Assert.AreSame(pair1, pair2);
            Assert.AreEqual(1, _algorithm.TradingPairs.Count);
        }

        [Test]
        public void Test_AddTradingPair_ThrowsIfLeg1SecurityNotAdded()
        {
            // Arrange
            var spy = Symbol.Create("SPY", SecurityType.Equity, QuantConnect.Market.USA);
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                _algorithm.AddTradingPair(spy, aapl));
            Assert.That(ex.Message, Does.Contain("must be added to the algorithm"));
        }

        [Test]
        public void Test_AddTradingPair_ThrowsIfLeg2SecurityNotAdded()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = Symbol.Create("AAPL", SecurityType.Equity, QuantConnect.Market.USA);

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                _algorithm.AddTradingPair(spy, aapl));
            Assert.That(ex.Message, Does.Contain("must be added to the algorithm"));
        }

        #endregion

        #region TradingPairs Property Tests

        [Test]
        public void Test_TradingPairs_PropertyExists()
        {
            // Act & Assert
            Assert.IsNotNull(_algorithm.TradingPairs);
        }

        [Test]
        public void Test_TradingPairs_InitiallyEmpty()
        {
            // Act & Assert
            Assert.AreEqual(0, _algorithm.TradingPairs.Count);
        }

        [Test]
        public void Test_TradingPairs_AccessByTuple()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;
            var addedPair = _algorithm.AddTradingPair(spy, aapl);

            // Act
            var retrieved = _algorithm.TradingPairs[(spy, aapl)];

            // Assert
            Assert.AreSame(addedPair, retrieved);
        }

        [Test]
        public void Test_TradingPairs_ContainsKey()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;
            _algorithm.AddTradingPair(spy, aapl);

            // Act
            var found = _algorithm.TradingPairs.TryGetValue((spy, aapl), out var pair);

            // Assert
            Assert.IsTrue(found);
            Assert.IsNotNull(pair);
        }

        #endregion

        #region Slice Integration Tests

        [Test]
        public void Test_Slice_ContainsTradingPairs()
        {
            // Arrange
            var spy = _algorithm.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = _algorithm.AddEquity("AAPL", Resolution.Minute).Symbol;
            _algorithm.AddTradingPair(spy, aapl);

            // Create a slice with TradingPairs
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(DateTime.UtcNow);
            var slice = CreateSlice(tradingPairs);

            // Act & Assert
            Assert.IsNotNull(slice.TradingPairs);
        }

        [Test]
        public void Test_OnData_CanAccessTradingPairs()
        {
            // Arrange
            var testAlgo = new TradingPairAccessTestAlgorithm();
            testAlgo.SubscriptionManager.SetDataManager(new DataManagerStub(testAlgo));

            var spy = testAlgo.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = testAlgo.AddEquity("AAPL", Resolution.Minute).Symbol;
            testAlgo.AddTradingPair(spy, aapl);

            // Update prices
            SetSecurityPrices(testAlgo.Securities[spy], 100m, 101m);
            SetSecurityPrices(testAlgo.Securities[aapl], 99m, 100m);

            // Update trading pairs
            testAlgo.TradingPairs.UpdateAll();

            // Create slice with trading pairs
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(DateTime.UtcNow);
            foreach (var pair in testAlgo.TradingPairs)
            {
                tradingPairs.Add(pair);
            }
            var slice = CreateSlice(tradingPairs);

            // Act
            testAlgo.OnData(slice);

            // Assert
            Assert.IsTrue(testAlgo.TradingPairsAccessed);
            Assert.AreEqual(1, testAlgo.PairsCount);
        }

        [Test]
        public void Test_OnData_CanIterateTradingPairs()
        {
            // Arrange
            var testAlgo = new TradingPairIterationTestAlgorithm();
            testAlgo.SubscriptionManager.SetDataManager(new DataManagerStub(testAlgo));

            var spy = testAlgo.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = testAlgo.AddEquity("AAPL", Resolution.Minute).Symbol;
            var qqq = testAlgo.AddEquity("QQQ", Resolution.Minute).Symbol;

            testAlgo.AddTradingPair(spy, aapl);
            testAlgo.AddTradingPair(spy, qqq);

            // Create slice with trading pairs
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(DateTime.UtcNow);
            foreach (var pair in testAlgo.TradingPairs)
            {
                tradingPairs.Add(pair);
            }
            var slice = CreateSlice(tradingPairs);

            // Act
            testAlgo.OnData(slice);

            // Assert
            Assert.AreEqual(2, testAlgo.IteratedPairsCount);
        }

        [Test]
        public void Test_OnData_CanFilterCrossedPairs()
        {
            // Arrange
            var testAlgo = new CrossedPairsFilterTestAlgorithm();
            testAlgo.SubscriptionManager.SetDataManager(new DataManagerStub(testAlgo));

            var spy = testAlgo.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = testAlgo.AddEquity("AAPL", Resolution.Minute).Symbol;
            var qqq = testAlgo.AddEquity("QQQ", Resolution.Minute).Symbol;

            testAlgo.AddTradingPair(spy, aapl);
            testAlgo.AddTradingPair(spy, qqq);

            // Set prices to create one crossed pair
            SetSecurityPrices(testAlgo.Securities[spy], 101m, 102m);
            SetSecurityPrices(testAlgo.Securities[aapl], 99m, 100m);  // Crossed
            SetSecurityPrices(testAlgo.Securities[qqq], 100m, 103m);  // NoOpportunity

            // Update trading pairs
            testAlgo.TradingPairs.UpdateAll();

            // Create slice with trading pairs
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(DateTime.UtcNow);
            foreach (var pair in testAlgo.TradingPairs)
            {
                tradingPairs.Add(pair);
            }
            var slice = CreateSlice(tradingPairs);

            // Act
            testAlgo.OnData(slice);

            // Assert
            Assert.AreEqual(1, testAlgo.CrossedPairsCount);
        }

        [Test]
        public void Test_OnData_CanReadPairProperties()
        {
            // Arrange
            var testAlgo = new PairPropertiesReadTestAlgorithm();
            testAlgo.SubscriptionManager.SetDataManager(new DataManagerStub(testAlgo));

            var spy = testAlgo.AddEquity("SPY", Resolution.Minute).Symbol;
            var aapl = testAlgo.AddEquity("AAPL", Resolution.Minute).Symbol;
            testAlgo.AddTradingPair(spy, aapl);

            // Set prices
            SetSecurityPrices(testAlgo.Securities[spy], 101m, 102m);
            SetSecurityPrices(testAlgo.Securities[aapl], 99m, 100m);

            // Update trading pairs
            testAlgo.TradingPairs.UpdateAll();

            // Create slice with trading pairs
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(DateTime.UtcNow);
            foreach (var pair in testAlgo.TradingPairs)
            {
                tradingPairs.Add(pair);
            }
            var slice = CreateSlice(tradingPairs);

            // Act
            testAlgo.OnData(slice);

            // Assert
            Assert.IsTrue(testAlgo.PropertiesRead);
            Assert.IsTrue(testAlgo.HasValidPrices);
            Assert.AreEqual(MarketState.Crossed, testAlgo.ObservedMarketState);
        }

        #endregion

        #region Helper Methods

        private void SetSecurityPrices(Security security, decimal bid, decimal ask)
        {
            security.SetMarketPrice(new Tick
            {
                Symbol = security.Symbol,
                Value = (bid + ask) / 2,
                BidPrice = bid,
                AskPrice = ask,
                TickType = TickType.Quote,
                Time = DateTime.UtcNow
            });
        }

        private Slice CreateSlice(QuantConnect.Data.Market.TradingPairs tradingPairs)
        {
            var time = DateTime.UtcNow;
            return new Slice(
                time,
                new List<BaseData>(),
                new TradeBars(),
                new QuoteBars(),
                new Ticks(),
                new OrderbookDepths(),
                new OptionChains(),
                new FuturesChains(),
                new Splits(),
                new Dividends(),
                new Delistings(),
                new SymbolChangedEvents(),
                new MarginInterestRates(),
                tradingPairs,
                time
            );
        }

        #endregion

        #region Test Algorithms

        private class TradingPairAccessTestAlgorithm : QCAlgorithm
        {
            public bool TradingPairsAccessed { get; private set; }
            public int PairsCount { get; private set; }

            public override void OnData(Slice slice)
            {
                if (slice.TradingPairs != null)
                {
                    TradingPairsAccessed = true;
                    PairsCount = slice.TradingPairs.Count;
                }
            }
        }

        private class TradingPairIterationTestAlgorithm : QCAlgorithm
        {
            public int IteratedPairsCount { get; private set; }

            public override void OnData(Slice slice)
            {
                if (slice.TradingPairs != null)
                {
                    foreach (var pair in slice.TradingPairs)
                    {
                        IteratedPairsCount++;
                    }
                }
            }
        }

        private class CrossedPairsFilterTestAlgorithm : QCAlgorithm
        {
            public int CrossedPairsCount { get; private set; }

            public override void OnData(Slice slice)
            {
                if (slice.TradingPairs != null)
                {
                    CrossedPairsCount = slice.TradingPairs.GetCrossedPairs().Count();
                }
            }
        }

        private class PairPropertiesReadTestAlgorithm : QCAlgorithm
        {
            public bool PropertiesRead { get; private set; }
            public bool HasValidPrices { get; private set; }
            public MarketState ObservedMarketState { get; private set; }

            public override void OnData(Slice slice)
            {
                if (slice.TradingPairs != null && slice.TradingPairs.Count > 0)
                {
                    foreach (var pair in slice.TradingPairs)
                    {
                        PropertiesRead = true;
                        HasValidPrices = pair.HasValidPrices;
                        ObservedMarketState = pair.MarketState;
                        break; // Only check first pair
                    }
                }
            }
        }

        #endregion
    }
}
