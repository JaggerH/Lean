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
using System.Collections.Specialized;
using System.Linq;
using QuantConnect.Securities;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Manages a collection of trading pairs with automatic updates
    /// </summary>
    public partial class TradingPairManager : IEnumerable<TradingPair>, INotifyCollectionChanged
    {
        /// <summary>
        /// Event fired when a trading pair is added or removed from the collection
        /// </summary>
        public event NotifyCollectionChangedEventHandler CollectionChanged;
        private readonly SecurityManager _securities;
        private readonly IOrderProvider _transactions;
        private readonly Dictionary<(Symbol, Symbol), TradingPair> _pairs;

        /// <summary>
        /// Gets the number of trading pairs in the manager
        /// </summary>
        public int Count => _pairs.Count;

        /// <summary>
        /// Initializes a new instance of the <see cref="TradingPairManager"/> class
        /// </summary>
        /// <param name="securities">The security manager containing all securities</param>
        /// <param name="transactions">The order provider for order operations</param>
        public TradingPairManager(SecurityManager securities, IOrderProvider transactions)
        {
            _securities = securities ?? throw new ArgumentNullException(nameof(securities));
            _transactions = transactions ?? throw new ArgumentNullException(nameof(transactions));
            _pairs = new Dictionary<(Symbol, Symbol), TradingPair>();
        }

        /// <summary>
        /// Adds a new trading pair or returns an existing one
        /// </summary>
        /// <param name="leg1">The first leg symbol</param>
        /// <param name="leg2">The second leg symbol</param>
        /// <param name="pairType">The type of trading pair (default: "spread")</param>
        /// <returns>The created or existing trading pair</returns>
        public TradingPair AddPair(Symbol leg1, Symbol leg2, string pairType = "spread")
        {
            var key = (leg1, leg2);

            if (_pairs.TryGetValue(key, out var existingPair))
            {
                return existingPair;
            }

            // Ensure both securities exist
            if (!_securities.ContainsKey(leg1))
            {
                throw new ArgumentException($"Security for symbol {leg1} not found in SecurityManager");
            }
            if (!_securities.ContainsKey(leg2))
            {
                throw new ArgumentException($"Security for symbol {leg2} not found in SecurityManager");
            }

            var pair = new TradingPair(
                leg1, leg2,
                pairType,
                _securities[leg1],
                _securities[leg2]
            );

            _pairs[key] = pair;
            OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Add, pair));

            return pair;
        }

        /// <summary>
        /// Gets a trading pair by its symbol tuple
        /// </summary>
        /// <param name="key">The tuple of (leg1, leg2) symbols</param>
        /// <returns>The trading pair if found</returns>
        public TradingPair this[(Symbol, Symbol) key]
        {
            get
            {
                if (_pairs.TryGetValue(key, out var pair))
                {
                    return pair;
                }
                throw new KeyNotFoundException($"Trading pair {key.Item1}-{key.Item2} not found");
            }
        }

        /// <summary>
        /// Tries to get a trading pair by its symbol tuple
        /// </summary>
        public bool TryGetValue((Symbol, Symbol) key, out TradingPair pair)
        {
            return _pairs.TryGetValue(key, out pair);
        }

        /// <summary>
        /// Removes a trading pair
        /// </summary>
        /// <param name="leg1">The first leg symbol</param>
        /// <param name="leg2">The second leg symbol</param>
        /// <returns>True if the pair was removed, false if not found</returns>
        public bool RemovePair(Symbol leg1, Symbol leg2)
        {
            var key = (leg1, leg2);
            if (_pairs.TryGetValue(key, out var pair))
            {
                _pairs.Remove(key);
                OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Remove, pair));
                return true;
            }
            return false;
        }

        /// <summary>
        /// Updates all trading pairs with current security data
        /// </summary>
        public void UpdateAll()
        {
            foreach (var pair in _pairs.Values)
            {
                pair.Update();
            }
        }

        /// <summary>
        /// Gets all trading pairs
        /// </summary>
        public IEnumerable<TradingPair> GetAll()
        {
            return _pairs.Values;
        }

        /// <summary>
        /// Gets all trading pairs in a specific market state
        /// </summary>
        public IEnumerable<TradingPair> GetByState(MarketState state)
        {
            return _pairs.Values.Where(p => p.MarketState == state);
        }

        /// <summary>
        /// Gets all crossed trading pairs (arbitrage opportunities)
        /// </summary>
        public IEnumerable<TradingPair> GetCrossedPairs()
        {
            return GetByState(MarketState.Crossed);
        }

        /// <summary>
        /// Clears all trading pairs
        /// </summary>
        public void Clear()
        {
            _pairs.Clear();
            OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }

        /// <summary>
        /// Raises the CollectionChanged event
        /// </summary>
        /// <param name="e">Event arguments for the CollectionChanged event</param>
        protected virtual void OnCollectionChanged(NotifyCollectionChangedEventArgs e)
        {
            CollectionChanged?.Invoke(this, e);
        }

        /// <summary>
        /// Returns an enumerator that iterates through the trading pairs
        /// </summary>
        public IEnumerator<TradingPair> GetEnumerator()
        {
            return _pairs.Values.GetEnumerator();
        }

        /// <summary>
        /// Returns an enumerator that iterates through the trading pairs
        /// </summary>
        IEnumerator IEnumerable.GetEnumerator()
        {
            return GetEnumerator();
        }
    }
}