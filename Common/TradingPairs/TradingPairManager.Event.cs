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
using QuantConnect.Orders;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Grid trading functionality extension for TradingPairManager.
    /// Manages grid position lifecycle using Order.Tag for tracking.
    /// </summary>
    public partial class TradingPairManager
    {

        #region Order Event Processing

        /// <summary>
        /// Internal context object holding parsed order information.
        /// Reduces redundant Tag parsing across multiple handlers.
        /// </summary>
        private class OrderContext
        {
            public TradingPair Pair { get; set; }
            public GridPosition Position { get; set; }  // Always non-null (created in ParseOrderContext)
            public GridLevelPair LevelPair { get; set; }
            public string Tag { get; set; }
        }

        /// <summary>
        /// Parses order context from OrderEvent.
        /// Decodes Tag, finds TradingPair, and gets or creates GridPosition.
        /// </summary>
        /// <param name="orderEvent">The order event to parse</param>
        /// <returns>OrderContext if successful, null otherwise</returns>
        private OrderContext ParseOrderContext(OrderEvent orderEvent)
        {
            var order = _transactions.GetOrderById(orderEvent.OrderId);
            if (order == null || string.IsNullOrEmpty(order.Tag))
                return null;

            // Decode Tag (single parse point) - directly get Symbols
            if (!TryDecodeGridTag(order.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
                return null;

            // Find TradingPair using Symbols
            TryGetValue((leg1Symbol, leg2Symbol), out var pair);
            if (pair == null)
                return null;

            // Get or create GridPosition for this order
            var position = pair.GetOrCreatePosition(levelPair, orderEvent.UtcTime);

            return new OrderContext
            {
                Pair = pair,
                Position = position,
                LevelPair = levelPair,
                Tag = order.Tag
            };
        }
        
        /// <summary>
        /// Processes order events and updates corresponding GridPositions.
        /// Call this from Algorithm.OnOrderEvent().
        ///
        /// Lifecycle:
        /// 1. PartiallyFilled: Update position quantities
        /// 2. Filled: Update position quantities, then clean up if empty
        /// 3. Canceled/Invalid: Clean up position if empty
        ///
        /// Note: GridPosition is automatically created when ParseOrderContext is called.
        /// </summary>
        /// <param name="orderEvent">The order event to process</param>
        public void ProcessGridOrderEvent(OrderEvent orderEvent)
        {
            // Parse order context once (avoids redundant Tag parsing)
            // This also creates GridPosition if it doesn't exist
            var context = ParseOrderContext(orderEvent);
            if (context == null)
                return; // Not a grid order or parsing failed

            // Dispatch based on order status
            switch (orderEvent.Status)
            {
                case OrderStatus.PartiallyFilled:
                    HandleOrderFilled(orderEvent, context);
                    break;

                case OrderStatus.Filled:
                    // Update position first, then clean up
                    HandleOrderFilled(orderEvent, context);
                    HandleOrderCompleted(orderEvent, context);
                    break;

                case OrderStatus.Canceled:
                case OrderStatus.Invalid:
                    HandleOrderCompleted(orderEvent, context);
                    break;

                // OrderStatus.None, OrderStatus.New, OrderStatus.Submitted, OrderStatus.UpdateSubmitted
                // are not actionable for grid positions
                default:
                    break;
            }
        }

        /// <summary>
        /// Handles order fill - updates position quantities and costs.
        /// </summary>
        /// <param name="orderEvent">Order fill event (Filled or PartiallyFilled)</param>
        /// <param name="context">Parsed order context</param>
        private void HandleOrderFilled(OrderEvent orderEvent, OrderContext context)
        {
            // Update position with fill data
            context.Position.ProcessFill(orderEvent);
        }

        /// <summary>
        /// Handles order completion (Filled/Canceled/Invalid).
        /// Removes empty positions to keep GridPositions dictionary clean.
        /// </summary>
        /// <param name="orderEvent">Order completion event</param>
        /// <param name="context">Parsed order context</param>
        private void HandleOrderCompleted(OrderEvent orderEvent, OrderContext context)
        {
            // Remove position if not invested
            if (!context.Position.Invested)
            {
                context.Pair.GridPositions.Remove(context.Tag);
            }
        }

        #endregion

    }
}
