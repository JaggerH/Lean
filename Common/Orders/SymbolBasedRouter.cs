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
using QuantConnect.Logging;

namespace QuantConnect.Orders
{
    /// <summary>
    /// Routes orders based on symbol mapping configuration
    /// </summary>
    public class SymbolBasedRouter : IOrderRouter
    {
        private readonly Dictionary<Symbol, string> _symbolToAccount;
        private readonly string _defaultAccount;

        /// <summary>
        /// Creates a new symbol-based router
        /// </summary>
        /// <param name="symbolMappings">Dictionary mapping symbols to account names</param>
        /// <param name="defaultAccount">Default account for unmapped symbols</param>
        public SymbolBasedRouter(Dictionary<Symbol, string> symbolMappings, string defaultAccount)
        {
            _symbolToAccount = symbolMappings ?? throw new ArgumentNullException(nameof(symbolMappings));
            _defaultAccount = defaultAccount ?? throw new ArgumentNullException(nameof(defaultAccount));
        }

        /// <summary>
        /// Routes an order based on its symbol
        /// </summary>
        public string Route(Order order)
        {
            if (_symbolToAccount.TryGetValue(order.Symbol, out var accountName))
            {
                Log.Trace($"SymbolBasedRouter: Routing order {order.Id} ({order.Symbol}) to account '{accountName}'");
                return accountName;
            }

            Log.Trace($"SymbolBasedRouter: Routing order {order.Id} ({order.Symbol}) to default account '{_defaultAccount}'");
            return _defaultAccount;
        }

        /// <summary>
        /// Validates that the router has at least one mapping
        /// </summary>
        public bool Validate()
        {
            if (_symbolToAccount.Count == 0)
            {
                Log.Error("SymbolBasedRouter: No symbol mappings configured");
                return false;
            }

            if (string.IsNullOrEmpty(_defaultAccount))
            {
                Log.Error("SymbolBasedRouter: Default account not specified");
                return false;
            }

            return true;
        }
    }
}
