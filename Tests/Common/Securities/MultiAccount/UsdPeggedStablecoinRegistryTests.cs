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

using NUnit.Framework;
using QuantConnect.Securities.MultiAccount;

namespace QuantConnect.Tests.Common.Securities.MultiAccount
{
    [TestFixture]
    public class UsdPeggedStablecoinRegistryTests
    {
        [Test]
        public void DefaultRegistryContainsCommonStablecoins()
        {
            // Verify that the registry contains all common USD-pegged stablecoins
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("USDT"), "USDT should be registered");
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("USDC"), "USDC should be registered");
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("BUSD"), "BUSD should be registered");
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("DAI"), "DAI should be registered");
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("TUSD"), "TUSD should be registered");
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged("USDP"), "USDP should be registered");
        }

        [Test]
        [TestCase("USDT")]
        [TestCase("USDC")]
        [TestCase("BUSD")]
        [TestCase("DAI")]
        [TestCase("TUSD")]
        [TestCase("USDP")]
        public void IsUsdPeggedReturnsTrueForStablecoins(string currency)
        {
            Assert.IsTrue(UsdPeggedStablecoinRegistry.IsUsdPegged(currency),
                $"{currency} should be recognized as USD-pegged");
        }

        [Test]
        [TestCase("BTC")]
        [TestCase("ETH")]
        [TestCase("EUR")]
        [TestCase("GBP")]
        [TestCase("JPY")]
        [TestCase("INVALID")]
        public void IsUsdPeggedReturnsFalseForNonStablecoins(string currency)
        {
            Assert.IsFalse(UsdPeggedStablecoinRegistry.IsUsdPegged(currency),
                $"{currency} should not be recognized as USD-pegged");
        }

        [Test]
        [TestCase("USDT")]
        [TestCase("USDC")]
        [TestCase("BUSD")]
        [TestCase("DAI")]
        [TestCase("TUSD")]
        [TestCase("USDP")]
        public void GetUsdConversionRateReturnsOneForStablecoins(string currency)
        {
            var rate = UsdPeggedStablecoinRegistry.GetUsdConversionRate(currency);
            Assert.AreEqual(1.0m, rate,
                $"{currency} should have 1:1 conversion rate with USD");
        }

        [Test]
        [TestCase("BTC")]
        [TestCase("ETH")]
        [TestCase("EUR")]
        [TestCase("GBP")]
        [TestCase("JPY")]
        public void GetUsdConversionRateReturnsZeroForNonStablecoins(string currency)
        {
            var rate = UsdPeggedStablecoinRegistry.GetUsdConversionRate(currency);
            Assert.AreEqual(0m, rate,
                $"{currency} should have 0 conversion rate (not USD-pegged)");
        }
    }
}
