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

using System.Collections.Generic;
using System.Linq;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Represents changes to the trading pairs collection (additions and removals).
    /// Similar to SecurityChanges for LEAN Framework consistency.
    /// </summary>
    public class TradingPairChanges
    {
        /// <summary>
        /// Gets the trading pairs that were added to the collection
        /// </summary>
        public IReadOnlyList<TradingPair> AddedPairs { get; }

        /// <summary>
        /// Gets the trading pairs that were removed from the collection
        /// </summary>
        public IReadOnlyList<TradingPair> RemovedPairs { get; }

        /// <summary>
        /// Gets a value indicating whether there were any changes (additions or removals)
        /// </summary>
        public bool HasChanges => AddedPairs.Count > 0 || RemovedPairs.Count > 0;

        /// <summary>
        /// Initializes a new instance of the <see cref="TradingPairChanges"/> class
        /// </summary>
        /// <param name="addedPairs">The trading pairs that were added</param>
        /// <param name="removedPairs">The trading pairs that were removed</param>
        public TradingPairChanges(IEnumerable<TradingPair> addedPairs, IEnumerable<TradingPair> removedPairs)
        {
            AddedPairs = addedPairs?.ToList() ?? new List<TradingPair>();
            RemovedPairs = removedPairs?.ToList() ?? new List<TradingPair>();
        }

        /// <summary>
        /// Gets an empty TradingPairChanges instance (no changes)
        /// </summary>
        public static readonly TradingPairChanges None = new TradingPairChanges(null, null);

        /// <summary>
        /// Returns a string representation of the changes
        /// </summary>
        public override string ToString()
        {
            return $"Added: {AddedPairs.Count}, Removed: {RemovedPairs.Count}";
        }
    }
}
