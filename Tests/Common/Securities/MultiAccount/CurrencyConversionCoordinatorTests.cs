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
using Moq;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Brokerages;
using QuantConnect.Data;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Securities.CurrencyConversion;
using QuantConnect.Securities.MultiAccount;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Common.Securities.MultiAccount
{
    [TestFixture]
    public class CurrencyConversionCoordinatorTests
    {
        private CurrencyConversionCoordinator _coordinator;
        private static readonly SecurityExchangeHours SecurityExchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);

        [SetUp]
        public void SetUp()
        {
            _coordinator = new CurrencyConversionCoordinator();
        }

        [Test]
        public void SetupSubAccountConversionsCreatesSubscriptions()
        {
            // Arrange
            var algorithm = CreateTestAlgorithm();
            var securityService = new SecurityService(
                algorithm.Portfolio.CashBook,
                MarketHoursDatabase.FromDataFolder(),
                SymbolPropertiesDatabase.FromDataFolder(),
                algorithm,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCacheProvider(algorithm.Portfolio));

            var accountConfigs = new Dictionary<string, decimal>
            {
                { "account1", 10000m }
            };
            var accountCurrencies = new Dictionary<string, string>
            {
                { "account1", "USDT" }
            };
            var router = new TestRouter("account1");

            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                algorithm.Securities,
                algorithm.Transactions,
                algorithm.Settings,
                algorithm.DefaultOrderProperties,
                TimeKeeper,
                accountCurrencies
            );

            // Add a currency that requires conversion
            multiPortfolio.GetAccount("account1").CashBook.Add("BTC", 1m, 0m);

            // Act
            _coordinator.SetupSubAccountConversions(multiPortfolio, algorithm, securityService);

            // Assert - Verify that currency conversion subscriptions were attempted
            // Note: Actual subscription creation depends on market data availability
            Assert.IsNotNull(multiPortfolio.GetAccount("account1").CashBook["BTC"].CurrencyConversion);
        }

        [Test]
        public void SyncConversionsToMainClearsMainAccountFirst()
        {
            // Arrange
            var algorithm = CreateTestAlgorithm();
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "account1", 10000m }
            };
            var accountCurrencies = new Dictionary<string, string>
            {
                { "account1", "USD" }
            };
            var router = new TestRouter("account1");

            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                algorithm.Securities,
                algorithm.Transactions,
                algorithm.Settings,
                algorithm.DefaultOrderProperties,
                TimeKeeper,
                accountCurrencies
            );

            var mainCashBook = ((SecurityPortfolioManager)multiPortfolio).CashBook;

            // Verify main account initially has default USD (from algorithm initialization)
            // The main account should have been set to 10000 from initialization
            var initialUsdAmount = mainCashBook[Currencies.USD].Amount;

            // Act
            _coordinator.SyncConversionsToMain(multiPortfolio);

            // Assert - Main account should aggregate from sub-accounts
            Assert.AreEqual(10000m, mainCashBook[Currencies.USD].Amount,
                "Main account USD should equal sum of sub-accounts");
        }

        [Test]
        public void SyncConversionsToMainAggregatesCurrencies()
        {
            // Arrange
            var algorithm = CreateTestAlgorithm();
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "account1", 5000m },
                { "account2", 7000m }
            };
            var accountCurrencies = new Dictionary<string, string>
            {
                { "account1", "USDT" },
                { "account2", "USDT" }
            };
            var router = new TestRouter("account1");

            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                algorithm.Securities,
                algorithm.Transactions,
                algorithm.Settings,
                algorithm.DefaultOrderProperties,
                TimeKeeper,
                accountCurrencies
            );

            // Add different currencies to each account
            multiPortfolio.GetAccount("account1").CashBook.Add("BTC", 1m, 50000m);
            multiPortfolio.GetAccount("account2").CashBook.Add("BTC", 0.5m, 50000m);
            multiPortfolio.GetAccount("account2").CashBook.Add("ETH", 10m, 3000m);

            // Act
            _coordinator.SyncConversionsToMain(multiPortfolio);

            // Assert
            var mainCashBook = ((SecurityPortfolioManager)multiPortfolio).CashBook;

            Assert.IsTrue(mainCashBook.ContainsKey("USDT"), "Main account should have USDT");
            Assert.IsTrue(mainCashBook.ContainsKey("BTC"), "Main account should have BTC");
            Assert.IsTrue(mainCashBook.ContainsKey("ETH"), "Main account should have ETH");

            Assert.AreEqual(12000m, mainCashBook["USDT"].Amount, "USDT should be sum of both accounts");
            Assert.AreEqual(1.5m, mainCashBook["BTC"].Amount, "BTC should be sum of both accounts");
            Assert.AreEqual(10m, mainCashBook["ETH"].Amount, "ETH should only come from account2");
        }

        [Test]
        public void SyncConversionsToMainCopiesConversions()
        {
            // Arrange
            var algorithm = CreateTestAlgorithm();
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "account1", 10000m }
            };
            var accountCurrencies = new Dictionary<string, string>
            {
                { "account1", "USDT" }
            };
            var router = new TestRouter("account1");

            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                algorithm.Securities,
                algorithm.Transactions,
                algorithm.Settings,
                algorithm.DefaultOrderProperties,
                TimeKeeper,
                accountCurrencies
            );

            // Set up a conversion in sub-account
            var subAccount = multiPortfolio.GetAccount("account1");
            var btcCash = new Cash("BTC", 1m, 50000m);
            var conversion = new ConstantCurrencyConversion("BTC", "USDT", 50000m);
            btcCash.CurrencyConversion = conversion;
            subAccount.CashBook.Add("BTC", btcCash);

            // Act
            _coordinator.SyncConversionsToMain(multiPortfolio);

            // Assert
            var mainCashBook = ((SecurityPortfolioManager)multiPortfolio).CashBook;
            Assert.IsTrue(mainCashBook.ContainsKey("BTC"));
            Assert.IsNotNull(mainCashBook["BTC"].CurrencyConversion);
            Assert.AreEqual("USDT", mainCashBook["BTC"].CurrencyConversion.DestinationCurrency);
        }

        [Test]
        public void SyncConversionsToMainSetsIdentityForStablecoins()
        {
            // Arrange
            var algorithm = CreateTestAlgorithm();
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "account1", 10000m }
            };
            var accountCurrencies = new Dictionary<string, string>
            {
                { "account1", "USDT" }
            };
            var router = new TestRouter("account1");

            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                algorithm.Securities,
                algorithm.Transactions,
                algorithm.Settings,
                algorithm.DefaultOrderProperties,
                TimeKeeper,
                accountCurrencies
            );

            // Add USD-pegged stablecoins
            multiPortfolio.GetAccount("account1").CashBook.Add("USDC", 5000m, 1m);
            multiPortfolio.GetAccount("account1").CashBook.Add("BUSD", 3000m, 1m);

            // Act
            _coordinator.SyncConversionsToMain(multiPortfolio);

            // Assert
            var mainCashBook = ((SecurityPortfolioManager)multiPortfolio).CashBook;

            Assert.IsTrue(mainCashBook.ContainsKey("USDC"));
            Assert.IsTrue(mainCashBook.ContainsKey("BUSD"));

            // Verify Identity conversion was set (converts to USD at 1:1 rate)
            var usdcConversion = mainCashBook["USDC"].CurrencyConversion;
            var busdConversion = mainCashBook["BUSD"].CurrencyConversion;

            Assert.IsNotNull(usdcConversion);
            Assert.IsNotNull(busdConversion);

            // Identity conversions should convert to USD
            Assert.AreEqual("USD", usdcConversion.DestinationCurrency);
            Assert.AreEqual("USD", busdConversion.DestinationCurrency);

            // Verify conversion rate is 1:1
            Assert.AreEqual(1m, usdcConversion.ConversionRate);
            Assert.AreEqual(1m, busdConversion.ConversionRate);
        }

        // Helper Methods

        private static QCAlgorithm CreateTestAlgorithm()
        {
            var algorithm = new QCAlgorithm();
            algorithm.SubscriptionManager.SetDataManager(new DataManagerStub(algorithm));
            return algorithm;
        }

        private static TimeKeeper TimeKeeper
        {
            get { return new TimeKeeper(DateTime.UtcNow, new[] { TimeZones.NewYork }); }
        }

        // Test Router Implementation
        private class TestRouter : IOrderRouter
        {
            private readonly string _targetAccount;

            public TestRouter(string targetAccount)
            {
                _targetAccount = targetAccount;
            }

            public string Route(Order order)
            {
                return _targetAccount;
            }

            public bool Validate()
            {
                return !string.IsNullOrEmpty(_targetAccount);
            }
        }
    }
}
