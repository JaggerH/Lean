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

namespace QuantConnect.Tests.Common.Data
{
    [TestFixture]
    public class SliceTradingPairsTests
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
            var pair = new TradingPair(leg1, leg2, "spread", leg1Security, leg2Security);
            return pair;
        }

        private Slice CreateSlice(DateTime time, QuantConnect.Data.Market.TradingPairs tradingPairs)
        {
            var bars = new TradeBars();
            var quotes = new QuoteBars();
            var ticks = new Ticks();
            var orderbookDepths = new OrderbookDepths();
            var options = new OptionChains();
            var futures = new FuturesChains();
            var splits = new Splits();
            var dividends = new Dividends();
            var delistings = new Delistings();
            var symbolChanges = new SymbolChangedEvents();
            var marginInterestRates = new MarginInterestRates();

            return new Slice(
                time,
                new List<BaseData>(),
                bars,
                quotes,
                ticks,
                orderbookDepths,
                options,
                futures,
                splits,
                dividends,
                delistings,
                symbolChanges,
                marginInterestRates,
                tradingPairs,
                time.ConvertToUtc(TimeZones.NewYork)
            );
        }

        #region Slice TradingPairs Property Tests

        [Test]
        public void Test_Slice_TradingPairsProperty_Exists()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            // Act
            var slice = CreateSlice(time, tradingPairs);

            // Assert
            Assert.IsNotNull(slice.TradingPairs);
        }

        [Test]
        public void Test_Slice_TradingPairsProperty_ReturnsCorrectInstance()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            // Act
            var slice = CreateSlice(time, tradingPairs);

            // Assert
            Assert.AreSame(tradingPairs, slice.TradingPairs);
        }

        [Test]
        public void Test_Slice_WithEmptyTradingPairs()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            // Act
            var slice = CreateSlice(time, tradingPairs);

            // Assert
            Assert.IsNotNull(slice.TradingPairs);
            Assert.AreEqual(0, slice.TradingPairs.Count);
        }

        [Test]
        public void Test_Slice_WithPopulatedTradingPairs()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            tradingPairs.Add(pair);

            // Act
            var slice = CreateSlice(time, tradingPairs);

            // Assert
            Assert.AreEqual(1, slice.TradingPairs.Count);
        }

        #endregion

        #region Accessing TradingPairs Through Slice

        [Test]
        public void Test_Slice_AccessPairByTuple()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            tradingPairs.Add(pair);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var retrieved = slice.TradingPairs[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.AreSame(pair, retrieved);
        }

        [Test]
        public void Test_Slice_TryGetPairByTuple()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            tradingPairs.Add(pair);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var found = slice.TradingPairs.TryGetValue((Symbols.SPY, Symbols.AAPL), out var retrieved);

            // Assert
            Assert.IsTrue(found);
            Assert.AreSame(pair, retrieved);
        }

        [Test]
        public void Test_Slice_ContainsKeyByTuple()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            tradingPairs.Add(pair);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var contains = slice.TradingPairs.ContainsKey((Symbols.SPY, Symbols.AAPL));

            // Assert
            Assert.IsTrue(contains);
        }

        [Test]
        public void Test_Slice_IterateTradingPairs()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);
            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var count = 0;
            foreach (var pair in slice.TradingPairs)
            {
                Assert.IsNotNull(pair);
                count++;
            }

            // Assert
            Assert.AreEqual(2, count);
        }

        #endregion

        #region Filtering Methods Through Slice

        [Test]
        public void Test_Slice_GetCrossedPairs()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // Set prices to create Crossed state for pair1
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // Crossed
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // NoOpportunity

            pair1.Update();
            pair2.Update();

            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var crossed = slice.TradingPairs.GetCrossedPairs().ToList();

            // Assert
            Assert.AreEqual(1, crossed.Count);
            Assert.AreEqual(MarketState.Crossed, crossed[0].MarketState);
        }

        [Test]
        public void Test_Slice_GetByState_Crossed()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // Crossed
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // NoOpportunity

            pair1.Update();
            pair2.Update();

            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var crossed = slice.TradingPairs.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.AreEqual(1, crossed.Count);
            Assert.AreSame(pair1, crossed[0]);
        }

        [Test]
        public void Test_Slice_GetByState_NoOpportunity()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // Set prices for NoOpportunity state
            SetSecurityPrices(_spySecurity, bid: 99m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_qqqSecurity, bid: 100.5m, ask: 101.5m);

            pair1.Update();
            pair2.Update();

            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var noOpportunity = slice.TradingPairs.GetByState(MarketState.NoOpportunity).ToList();

            // Assert
            Assert.AreEqual(2, noOpportunity.Count);
        }

        #endregion

        #region Reading Pair Data Through Slice

        [Test]
        public void Test_Slice_ReadPairPrices()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            SetSecurityPrices(_spySecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);
            pair.Update();

            tradingPairs.Add(pair);
            var slice = CreateSlice(time, tradingPairs);

            // Act
            var retrieved = slice.TradingPairs[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.IsTrue(retrieved.HasValidPrices);
            Assert.AreEqual(100m, retrieved.Leg1BidPrice);
            Assert.AreEqual(101m, retrieved.Leg1AskPrice);
            Assert.AreEqual(99m, retrieved.Leg2BidPrice);
            Assert.AreEqual(100m, retrieved.Leg2AskPrice);
        }

        [Test]
        public void Test_Slice_ReadPairSpreads()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);
            pair.Update();

            tradingPairs.Add(pair);
            var slice = CreateSlice(time, tradingPairs);

            // Act
            var retrieved = slice.TradingPairs[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.AreEqual(MarketState.Crossed, retrieved.MarketState);
            Assert.IsNotNull(retrieved.ExecutableSpread);
            Assert.AreEqual("SHORT_SPREAD", retrieved.Direction);
        }

        [Test]
        public void Test_Slice_ReadPairMarketState()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var pair = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);

            // Wide spread to avoid LimitOpportunity patterns
            SetSecurityPrices(_spySecurity, bid: 99m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 100m, ask: 101m);
            pair.Update();

            tradingPairs.Add(pair);
            var slice = CreateSlice(time, tradingPairs);

            // Act
            var retrieved = slice.TradingPairs[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.AreEqual(MarketState.NoOpportunity, retrieved.MarketState);
            Assert.IsNull(retrieved.ExecutableSpread);
            Assert.AreEqual("none", retrieved.Direction);
        }

        #endregion

        #region Multiple Pairs Scenarios

        [Test]
        public void Test_Slice_MultiplePairs_DifferentStates()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);

            // pair1: Crossed, pair2: NoOpportunity
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);

            pair1.Update();
            pair2.Update();

            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);

            var slice = CreateSlice(time, tradingPairs);

            // Act
            var crossedCount = slice.TradingPairs.GetByState(MarketState.Crossed).Count();
            var noOpportunityCount = slice.TradingPairs.GetByState(MarketState.NoOpportunity).Count();

            // Assert
            Assert.AreEqual(1, crossedCount);
            Assert.AreEqual(1, noOpportunityCount);
        }

        [Test]
        public void Test_Slice_MultiplePairs_AllAccessible()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            var pair1 = CreatePair(Symbols.SPY, Symbols.AAPL, _spySecurity, _aaplSecurity);
            var pair2 = CreatePair(Symbols.SPY, _qqqSecurity.Symbol, _spySecurity, _qqqSecurity);
            var pair3 = CreatePair(Symbols.AAPL, _qqqSecurity.Symbol, _aaplSecurity, _qqqSecurity);

            tradingPairs.Add(pair1);
            tradingPairs.Add(pair2);
            tradingPairs.Add(pair3);

            var slice = CreateSlice(time, tradingPairs);

            // Act & Assert
            Assert.IsTrue(slice.TradingPairs.ContainsKey((Symbols.SPY, Symbols.AAPL)));
            Assert.IsTrue(slice.TradingPairs.ContainsKey((Symbols.SPY, _qqqSecurity.Symbol)));
            Assert.IsTrue(slice.TradingPairs.ContainsKey((Symbols.AAPL, _qqqSecurity.Symbol)));

            Assert.AreSame(pair1, slice.TradingPairs[(Symbols.SPY, Symbols.AAPL)]);
            Assert.AreSame(pair2, slice.TradingPairs[(Symbols.SPY, _qqqSecurity.Symbol)]);
            Assert.AreSame(pair3, slice.TradingPairs[(Symbols.AAPL, _qqqSecurity.Symbol)]);
        }

        #endregion

        #region Edge Cases

        [Test]
        public void Test_Slice_NullTradingPairs()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);

            // Act
            var slice = CreateSlice(time, null);

            // Assert
            Assert.IsNull(slice.TradingPairs);
        }

        [Test]
        public void Test_Slice_EmptyTradingPairs_EnumerationWorks()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var slice = CreateSlice(time, tradingPairs);

            // Act
            var count = 0;
            foreach (var pair in slice.TradingPairs)
            {
                count++;
            }

            // Assert
            Assert.AreEqual(0, count);
        }

        [Test]
        public void Test_Slice_EmptyTradingPairs_GetCrossedPairsReturnsEmpty()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 0, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);
            var slice = CreateSlice(time, tradingPairs);

            // Act
            var crossed = slice.TradingPairs.GetCrossedPairs().ToList();

            // Assert
            Assert.IsEmpty(crossed);
        }

        #endregion

        #region Time Consistency

        [Test]
        public void Test_Slice_Time_MatchesTradingPairsTime()
        {
            // Arrange
            var time = new DateTime(2024, 1, 1, 10, 30, 0);
            var tradingPairs = new QuantConnect.Data.Market.TradingPairs(time);

            // Act
            var slice = CreateSlice(time, tradingPairs);

            // Assert
            Assert.AreEqual(time, slice.Time);
            Assert.AreEqual(time, slice.TradingPairs.Time);
        }

        [Test]
        public void Test_Slice_MultipleTimes_TradingPairsPreserveTime()
        {
            // Arrange
            var time1 = new DateTime(2024, 1, 1, 10, 0, 0);
            var time2 = new DateTime(2024, 1, 1, 10, 1, 0);

            var tradingPairs1 = new QuantConnect.Data.Market.TradingPairs(time1);
            var tradingPairs2 = new QuantConnect.Data.Market.TradingPairs(time2);

            // Act
            var slice1 = CreateSlice(time1, tradingPairs1);
            var slice2 = CreateSlice(time2, tradingPairs2);

            // Assert
            Assert.AreEqual(time1, slice1.TradingPairs.Time);
            Assert.AreEqual(time2, slice2.TradingPairs.Time);
        }

        #endregion
    }
}
