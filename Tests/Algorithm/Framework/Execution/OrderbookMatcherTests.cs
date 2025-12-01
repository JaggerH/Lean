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
using QuantConnect.Algorithm.Framework.Execution;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;

namespace QuantConnect.Tests.Algorithm.Framework.Execution
{
    /// <summary>
    /// Tests for OrderbookMatcher - Only tests public MatchPair API
    /// </summary>
    [TestFixture]
    public class OrderbookMatcherTests
    {
        private AQCAlgorithm _algorithm;
        private Symbol _btcSymbol;
        private Symbol _ethSymbol;

        [SetUp]
        public void Setup()
        {
            _algorithm = new AQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(new DataManagerStub(_algorithm));

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _ethSymbol = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);

            // Add securities
            _algorithm.AddSecurity(_btcSymbol);
            _algorithm.AddSecurity(_ethSymbol);
        }

        #region AutoDetect Strategy Tests

        [Test]
        public void MatchPair_AutoDetect_ChoosesDualOrderbookWhenBothAvailable()
        {
            // Arrange
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (50000m, 1m) },
                new[] { (50100m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            var ethOrderbook = CreateOrderbook(_ethSymbol,
                new[] { (3000m, 10m) },
                new[] { (3010m, 10m) });
            _algorithm.Securities[_ethSymbol].Cache.AddData(ethOrderbook);

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.AutoDetect);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.DualOrderbook, result.UsedStrategy);
        }

        [Test]
        public void MatchPair_AutoDetect_FallsBackToSingleOrderbook()
        {
            // Arrange - Only BTC has orderbook
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (50000m, 1m) },
                new[] { (50100m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            SetupPrices(_ethSymbol, 3000m, 3010m);

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.AutoDetect);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.SingleOrderbook, result.UsedStrategy);
        }

        [Test]
        public void MatchPair_AutoDetect_FallsBackToBestPrices()
        {
            // Arrange - No orderbooks
            SetupPrices(_btcSymbol, 50000m, 50100m);
            SetupPrices(_ethSymbol, 3000m, 3010m);

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.AutoDetect);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.BestPrices, result.UsedStrategy);
        }

        #endregion

        #region DualOrderbook Strategy Tests

        [Test]
        public void MatchPair_DualOrderbook_MatchesBothSides()
        {
            // Arrange - Both have orderbooks
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (50000m, 1m), (49900m, 2m) },
                new[] { (50100m, 1m), (50200m, 2m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            var ethOrderbook = CreateOrderbook(_ethSymbol,
                new[] { (3000m, 10m), (2990m, 20m) },
                new[] { (3010m, 10m), (3020m, 20m) });
            _algorithm.Securities[_ethSymbol].Cache.AddData(ethOrderbook);

            // Act - LONG_SPREAD: Buy BTC, Sell ETH
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.DualOrderbook);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.DualOrderbook, result.UsedStrategy);
            Assert.Greater(result.Symbol1Quantity, 0); // Buy BTC
            Assert.Less(result.Symbol2Quantity, 0);    // Sell ETH
            Assert.Greater(result.MatchedLevels.Count, 0);
        }

        [Test]
        public void MatchPair_DualOrderbook_FailsWhenOrderbooksMissing()
        {
            // Arrange - Only one has orderbook
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (50000m, 1m) },
                new[] { (50100m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.DualOrderbook);

            // Assert
            Assert.IsFalse(result.Executable);
            Assert.That(result.RejectReason, Does.Contain("orderbook"));
        }

        #endregion

        #region SingleOrderbook Strategy Tests

        [Test]
        public void MatchPair_SingleOrderbook_MatchesSingleSideWithOrderbook()
        {
            // Arrange - Only BTC has orderbook
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (50000m, 0.5m), (49900m, 1m), (49800m, 2m) },
                new[] { (50100m, 0.5m), (50200m, 1m), (50300m, 2m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            SetupPrices(_ethSymbol, 3000m, 3010m);

            // Act - LONG_SPREAD: Buy BTC (has orderbook), Sell ETH (no orderbook)
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.SingleOrderbook);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.SingleOrderbook, result.UsedStrategy);
            Assert.Greater(result.Symbol1Quantity, 0); // Buy BTC
            Assert.Less(result.Symbol2Quantity, 0);    // Sell ETH
            Assert.Greater(result.MatchedLevels.Count, 0);
        }

        [Test]
        public void MatchPair_SingleOrderbook_FailsWhenNoOrderbook()
        {
            // Arrange - Neither has orderbook
            SetupPrices(_btcSymbol, 50000m, 50100m);
            SetupPrices(_ethSymbol, 3000m, 3010m);

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.SingleOrderbook);

            // Assert
            Assert.IsFalse(result.Executable);
            Assert.That(result.RejectReason, Does.Contain("orderbook"));
        }

        #endregion

        #region BestPrices Strategy Tests

        [Test]
        public void MatchPair_BestPrices_LongSpread_CalculatesCorrectQuantities()
        {
            // Arrange - LONG_SPREAD: Buy BTC, Sell ETH
            SetupPrices(_btcSymbol, 50000m, 50100m);
            SetupPrices(_ethSymbol, 3000m, 3010m);

            var targetUsd = 10000m;

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                targetUsd, ArbitrageDirection.LongSpread, 0.01m,
                MatchingStrategy.BestPrices);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.BestPrices, result.UsedStrategy);

            // Buy BTC at Ask (50100)
            Assert.Greater(result.Symbol1Quantity, 0);

            // Sell ETH at Bid (3000)
            Assert.Less(result.Symbol2Quantity, 0);
        }

        [Test]
        public void MatchPair_BestPrices_ShortSpread_CalculatesCorrectQuantities()
        {
            // Arrange - SHORT_SPREAD: Sell BTC, Buy ETH
            SetupPrices(_btcSymbol, 50000m, 50100m);
            SetupPrices(_ethSymbol, 3000m, 3010m);

            var targetUsd = 10000m;

            // Act
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                targetUsd, ArbitrageDirection.ShortSpread, 0.01m,
                MatchingStrategy.BestPrices);

            // Assert
            Assert.IsTrue(result.Executable);

            // Sell BTC at Bid (50000)
            Assert.Less(result.Symbol1Quantity, 0);

            // Buy ETH at Ask (3010)
            Assert.Greater(result.Symbol2Quantity, 0);
        }

        [Test]
        public void MatchPair_BestPrices_FailsWhenSpreadInsufficient()
        {
            // Arrange - Set prices with very small spread
            SetupPrices(_btcSymbol, 50000m, 50010m); // 0.02% spread
            SetupPrices(_ethSymbol, 3000m, 3001m);   // 0.03% spread

            // Act - Require 5% spread
            var result = OrderbookMatcher.MatchPair(
                _algorithm, _btcSymbol, _ethSymbol,
                10000m, ArbitrageDirection.LongSpread, 0.05m,
                MatchingStrategy.BestPrices);

            // Assert
            Assert.IsFalse(result.Executable);
            Assert.That(result.RejectReason, Does.Contain("Spread"));
        }

        #endregion

        #region Helper Methods

        private OrderbookDepth CreateOrderbook(Symbol symbol, (decimal price, decimal size)[] bids, (decimal price, decimal size)[] asks)
        {
            var orderbook = new OrderbookDepth
            {
                Symbol = symbol,
                Time = _algorithm.UtcTime,
                Bids = new List<OrderbookLevel>(),
                Asks = new List<OrderbookLevel>()
            };

            foreach (var (price, size) in bids)
            {
                orderbook.Bids.Add(new OrderbookLevel(price, size));
            }

            foreach (var (price, size) in asks)
            {
                orderbook.Asks.Add(new OrderbookLevel(price, size));
            }

            return orderbook;
        }

        private void SetupPrices(Symbol symbol, decimal bid, decimal ask)
        {
            var security = _algorithm.Securities[symbol];

            if (symbol.SecurityType == SecurityType.Crypto)
            {
                security.SetMarketPrice(new QuoteBar
                {
                    Symbol = symbol,
                    Time = _algorithm.UtcTime,
                    Bid = new Bar(bid, bid, bid, bid),
                    Ask = new Bar(ask, ask, ask, ask)
                });
            }
            else
            {
                security.SetMarketPrice(new TradeBar
                {
                    Symbol = symbol,
                    Time = _algorithm.UtcTime,
                    Open = (bid + ask) / 2,
                    High = (bid + ask) / 2,
                    Low = (bid + ask) / 2,
                    Close = (bid + ask) / 2,
                    Volume = 1000
                });
            }
        }

        #endregion
    }
}
