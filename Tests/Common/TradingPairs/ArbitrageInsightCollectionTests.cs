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
using Moq;
using NUnit.Framework;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Data;
using QuantConnect.Interfaces;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class ArbitrageInsightCollectionTests
    {
        private SecurityManager _securities;
        private SecurityTransactionManager _transactions;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private TradingPair _tradingPair;
        private GridLevelPair _gridLevel1;
        private GridLevelPair _gridLevel2;
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;
        private DateTime _testTime;

        [SetUp]
        public void Setup()
        {
            _testTime = new DateTime(2024, 1, 1, 9, 30, 0);
            _securities = new SecurityManager(new TimeKeeper(_testTime, TimeZones.NewYork));
            _mockAlgorithm = new Mock<AIAlgorithm>();
            _transactions = new SecurityTransactionManager(_mockAlgorithm.Object, _securities);
            _mockAlgorithm.Setup(a => a.Securities).Returns(_securities);
            _mockAlgorithm.Setup(a => a.Transactions).Returns(_transactions);

            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var timeKeeper = new LocalTimeKeeper(_testTime.ConvertToUtc(TimeZones.NewYork), TimeZones.NewYork);

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            var btcSecurity = CreateSecurity(_btcSymbol, exchangeHours, timeKeeper);
            var mstrSecurity = CreateSecurity(_mstrSymbol, exchangeHours, timeKeeper);

            _securities.Add(btcSecurity);
            _securities.Add(mstrSecurity);

            // Create TradingPair with all required parameters
            _tradingPair = new TradingPair(_btcSymbol, _mstrSymbol, "spread", btcSecurity, mstrSecurity);

            // Create GridLevelPairs using the correct constructor signature
            // LONG_SPREAD entry must be negative (crypto overpriced relative to stock)
            _gridLevel1 = new GridLevelPair(
                -0.02m,      // entrySpread (negative for LONG_SPREAD)
                0.005m,      // exitSpread (positive)
                "LONG_SPREAD",
                0.25m,       // positionSizePct
                (_btcSymbol, _mstrSymbol)
            );

            _gridLevel2 = new GridLevelPair(
                -0.03m,      // entrySpread (negative for LONG_SPREAD)
                0.01m,       // exitSpread (positive)
                "LONG_SPREAD",
                0.25m,       // positionSizePct
                (_btcSymbol, _mstrSymbol)
            );
        }

        private Security CreateSecurity(Symbol symbol, SecurityExchangeHours exchangeHours, LocalTimeKeeper timeKeeper)
        {
            var config = new SubscriptionDataConfig(
                typeof(QuantConnect.Data.Market.TradeBar),
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

        [Test]
        public void AddIncreasesCount()
        {
            var collection = new ArbitrageInsightCollection();
            Assert.AreEqual(0, collection.Count);
            Assert.AreEqual(0, collection.TotalCount);

            var insight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1);
            collection.Add(insight);

            Assert.AreEqual(1, collection.Count);
            Assert.AreEqual(1, collection.TotalCount);
        }

        [Test]
        public void AddRangeAddsMultipleInsights()
        {
            var collection = new ArbitrageInsightCollection();

            var insights = new[]
            {
                CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1),
                CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel2)
            };

            collection.AddRange(insights);

            Assert.AreEqual(2, collection.Count);
            Assert.AreEqual(2, collection.TotalCount);
        }

        [Test]
        public void GetInsightReturnsCorrectInsight()
        {
            var collection = new ArbitrageInsightCollection();
            var insight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1);
            collection.Add(insight);

            var retrieved = collection.GetInsight(_tradingPair, _gridLevel1);

            Assert.IsNotNull(retrieved);
            Assert.AreEqual(insight.Id, retrieved.Id);
        }

        [Test]
        public void GetInsightReturnsNullForNonExistent()
        {
            var collection = new ArbitrageInsightCollection();
            var retrieved = collection.GetInsight(_tradingPair, _gridLevel1);

            Assert.IsNull(retrieved);
        }

        [Test]
        public void GetActiveInsightsFiltersExpiredInsights()
        {
            var collection = new ArbitrageInsightCollection();

            var activeInsight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1, TimeSpan.FromHours(1));
            var expiredInsight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel2, TimeSpan.FromMinutes(1));

            collection.Add(activeInsight);
            collection.Add(expiredInsight);

            // Initialize timestamps
            activeInsight.GeneratedTimeUtc = _testTime;
            activeInsight.CloseTimeUtc = _testTime.AddHours(1);
            expiredInsight.GeneratedTimeUtc = _testTime;
            expiredInsight.CloseTimeUtc = _testTime.AddMinutes(1);

            // Query 30 minutes later
            var queryTime = _testTime.AddMinutes(30);
            var activeInsights = collection.GetActiveInsights(queryTime);

            Assert.AreEqual(1, activeInsights.Count);
            Assert.AreEqual(activeInsight.Id, activeInsights[0].Id);
        }

        [Test]
        public void RemoveExpiredInsightsRemovesAndReturnsExpired()
        {
            var collection = new ArbitrageInsightCollection();

            var activeInsight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1, TimeSpan.FromHours(1));
            var expiredInsight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel2, TimeSpan.FromMinutes(1));

            collection.Add(activeInsight);
            collection.Add(expiredInsight);

            activeInsight.GeneratedTimeUtc = _testTime;
            activeInsight.CloseTimeUtc = _testTime.AddHours(1);
            expiredInsight.GeneratedTimeUtc = _testTime;
            expiredInsight.CloseTimeUtc = _testTime.AddMinutes(1);

            var queryTime = _testTime.AddMinutes(30);
            var removed = collection.RemoveExpiredInsights(queryTime);

            Assert.AreEqual(1, removed.Count);
            Assert.AreEqual(expiredInsight.Id, removed[0].Id);
            Assert.AreEqual(1, collection.Count);  // Only active one remains
            Assert.AreEqual(2, collection.TotalCount);  // Total count unchanged
        }

        [Test]
        public void CancelMakesInsightExpiredAndRemovesFromActive()
        {
            var collection = new ArbitrageInsightCollection();
            var insight = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1, TimeSpan.FromHours(1));

            collection.Add(insight);
            insight.GeneratedTimeUtc = _testTime;
            insight.CloseTimeUtc = _testTime.AddHours(1);

            Assert.AreEqual(1, collection.Count);
            Assert.IsTrue(insight.IsActive(_testTime));

            collection.Cancel(insight, _testTime);

            Assert.AreEqual(0, collection.Count);  // Removed from active
            Assert.AreEqual(1, collection.TotalCount);  // Still in total
            Assert.IsFalse(insight.IsActive(_testTime));  // Now expired
        }

        [Test]
        public void GetInsightsForPairReturnsCorrectInsights()
        {
            var collection = new ArbitrageInsightCollection();

            var insight1 = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1);
            var insight2 = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel2);

            collection.Add(insight1);
            collection.Add(insight2);

            var pairInsights = collection.GetInsightsForPair(_tradingPair);

            Assert.AreEqual(2, pairInsights.Count);
        }

        [Test]
        public void AddingInsightWithSameKeyOverwritesPrevious()
        {
            var collection = new ArbitrageInsightCollection();

            var insight1 = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1);
            var insight2 = CreateInsight(SignalType.Entry, SpreadDirection.ShortSpread, _gridLevel1);

            collection.Add(insight1);
            collection.Add(insight2);  // Same pair + level, should overwrite

            Assert.AreEqual(1, collection.Count);  // Only one active
            Assert.AreEqual(2, collection.TotalCount);  // But both in history

            var retrieved = collection.GetInsight(_tradingPair, _gridLevel1);
            Assert.AreEqual(insight2.Id, retrieved.Id);  // Should be the second one
        }

        [Test]
        public void EnumeratorReturnsActiveInsights()
        {
            var collection = new ArbitrageInsightCollection();

            var insight1 = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel1);
            var insight2 = CreateInsight(SignalType.Entry, SpreadDirection.LongSpread, _gridLevel2);

            collection.Add(insight1);
            collection.Add(insight2);

            var enumerated = collection.ToList();

            Assert.AreEqual(2, enumerated.Count);
        }

        private ArbitrageInsight CreateInsight(
            SignalType type,
            SpreadDirection direction,
            GridLevelPair levelPair,
            TimeSpan? period = null)
        {
            return new ArbitrageInsight(
                _tradingPair,
                levelPair,
                type,
                direction,
                0.025m,  // 2.5% spread snapshot
                period ?? TimeSpan.FromDays(1),
                0.8  // 80% confidence
            );
        }
    }
}
