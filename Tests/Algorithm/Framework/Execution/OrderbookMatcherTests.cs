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
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Tests.Engine.DataFeeds;
using QuantConnect.TradingPairs.Grid;

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
        private Symbol _btcUsdtSymbol;

        [SetUp]
        public void Setup()
        {
            _algorithm = new AQCAlgorithm();
            _algorithm.SubscriptionManager.SetDataManager(new DataManagerStub(_algorithm));

            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _btcUsdtSymbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Binance);

            // Add securities
            _algorithm.AddSecurity(_btcSymbol);
            _algorithm.AddSecurity(_btcUsdtSymbol);
        }

        /// <summary>
        /// Test implementation of IArbitragePortfolioTarget for unit testing
        /// </summary>
        private class TestArbitragePortfolioTarget : IArbitragePortfolioTarget
        {
            public Symbol Leg1Symbol { get; set; }
            public Symbol Leg2Symbol { get; set; }
            public decimal Leg1Quantity { get; set; }
            public decimal Leg2Quantity { get; set; }
            public GridLevel Level { get; set; }
            public string Tag { get; set; }
        }

        /// <summary>
        /// Helper method to create test target from test parameters.
        /// Uses target quantity directly instead of USD value.
        /// </summary>
        private TestArbitragePortfolioTarget CreateTestTarget(
            Symbol leg1Symbol,
            Symbol leg2Symbol,
            decimal targetQuantity,
            string direction,
            decimal expectedSpreadPct)
        {
            decimal leg1Qty, leg2Qty;
            if (direction == "LONG_SPREAD")
            {
                // Buy leg1, sell leg2
                leg1Qty = targetQuantity;
                leg2Qty = -targetQuantity;
            }
            else
            {
                // Sell leg1, buy leg2
                leg1Qty = -targetQuantity;
                leg2Qty = targetQuantity;
            }

            return new TestArbitragePortfolioTarget
            {
                Leg1Symbol = leg1Symbol,
                Leg2Symbol = leg2Symbol,
                Leg1Quantity = leg1Qty,
                Leg2Quantity = leg2Qty,
                Level = new GridLevel(
                    spreadPct: expectedSpreadPct,
                    direction: direction,
                    type: "ENTRY",
                    positionSizePct: 0.25m
                ),
                Tag = $"{leg1Symbol}|{leg2Symbol}|{expectedSpreadPct}|-{expectedSpreadPct}|{direction}|0.25"
            };
        }

        #region AutoDetect Strategy Tests

        [Test]
        public void MatchPair_AutoDetect_ChoosesDualOrderbookWhenBothAvailable()
        {
            // Arrange - BTC vs BTCUSDT with Leg1 cheaper than Leg2
            // For LONG_SPREAD: Leg1 should be cheaper (negative spread is good)
            // BTCUSD: bid=49000, ask=50000
            // BTCUSDT: bid=51000, ask=52000
            // Long Spread: buy BTCUSD at 50000, sell BTCUSDT at 51000
            // Spread = (50000 - 51000) / 50000 = -2% (negative, good for LONG)
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (49000m, 1m) },
                new[] { (50000m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            var btcUsdtOrderbook = CreateOrderbook(_btcUsdtSymbol,
                new[] { (51000m, 1m) },
                new[] { (52000m, 1m) });
            _algorithm.Securities[_btcUsdtSymbol].Cache.AddData(btcUsdtOrderbook);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,  // 0.2 BTC
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m  // Accept spread <= -0.5%
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.AutoDetect);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.DualOrderbook, result.UsedStrategy);
        }

        [Test]
        public void MatchPair_AutoDetect_FallsBackToSingleOrderbook()
        {
            // Arrange - Only BTCUSD has orderbook, BTCUSDT only has price
            // BTCUSD: bid=49000, ask=50000 (cheaper, has orderbook)
            // BTCUSDT: bid=51000, ask=52000 (more expensive, no orderbook)
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (49000m, 1m) },
                new[] { (50000m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            SetupPrices(_btcUsdtSymbol, 51000m, 52000m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m  // Accept spread <= -0.5%
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.AutoDetect);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.SingleOrderbook, result.UsedStrategy);
        }

        [Test]
        public void MatchPair_AutoDetect_FallsBackToBestPrices()
        {
            // Arrange - No orderbooks, only prices
            // BTCUSD: bid=49000, ask=50000 (cheaper)
            // BTCUSDT: bid=51000, ask=52000 (more expensive)
            SetupPrices(_btcSymbol, 49000m, 50000m);
            SetupPrices(_btcUsdtSymbol, 51000m, 52000m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m  // Accept spread <= -0.5%
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
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
            // BTCUSD: cheaper (bid=49000/48900, ask=50000/50100)
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (49000m, 1m), (48900m, 2m) },
                new[] { (50000m, 1m), (50100m, 2m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            // BTCUSDT: more expensive (bid=51000/50900, ask=52000/52100)
            var btcUsdtOrderbook = CreateOrderbook(_btcUsdtSymbol,
                new[] { (51000m, 1m), (50900m, 2m) },
                new[] { (52000m, 1m), (52100m, 2m) });
            _algorithm.Securities[_btcUsdtSymbol].Cache.AddData(btcUsdtOrderbook);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m  // Accept spread <= -0.5%
            );

            // Act - LONG_SPREAD: Buy BTCUSD, Sell BTCUSDT
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.DualOrderbook);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.DualOrderbook, result.UsedStrategy);
            Assert.Greater(result.Symbol1Quantity, 0); // Buy BTCUSD
            Assert.Less(result.Symbol2Quantity, 0);    // Sell BTCUSDT
            Assert.Greater(result.MatchedLevels.Count, 0);
        }

        [Test]
        public void MatchPair_DualOrderbook_FailsWhenOrderbooksMissing()
        {
            // Arrange - Only one has orderbook
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (49000m, 1m) },
                new[] { (50000m, 1m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.DualOrderbook);

            // Assert
            Assert.IsFalse(result.Executable);
            Assert.That(result.RejectReason.ToLower(), Does.Contain("orderbook"));
        }

        #endregion

        #region SingleOrderbook Strategy Tests

        [Test]
        public void MatchPair_SingleOrderbook_MatchesSingleSideWithOrderbook()
        {
            // Arrange - Only BTCUSD has orderbook (cheaper)
            // BTCUSD: bid=49000/48900/48800, ask=50000/50100/50200
            var btcOrderbook = CreateOrderbook(_btcSymbol,
                new[] { (49000m, 0.5m), (48900m, 1m), (48800m, 2m) },
                new[] { (50000m, 0.5m), (50100m, 1m), (50200m, 2m) });
            _algorithm.Securities[_btcSymbol].Cache.AddData(btcOrderbook);

            // BTCUSDT: only has price (more expensive)
            SetupPrices(_btcUsdtSymbol, 51000m, 52000m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m
            );

            // Act - LONG_SPREAD: Buy BTCUSD (has orderbook), Sell BTCUSDT (no orderbook)
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.SingleOrderbook);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.SingleOrderbook, result.UsedStrategy);
            Assert.Greater(result.Symbol1Quantity, 0); // Buy BTCUSD
            Assert.Less(result.Symbol2Quantity, 0);    // Sell BTCUSDT
            Assert.Greater(result.MatchedLevels.Count, 0);
        }

        [Test]
        public void MatchPair_SingleOrderbook_FailsWhenNoOrderbook()
        {
            // Arrange - Neither has orderbook
            SetupPrices(_btcSymbol, 49000m, 50000m);
            SetupPrices(_btcUsdtSymbol, 51000m, 52000m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.SingleOrderbook);

            // Assert
            Assert.IsFalse(result.Executable);
            Assert.That(result.RejectReason.ToLower(), Does.Contain("orderbook"));
        }

        #endregion

        #region BestPrices Strategy Tests

        [Test]
        public void MatchPair_BestPrices_LongSpread_CalculatesCorrectQuantities()
        {
            // Arrange - LONG_SPREAD: Buy BTCUSD (cheaper), Sell BTCUSDT (more expensive)
            // BTCUSD: bid=49000, ask=50000
            // BTCUSDT: bid=51000, ask=52000
            // Long: buy BTCUSD at 50000, sell BTCUSDT at 51000
            // Spread = (50000 - 51000) / 50000 = -2%
            SetupPrices(_btcSymbol, 49000m, 50000m);
            SetupPrices(_btcUsdtSymbol, 51000m, 52000m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.005m  // Accept spread <= -0.5%
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.BestPrices);

            // Assert
            Assert.IsTrue(result.Executable);
            Assert.AreEqual(MatchingStrategy.BestPrices, result.UsedStrategy);

            // Buy BTCUSD at Ask (50000)
            Assert.Greater(result.Symbol1Quantity, 0);

            // Sell BTCUSDT at Bid (51000)
            Assert.Less(result.Symbol2Quantity, 0);
        }

        [Test]
        public void MatchPair_BestPrices_ShortSpread_CalculatesCorrectQuantities()
        {
            // Arrange - SHORT_SPREAD: Sell BTCUSD, Buy BTCUSDT
            // BTCUSD: bid=50000, ask=50100
            // BTCUSDT: bid=50100, ask=50200
            // Short: sell BTCUSD at 50000, buy BTCUSDT at 50200
            // Spread = (50000 - 50200) / 50000 = -0.4%
            SetupPrices(_btcSymbol, 50000m, 50100m);
            SetupPrices(_btcUsdtSymbol, 50100m, 50200m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "SHORT_SPREAD",
                expectedSpreadPct: -0.005m  // -0.5%
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.BestPrices);

            // Assert
            Assert.IsTrue(result.Executable);

            // Sell BTCUSD at Bid (50000)
            Assert.Less(result.Symbol1Quantity, 0);

            // Buy BTCUSDT at Ask (50200)
            Assert.Greater(result.Symbol2Quantity, 0);
        }

        [Test]
        public void MatchPair_BestPrices_FailsWhenSpreadInsufficient()
        {
            // Arrange - Set prices with insufficient spread for LONG_SPREAD
            // For LONG_SPREAD to be rejected: actual spread must be > expected spread
            // BTCUSD: bid=50000, ask=50010 (slightly cheaper)
            // BTCUSDT: bid=50020, ask=50030 (slightly more expensive)
            // Spread = (50010 - 50020) / 50010 = -0.02% (small negative spread)
            SetupPrices(_btcSymbol, 50000m, 50010m);
            SetupPrices(_btcUsdtSymbol, 50020m, 50030m);

            var target = CreateTestTarget(
                _btcSymbol, _btcUsdtSymbol,
                targetQuantity: 0.2m,
                direction: "LONG_SPREAD",
                expectedSpreadPct: -0.05m  // Require spread <= -5% (very strict)
            );

            // Act
            var targetUsd = Math.Abs(target.Leg1Quantity) * _algorithm.Securities[target.Leg1Symbol].Price;
            var result = OrderbookMatcher.MatchPair(
                _algorithm,
                target,
                targetUsd,
                MatchingStrategy.BestPrices);

            // Assert
            // -0.02% > -5%, so should be rejected
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
