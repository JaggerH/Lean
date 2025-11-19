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

namespace QuantConnect.Securities.MultiAccount
{
    /// <summary>
    /// Registry for USD-pegged stablecoins that should use 1:1 conversion rate
    /// </summary>
    /// <remarks>
    /// This is different from <see cref="Currencies.IsStableCoinWithoutPair"/> which checks
    /// if a trading PAIR exists (e.g., "USDTUSD" in a specific market). This registry checks
    /// if a single CURRENCY is pegged 1:1 to USD for conversion purposes.
    ///
    /// Used in multi-account mode to prevent creating conversion subscriptions for stablecoins
    /// that are already 1:1 with USD.
    /// </remarks>
    public static class UsdPeggedStablecoinRegistry
    {
        private static readonly HashSet<string> _usdPeggedStablecoins = new HashSet<string>
        {
            "USDT",  // Tether
            "USDC",  // USD Coin
            "BUSD",  // Binance USD
            "DAI",   // Dai
            "TUSD",  // TrueUSD
            "USDP"   // Pax Dollar
        };

        /// <summary>
        /// Checks if a currency is pegged 1:1 to USD
        /// </summary>
        /// <param name="currency">The currency code to check</param>
        /// <returns>True if the currency is USD-pegged</returns>
        public static bool IsUsdPegged(string currency)
        {
            return _usdPeggedStablecoins.Contains(currency);
        }

        /// <summary>
        /// Gets the USD conversion rate for a currency
        /// </summary>
        /// <param name="currency">The currency code</param>
        /// <returns>1.0 if the currency is USD-pegged, 0 otherwise</returns>
        public static decimal GetUsdConversionRate(string currency)
        {
            return IsUsdPegged(currency) ? 1.0m : 0m;
        }
    }
}
