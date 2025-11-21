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
using Newtonsoft.Json;

namespace QuantConnect.TradingPairs.Grid
{
    /// <summary>
    /// Represents a grid trading level configuration (entry or exit trigger).
    /// Implemented as a struct (value type) for immutability and efficient copying.
    /// Does NOT store Symbol information - used within TradingPair context.
    /// </summary>
    public struct GridLevel
    {
        /// <summary>
        /// Spread percentage trigger level (e.g., -0.02 for -2%)
        /// </summary>
        [JsonProperty("spread_pct")]
        public decimal SpreadPct { get; }

        /// <summary>
        /// Trade direction: "LONG_SPREAD" or "SHORT_SPREAD"
        /// </summary>
        [JsonProperty("direction")]
        public string Direction { get; }

        /// <summary>
        /// Level type: "ENTRY" or "EXIT"
        /// </summary>
        [JsonProperty("type")]
        public string Type { get; }

        /// <summary>
        /// Position size as percentage of portfolio (e.g., 0.25 for 25%)
        /// </summary>
        [JsonProperty("position_size_pct")]
        public decimal PositionSizePct { get; }

        /// <summary>
        /// Creates a new grid level
        /// </summary>
        /// <param name="spreadPct">Spread percentage trigger</param>
        /// <param name="direction">Trade direction (LONG_SPREAD or SHORT_SPREAD)</param>
        /// <param name="type">Level type (ENTRY or EXIT)</param>
        /// <param name="positionSizePct">Position size percentage</param>
        public GridLevel(
            decimal spreadPct,
            string direction,
            string type,
            decimal positionSizePct)
        {
            SpreadPct = spreadPct;
            Direction = direction ?? throw new ArgumentNullException(nameof(direction));
            Type = type ?? throw new ArgumentNullException(nameof(type));
            PositionSizePct = positionSizePct;

            // Validate direction
            if (direction != "LONG_SPREAD" && direction != "SHORT_SPREAD")
            {
                throw new ArgumentException($"Invalid direction: {direction}. Must be LONG_SPREAD or SHORT_SPREAD.", nameof(direction));
            }

            // Validate type
            if (type != "ENTRY" && type != "EXIT")
            {
                throw new ArgumentException($"Invalid type: {type}. Must be ENTRY or EXIT.", nameof(type));
            }
        }

        /// <summary>
        /// Natural key for this grid level, used for position indexing within a TradingPair.
        /// Format: "{spread}|{direction}|{type}"
        /// Example: "-0.0200|LONG_SPREAD|ENTRY"
        ///
        /// NOTE: Does not include pair information - unique within a TradingPair context.
        /// </summary>
        [JsonIgnore]
        public string NaturalKey => $"{SpreadPct:F4}|{Direction}|{Type}";

        /// <summary>
        /// Human-readable display name for logging and debugging.
        /// Requires external pairKey parameter since GridLevel doesn't store Symbol info.
        /// Format: "{pair} {arrow} {spread}%"
        /// Example: "BTC-MSTR → -2.0%"
        /// </summary>
        /// <param name="pairKey">Trading pair key (e.g., "BTCUSD-MSTR")</param>
        /// <returns>Display name string</returns>
        public string GetDisplayName(string pairKey)
        {
            string arrow = Type == "ENTRY" ? "→" : "←";
            string spreadStr = $"{SpreadPct * 100:+0.0;-0.0;0.0}%";
            return $"{pairKey} {arrow} {spreadStr}";
        }

        /// <summary>
        /// String representation for debugging
        /// </summary>
        public override string ToString()
        {
            string arrow = Type == "ENTRY" ? "→" : "←";
            return $"GridLevel({arrow} {SpreadPct * 100:+0.0;-0.0}%, {Direction}, Size: {PositionSizePct:P0})";
        }
    }
}
