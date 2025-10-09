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
    /// Routes orders based on security type (Equity, Crypto, Forex, etc.)
    /// </summary>
    public class SecurityTypeRouter : IOrderRouter
    {
        private readonly Dictionary<SecurityType, string> _securityTypeToAccount;
        private readonly string _defaultAccount;

        /// <summary>
        /// Creates a new security type-based router
        /// </summary>
        /// <param name="securityTypeMappings">Dictionary mapping security types to account names</param>
        /// <param name="defaultAccount">Default account for unmapped security types</param>
        public SecurityTypeRouter(Dictionary<SecurityType, string> securityTypeMappings, string defaultAccount)
        {
            _securityTypeToAccount = securityTypeMappings ?? throw new ArgumentNullException(nameof(securityTypeMappings));
            _defaultAccount = defaultAccount ?? throw new ArgumentNullException(nameof(defaultAccount));
        }

        /// <summary>
        /// Routes an order based on its symbol's security type
        /// </summary>
        public string Route(Order order)
        {
            var securityType = order.Symbol.SecurityType;

            if (_securityTypeToAccount.TryGetValue(securityType, out var accountName))
            {
                Log.Trace($"SecurityTypeRouter: Routing order {order.Id} ({order.Symbol}, {securityType}) to account '{accountName}'");
                return accountName;
            }

            Log.Trace($"SecurityTypeRouter: Routing order {order.Id} ({order.Symbol}, {securityType}) to default account '{_defaultAccount}'");
            return _defaultAccount;
        }

        /// <summary>
        /// Validates that the router has at least one mapping
        /// </summary>
        public bool Validate()
        {
            if (_securityTypeToAccount.Count == 0)
            {
                Log.Error("SecurityTypeRouter: No security type mappings configured");
                return false;
            }

            if (string.IsNullOrEmpty(_defaultAccount))
            {
                Log.Error("SecurityTypeRouter: Default account not specified");
                return false;
            }

            return true;
        }
    }
}
