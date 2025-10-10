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
using System.Linq;
using QuantConnect.Interfaces;
using QuantConnect.Securities;

namespace QuantConnect.Orders
{
    /// <summary>
    /// Spread Market Order Type - executes multiple correlated trades simultaneously at market prices.
    /// Designed for arbitrage and spread trading strategies where atomic execution across legs is critical.
    ///
    /// Note: This is a simplified version that works with GroupOrderManager to achieve atomicity.
    /// Each leg is created as a separate MarketOrder with the same GroupOrderManager,
    /// which ensures all legs pass pre-validation together and are submitted atomically.
    /// </summary>
    public class SpreadMarketOrder : MarketOrder
    {
        /// <summary>
        /// Spread Market Order Type
        /// </summary>
        public override OrderType Type => OrderType.SpreadMarket;

        /// <summary>
        /// Creates a new instance of SpreadMarketOrder
        /// </summary>
        public SpreadMarketOrder() : base()
        {
        }

        /// <summary>
        /// Creates a new instance of SpreadMarketOrder with specified parameters
        /// </summary>
        /// <param name="symbol">The symbol for this leg of the spread order</param>
        /// <param name="quantity">The actual quantity to trade (not a multiplier)</param>
        /// <param name="time">The time the order was placed</param>
        /// <param name="groupOrderManager">The group order manager linking all legs together</param>
        /// <param name="tag">Optional order tag</param>
        /// <param name="properties">Optional order properties</param>
        public SpreadMarketOrder(Symbol symbol, decimal quantity, DateTime time, GroupOrderManager groupOrderManager, string tag = "", IOrderProperties properties = null)
            : base(symbol, quantity, time, tag, properties)
        {
            GroupOrderManager = groupOrderManager;
        }

        /// <summary>
        /// Creates a deep-copy clone of this order
        /// </summary>
        public override Order Clone()
        {
            var order = new SpreadMarketOrder();
            CopyTo(order);
            return order;
        }

        /// <summary>
        /// Returns a string representation of the order
        /// </summary>
        public override string ToString()
        {
            var groupInfo = GroupOrderManager != null
                ? $" [Group {GroupOrderManager.Id}, Leg {Array.IndexOf(GroupOrderManager.OrderIds.ToArray(), Id) + 1}/{GroupOrderManager.Count}]"
                : "";
            return $"{base.ToString()}{groupInfo}";
        }
    }
}
