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
using QuantConnect.Indicators;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Securities.MultiAccount;
using QuantConnect.Tests.Engine;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Common.Securities.MultiAccount
{
    [TestFixture]
    public class MultiSecurityPortfolioManagerTests
    {
        private static readonly SecurityExchangeHours SecurityExchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
        private static readonly Symbol SPY = Symbols.SPY;
        private static readonly Symbol BTCUSD = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

        [Test]
        public void InitializesMultipleAccounts()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 100000m },
                { "AccountB", 200000m }
            };

            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            // Act
            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Assert
            Assert.AreEqual(2, portfolio.SubAccounts.Count);
            Assert.IsTrue(portfolio.SubAccounts.ContainsKey("AccountA"));
            Assert.IsTrue(portfolio.SubAccounts.ContainsKey("AccountB"));

            var accountA = portfolio.GetAccount("AccountA");
            var accountB = portfolio.GetAccount("AccountB");

            Assert.AreEqual(100000m, accountA.Cash);
            Assert.AreEqual(200000m, accountB.Cash);
            Assert.AreEqual(300000m, portfolio.Cash);
        }

        [Test]
        public void ThrowsOnEmptyAccountConfiguration()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>();
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            // Act & Assert
            Assert.Throws<ArgumentException>(() =>
            {
                new MultiSecurityPortfolioManager(
                    accountConfigs,
                    router,
                    securities,
                    transactions,
                    new AlgorithmSettings(),
                    null,
                    TimeKeeper
                );
            });
        }

        [Test]
        public void ThrowsOnNullRouter()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 100000m }
            };
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            // Act & Assert
            Assert.Throws<ArgumentNullException>(() =>
            {
                new MultiSecurityPortfolioManager(
                    accountConfigs,
                    null,
                    securities,
                    transactions,
                    new AlgorithmSettings(),
                    null,
                    TimeKeeper
                );
            });
        }

        [Test]
        public void GetAccountThrowsForNonExistentAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 100000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act & Assert
            Assert.Throws<ArgumentException>(() => portfolio.GetAccount("NonExistentAccount"));
        }

        [Test]
        public void RoutesOrderToCorrectAccountForValidation()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var routerCallCount = 0;
            var routedAccount = "";

            var router = new TestRouter("AccountA", (order) =>
            {
                routerCallCount++;
                routedAccount = "AccountA";
            });

            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Router is called once during initialization for pre-existing SPY
            var initializationCallCount = routerCallCount;

            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };

            // Act
            var result = portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            // Assert - verify router was called once more for buying power validation
            Assert.AreEqual(initializationCallCount + 1, routerCallCount, "Router should be called once more during validation");
            Assert.AreEqual("AccountA", routedAccount, "Order should route to AccountA");
        }

        [Test]
        public void RejectsOrderWithInsufficientBuyingPower()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 1000m }  // Not enough cash for 1000 shares at $100
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            var order = new MarketOrder(SPY, 1000, DateTime.UtcNow) { Id = 1 };

            // Act
            var result = portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            // Assert
            Assert.IsFalse(result.IsSufficient);
        }

        [Test]
        public void ProcessFillsUpdatesCorrectAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            orderProcessor.AddOrder(order);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            var fill = new OrderEvent(
                1,
                SPY,
                DateTime.UtcNow,
                OrderStatus.Filled,
                OrderDirection.Buy,
                100m,
                50,
                OrderFee.Zero
            );

            // Act
            portfolio.ProcessFills(new List<OrderEvent> { fill });

            // Assert
            var accountA = portfolio.GetAccount("AccountA");
            var accountB = portfolio.GetAccount("AccountB");

            Assert.AreEqual(5000m, accountA.Cash);  // 10000 - (50 * 100)
            Assert.AreEqual(20000m, accountB.Cash); // Unchanged
        }

        [Test]
        public void AggregatesTotalPortfolioValueCorrectly()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var totalValue = portfolio.TotalPortfolioValue;

            // Assert
            Assert.AreEqual(30000m, totalValue);
        }

        [Test]
        public void GetAccountValuesReturnsAllAccounts()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var accountValues = portfolio.GetAccountValues();

            // Assert
            Assert.AreEqual(2, accountValues.Count);
            Assert.AreEqual(10000m, accountValues["AccountA"]);
            Assert.AreEqual(20000m, accountValues["AccountB"]);
        }

        [Test]
        public void GetAccountsSummaryGeneratesCorrectOutput()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var summary = portfolio.GetAccountsSummary();

            // Assert
            Assert.IsNotNull(summary);
            Assert.IsTrue(summary.Contains("AccountA"));
            Assert.IsTrue(summary.Contains("AccountB"));
            Assert.IsTrue(summary.Contains("10,000.00"));
            Assert.IsTrue(summary.Contains("20,000.00"));
            Assert.IsTrue(summary.Contains("30,000.00"));
        }

        [Test]
        public void SymbolBasedRouterRoutesToCorrectAccount()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "EquityAccount" },
                { BTCUSD, "CryptoAccount" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            var spyOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var btcOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var unmappedSymbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA);
            var aaplOrder = new MarketOrder(unmappedSymbol, 50, DateTime.UtcNow);

            // Act
            var spyRoute = router.Route(spyOrder);
            var btcRoute = router.Route(btcOrder);
            var aaplRoute = router.Route(aaplOrder);

            // Assert
            Assert.AreEqual("EquityAccount", spyRoute);
            Assert.AreEqual("CryptoAccount", btcRoute);
            Assert.AreEqual("DefaultAccount", aaplRoute);
        }

        [Test]
        public void SecurityTypeRouterRoutesToCorrectAccount()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "EquityAccount" },
                { SecurityType.Crypto, "CryptoAccount" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            var spyOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var btcOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var forexSymbol = Symbol.Create("EURUSD", SecurityType.Forex, Market.FXCM);
            var forexOrder = new MarketOrder(forexSymbol, 1000, DateTime.UtcNow);

            // Act
            var spyRoute = router.Route(spyOrder);
            var btcRoute = router.Route(btcOrder);
            var forexRoute = router.Route(forexOrder);

            // Assert
            Assert.AreEqual("EquityAccount", spyRoute);
            Assert.AreEqual("CryptoAccount", btcRoute);
            Assert.AreEqual("DefaultAccount", forexRoute);
        }

        [Test]
        public void SymbolBasedRouterValidationFailsWithEmptyMappings()
        {
            // Arrange
            var router = new SymbolBasedRouter(new Dictionary<Symbol, string>(), "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsFalse(isValid);
        }

        [Test]
        public void SecurityTypeRouterValidationFailsWithEmptyMappings()
        {
            // Arrange
            var router = new SecurityTypeRouter(new Dictionary<SecurityType, string>(), "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsFalse(isValid);
        }

        [Test]
        public void MultipleOrdersAcrossDifferentAccounts()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" },
                { BTCUSD, "AccountB" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountA");

            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);
            AddSecurity(securities, BTCUSD, 50000m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Ensure crypto base currencies are in CashBook
            EnsureCryptoBaseCurrenciesInCashBook(portfolio, securities);

            var spyOrder = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            var btcOrder = new MarketOrder(BTCUSD, 0.1m, DateTime.UtcNow) { Id = 2 };

            // Register orders with order processor
            orderProcessor.AddOrder(spyOrder);
            orderProcessor.AddOrder(btcOrder);

            // Act
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { spyOrder });
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { btcOrder });

            var spyFill = new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled, OrderDirection.Buy, 100m, 50, OrderFee.Zero);
            var btcFill = new OrderEvent(2, BTCUSD, DateTime.UtcNow, OrderStatus.Filled, OrderDirection.Buy, 50000m, 0.1m, OrderFee.Zero);

            portfolio.ProcessFills(new List<OrderEvent> { spyFill, btcFill });

            // Assert
            var accountA = portfolio.GetAccount("AccountA");
            var accountB = portfolio.GetAccount("AccountB");

            Assert.AreEqual(5000m, accountA.Cash);     // 10000 - (50 * 100)
            Assert.AreEqual(15000m, accountB.Cash);    // 20000 - (0.1 * 50000)
        }

        [Test]
        public void ProcessFillsDoesNotDuplicateHoldings()
        {
            // Arrange: Create 2 accounts with different initial cash
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };

            // Use SymbolBasedRouter to explicitly route SPY to AccountA
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountB");

            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act: Execute fills in AccountA
            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            orderProcessor.AddOrder(order);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            var fill = new OrderEvent(
                1,
                SPY,
                DateTime.UtcNow,
                OrderStatus.Filled,
                OrderDirection.Buy,
                100m,
                50,
                OrderFee.Zero
            );

            portfolio.ProcessFills(new List<OrderEvent> { fill });

            // Assert: Verify AccountA's cash is updated correctly
            var accountA = portfolio.GetAccount("AccountA");
            Assert.AreEqual(5000m, accountA.Cash, "AccountA cash should be reduced by 5000");

            // Assert: Verify AccountB's cash remains unchanged (no trades)
            var accountB = portfolio.GetAccount("AccountB");
            Assert.AreEqual(20000m, accountB.Cash, "AccountB cash should be unchanged");

            // Critical: Verify holdings are isolated per account
            // AccountA should have 50 shares (it executed the trade)
            Assert.AreEqual(50, accountA[SPY].Quantity, "AccountA should have 50 shares");

            // AccountB should NOT have SPY in its SecurityManager (SPY was routed to AccountA only)
            Assert.IsFalse(accountB.Securities.ContainsKey(SPY),
                "AccountB should not have SPY - it was routed to AccountA");

            // Main portfolio should show aggregated holdings (50 from AccountA + 0 from AccountB)
            Assert.AreEqual(50, securities[SPY].Holdings.Quantity,
                "Main portfolio holdings should show 50 shares (aggregated from AccountA)");
        }

        [Test]
        public void GetAccountHoldingReturnsCorrectHoldings()
        {
            // Arrange: Create multi-account setup with 2 accounts
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountB");

            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            // Add securities BEFORE creating portfolio (constructor will route them to sub-accounts)
            AddSecurity(securities, SPY, 100m);
            var aaplSymbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA);
            AddSecurity(securities, aaplSymbol, 150m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act: Execute fills in AccountA for SPY
            var orderA = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            orderProcessor.AddOrder(orderA);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { orderA });

            var fillA = new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 100m, 50, OrderFee.Zero);
            portfolio.ProcessFills(new List<OrderEvent> { fillA });

            // Execute fill in AccountB (default) for AAPL with different quantity
            var orderB = new MarketOrder(aaplSymbol, 30, DateTime.UtcNow) { Id = 2 };
            orderProcessor.AddOrder(orderB);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { orderB });

            var fillB = new OrderEvent(2, aaplSymbol, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 150m, 30, OrderFee.Zero);
            portfolio.ProcessFills(new List<OrderEvent> { fillB });

            // Assert: Verify GetAccountHolding returns isolated holdings for each sub-account
            // Note: Each sub-account only contains securities it trades (routed by the router)
            // AccountA has SPY (explicitly mapped), AccountB has AAPL (default route)

            var holdingA_SPY = portfolio.GetAccountHolding("AccountA", SPY);
            var holdingB_AAPL = portfolio.GetAccountHolding("AccountB", aaplSymbol);

            // Sub-account holdings should be isolated - each account only holds what it bought
            Assert.AreEqual(50, holdingA_SPY.Quantity, "AccountA bought 50 shares of SPY");
            Assert.AreEqual(30, holdingB_AAPL.Quantity, "AccountB bought 30 shares of AAPL");

            // Verify AccountB does NOT have SPY in its SecurityManager (would throw KeyNotFoundException)
            var accountB = portfolio.GetAccount("AccountB");
            Assert.IsFalse(accountB.Securities.ContainsKey(SPY), "AccountB should not have SPY");

            // Verify AccountA does NOT have AAPL in its SecurityManager (would throw KeyNotFoundException)
            var accountA = portfolio.GetAccount("AccountA");
            Assert.IsFalse(accountA.Securities.ContainsKey(aaplSymbol), "AccountA should not have AAPL");

            // Main account should show aggregated holdings from all sub-accounts
            var mainHolding_SPY = portfolio.Securities[SPY].Holdings;
            var mainHolding_AAPL = portfolio.Securities[aaplSymbol].Holdings;

            Assert.AreEqual(50, mainHolding_SPY.Quantity, "Main account should aggregate SPY holdings (50 from AccountA)");
            Assert.AreEqual(30, mainHolding_AAPL.Quantity, "Main account should aggregate AAPL holdings (30 from AccountB)");
        }

        [Test]
        public void GetAccountCashReturnsCorrectCashBalance()
        {
            // Arrange: Create accounts with different initial cash amounts
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act: Execute fills that reduce cash in one account
            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            orderProcessor.AddOrder(order);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            var fill = new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 100m, 50, OrderFee.Zero);
            portfolio.ProcessFills(new List<OrderEvent> { fill });

            // Assert: Verify GetAccountCash returns correct reduced amount for AccountA
            Assert.AreEqual(5000m, portfolio.GetAccountCash("AccountA"),
                "AccountA cash should be 5000 after purchase");

            // Assert: Verify GetAccountCash returns unchanged amount for AccountB
            Assert.AreEqual(20000m, portfolio.GetAccountCash("AccountB"),
                "AccountB cash should remain 20000");
        }

        [Test]
        public void GetAccountCashBookReturnsIndependentCashBooks()
        {
            // Arrange: Create multi-account setup
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act: Directly add a currency to AccountA's CashBook to test isolation
            var accountA = portfolio.GetAccount("AccountA");
            accountA.CashBook.Add("EUR", 1000m, 1.1m);

            // Assert: Verify GetAccountCashBook for AccountA shows EUR
            var cashBookA = portfolio.GetAccountCashBook("AccountA");
            Assert.IsTrue(cashBookA.ContainsKey("EUR"), "AccountA CashBook should contain EUR");
            Assert.AreEqual(1000m, cashBookA["EUR"].Amount, "AccountA should have 1000 EUR");

            // Assert: Verify GetAccountCashBook for AccountB does NOT show AccountA's EUR
            var cashBookB = portfolio.GetAccountCashBook("AccountB");
            Assert.IsFalse(cashBookB.ContainsKey("EUR"),
                "AccountB CashBook should not contain AccountA's EUR");

            // Assert: Verify CashBooks are truly independent objects
            Assert.AreNotSame(cashBookA, cashBookB,
                "CashBooks should be independent objects");
        }

        [Test]
        public void ProcessFillsUpdatesCorrectAccountCashBook()
        {
            // Arrange: Create multi-account setup
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            var initialCashA = portfolio.GetAccountCash("AccountA");
            var initialCashB = portfolio.GetAccountCash("AccountB");

            // Act: Execute fills in AccountA
            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };
            orderProcessor.AddOrder(order);
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            var fill = new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 100m, 50, OrderFee.Zero);
            portfolio.ProcessFills(new List<OrderEvent> { fill });

            // Assert: Verify AccountA's USD cash is reduced
            var cashBookA = portfolio.GetAccountCashBook("AccountA");
            Assert.AreEqual(5000m, cashBookA[Currencies.USD].Amount,
                "AccountA USD should be reduced by purchase");

            // Assert: Verify AccountB's CashBook is NOT updated
            var cashBookB = portfolio.GetAccountCashBook("AccountB");
            Assert.AreEqual(20000m, cashBookB[Currencies.USD].Amount,
                "AccountB USD should be unchanged");

            // Assert: Verify CashBooks are independent
            Assert.AreNotSame(cashBookA, cashBookB, "CashBooks should be independent");

            // Assert: Verify aggregated cash reflects only AccountA's change
            var expectedTotalCash = initialCashA - 5000m + initialCashB; // AccountA reduced by 5000
            Assert.AreEqual(expectedTotalCash, portfolio.Cash,
                "Aggregated cash should reflect only AccountA's purchase");
        }

        [Test]
        public void MultipleFillsAcrossDifferentAccountsNoCrossContamination()
        {
            // Arrange: Create 3 accounts to test multiple scenarios
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m },
                { "AccountC", 30000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountC");

            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);
            var aaplSymbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA);
            AddSecurity(securities, aaplSymbol, 150m);
            var msftSymbol = Symbol.Create("MSFT", SecurityType.Equity, Market.USA);
            AddSecurity(securities, msftSymbol, 200m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act: Execute multiple fills routing to different accounts
            // Note: Since symbolMappings only has SPY->AccountA, AAPL and MSFT go to default (AccountC)
            var orders = new List<Order>
            {
                new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 },      // -> AccountA
                new MarketOrder(aaplSymbol, 100, DateTime.UtcNow) { Id = 2 }, // -> AccountC (default)
                new MarketOrder(msftSymbol, 25, DateTime.UtcNow) { Id = 3 } // -> AccountC (default)
            };

            // Register orders with order processor
            foreach (var order in orders)
            {
                orderProcessor.AddOrder(order);
                portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });
            }

            var fills = new List<OrderEvent>
            {
                new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled,
                    OrderDirection.Buy, 100m, 50, OrderFee.Zero),
                new OrderEvent(2, aaplSymbol, DateTime.UtcNow, OrderStatus.Filled,
                    OrderDirection.Buy, 150m, 100, OrderFee.Zero),
                new OrderEvent(3, msftSymbol, DateTime.UtcNow, OrderStatus.Filled,
                    OrderDirection.Buy, 200m, 25, OrderFee.Zero)
            };

            portfolio.ProcessFills(fills);

            // Assert: Verify each account's cash is updated correctly (no cross-contamination)
            Assert.AreEqual(5000m, portfolio.GetAccountCash("AccountA"),
                "AccountA: 10000 - (50 * 100)");
            Assert.AreEqual(20000m, portfolio.GetAccountCash("AccountB"),
                "AccountB: unchanged");
            Assert.AreEqual(10000m, portfolio.GetAccountCash("AccountC"),
                "AccountC: 30000 - (100 * 150) - (25 * 200)");

            // Assert: Verify holdings isolation - each account only has securities it traded
            // AccountA: Only SPY (routed to AccountA)
            Assert.AreEqual(50, portfolio.GetAccountHolding("AccountA", SPY).Quantity,
                "AccountA should have SPY holdings");

            // AccountC: Only AAPL and MSFT (routed to default AccountC)
            Assert.AreEqual(100, portfolio.GetAccountHolding("AccountC", aaplSymbol).Quantity,
                "AccountC should have AAPL holdings");
            Assert.AreEqual(25, portfolio.GetAccountHolding("AccountC", msftSymbol).Quantity,
                "AccountC should have MSFT holdings");

            // AccountB: No securities (no trades routed to AccountB)
            // Note: Cannot call GetAccountHolding for symbols not in the account's SecurityManager

            // Assert: Verify aggregated values are correct
            var expectedTotalCash = 5000m + 20000m + 10000m;
            Assert.AreEqual(expectedTotalCash, portfolio.Cash,
                "Aggregated cash should sum all accounts");
        }

        [Test]
        public void GetAccountHoldingThrowsForNonExistentAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act & Assert: Verify calling GetAccountHolding with non-existent account throws
            Assert.Throws<ArgumentException>(() =>
                portfolio.GetAccountHolding("NonExistent", SPY),
                "Should throw ArgumentException for non-existent account");
        }

        [Test]
        public void GetAccountCashThrowsForNonExistentAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act & Assert: Verify calling GetAccountCash with non-existent account throws
            Assert.Throws<ArgumentException>(() =>
                portfolio.GetAccountCash("NonExistent"),
                "Should throw ArgumentException for non-existent account");
        }

        [Test]
        public void GetAccountCashBookThrowsForNonExistentAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act & Assert: Verify calling GetAccountCashBook with non-existent account throws
            Assert.Throws<ArgumentException>(() =>
                portfolio.GetAccountCashBook("NonExistent"),
                "Should throw ArgumentException for non-existent account");
        }

        [Test]
        public void CashBookPropertyReturnsRoutingCashBook()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var cashBook = portfolio.CashBook;

            // Assert
            Assert.IsNotNull(cashBook);
            Assert.IsInstanceOf<RoutingCashBook>(cashBook,
                "CashBook should return RoutingCashBook instance");
        }

        [Test]
        public void FindAccountForSymbolReturnsCorrectAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" },
                { BTCUSD, "AccountB" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountA");

            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);
            AddSecurity(securities, BTCUSD, 50000m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var spyAccount = portfolio.FindAccountForSymbol(SPY);
            var btcAccount = portfolio.FindAccountForSymbol(BTCUSD);
            var unmappedSymbol = Symbol.Create("AAPL", SecurityType.Equity, Market.USA);
            var unmappedAccount = portfolio.FindAccountForSymbol(unmappedSymbol);

            // Assert
            Assert.AreEqual("AccountA", spyAccount, "SPY should be in AccountA");
            Assert.AreEqual("AccountB", btcAccount, "BTCUSD should be in AccountB");
            Assert.IsNull(unmappedAccount, "Unmapped symbol should return null");
        }

        [Test]
        public void GetSubAccountSecuritiesSummaryReturnsCorrectInformation()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m },
                { "AccountB", 20000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" },
                { BTCUSD, "AccountB" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountA");

            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);
            AddSecurity(securities, BTCUSD, 50000m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var summary = portfolio.GetSubAccountSecuritiesSummary();

            // Assert
            Assert.IsNotNull(summary);
            Assert.IsTrue(summary.Contains("AccountA"), "Summary should contain AccountA");
            Assert.IsTrue(summary.Contains("AccountB"), "Summary should contain AccountB");
            Assert.IsTrue(summary.Contains("SPY") || summary.Contains("Security Count"),
                "Summary should contain security information");
        }

        [Test]
        public void TotalMarginUsedAggregatesAllAccounts()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 100000m },
                { "AccountB", 200000m }
            };

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "AccountA" },
                { BTCUSD, "AccountB" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "AccountA");

            var securities = CreateSecurityManager();
            var transactions = CreateTransactionManagerWithOrderProcessor(securities, out var orderProcessor);

            AddSecurity(securities, SPY, 100m);
            AddSecurity(securities, BTCUSD, 50000m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Execute fills to generate margin usage
            var spyOrder = new MarketOrder(SPY, 500, DateTime.UtcNow) { Id = 1 };
            var btcOrder = new MarketOrder(BTCUSD, 1m, DateTime.UtcNow) { Id = 2 };

            // Register orders with order processor
            orderProcessor.AddOrder(spyOrder);
            orderProcessor.AddOrder(btcOrder);

            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { spyOrder });
            portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { btcOrder });

            var spyFill = new OrderEvent(1, SPY, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 100m, 500, OrderFee.Zero);
            var btcFill = new OrderEvent(2, BTCUSD, DateTime.UtcNow, OrderStatus.Filled,
                OrderDirection.Buy, 50000m, 1m, OrderFee.Zero);

            portfolio.ProcessFills(new List<OrderEvent> { spyFill, btcFill });

            // Act
            var totalMarginUsed = portfolio.TotalMarginUsed;
            var accountAMargin = portfolio.GetAccount("AccountA").TotalMarginUsed;
            var accountBMargin = portfolio.GetAccount("AccountB").TotalMarginUsed;

            // Assert
            Assert.AreEqual(accountAMargin + accountBMargin, totalMarginUsed,
                "Total margin should equal sum of all sub-accounts");
            Assert.Greater(totalMarginUsed, 0m, "Total margin should be positive after fills");
        }

        [Test]
        public void HasSufficientBuyingPowerReturnsFalseForUnknownAccount()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };

            // Router that returns non-existent account
            var router = new TestRouter("NonExistentAccount");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            AddSecurity(securities, SPY, 100m);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            var order = new MarketOrder(SPY, 50, DateTime.UtcNow) { Id = 1 };

            // Act
            var result = portfolio.HasSufficientBuyingPowerForOrder(new List<Order> { order });

            // Assert
            Assert.IsFalse(result.IsSufficient, "Should return false for unknown account");
            Assert.IsTrue(result.Reason.Contains("not found"),
                "Reason should indicate account not found");
        }

        [Test]
        public void HasSufficientBuyingPowerHandlesEmptyOrderList()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            // Act
            var resultNull = portfolio.HasSufficientBuyingPowerForOrder(null);
            var resultEmpty = portfolio.HasSufficientBuyingPowerForOrder(new List<Order>());

            // Assert
            Assert.IsTrue(resultNull.IsSufficient, "Null order list should return true");
            Assert.IsTrue(resultEmpty.IsSufficient, "Empty order list should return true");
        }

        [Test]
        public void ThrowsOnNullTimeKeeper()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 100000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            // Act & Assert
            Assert.Throws<ArgumentNullException>(() =>
            {
                new MultiSecurityPortfolioManager(
                    accountConfigs,
                    router,
                    securities,
                    transactions,
                    new AlgorithmSettings(),
                    null,
                    null  // null TimeKeeper
                );
            });
        }

        [Test]
        public void ProcessFillsHandlesNullAndEmptyFills()
        {
            // Arrange
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "AccountA", 10000m }
            };
            var router = new TestRouter("AccountA");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper
            );

            var initialCash = portfolio.GetAccountCash("AccountA");

            // Act
            portfolio.ProcessFills(null);
            portfolio.ProcessFills(new List<OrderEvent>());

            // Assert
            Assert.AreEqual(initialCash, portfolio.GetAccountCash("AccountA"),
                "Cash should remain unchanged after processing null/empty fills");
        }

        [Test]
        public void SingleGateAccountWithUsdtCurrency()
        {
            // Arrange: Create single Gate account with USDT as base currency
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "Gate", 20000m }
            };

            var accountCurrencies = new Dictionary<string, string>
            {
                { "Gate", "USDT" }  // Gate uses USDT as base currency
            };

            var router = new TestRouter("Gate");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper,
                accountCurrencies  // Pass currency mappings
            );

            // Verify Gate account has correct currency
            var gateAccount = portfolio.GetAccount("Gate");
            Assert.AreEqual("USDT", gateAccount.CashBook.AccountCurrency,
                "Gate account should use USDT as base currency");
            Assert.AreEqual(20000m, gateAccount.CashBook["USDT"].Amount,
                "Gate account should have 20,000 USDT");

            // Act: Sync currencies to main account
            var coordinator = new CurrencyConversionCoordinator();
            coordinator.SyncConversionsToMain(portfolio);

            // Assert: Main account should aggregate currencies from sub-accounts
            var mainCashBook = ((SecurityPortfolioManager)portfolio).CashBook;

            Assert.IsTrue(mainCashBook.ContainsKey("USDT"),
                "Main account should have USDT from Gate account");
            Assert.AreEqual(20000m, mainCashBook["USDT"].Amount,
                "Main account USDT should equal Gate's 20,000 USDT");

            // Main account should NOT have USD (or should have 0 USD after sync clears it)
            if (mainCashBook.ContainsKey("USD"))
            {
                Assert.AreEqual(0m, mainCashBook["USD"].Amount,
                    "Main account USD should be 0 when only Gate (USDT) exists");
            }

            // Verify USDT has proper currency conversion to USD (1:1 for stablecoins)
            Assert.IsNotNull(mainCashBook["USDT"].CurrencyConversion,
                "USDT should have currency conversion");
            Assert.AreEqual("USD", mainCashBook["USDT"].CurrencyConversion.DestinationCurrency,
                "USDT should convert to USD");
        }

        [Test]
        public void MixedIbkrAndGateAccountsWithDifferentCurrencies()
        {
            // Arrange: Create IBKR (USD) and Gate (USDT) accounts
            var accountConfigs = new Dictionary<string, decimal>
            {
                { "IBKR", 50000m },  // 50,000 USD
                { "Gate", 20000m }   // 20,000 USDT
            };

            var accountCurrencies = new Dictionary<string, string>
            {
                { "IBKR", "USD" },   // IBKR uses USD
                { "Gate", "USDT" }   // Gate uses USDT
            };

            var router = new TestRouter("IBKR");
            var securities = CreateSecurityManager();
            var transactions = new SecurityTransactionManager(null, securities);

            var portfolio = new MultiSecurityPortfolioManager(
                accountConfigs,
                router,
                securities,
                transactions,
                new AlgorithmSettings(),
                null,
                TimeKeeper,
                accountCurrencies
            );

            // Verify each account has correct currency and amount
            var ibkrAccount = portfolio.GetAccount("IBKR");
            var gateAccount = portfolio.GetAccount("Gate");

            Assert.AreEqual("USD", ibkrAccount.CashBook.AccountCurrency,
                "IBKR should use USD");
            Assert.AreEqual(50000m, ibkrAccount.CashBook["USD"].Amount,
                "IBKR should have 50,000 USD");

            Assert.AreEqual("USDT", gateAccount.CashBook.AccountCurrency,
                "Gate should use USDT");
            Assert.AreEqual(20000m, gateAccount.CashBook["USDT"].Amount,
                "Gate should have 20,000 USDT");

            // Act: Sync currencies to main account
            var coordinator = new CurrencyConversionCoordinator();
            coordinator.SyncConversionsToMain(portfolio);

            // Assert: Main account should aggregate both currencies
            var mainCashBook = ((SecurityPortfolioManager)portfolio).CashBook;

            Assert.IsTrue(mainCashBook.ContainsKey("USD"),
                "Main account should have USD from IBKR");
            Assert.IsTrue(mainCashBook.ContainsKey("USDT"),
                "Main account should have USDT from Gate");

            Assert.AreEqual(50000m, mainCashBook["USD"].Amount,
                "Main account should have 50,000 USD from IBKR");
            Assert.AreEqual(20000m, mainCashBook["USDT"].Amount,
                "Main account should have 20,000 USDT from Gate");

            // Verify USDT has proper conversion to USD (1:1 Identity conversion)
            Assert.IsNotNull(mainCashBook["USDT"].CurrencyConversion,
                "USDT should have currency conversion");
            Assert.AreEqual("USD", mainCashBook["USDT"].CurrencyConversion.DestinationCurrency,
                "USDT should convert to USD");
            Assert.AreEqual(1m, mainCashBook["USDT"].ConversionRate,
                "USDT should have 1:1 conversion rate to USD");
        }

        // Helper Methods

        private static SecurityManager CreateSecurityManager()
        {
            return new SecurityManager(TimeKeeper);
        }

        private static SecurityTransactionManager CreateTransactionManagerWithOrderProcessor(SecurityManager securities, out FakeOrderProcessor orderProcessor)
        {
            var transactions = new SecurityTransactionManager(null, securities);
            orderProcessor = new FakeOrderProcessor();
            orderProcessor.TransactionManager = transactions;
            transactions.SetOrderProcessor(orderProcessor);
            return transactions;
        }

        private static void EnsureCryptoBaseCurrenciesInCashBook(MultiSecurityPortfolioManager portfolio, SecurityManager securities)
        {
            // For each crypto security, ensure its base currency is in the account's CashBook
            foreach (var kvp in securities)
            {
                var security = kvp.Value;
                if (security is QuantConnect.Securities.Crypto.Crypto crypto)
                {
                    // Find which account this crypto belongs to
                    var tempOrder = new MarketOrder(security.Symbol, 0, DateTime.UtcNow);
                    var accountName = portfolio.FindAccountForSymbol(security.Symbol);

                    if (!string.IsNullOrEmpty(accountName))
                    {
                        var account = portfolio.GetAccount(accountName);
                        var baseCurrency = crypto.BaseCurrency.Symbol;

                        if (!account.CashBook.ContainsKey(baseCurrency))
                        {
                            account.CashBook.Add(baseCurrency, new Cash(baseCurrency, 0, 0));
                        }
                    }
                }
            }
        }

        private static void AddSecurity(SecurityManager securities, Symbol symbol, decimal price)
        {
            var subscriptions = new SubscriptionManager(TimeKeeper);
            subscriptions.SetDataManager(new DataManagerStub(TimeKeeper));

            Security security;
            var config = subscriptions.Add(symbol, Resolution.Minute, TimeZones.NewYork, TimeZones.NewYork);

            // Create appropriate security type based on symbol
            if (symbol.SecurityType == SecurityType.Crypto)
            {
                // Use the correct method to decompose currency pair
                var symbolProperties = SymbolProperties.GetDefault(Currencies.USD);
                QuantConnect.Securities.Crypto.Crypto.DecomposeCurrencyPair(symbol, symbolProperties, out var baseCurrency, out var quoteCurrency);

                var baseCash = new Cash(baseCurrency, 0, 0);
                var quoteCash = new Cash(quoteCurrency, 0, 1m);

                security = new QuantConnect.Securities.Crypto.Crypto(
                    symbol,
                    SecurityExchangeHours,
                    quoteCash,
                    baseCash,
                    symbolProperties,
                    ErrorCurrencyConverter.Instance,
                    RegisteredSecurityDataTypesProvider.Null,
                    new SecurityCache()
                );
            }
            else
            {
                security = new Security(
                    SecurityExchangeHours,
                    config,
                    new Cash(Currencies.USD, 0, 1m),
                    SymbolProperties.GetDefault(Currencies.USD),
                    ErrorCurrencyConverter.Instance,
                    RegisteredSecurityDataTypesProvider.Null,
                    new SecurityCache()
                );
            }

            security.SetMarketPrice(new IndicatorDataPoint(symbol, DateTime.UtcNow, price));
            securities.Add(symbol, security);
        }

        private static TimeKeeper TimeKeeper
        {
            get { return new TimeKeeper(DateTime.Now, new[] { TimeZones.NewYork }); }
        }

        // Test Router Implementation
        private class TestRouter : IOrderRouter
        {
            private readonly string _targetAccount;
            private readonly Action<Order> _onRoute;

            public TestRouter(string targetAccount, Action<Order> onRoute = null)
            {
                _targetAccount = targetAccount;
                _onRoute = onRoute;
            }

            public string Route(Order order)
            {
                _onRoute?.Invoke(order);
                return _targetAccount;
            }

            public bool Validate()
            {
                return !string.IsNullOrEmpty(_targetAccount);
            }
        }
    }
}
