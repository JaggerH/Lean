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
 *
*/

using System.Linq;
using QuantConnect.Securities;
using QuantConnect.Interfaces;
using QuantConnect.Orders;

namespace QuantConnect.Util
{
    /// <summary>
    /// Provides useful infrastructure methods to the <see cref="Security"/> class.
    /// These are added in this way to avoid mudding the class's public API
    /// </summary>
    public static class SecurityExtensions
    {
        /// <summary>
        /// Determines if all subscriptions for the security are internal feeds
        /// </summary>
        public static bool IsInternalFeed(this Security security)
        {
            return security.Subscriptions.All(x => x.IsInternalFeed);
        }

        /// <summary>
        /// Gets the portfolio manager for the account that would handle orders for the given symbol.
        /// In single-account scenarios, returns the main portfolio.
        /// In multi-account scenarios, uses the order router to determine the target account.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="symbol">The symbol to route</param>
        /// <returns>The portfolio manager for the account that handles this symbol</returns>
        public static SecurityPortfolioManager GetPortfolioForSymbol(
            this IAlgorithm algorithm, Symbol symbol)
        {
            if (algorithm.Portfolio is MultiSecurityPortfolioManager multiPortfolio)
            {
                // Create a temporary order to determine routing
                var tempOrder = new MarketOrder(symbol, 0, algorithm.UtcTime);

                // Access the router via reflection (it's a private field)
                var router = multiPortfolio.GetType()
                    .GetField("_router", System.Reflection.BindingFlags.NonPublic |
                                         System.Reflection.BindingFlags.Instance)
                    ?.GetValue(multiPortfolio) as IOrderRouter;

                if (router != null)
                {
                    var accountName = router.Route(tempOrder);
                    return multiPortfolio.GetAccount(accountName);
                }
            }

            return algorithm.Portfolio;
        }
    }
}
