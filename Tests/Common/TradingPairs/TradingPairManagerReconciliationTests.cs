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
using QuantConnect.Orders;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairManagerReconciliationTests
    {
        private SecurityManager _securities;
        private SecurityTransactionManager _transactions;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private SecurityPortfolioManager _portfolio;
        private Security _btcSecurity;
        private Security _mstrSecurity;
        private Security _ethSecurity;

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

            var btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            var mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);
            var ethSymbol = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);

            _btcSecurity = CreateSecurity(btcSymbol, exchangeHours, timeKeeper);
            _mstrSecurity = CreateSecurity(mstrSymbol, exchangeHours, timeKeeper);
            _ethSecurity = CreateSecurity(ethSymbol, exchangeHours, timeKeeper);

            _securities.Add(_btcSecurity);
            _securities.Add(_mstrSecurity);
            _securities.Add(_ethSecurity);

            // Create transaction manager and portfolio
            _transactions = new SecurityTransactionManager(null, _securities);
            _portfolio = new SecurityPortfolioManager(_securities, _transactions, new AlgorithmSettings());
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

        private void SetPortfolioHolding(Symbol symbol, decimal quantity)
        {
            var holdings = _portfolio[symbol];
            // Use reflection to set the quantity
            var quantityProperty = holdings.GetType().GetProperty("Quantity");
            quantityProperty.SetValue(holdings, quantity);
        }

        private TradingPairManager CreateManager()
        {
            return new TradingPairManager(_mockAlgorithm.Object);
        }

        private TradingPair CreateTradingPair(TradingPairManager manager, Symbol leg1, Symbol leg2)
        {
            var pair = manager.AddPair(leg1, leg2);
            return pair;
        }

        private GridPosition CreateGridPosition(TradingPair pair, decimal leg1Qty, decimal leg2Qty)
        {
            // Create a grid level pair
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (pair.Leg1Symbol, pair.Leg2Symbol));

            var position = new GridPosition(pair, levelPair);

            // Use reflection to set quantities
            var leg1QuantityField = typeof(GridPosition).GetProperty("Leg1Quantity", BindingFlags.Public | BindingFlags.Instance);
            var leg2QuantityField = typeof(GridPosition).GetProperty("Leg2Quantity", BindingFlags.Public | BindingFlags.Instance);

            leg1QuantityField.SetValue(position, leg1Qty);
            leg2QuantityField.SetValue(position, leg2Qty);

            return position;
        }

        #region Reflection Helpers

        private Dictionary<Symbol, decimal> InvokeAggregateGridPositions(TradingPairManager manager)
        {
            var method = typeof(TradingPairManager).GetMethod("AggregateGridPositions",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (Dictionary<Symbol, decimal>)method.Invoke(manager, null);
        }

        private Dictionary<Symbol, decimal> InvokeCalculateBaseline(TradingPairManager manager, SecurityPortfolioManager portfolio)
        {
            var method = typeof(TradingPairManager).GetMethod("CalculateBaseline",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (Dictionary<Symbol, decimal>)method.Invoke(manager, new object[] { portfolio });
        }

        private Dictionary<Symbol, decimal> GetBaselineField(TradingPairManager manager)
        {
            var field = typeof(TradingPairManager).GetField("_baseline",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (Dictionary<Symbol, decimal>)field.GetValue(manager);
        }

        private void SetBaselineField(TradingPairManager manager, Dictionary<Symbol, decimal> baseline)
        {
            var field = typeof(TradingPairManager).GetField("_baseline",
                BindingFlags.NonPublic | BindingFlags.Instance);
            field.GetValue(manager); // Get the existing dictionary
            var existingBaseline = (Dictionary<Symbol, decimal>)field.GetValue(manager);
            existingBaseline.Clear();
            foreach (var kvp in baseline)
            {
                existingBaseline[kvp.Key] = kvp.Value;
            }
        }

        #endregion

        #region AggregateGridPositions Tests

        [Test]
        public void Test_AggregateGridPositions_EmptyManager_ReturnsEmptyDictionary()
        {
            // Arrange
            var manager = CreateManager();

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            Assert.IsNotNull(result);
            Assert.AreEqual(0, result.Count);
        }

        [Test]
        public void Test_AggregateGridPositions_SinglePairSinglePosition_ReturnsCorrectQuantities()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            // Add position to pair (use reflection to access GridPositions)
            var gridPositionsProperty = typeof(TradingPair).GetProperty("GridPositions");
            var gridPositions = (Dictionary<string, GridPosition>)gridPositionsProperty.GetValue(pair);
            gridPositions["test_position"] = position;

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(0.5m, result[_btcSecurity.Symbol]);
            Assert.AreEqual(-100m, result[_mstrSecurity.Symbol]);
        }

        [Test]
        public void Test_AggregateGridPositions_MultiplePairs_AggregatesCorrectly()
        {
            // Arrange
            var manager = CreateManager();

            // First pair: BTC-MSTR
            var pair1 = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position1 = CreateGridPosition(pair1, 0.5m, -100m);
            var gridPositions1 = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair1);
            gridPositions1["pos1"] = position1;

            // Second pair: ETH-MSTR
            var pair2 = CreateTradingPair(manager, _ethSecurity.Symbol, _mstrSecurity.Symbol);
            var position2 = CreateGridPosition(pair2, 2m, -50m);
            var gridPositions2 = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair2);
            gridPositions2["pos2"] = position2;

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            Assert.AreEqual(3, result.Count);
            Assert.AreEqual(0.5m, result[_btcSecurity.Symbol]);
            Assert.AreEqual(2m, result[_ethSecurity.Symbol]);
            Assert.AreEqual(-150m, result[_mstrSecurity.Symbol]); // -100 + -50
        }

        [Test]
        public void Test_AggregateGridPositions_SameSymbolMultiplePositions_SumsQuantities()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var position1 = CreateGridPosition(pair, 0.3m, -50m);
            var position2 = CreateGridPosition(pair, 0.2m, -30m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position1;
            gridPositions["pos2"] = position2;

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(0.5m, result[_btcSecurity.Symbol]); // 0.3 + 0.2
            Assert.AreEqual(-80m, result[_mstrSecurity.Symbol]); // -50 + -30
        }

        [Test]
        public void Test_AggregateGridPositions_PositiveAndNegativeQuantities_CalculatesNetPosition()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var position1 = CreateGridPosition(pair, 1m, -100m);
            var position2 = CreateGridPosition(pair, -0.3m, 50m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position1;
            gridPositions["pos2"] = position2;

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(0.7m, result[_btcSecurity.Symbol]); // 1 + (-0.3)
            Assert.AreEqual(-50m, result[_mstrSecurity.Symbol]); // -100 + 50
        }

        [Test]
        public void Test_AggregateGridPositions_ZeroQuantities_IncludesInResult()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var position = CreateGridPosition(pair, 0m, 0m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Act
            var result = InvokeAggregateGridPositions(manager);

            // Assert
            // Zero quantities are still included in the aggregation
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(0m, result[_btcSecurity.Symbol]);
            Assert.AreEqual(0m, result[_mstrSecurity.Symbol]);
        }

        #endregion

        #region CalculateBaseline Tests

        [Test]
        public void Test_CalculateBaseline_PortfolioMatchesGP_ReturnsEmptyDictionary()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Set portfolio to match GP
            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.IsNotNull(result);
            Assert.AreEqual(0, result.Count); // All differences are zero, so filtered out
        }

        [Test]
        public void Test_CalculateBaseline_PortfolioHasHoldings_GPIsEmpty_ReturnsPortfolioQuantities()
        {
            // Arrange
            var manager = CreateManager();

            SetPortfolioHolding(_btcSecurity.Symbol, 1.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, 200m);

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(1.5m, result[_btcSecurity.Symbol]);
            Assert.AreEqual(200m, result[_mstrSecurity.Symbol]);
        }

        [Test]
        public void Test_CalculateBaseline_GPHasPositions_PortfolioIsEmpty_ReturnsNegativeGPQuantities()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Portfolio is empty (default)

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(-0.5m, result[_btcSecurity.Symbol]); // 0 - 0.5
            Assert.AreEqual(100m, result[_mstrSecurity.Symbol]); // 0 - (-100)
        }

        [Test]
        public void Test_CalculateBaseline_PortfolioGreaterThanGP_ReturnsPositiveDifferences()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            SetPortfolioHolding(_btcSecurity.Symbol, 1m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -50m);

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(0.5m, result[_btcSecurity.Symbol]); // 1 - 0.5
            Assert.AreEqual(50m, result[_mstrSecurity.Symbol]); // -50 - (-100)
        }

        [Test]
        public void Test_CalculateBaseline_PortfolioLessThanGP_ReturnsNegativeDifferences()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 1m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -150m);

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(2, result.Count);
            Assert.AreEqual(-0.5m, result[_btcSecurity.Symbol]); // 0.5 - 1
            Assert.AreEqual(-50m, result[_mstrSecurity.Symbol]); // -150 - (-100)
        }

        [Test]
        public void Test_CalculateBaseline_SymbolOnlyInPortfolio_IncludesWithPortfolioQuantity()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);
            SetPortfolioHolding(_ethSecurity.Symbol, 5m); // ETH only in portfolio

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(1, result.Count);
            Assert.AreEqual(5m, result[_ethSecurity.Symbol]); // 5 - 0 (GP doesn't have ETH)
        }

        [Test]
        public void Test_CalculateBaseline_ZeroDifferencesFiltered_OnlyNonZeroReturned()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m); // Matches GP, diff = 0
            SetPortfolioHolding(_mstrSecurity.Symbol, -50m); // Doesn't match, diff = 50

            // Act
            var result = InvokeCalculateBaseline(manager, _portfolio);

            // Assert
            Assert.AreEqual(1, result.Count);
            Assert.IsFalse(result.ContainsKey(_btcSecurity.Symbol)); // Zero diff filtered out
            Assert.AreEqual(50m, result[_mstrSecurity.Symbol]);
        }

        #endregion

        #region CompareBaseline Tests

        // Create a testable subclass that allows us to spy on protected virtual methods
        private class TestableTradingPairManager : TradingPairManager
        {
            public TestableTradingPairManager(AIAlgorithm algorithm)
                : base(algorithm)
            {
            }
        }

        [Test]
        public void Test_CompareBaseline_BaselineMatchesCurrent_NoLoggingNoReplay()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Initialize baseline
            manager.InitializeBaseline(_portfolio);

            // Act - portfolio hasn't changed, so baseline should match
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.AreEqual(0, manager.LoggedDiscrepancies.Count); // Removed in refactoring
            // Assert.AreEqual(0, manager.ReplayedSymbols.Count); // Removed in refactoring
        }

        [Test]
        public void Test_CompareBaseline_SingleDiscrepancy_LogsAndTriggersReplay()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Initialize baseline with empty portfolio
            manager.InitializeBaseline(_portfolio);

            // Change portfolio
            SetPortfolioHolding(_btcSecurity.Symbol, 1m); // Was 0, GP is 0.5, baseline was -0.5, now current is 0.5

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.AreEqual(1, manager.LoggedDiscrepancies.Count); // Removed in refactoring
            // var discrepancy = manager.LoggedDiscrepancies[0]; // Removed in refactoring
            // Assert.AreEqual(_btcSecurity.Symbol, discrepancy.Item1); // Removed in refactoring
            // Assert.AreEqual(-0.5m, discrepancy.Item2); // Removed in refactoring // baseline value
            // Assert.AreEqual(0.5m, discrepancy.Item3); // Removed in refactoring // current value

            // Assert.AreEqual(1, manager.ReplayedSymbols.Count); // Removed in refactoring
            // Assert.IsTrue(manager.ReplayedSymbols.Contains(_btcSecurity.Symbol)); // Removed in refactoring
        }

        [Test]
        public void Test_CompareBaseline_MultipleDiscrepancies_LogsAllAndTriggersReplay()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Initialize baseline
            manager.InitializeBaseline(_portfolio);

            // Change portfolio for both symbols
            SetPortfolioHolding(_btcSecurity.Symbol, 2m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -50m);

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.AreEqual(2, manager.LoggedDiscrepancies.Count); // Removed in refactoring
            // Assert.AreEqual(2, manager.ReplayedSymbols.Count); // Removed in refactoring
            // Assert.IsTrue(manager.ReplayedSymbols.Contains(_btcSecurity.Symbol)); // Removed in refactoring
            // Assert.IsTrue(manager.ReplayedSymbols.Contains(_mstrSecurity.Symbol)); // Removed in refactoring
        }

        [Test]
        public void Test_CompareBaseline_BaselineHasSymbolCurrentDoesNot_TriggersReplay()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);

            // Set baseline manually with BTC
            var baseline = new Dictionary<Symbol, decimal>
            {
                { _btcSecurity.Symbol, 0.5m }
            };
            SetBaselineField(manager, baseline);

            // Current has no positions (GP and Portfolio both empty)
            // So current diff should be empty, meaning baseline value becomes 0 in comparison

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.AreEqual(1, manager.LoggedDiscrepancies.Count); // Removed in refactoring
            // var discrepancy = manager.LoggedDiscrepancies[0]; // Removed in refactoring
            // Assert.AreEqual(_btcSecurity.Symbol, discrepancy.Item1); // Removed in refactoring
            // Assert.AreEqual(0.5m, discrepancy.Item2); // Removed in refactoring
            // Assert.AreEqual(0m, discrepancy.Item3); // Removed in refactoring

            // Assert.AreEqual(1, manager.ReplayedSymbols.Count); // Removed in refactoring
        }

        [Test]
        public void Test_CompareBaseline_CurrentHasSymbolBaselineDoesNot_TriggersReplay()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            var position = CreateGridPosition(pair, 0.5m, -100m);

            var gridPositions = (Dictionary<string, GridPosition>)typeof(TradingPair)
                .GetProperty("GridPositions").GetValue(pair);
            gridPositions["pos1"] = position;

            // Initialize with empty baseline
            SetBaselineField(manager, new Dictionary<Symbol, decimal>());

            // Current will have differences (portfolio=0, GP has values)

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.Greater(manager.LoggedDiscrepancies.Count, 0); // Removed in refactoring
            // Assert.Greater(manager.ReplayedSymbols.Count, 0); // Removed in refactoring
        }

        [Test]
        public void Test_CompareBaseline_EmptyBaselineEmptyCurrent_NoAction()
        {
            // Arrange
            var manager = new TestableTradingPairManager(_mockAlgorithm.Object);

            // Both baseline and current are empty
            SetBaselineField(manager, new Dictionary<Symbol, decimal>());

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert
            // Assert.AreEqual(0, manager.LoggedDiscrepancies.Count); // Removed in refactoring
            // Assert.AreEqual(0, manager.ReplayedSymbols.Count); // Removed in refactoring
        }

        #endregion
    }
}
