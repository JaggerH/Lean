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
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Algorithm.Framework.Execution;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs;

namespace QuantConnect.Tests.Algorithm
{
    [TestFixture]
    public class AQCAlgorithmOnTradingPairsChangedTests
    {
        private TestAQCAlgorithm _algorithm;

        [SetUp]
        public void Setup()
        {
            _algorithm = new TestAQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(new DataManagerStub(_algorithm));
        }

        [Test]
        public void OnTradingPairsChanged_IsCalledWhenPairAdded()
        {
            // Arrange
            var spy = AddSecurity(_algorithm, Symbols.SPY);
            var aapl = AddSecurity(_algorithm, Symbols.AAPL);

            var alphaModel = new TestArbitrageAlphaModel();
            var portfolioModel = new TestArbitragePortfolioConstructionModel();
            var executionModel = new TestArbitrageExecutionModel();

            // Set alpha model using reflection since SetAlpha expects IAlphaModel
            typeof(QCAlgorithm).GetProperty("Alpha").SetValue(_algorithm, alphaModel);
            _algorithm.SetArbitragePortfolioConstruction(portfolioModel);
            _algorithm.SetArbitrageExecution(executionModel);

            // Act
            var pair = _algorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test");

            // Assert
            Assert.AreEqual(1, alphaModel.OnTradingPairsChangedCallCount, "Alpha model should be notified");
            Assert.AreEqual(1, portfolioModel.OnTradingPairsChangedCallCount, "Portfolio model should be notified");
            Assert.AreEqual(1, executionModel.OnTradingPairsChangedCallCount, "Execution model should be notified");

            Assert.AreEqual(1, alphaModel.LastChanges.AddedPairs.Count, "Should have 1 added pair");
            Assert.AreEqual(0, alphaModel.LastChanges.RemovedPairs.Count, "Should have 0 removed pairs");
            Assert.AreEqual(pair, alphaModel.LastChanges.AddedPairs[0], "Added pair should match");
        }

        [Test]
        public void OnTradingPairsChanged_IsCalledWhenPairRemoved()
        {
            // Arrange
            var spy = AddSecurity(_algorithm, Symbols.SPY);
            var aapl = AddSecurity(_algorithm, Symbols.AAPL);

            var alphaModel = new TestArbitrageAlphaModel();
            var portfolioModel = new TestArbitragePortfolioConstructionModel();
            var executionModel = new TestArbitrageExecutionModel();

            // Set alpha model using reflection since SetAlpha expects IAlphaModel
            typeof(QCAlgorithm).GetProperty("Alpha").SetValue(_algorithm, alphaModel);
            _algorithm.SetArbitragePortfolioConstruction(portfolioModel);
            _algorithm.SetArbitrageExecution(executionModel);

            var pair = _algorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test");

            // Reset counters after add
            alphaModel.Reset();
            portfolioModel.Reset();
            executionModel.Reset();

            // Act
            _algorithm.TradingPairs.RemovePair(Symbols.SPY, Symbols.AAPL);

            // Assert
            Assert.AreEqual(1, alphaModel.OnTradingPairsChangedCallCount, "Alpha model should be notified");
            Assert.AreEqual(1, portfolioModel.OnTradingPairsChangedCallCount, "Portfolio model should be notified");
            Assert.AreEqual(1, executionModel.OnTradingPairsChangedCallCount, "Execution model should be notified");

            Assert.AreEqual(0, alphaModel.LastChanges.AddedPairs.Count, "Should have 0 added pairs");
            Assert.AreEqual(1, alphaModel.LastChanges.RemovedPairs.Count, "Should have 1 removed pair");
            Assert.AreEqual(pair, alphaModel.LastChanges.RemovedPairs[0], "Removed pair should match");
        }

        [Test]
        public void OnTradingPairsChanged_NotCalledWhenModelsNotSet()
        {
            // Arrange
            var spy = AddSecurity(_algorithm, Symbols.SPY);
            var aapl = AddSecurity(_algorithm, Symbols.AAPL);

            // Don't set any models - use defaults

            // Act - should not throw
            Assert.DoesNotThrow(() =>
            {
                _algorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test");
            });
        }

        [Test]
        public void OnTradingPairsChanged_OnlyNotifiesArbitrageAlphaModel()
        {
            // Arrange
            var spy = AddSecurity(_algorithm, Symbols.SPY);
            var aapl = AddSecurity(_algorithm, Symbols.AAPL);

            var regularAlphaModel = new TestRegularAlphaModel();
            var portfolioModel = new TestArbitragePortfolioConstructionModel();

            typeof(QCAlgorithm).GetProperty("Alpha").SetValue(_algorithm, regularAlphaModel);
            _algorithm.SetArbitragePortfolioConstruction(portfolioModel);

            // Act
            _algorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test");

            // Assert
            Assert.AreEqual(0, regularAlphaModel.OnSecuritiesChangedCallCount,
                "Regular alpha model should not be notified via OnSecuritiesChanged");
            Assert.AreEqual(1, portfolioModel.OnTradingPairsChangedCallCount,
                "Portfolio model should still be notified");
        }

        [Test]
        public void OnTradingPairsChanged_CanBeOverriddenInUserAlgorithm()
        {
            // Arrange
            var customAlgorithm = new CustomAQCAlgorithm();
            customAlgorithm.SubscriptionManager.SetDataManager(new DataManagerStub(customAlgorithm));

            var spy = AddSecurity(customAlgorithm, Symbols.SPY);
            var aapl = AddSecurity(customAlgorithm, Symbols.AAPL);

            // Act
            customAlgorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test");

            // Assert
            Assert.AreEqual(1, customAlgorithm.OnTradingPairsChangedCallCount,
                "Custom OnTradingPairsChanged should be called");
            Assert.IsTrue(customAlgorithm.LastChanges.HasChanges,
                "Changes should be passed to override");
        }

        [Test]
        public void OnTradingPairsChanged_HandlesMultiplePairsAdded()
        {
            // Arrange
            var spy = AddSecurity(_algorithm, Symbols.SPY);
            var aapl = AddSecurity(_algorithm, Symbols.AAPL);
            var qqq = AddSecurity(_algorithm, Symbol.Create("QQQ", SecurityType.Equity, Market.USA));

            var alphaModel = new TestArbitrageAlphaModel();
            typeof(QCAlgorithm).GetProperty("Alpha").SetValue(_algorithm, alphaModel);

            // Act - Add multiple pairs
            var pair1 = _algorithm.AddTradingPair(Symbols.SPY, Symbols.AAPL, "test1");
            var pair2 = _algorithm.AddTradingPair(Symbols.SPY, Symbol.Create("QQQ", SecurityType.Equity, Market.USA), "test2");

            // Assert
            Assert.AreEqual(2, alphaModel.OnTradingPairsChangedCallCount,
                "Should be called twice for two separate additions");
        }

        private Security AddSecurity(AQCAlgorithm algorithm, Symbol symbol)
        {
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var timeKeeper = new LocalTimeKeeper(DateTime.UtcNow, TimeZones.NewYork);

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
            algorithm.Securities.Add(security);
            return security;
        }
    }

    /// <summary>
    /// Test implementation of AQCAlgorithm
    /// </summary>
    public class TestAQCAlgorithm : AQCAlgorithm
    {
        public TestAQCAlgorithm()
        {
            // No history provider needed for these tests
        }
    }

    /// <summary>
    /// Custom algorithm that overrides OnTradingPairsChanged
    /// </summary>
    public class CustomAQCAlgorithm : AQCAlgorithm
    {
        public int OnTradingPairsChangedCallCount { get; private set; }
        public TradingPairChanges LastChanges { get; private set; }

        public CustomAQCAlgorithm()
        {
            // No history provider needed for these tests
        }

        public override void OnTradingPairsChanged(TradingPairChanges changes)
        {
            OnTradingPairsChangedCallCount++;
            LastChanges = changes;
            base.OnTradingPairsChanged(changes);
        }
    }

    /// <summary>
    /// Test implementation of ArbitrageAlphaModel that tracks calls
    /// </summary>
    public class TestArbitrageAlphaModel : AlphaModel, IArbitrageAlphaModel
    {
        public int OnTradingPairsChangedCallCount { get; set; }
        public TradingPairChanges LastChanges { get; private set; }

        public void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            OnTradingPairsChangedCallCount++;
            LastChanges = changes;
        }

        // IEnumerable<ArbitrageInsight> IArbitrageAlphaModel.Update(AIAlgorithm algorithm, Slice data)
        // {
        //     return new ArbitrageInsight[0];
        // }

        public override IEnumerable<Insight> Update(QCAlgorithm algorithm, Slice data)
        {
            return new Insight[0];
        }

        public void Reset()
        {
            OnTradingPairsChangedCallCount = 0;
            LastChanges = null;
        }
    }

    /// <summary>
    /// Test implementation of regular AlphaModel (not arbitrage)
    /// </summary>
    public class TestRegularAlphaModel : AlphaModel
    {
        public int OnSecuritiesChangedCallCount { get; private set; }

        public override void OnSecuritiesChanged(QCAlgorithm algorithm, Data.UniverseSelection.SecurityChanges changes)
        {
            OnSecuritiesChangedCallCount++;
        }

        public override IEnumerable<Insight> Update(QCAlgorithm algorithm, Slice data)
        {
            return new Insight[0];
        }
    }

    /// <summary>
    /// Test implementation of ArbitragePortfolioConstructionModel
    /// </summary>
    public class TestArbitragePortfolioConstructionModel : ArbitragePortfolioConstructionModel
    {
        public int OnTradingPairsChangedCallCount { get; private set; }
        public TradingPairChanges LastChanges { get; private set; }

        public override void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            OnTradingPairsChangedCallCount++;
            LastChanges = changes;
            base.OnTradingPairsChanged(algorithm, changes);
        }

        public void Reset()
        {
            OnTradingPairsChangedCallCount = 0;
            LastChanges = null;
        }
    }

    /// <summary>
    /// Test implementation of ArbitrageExecutionModel
    /// </summary>
    public class TestArbitrageExecutionModel : ArbitrageExecutionModel
    {
        public int OnTradingPairsChangedCallCount { get; private set; }
        public TradingPairChanges LastChanges { get; private set; }

        public override void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            OnTradingPairsChangedCallCount++;
            LastChanges = changes;
            base.OnTradingPairsChanged(algorithm, changes);
        }

        public void Reset()
        {
            OnTradingPairsChangedCallCount = 0;
            LastChanges = null;
        }
    }
}
