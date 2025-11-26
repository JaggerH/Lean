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
using Moq;
using Newtonsoft.Json;
using NUnit.Framework;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairManagerGridTests
    {
        private SecurityManager _securities;
        private SecurityTransactionManager _transactions;
        private Mock<AIAlgorithm> _mockAlgorithm;
        private Security _btcSecurity;
        private Security _mstrSecurity;
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

            var btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            var mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            _btcSecurity = CreateSecurity(btcSymbol, exchangeHours, timeKeeper);
            _mstrSecurity = CreateSecurity(mstrSymbol, exchangeHours, timeKeeper);

            _securities.Add(_btcSecurity);
            _securities.Add(_mstrSecurity);
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

        private GridLevelPair CreateTestLevelPair(decimal entrySpread, decimal exitSpread, string direction = "LONG_SPREAD")
        {
            return new GridLevelPair(
                entrySpread,
                exitSpread,
                direction,
                0.25m,
                (_btcSecurity.Symbol, _mstrSecurity.Symbol)
            );
        }

        #region GridPosition Creation Tests

        [Test]
        public void Test_AddPair_InitializesGridCollections()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);

            // Act
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);

            // Assert
            Assert.IsNotNull(pair.LevelPairs, "LevelPairs collection should be initialized");
            Assert.IsNotNull(pair.GridPositions, "GridPositions collection should be initialized");
            Assert.AreEqual(0, pair.LevelPairs.Count);
            Assert.AreEqual(0, pair.GridPositions.Count);
        }

        [Test]
        public void Test_GridPosition_CanBeAddedManually()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            var levelPair = CreateTestLevelPair(-0.02m, 0.01m);

            // Act
            var position = new GridPosition(
                pair,
                levelPair
            );
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);
            pair.GridPositions[tag] = position;

            // Assert
            Assert.AreEqual(1, pair.GridPositions.Count);
            Assert.IsTrue(pair.GridPositions.ContainsKey(tag));
        }

        #endregion

        #region GridLevelPair Tests

        [Test]
        public void Test_GridLevelPair_CreatesValidLevels()
        {
            // Arrange & Act
            var levelPair = CreateTestLevelPair(-0.02m, 0.01m, "LONG_SPREAD");

            // Assert
            Assert.AreEqual(-0.02m, levelPair.Entry.SpreadPct);
            Assert.AreEqual(0.01m, levelPair.Exit.SpreadPct);
            Assert.AreEqual("LONG_SPREAD", levelPair.Entry.Direction);
            Assert.AreEqual("SHORT_SPREAD", levelPair.Exit.Direction, "Exit should have opposite direction");
            Assert.AreEqual("ENTRY", levelPair.Entry.Type);
            Assert.AreEqual("EXIT", levelPair.Exit.Type);
        }

        [Test]
        public void Test_GridLevel_NaturalKey_IsUnique()
        {
            // Arrange
            var levelPair1 = CreateTestLevelPair(-0.02m, 0.01m);
            var levelPair2 = CreateTestLevelPair(-0.03m, 0.01m);

            // Act
            var key1 = levelPair1.Entry.NaturalKey;
            var key2 = levelPair2.Entry.NaturalKey;

            // Assert
            Assert.AreNotEqual(key1, key2, "Different entry spreads should produce different keys");
            Assert.IsTrue(key1.Contains("-0.0200"), "Key should contain spread percentage");
            Assert.IsTrue(key1.Contains("LONG_SPREAD"), "Key should contain direction");
            Assert.IsTrue(key1.Contains("ENTRY"), "Key should contain type");
        }

        #endregion

        #region GridPosition Tests

        [Test]
        public void Test_GridPosition_InitializesEmpty()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            var levelPair = CreateTestLevelPair(-0.02m, 0.01m);

            // Act
            var position = new GridPosition(
                pair,
                levelPair
            );

            // Assert
            Assert.AreEqual(0m, position.Leg1Quantity);
            Assert.AreEqual(0m, position.Leg2Quantity);
            Assert.AreEqual(0m, position.Leg1AverageCost);
            Assert.AreEqual(0m, position.Leg2AverageCost);
            Assert.IsFalse(position.Invested);
            Assert.IsNull(position.FirstFillTime);
        }

        #endregion

        #region Tag Encoding/Decoding Tests

        [Test]
        public void Test_EncodeGridTag_ValidInput_ReturnsCorrectFormat()
        {
            // Arrange
            var levelPair = CreateTestLevelPair(-0.02m, 0.005m, "LONG_SPREAD");

            // Act
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);

            // Assert
            Assert.IsNotNull(tag);
            Assert.IsTrue(tag.Contains(_btcSecurity.Symbol.ID.ToString()), "Tag should contain BTC SecurityIdentifier");
            Assert.IsTrue(tag.Contains(_mstrSecurity.Symbol.ID.ToString()), "Tag should contain MSTR SecurityIdentifier");
            Assert.IsTrue(tag.Contains("-0.0200"), "Tag should contain entry spread");
            Assert.IsTrue(tag.Contains("0.0050"), "Tag should contain exit spread");
            Assert.IsTrue(tag.Contains("LONG_SPREAD"), "Tag should contain direction");
            Assert.IsTrue(tag.Contains("0.2500"), "Tag should contain position size");
        }

        [Test]
        public void Test_TryDecodeGridTag_ValidTag_ReturnsTrue()
        {
            // Arrange
            var levelPair = CreateTestLevelPair(-0.02m, 0.005m, "LONG_SPREAD");
            var tag = TradingPairManager.EncodeGridTag(_btcSecurity.Symbol, _mstrSecurity.Symbol, levelPair);

            // Act
            var success = TradingPairManager.TryDecodeGridTag(tag, out var sid1, out var sid2, out var decodedLevelPair);

            // Assert
            Assert.IsTrue(success);
            Assert.IsNotNull(sid1);
            Assert.IsNotNull(sid2);
            Assert.IsNotNull(decodedLevelPair);
            Assert.AreEqual(-0.02m, decodedLevelPair.Entry.SpreadPct);
            Assert.AreEqual(0.005m, decodedLevelPair.Exit.SpreadPct);
            Assert.AreEqual("LONG_SPREAD", decodedLevelPair.Entry.Direction);
            Assert.AreEqual(0.25m, decodedLevelPair.Entry.PositionSizePct);
        }

        [Test]
        public void Test_TryDecodeGridTag_InvalidTag_ReturnsFalse()
        {
            // Arrange
            var invalidTag = "invalid|tag|format";

            // Act
            var success = TradingPairManager.TryDecodeGridTag(invalidTag, out var sid1, out var sid2, out var levelPair);

            // Assert
            Assert.IsFalse(success);
            Assert.IsNull(sid1);
            Assert.IsNull(sid2);
            Assert.IsNull(levelPair);
        }

        [Test]
        public void Test_TryDecodeGridTag_EmptyTag_ReturnsFalse()
        {
            // Act
            var success = TradingPairManager.TryDecodeGridTag("", out var sid1, out var sid2, out var levelPair);

            // Assert
            Assert.IsFalse(success);
        }

        [Test]
        public void Test_TryDecodeGridTag_NullTag_ReturnsFalse()
        {
            // Act
            var success = TradingPairManager.TryDecodeGridTag(null, out var sid1, out var sid2, out var levelPair);

            // Assert
            Assert.IsFalse(success);
        }

        #endregion

        #region Symbol/SecurityIdentifier Round-Trip Tests

        [Test]
        public void Test_SymbolToSecurityIdentifier_RoundTrip_Crypto_PreservesAllProperties()
        {
            // Step 1: 使用传统方式创建 Symbol
            var originalSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

            // Step 2: 生成 SecurityIdentifier 字符串
            var sidString = originalSymbol.ID.ToString();

            // Step 3: 用 SecurityIdentifier.TryParse 转回 Symbol
            Assert.IsTrue(SecurityIdentifier.TryParse(sidString, out var sid));
            var symbolFromStr = new Symbol(sid, sid.Symbol);

            // Step 4: 验证三个参数完全一致
            Assert.AreEqual(originalSymbol.Value, symbolFromStr.Value, "Symbol.Value (ticker) should match");
            Assert.AreEqual(originalSymbol.ID.SecurityType, symbolFromStr.ID.SecurityType, "SecurityType should match");
            Assert.AreEqual(originalSymbol.ID.Market, symbolFromStr.ID.Market, "Market should match");
        }

        [Test]
        public void Test_SymbolToSecurityIdentifier_RoundTrip_Equity_PreservesAllProperties()
        {
            // Step 1: 使用传统方式创建 Symbol
            var originalSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);

            // Step 2: 生成 SecurityIdentifier 字符串
            var sidString = originalSymbol.ID.ToString();

            // Step 3: 用 SecurityIdentifier.TryParse 转回 Symbol
            Assert.IsTrue(SecurityIdentifier.TryParse(sidString, out var sid));
            var symbolFromStr = new Symbol(sid, sid.Symbol);

            // Step 4: 验证三个参数完全一致
            Assert.AreEqual(originalSymbol.Value, symbolFromStr.Value, "Symbol.Value (ticker) should match");
            Assert.AreEqual(originalSymbol.ID.SecurityType, symbolFromStr.ID.SecurityType, "SecurityType should match");
            Assert.AreEqual(originalSymbol.ID.Market, symbolFromStr.ID.Market, "Market should match");
        }

        [Test]
        public void Test_SymbolToSecurityIdentifier_RoundTrip_Forex_PreservesAllProperties()
        {
            // Step 1: 使用传统方式创建 Symbol
            var originalSymbol = Symbol.Create("EURUSD", SecurityType.Forex, Market.Oanda);

            // Step 2: 生成 SecurityIdentifier 字符串
            var sidString = originalSymbol.ID.ToString();

            // Step 3: 用 SecurityIdentifier.TryParse 转回 Symbol
            Assert.IsTrue(SecurityIdentifier.TryParse(sidString, out var sid));
            var symbolFromStr = new Symbol(sid, sid.Symbol);

            // Step 4: 验证三个参数完全一致
            Assert.AreEqual(originalSymbol.Value, symbolFromStr.Value, "Symbol.Value (ticker) should match");
            Assert.AreEqual(originalSymbol.ID.SecurityType, symbolFromStr.ID.SecurityType, "SecurityType should match");
            Assert.AreEqual(originalSymbol.ID.Market, symbolFromStr.ID.Market, "Market should match");
        }

        [Test]
        public void Test_GridPosition_LevelPair_IsAccessible()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));

            // Act
            var position = new GridPosition(pair, levelPair);

            // Assert
            Assert.IsNotNull(position.LevelPair);
            Assert.AreEqual(-0.02m, position.LevelPair.Entry.SpreadPct);
            Assert.AreEqual(0.01m, position.LevelPair.Exit.SpreadPct);
            Assert.AreEqual("LONG_SPREAD", position.LevelPair.Entry.Direction);
        }

        [Test]
        public void Test_GridPosition_LevelPair_PreservedAfterSerialization()
        {
            // Arrange
            var manager = new TradingPairManager(_mockAlgorithm.Object);
            var pair = manager.AddPair(_btcSecurity.Symbol, _mstrSecurity.Symbol);
            var levelPair = new GridLevelPair(-0.02m, 0.01m, "LONG_SPREAD", 0.25m, (_btcSecurity.Symbol, _mstrSecurity.Symbol));
            var position = new GridPosition(pair, levelPair);

            // Act - Serialize and deserialize
            var json = JsonConvert.SerializeObject(position);
            var deserialized = JsonConvert.DeserializeObject<GridPosition>(json);

            // Assert
            Assert.IsNotNull(deserialized.LevelPair);
            Assert.AreEqual(-0.02m, deserialized.LevelPair.Entry.SpreadPct);
            Assert.AreEqual(0.01m, deserialized.LevelPair.Exit.SpreadPct);
        }

        #endregion
    }
}
