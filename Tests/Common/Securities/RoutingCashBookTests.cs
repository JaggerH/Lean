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
using QuantConnect.Securities;
using QuantConnect.Securities.Volatility;
using QuantConnect.Orders.Fills;
using QuantConnect.Orders.Fees;
using QuantConnect.Orders.Slippage;

namespace QuantConnect.Tests.Common.Securities
{
    [TestFixture]
    public class RoutingCashBookTests
    {
        private CashBook _mainCashBook;
        private Dictionary<string, SecurityPortfolioManager> _subAccounts;
        private Dictionary<string, SecurityManager> _subAccountSecurityManagers;
        private SecurityManager _account1SecurityManager;
        private SecurityManager _account2SecurityManager;
        private SecurityPortfolioManager _account1Portfolio;
        private SecurityPortfolioManager _account2Portfolio;

        [SetUp]
        public void SetUp()
        {
            // Create main CashBook with standard currencies
            _mainCashBook = new CashBook();
            _mainCashBook.Add("USD", 10000m, 1m);
            _mainCashBook.Add("EUR", 5000m, 1.10m);
            _mainCashBook.Add("JPY", 100000m, 0.01m);

            // Create sub-account security managers
            var timeKeeper = new TimeKeeper(DateTime.UtcNow, TimeZones.NewYork);
            _account1SecurityManager = new SecurityManager(timeKeeper);
            _account2SecurityManager = new SecurityManager(timeKeeper);

            // Create mock crypto securities with IBaseCurrencySymbol for account1
            var aaplSymbol = Symbol.Create("AAPL", SecurityType.Crypto, Market.USA);
            var aaplCash = new Cash("AAPL", 100m, 150m);
            var aaplSecurity = CreateMockCryptoSecurity(aaplSymbol, aaplCash);
            _account1SecurityManager.Add(aaplSecurity);

            // Create mock crypto securities for account2
            var tslaSymbol = Symbol.Create("TSLA", SecurityType.Crypto, Market.USA);
            var tslaCash = new Cash("TSLA", 50m, 200m);
            var tslaSecurity = CreateMockCryptoSecurity(tslaSymbol, tslaCash);
            _account2SecurityManager.Add(tslaSecurity);

            // Create sub-account portfolios with their own CashBooks
            _account1Portfolio = new SecurityPortfolioManager(_account1SecurityManager, new SecurityTransactionManager(null, _account1SecurityManager), new AlgorithmSettings());
            _account1Portfolio.CashBook.Add("AAPL", 100m, 150m);
            _account1Portfolio.CashBook.Add("USD", 5000m, 1m);

            _account2Portfolio = new SecurityPortfolioManager(_account2SecurityManager, new SecurityTransactionManager(null, _account2SecurityManager), new AlgorithmSettings());
            _account2Portfolio.CashBook.Add("TSLA", 50m, 200m);
            _account2Portfolio.CashBook.Add("USD", 3000m, 1m);

            // Setup dictionaries
            _subAccounts = new Dictionary<string, SecurityPortfolioManager>
            {
                { "Account1", _account1Portfolio },
                { "Account2", _account2Portfolio }
            };

            _subAccountSecurityManagers = new Dictionary<string, SecurityManager>
            {
                { "Account1", _account1SecurityManager },
                { "Account2", _account2SecurityManager }
            };
        }

        /// <summary>
        /// Creates a mock crypto security that implements IBaseCurrencySymbol
        /// </summary>
        private Security CreateMockCryptoSecurity(Symbol symbol, Cash baseCurrency)
        {
            var quoteCurrency = new Cash(Currencies.USD, 0, 1m);
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var symbolProperties = SymbolProperties.GetDefault(Currencies.USD);
            var securityCache = new SecurityCache();

            return new MockCryptoSecurity(
                symbol,
                exchangeHours,
                quoteCurrency,
                baseCurrency,
                symbolProperties,
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                securityCache
            );
        }

        [Test]
        public void Constructor_ThrowsException_WhenMainCashBookIsNull()
        {
            Assert.Throws<ArgumentNullException>(() =>
                new RoutingCashBook(null, _subAccounts, _subAccountSecurityManagers));
        }

        [Test]
        public void Constructor_ThrowsException_WhenSubAccountsIsNull()
        {
            Assert.Throws<ArgumentNullException>(() =>
                new RoutingCashBook(_mainCashBook, null, _subAccountSecurityManagers));
        }

        [Test]
        public void Constructor_ThrowsException_WhenSubAccountSecurityManagersIsNull()
        {
            Assert.Throws<ArgumentNullException>(() =>
                new RoutingCashBook(_mainCashBook, _subAccounts, null));
        }

        [Test]
        public void Constructor_SetsAccountCurrency_FromMainCashBook()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);
            Assert.AreEqual(_mainCashBook.AccountCurrency, routingCashBook.AccountCurrency);
        }

        [Test]
        public void IndexerGetter_RoutesToMainCashBook_ForStandardCurrencies()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var usdCash = routingCashBook["USD"];
            Assert.AreEqual(10000m, usdCash.Amount);
            Assert.AreEqual(1m, usdCash.ConversionRate);

            var eurCash = routingCashBook["EUR"];
            Assert.AreEqual(5000m, eurCash.Amount);
            Assert.AreEqual(1.10m, eurCash.ConversionRate);

            var jpyCash = routingCashBook["JPY"];
            Assert.AreEqual(100000m, jpyCash.Amount);
            Assert.AreEqual(0.01m, jpyCash.ConversionRate);
        }

        [Test]
        public void IndexerGetter_RoutesToSubAccount_ForCryptoAssetCurrencies()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            // AAPL should route to Account1
            var aaplCash = routingCashBook["AAPL"];
            Assert.AreEqual(100m, aaplCash.Amount);
            Assert.AreEqual(150m, aaplCash.ConversionRate);

            // TSLA should route to Account2
            var tslaCash = routingCashBook["TSLA"];
            Assert.AreEqual(50m, tslaCash.Amount);
            Assert.AreEqual(200m, tslaCash.ConversionRate);
        }

        [Test]
        public void IndexerGetter_FallsBackToMainCashBook_WhenCurrencyNotFoundInSubAccounts()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            // GBP doesn't exist in any sub-account, should fall back to main CashBook
            // This will throw since GBP isn't in main CashBook either
            Assert.Throws<KeyNotFoundException>(() => { var _ = routingCashBook["GBP"]; });
        }

        [Test]
        public void IndexerSetter_DelegatesToMainCashBook()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var gbpCash = new Cash("GBP", 2000m, 1.25m);
            routingCashBook["GBP"] = gbpCash;

            // Verify it was added to main CashBook
            Assert.IsTrue(_mainCashBook.ContainsKey("GBP"));
            Assert.AreEqual(2000m, _mainCashBook["GBP"].Amount);
            Assert.AreEqual(1.25m, _mainCashBook["GBP"].ConversionRate);
        }

        [Test]
        public void ContainsKey_ReturnsTrue_ForStandardCurrenciesInMainCashBook()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            Assert.IsTrue(routingCashBook.ContainsKey("USD"));
            Assert.IsTrue(routingCashBook.ContainsKey("EUR"));
            Assert.IsTrue(routingCashBook.ContainsKey("JPY"));
        }

        [Test]
        public void ContainsKey_ReturnsTrue_ForCryptoAssetCurrenciesInSubAccounts()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            Assert.IsTrue(routingCashBook.ContainsKey("AAPL"));
            Assert.IsTrue(routingCashBook.ContainsKey("TSLA"));
        }

        [Test]
        public void ContainsKey_ReturnsFalse_WhenCurrencyNotFound()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            Assert.IsFalse(routingCashBook.ContainsKey("GBP"));
            Assert.IsFalse(routingCashBook.ContainsKey("MSFT"));
        }

        [Test]
        public void TryGetValue_ReturnsTrue_ForStandardCurrencies()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var success = routingCashBook.TryGetValue("USD", out var cash);
            Assert.IsTrue(success);
            Assert.IsNotNull(cash);
            Assert.AreEqual(10000m, cash.Amount);
        }

        [Test]
        public void TryGetValue_ReturnsTrue_ForCryptoAssetCurrencies()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var success1 = routingCashBook.TryGetValue("AAPL", out var aaplCash);
            Assert.IsTrue(success1);
            Assert.IsNotNull(aaplCash);
            Assert.AreEqual(100m, aaplCash.Amount);

            var success2 = routingCashBook.TryGetValue("TSLA", out var tslaCash);
            Assert.IsTrue(success2);
            Assert.IsNotNull(tslaCash);
            Assert.AreEqual(50m, tslaCash.Amount);
        }

        [Test]
        public void TryGetValue_ReturnsFalse_WhenCurrencyNotFound()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var success = routingCashBook.TryGetValue("GBP", out var cash);
            Assert.IsFalse(success);
            Assert.IsNull(cash);
        }

        [Test]
        public void Count_ReturnsMainCashBookCount()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            // Main CashBook has USD (default) + EUR + JPY = 3
            Assert.AreEqual(_mainCashBook.Count, routingCashBook.Count);
        }

        [Test]
        public void Add_AddsToMainCashBook()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            var initialCount = _mainCashBook.Count;
            routingCashBook.Add("GBP", 1000m, 1.25m);

            Assert.AreEqual(initialCount + 1, _mainCashBook.Count);
            Assert.IsTrue(_mainCashBook.ContainsKey("GBP"));
            Assert.AreEqual(1000m, _mainCashBook["GBP"].Amount);
        }

        [Test]
        public void ToString_ReturnsMainCashBookString()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            Assert.AreEqual(_mainCashBook.ToString(), routingCashBook.ToString());
        }

        [Test]
        public void RoutingLogic_WorksWithMultipleSubAccounts()
        {
            var routingCashBook = new RoutingCashBook(_mainCashBook, _subAccounts, _subAccountSecurityManagers);

            // Verify each crypto asset routes to its correct sub-account
            var aaplCash = routingCashBook["AAPL"];
            Assert.AreEqual(100m, aaplCash.Amount);
            Assert.AreEqual(150m, aaplCash.ConversionRate);

            var tslaCash = routingCashBook["TSLA"];
            Assert.AreEqual(50m, tslaCash.Amount);
            Assert.AreEqual(200m, tslaCash.ConversionRate);

            // Standard currencies still route to main
            var usdCash = routingCashBook["USD"];
            Assert.AreEqual(10000m, usdCash.Amount);
        }

        [Test]
        public void RoutingLogic_HandlesEmptySubAccounts()
        {
            var emptySubAccounts = new Dictionary<string, SecurityPortfolioManager>();
            var emptySecurityManagers = new Dictionary<string, SecurityManager>();
            var routingCashBook = new RoutingCashBook(_mainCashBook, emptySubAccounts, emptySecurityManagers);

            // Should fall back to main CashBook for all currencies
            var usdCash = routingCashBook["USD"];
            Assert.AreEqual(10000m, usdCash.Amount);

            var eurCash = routingCashBook["EUR"];
            Assert.AreEqual(5000m, eurCash.Amount);
        }

        /// <summary>
        /// Mock crypto security class that implements IBaseCurrencySymbol for testing
        /// </summary>
        private class MockCryptoSecurity : Security, IBaseCurrencySymbol
        {
            public Cash BaseCurrency { get; private set; }

            public MockCryptoSecurity(
                Symbol symbol,
                SecurityExchangeHours exchangeHours,
                Cash quoteCurrency,
                Cash baseCurrency,
                SymbolProperties symbolProperties,
                ICurrencyConverter currencyConverter,
                IRegisteredSecurityDataTypesProvider registeredTypes,
                SecurityCache cache)
                : base(symbol,
                    quoteCurrency,
                    symbolProperties,
                    new SecurityExchange(exchangeHours),
                    cache,
                    new SecurityPortfolioModel(),
                    new ImmediateFillModel(),
                    new ConstantFeeModel(0),
                    new NullSlippageModel(),
                    new ImmediateSettlementModel(),
                    new BaseVolatilityModel(),
                    new SecurityMarginModel(),
                    new SecurityDataFilter(),
                    new SecurityPriceVariationModel(),
                    currencyConverter,
                    registeredTypes,
                    QuantConnect.Securities.MarginInterestRateModel.Null)
            {
                BaseCurrency = baseCurrency;
            }
        }
    }
}
