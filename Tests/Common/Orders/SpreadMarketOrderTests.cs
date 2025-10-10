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
using System.Linq;
using NUnit.Framework;
using QuantConnect.Orders;
using QuantConnect.Securities;

namespace QuantConnect.Tests.Common.Orders
{
    [TestFixture]
    public class SpreadMarketOrderTests
    {
        [Test]
        public void SpreadMarketOrderCreation()
        {
            var btcusd = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            var ethusd = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);

            var groupOrderManager = new GroupOrderManager(1, 2, 1, 0);
            var time = new DateTime(2024, 1, 1);

            var order = new SpreadMarketOrder(btcusd, 1, time, groupOrderManager, "test spread order");

            Assert.AreEqual(OrderType.SpreadMarket, order.Type);
            Assert.AreEqual(btcusd, order.Symbol);
            Assert.AreEqual(1, order.Quantity);
            Assert.AreEqual("test spread order", order.Tag);
            Assert.AreEqual(groupOrderManager, order.GroupOrderManager);
        }

        [Test]
        public void SpreadMarketOrderWithMultipleOrders()
        {
            // Test that multiple SpreadMarketOrders can be created with the same GroupOrderManager
            var btcusd = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);
            var ethusd = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Coinbase);

            var groupOrderManager = new GroupOrderManager(1, 2, 1, 0);
            var time = new DateTime(2024, 1, 1);

            var order1 = new SpreadMarketOrder(btcusd, 1, time, groupOrderManager);
            var order2 = new SpreadMarketOrder(ethusd, -1, time, groupOrderManager);

            Assert.AreEqual(OrderType.SpreadMarket, order1.Type);
            Assert.AreEqual(OrderType.SpreadMarket, order2.Type);
            Assert.AreEqual(groupOrderManager, order1.GroupOrderManager);
            Assert.AreEqual(groupOrderManager, order2.GroupOrderManager);
            Assert.AreEqual(btcusd, order1.Symbol);
            Assert.AreEqual(1, order1.Quantity);
            Assert.AreEqual(ethusd, order2.Symbol);
            Assert.AreEqual(-1, order2.Quantity);
        }

        [Test]
        public void SpreadMarketOrderClone()
        {
            var btcusd = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

            var groupOrderManager = new GroupOrderManager(1, 2, 1, 0);
            var time = new DateTime(2024, 1, 1);

            var order = new SpreadMarketOrder(btcusd, 1, time, groupOrderManager, "original");

            var clone = (SpreadMarketOrder)order.Clone();

            Assert.AreEqual(order.Type, clone.Type);
            Assert.AreEqual(order.Symbol, clone.Symbol);
            Assert.AreEqual(order.Quantity, clone.Quantity);
            Assert.AreEqual(order.Tag, clone.Tag);
            Assert.AreEqual(order.GroupOrderManager, clone.GroupOrderManager);

            // Ensure it's a deep copy
            Assert.AreNotSame(order, clone);
        }

        [Test]
        public void SpreadMarketOrderToString()
        {
            var btcusd = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

            var groupOrderManager = new GroupOrderManager(1, 2, 1, 0);
            var time = new DateTime(2024, 1, 1);

            var order = new SpreadMarketOrder(btcusd, 1, time, groupOrderManager);
            order.Id = 1;
            groupOrderManager.OrderIds.Add(order.Id);

            var str = order.ToString();

            Assert.IsTrue(str.Contains("SpreadMarket"));
            Assert.IsTrue(str.Contains("BTCUSD"));
            Assert.IsTrue(str.Contains("Group"));
        }

        [Test]
        public void SpreadMarketOrderApplyUpdateRequest()
        {
            var btcusd = Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Coinbase);

            var groupOrderManager = new GroupOrderManager(1, 1, 1, 0);
            var time = new DateTime(2024, 1, 1);

            var order = new SpreadMarketOrder(btcusd, 1, time, groupOrderManager);
            order.Id = 1;

            var updateRequest = new UpdateOrderRequest(time, 1, new UpdateOrderFields { Quantity = 2 });
            order.ApplyUpdateOrderRequest(updateRequest);

            Assert.AreEqual(2, order.Quantity);
        }
    }
}
