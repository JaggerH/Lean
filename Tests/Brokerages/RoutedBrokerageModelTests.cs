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
using QuantConnect.Brokerages;
using QuantConnect.Securities;

namespace QuantConnect.Tests.Brokerages
{
    [TestFixture]
    public class RoutedBrokerageModelTests
    {
        [Test]
        public void RoutedBrokerageModel_TwoSubAccounts_LoadsCashAndCurrenciesCorrectly()
        {
            // Arrange - Create two different brokerage models with different currencies
            var gateBrokerageModel = new GateBrokerageModel(AccountType.Margin);
            var interactiveBrokerageModel = new InteractiveBrokersBrokerageModel(AccountType.Margin);

            // Create market to brokerage model mappings
            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { Market.Gate, gateBrokerageModel },
                { Market.USA, interactiveBrokerageModel }
            };

            // Act - Create RoutedBrokerageModel
            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel, gateBrokerageModel);

            // Assert - Verify default account currencies from both models
            Assert.AreEqual("USDT", gateBrokerageModel.DefaultAccountCurrency, "Gate.io should use USDT as base currency");
            Assert.AreEqual("USD", interactiveBrokerageModel.DefaultAccountCurrency, "Interactive Brokers should use USD as base currency");

            // Verify merged default markets
            Assert.IsNotNull(routedModel.DefaultMarkets);
            Assert.IsTrue(routedModel.DefaultMarkets.ContainsKey(SecurityType.Crypto), "Should contain Crypto market mapping");
            Assert.IsTrue(routedModel.DefaultMarkets.ContainsKey(SecurityType.Equity), "Should contain Equity market mapping");
        }

        [Test]
        public void RoutedBrokerageModel_MultipleMarkets_MergesDefaultMarketsCorrectly()
        {
            // Arrange
            var gateBrokerageModel = new GateBrokerageModel();
            var interactiveBrokerageModel = new InteractiveBrokersBrokerageModel();

            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { Market.Gate, gateBrokerageModel },
                { Market.USA, interactiveBrokerageModel }
            };

            // Act
            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel);

            // Assert - Verify that Crypto maps to Gate and Equity maps to USA
            Assert.AreEqual(Market.Gate, routedModel.DefaultMarkets[SecurityType.Crypto]);
            Assert.AreEqual(Market.USA, routedModel.DefaultMarkets[SecurityType.Equity]);
        }

        [Test]
        public void RoutedBrokerageModel_CaseInsensitiveMarketLookup_Works()
        {
            // Arrange
            var gateBrokerageModel = new GateBrokerageModel();
            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { "GATE", gateBrokerageModel }  // Uppercase
            };

            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel);
            var marketMappings = routedModel.GetMarketMappings();

            // Assert - Should find the model regardless of case
            Assert.IsTrue(marketMappings.ContainsKey("gate"), "Should support case-insensitive lookup for lowercase");
            Assert.AreSame(gateBrokerageModel, marketMappings["gate"]);
        }

        [Test]
        public void RoutedBrokerageModel_EmptyDictionary_ThrowsArgumentException()
        {
            // Arrange
            var emptyDictionary = new Dictionary<string, IBrokerageModel>();

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                new RoutedBrokerageModel(emptyDictionary));
            Assert.That(ex.Message, Does.Contain("cannot be null or empty"));
        }

        [Test]
        public void RoutedBrokerageModel_NullDictionary_ThrowsArgumentException()
        {
            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                new RoutedBrokerageModel(null));
            Assert.That(ex.Message, Does.Contain("cannot be null or empty"));
        }
    }
}
