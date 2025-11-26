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
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Moq;
using NUnit.Framework;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairManagerPendingRemovalTests
    {
        private SecurityManager _securities;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private SecurityTransactionManager _transactions;
        private Security _btcSecurity;
        private Security _mstrSecurity;
        private Security _ethSecurity;

        [SetUp]
        public void Setup()
        {
            // Setup pattern from TradingPairManagerTests.cs
            _securities = new SecurityManager(new TimeKeeper(DateTime.UtcNow, TimeZones.NewYork));
            _mockAlgorithm = new Mock<AIAlgorithm>();
            _transactions = new SecurityTransactionManager(_mockAlgorithm.Object, _securities);

            _mockAlgorithm.Setup(a => a.Securities).Returns(_securities);
            _mockAlgorithm.Setup(a => a.Transactions).Returns(_transactions);

            // Setup in-memory ObjectStore for state persistence
            var objectStoreData = new Dictionary<string, string>();
            var inMemoryObjectStore = new InMemoryObjectStore(objectStoreData);
            var objectStoreWrapper = new QuantConnect.Storage.ObjectStore(inMemoryObjectStore);
            _mockAlgorithm.Setup(a => a.ObjectStore).Returns(objectStoreWrapper);

            // Create test securities
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var dateTime = new DateTime(2024, 1, 1, 9, 30, 0);
            var timeKeeper = new LocalTimeKeeper(
                dateTime.ConvertToUtc(TimeZones.NewYork), TimeZones.NewYork);

            _btcSecurity = CreateSecurity(
                Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase),
                exchangeHours, timeKeeper);
            _mstrSecurity = CreateSecurity(
                Symbol.Create("MSTR", SecurityType.Equity, Market.USA),
                exchangeHours, timeKeeper);
            _ethSecurity = CreateSecurity(
                Symbol.Create("ETHUSDT", SecurityType.Crypto, Market.Gate),
                exchangeHours, timeKeeper);

            _securities.Add(_btcSecurity);
            _securities.Add(_mstrSecurity);
            _securities.Add(_ethSecurity);
        }

        private Security CreateSecurity(Symbol symbol, SecurityExchangeHours exchangeHours,
                                       LocalTimeKeeper timeKeeper)
        {
            // Standard security creation pattern
            var config = new SubscriptionDataConfig(
                typeof(TradeBar), symbol, Resolution.Minute,
                TimeZones.NewYork, TimeZones.NewYork, true, true, false);

            Security security;

            // Create Crypto security for crypto symbols (implements IBaseCurrencySymbol)
            if (symbol.SecurityType == SecurityType.Crypto)
            {
                var quoteCurrency = new Cash(Currencies.USD, 0, 1m);
                var ticker = symbol.Value;
                var baseCurrencySymbol = ticker.Replace("USD", "").Replace("USDT", "");
                var baseCurrency = new Cash(baseCurrencySymbol, 0, 1m);

                security = new QuantConnect.Securities.Crypto.Crypto(
                    exchangeHours,
                    quoteCurrency,
                    baseCurrency,
                    config,
                    SymbolProperties.GetDefault(Currencies.USD),
                    ErrorCurrencyConverter.Instance,
                    RegisteredSecurityDataTypesProvider.Null
                );
            }
            else
            {
                security = new Security(
                    exchangeHours, config,
                    new Cash(Currencies.USD, 0, 1m),
                    SymbolProperties.GetDefault(Currencies.USD),
                    ErrorCurrencyConverter.Instance,
                    RegisteredSecurityDataTypesProvider.Null,
                    new SecurityCache());
            }

            security.SetLocalTimeKeeper(timeKeeper);
            return security;
        }

        #region Category 1: RemovePair Pending Removal Logic

        [Test]
        public void Test_RemovePair_PendingRemoval_StillCountedInManager()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            AddActivePosition(pair, 1.0m, -100m);

            // Act
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Assert
            Assert.AreEqual(1, manager.Count);
            Assert.IsTrue(pair.IsPendingRemoval);
        }

        [Test]
        public void Test_RemovePair_AlreadyPendingRemoval_RemainsUnchanged()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            AddActivePosition(pair, 1.0m, -100m);
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act - Remove again
            var result = manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Assert
            Assert.IsTrue(result);
            Assert.IsTrue(pair.IsPendingRemoval);
            Assert.AreEqual(1, manager.Count);
        }

        #endregion

        #region Category 2: AddPair Clearing Pending Removal

        [Test]
        public void Test_AddPair_ClearsPendingRemovalFlag()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            AddActivePosition(pair, 1.0m, -100m);
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            Assert.IsTrue(pair.IsPendingRemoval);

            // Act - Re-add the pair
            var readdedPair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Assert
            Assert.AreSame(pair, readdedPair); // Same instance
            Assert.IsFalse(pair.IsPendingRemoval);
            Assert.IsTrue(pair.HasActivePositions); // Positions still exist
        }

        [Test]
        public void Test_AddPair_AfterPendingRemoval_AllowsNewEntries()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            AddActivePosition(pair, 1.0m, -100m);
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act
            manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Assert - Should be able to add new positions
            Assert.IsFalse(pair.IsPendingRemoval);
            var levelPair2 = new GridLevelPair(0.03m, -0.015m, "SHORT_SPREAD", 0.25m,
                                               (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Should not throw
            Assert.DoesNotThrow(() => pair.GetOrCreatePosition(levelPair2));
        }

        #endregion

        #region Category 3: Utility Methods

        [Test]
        public void Test_GetPendingRemovalPairs_ReturnsPendingPairs()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair1 = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            AddActivePosition(pair1, 1.0m, -100m);
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act
            var pendingPairs = manager.GetPendingRemovalPairs();

            // Assert
            Assert.AreEqual(1, pendingPairs.Count());
            Assert.Contains(pair1, pendingPairs.ToList());
        }

        [Test]
        public void Test_PendingRemovalCount_ReturnsCorrectCount()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair1 = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            var pair2 = manager.AddPair(_ethSecurity.Symbol, _mstrSecurity.Symbol);

            AddActivePosition(pair1, 1.0m, -100m);
            AddActivePosition(pair2, 50m, -50m);

            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.RemovePair(_ethSecurity.Symbol, _mstrSecurity.Symbol);

            // Act & Assert
            Assert.AreEqual(2, manager.PendingRemovalCount);
        }

        [Test]
        public void Test_IsPendingRemoval_Method_ReturnsCorrectStatus()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act & Assert - Not pending initially
            Assert.IsFalse(manager.IsPendingRemoval(_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Mark pending
            AddActivePosition(pair, 1.0m, -100m);
            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act & Assert - Now pending
            Assert.IsTrue(manager.IsPendingRemoval(_btcSecurity.Symbol, _mstrSecurity.Symbol));
        }

        #endregion

        #region Category 4: CompletePendingRemoval on Position Close

        [Test]
        public void Test_ProcessGridOrderEvent_CompletesRemovalWhenPositionsClosed()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", 1.0m);
            SetPositionQuantity(position, "Leg2Quantity", -100m);

            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);
            pair.GridPositions[tag] = position;

            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            Assert.IsTrue(pair.IsPendingRemoval);

            // Act - Process order events to close position
            var closeOrder1 = CreateCloseOrderEvent(_btcSecurity.Symbol, -1.0m, tag);
            var closeOrder2 = CreateCloseOrderEvent(_mstrSecurity.Symbol, 100m, tag);

            manager.ProcessGridOrderEvent(closeOrder1);
            manager.ProcessGridOrderEvent(closeOrder2);

            // Assert - Pair should be removed
            Assert.AreEqual(0, manager.Count);
            Assert.IsFalse(manager.IsPendingRemoval(_btcSecurity.Symbol, _mstrSecurity.Symbol));
        }

        [Test]
        public void Test_MultiplePositions_OnlyCompletesWhenAllClosed()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Add two positions
            var levelPair1 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                               (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var levelPair2 = new GridLevelPair(-0.03m, 0.015m, "LONG_SPREAD", 0.25m,
                                               (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            var position1 = CreatePositionWithQuantity(pair, levelPair1, 1.0m, -100m);
            var position2 = CreatePositionWithQuantity(pair, levelPair2, 0.5m, -50m);

            var tag1 = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair1);
            var tag2 = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair2);

            pair.GridPositions[tag1] = position1;
            pair.GridPositions[tag2] = position2;

            manager.RemovePair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act - Close first position only
            var close1_1 = CreateCloseOrderEvent(_btcSecurity.Symbol, -1.0m, tag1);
            var close1_2 = CreateCloseOrderEvent(_mstrSecurity.Symbol, 100m, tag1);
            manager.ProcessGridOrderEvent(close1_1);
            manager.ProcessGridOrderEvent(close1_2);

            // Assert - Still exists because position2 is still open
            Assert.AreEqual(1, manager.Count);
            Assert.IsTrue(pair.IsPendingRemoval);

            // Act - Close second position
            var close2_1 = CreateCloseOrderEvent(_btcSecurity.Symbol, -0.5m, tag2);
            var close2_2 = CreateCloseOrderEvent(_mstrSecurity.Symbol, 50m, tag2);
            manager.ProcessGridOrderEvent(close2_1);
            manager.ProcessGridOrderEvent(close2_2);

            // Assert - Now removed
            Assert.AreEqual(0, manager.Count);
        }

        #endregion

        #region Helper Methods

        private void AddActivePosition(TradingPair pair, decimal leg1Qty, decimal leg2Qty)
        {
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m,
                                              (pair.Leg1Symbol, pair.Leg2Symbol));
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", leg1Qty);
            SetPositionQuantity(position, "Leg2Quantity", leg2Qty);

            var tag = TradingPairManager.EncodeGridTag(pair.Leg1Symbol, pair.Leg2Symbol, levelPair);
            pair.GridPositions[tag] = position;
        }

        private GridPosition CreatePositionWithQuantity(TradingPair pair, GridLevelPair levelPair,
                                                        decimal leg1Qty, decimal leg2Qty)
        {
            var position = new GridPosition(pair, levelPair);
            SetPositionQuantity(position, "Leg1Quantity", leg1Qty);
            SetPositionQuantity(position, "Leg2Quantity", leg2Qty);
            return position;
        }

        private void SetPositionQuantity(GridPosition position, string propertyName, decimal value)
        {
            var field = typeof(GridPosition).GetField($"<{propertyName}>k__BackingField",
                BindingFlags.NonPublic | BindingFlags.Instance);
            field.SetValue(position, value);
        }

        private OrderEvent CreateCloseOrderEvent(Symbol symbol, decimal quantity, string tag)
        {
            var request = new SubmitOrderRequest(
                OrderType.Market, symbol.SecurityType, symbol,
                quantity, 0, 0, DateTime.UtcNow, tag);

            var ticket = new OrderTicket(null, request);

            return new OrderEvent(
                1, symbol, DateTime.UtcNow, OrderStatus.Filled,
                quantity > 0 ? OrderDirection.Buy : OrderDirection.Sell,
                100m, quantity,
                new OrderFee(new CashAmount(0, Currencies.USD)), "Test fill")
            {
                Ticket = ticket
            };
        }

        #endregion
    }
}
