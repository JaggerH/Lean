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
using Moq;
using Newtonsoft.Json.Linq;
using NUnit.Framework;
using QuantConnect.Algorithm;
using QuantConnect.Brokerages;
using QuantConnect.Interfaces;
using QuantConnect.Lean.Engine.Setup.MultiAccount;
using QuantConnect.Orders;
using QuantConnect.Securities;

namespace QuantConnect.Tests.Engine.Setup.MultiAccount
{
    [TestFixture]
    public class MultiAccountConfigurationServiceTests
    {
        private MultiAccountConfigurationService _service;

        [SetUp]
        public void SetUp()
        {
            _service = new MultiAccountConfigurationService();
        }

        [Test]
        public void ParseSingleBrokerageConfigSucceeds()
        {
            // Arrange
            var json = @"{
                'accounts': {
                    'account1': 10000,
                    'account2': 20000
                },
                'router': {
                    'type': 'market',
                    'mappings': {
                        'binance': 'account1',
                        'gate': 'account2'
                    }
                }
            }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USDT");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act
            var result = _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm);

            // Assert
            Assert.IsNotNull(result);
            Assert.IsFalse(result.IsMultiBrokerageMode);
            Assert.AreEqual(2, result.AccountInitialCash.Count);
            Assert.AreEqual(10000m, result.AccountInitialCash["account1"]);
            Assert.AreEqual(20000m, result.AccountInitialCash["account2"]);
            Assert.AreEqual(2, result.AccountCurrencies.Count);
            Assert.AreEqual("USDT", result.AccountCurrencies["account1"]);
            Assert.AreEqual("USDT", result.AccountCurrencies["account2"]);
            Assert.IsNotNull(result.Router);
            Assert.IsInstanceOf<MarketBasedRouter>(result.Router);
        }

        [Test]
        public void ParseSingleBrokerageConfigThrowsOnMissingAccounts()
        {
            // Arrange
            var json = @"{ 'router': { 'type': 'market', 'mappings': {} } }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USD");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act & Assert
            Assert.Throws<ArgumentException>(() =>
                _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm));
        }

        [Test]
        public void ValidateConfigurationSucceeds()
        {
            // Arrange
            var config = new MultiAccountConfigurationService.MultiAccountConfiguration
            {
                AccountInitialCash = new Dictionary<string, decimal>
                {
                    { "account1", 10000m },
                    { "account2", 20000m }
                },
                AccountCurrencies = new Dictionary<string, string>
                {
                    { "account1", "USDT" },
                    { "account2", "USDT" }
                }
            };

            // Act & Assert - should not throw
            Assert.DoesNotThrow(() => _service.ValidateConfiguration(config));
        }

        [Test]
        public void ValidateConfigurationThrowsOnNullCurrencies()
        {
            // Arrange
            var config = new MultiAccountConfigurationService.MultiAccountConfiguration
            {
                AccountInitialCash = new Dictionary<string, decimal> { { "account1", 10000m } },
                AccountCurrencies = null
            };

            // Act & Assert
            var ex = Assert.Throws<InvalidOperationException>(() => _service.ValidateConfiguration(config));
            Assert.That(ex.Message, Does.Contain("AccountCurrencies is empty"));
        }

        [Test]
        public void ValidateConfigurationThrowsOnEmptyCurrencies()
        {
            // Arrange
            var config = new MultiAccountConfigurationService.MultiAccountConfiguration
            {
                AccountInitialCash = new Dictionary<string, decimal> { { "account1", 10000m } },
                AccountCurrencies = new Dictionary<string, string>()
            };

            // Act & Assert
            var ex = Assert.Throws<InvalidOperationException>(() => _service.ValidateConfiguration(config));
            Assert.That(ex.Message, Does.Contain("AccountCurrencies is empty"));
        }

        [Test]
        public void ValidateConfigurationThrowsOnMissingCurrency()
        {
            // Arrange
            var config = new MultiAccountConfigurationService.MultiAccountConfiguration
            {
                AccountInitialCash = new Dictionary<string, decimal>
                {
                    { "account1", 10000m },
                    { "account2", 20000m }
                },
                AccountCurrencies = new Dictionary<string, string>
                {
                    { "account1", "USDT" }
                    // account2 is missing
                }
            };

            // Act & Assert
            var ex = Assert.Throws<InvalidOperationException>(() => _service.ValidateConfiguration(config));
            Assert.That(ex.Message, Does.Contain("account2"));
            Assert.That(ex.Message, Does.Contain("missing currency mapping"));
        }

        [Test]
        public void ValidateConfigurationThrowsOnEmptyCurrencyValue()
        {
            // Arrange
            var config = new MultiAccountConfigurationService.MultiAccountConfiguration
            {
                AccountInitialCash = new Dictionary<string, decimal> { { "account1", 10000m } },
                AccountCurrencies = new Dictionary<string, string> { { "account1", "" } }
            };

            // Act & Assert
            var ex = Assert.Throws<InvalidOperationException>(() => _service.ValidateConfiguration(config));
            Assert.That(ex.Message, Does.Contain("account1"));
            Assert.That(ex.Message, Does.Contain("empty currency"));
        }

        [Test]
        public void CreateMarketBasedRouterSucceeds()
        {
            // Arrange
            var json = @"{
                'accounts': {
                    'account1': 10000
                },
                'router': {
                    'type': 'market',
                    'mappings': {
                        'binance': 'account1'
                    }
                }
            }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USDT");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act
            var result = _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm);

            // Assert
            Assert.IsNotNull(result.Router);
            Assert.IsInstanceOf<MarketBasedRouter>(result.Router);
        }

        [Test]
        public void CreateSecurityTypeRouterSucceeds()
        {
            // Arrange
            var json = @"{
                'accounts': {
                    'account1': 10000
                },
                'router': {
                    'type': 'securitytype',
                    'mappings': {
                        'Crypto': 'account1'
                    }
                }
            }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USDT");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act
            var result = _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm);

            // Assert
            Assert.IsNotNull(result.Router);
            Assert.IsInstanceOf<SecurityTypeRouter>(result.Router);
        }

        [Test]
        public void RouterCreationThrowsOnEmptyMappings()
        {
            // Arrange
            var json = @"{
                'accounts': {
                    'account1': 10000
                },
                'router': {
                    'type': 'market',
                    'mappings': {}
                }
            }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USDT");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm));
            Assert.That(ex.Message, Does.Contain("mappings"));
        }

        [Test]
        public void RouterCreationThrowsOnUnknownRouterType()
        {
            // Arrange
            var json = @"{
                'accounts': {
                    'account1': 10000
                },
                'router': {
                    'type': 'unknown',
                    'mappings': {
                        'binance': 'account1'
                    }
                }
            }";
            var configToken = JToken.Parse(json);

            var mockBrokerageFactory = new Mock<IBrokerageFactory>();
            var mockBrokerageModel = new Mock<IBrokerageModel>();
            mockBrokerageModel.Setup(m => m.DefaultAccountCurrency).Returns("USDT");
            mockBrokerageFactory.Setup(f => f.GetBrokerageModel(It.IsAny<IOrderProvider>()))
                .Returns(mockBrokerageModel.Object);

            var algorithm = new QCAlgorithm();

            // Act & Assert
            var ex = Assert.Throws<ArgumentException>(() =>
                _service.ParseSingleBrokerageConfig(configToken, mockBrokerageFactory.Object, algorithm));
            Assert.That(ex.Message, Does.Contain("Unknown router type"));
        }
    }
}
