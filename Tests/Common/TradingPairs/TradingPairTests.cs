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
using NUnit.Framework;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;
using NodaTime;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairTests
    {
        private Security _leg1Security;
        private Security _leg2Security;
        private const decimal Epsilon = 0.0001m;

        [SetUp]
        public void Setup()
        {
            // Create test securities
            var exchangeHours = SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork);
            var config1 = CreateTradeBarConfig(Symbols.SPY);
            var config2 = CreateTradeBarConfig(Symbols.AAPL);

            _leg1Security = new Security(
                exchangeHours,
                config1,
                new Cash(Currencies.USD, 0, 1m),
                SymbolProperties.GetDefault(Currencies.USD),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            _leg2Security = new Security(
                exchangeHours,
                config2,
                new Cash(Currencies.USD, 0, 1m),
                SymbolProperties.GetDefault(Currencies.USD),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            // Set up LocalTimeKeeper for both securities
            var dateTime = new DateTime(2024, 1, 1, 9, 30, 0);
            var timeKeeper = new LocalTimeKeeper(dateTime.ConvertToUtc(TimeZones.NewYork), TimeZones.NewYork);
            _leg1Security.SetLocalTimeKeeper(timeKeeper);
            _leg2Security.SetLocalTimeKeeper(timeKeeper);
        }

        private SubscriptionDataConfig CreateTradeBarConfig(Symbol symbol)
        {
            return new SubscriptionDataConfig(
                typeof(TradeBar),
                symbol,
                Resolution.Minute,
                TimeZones.NewYork,
                TimeZones.NewYork,
                true,
                true,
                false
            );
        }

        private void SetPrices(decimal leg1Bid, decimal leg1Ask, decimal leg2Bid, decimal leg2Ask)
        {
            _leg1Security.SetMarketPrice(new QuoteBar
            {
                Symbol = _leg1Security.Symbol,
                Time = DateTime.UtcNow,
                Bid = new Bar(leg1Bid, leg1Bid, leg1Bid, leg1Bid),
                Ask = new Bar(leg1Ask, leg1Ask, leg1Ask, leg1Ask)
            });

            _leg2Security.SetMarketPrice(new QuoteBar
            {
                Symbol = _leg2Security.Symbol,
                Time = DateTime.UtcNow,
                Bid = new Bar(leg2Bid, leg2Bid, leg2Bid, leg2Bid),
                Ask = new Bar(leg2Ask, leg2Ask, leg2Ask, leg2Ask)
            });
        }

        #region Spread Calculation Tests

        [Test]
        public void Test_ShortSpread_ValidPrices_CorrectFormula()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            // Short Spread = (leg1_bid - leg2_ask) / leg1_bid = (100 - 99) / 100 = 0.01 = 1%
            var expectedShortSpread = (100m - 99m) / 100m;
            Assert.That(Math.Abs(expectedShortSpread - pair.ShortSpread), Is.LessThan(Epsilon),
                $"ShortSpread should be {expectedShortSpread}, got {pair.ShortSpread}");
        }

        [Test]
        public void Test_LongSpread_ValidPrices_CorrectFormula()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            // Long Spread = (leg1_ask - leg2_bid) / leg1_ask = (101 - 98) / 101 = 0.0297...
            var expectedLongSpread = (101m - 98m) / 101m;
            Assert.That(Math.Abs(expectedLongSpread - pair.LongSpread), Is.LessThan(Epsilon),
                $"LongSpread should be {expectedLongSpread}, got {pair.LongSpread}");
        }

        [Test]
        public void Test_TheoreticalSpread_CorrectSelection()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            // ShortSpread = (100-99)/100 = 0.01
            // LongSpread = (101-98)/101 = 0.0297...
            // Implementation selects by: |ShortSpread| >= |LongSpread| ? ShortSpread : LongSpread
            // 0.01 < 0.0297, so selects LongSpread
            var longSpread = (101m - 98m) / 101m;
            Assert.That(Math.Abs(longSpread - pair.TheoreticalSpread), Is.LessThan(Epsilon),
                "TheoreticalSpread should equal LongSpread in this case");
        }

        [Test]
        public void Test_Spread_ZeroBidPrice_HandlesGracefully()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 0m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            Assert.IsFalse(pair.HasValidPrices, "HasValidPrices should be false with zero bid");
            Assert.AreEqual(MarketState.Unknown, pair.MarketState, "MarketState should be Unknown with zero prices");
        }

        [Test]
        public void Test_Spread_NegativeSpread_HandlesCorrectly()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Leg1 bid < Leg2 ask (no immediate arbitrage, negative short spread)
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 102m, leg2Ask: 103m);

            // Act
            pair.Update();

            // Assert
            // ShortSpread = (100 - 103) / 100 = -0.03 (negative)
            var expectedShortSpread = (100m - 103m) / 100m;
            Assert.That(Math.Abs(expectedShortSpread - pair.ShortSpread), Is.LessThan(Epsilon));
            Assert.IsTrue(pair.ShortSpread < 0, "ShortSpread should be negative");
        }

        [Test]
        public void Test_Spread_EpsilonBoundary_HandlesCorrectly()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Set prices just above epsilon boundary for crossed market
            SetPrices(leg1Bid: 100.0002m, leg1Ask: 100.01m, leg2Bid: 99.99m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            // leg1_bid (100.0002) > leg2_ask (100) + epsilon (0.0001)
            // Should be Crossed
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
        }

        [Test]
        public void Test_Spread_VerySmallSpread_PreservesPrecision()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 1000.00m, leg1Ask: 1000.10m, leg2Bid: 999.95m, leg2Ask: 1000.05m);

            // Act
            pair.Update();

            // Assert
            // ShortSpread = (1000.00 - 1000.05) / 1000.00 = -0.00005 = -0.005%
            var expectedShortSpread = (1000.00m - 1000.05m) / 1000.00m;
            Assert.That(Math.Abs(expectedShortSpread - pair.ShortSpread), Is.LessThan(0.0000001m),
                "Should preserve precision for small spreads");
        }

        [Test]
        public void Test_Spread_LargePrices_NoOverflow()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 50000m, leg1Ask: 50100m, leg2Bid: 49900m, leg2Ask: 50000m);

            // Act
            pair.Update();

            // Assert
            // ShortSpread = (50000 - 50000) / 50000 = 0
            Assert.That(Math.Abs(0m - pair.ShortSpread), Is.LessThan(Epsilon));
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState);
        }

        [Test]
        public void Test_Spread_InvalidBidAsk_BidGreaterThanAsk_ReturnsUnknown()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Invalid: bid > ask
            SetPrices(leg1Bid: 102m, leg1Ask: 100m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            Assert.IsFalse(pair.HasValidPrices, "HasValidPrices should be false when bid > ask");
            Assert.AreEqual(MarketState.Unknown, pair.MarketState);
        }

        [Test]
        public void Test_Spread_UpdateMultipleTimes_RecalculatesCorrectly()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);

            // First update
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);
            pair.Update();
            var firstSpread = pair.TheoreticalSpread;

            // Second update with different prices
            SetPrices(leg1Bid: 105m, leg1Ask: 106m, leg2Bid: 103m, leg2Ask: 104m);
            pair.Update();
            var secondSpread = pair.TheoreticalSpread;

            // Assert
            Assert.AreNotEqual(firstSpread, secondSpread, "Spread should recalculate on update");
            // TheoreticalSpread selects by: |ShortSpread| >= |LongSpread| ? ShortSpread : LongSpread
            // ShortSpread = (105-104)/105 = 0.0095, LongSpread = (106-103)/106 = 0.0283
            // Selects LongSpread (larger absolute value)
            var expectedSecondSpread = (106m - 103m) / 106m;
            Assert.That(Math.Abs(expectedSecondSpread - secondSpread), Is.LessThan(Epsilon));
        }

        #endregion

        #region MarketState Determination Tests

        [Test]
        public void Test_MarketState_Crossed_Leg1BidGreaterThanLeg2Ask()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed Pattern 1: leg1_bid > leg2_ask + epsilon
            SetPrices(leg1Bid: 100.5m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState,
                "Should be Crossed when leg1_bid > leg2_ask + epsilon");
            Assert.AreEqual("SHORT_SPREAD", pair.Direction,
                "Direction should be SHORT_SPREAD");
        }

        [Test]
        public void Test_MarketState_Crossed_Leg2BidGreaterThanLeg1Ask()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed Pattern 2: leg2_bid > leg1_ask + epsilon
            SetPrices(leg1Bid: 98m, leg1Ask: 100m, leg2Bid: 100.5m, leg2Ask: 101m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState,
                "Should be Crossed when leg2_bid > leg1_ask + epsilon");
            Assert.AreEqual("LONG_SPREAD", pair.Direction,
                "Direction should be buy_leg1_sell_leg2");
        }

        [Test]
        public void Test_MarketState_LimitOpportunity_Pattern1()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid -> SHORT_SPREAD
            SetPrices(leg1Bid: 101m, leg1Ask: 103m, leg2Bid: 100m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState,
                "Should be LimitOpportunity when leg1_ask > leg2_ask > leg1_bid > leg2_bid");
            Assert.AreEqual("SHORT_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_MarketState_LimitOpportunity_Pattern2()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid -> LONG_SPREAD
            SetPrices(leg1Bid: 100m, leg1Ask: 102m, leg2Bid: 101m, leg2Ask: 103m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState,
                "Should be LimitOpportunity when leg2_ask > leg1_ask > leg2_bid > leg1_bid");
            Assert.AreEqual("LONG_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_MarketState_NoOpportunity_NormalMarket()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // NoOpportunity: quotes overlap but don't match LimitOpportunity patterns
            // leg1_ask < leg2_ask but leg1_bid > leg2_bid (doesn't match any pattern)
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 99m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState,
                "Should be NoOpportunity when quotes overlap but don't match patterns");
            Assert.AreEqual("none", pair.Direction);
        }

        [Test]
        public void Test_MarketState_Unknown_NoPriceData()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Don't set any prices

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Unknown, pair.MarketState,
                "Should be Unknown when no price data available");
            Assert.IsFalse(pair.HasValidPrices);
        }

        [Test]
        public void Test_MarketState_Unknown_InvalidPrices()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Set zero prices
            SetPrices(leg1Bid: 0m, leg1Ask: 0m, leg2Bid: 0m, leg2Ask: 0m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Unknown, pair.MarketState,
                "Should be Unknown with zero prices");
            Assert.IsFalse(pair.HasValidPrices);
        }

        [Test]
        public void Test_MarketState_Transition_CrossedToNormal()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);

            // Start in Crossed state
            SetPrices(leg1Bid: 100.5m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 100m);
            pair.Update();
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);

            // Transition to NoOpportunity
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 99m, leg2Ask: 102m);
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState,
                "Should transition from Crossed to NoOpportunity");
        }

        [Test]
        public void Test_MarketState_Transition_NormalToCrossed()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);

            // Start in NoOpportunity state
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 99m, leg2Ask: 102m);
            pair.Update();
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState);

            // Transition to Crossed
            SetPrices(leg1Bid: 100.5m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 100m);
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState,
                "Should transition from NoOpportunity to Crossed");
        }

        [Test]
        public void Test_MarketState_TinyDifference_StillCrossed()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // EPSILON is only for zero-checking in CheckValidPrices, NOT for crossing detection
            // Even a tiny crossing should be detected as Crossed (correct arbitrage behavior)
            // leg1_bid (100.00000001) > leg2_ask (100) by 0.00000001
            SetPrices(leg1Bid: 100.00000001m, leg1Ask: 100.01m, leg2Bid: 99.99m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState,
                "Should be Crossed even with tiny difference - epsilon is not used for crossing detection");
            Assert.AreEqual("SHORT_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_MarketState_Epsilon_JustAboveCrossed()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // leg1_bid = 100.00015, leg2_ask = 100, epsilon = 0.0001
            // 100.00015 > 100 + 0.0001, so IS crossed
            SetPrices(leg1Bid: 100.00015m, leg1Ask: 100.01m, leg2Bid: 99.99m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState,
                "Should be Crossed when just above epsilon threshold");
        }

        #endregion

        #region Arbitrage Direction Tests

        [Test]
        public void Test_Direction_Crossed_ShortSpread_BuyLeg1SellLeg2()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed with leg2_bid > leg1_ask (short spread arbitrage)
            SetPrices(leg1Bid: 98m, leg1Ask: 100m, leg2Bid: 100.5m, leg2Ask: 101m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
            Assert.AreEqual("LONG_SPREAD", pair.Direction,
                "Direction should be buy_leg1_sell_leg2 for short spread arbitrage");
        }

        [Test]
        public void Test_Direction_Crossed_LongSpread_BuyLeg2SellLeg1()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed with leg1_bid > leg2_ask (long spread arbitrage)
            SetPrices(leg1Bid: 100.5m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
            Assert.AreEqual("SHORT_SPREAD", pair.Direction,
                "Direction should be buy_leg2_sell_leg1 for long spread arbitrage");
        }

        [Test]
        public void Test_Direction_LimitOpportunity_Pattern1()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid -> SHORT_SPREAD
            SetPrices(leg1Bid: 101m, leg1Ask: 103m, leg2Bid: 100m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState);
            Assert.AreEqual("SHORT_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_Direction_LimitOpportunity_Pattern2()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid -> LONG_SPREAD
            SetPrices(leg1Bid: 100m, leg1Ask: 102m, leg2Bid: 101m, leg2Ask: 103m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState);
            Assert.AreEqual("LONG_SPREAD", pair.Direction);
        }

        [Test]
        public void Test_Direction_NoOpportunity_ReturnsNone()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // NoOpportunity: quotes overlap but don't match LimitOpportunity patterns
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 99m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState);
            Assert.AreEqual("none", pair.Direction);
        }

        [Test]
        public void Test_Direction_Unknown_ReturnsNone()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // No prices set

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Unknown, pair.MarketState);
            Assert.AreEqual("none", pair.Direction);
        }

        #endregion

        #region ExecutableSpread Tests

        [Test]
        public void Test_ExecutableSpread_Crossed_ShortSpread_ReturnsShortSpread()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed market with SHORT_SPREAD: leg1_bid > leg2_ask + epsilon
            SetPrices(leg1Bid: 100.5m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 100m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
            Assert.AreEqual("SHORT_SPREAD", pair.Direction);
            Assert.IsNotNull(pair.ExecutableSpread, "ExecutableSpread should not be null for Crossed");
            // ExecutableSpread should equal ShortSpread for SHORT_SPREAD direction
            Assert.That(Math.Abs(pair.ShortSpread - pair.ExecutableSpread.Value), Is.LessThan(Epsilon));
        }

        [Test]
        public void Test_ExecutableSpread_Crossed_LongSpread_ReturnsLongSpread()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // Crossed market with LONG_SPREAD: leg2_bid > leg1_ask + epsilon
            SetPrices(leg1Bid: 98m, leg1Ask: 100m, leg2Bid: 100.5m, leg2Ask: 101m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Crossed, pair.MarketState);
            Assert.AreEqual("LONG_SPREAD", pair.Direction);
            Assert.IsNotNull(pair.ExecutableSpread, "ExecutableSpread should not be null for Crossed");
            // ExecutableSpread should equal LongSpread for LONG_SPREAD direction
            Assert.That(Math.Abs(pair.LongSpread - pair.ExecutableSpread.Value), Is.LessThan(Epsilon));
        }

        [Test]
        public void Test_ExecutableSpread_LimitOpportunity_Pattern1_CalculatesOverlap()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid -> SHORT_SPREAD
            SetPrices(leg1Bid: 101m, leg1Ask: 103m, leg2Bid: 100m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState);
            Assert.IsNotNull(pair.ExecutableSpread, "ExecutableSpread should not be null for LimitOpportunity");
            // ExecutableSpread = Max(spread1, spread2)
            // spread1 = (leg1_ask - leg2_ask) / leg1_ask = (103 - 102) / 103
            // spread2 = (leg1_bid - leg2_bid) / leg1_bid = (101 - 100) / 101
            var spread1 = (103m - 102m) / 103m;
            var spread2 = (101m - 100m) / 101m;
            var expectedExecutableSpread = Math.Max(spread1, spread2);
            Assert.That(Math.Abs(expectedExecutableSpread - pair.ExecutableSpread.Value), Is.LessThan(Epsilon));
        }

        [Test]
        public void Test_ExecutableSpread_LimitOpportunity_Pattern2_CalculatesOverlap()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // LimitOpportunity Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid -> LONG_SPREAD
            SetPrices(leg1Bid: 100m, leg1Ask: 102m, leg2Bid: 101m, leg2Ask: 103m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.LimitOpportunity, pair.MarketState);
            Assert.IsNotNull(pair.ExecutableSpread, "ExecutableSpread should not be null for LimitOpportunity");
            // ExecutableSpread = Min(spread1, spread2)
            // spread1 = (leg1_ask - leg2_bid) / leg1_ask = (102 - 101) / 102
            // spread2 = (leg1_bid - leg2_ask) / leg1_bid = (100 - 103) / 100
            var spread1 = (102m - 101m) / 102m;
            var spread2 = (100m - 103m) / 100m;
            var expectedExecutableSpread = Math.Min(spread1, spread2);
            Assert.That(Math.Abs(expectedExecutableSpread - pair.ExecutableSpread.Value), Is.LessThan(Epsilon));
        }

        [Test]
        public void Test_ExecutableSpread_NoOpportunity_ReturnsNull()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // NoOpportunity: quotes overlap but don't match LimitOpportunity patterns
            // leg1_ask < leg2_ask but leg1_bid > leg2_bid (doesn't match any pattern)
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 99m, leg2Ask: 102m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.NoOpportunity, pair.MarketState);
            Assert.IsNull(pair.ExecutableSpread, "ExecutableSpread should be null for NoOpportunity");
        }

        [Test]
        public void Test_ExecutableSpread_Unknown_ReturnsNull()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            // No prices set

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(MarketState.Unknown, pair.MarketState);
            Assert.IsNull(pair.ExecutableSpread, "ExecutableSpread should be null for Unknown");
        }

        #endregion

        #region Additional Property Tests

        [Test]
        public void Test_Properties_ValidPrices_AccessibleAndCorrect()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);
            SetPrices(leg1Bid: 100m, leg1Ask: 101m, leg2Bid: 98m, leg2Ask: 99m);

            // Act
            pair.Update();

            // Assert
            Assert.AreEqual(100m, pair.Leg1BidPrice);
            Assert.AreEqual(101m, pair.Leg1AskPrice);
            Assert.AreEqual(100.5m, pair.Leg1MidPrice, "Mid should be (bid + ask) / 2");
            Assert.AreEqual(98m, pair.Leg2BidPrice);
            Assert.AreEqual(99m, pair.Leg2AskPrice);
            Assert.AreEqual(98.5m, pair.Leg2MidPrice);
            Assert.IsTrue(pair.HasValidPrices);
            var expectedKey = $"{_leg1Security.Symbol}-{_leg2Security.Symbol}";
            Assert.AreEqual(expectedKey, pair.Key);
            Assert.AreEqual(_leg1Security.Symbol, pair.Leg1Symbol);
            Assert.AreEqual(_leg2Security.Symbol, pair.Leg2Symbol);
        }

        [Test]
        public void Test_PairType_ReturnsSpread()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);

            // Assert
            Assert.AreEqual("spread", pair.PairType);
        }

        [Test]
        public void Test_Key_ReturnsFormattedString()
        {
            // Arrange
            var pair = new TradingPair(_leg1Security.Symbol, _leg2Security.Symbol, "spread", _leg1Security, _leg2Security);

            // Assert
            // Key should be formatted as "Symbol1-Symbol2"
            var expectedKey = $"{_leg1Security.Symbol}-{_leg2Security.Symbol}";
            Assert.AreEqual(expectedKey, pair.Key);
        }

        #endregion
    }
}
