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
using QuantConnect.Orders;
using Newtonsoft.Json;

namespace QuantConnect.TradingPairs.Grid
{
    /// <summary>
    /// Represents an active grid trading position.
    /// Tracks quantities, costs, and associated orders for a trading pair position
    /// opened at a specific grid entry level.
    ///
    /// NOTE: This is a simplified version without lifecycle management.
    /// Status tracking (Pending/Active/Closing/Closed) will be added in Phase 3.
    /// </summary>
    public class GridPosition
    {
        /// <summary>
        /// Position open time
        /// </summary>
        [JsonProperty("open_time")]
        public DateTime OpenTime { get; private set; }

        /// <summary>
        /// First fill time (when position became active)
        /// </summary>
        [JsonProperty("first_fill_time")]
        public DateTime? FirstFillTime { get; private set; }

        /// <summary>
        /// Leg 1 symbol (automatically serialized by LEAN's SymbolJsonConverter)
        /// </summary>
        [JsonProperty("leg1_symbol")]
        public Symbol Leg1Symbol { get; private set; }

        /// <summary>
        /// Leg 2 symbol (automatically serialized by LEAN's SymbolJsonConverter)
        /// </summary>
        [JsonProperty("leg2_symbol")]
        public Symbol Leg2Symbol { get; private set; }

        /// <summary>
        /// Pair key computed from symbols
        /// </summary>
        [JsonIgnore]
        public string PairKey => $"{Leg1Symbol.Value}-{Leg2Symbol.Value}";

        /// <summary>
        /// Leg 1 (crypto) quantity
        /// </summary>
        [JsonProperty("leg1_quantity")]
        public decimal Leg1Quantity { get; private set; }

        /// <summary>
        /// Leg 2 (stock) quantity
        /// </summary>
        [JsonProperty("leg2_quantity")]
        public decimal Leg2Quantity { get; private set; }

        /// <summary>
        /// Leg 1 weighted average fill price
        /// </summary>
        [JsonProperty("leg1_average_cost")]
        public decimal Leg1AverageCost { get; private set; }

        /// <summary>
        /// Leg 2 weighted average fill price
        /// </summary>
        [JsonProperty("leg2_average_cost")]
        public decimal Leg2AverageCost { get; private set; }

        /// <summary>
        /// Grid level pair (entry and exit configuration)
        /// </summary>
        [JsonProperty("level_pair")]
        private readonly GridLevelPair _levelPair;

        /// <summary>
        /// Associated order tickets (runtime tracking)
        /// Not serialized - will be rebuilt from BrokerIds on restart
        /// </summary>
        [JsonIgnore]
        private readonly List<OrderTicket> _tickets;

        /// <summary>
        /// Read-only view of order tickets
        /// </summary>
        [JsonIgnore]
        public IReadOnlyList<OrderTicket> Tickets => _tickets.AsReadOnly();

        /// <summary>
        /// Broker order IDs (for restart recovery)
        /// These persist across algorithm restarts, unlike Lean's internal OrderIds
        /// </summary>
        [JsonProperty("broker_ids")]
        private readonly HashSet<string> _brokerIds;

        /// <summary>
        /// Read-only view of broker IDs
        /// </summary>
        [JsonIgnore]
        public IReadOnlyCollection<string> BrokerIds => _brokerIds;

        /// <summary>
        /// Creates a new grid position
        /// </summary>
        /// <param name="leg1Symbol">Leg 1 symbol</param>
        /// <param name="leg2Symbol">Leg 2 symbol</param>
        /// <param name="levelPair">Grid level pair (entry and exit)</param>
        /// <param name="openTime">Position open time</param>
        public GridPosition(Symbol leg1Symbol, Symbol leg2Symbol, GridLevelPair levelPair, DateTime openTime)
        {
            Leg1Symbol = leg1Symbol;
            Leg2Symbol = leg2Symbol;
            _levelPair = levelPair ?? throw new ArgumentNullException(nameof(levelPair));
            OpenTime = openTime;

            _tickets = new List<OrderTicket>();
            _brokerIds = new HashSet<string>();

            Leg1Quantity = 0m;
            Leg2Quantity = 0m;
            Leg1AverageCost = 0m;
            Leg2AverageCost = 0m;
        }

        /// <summary>
        /// JSON constructor for deserialization
        /// </summary>
        [JsonConstructor]
        private GridPosition(
            DateTime openTime,
            DateTime? firstFillTime,
            Symbol leg1Symbol,
            Symbol leg2Symbol,
            decimal leg1Quantity,
            decimal leg2Quantity,
            decimal leg1AverageCost,
            decimal leg2AverageCost,
            GridLevelPair levelPair,
            HashSet<string> brokerIds)
        {
            OpenTime = openTime;
            FirstFillTime = firstFillTime;
            Leg1Symbol = leg1Symbol;
            Leg2Symbol = leg2Symbol;
            Leg1Quantity = leg1Quantity;
            Leg2Quantity = leg2Quantity;
            Leg1AverageCost = leg1AverageCost;
            Leg2AverageCost = leg2AverageCost;
            _levelPair = levelPair;
            _brokerIds = brokerIds ?? new HashSet<string>();
            _tickets = new List<OrderTicket>();
        }

        /// <summary>
        /// Adds an order ticket to this position
        /// </summary>
        /// <param name="ticket">Order ticket to track</param>
        public void AddTicket(OrderTicket ticket)
        {
            if (ticket == null)
            {
                throw new ArgumentNullException(nameof(ticket));
            }

            if (!_tickets.Contains(ticket))
            {
                _tickets.Add(ticket);
            }
        }

        /// <summary>
        /// Handles order submitted event - stores broker IDs from the order
        /// </summary>
        /// <param name="order">Order object</param>
        public void OnOrderSubmitted(Order order)
        {
            if (order != null && order.BrokerId != null)
            {
                foreach (var brokerId in order.BrokerId)
                {
                    if (!string.IsNullOrEmpty(brokerId))
                    {
                        _brokerIds.Add(brokerId);
                    }
                }
            }
        }

        /// <summary>
        /// Handles order filled event - updates quantities and costs
        /// </summary>
        /// <param name="fill">Fill event</param>
        /// <param name="ticket">Associated order ticket</param>
        public void OnOrderFilled(OrderEvent fill, OrderTicket ticket)
        {
            if (FirstFillTime == null)
            {
                FirstFillTime = fill.UtcTime;
            }

            // Use Symbol.Equals for strict comparison (compares SecurityIdentifier)
            bool isLeg1 = ticket.Symbol.Equals(Leg1Symbol);

            if (isLeg1)
            {
                // Update leg 1 weighted average cost
                decimal totalCost = Leg1AverageCost * Leg1Quantity + fill.FillPrice * fill.FillQuantity;
                Leg1Quantity += fill.FillQuantity;
                Leg1AverageCost = Leg1Quantity != 0 ? totalCost / Leg1Quantity : 0m;
            }
            else
            {
                // Update leg 2 weighted average cost
                decimal totalCost = Leg2AverageCost * Leg2Quantity + fill.FillPrice * fill.FillQuantity;
                Leg2Quantity += fill.FillQuantity;
                Leg2AverageCost = Leg2Quantity != 0 ? totalCost / Leg2Quantity : 0m;
            }
        }

        /// <summary>
        /// Handles order termination (filled/canceled/invalid) - cleans up tracking
        /// </summary>
        /// <param name="order">Order object</param>
        public void OnOrderTerminated(Order order)
        {
            // Remove ticket from tracking
            _tickets.RemoveAll(t => t.OrderId == order.Id);

            // Remove broker IDs
            if (order != null && order.BrokerId != null)
            {
                foreach (var brokerId in order.BrokerId)
                {
                    if (!string.IsNullOrEmpty(brokerId))
                    {
                        _brokerIds.Remove(brokerId);
                    }
                }
            }
        }

        /// <summary>
        /// Checks if position should exit based on current spread
        /// </summary>
        /// <param name="currentSpread">Current theoretical spread percentage</param>
        /// <returns>True if exit condition is met</returns>
        public bool ShouldExit(decimal currentSpread)
        {
            if (IsEmpty)
            {
                return false;  // Already closed
            }

            if (_levelPair.Exit.Direction == "LONG_SPREAD")
            {
                // Long spread exit: close when spread rises above exit level
                return currentSpread >= _levelPair.Exit.SpreadPct;
            }
            else  // SHORT_SPREAD
            {
                // Short spread exit: close when spread falls below exit level
                return currentSpread <= _levelPair.Exit.SpreadPct;
            }
        }

        /// <summary>
        /// Checks if position is empty (no holdings)
        /// </summary>
        [JsonIgnore]
        public bool IsEmpty
        {
            get
            {
                return Math.Abs(Leg1Quantity) < 0.01m && Math.Abs(Leg2Quantity) < 0.01m;
            }
        }

        /// <summary>
        /// Finds a ticket by order ID
        /// </summary>
        /// <param name="orderId">Order ID to find</param>
        /// <returns>Matching ticket, or null if not found</returns>
        public OrderTicket FindTicket(int orderId)
        {
            return _tickets.FirstOrDefault(t => t.OrderId == orderId);
        }

        /// <summary>
        /// String representation for debugging
        /// </summary>
        public override string ToString()
        {
            string spreadStr = $"{_levelPair.Exit.SpreadPct * 100:+0.0;-0.0;0.0}%";
            return $"GridPosition({PairKey}, Leg1: {Leg1Quantity:F4} @ {Leg1AverageCost:F2}, " +
                   $"Leg2: {Leg2Quantity:F4} @ {Leg2AverageCost:F2}, Exit: {spreadStr})";
        }
    }
}
