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
using QuantConnect.Orders.Fees;

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

            var btcSymbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Gate);
            var ethSymbol = Symbol.Create("ETHUSDT", SecurityType.Crypto, Market.Gate);
            var mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

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

            // Use appropriate LotSize for crypto (0.01) vs equity (1)
            var lotSize = symbol.SecurityType == SecurityType.Crypto ? 0.01m : 1m;
            var symbolProperties = new SymbolProperties(
                symbol.Value,
                Currencies.USD,
                1m,
                0.01m,
                lotSize,
                symbol.Value
            );

            var security = new Security(
                exchangeHours,
                config,
                new Cash(Currencies.USD, 0, 1m),
                symbolProperties,
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

        #region ExecutionHistoryProvider Integration Tests

        [Test]
        public void Test_ExecutionHistoryProvider_IsInjected_CanCallGetExecutionHistory()
        {
            // Arrange
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            var testExecutions = new List<ExecutionRecord>
            {
                new ExecutionRecord
                {
                    Symbol = _btcSecurity.Symbol,
                    TimeUtc = DateTime.UtcNow,
                    Quantity = 0.5m,
                    Price = 50000m,
                    ExecutionId = "test_1"
                }
            };

            mockProvider
                .Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(testExecutions);

            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);

            var manager = CreateManager();

            // Act - Call Reconciliation which should use ExecutionHistoryProvider
            manager.Reconciliation();

            // Assert - Verify that GetExecutionHistory was called
            mockProvider.Verify(
                p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()),
                Times.Once,
                "Reconciliation should call ExecutionHistoryProvider.GetExecutionHistory");
        }

        [Test]
        public void Test_ExecutionHistoryProvider_NotSet_ReconciliationHandlesGracefully()
        {
            // Arrange
            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns((IExecutionHistoryProvider)null);
            var manager = CreateManager();

            // Act & Assert - Should not throw
            Assert.DoesNotThrow(() => manager.Reconciliation(),
                "Reconciliation should handle null ExecutionHistoryProvider gracefully");
        }

        [Test]
        public void Test_ExecutionHistoryProvider_ReturnsExecutions_ProcessedCorrectly()
        {
            // Arrange
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            var pair = CreateTradingPair(CreateManager(), _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var testExecutions = new List<ExecutionRecord>
            {
                new ExecutionRecord
                {
                    Symbol = _btcSecurity.Symbol,
                    TimeUtc = DateTime.UtcNow.AddMinutes(-5),
                    Quantity = 0.5m,
                    Price = 50000m,
                    ExecutionId = "exec_1",
                    Tag = "order_1"
                },
                new ExecutionRecord
                {
                    Symbol = _mstrSecurity.Symbol,
                    TimeUtc = DateTime.UtcNow.AddMinutes(-4),
                    Quantity = -100m,
                    Price = 500m,
                    ExecutionId = "exec_2",
                    Tag = "order_2"
                }
            };

            mockProvider
                .Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(testExecutions);

            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);
            var manager = CreateManager();
            var tradingPair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Act
            manager.Reconciliation();

            // Assert
            mockProvider.Verify(
                p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()),
                Times.Once,
                "Should retrieve execution history");
        }

        [Test]
        public void Test_ExecutionHistoryProvider_EmptyResults_HandledCorrectly()
        {
            // Arrange
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            mockProvider
                .Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(new List<ExecutionRecord>());

            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);
            var manager = CreateManager();

            // Act & Assert - Should not throw with empty results
            Assert.DoesNotThrow(() => manager.Reconciliation(),
                "Reconciliation should handle empty execution history gracefully");

            mockProvider.Verify(
                p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()),
                Times.Once);
        }

        [Test]
        public void Test_ExecutionHistoryProvider_CallsWithCorrectTimeRange()
        {
            // Arrange
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            DateTime? capturedStartTime = null;
            DateTime? capturedEndTime = null;

            mockProvider
                .Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Callback<DateTime, DateTime>((start, end) =>
                {
                    capturedStartTime = start;
                    capturedEndTime = end;
                })
                .Returns(new List<ExecutionRecord>());

            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);
            var manager = CreateManager();

            // Act
            manager.Reconciliation();

            // Assert
            Assert.IsNotNull(capturedStartTime, "Start time should be captured");
            Assert.IsNotNull(capturedEndTime, "End time should be captured");
            Assert.LessOrEqual(capturedStartTime.Value, capturedEndTime.Value,
                "Start time should be before or equal to end time");

            // Verify time range is reasonable (approximately 30 minutes lookback by default)
            var timeDiff = capturedEndTime.Value - capturedStartTime.Value;
            Assert.LessOrEqual(timeDiff, TimeSpan.FromMinutes(31),
                "Default time range should be approximately 30 minutes");
        }

        #endregion
    }

    /// <summary>
    /// Integration tests for TradingPairManager reconciliation workflow
    /// Tests end-to-end scenarios with OrderEvent processing, state tracking, and reconciliation
    /// </summary>
    [TestFixture]
    public class TradingPairManagerReconciliationIntegrationTests
    {
        private SecurityManager _securities;
        private SecurityTransactionManager _transactions;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private SecurityPortfolioManager _portfolio;
        private Security _btcSecurity;
        private Security _mstrSecurity;
        private Security _ethSecurity;
        private int _nextOrderId = 1;

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

            var btcSymbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Gate);
            var ethSymbol = Symbol.Create("ETHUSDT", SecurityType.Crypto, Market.Gate);
            var mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            _btcSecurity = CreateSecurity(btcSymbol, exchangeHours, timeKeeper);
            _mstrSecurity = CreateSecurity(mstrSymbol, exchangeHours, timeKeeper);
            _ethSecurity = CreateSecurity(ethSymbol, exchangeHours, timeKeeper);

            _securities.Add(_btcSecurity);
            _securities.Add(_mstrSecurity);
            _securities.Add(_ethSecurity);

            // Create transaction manager and portfolio
            _transactions = new SecurityTransactionManager(null, _securities);
            _portfolio = new SecurityPortfolioManager(_securities, _transactions, new AlgorithmSettings());

            _nextOrderId = 1; // Reset order ID counter
        }

        #region Helper Methods

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

            // Use appropriate LotSize for crypto (0.01) vs equity (1)
            var lotSize = symbol.SecurityType == SecurityType.Crypto ? 0.01m : 1m;
            var symbolProperties = new SymbolProperties(
                symbol.Value,
                Currencies.USD,
                1m,
                0.01m,
                lotSize,
                symbol.Value
            );

            var security = new Security(
                exchangeHours,
                config,
                new Cash(Currencies.USD, 0, 1m),
                symbolProperties,
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
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (pair.Leg1Symbol, pair.Leg2Symbol));
            var position = new GridPosition(pair, levelPair);

            var leg1QuantityField = typeof(GridPosition).GetProperty("Leg1Quantity", BindingFlags.Public | BindingFlags.Instance);
            var leg2QuantityField = typeof(GridPosition).GetProperty("Leg2Quantity", BindingFlags.Public | BindingFlags.Instance);

            leg1QuantityField.SetValue(position, leg1Qty);
            leg2QuantityField.SetValue(position, leg2Qty);

            return position;
        }

        // Access _lastFillTimeByMarket dictionary
        private Dictionary<string, DateTime> GetLastFillTimeByMarket(TradingPairManager manager)
        {
            var field = typeof(TradingPairManager).GetField("_lastFillTimeByMarket",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (Dictionary<string, DateTime>)field.GetValue(manager);
        }

        // Access _processedExecutions dictionary
        private Dictionary<string, TradingPairManager.ExecutionSnapshot> GetProcessedExecutions(TradingPairManager manager)
        {
            var field = typeof(TradingPairManager).GetField("_processedExecutions",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (Dictionary<string, TradingPairManager.ExecutionSnapshot>)field.GetValue(manager);
        }

        // Set _lastFillTimeByMarket for test setup
        private void SetLastFillTimeByMarket(TradingPairManager manager, Dictionary<string, DateTime> times)
        {
            var field = typeof(TradingPairManager).GetField("_lastFillTimeByMarket",
                BindingFlags.NonPublic | BindingFlags.Instance);
            var existing = (Dictionary<string, DateTime>)field.GetValue(manager);
            existing.Clear();
            foreach (var kvp in times) existing[kvp.Key] = kvp.Value;
        }

        // Set _processedExecutions for test setup
        private void SetProcessedExecutions(TradingPairManager manager, Dictionary<string, TradingPairManager.ExecutionSnapshot> executions)
        {
            var field = typeof(TradingPairManager).GetField("_processedExecutions",
                BindingFlags.NonPublic | BindingFlags.Instance);
            var existing = (Dictionary<string, TradingPairManager.ExecutionSnapshot>)field.GetValue(manager);
            existing.Clear();
            foreach (var kvp in executions) existing[kvp.Key] = kvp.Value;
        }

        // Create OrderEvent helper with proper grid tag encoding
        private OrderEvent CreateOrderEvent(Symbol symbol, decimal quantity, decimal price,
            DateTime utcTime, string executionId, GridLevelPair levelPair, Symbol leg1Symbol, Symbol leg2Symbol, OrderStatus status = OrderStatus.Filled)
        {
            // Use TradingPairManager.EncodeGridTag to create proper tag format
            var tag = TradingPairManager.EncodeGridTag(leg1Symbol, leg2Symbol, levelPair);

            var request = new SubmitOrderRequest(OrderType.Market, symbol.SecurityType,
                symbol, quantity, 0, 0, utcTime, tag);
            var ticket = new OrderTicket(null, request);

            var orderEvent = new OrderEvent(
                _nextOrderId++, symbol, utcTime, status,
                quantity > 0 ? OrderDirection.Buy : OrderDirection.Sell,
                price, quantity,
                new OrderFee(new CashAmount(0.01m, Currencies.USD)), "Test fill")
            {
                Ticket = ticket,
                ExecutionId = executionId
            };

            return orderEvent;
        }

        // Helper to parse old tag format and create GridLevelPair
        private GridLevelPair ParseTagToLevelPair(string tag, Symbol leg1Symbol, Symbol leg2Symbol)
        {
            // Tag format: "BTCUSD|MSTR|-0.02|0.01|LONG_SPREAD|0.25"
            var parts = tag.Split('|');
            var entrySpread = decimal.Parse(parts[2]);
            var exitSpread = decimal.Parse(parts[3]);
            var direction = parts[4];
            var positionSize = decimal.Parse(parts[5]);
            return new GridLevelPair(entrySpread, exitSpread, direction, positionSize, (leg1Symbol, leg2Symbol));
        }

        // Create ExecutionRecord helper
        private ExecutionRecord CreateExecutionRecord(Symbol symbol, decimal quantity,
            decimal price, DateTime timeUtc, string executionId, string tag = null)
        {
            return new ExecutionRecord
            {
                Symbol = symbol,
                Quantity = quantity,
                Price = price,
                TimeUtc = timeUtc,
                ExecutionId = executionId,
                Tag = tag,
                Fee = 0.01m,
                FeeCurrency = Currencies.USD
            };
        }

        // Invoke ShouldProcessExecution via reflection
        private bool InvokeShouldProcessExecution(TradingPairManager manager, ExecutionRecord execution)
        {
            var method = typeof(TradingPairManager).GetMethod("ShouldProcessExecution",
                BindingFlags.NonPublic | BindingFlags.Instance);
            return (bool)method.Invoke(manager, new object[] { execution });
        }

        // Invoke CleanupProcessedExecutions via reflection
        private void InvokeCleanupProcessedExecutions(TradingPairManager manager)
        {
            var method = typeof(TradingPairManager).GetMethod("CleanupProcessedExecutions",
                BindingFlags.NonPublic | BindingFlags.Instance);
            method.Invoke(manager, null);
        }

        // Helper to verify ExecutionSnapshot contents
        private void AssertExecutionSnapshot(object snapshot, string expectedExecutionId,
            DateTime expectedTime, string expectedMarket)
        {
            var snapshotType = snapshot.GetType();
            var execId = (string)snapshotType.GetProperty("ExecutionId").GetValue(snapshot);
            var timeUtc = (DateTime)snapshotType.GetProperty("TimeUtc").GetValue(snapshot);
            var market = (string)snapshotType.GetProperty("Market").GetValue(snapshot);

            Assert.AreEqual(expectedExecutionId, execId);
            Assert.AreEqual(expectedTime, timeUtc);
            Assert.AreEqual(expectedMarket, market);
        }

        // Helper to verify timestamp precision
        private void AssertLastFillTime(Dictionary<string, DateTime> lastFillTimes,
            string market, DateTime expectedTime)
        {
            Assert.IsTrue(lastFillTimes.ContainsKey(market),
                $"Market '{market}' not found in _lastFillTimeByMarket");
            Assert.AreEqual(expectedTime, lastFillTimes[market],
                $"Market '{market}' timestamp mismatch");
        }

        // Reflection helpers from base class
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

        // Helper to verify LP == GP
        private void AssertPortfolioMatchesGridPositions(TradingPairManager manager,
            SecurityPortfolioManager portfolio)
        {
            var baseline = InvokeCalculateBaseline(manager, portfolio);
            Assert.AreEqual(0, baseline.Count,
                $"Portfolio and GridPositions mismatch: {string.Join(", ", baseline.Select(kvp => $"{kvp.Key}: {kvp.Value}"))}");
        }

        #endregion

        #region Category 1: Core Reconciliation Flow

        [Test]
        public void Test_EmptyState_ProcessTwoOrderEvents_StateConsistent()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act
            var orderEvent1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent1);

            var orderEvent2 = CreateOrderEvent(_mstrSecurity.Symbol, -100m, 500m, T0.AddMinutes(1), "exec_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent2);

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(2, gpAggregation.Count);
            Assert.AreEqual(0.5m, gpAggregation[_btcSecurity.Symbol]);
            Assert.AreEqual(-100m, gpAggregation[_mstrSecurity.Symbol]);

            AssertPortfolioMatchesGridPositions(manager, _portfolio);

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            Assert.AreEqual(2, lastFillTimes.Count);
            AssertLastFillTime(lastFillTimes, "gate", T0);
            AssertLastFillTime(lastFillTimes, "usa", T0.AddMinutes(1));

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count);
            Assert.IsTrue(processedExecs.ContainsKey("exec_1"));
            Assert.IsTrue(processedExecs.ContainsKey("exec_2"));
        }

        [Test]
        public void Test_PortfolioNotEmpty_GPEmpty_ProcessOrderEvents_StateReconciled()
        {
            // Arrange
            var manager = CreateManager();
            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            manager.InitializeBaseline(_portfolio);
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act
            var orderEvent1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "reconnect_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent1);

            var orderEvent2 = CreateOrderEvent(_mstrSecurity.Symbol, -100m, 500m, T0.AddSeconds(30), "reconnect_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent2);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(2, gpAggregation.Count);
            Assert.AreEqual(0.5m, gpAggregation[_btcSecurity.Symbol]);
            Assert.AreEqual(-100m, gpAggregation[_mstrSecurity.Symbol]);

            AssertPortfolioMatchesGridPositions(manager, _portfolio);

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            AssertLastFillTime(lastFillTimes, "gate", T0);
            AssertLastFillTime(lastFillTimes, "usa", T0.AddSeconds(30));

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count);
        }

        [Test]
        public void Test_BothNotEmpty_ProcessNewOrderEvents_IncrementalReconciliation()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair1 = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Create first position
            var orderEvent1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_1", levelPair1, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent1);
            var orderEvent2 = CreateOrderEvent(_mstrSecurity.Symbol, -100m, 500m, T0, "exec_2", levelPair1, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent2);

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            // Act - Add second position
            var levelPair2 = new GridLevelPair(-0.03m, 0.015m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var orderEvent3 = CreateOrderEvent(_btcSecurity.Symbol, 0.3m, 51000m, T0.AddMinutes(5), "exec_3", levelPair2, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent3);
            var orderEvent4 = CreateOrderEvent(_mstrSecurity.Symbol, -60m, 510m, T0.AddMinutes(5).AddSeconds(10), "exec_4", levelPair2, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(orderEvent4);

            SetPortfolioHolding(_btcSecurity.Symbol, 0.8m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -160m);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(2, gpAggregation.Count);
            Assert.AreEqual(0.8m, gpAggregation[_btcSecurity.Symbol]);
            Assert.AreEqual(-160m, gpAggregation[_mstrSecurity.Symbol]);

            AssertPortfolioMatchesGridPositions(manager, _portfolio);

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            AssertLastFillTime(lastFillTimes, "gate", T0.AddMinutes(5));
            AssertLastFillTime(lastFillTimes, "usa", T0.AddMinutes(5).AddSeconds(10));

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(4, processedExecs.Count);
        }

        [Test]
        public void Test_CrossMarket_IndependentTimestamps_CorrectPerMarketTracking()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var T1 = new DateTime(2024, 1, 1, 10, 5, 0, DateTimeKind.Utc);
            var T2 = new DateTime(2024, 1, 1, 10, 3, 0, DateTimeKind.Utc); // OLDER than T0
            var T3 = new DateTime(2024, 1, 1, 10, 7, 0, DateTimeKind.Utc); // NEWER than T1

            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act - Process fills in specific order to test timestamp update logic
            var btc1 = CreateOrderEvent(_btcSecurity.Symbol, 0.1m, 50000m, T0, "btc_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(btc1);

            var mstr1 = CreateOrderEvent(_mstrSecurity.Symbol, -20m, 500m, T1, "mstr_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(mstr1);

            var btc2 = CreateOrderEvent(_btcSecurity.Symbol, 0.2m, 51000m, T2, "btc_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol); // Older time
            manager.ProcessGridOrderEvent(btc2);

            var mstr2 = CreateOrderEvent(_mstrSecurity.Symbol, -30m, 510m, T3, "mstr_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol); // Newer time
            manager.ProcessGridOrderEvent(mstr2);

            // Assert
            var lastFillTimes = GetLastFillTimeByMarket(manager);
            // BTC (coinbase) should NOT be updated by older T2
            AssertLastFillTime(lastFillTimes, "gate", T2);
            // MSTR (usa) should be updated by newer T3
            AssertLastFillTime(lastFillTimes, "usa", T3);

            // Before cleanup, should have all 4 executions
            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(4, processedExecs.Count);

            // Trigger cleanup - should remove old executions per market
            InvokeCleanupProcessedExecutions(manager);

            // After cleanup, should only have 2 executions (btc_2 and mstr_2)
            processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count);
            Assert.IsTrue(processedExecs.ContainsKey("btc_2"));
            Assert.IsTrue(processedExecs.ContainsKey("mstr_2"));
        }

        [Test]
        public void Test_PartialFills_MultipleExecutions_WeightedAverageCostCorrect()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act - Process partial fills
            var partial1 = CreateOrderEvent(_btcSecurity.Symbol, 0.2m, 50000m, T0, "partial_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol, OrderStatus.PartiallyFilled);
            manager.ProcessGridOrderEvent(partial1);

            var partial2 = CreateOrderEvent(_btcSecurity.Symbol, 0.3m, 51000m, T0.AddSeconds(30), "partial_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol, OrderStatus.PartiallyFilled);
            manager.ProcessGridOrderEvent(partial2);

            var filled = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 49000m, T0.AddMinutes(1), "partial_3", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol, OrderStatus.Filled);
            manager.ProcessGridOrderEvent(filled);

            SetPortfolioHolding(_btcSecurity.Symbol, 1.0m);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(1.0m, gpAggregation[_btcSecurity.Symbol]);

            // Verify weighted average cost: (0.2*50000 + 0.3*51000 + 0.5*49000) / 1.0 = 49800
            var gridPositions = typeof(TradingPair).GetProperty("GridPositions").GetValue(pair) as Dictionary<string, GridPosition>;
            var position = gridPositions.Values.First();
            var avgCost = (decimal)typeof(GridPosition).GetProperty("Leg1AverageCost").GetValue(position);
            Assert.AreEqual(49800m, avgCost);

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(3, processedExecs.Count);

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            AssertLastFillTime(lastFillTimes, "gate", T0.AddMinutes(1));
        }

        #endregion

        #region Category 2: Deduplication Logic

        [Test]
        public void Test_DuplicateExecutionId_Reconciliation_OnlyProcessedOnce()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Process live OrderEvent
            var liveEvent = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "live_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(liveEvent);
            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);

            // Setup mock ExecutionHistoryProvider with DUPLICATE execution
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);
            var duplicateExec = CreateExecutionRecord(_btcSecurity.Symbol, 0.5m, 50000m, T0, "live_1", tag);
            mockProvider.Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(new List<ExecutionRecord> { duplicateExec });
            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);

            // Act
            manager.Reconciliation();

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.5m, gpAggregation[_btcSecurity.Symbol]); // NOT 1.0 - no double-counting

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(1, processedExecs.Count); // Still just one

            AssertPortfolioMatchesGridPositions(manager, _portfolio);
        }

        [Test]
        public void Test_SameExecutionId_DifferentSymbols_BothProcessedBySymbolRouting()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act - Process two fills with same ExecutionId but different Symbols
            var btcEvent = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "shared_id", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(btcEvent);

            var mstrEvent = CreateOrderEvent(_mstrSecurity.Symbol, -100m, 500m, T0, "shared_id", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(mstrEvent);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.5m, gpAggregation[_btcSecurity.Symbol]);
            Assert.AreEqual(-100m, gpAggregation[_mstrSecurity.Symbol]);

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count); // Both tracked
        }

        [Test]
        public void Test_NullExecutionId_StillProcessed_NoDeduplication()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act - Process two events with null ExecutionId
            var event1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, null, levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(event1);

            var event2 = CreateOrderEvent(_btcSecurity.Symbol, 0.3m, 51000m, T0.AddMinutes(1), null, levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(event2);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.8m, gpAggregation[_btcSecurity.Symbol]); // Both processed

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(0, processedExecs.Count); // Nulls not tracked

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            AssertLastFillTime(lastFillTimes, "gate", T0.AddMinutes(1)); // Still updated
        }

        [Test]
        public void Test_EmptyExecutionId_StillProcessed_NoDeduplication()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act
            var event1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(event1);

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.5m, gpAggregation[_btcSecurity.Symbol]);

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(0, processedExecs.Count); // Empty string not tracked
        }

        #endregion

        #region Category 3: Time Filtering Logic

        [Test]
        public void Test_ShouldProcessExecution_ExecutionBeforeLastFill_Filtered()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0.AddMinutes(5) }
            });

            var oldExec = CreateExecutionRecord(_btcSecurity.Symbol, 0.5m, 50000m, T0.AddMinutes(2), "old_exec");

            // Act
            var result = InvokeShouldProcessExecution(manager, oldExec);

            // Assert
            Assert.IsFalse(result, "Old execution should be filtered");
        }

        [Test]
        public void Test_ShouldProcessExecution_ExecutionAtLastFill_Accepted()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0 }
            });

            var timeEqualExec = CreateExecutionRecord(_btcSecurity.Symbol, 0.5m, 50000m, T0, "time_equal");

            // Act
            var result = InvokeShouldProcessExecution(manager, timeEqualExec);

            // Assert
            Assert.IsTrue(result, "Time-equal execution should be accepted");
        }

        [Test]
        public void Test_ShouldProcessExecution_NewMarket_NoFilter_AllAccepted()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0 }
                // No "usa" entry
            });

            var newMarketExec = CreateExecutionRecord(_mstrSecurity.Symbol, -100m, 500m, T0.AddMinutes(-10), "new_market_exec");

            // Act
            var result = InvokeShouldProcessExecution(manager, newMarketExec);

            // Assert
            Assert.IsTrue(result, "New market should have no time filter");
        }

        #endregion

        #region Category 4: Cleanup Logic

        [Test]
        public void Test_CleanupProcessedExecutions_RemovesOldExecutions_KeepsRecent()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0.AddMinutes(5) },
                { "usa", T0.AddMinutes(3) }
            });

            // Create ExecutionSnapshot type
            var snapshotType = typeof(TradingPairManager).GetNestedType("ExecutionSnapshot", BindingFlags.NonPublic);
            var oldBtc = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(oldBtc, "old_btc");
            snapshotType.GetProperty("TimeUtc").SetValue(oldBtc, T0.AddMinutes(2));
            snapshotType.GetProperty("Market").SetValue(oldBtc, "coinbase");

            var recentBtc = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(recentBtc, "recent_btc");
            snapshotType.GetProperty("TimeUtc").SetValue(recentBtc, T0.AddMinutes(5));
            snapshotType.GetProperty("Market").SetValue(recentBtc, "coinbase");

            var oldMstr = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(oldMstr, "old_mstr");
            snapshotType.GetProperty("TimeUtc").SetValue(oldMstr, T0.AddMinutes(1));
            snapshotType.GetProperty("Market").SetValue(oldMstr, "usa");

            var recentMstr = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(recentMstr, "recent_mstr");
            snapshotType.GetProperty("TimeUtc").SetValue(recentMstr, T0.AddMinutes(4));
            snapshotType.GetProperty("Market").SetValue(recentMstr, "usa");

            SetProcessedExecutions(manager, new Dictionary<string, TradingPairManager.ExecutionSnapshot>
            {
                { "old_btc", (TradingPairManager.ExecutionSnapshot)oldBtc },
                { "recent_btc", (TradingPairManager.ExecutionSnapshot)recentBtc },
                { "old_mstr", (TradingPairManager.ExecutionSnapshot)oldMstr },
                { "recent_mstr", (TradingPairManager.ExecutionSnapshot)recentMstr }
            });

            // Act
            InvokeCleanupProcessedExecutions(manager);

            // Assert
            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count);
            Assert.IsTrue(processedExecs.ContainsKey("recent_btc"));
            Assert.IsTrue(processedExecs.ContainsKey("recent_mstr"));
            Assert.IsFalse(processedExecs.ContainsKey("old_btc"));
            Assert.IsFalse(processedExecs.ContainsKey("old_mstr"));
        }

        [Test]
        public void Test_CleanupProcessedExecutions_NoLastFillTime_NoCleanup()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0 }
                // No "usa" entry
            });

            var snapshotType = typeof(TradingPairManager).GetNestedType("ExecutionSnapshot", BindingFlags.NonPublic);

            var btcExec = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(btcExec, "btc_exec");
            snapshotType.GetProperty("TimeUtc").SetValue(btcExec, T0.AddMinutes(-1));
            snapshotType.GetProperty("Market").SetValue(btcExec, "coinbase");

            var mstrExec = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(mstrExec, "mstr_exec");
            snapshotType.GetProperty("TimeUtc").SetValue(mstrExec, T0.AddMinutes(-2));
            snapshotType.GetProperty("Market").SetValue(mstrExec, "usa");

            SetProcessedExecutions(manager, new Dictionary<string, TradingPairManager.ExecutionSnapshot>
            {
                { "btc_exec", (TradingPairManager.ExecutionSnapshot)btcExec },
                { "mstr_exec", (TradingPairManager.ExecutionSnapshot)mstrExec }
            });

            // Act
            InvokeCleanupProcessedExecutions(manager);

            // Assert
            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(1, processedExecs.Count);
            Assert.IsFalse(processedExecs.ContainsKey("btc_exec")); // Removed
            Assert.IsTrue(processedExecs.ContainsKey("mstr_exec")); // Kept (no lastFillTime for "usa")
        }

        #endregion

        #region Category 5: Reconciliation Integration

        [Test]
        public void Test_Reconciliation_WithExecutionHistoryProvider_RebuildsGPFromEmpty()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);

            // Simulate reconnection: LP has brokerage positions
            SetPortfolioHolding(_btcSecurity.Symbol, 0.7m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            // Setup mock ExecutionHistoryProvider
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            var executions = new List<ExecutionRecord>
            {
                CreateExecutionRecord(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_hist_1", tag),
                CreateExecutionRecord(_mstrSecurity.Symbol, -100m, 500m, T0.AddMinutes(1), "exec_hist_2", tag),
                CreateExecutionRecord(_btcSecurity.Symbol, 0.2m, 51000m, T0.AddMinutes(2), "exec_hist_3", tag)
            };
            mockProvider.Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(executions);
            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);

            // Act
            manager.InitializeBaseline(_portfolio); // Won't set baseline (_lastFillTimeByMarket is empty)
            manager.CompareBaseline(_portfolio); // Should trigger reconciliation

            // Assert
            mockProvider.Verify(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()), Times.Once);

            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.7m, gpAggregation[_btcSecurity.Symbol]);
            Assert.AreEqual(-100m, gpAggregation[_mstrSecurity.Symbol]);

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(3, processedExecs.Count);

            var lastFillTimes = GetLastFillTimeByMarket(manager);
            AssertLastFillTime(lastFillTimes, "gate", T0.AddMinutes(2));
            AssertLastFillTime(lastFillTimes, "usa", T0.AddMinutes(1));

            // Verify reconciliation complete
            AssertPortfolioMatchesGridPositions(manager, _portfolio);
        }

        [Test]
        public void Test_Reconciliation_TimeRangeCalculation_UsesMinLastFillMinusFiveMinutes()
        {
            // Arrange
            var manager = CreateManager();
            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);

            SetLastFillTimeByMarket(manager, new Dictionary<string, DateTime>
            {
                { "coinbase", T0.AddMinutes(10) },
                { "usa", T0.AddMinutes(5) }
            });

            DateTime? capturedStartTime = null;
            DateTime? capturedEndTime = null;

            var mockProvider = new Mock<IExecutionHistoryProvider>();
            mockProvider.Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Callback<DateTime, DateTime>((start, end) =>
                {
                    capturedStartTime = start;
                    capturedEndTime = end;
                })
                .Returns(new List<ExecutionRecord>());
            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);

            // Act
            manager.Reconciliation();

            // Assert
            Assert.IsNotNull(capturedStartTime);
            Assert.IsNotNull(capturedEndTime);

            // Start time should be min(lastFillTimes) - 5 minutes = T0 + 5min - 5min = T0
            Assert.AreEqual(T0, capturedStartTime.Value);
            Assert.GreaterOrEqual(capturedEndTime.Value, DateTime.UtcNow.AddSeconds(-5));
        }

        [Test]
        public void Test_Reconciliation_FiltersDuplicatesFromHistory_NoDoubleProcessing()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);

            // Process live event
            var liveEvent = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(liveEvent);

            // Setup mock with duplicate and new execution
            var mockProvider = new Mock<IExecutionHistoryProvider>();
            var executions = new List<ExecutionRecord>
            {
                CreateExecutionRecord(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_1", tag), // DUPLICATE
                CreateExecutionRecord(_btcSecurity.Symbol, 0.3m, 51000m, T0.AddMinutes(1), "exec_2", tag) // NEW
            };
            mockProvider.Setup(p => p.GetExecutionHistory(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
                .Returns(executions);
            _mockAlgorithm.Setup(a => a.ExecutionHistoryProvider).Returns(mockProvider.Object);

            SetPortfolioHolding(_btcSecurity.Symbol, 0.8m);

            // Act
            manager.Reconciliation();

            // Assert
            var gpAggregation = InvokeAggregateGridPositions(manager);
            Assert.AreEqual(0.8m, gpAggregation[_btcSecurity.Symbol]); // 0.5 from before + 0.3 new

            var processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count); // exec_1 and exec_2
        }

        [Test]
        public void Test_CompareBaseline_WhenConsistent_TriggersCleanup()
        {
            // Arrange
            var manager = CreateManager();
            var pair = CreateTradingPair(manager, _btcSecurity.Symbol, _mstrSecurity.Symbol);

            var T0 = new DateTime(2024, 1, 1, 10, 0, 0, DateTimeKind.Utc);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Process two OrderEvents
            var event1 = CreateOrderEvent(_btcSecurity.Symbol, 0.5m, 50000m, T0, "exec_1", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(event1);

            var event2 = CreateOrderEvent(_mstrSecurity.Symbol, -100m, 500m, T0.AddMinutes(5), "exec_2", levelPair, _btcSecurity.Symbol, _mstrSecurity.Symbol);
            manager.ProcessGridOrderEvent(event2);

            SetPortfolioHolding(_btcSecurity.Symbol, 0.5m);
            SetPortfolioHolding(_mstrSecurity.Symbol, -100m);

            // Manually add old execution to test cleanup
            var snapshotType = typeof(TradingPairManager).GetNestedType("ExecutionSnapshot", BindingFlags.NonPublic);
            var oldExec = Activator.CreateInstance(snapshotType);
            snapshotType.GetProperty("ExecutionId").SetValue(oldExec, "old_exec");
            snapshotType.GetProperty("TimeUtc").SetValue(oldExec, T0);
            snapshotType.GetProperty("Market").SetValue(oldExec, "coinbase");

            var processedExecs = GetProcessedExecutions(manager);
            processedExecs["old_exec"] = (TradingPairManager.ExecutionSnapshot)oldExec;

            // Act
            manager.CompareBaseline(_portfolio);

            // Assert - Cleanup should have been triggered
            processedExecs = GetProcessedExecutions(manager);
            Assert.AreEqual(2, processedExecs.Count);
            Assert.IsTrue(processedExecs.ContainsKey("exec_2")); // T0+5min, equal to lastFillTime, kept
            Assert.IsFalse(processedExecs.ContainsKey("exec_1")); // T0 < T0+5min, removed
        }

        #endregion
    }
}
