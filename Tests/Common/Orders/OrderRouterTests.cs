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
using System.Diagnostics;
using NUnit.Framework;
using QuantConnect.Orders;

namespace QuantConnect.Tests.Common.Orders
{
    [TestFixture]
    public class OrderRouterTests
    {
        private static readonly Symbol SPY = Symbols.SPY; // Market.USA
        private static readonly Symbol BTCUSD = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Kraken);
        private static readonly Symbol ETHUSD = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);
        private static readonly Symbol EURUSD = Symbol.Create("EURUSD", SecurityType.Forex, Market.FXCM);
        private static readonly Symbol AAPL = Symbol.Create("AAPL", SecurityType.Equity, Market.USA);

        #region SimpleOrderRouter Tests

        [Test]
        public void SimpleOrderRouter_RoutesAllOrdersToDefaultAccount()
        {
            // Arrange
            var router = new SimpleOrderRouter("DefaultAccount");
            var order1 = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var order2 = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var order3 = new MarketOrder(EURUSD, 1000, DateTime.UtcNow);

            // Act
            var route1 = router.Route(order1);
            var route2 = router.Route(order2);
            var route3 = router.Route(order3);

            // Assert - All orders should route to the same account
            Assert.AreEqual("DefaultAccount", route1);
            Assert.AreEqual("DefaultAccount", route2);
            Assert.AreEqual("DefaultAccount", route3);
        }

        [Test]
        public void SimpleOrderRouter_ValidatesSuccessfullyWithValidAccountName()
        {
            // Arrange
            var router = new SimpleOrderRouter("ValidAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsTrue(isValid);
        }

        [Test]
        public void SimpleOrderRouter_ThrowsArgumentNullExceptionForNullAccountName()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new SimpleOrderRouter(null));
        }

        [Test]
        public void SimpleOrderRouter_ValidatesFailsForEmptyAccountName()
        {
            // Arrange - Note: Constructor accepts empty string, but Validate() will fail
            var router = new SimpleOrderRouter("");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsFalse(isValid);
        }

        [Test]
        public void SimpleOrderRouter_HandlesNullOrder()
        {
            // Arrange
            var router = new SimpleOrderRouter("DefaultAccount");

            // Act - SimpleOrderRouter doesn't access order properties, so it doesn't throw
            var result = router.Route(null);

            // Assert - Should return the default account even for null order
            Assert.AreEqual("DefaultAccount", result);
        }

        #endregion

        #region MarketBasedRouter Tests

        [Test]
        public void MarketBasedRouter_RoutesOrdersBasedOnMarket()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" },
                { Market.Kraken, "Kraken_Account" },
                { Market.Coinbase, "Coinbase_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            var spyOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var btcOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var ethOrder = new MarketOrder(ETHUSD, 1, DateTime.UtcNow);

            // Act
            var spyRoute = router.Route(spyOrder);
            var btcRoute = router.Route(btcOrder);
            var ethRoute = router.Route(ethOrder);

            // Assert
            Assert.AreEqual("IBKR_Account", spyRoute);
            Assert.AreEqual("Kraken_Account", btcRoute);
            Assert.AreEqual("Coinbase_Account", ethRoute);
        }

        [Test]
        public void MarketBasedRouter_UsesDefaultAccountForUnknownMarket()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            var forexOrder = new MarketOrder(EURUSD, 1000, DateTime.UtcNow);

            // Act
            var route = router.Route(forexOrder);

            // Assert - FXCM market is not mapped, should use default
            Assert.AreEqual("DefaultAccount", route);
        }

        [Test]
        public void MarketBasedRouter_IsCaseInsensitive()
        {
            // Arrange - Test with different case variations
            var marketMappings = new Dictionary<string, string>
            {
                { "USA", "IBKR_Account" },
                { "kraken", "Kraken_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            // Create symbols with different market case
            var usaSymbol = Symbol.Create("MSFT", SecurityType.Equity, "usa");
            var krakenSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, "KRAKEN");

            var usaOrder = new MarketOrder(usaSymbol, 100, DateTime.UtcNow);
            var krakenOrder = new MarketOrder(krakenSymbol, 1, DateTime.UtcNow);

            // Act
            var usaRoute = router.Route(usaOrder);
            var krakenRoute = router.Route(krakenOrder);

            // Assert - Should match regardless of case
            Assert.AreEqual("IBKR_Account", usaRoute);
            Assert.AreEqual("Kraken_Account", krakenRoute);
        }

        [Test]
        public void MarketBasedRouter_ValidatesSuccessfullyWithValidDefaultAccount()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsTrue(isValid);
        }

        [Test]
        public void MarketBasedRouter_ThrowsArgumentNullExceptionForNullDefaultAccount()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" }
            };

            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new MarketBasedRouter(marketMappings, null));
        }

        [Test]
        public void MarketBasedRouter_AcceptsNullMappings()
        {
            // Arrange & Act - Should not throw, will use default for all
            var router = new MarketBasedRouter(null, "DefaultAccount");
            var order = new MarketOrder(SPY, 100, DateTime.UtcNow);

            // Assert
            Assert.AreEqual("DefaultAccount", router.Route(order));
        }

        [Test]
        public void MarketBasedRouter_AcceptsEmptyMappings()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>();
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");
            var order = new MarketOrder(SPY, 100, DateTime.UtcNow);

            // Act
            var route = router.Route(order);

            // Assert - Should use default account for all orders
            Assert.AreEqual("DefaultAccount", route);
        }

        [Test]
        public void MarketBasedRouter_HandlesNullOrder()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            // Act & Assert - Should throw NullReferenceException when accessing null order
            Assert.Throws<NullReferenceException>(() => router.Route(null));
        }

        #endregion

        #region SecurityTypeRouter Tests

        [Test]
        public void SecurityTypeRouter_RoutesOrdersBasedOnSecurityType()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" },
                { SecurityType.Crypto, "Crypto_Account" },
                { SecurityType.Forex, "Forex_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            var equityOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var cryptoOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var forexOrder = new MarketOrder(EURUSD, 1000, DateTime.UtcNow);

            // Act
            var equityRoute = router.Route(equityOrder);
            var cryptoRoute = router.Route(cryptoOrder);
            var forexRoute = router.Route(forexOrder);

            // Assert
            Assert.AreEqual("Equity_Account", equityRoute);
            Assert.AreEqual("Crypto_Account", cryptoRoute);
            Assert.AreEqual("Forex_Account", forexRoute);
        }

        [Test]
        public void SecurityTypeRouter_UsesDefaultAccountForUnmappedSecurityType()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            var cryptoOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);

            // Act
            var route = router.Route(cryptoOrder);

            // Assert - Crypto is not mapped, should use default
            Assert.AreEqual("DefaultAccount", route);
        }

        [Test]
        public void SecurityTypeRouter_ValidatesSuccessfullyWithValidConfiguration()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsTrue(isValid);
        }

        [Test]
        public void SecurityTypeRouter_ValidatesFailsWithEmptyMappings()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>();
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert - Validation should fail with no mappings
            Assert.IsFalse(isValid);
        }

        [Test]
        public void SecurityTypeRouter_ValidatesFailsWithNullDefaultAccount()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" }
            };

            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new SecurityTypeRouter(typeMappings, null));
        }

        [Test]
        public void SecurityTypeRouter_ThrowsArgumentNullExceptionForNullMappings()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new SecurityTypeRouter(null, "DefaultAccount"));
        }

        [Test]
        public void SecurityTypeRouter_HandlesNullOrder()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            // Act & Assert - Should throw NullReferenceException when accessing null order
            Assert.Throws<NullReferenceException>(() => router.Route(null));
        }

        #endregion

        #region SymbolBasedRouter Tests

        [Test]
        public void SymbolBasedRouter_RoutesOrdersBasedOnSymbol()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" },
                { BTCUSD, "BTC_Account" },
                { AAPL, "AAPL_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            var spyOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var btcOrder = new MarketOrder(BTCUSD, 1, DateTime.UtcNow);
            var aaplOrder = new MarketOrder(AAPL, 50, DateTime.UtcNow);

            // Act
            var spyRoute = router.Route(spyOrder);
            var btcRoute = router.Route(btcOrder);
            var aaplRoute = router.Route(aaplOrder);

            // Assert
            Assert.AreEqual("SPY_Account", spyRoute);
            Assert.AreEqual("BTC_Account", btcRoute);
            Assert.AreEqual("AAPL_Account", aaplRoute);
        }

        [Test]
        public void SymbolBasedRouter_UsesDefaultAccountForUnmappedSymbol()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            var unmappedSymbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA);
            var tslaOrder = new MarketOrder(unmappedSymbol, 10, DateTime.UtcNow);

            // Act
            var route = router.Route(tslaOrder);

            // Assert - TSLA is not mapped, should use default
            Assert.AreEqual("DefaultAccount", route);
        }

        [Test]
        public void SymbolBasedRouter_ValidatesSuccessfullyWithValidConfiguration()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert
            Assert.IsTrue(isValid);
        }

        [Test]
        public void SymbolBasedRouter_ValidatesFailsWithEmptyMappings()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>();
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            // Act
            var isValid = router.Validate();

            // Assert - Validation should fail with no mappings
            Assert.IsFalse(isValid);
        }

        [Test]
        public void SymbolBasedRouter_ThrowsArgumentNullExceptionForNullMappings()
        {
            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new SymbolBasedRouter(null, "DefaultAccount"));
        }

        [Test]
        public void SymbolBasedRouter_ThrowsArgumentNullExceptionForNullDefaultAccount()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" }
            };

            // Act & Assert
            Assert.Throws<ArgumentNullException>(() => new SymbolBasedRouter(symbolMappings, null));
        }

        [Test]
        public void SymbolBasedRouter_HandlesNullOrder()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            // Act & Assert - Should throw NullReferenceException when accessing null order
            Assert.Throws<NullReferenceException>(() => router.Route(null));
        }

        #endregion

        #region Performance Tests

        [Test]
        public void SimpleOrderRouter_PerformanceTest_10000Orders()
        {
            // Arrange
            var router = new SimpleOrderRouter("DefaultAccount");
            var orders = new List<Order>();

            // Create 10,000 orders
            for (int i = 0; i < 10000; i++)
            {
                orders.Add(new MarketOrder(SPY, 100, DateTime.UtcNow));
            }

            // Act
            var stopwatch = Stopwatch.StartNew();
            foreach (var order in orders)
            {
                router.Route(order);
            }
            stopwatch.Stop();

            // Assert - Should complete in under 100ms
            Assert.Less(stopwatch.ElapsedMilliseconds, 100,
                $"Routing 10,000 orders took {stopwatch.ElapsedMilliseconds}ms, expected < 100ms");
        }

        [Test]
        public void MarketBasedRouter_PerformanceTest_10000Orders()
        {
            // Arrange
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" },
                { Market.Kraken, "Kraken_Account" },
                { Market.Coinbase, "Coinbase_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            var orders = new List<Order>();
            var symbols = new[] { SPY, BTCUSD, ETHUSD, AAPL };

            // Create 10,000 orders with varied markets
            for (int i = 0; i < 10000; i++)
            {
                orders.Add(new MarketOrder(symbols[i % symbols.Length], 100, DateTime.UtcNow));
            }

            // Act
            var stopwatch = Stopwatch.StartNew();
            foreach (var order in orders)
            {
                router.Route(order);
            }
            stopwatch.Stop();

            // Assert - Should complete in under 100ms
            Assert.Less(stopwatch.ElapsedMilliseconds, 100,
                $"Routing 10,000 orders took {stopwatch.ElapsedMilliseconds}ms, expected < 100ms");
        }

        [Test]
        public void SecurityTypeRouter_PerformanceTest_10000Orders()
        {
            // Arrange
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" },
                { SecurityType.Crypto, "Crypto_Account" },
                { SecurityType.Forex, "Forex_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            var orders = new List<Order>();
            var symbols = new[] { SPY, BTCUSD, EURUSD, AAPL };

            // Create 10,000 orders with varied security types
            for (int i = 0; i < 10000; i++)
            {
                orders.Add(new MarketOrder(symbols[i % symbols.Length], 100, DateTime.UtcNow));
            }

            // Act
            var stopwatch = Stopwatch.StartNew();
            foreach (var order in orders)
            {
                router.Route(order);
            }
            stopwatch.Stop();

            // Assert - Should complete in under 100ms
            Assert.Less(stopwatch.ElapsedMilliseconds, 100,
                $"Routing 10,000 orders took {stopwatch.ElapsedMilliseconds}ms, expected < 100ms");
        }

        [Test]
        public void SymbolBasedRouter_PerformanceTest_10000Orders()
        {
            // Arrange
            var symbolMappings = new Dictionary<Symbol, string>
            {
                { SPY, "SPY_Account" },
                { BTCUSD, "BTC_Account" },
                { AAPL, "AAPL_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            var orders = new List<Order>();
            var symbols = new[] { SPY, BTCUSD, AAPL };

            // Create 10,000 orders with varied symbols
            for (int i = 0; i < 10000; i++)
            {
                orders.Add(new MarketOrder(symbols[i % symbols.Length], 100, DateTime.UtcNow));
            }

            // Act
            var stopwatch = Stopwatch.StartNew();
            foreach (var order in orders)
            {
                router.Route(order);
            }
            stopwatch.Stop();

            // Assert - Should complete in under 100ms
            Assert.Less(stopwatch.ElapsedMilliseconds, 100,
                $"Routing 10,000 orders took {stopwatch.ElapsedMilliseconds}ms, expected < 100ms");
        }

        #endregion

        #region Edge Cases and Complex Scenarios

        [Test]
        public void MarketBasedRouter_HandlesMultipleMappingsForSameAccount()
        {
            // Arrange - Multiple markets can map to the same account
            var marketMappings = new Dictionary<string, string>
            {
                { Market.USA, "Primary_Account" },
                { Market.Kraken, "Primary_Account" },
                { Market.Coinbase, "Primary_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            var usaSymbol = Symbol.Create("MSFT", SecurityType.Equity, Market.USA);
            var krakenSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Kraken);
            var coinbaseSymbol = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);

            var order1 = new MarketOrder(usaSymbol, 100, DateTime.UtcNow);
            var order2 = new MarketOrder(krakenSymbol, 1, DateTime.UtcNow);
            var order3 = new MarketOrder(coinbaseSymbol, 1, DateTime.UtcNow);

            // Act
            var route1 = router.Route(order1);
            var route2 = router.Route(order2);
            var route3 = router.Route(order3);

            // Assert - All should route to the same account
            Assert.AreEqual("Primary_Account", route1);
            Assert.AreEqual("Primary_Account", route2);
            Assert.AreEqual("Primary_Account", route3);
        }

        [Test]
        public void SecurityTypeRouter_HandlesAllSecurityTypes()
        {
            // Arrange - Test with multiple security types
            var typeMappings = new Dictionary<SecurityType, string>
            {
                { SecurityType.Equity, "Equity_Account" },
                { SecurityType.Crypto, "Crypto_Account" },
                { SecurityType.Forex, "Forex_Account" },
                { SecurityType.Option, "Option_Account" },
                { SecurityType.Future, "Future_Account" }
            };
            var router = new SecurityTypeRouter(typeMappings, "DefaultAccount");

            var equitySymbol = Symbol.Create("SPY", SecurityType.Equity, Market.USA);
            var cryptoSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Kraken);
            var forexSymbol = Symbol.Create("EURUSD", SecurityType.Forex, Market.FXCM);
            var futureSymbol = Symbol.CreateFuture("ES", Market.CME, new DateTime(2024, 12, 31));

            var order1 = new MarketOrder(equitySymbol, 100, DateTime.UtcNow);
            var order2 = new MarketOrder(cryptoSymbol, 1, DateTime.UtcNow);
            var order3 = new MarketOrder(forexSymbol, 1000, DateTime.UtcNow);
            var order4 = new MarketOrder(futureSymbol, 1, DateTime.UtcNow);

            // Act
            var route1 = router.Route(order1);
            var route2 = router.Route(order2);
            var route3 = router.Route(order3);
            var route4 = router.Route(order4);

            // Assert
            Assert.AreEqual("Equity_Account", route1);
            Assert.AreEqual("Crypto_Account", route2);
            Assert.AreEqual("Forex_Account", route3);
            Assert.AreEqual("Future_Account", route4);
        }

        [Test]
        public void AllRouters_HandleDifferentOrderTypes()
        {
            // Arrange - Test that routers work with different order types, not just MarketOrder
            var router = new SimpleOrderRouter("TestAccount");

            var marketOrder = new MarketOrder(SPY, 100, DateTime.UtcNow);
            var limitOrder = new LimitOrder(SPY, 100, 450m, DateTime.UtcNow);
            var stopOrder = new StopMarketOrder(SPY, 100, 440m, DateTime.UtcNow);

            // Act
            var route1 = router.Route(marketOrder);
            var route2 = router.Route(limitOrder);
            var route3 = router.Route(stopOrder);

            // Assert - All order types should route the same way
            Assert.AreEqual("TestAccount", route1);
            Assert.AreEqual("TestAccount", route2);
            Assert.AreEqual("TestAccount", route3);
        }

        [Test]
        public void SymbolBasedRouter_DistinguishesBetweenDifferentSymbolsWithSameTicker()
        {
            // Arrange - Two symbols with same ticker but different markets
            var btcKraken = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Kraken);
            var btcCoinbase = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

            var symbolMappings = new Dictionary<Symbol, string>
            {
                { btcKraken, "Kraken_Account" },
                { btcCoinbase, "Coinbase_Account" }
            };
            var router = new SymbolBasedRouter(symbolMappings, "DefaultAccount");

            var order1 = new MarketOrder(btcKraken, 1, DateTime.UtcNow);
            var order2 = new MarketOrder(btcCoinbase, 1, DateTime.UtcNow);

            // Act
            var route1 = router.Route(order1);
            var route2 = router.Route(order2);

            // Assert - Should route to different accounts based on full symbol identity
            Assert.AreEqual("Kraken_Account", route1);
            Assert.AreEqual("Coinbase_Account", route2);
        }

        [Test]
        public void MarketBasedRouter_HandlesWhitespaceInMarketNames()
        {
            // Arrange - Test that whitespace in mapping keys prevents matching
            // Note: The Dictionary constructor doesn't trim keys, so " USA " != "usa"
            var marketMappings = new Dictionary<string, string>
            {
                { " USA ", "IBKR_Account" },
                { "Kraken", "Kraken_Account" }
            };
            var router = new MarketBasedRouter(marketMappings, "DefaultAccount");

            // Symbol market is "usa" without whitespace
            var usaSymbol = Symbol.Create("MSFT", SecurityType.Equity, Market.USA);
            var order = new MarketOrder(usaSymbol, 100, DateTime.UtcNow);

            // Act
            var route = router.Route(order);

            // Assert - Should use default account because " USA " doesn't match "usa"
            Assert.AreEqual("DefaultAccount", route);

            // Now test with proper mapping (no whitespace)
            var marketMappings2 = new Dictionary<string, string>
            {
                { Market.USA, "IBKR_Account" }
            };
            var router2 = new MarketBasedRouter(marketMappings2, "DefaultAccount");
            var route2 = router2.Route(order);

            // Assert - Should match correctly now
            Assert.AreEqual("IBKR_Account", route2);
        }

        #endregion
    }
}
