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
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Tests.Common.TradingPairs
{
    [TestFixture]
    public class TradingPairManagerUtilityTests
    {
        private Symbol _btcSymbol;
        private Symbol _mstrSymbol;

        [SetUp]
        public void Setup()
        {
            _btcSymbol = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            _mstrSymbol = Symbol.Create("MSTR", SecurityType.Equity, Market.USA);
        }

        private GridLevelPair CreateTestLevelPair(decimal entrySpread, decimal exitSpread, string direction = "LONG_SPREAD")
        {
            return new GridLevelPair(
                entrySpread,
                exitSpread,
                direction,
                0.25m
            );
        }

        #region Tag Encoding/Decoding Tests

        [Test]
        public void Test_EncodeGridTag_ValidInput_ReturnsCorrectFormat()
        {
            // Arrange
            var levelPair = CreateTestLevelPair(-0.02m, 0.005m, "LONG_SPREAD");

            // Act
            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);

            // Assert
            Assert.IsNotNull(tag);
            Assert.IsTrue(tag.Contains(_btcSymbol.ID.ToString()), "Tag should contain BTC SecurityIdentifier");
            Assert.IsTrue(tag.Contains(_mstrSymbol.ID.ToString()), "Tag should contain MSTR SecurityIdentifier");
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
            var tag = TradingPairManager.EncodeGridTag(_btcSymbol, _mstrSymbol, levelPair);

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

        #endregion
    }
}
