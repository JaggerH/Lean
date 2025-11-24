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
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Grid trading functionality extension for TradingPair.
    /// This partial class adds grid-based trading support to the TradingPair class,
    /// mirroring LEAN's Security → SecurityHolding pattern with TradingPair → GridPosition.
    /// </summary>
    public partial class TradingPair
    {
        /// <summary>
        /// Grid level pair configurations for this trading pair.
        /// Each GridLevelPair defines an entry and exit trigger.
        /// </summary>
        public List<GridLevelPair> LevelPairs { get; }

        /// <summary>
        /// Adds a grid level pair configuration to this trading pair.
        /// </summary>
        /// <param name="levelPair">The grid level pair to add</param>
        public void AddLevelPair(GridLevelPair levelPair)
        {
            if (levelPair == null)
            {
                throw new ArgumentNullException(nameof(levelPair));
            }

            LevelPairs.Add(levelPair);
        }

        /// <summary>
        /// Adds a grid level pair with entry/exit spread thresholds.
        /// </summary>
        /// <param name="entrySpread">Entry spread threshold (e.g., -0.01 for -1%)</param>
        /// <param name="exitSpread">Exit spread threshold (e.g., 0.02 for 2%)</param>
        /// <param name="direction">Spread direction (LongSpread, ShortSpread, or FlatSpread)</param>
        /// <param name="positionSizePct">Position size as percentage of portfolio (e.g., 0.5 for 50%)</param>
        /// <returns>The created GridLevelPair</returns>
        public GridLevelPair AddLevelPair(
            decimal entrySpread,
            decimal exitSpread,
            SpreadDirection direction,
            decimal positionSizePct = 0.5m)
        {
            // Convert SpreadDirection enum to string for GridLevelPair constructor
            string directionString = direction == SpreadDirection.LongSpread ? "LONG_SPREAD" : "SHORT_SPREAD";

            var levelPair = new GridLevelPair(
                entrySpread,
                exitSpread,
                directionString,
                positionSizePct,
                (Leg1Symbol, Leg2Symbol)  // Pass trading pair symbols for validation
            );

            LevelPairs.Add(levelPair);
            return levelPair;
        }

        /// <summary>
        /// Active grid positions indexed by Tag (encoded grid configuration).
        /// Key format: "{Symbol1.ID}|{Symbol2.ID}|{EntrySpread}|{ExitSpread}|{Direction}|{PositionSize}"
        /// Example: "BTCUSD 8O|MSTR 2T|-0.0200|0.0050|LONG_SPREAD|0.2500"
        ///
        /// This Tag-based indexing enables:
        /// - Direct lookup from Order.Tag without re-parsing
        /// - Self-contained position identification
        /// - Automatic recovery after algorithm restart
        /// </summary>
        public Dictionary<string, GridPosition> GridPositions { get; }

        /// <summary>
        /// Gets or creates a grid position for the specified level pair.
        /// Uses EncodeGridTag() to generate the dictionary key.
        /// </summary>
        /// <param name="levelPair">The grid level pair (entry and exit configuration)</param>
        /// <returns>Existing or newly created grid position</returns>
        public GridPosition GetOrCreatePosition(GridLevelPair levelPair)
        {
            if (levelPair == null)
            {
                throw new ArgumentNullException(nameof(levelPair));
            }

            // Return existing position if found
            if (TryGetPosition(levelPair, out var existingPosition, out var tag))
            {
                return existingPosition;
            }

            // Create new position
            var newPosition = new GridPosition(
                this,
                levelPair
            );

            GridPositions[tag] = newPosition;
            return newPosition;
        }

        /// <summary>
        /// Tries to get an existing grid position by Tag.
        /// </summary>
        /// <param name="tag">The Tag (from Order.Tag or EncodeGridTag)</param>
        /// <param name="position">Output parameter for the found position</param>
        /// <returns>True if position exists, false otherwise</returns>
        public bool TryGetPosition(string tag, out GridPosition position)
        {
            return GridPositions.TryGetValue(tag, out position);
        }

        /// <summary>
        /// Tries to get an existing grid position by GridLevelPair.
        /// Encodes the Tag internally using EncodeGridTag().
        /// </summary>
        /// <param name="levelPair">The grid level pair to search for</param>
        /// <param name="position">Output parameter for the found position</param>
        /// <param name="tag">Output parameter for the encoded tag</param>
        /// <returns>True if position exists, false otherwise</returns>
        public bool TryGetPosition(GridLevelPair levelPair, out GridPosition position, out string tag)
        {
            tag = TradingPairManager.EncodeGridTag(Leg1Symbol, Leg2Symbol, levelPair);
            return GridPositions.TryGetValue(tag, out position);
        }

        /// <summary>
        /// Removes a grid position from tracking.
        /// Typically called when a position is fully closed and cleaned up.
        /// </summary>
        /// <param name="position">The position to remove</param>
        /// <returns>True if position was removed, false if it didn't exist</returns>
        public bool RemovePosition(GridPosition position)
        {
            if (position == null)
            {
                throw new ArgumentNullException(nameof(position));
            }

            // Find the key by matching the position
            foreach (var kvp in GridPositions)
            {
                if (kvp.Value == position)
                {
                    return GridPositions.Remove(kvp.Key);
                }
            }

            return false;
        }

        /// <summary>
        /// Removes a grid position by its Tag.
        /// </summary>
        /// <param name="tag">The Tag (from Order.Tag or EncodeGridTag)</param>
        /// <returns>True if position was removed, false if it didn't exist</returns>
        public bool RemovePosition(string tag)
        {
            return GridPositions.Remove(tag);
        }

        /// <summary>
        /// Gets the count of active grid positions.
        /// </summary>
        public int ActivePositionCount => GridPositions.Count;

        /// <summary>
        /// Checks if there are any active grid positions.
        /// </summary>
        public bool HasActivePositions => GridPositions.Count > 0;
    }
}
