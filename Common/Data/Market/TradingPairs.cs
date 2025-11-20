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
using QuantConnect.TradingPairs;

namespace QuantConnect.Data.Market
{
    /// <summary>
    /// Collection of TradingPair objects for use in data slices, similar to TradeBars, QuoteBars, etc.
    /// This provides a time-slice snapshot of all trading pairs at a specific moment.
    /// </summary>
    public class TradingPairs : DataDictionary<TradingPair>
    {
        // Store pairs by tuple key for type-safe access
        private readonly Dictionary<(Symbol, Symbol), TradingPair> _pairsByTuple;

        /// <summary>
        /// Initializes a new instance of the <see cref="TradingPairs"/> class
        /// </summary>
        public TradingPairs() : base()
        {
            _pairsByTuple = new Dictionary<(Symbol, Symbol), TradingPair>();
        }

        /// <summary>
        /// Initializes a new instance of the <see cref="TradingPairs"/> class
        /// </summary>
        /// <param name="time">The time associated with this collection</param>
        public TradingPairs(DateTime time) : base(time)
        {
            _pairsByTuple = new Dictionary<(Symbol, Symbol), TradingPair>();
        }

        /// <summary>
        /// Adds a trading pair to the collection
        /// </summary>
        /// <param name="pair">The trading pair to add</param>
        public void Add(TradingPair pair)
        {
            // Create a composite symbol for the DataDictionary base class
            // This allows us to maintain compatibility with existing Lean patterns
            // Use Symbol.Value (ticker) to avoid spaces in the composite symbol
            var compositeSymbol = Symbol.Create(
                $"{pair.Leg1Symbol.Value}-{pair.Leg2Symbol.Value}",
                SecurityType.Base,
                pair.Leg1Symbol.ID.Market,
                baseDataType: typeof(TradingPair)
            );

            base[compositeSymbol] = pair;
            _pairsByTuple[(pair.Leg1Symbol, pair.Leg2Symbol)] = pair;
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
                if (_pairsByTuple.TryGetValue(key, out var pair))
                {
                    return pair;
                }
                throw new KeyNotFoundException($"Trading pair ({key.Item1}, {key.Item2}) not found");
            }
            set
            {
                _pairsByTuple[key] = value;
                // Also update the base dictionary
                // Use Symbol.Value (ticker) to avoid spaces in the composite symbol
                var compositeSymbol = Symbol.Create(
                    $"{value.Leg1Symbol.Value}-{value.Leg2Symbol.Value}",
                    SecurityType.Base,
                    value.Leg1Symbol.ID.Market,
                    baseDataType: typeof(TradingPair)
                );
                base[compositeSymbol] = value;
            }
        }

        /// <summary>
        /// Tries to get a trading pair by its symbol tuple
        /// </summary>
        public bool TryGetValue((Symbol, Symbol) key, out TradingPair pair)
        {
            return _pairsByTuple.TryGetValue(key, out pair);
        }

        /// <summary>
        /// Gets all trading pairs in a specific market state
        /// </summary>
        public IEnumerable<TradingPair> GetByState(MarketState state)
        {
            return this.Select(kvp => kvp.Value).Where(p => p.MarketState == state);
        }

        /// <summary>
        /// Gets all crossed trading pairs (arbitrage opportunities)
        /// </summary>
        public IEnumerable<TradingPair> GetCrossedPairs()
        {
            return GetByState(MarketState.Crossed);
        }

        /// <summary>
        /// Checks if the collection contains a trading pair with the given tuple key
        /// </summary>
        public bool ContainsKey((Symbol, Symbol) key)
        {
            return _pairsByTuple.ContainsKey(key);
        }

        /// <summary>
        /// Returns an enumerator that iterates through the trading pairs
        /// </summary>
        public IEnumerator<TradingPair> GetEnumerator()
        {
            return _pairsByTuple.Values.GetEnumerator();
        }
    }
}