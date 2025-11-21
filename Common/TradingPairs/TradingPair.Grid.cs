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
        /// Grid level configurations for this trading pair.
        /// Each GridLevelPair defines an entry and exit trigger.
        /// </summary>
        public List<GridLevelPair> GridLevels { get; }

        /// <summary>
        /// Active grid positions indexed by entry level's natural key.
        /// Key format: "{spread}|{direction}|{type}" (e.g., "-0.0200|LONG_SPREAD|ENTRY")
        /// </summary>
        public Dictionary<string, GridPosition> GridPositions { get; }

        /// <summary>
        /// Initializes grid collections in the constructor.
        /// This must be called from TradingPair's main constructor.
        /// </summary>
        private void InitializeGridCollections()
        {
            // These are initialized in the field declarations above
            // This method is a placeholder for future initialization logic if needed
        }

        /// <summary>
        /// Gets or creates a grid position for the specified level pair.
        /// Uses the entry level's NaturalKey as the dictionary key to ensure
        /// only one position exists per entry level.
        /// </summary>
        /// <param name="levelPair">The grid level pair (entry and exit configuration)</param>
        /// <param name="time">Position open time</param>
        /// <returns>Existing or newly created grid position</returns>
        public GridPosition GetOrCreatePosition(GridLevelPair levelPair, DateTime time)
        {
            if (levelPair == null)
            {
                throw new ArgumentNullException(nameof(levelPair));
            }

            // Use entry level's natural key for indexing
            string key = levelPair.Entry.NaturalKey;

            // Return existing position if found
            if (GridPositions.TryGetValue(key, out var existingPosition))
            {
                return existingPosition;
            }

            // Create new position
            var newPosition = new GridPosition(
                Leg1Symbol,
                Leg2Symbol,
                levelPair,
                time
            );

            GridPositions[key] = newPosition;
            return newPosition;
        }

        /// <summary>
        /// Tries to get an existing grid position by entry level.
        /// </summary>
        /// <param name="entryLevel">The entry level to look up</param>
        /// <param name="position">Output parameter for the found position</param>
        /// <returns>True if position exists, false otherwise</returns>
        public bool TryGetPosition(GridLevel entryLevel, out GridPosition position)
        {
            return GridPositions.TryGetValue(entryLevel.NaturalKey, out position);
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
        /// Removes a grid position by its entry level's natural key.
        /// </summary>
        /// <param name="entryLevelKey">The natural key of the entry level</param>
        /// <returns>True if position was removed, false if it didn't exist</returns>
        public bool RemovePosition(string entryLevelKey)
        {
            return GridPositions.Remove(entryLevelKey);
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
