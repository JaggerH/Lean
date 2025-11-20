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
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;

namespace QuantConnect.Tests.Common.Data.Market
{
    [TestFixture]
    public class TradingPairsTests
    {
        private Security _spySecurity;
        private Security _aaplSecurity;
        private Security _qqqSecurity;

        [SetUp]
        public void Setup()
        {
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var dateTime = new DateTime(2024, 1, 1, 9, 30, 0);
            var timeKeeper = new LocalTimeKeeper(dateTime.ConvertToUtc(TimeZones.NewYork), TimeZones.NewYork);

            _spySecurity = CreateSecurity(Symbols.SPY, exchangeHours, timeKeeper);
            _aaplSecurity = CreateSecurity(Symbols.AAPL, exchangeHours, timeKeeper);
            _qqqSecurity = CreateSecurity(Symbol.Create("QQQ", SecurityType.Equity, QuantConnect.Market.USA), exchangeHours, timeKeeper);
        }

        private Security CreateSecurity(Symbol symbol, SecurityExchangeHours exchangeHours, LocalTimeKeeper timeKeeper)
        {
            var config = new SubscriptionDataConfig(
                typeof(TradeBar),
                symbol,
                Resolution.Minute,
                TimeZones.NewYork,
                TimeZones.NewYork,
                true,
                true,
                false
            );

            var security = new Security(
                exchangeHours,
                config,
                new Cash(Currencies.USD, 0, 1m),
                SymbolProperties.GetDefault(Currencies.USD),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            security.SetLocalTimeKeeper(timeKeeper);
            return security;
        }

        private void SetSecurityPrices(Security security, decimal bid, decimal ask)
        {
            security.SetMarketPrice(new Tick
            {
                Symbol = security.Symbol,
                Value = (bid + ask) / 2,
                BidPrice = bid,
                AskPrice = ask,
                TickType = TickType.Quote,
                Time = security.LocalTime
            });
        }

        private TradingPair CreatePair(Symbol leg1, Symbol leg2, Security leg1Security, Security leg2Security)
        {
            return new TradingPair(leg1, leg2, "spread", leg1Security, leg2Security);
        }

        #region Initialization Tests

        [Test]
        public void Test_Constructor_Default_InitializesEmpty()
        {
            // Arrange & Act
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Assert
            Assert.AreEqual(0, collection.Count);
            Assert.IsNotNull(collection);
        }

        [Test]
        public void Test_Constructor_WithTime_InitializesWithTime()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);

            // Act
            var collection = new QuantConnect.Data.Market.TradingPairs(time);

            // Assert
            Assert.AreEqual(0, collection.Count);
            Assert.AreEqual(time, collection.Time);
        }

        #endregion

        #region Add Tests

        [Test]
        public void Test_Add_AddsNewPair()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Act
            collection.Add(pair);

            // Assert
            Assert.AreEqual(1, collection.Count);
        }

        [Test]
        public void Test_Add_CreatesCompositeSymbol()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Act
            collection.Add(pair);

            // Assert - The collection should have both DataDictionary key and tuple key
            Assert.AreEqual(1, collection.Count);
            Assert.IsTrue(collection.ContainsKey((Symbols.SPY, Symbols.AAPL)));
        }

        [Test]
        public void Test_Add_MultiplePairs()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // Act
            collection.Add(pair1);
            collection.Add(pair2);

            // Assert
            Assert.AreEqual(2, collection.Count);
        }

        #endregion

        #region Tuple Indexer Tests

        [Test]
        public void Test_TupleIndexer_Get_ReturnsCorrectPair()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            collection.Add(pair);

            // Act
            var retrieved = collection[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.AreSame(pair, retrieved);
        }

        [Test]
        public void Test_TupleIndexer_Get_ThrowsIfNotFound()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Act & Assert
            Assert.Throws<KeyNotFoundException>(() =>
            {
                var pair = collection[(Symbols.SPY, Symbols.AAPL)];
            });
        }

        [Test]
        public void Test_TupleIndexer_Set_AddsPair()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Act
            collection[(Symbols.SPY, Symbols.AAPL)] = pair;

            // Assert
            Assert.AreEqual(1, collection.Count);
            Assert.AreSame(pair, collection[(Symbols.SPY, Symbols.AAPL)]);
        }

        [Test]
        public void Test_TupleIndexer_Set_UpdatesExistingPair()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            collection.Add(pair1);

            // Act
            collection[(Symbols.SPY, Symbols.AAPL)] = pair2;

            // Assert
            Assert.AreEqual(1, collection.Count);
            Assert.AreSame(pair2, collection[(Symbols.SPY, Symbols.AAPL)]);
        }

        #endregion

        #region TryGetValue Tests

        [Test]
        public void Test_TryGetValue_ReturnsTrueIfFound()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            collection.Add(pair);

            // Act
            var found = collection.TryGetValue((Symbols.SPY, Symbols.AAPL), out var retrieved);

            // Assert
            Assert.IsTrue(found);
            Assert.AreSame(pair, retrieved);
        }

        [Test]
        public void Test_TryGetValue_ReturnsFalseIfNotFound()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Act
            var found = collection.TryGetValue((Symbols.SPY, Symbols.AAPL), out var retrieved);

            // Assert
            Assert.IsFalse(found);
            Assert.IsNull(retrieved);
        }

        #endregion

        #region ContainsKey Tests

        [Test]
        public void Test_ContainsKey_ReturnsTrueIfExists()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            collection.Add(pair);

            // Act
            var contains = collection.ContainsKey((Symbols.SPY, Symbols.AAPL));

            // Assert
            Assert.IsTrue(contains);
        }

        [Test]
        public void Test_ContainsKey_ReturnsFalseIfNotExists()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Act
            var contains = collection.ContainsKey((Symbols.SPY, Symbols.AAPL));

            // Assert
            Assert.IsFalse(contains);
        }

        #endregion

        #region GetByState Tests

        [Test]
        public void Test_GetByState_ReturnsCrossedPairs()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // Set prices to create Crossed state for pair1
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // Crossed
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // NoOpportunity

            pair1.Update();
            pair2.Update();

            collection.Add(pair1);
            collection.Add(pair2);

            // Act
            var crossed = collection.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.AreEqual(1, crossed.Count);
            Assert.AreSame(pair1, crossed[0]);
        }

        [Test]
        public void Test_GetByState_ReturnsNoOpportunityPairs()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // Set prices for NoOpportunity state
            SetSecurityPrices(_spySecurity, bid: 99m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_qqqSecurity, bid: 100.5m, ask: 101.5m);

            pair1.Update();
            pair2.Update();

            collection.Add(pair1);
            collection.Add(pair2);

            // Act
            var noOpportunity = collection.GetByState(MarketState.NoOpportunity).ToList();

            // Assert
            Assert.AreEqual(2, noOpportunity.Count);
        }

        [Test]
        public void Test_GetByState_ReturnsEmptyIfNoMatches()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            SetSecurityPrices(_spySecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_aaplSecurity, bid: 100.2m, ask: 101.2m);
            pair.Update();

            collection.Add(pair);

            // Act
            var crossed = collection.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.IsEmpty(crossed);
        }

        #endregion

        #region GetCrossedPairs Tests

        [Test]
        public void Test_GetCrossedPairs_ReturnsOnlyCrossedPairs()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // Crossed
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // NoOpportunity

            pair1.Update();
            pair2.Update();

            collection.Add(pair1);
            collection.Add(pair2);

            // Act
            var crossed = collection.GetCrossedPairs().ToList();

            // Assert
            Assert.AreEqual(1, crossed.Count);
            Assert.AreEqual(MarketState.Crossed, crossed[0].MarketState);
        }

        [Test]
        public void Test_GetCrossedPairs_ReturnsEmptyIfNone()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            SetSecurityPrices(_spySecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_aaplSecurity, bid: 100.2m, ask: 101.2m);
            pair.Update();

            collection.Add(pair);

            // Act
            var crossed = collection.GetCrossedPairs().ToList();

            // Assert
            Assert.IsEmpty(crossed);
        }

        #endregion

        #region Enumeration Tests

        [Test]
        public void Test_GetEnumerator_IteratesAllPairs()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);
            collection.Add(pair1);
            collection.Add(pair2);

            // Act
            var count = 0;
            foreach (var pair in collection)
            {
                Assert.IsNotNull(pair);
                count++;
            }

            // Assert
            Assert.AreEqual(2, count);
        }

        [Test]
        public void Test_Enumeration_SupportsLinq()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);
            var pair3 = CreatePair(Symbols.AAPL, _qqqSecurity.Symbol, _aaplSecurity, _qqqSecurity);

            collection.Add(pair1);
            collection.Add(pair2);
            collection.Add(pair3);

            // Act - Collect pairs using foreach (which uses the custom GetEnumerator)
            var allPairs = new List<TradingPair>();
            foreach (var pair in collection)
            {
                allPairs.Add(pair);
            }
            var spyPairs = allPairs.Where(p => p.Leg1Symbol == Symbols.SPY).ToList();

            // Assert
            Assert.AreEqual(2, spyPairs.Count);
            Assert.IsTrue(spyPairs.All(p => p.Leg1Symbol == Symbols.SPY));
        }

        #endregion

        #region DataDictionary Compatibility Tests

        [Test]
        public void Test_DataDictionary_CountProperty()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Act & Assert
            Assert.AreEqual(0, collection.Count);
            collection.Add(pair);
            Assert.AreEqual(1, collection.Count);
        }

        [Test]
        public void Test_DataDictionary_TimeProperty()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 30, 0);
            var collection = new QuantConnect.Data.Market.TradingPairs(time);

            // Act & Assert
            Assert.AreEqual(time, collection.Time);
        }

        [Test]
        public void Test_Add_StoresInBothDictionaries()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Act
            collection.Add(pair);

            // Assert - Can access via both tuple key and DataDictionary enumeration
            Assert.IsTrue(collection.ContainsKey((Symbols.SPY, Symbols.AAPL)));
            Assert.AreEqual(1, collection.Count);

            // Verify we can enumerate (uses tuple dictionary)
            var enumerated = collection.ToList();
            Assert.AreEqual(1, enumerated.Count);
        }

        #endregion

        #region Edge Cases

        [Test]
        public void Test_EmptyCollection_EnumerationWorks()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Act
            var count = 0;
            foreach (var pair in collection)
            {
                count++;
            }

            // Assert
            Assert.AreEqual(0, count);
        }

        [Test]
        public void Test_GetByState_WithEmptyCollection()
        {
            // Arrange
            var collection = new QuantConnect.Data.Market.TradingPairs();

            // Act
            var crossed = collection.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.IsEmpty(crossed);
        }

        #endregion
    }
}
