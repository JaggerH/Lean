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
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using QuantConnect.Interfaces;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Collection of ArbitragePortfolioTarget keyed by Tag (not Symbol).
    /// This is fundamentally different from PortfolioTargetCollection which uses Symbol as key.
    /// Using Tag as key allows multiple grid levels for the same symbol pair to coexist.
    /// </summary>
    public class ArbitragePortfolioTargetCollection : ICollection<IArbitragePortfolioTarget>, IDictionary<string, IArbitragePortfolioTarget>
    {
        private List<IArbitragePortfolioTarget> _enumerable;
        private List<KeyValuePair<string, IArbitragePortfolioTarget>> _kvpEnumerable;
        private readonly Dictionary<string, IArbitragePortfolioTarget> _targets = new();

        /// <summary>
        /// Gets the number of targets in this collection
        /// </summary>
        public int Count
        {
            get
            {
                lock (_targets)
                {
                    return _targets.Count;
                }
            }
        }

        /// <summary>
        /// True if there is no target in the collection
        /// </summary>
        public bool IsEmpty
        {
            get
            {
                lock (_targets)
                {
                    return _targets.Count == 0;
                }
            }
        }

        /// <summary>
        /// Gets `false`. This collection is not read-only.
        /// </summary>
        public bool IsReadOnly => false;

        /// <summary>
        /// Gets the tag keys for this collection
        /// </summary>
        public ICollection<string> Keys
        {
            get
            {
                lock (_targets)
                {
                    return _targets.Keys.ToList();
                }
            }
        }

        /// <summary>
        /// Gets the values in this collection
        /// </summary>
        public ICollection<IArbitragePortfolioTarget> Values
        {
            get
            {
                lock (_targets)
                {
                    return _targets.Values.ToList();
                }
            }
        }

        /// <summary>
        /// Indexer to get/set a target by tag
        /// </summary>
        public IArbitragePortfolioTarget this[string tag]
        {
            get
            {
                lock (_targets)
                {
                    return _targets[tag];
                }
            }
            set
            {
                lock (_targets)
                {
                    _targets[tag] = value;
                    _enumerable = null;
                    _kvpEnumerable = null;
                }
            }
        }

        /// <summary>
        /// Adds a range of targets to the collection.
        /// New targets with the same Tag will overwrite existing ones.
        /// </summary>
        /// <param name="targets">The targets to add</param>
        public void AddRange(IArbitragePortfolioTarget[] targets)
        {
            if (targets == null)
            {
                return;
            }

            lock (_targets)
            {
                foreach (var target in targets)
                {
                    if (target == null)
                    {
                        continue;
                    }

                    _targets[target.Tag] = target;
                    _enumerable = null;
                    _kvpEnumerable = null;
                }
            }
        }

        /// <summary>
        /// Gets all targets in insertion order (no specific ordering in first version).
        /// Future versions may add ordering by margin impact if needed.
        /// </summary>
        /// <returns>Enumerable of all targets</returns>
        public IEnumerable<IArbitragePortfolioTarget> GetTargets()
        {
            return _targets.Values;
        }

        /// <summary>
        /// Clears fulfilled targets based on GridPosition quantities.
        /// A target is considered fulfilled when:
        /// 1. Both legs have reached their target delta quantities (within lot size tolerance)
        /// 2. No pending open orders exist for this Tag
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        public void ClearFulfilled(IAlgorithm algorithm)
        {
            var toRemove = new List<string>();

            foreach (var kvp in _targets)
            {
                var tag = kvp.Key;
                var target = kvp.Value;

                // Check if both legs are fulfilled
                bool leg1Fulfilled = IsLegFulfilled(algorithm, target, isLeg1: true);
                bool leg2Fulfilled = IsLegFulfilled(algorithm, target, isLeg1: false);

                if (leg1Fulfilled && leg2Fulfilled)
                {
                    toRemove.Add(tag);
                }
            }

            foreach (var tag in toRemove)
            {
                _targets.Remove(tag);
            }
        }

        /// <summary>
        /// Checks if a specific leg of the target is fulfilled
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The target to check</param>
        /// <param name="isLeg1">True to check leg1, false to check leg2</param>
        /// <returns>True if the leg is fulfilled</returns>
        private bool IsLegFulfilled(IAlgorithm algorithm, IArbitragePortfolioTarget target, bool isLeg1)
        {
            var symbol = isLeg1 ? target.Leg1Symbol : target.Leg2Symbol;
            var targetDelta = isLeg1 ? target.Leg1Quantity : target.Leg2Quantity;

            // Get GridPosition from Tag
            if (!(algorithm is Interfaces.AIAlgorithm aiAlgorithm))
            {
                return false;
            }

            if (!TradingPairs.TradingPairManager.TryDecodeGridTag(
                target.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
            {
                return false;
            }

            if (!aiAlgorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
            {
                return false;
            }

            var position = pair.GetOrCreatePosition(levelPair);
            var currentQty = isLeg1 ? position.Leg1Quantity : position.Leg2Quantity;

            // Simplified: assume initial position = 0
            // Future optimization: add InitialLeg1Quantity/InitialLeg2Quantity to GridPosition
            var alreadyTraded = currentQty;

            // Only count open orders with same Tag to avoid cross-contamination between grid levels
            var openOrdersQty = GetOpenOrderQuantityForTag(algorithm, symbol, target.Tag);

            // Get lot size for tolerance check
            if (!algorithm.Securities.ContainsKey(symbol))
            {
                return false;
            }

            var security = algorithm.Securities[symbol];
            var lotSize = security.SymbolProperties.LotSize;

            // Check if target is fulfilled within lot size tolerance
            return Math.Abs(targetDelta - alreadyTraded) < lotSize
                   && Math.Abs(openOrdersQty) < lotSize;
        }

        /// <summary>
        /// Gets the total open order quantity for a specific symbol and tag.
        /// Only counts orders with matching Tag to support per-position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="symbol">The symbol to check</param>
        /// <param name="tag">The tag to filter by</param>
        /// <returns>Total open order quantity for this tag</returns>
        private decimal GetOpenOrderQuantityForTag(IAlgorithm algorithm, Symbol symbol, string tag)
        {
            // Use GetOpenOrderTickets to access QuantityRemaining
            return algorithm.Transactions.GetOpenOrderTickets(symbol)
                .Where(o => o.Tag == tag)
                .Sum(o => o.QuantityRemaining);
        }

        /// <summary>
        /// Clears all targets from the collection
        /// </summary>
        public void Clear()
        {
            _targets.Clear();
        }

        /// <summary>
        /// Checks if a target exists for the given tag
        /// </summary>
        /// <param name="tag">The tag to check</param>
        /// <returns>True if target exists</returns>
        public bool ContainsTag(string tag)
        {
            return _targets.ContainsKey(tag);
        }

        /// <summary>
        /// Tries to get a target by tag
        /// </summary>
        /// <param name="tag">The tag to look up</param>
        /// <param name="target">The target if found</param>
        /// <returns>True if target was found</returns>
        public bool TryGetTarget(string tag, out IArbitragePortfolioTarget target)
        {
            if (_targets.TryGetValue(tag, out var iTarget))
            {
                target = iTarget as ArbitragePortfolioTarget;
                return target != null;
            }
            target = null;
            return false;
        }

        #region ICollection<IArbitragePortfolioTarget> Implementation

        public void Add(IArbitragePortfolioTarget item)
        {
            lock (_targets)
            {
                _targets[item.Tag] = item;
                _enumerable = null;
                _kvpEnumerable = null;
            }
        }

        public bool Contains(IArbitragePortfolioTarget item)
        {
            lock (_targets)
            {
                return _targets.ContainsKey(item.Tag) && _targets[item.Tag] == item;
            }
        }

        public void CopyTo(IArbitragePortfolioTarget[] array, int arrayIndex)
        {
            lock (_targets)
            {
                _targets.Values.CopyTo(array, arrayIndex);
            }
        }

        public bool Remove(IArbitragePortfolioTarget item)
        {
            lock (_targets)
            {
                if (_targets.TryGetValue(item.Tag, out var existing) && existing == item)
                {
                    _targets.Remove(item.Tag);
                    _enumerable = null;
                    _kvpEnumerable = null;
                    return true;
                }
                return false;
            }
        }

        public IEnumerator<IArbitragePortfolioTarget> GetEnumerator()
        {
            lock (_targets)
            {
                if (_enumerable == null)
                {
                    _enumerable = _targets.Values.ToList();
                }
                return _enumerable.GetEnumerator();
            }
        }

        IEnumerator IEnumerable.GetEnumerator()
        {
            return GetEnumerator();
        }

        #endregion

        #region IDictionary<string, IArbitragePortfolioTarget> Implementation

        public void Add(string key, IArbitragePortfolioTarget value)
        {
            lock (_targets)
            {
                _targets.Add(key, value);
                _enumerable = null;
                _kvpEnumerable = null;
            }
        }

        public bool ContainsKey(string key)
        {
            lock (_targets)
            {
                return _targets.ContainsKey(key);
            }
        }

        public bool Remove(string key)
        {
            lock (_targets)
            {
                var result = _targets.Remove(key);
                if (result)
                {
                    _enumerable = null;
                    _kvpEnumerable = null;
                }
                return result;
            }
        }

        public bool TryGetValue(string key, out IArbitragePortfolioTarget value)
        {
            lock (_targets)
            {
                return _targets.TryGetValue(key, out value);
            }
        }

        public void Add(KeyValuePair<string, IArbitragePortfolioTarget> item)
        {
            Add(item.Key, item.Value);
        }

        public bool Contains(KeyValuePair<string, IArbitragePortfolioTarget> item)
        {
            lock (_targets)
            {
                return _targets.TryGetValue(item.Key, out var value) && value == item.Value;
            }
        }

        public void CopyTo(KeyValuePair<string, IArbitragePortfolioTarget>[] array, int arrayIndex)
        {
            lock (_targets)
            {
                ((ICollection<KeyValuePair<string, IArbitragePortfolioTarget>>)_targets).CopyTo(array, arrayIndex);
            }
        }

        public bool Remove(KeyValuePair<string, IArbitragePortfolioTarget> item)
        {
            lock (_targets)
            {
                if (_targets.TryGetValue(item.Key, out var value) && value == item.Value)
                {
                    _targets.Remove(item.Key);
                    _enumerable = null;
                    _kvpEnumerable = null;
                    return true;
                }
                return false;
            }
        }

        IEnumerator<KeyValuePair<string, IArbitragePortfolioTarget>> IEnumerable<KeyValuePair<string, IArbitragePortfolioTarget>>.GetEnumerator()
        {
            lock (_targets)
            {
                if (_kvpEnumerable == null)
                {
                    _kvpEnumerable = _targets.ToList();
                }
                return _kvpEnumerable.GetEnumerator();
            }
        }

        #endregion
    }
}
