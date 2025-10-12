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
using QuantConnect.Logging;

namespace QuantConnect.Orders
{
    /// <summary>
    /// Routes orders based on the Symbol's Market (USA, Kraken, Binance, etc.)
    /// This is the recommended router for multi-exchange/multi-brokerage strategies.
    /// </summary>
    public class MarketBasedRouter : IOrderRouter
    {
        private readonly Dictionary<string, string> _marketToAccount;
        private readonly string _defaultAccount;

        /// <summary>
        /// Creates a new market-based router
        /// </summary>
        /// <param name="marketMappings">Dictionary mapping market names to account names</param>
        /// <param name="defaultAccount">Default account for unmapped markets</param>
        public MarketBasedRouter(Dictionary<string, string> marketMappings, string defaultAccount)
        {
            // Use case-insensitive dictionary to handle "USA" vs "usa", "Kraken" vs "kraken"
            _marketToAccount = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (marketMappings != null)
            {
                foreach (var kvp in marketMappings)
                {
                    _marketToAccount[kvp.Key] = kvp.Value;
                }
            }
            _defaultAccount = defaultAccount ?? throw new ArgumentNullException(nameof(defaultAccount));
        }

        /// <summary>
        /// Routes an order based on its symbol's market
        /// </summary>
        /// <param name="order">The order to route</param>
        /// <returns>The account name that should handle this order</returns>
        public string Route(Order order)
        {
            var market = order.Symbol.ID.Market;

            if (_marketToAccount.TryGetValue(market, out var accountName))
            {
                return accountName;
            }

            return _defaultAccount;
        }

        /// <summary>
        /// Validates that the router has a valid default account
        /// </summary>
        /// <returns>True if the configuration is valid</returns>
        public bool Validate()
        {
            return !string.IsNullOrEmpty(_defaultAccount);
        }
    }
}
