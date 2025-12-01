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
using Newtonsoft.Json;

namespace QuantConnect.TradingPairs.Grid
{
    /// <summary>
    /// Paired grid level configuration (entry + exit).
    /// Automatically creates entry and exit levels with proper direction pairing
    /// and validates spread relationships.
    ///
    /// Note: Accepts Symbol parameters for validation but does NOT store them.
    /// GridLevel objects contain only spread/direction/type configuration.
    /// </summary>
    public class GridLevelPair
    {
        /// <summary>
        /// Entry level configuration
        /// </summary>
        [JsonProperty("entry")]
        public GridLevel Entry { get; private set; }

        /// <summary>
        /// Exit level configuration (direction is opposite to entry)
        /// </summary>
        [JsonProperty("exit")]
        public GridLevel Exit { get; private set; }

        /// <summary>
        /// Display name for the pair (requires external pairKey)
        /// </summary>
        public string GetDisplayName(string pairKey) => $"{Entry.GetDisplayName(pairKey)} ⟷ {Exit.GetDisplayName(pairKey)}";

        /// <summary>
        /// Creates a new grid level pair with auto-generated entry and exit levels.
        /// Validates spread relationships based on direction.
        /// </summary>
        /// <param name="entrySpreadPct">Entry trigger spread (e.g., -0.02 for -2%)</param>
        /// <param name="exitSpreadPct">Exit trigger spread (e.g., -0.005 for -0.5%)</param>
        /// <param name="direction">Trade direction (LONG_SPREAD or SHORT_SPREAD)</param>
        /// <param name="positionSizePct">Position size as percentage (e.g., 0.25 for 25%)</param>
        public GridLevelPair(
            decimal entrySpreadPct,
            decimal exitSpreadPct,
            string direction,
            decimal positionSizePct)
        {
            // Validate direction
            if (direction != "LONG_SPREAD" && direction != "SHORT_SPREAD")
            {
                throw new ArgumentException(
                    $"Invalid direction: {direction}. Must be LONG_SPREAD or SHORT_SPREAD.",
                    nameof(direction));
            }

            // Validate spread relationship based on direction
            ValidateSpreads(entrySpreadPct, exitSpreadPct, direction);

            // Determine exit direction (opposite of entry)
            string exitDirection = direction == "LONG_SPREAD" ? "SHORT_SPREAD" : "LONG_SPREAD";

            // Create entry level (no Symbol storage)
            Entry = new GridLevel(
                spreadPct: entrySpreadPct,
                direction: direction,
                type: "ENTRY",
                positionSizePct: positionSizePct
            );

            // Create exit level (opposite direction, negative size for closing)
            Exit = new GridLevel(
                spreadPct: exitSpreadPct,
                direction: exitDirection,
                type: "EXIT",
                positionSizePct: -positionSizePct  // Negative to close position
            );
        }

        /// <summary>
        /// JSON constructor for deserialization
        /// </summary>
        [JsonConstructor]
        private GridLevelPair(GridLevel entry, GridLevel exit)
        {
            Entry = entry;
            Exit = exit;
        }

        /// <summary>
        /// Validates spread relationship based on trading direction
        /// </summary>
        private void ValidateSpreads(decimal entrySpreadPct, decimal exitSpreadPct, string direction)
        {
            if (direction == "LONG_SPREAD")
            {
                // Long spread strategy:
                // - Entry: spread becomes negative (buy crypto, sell stock)
                // - Exit: spread returns to positive (sell crypto, buy stock)
                // Therefore: entry < 0 and exit > entry

                if (entrySpreadPct >= 0)
                {
                    throw new ArgumentException(
                        $"LONG_SPREAD entry must be negative. Got: {entrySpreadPct:P2}",
                        nameof(entrySpreadPct));
                }

                if (exitSpreadPct <= entrySpreadPct)
                {
                    throw new ArgumentException(
                        $"LONG_SPREAD exit ({exitSpreadPct:P2}) must be greater than entry ({entrySpreadPct:P2})",
                        nameof(exitSpreadPct));
                }
            }
            else  // SHORT_SPREAD
            {
                // Short spread strategy:
                // - Entry: spread becomes positive (sell crypto, buy stock)
                // - Exit: spread returns to negative (buy crypto, sell stock)
                // Therefore: entry > 0 and exit < entry

                if (entrySpreadPct <= 0)
                {
                    throw new ArgumentException(
                        $"SHORT_SPREAD entry must be positive. Got: {entrySpreadPct:P2}",
                        nameof(entrySpreadPct));
                }

                if (exitSpreadPct >= entrySpreadPct)
                {
                    throw new ArgumentException(
                        $"SHORT_SPREAD exit ({exitSpreadPct:P2}) must be less than entry ({entrySpreadPct:P2})",
                        nameof(exitSpreadPct));
                }
            }
        }

        /// <summary>
        /// String representation for debugging (requires pairKey parameter)
        /// </summary>
        public override string ToString()
        {
            return $"GridLevelPair(Entry: {Entry}, Exit: {Exit})";
        }
    }
}
