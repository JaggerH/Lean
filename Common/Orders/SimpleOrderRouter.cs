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

namespace QuantConnect.Orders
{
    /// <summary>
    /// Simple router that routes all orders to a single account
    /// Useful for basic multi-account setups where manual routing is preferred
    /// </summary>
    public class SimpleOrderRouter : IOrderRouter
    {
        private readonly string _accountName;

        /// <summary>
        /// Creates a new simple router
        /// </summary>
        /// <param name="accountName">The account name to route all orders to</param>
        public SimpleOrderRouter(string accountName)
        {
            _accountName = accountName ?? throw new ArgumentNullException(nameof(accountName));
        }

        /// <summary>
        /// Routes all orders to the configured account
        /// </summary>
        /// <param name="order">The order to route</param>
        /// <returns>The account name</returns>
        public string Route(Order order)
        {
            return _accountName;
        }

        /// <summary>
        /// Validates that the router has a valid account name
        /// </summary>
        /// <returns>True if the configuration is valid</returns>
        public bool Validate()
        {
            return !string.IsNullOrEmpty(_accountName);
        }
    }
}
