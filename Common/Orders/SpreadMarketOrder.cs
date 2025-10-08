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
using QuantConnect.Interfaces;
using QuantConnect.Securities;

namespace QuantConnect.Orders
{
    /// <summary>
    /// Spread Market Order Type - executes multiple correlated trades simultaneously at market prices.
    /// Designed for arbitrage and spread trading strategies where atomic execution across legs is critical.
    /// </summary>
    public class SpreadMarketOrder : ComboOrder
    {
        /// <summary>
        /// The legs of this spread order
        /// </summary>
        public List<Leg> Legs { get; set; }

        /// <summary>
        /// Spread Market Order Type
        /// </summary>
        public override OrderType Type => OrderType.SpreadMarket;

        /// <summary>
        /// Creates a new instance of SpreadMarketOrder
        /// </summary>
        public SpreadMarketOrder() : base()
        {
            Legs = new List<Leg>();
        }

        /// <summary>
        /// Creates a new instance of SpreadMarketOrder with specified parameters
        /// </summary>
        /// <param name="symbol">The symbol (primary symbol for the order)</param>
        /// <param name="quantity">The quantity multiplier for all legs</param>
        /// <param name="time">The time the order was placed</param>
        /// <param name="groupOrderManager">The group order manager for this order</param>
        /// <param name="tag">Optional order tag</param>
        /// <param name="properties">Optional order properties</param>
        public SpreadMarketOrder(Symbol symbol, decimal quantity, DateTime time, GroupOrderManager groupOrderManager, string tag = "", IOrderProperties properties = null)
            : base(symbol, quantity, time, groupOrderManager, tag, properties)
        {
            Legs = new List<Leg>();
        }

        /// <summary>
        /// Gets the order value in units of the security's quote currency
        /// </summary>
        /// <param name="security">The security matching this order's symbol</param>
        protected override decimal GetValueImpl(Security security)
        {
            // For spread orders, the value is the sum of all leg values
            // This is a simplified calculation - actual value should consider all legs
            return Quantity * security.Price;
        }

        /// <summary>
        /// Creates a deep-copy clone of this order
        /// </summary>
        public override Order Clone()
        {
            var order = new SpreadMarketOrder
            {
                Legs = Legs?.Select(leg => Leg.Create(leg.Symbol, leg.Quantity, leg.OrderPrice)).ToList()
            };
            CopyTo(order);
            return order;
        }

        /// <summary>
        /// Returns a string representation of the order
        /// </summary>
        public override string ToString()
        {
            var legInfo = Legs != null && Legs.Any()
                ? $" with {Legs.Count} legs: [{string.Join(", ", Legs.Select(l => $"{l.Symbol}×{l.Quantity}"))}]"
                : "";
            return $"{base.ToString()}{legInfo}";
        }
    }
}
