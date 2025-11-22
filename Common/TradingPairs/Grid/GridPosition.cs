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
using QuantConnect.Securities;
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
        /// Reference to parent TradingPair (for accessing securities and lot sizes).
        /// Not serialized to avoid circular references.
        /// </summary>
        [JsonIgnore]
        public TradingPair TradingPair { get; private set; }

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
        /// Creates a new grid position
        /// </summary>
        /// <param name="tradingPair">Parent trading pair</param>
        /// <param name="levelPair">Grid level pair (entry and exit)</param>
        /// <param name="openTime">Position open time</param>
        public GridPosition(TradingPair tradingPair, GridLevelPair levelPair, DateTime openTime)
        {
            TradingPair = tradingPair ?? throw new ArgumentNullException(nameof(tradingPair));
            Leg1Symbol = tradingPair.Leg1Symbol;
            Leg2Symbol = tradingPair.Leg2Symbol;
            _levelPair = levelPair ?? throw new ArgumentNullException(nameof(levelPair));
            OpenTime = openTime;

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
            GridLevelPair levelPair)
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
        }

        /// <summary>
        /// Processes order fill and updates position quantities and costs.
        /// Called by TradingPairManager.ProcessGridOrderEvent().
        /// </summary>
        /// <param name="fill">Fill event</param>
        /// <param name="ticket">Associated order ticket</param>
        public void ProcessFill(OrderEvent fill, OrderTicket ticket)
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
        /// Checks if position should exit based on current spread
        /// </summary>
        /// <param name="currentSpread">Current theoretical spread percentage</param>
        /// <returns>True if exit condition is met</returns>
        public bool ShouldExit(decimal currentSpread)
        {
            if (!Invested)
            {
                return false;  // No position to exit
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
        /// Checks if the position has any holdings (mirrors SecurityHolding.Invested).
        /// Uses each security's lot size to determine if quantity is significant.
        /// </summary>
        [JsonIgnore]
        public bool Invested
        {
            get
            {
                var leg1LotSize = TradingPair?.Leg1Security?.SymbolProperties.LotSize ?? 0.01m;
                var leg2LotSize = TradingPair?.Leg2Security?.SymbolProperties.LotSize ?? 0.01m;
                return Math.Abs(Leg1Quantity) >= leg1LotSize || Math.Abs(Leg2Quantity) >= leg2LotSize;
            }
        }

        /// <summary>
        /// Sets the trading pair reference (used after deserialization to restore parent reference)
        /// </summary>
        /// <param name="tradingPair">Parent trading pair</param>
        public void SetTradingPair(TradingPair tradingPair)
        {
            TradingPair = tradingPair ?? throw new ArgumentNullException(nameof(tradingPair));
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
