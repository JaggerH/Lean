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
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Securities;
using QuantConnect.Securities.Equity;
using QuantConnect.Securities.Crypto;

namespace QuantConnect.Tests.Brokerages
{
    [TestFixture]
    public class RoutedBrokerageModelLeverageTests
    {
        /// <summary>
        /// 集成测试: 验证RoutedBrokerageModel正确路由不同证券到不同的BrokerageModel，
        /// 并且每个BrokerageModel返回正确的杠杆比率
        /// </summary>
        [Test]
        public void RoutedBrokerageModel_RoutesDifferentSecurities_WithCorrectLeverage()
        {
            // === Arrange ===
            // 创建两个BrokerageModel，杠杆不同
            var ibkrModel = new InteractiveBrokersBrokerageModel(AccountType.Margin); // 2x for stocks
            var gateModel = new GateBrokerageModel(AccountType.Margin); // 25x for crypto

            // 创建市场到BrokerageModel的映射
            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { Market.USA, ibkrModel },
                { Market.Gate, gateModel }
            };

            // 创建RoutedBrokerageModel
            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel);

            // === Act ===
            // 创建美股证券 (Market.USA)
            var tslaSymbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA);
            var tsla = new Equity(
                tslaSymbol,
                SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork),
                new Cash("USD", 0, 1),
                SymbolProperties.GetDefault("USD"),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            // 添加非内部订阅配置
            var tslaConfig = new SubscriptionDataConfig(
                typeof(TradeBar),
                tslaSymbol,
                Resolution.Minute,
                TimeZones.NewYork,
                TimeZones.NewYork,
                true,
                true,
                false // isInternalFeed = false
            );
            tsla.AddData(tslaConfig);

            // 创建Gate加密货币证券 (Market.Gate)
            var btcSymbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Gate);
            var btc = new Crypto(
                btcSymbol,
                SecurityExchangeHours.AlwaysOpen(TimeZones.Utc),
                new Cash("USDT", 0, 1),
                new Cash("BTC", 0, 50000),
                SymbolProperties.GetDefault("USDT"),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            // 添加非内部订阅配置
            var btcConfig = new SubscriptionDataConfig(
                typeof(TradeBar),
                btcSymbol,
                Resolution.Minute,
                TimeZones.Utc,
                TimeZones.Utc,
                true,
                true,
                false // isInternalFeed = false
            );
            btc.AddData(btcConfig);

            // === Assert ===
            // 1. 验证TSLA通过RoutedBrokerageModel获取IBKR的2x杠杆
            var tslaLeverage = routedModel.GetLeverage(tsla);
            Assert.AreEqual(2m, tslaLeverage,
                "TSLA (Market.USA) should route to IBKR and get 2x leverage");

            // 2. 验证BTCUSDT通过RoutedBrokerageModel获取Gate的25x杠杆
            var btcLeverage = routedModel.GetLeverage(btc);
            Assert.AreEqual(25m, btcLeverage,
                "BTCUSDT (Market.Gate) should route to Gate and get 25x leverage");

            // 3. 验证DefaultMarkets正确合并
            Assert.IsNotNull(routedModel.DefaultMarkets);
            Assert.AreEqual(Market.USA, routedModel.DefaultMarkets[SecurityType.Equity],
                "Default market for Equity should be USA");
            Assert.AreEqual(Market.Gate, routedModel.DefaultMarkets[SecurityType.Crypto],
                "Default market for Crypto should be Gate");

            // 4. 验证路由是基于证券的Market属性
            Assert.AreEqual(Market.USA, tsla.Symbol.ID.Market);
            Assert.AreEqual(Market.Gate, btc.Symbol.ID.Market);
        }

        /// <summary>
        /// 测试验证RoutedBrokerageModel对不同账户返回不同的基础货币
        /// </summary>
        [Test]
        public void RoutedBrokerageModel_DifferentAccounts_HaveCorrectBaseCurrencies()
        {
            // === Arrange ===
            var ibkrModel = new InteractiveBrokersBrokerageModel();
            var gateModel = new GateBrokerageModel();

            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { Market.USA, ibkrModel },
                { Market.Gate, gateModel }
            };

            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel);

            // === Assert ===
            // 验证IBKR使用USD作为基础货币
            Assert.AreEqual("USD", ibkrModel.DefaultAccountCurrency,
                "IBKR should use USD as base currency");

            // 验证Gate使用USDT作为基础货币
            Assert.AreEqual("USDT", gateModel.DefaultAccountCurrency,
                "Gate should use USDT as base currency");

            // 验证RoutedBrokerageModel合并了DefaultMarkets
            Assert.IsTrue(routedModel.DefaultMarkets.ContainsKey(SecurityType.Equity));
            Assert.IsTrue(routedModel.DefaultMarkets.ContainsKey(SecurityType.Crypto));
        }

        /// <summary>
        /// 测试验证在Cash账户类型下杠杆为1x
        /// </summary>
        [Test]
        public void RoutedBrokerageModel_CashAccountType_Returns1xLeverage()
        {
            // === Arrange ===
            var ibkrCashModel = new InteractiveBrokersBrokerageModel(AccountType.Cash);
            var gateCashModel = new GateBrokerageModel(AccountType.Cash);

            var marketToBrokerageModel = new Dictionary<string, IBrokerageModel>
            {
                { Market.USA, ibkrCashModel },
                { Market.Gate, gateCashModel }
            };

            var routedModel = new RoutedBrokerageModel(marketToBrokerageModel);

            // 创建证券
            var tslaSymbol = Symbol.Create("TSLA", SecurityType.Equity, Market.USA);
            var tsla = new Equity(
                tslaSymbol,
                SecurityExchangeHours.AlwaysOpen(TimeZones.NewYork),
                new Cash("USD", 0, 1),
                SymbolProperties.GetDefault("USD"),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            var tslaConfig = new SubscriptionDataConfig(
                typeof(TradeBar),
                tslaSymbol,
                Resolution.Minute,
                TimeZones.NewYork,
                TimeZones.NewYork,
                true,
                true,
                false
            );
            tsla.AddData(tslaConfig);

            var btcSymbol = Symbol.Create("BTCUSDT", SecurityType.Crypto, Market.Gate);
            var btc = new Crypto(
                btcSymbol,
                SecurityExchangeHours.AlwaysOpen(TimeZones.Utc),
                new Cash("USDT", 0, 1),
                new Cash("BTC", 0, 50000),
                SymbolProperties.GetDefault("USDT"),
                ErrorCurrencyConverter.Instance,
                RegisteredSecurityDataTypesProvider.Null,
                new SecurityCache()
            );

            var btcConfig = new SubscriptionDataConfig(
                typeof(TradeBar),
                btcSymbol,
                Resolution.Minute,
                TimeZones.Utc,
                TimeZones.Utc,
                true,
                true,
                false
            );
            btc.AddData(btcConfig);

            // === Assert ===
            // Cash账户类型应该返回1x杠杆
            var tslaLeverage = routedModel.GetLeverage(tsla);
            var btcLeverage = routedModel.GetLeverage(btc);

            Assert.AreEqual(1m, tslaLeverage,
                "TSLA in Cash account should have 1x leverage");
            Assert.AreEqual(1m, btcLeverage,
                "BTCUSDT in Cash account should have 1x leverage");
        }
    }
}
