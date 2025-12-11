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
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Execution
{
    /// <summary>
    /// Monitoring and logging functionality for ArbitrageExecutionModel
    /// </summary>
    public partial class ArbitrageExecutionModel
    {
        /// <summary>
        /// Represents a pending order about to be placed
        /// </summary>
        protected class PendingOrder
        {
            /// <summary>
            /// The symbol for this order
            /// </summary>
            public Symbol Symbol { get; set; }

            /// <summary>
            /// The quantity to order
            /// </summary>
            public decimal Quantity { get; set; }

            /// <summary>
            /// The remaining quantity before this order (for sweep orders)
            /// </summary>
            public decimal? Remaining { get; set; }
        }

        /// <summary>
        /// Context information for order placement
        /// </summary>
        protected class OrderContext
        {
            /// <summary>
            /// Type of order: "Matched" or "Sweep"
            /// </summary>
            public string OrderType { get; set; }

            /// <summary>
            /// Average spread percentage (for matched orders)
            /// </summary>
            public decimal? Spread { get; set; }

            /// <summary>
            /// Matching strategy used (for matched orders)
            /// </summary>
            public string Strategy { get; set; }

            /// <summary>
            /// Reason for sweep order (for sweep orders)
            /// </summary>
            public string Reason { get; set; }
        }

        /// <summary>
        /// Called before placing orders. Override this method to customize logging behavior.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        /// <param name="orders">The pending orders to be placed</param>
        /// <param name="context">Context information about the orders</param>
        protected virtual void OnPlacingOrders(
            AQCAlgorithm algorithm,
            IArbitragePortfolioTarget target,
            IEnumerable<PendingOrder> orders,
            OrderContext context)
        {
            var ordersList = orders.ToList();
            if (!ordersList.Any()) return;

            // Get current positions
            var (currentQty1, currentQty2) = GetCurrentQuantities(algorithm, target);

            // Determine if opening or closing
            var isClosing = target.Leg1Quantity == 0 && target.Leg2Quantity == 0;

            // Build order info
            var orderInfoParts = new List<string>();
            foreach (var order in ordersList)
            {
                var security = algorithm.Securities[order.Symbol];
                // IMPORTANT: Must account for ContractMultiplier for futures contracts
                var orderMv = Math.Abs(order.Quantity) * security.Price * security.SymbolProperties.ContractMultiplier;

                var orderInfo = $"{order.Symbol}={security.Price:F2}x{order.Quantity:F2}(${orderMv:F0})";
                if (order.Remaining.HasValue)
                {
                    orderInfo = $"{order.Symbol}: Remaining={order.Remaining.Value:F4} Order={security.Price:F2}x{order.Quantity:F2}(${orderMv:F0})";
                }
                orderInfoParts.Add(orderInfo);
            }

            // Build position info
            string positionInfo;
            if (context.OrderType == "Sweep")
            {
                // For sweep orders, just show the affected leg
                var order = ordersList.First();
                var currentQty = order.Symbol == target.Leg1Symbol ? currentQty1 : currentQty2;
                var afterQty = currentQty + order.Quantity;
                positionInfo = $"Position: {order.Symbol}: {currentQty:F2}→{afterQty:F2}/0";
            }
            else if (isClosing)
            {
                // Closing: show current→after/0 (X% closed)
                var leg1Order = ordersList.FirstOrDefault(o => o.Symbol == target.Leg1Symbol);
                var leg2Order = ordersList.FirstOrDefault(o => o.Symbol == target.Leg2Symbol);

                var afterQty1 = currentQty1 + (leg1Order?.Quantity ?? 0);
                var afterQty2 = currentQty2 + (leg2Order?.Quantity ?? 0);

                var leg1ClosePct = currentQty1 != 0 ? Math.Abs((leg1Order?.Quantity ?? 0) / currentQty1) : 0;
                var leg2ClosePct = currentQty2 != 0 ? Math.Abs((leg2Order?.Quantity ?? 0) / currentQty2) : 0;
                var avgClosePct = (leg1ClosePct + leg2ClosePct) / 2;

                positionInfo = $"Position: {target.Leg1Symbol}: {currentQty1:F2}→{afterQty1:F2}/0({avgClosePct:P0} closed) " +
                               $"{target.Leg2Symbol}: {currentQty2:F2}→{afterQty2:F2}/0({avgClosePct:P0} closed)";
            }
            else
            {
                // Opening: show current→after/target (X%)
                var leg1Order = ordersList.FirstOrDefault(o => o.Symbol == target.Leg1Symbol);
                var leg2Order = ordersList.FirstOrDefault(o => o.Symbol == target.Leg2Symbol);

                var afterQty1 = currentQty1 + (leg1Order?.Quantity ?? 0);
                var afterQty2 = currentQty2 + (leg2Order?.Quantity ?? 0);

                var leg1Progress = target.Leg1Quantity != 0 ? Math.Abs(afterQty1 / target.Leg1Quantity) : 0;
                var leg2Progress = target.Leg2Quantity != 0 ? Math.Abs(afterQty2 / target.Leg2Quantity) : 0;
                var avgProgress = (leg1Progress + leg2Progress) / 2;

                positionInfo = $"Position: {target.Leg1Symbol}: {currentQty1:F2}→{afterQty1:F2}/{target.Leg1Quantity:F2}({avgProgress:P0}) " +
                               $"{target.Leg2Symbol}: {currentQty2:F2}→{afterQty2:F2}/{target.Leg2Quantity:F2}({avgProgress:P0})";
            }

            // Build context info
            var contextInfo = new List<string>();
            if (context.Spread.HasValue)
            {
                contextInfo.Add($"spread={context.Spread.Value:P2}");
            }
            if (!string.IsNullOrEmpty(context.Strategy))
            {
                contextInfo.Add($"strategy={context.Strategy}");
            }
            if (!string.IsNullOrEmpty(context.Reason))
            {
                contextInfo.Add($"reason={context.Reason}");
            }
            contextInfo.Add($"tag={target.Tag}");

            // Build final log message
            var logMessage = $"ArbitrageExecutionModel: Placing {context.OrderType.ToLower()} orders | " +
                             $"Order: {string.Join(" ", orderInfoParts)} | " +
                             $"{positionInfo} | " +
                             $"{string.Join(" ", contextInfo)}";

            algorithm.Debug(logMessage);
        }
    }
}
