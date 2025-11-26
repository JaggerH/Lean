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
using Moq;
using NUnit.Framework;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairManagerTests
    {
        private SecurityManager _securities;
        private SecurityTransactionManager _transactions;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private Security _spySecurity;
        private Security _aaplSecurity;
        private Security _qqqSecurity;

        [SetUp]
        public void Setup()
        {
            _securities = new SecurityManager(new TimeKeeper(DateTime.UtcNow, TimeZones.NewYork));
            _mockAlgorithm = new Mock<AIAlgorithm>();
            _transactions = new SecurityTransactionManager(_mockAlgorithm.Object, _securities);
            _mockAlgorithm.Setup(a => a.Securities).Returns(_securities);
            _mockAlgorithm.Setup(a => a.Transactions).Returns(_transactions);

            // Create test securities
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var dateTime = new DateTime(2024, 1, 1, 9, 30, 0);
            var timeKeeper = new LocalTimeKeeper(dateTime.ConvertToUtc(TimeZones.NewYork), TimeZones.NewYork);

            _spySecurity = CreateSecurity(Symbols.SPY, exchangeHours, timeKeeper);
            _aaplSecurity = CreateSecurity(Symbols.AAPL, exchangeHours, timeKeeper);
            _qqqSecurity = CreateSecurity(Symbol.Create("QQQ", SecurityType.Equity, Market.USA), exchangeHours, timeKeeper);

            _securities.Add(_spySecurity);
            _securities.Add(_aaplSecurity);
            _securities.Add(_qqqSecurity);
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

        #region Initialization Tests

        [Test]
        public void Test_Constructor_InitializesEmptyManager()
        {
            // Arrange & Act
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Assert
            Assert.AreEqual(0, manager.Count);
            Assert.IsEmpty(manager.GetAll());
        }

        #endregion

        #region AddPair Tests

        [Test]
        public void Test_AddPair_CreatesNewPair()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.IsNotNull(pair);
            Assert.AreEqual(Symbols.SPY, pair.Leg1Symbol);
            Assert.AreEqual(Symbols.AAPL, pair.Leg2Symbol);
            Assert.AreEqual("spread", pair.PairType);
            Assert.AreEqual(1, manager.Count);
        }

        [Test]
        public void Test_AddPair_ReturnsSamePairIfExists()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair1 = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Act
            var pair2 = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.AreSame(pair1, pair2, "Should return the same instance");
            Assert.AreEqual(1, manager.Count, "Count should not increase");
        }

        [Test]
        public void Test_AddPair_ThrowsIfLeg1SecurityNotFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var unknownSymbol = Symbol.Create("UNKNOWN", SecurityType.Equity, Market.USA);

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                manager.AddPair(unknownSymbol, Symbols.AAPL));
            Assert.That(ex.Message, Does.Contain("not found in SecurityManager"));
        }

        [Test]
        public void Test_AddPair_ThrowsIfLeg2SecurityNotFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var unknownSymbol = Symbol.Create("UNKNOWN", SecurityType.Equity, Market.USA);

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                manager.AddPair(Symbols.SPY, unknownSymbol));
            Assert.That(ex.Message, Does.Contain("not found in SecurityManager"));
        }

        [Test]
        public void Test_AddPair_DefaultPairType()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.AreEqual("spread", pair.PairType);
        }

        [Test]
        public void Test_AddPair_CustomPairType()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL, "futures");

            // Assert
            Assert.AreEqual("futures", pair.PairType);
        }

        #endregion

        #region RemovePair Tests

        [Test]
        public void Test_RemovePair_WithoutActivePositions_RemovesImmediately()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Act
            var removed = manager.RemovePair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.IsTrue(removed);
            Assert.AreEqual(0, manager.Count);
            Assert.IsFalse(pair.IsPendingRemoval);
        }

        [Test]
        public void Test_RemovePair_WithActivePositions_MarksPendingRemoval()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Create a grid level pair and position
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (Symbols.SPY, Symbols.AAPL));
            var position = new GridPosition(pair, levelPair);

            // Set position quantities using reflection
            SetPositionQuantity(position, "Leg1Quantity", 1.0m);
            SetPositionQuantity(position, "Leg2Quantity", -100m);

            // Add position to pair
            var tag = TradingPairManager.EncodeGridTag(Symbols.SPY, Symbols.AAPL, levelPair);
            pair.GridPositions[tag] = position;

            // Act
            var removed = manager.RemovePair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.IsTrue(removed);
            Assert.AreEqual(1, manager.Count); // Still exists
            Assert.IsTrue(pair.IsPendingRemoval);
            Assert.IsTrue(pair.HasActivePositions);
        }

        [Test]
        public void Test_RemovePair_ReturnsFalseIfNotFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var removed = manager.RemovePair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.IsFalse(removed);
        }

        [Test]
        public void Test_RemovePair_UpdatesCount()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);
            Assert.AreEqual(2, manager.Count);

            // Act
            manager.RemovePair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.AreEqual(1, manager.Count);
        }

        // Helper method for setting GridPosition quantities
        private void SetPositionQuantity(GridPosition position, string propertyName, decimal value)
        {
            var field = typeof(GridPosition).GetField($"<{propertyName}>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            field.SetValue(position, value);
        }

        #endregion

        #region Indexer Access Tests

        [Test]
        public void Test_Indexer_ReturnsExistingPair()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var addedPair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Act
            var retrievedPair = manager[(Symbols.SPY, Symbols.AAPL)];

            // Assert
            Assert.AreSame(addedPair, retrievedPair);
        }

        [Test]
        public void Test_Indexer_ThrowsIfNotFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act & Assert
            Assert.Throws<KeyNotFoundException>(() =>
            {
                var pair = manager[(Symbols.SPY, Symbols.AAPL)];
            });
        }

        [Test]
        public void Test_TryGetValue_ReturnsTrueIfFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var addedPair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Act
            var found = manager.TryGetValue((Symbols.SPY, Symbols.AAPL), out var pair);

            // Assert
            Assert.IsTrue(found);
            Assert.AreSame(addedPair, pair);
        }

        [Test]
        public void Test_TryGetValue_ReturnsFalseIfNotFound()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var found = manager.TryGetValue((Symbols.SPY, Symbols.AAPL), out var pair);

            // Assert
            Assert.IsFalse(found);
            Assert.IsNull(pair);
        }

        #endregion

        #region UpdateAll Tests

        [Test]
        public void Test_UpdateAll_UpdatesAllPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Set prices to create a crossed market
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);

            // Act
            manager.UpdateAll();

            // Assert
            Assert.IsTrue(pair.HasValidPrices);
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
            Assert.AreEqual("SHORT_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_UpdateAll_WithNoPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act & Assert - should not throw
            Assert.DoesNotThrow(() => manager.UpdateAll());
        }

        [Test]
        public void Test_UpdateAll_UpdatesMultiplePairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair1 = manager.AddPair(Symbols.SPY, Symbols.AAPL);
            var pair2 = manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);

            // Set prices for different market states
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // SPY-AAPL: Crossed (101 > 100)
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // SPY-QQQ: NoOpportunity (101 < 103)

            // Act
            manager.UpdateAll();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair1.MarketState);
            Assert.AreEqual(MarketState.NoOpportunity, pair2.MarketState);
        }

        #endregion

        #region GetByState Tests

        [Test]
        public void Test_GetByState_ReturnsCrossedPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);

            // Set prices to create one crossed and one normal
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // SPY-AAPL: Crossed (101 > 100)
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // SPY-QQQ: NoOpportunity (101 < 103)

            manager.UpdateAll();

            // Act
            var crossedPairs = manager.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.AreEqual(1, crossedPairs.Count);
            Assert.AreEqual(Symbols.AAPL, crossedPairs[0].Leg2Symbol);
        }

        [Test]
        public void Test_GetByState_ReturnsNoOpportunityPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);

            // Set prices that avoid LimitOpportunity patterns by having bid1 < bid2 (breaks Pattern 1)
            SetSecurityPrices(_spySecurity, bid: 99m, ask: 102m);       // Wide spread, low bid
            SetSecurityPrices(_aaplSecurity, bid: 100m, ask: 101m);     // Normal spread, higher bid
            SetSecurityPrices(_qqqSecurity, bid: 100.5m, ask: 101.5m);  // Normal spread, even higher bid

            manager.UpdateAll();

            // Act
            var noOpportunityPairs = manager.GetByState(MarketState.NoOpportunity).ToList();

            // Assert
            Assert.AreEqual(2, noOpportunityPairs.Count);
        }

        [Test]
        public void Test_GetByState_ReturnsEmptyIfNoMatches()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Set prices with slightly overlapping ranges but no crossing
            SetSecurityPrices(_spySecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_aaplSecurity, bid: 100.2m, ask: 101.2m);

            manager.UpdateAll();

            // Act - look for Crossed pairs when there are none
            var crossedPairs = manager.GetByState(MarketState.Crossed).ToList();

            // Assert
            Assert.IsEmpty(crossedPairs);
        }

        [Test]
        public void Test_GetByState_FiltersCorrectly()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.AAPL, _qqqSecurity.Symbol);

            // Create Crossed for SPY-AAPL: SPY bid > AAPL ask
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);
            // Create LimitOpportunity for AAPL-QQQ
            // Pattern 1: aapl_ask > qqq_ask > aapl_bid > qqq_bid
            SetSecurityPrices(_qqqSecurity, bid: 99.5m, ask: 100.5m);

            manager.UpdateAll();

            // Act
            var crossed = manager.GetByState(MarketState.Crossed).ToList();
            var limitOpp = manager.GetByState(MarketState.LimitOpportunity).ToList();

            // Assert
            Assert.AreEqual(1, crossed.Count);
            Assert.AreEqual(1, limitOpp.Count);
        }

        #endregion

        #region GetCrossedPairs Tests

        [Test]
        public void Test_GetCrossedPairs_ReturnsOnlyCrossedPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);

            // Create one crossed and one NoOpportunity
            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);  // SPY-AAPL: Crossed (101 > 100)
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 103m);  // SPY-QQQ: NoOpportunity (101 < 103)

            manager.UpdateAll();

            // Act
            var crossedPairs = manager.GetCrossedPairs().ToList();

            // Assert
            Assert.AreEqual(1, crossedPairs.Count);
            Assert.AreEqual(MarketState.Crossed, crossedPairs[0].MarketState);
        }

        [Test]
        public void Test_GetCrossedPairs_ReturnsEmptyIfNone()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Prices clearly not crossed: SPY bid (100) < AAPL ask (102)
            SetSecurityPrices(_spySecurity, bid: 100m, ask: 101m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 102m);

            manager.UpdateAll();

            // Act
            var crossedPairs = manager.GetCrossedPairs().ToList();

            // Assert
            Assert.IsEmpty(crossedPairs);
        }

        #endregion

        #region GetAll Tests

        [Test]
        public void Test_GetAll_ReturnsAllPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);
            manager.AddPair(Symbols.AAPL, _qqqSecurity.Symbol);

            // Act
            var allPairs = manager.GetAll().ToList();

            // Assert
            Assert.AreEqual(3, allPairs.Count);
        }

        [Test]
        public void Test_GetAll_ReturnsEmptyIfNone()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var allPairs = manager.GetAll().ToList();

            // Assert
            Assert.IsEmpty(allPairs);
        }

        #endregion

        #region Clear Tests

        [Test]
        public void Test_Clear_RemovesAllPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);
            Assert.AreEqual(2, manager.Count);

            // Act
            manager.Clear();

            // Assert
            Assert.AreEqual(0, manager.Count);
            Assert.IsEmpty(manager.GetAll());
        }

        [Test]
        public void Test_Clear_SetsCountToZero()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);

            // Act
            manager.Clear();

            // Assert
            Assert.AreEqual(0, manager.Count);
        }

        #endregion

        #region IEnumerable Tests

        [Test]
        public void Test_Enumeration_IteratesAllPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);

            // Act
            var count = 0;
            foreach (var pair in manager)
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
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            manager.AddPair(Symbols.SPY, Symbols.AAPL);
            manager.AddPair(Symbols.SPY, _qqqSecurity.Symbol);
            manager.AddPair(Symbols.AAPL, _qqqSecurity.Symbol);

            SetSecurityPrices(_spySecurity, bid: 101m, ask: 102m);
            SetSecurityPrices(_aaplSecurity, bid: 99m, ask: 100m);
            SetSecurityPrices(_qqqSecurity, bid: 100m, ask: 101m);

            manager.UpdateAll();

            // Act
            var spyPairs = manager.Where(p => p.Leg1Symbol == Symbols.SPY).ToList();

            // Assert
            Assert.AreEqual(2, spyPairs.Count);
            Assert.IsTrue(spyPairs.All(p => p.Leg1Symbol == Symbols.SPY));
        }

        #endregion
    }
}
