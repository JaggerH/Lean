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

namespace QuantConnect.Securities
{
    /// <summary>
    /// A CashBook implementation that routes currency lookups to the appropriate sub-account
    /// in a multi-account portfolio setup.
    ///
    /// This class enables transparent access to currency balances across multiple sub-accounts,
    /// automatically routing crypto asset currencies (e.g., AAPL, TSLA) to their respective
    /// sub-account CashBooks while maintaining backward compatibility with existing code.
    /// </summary>
    public class RoutingCashBook : CashBook
    {
        private readonly CashBook _mainCashBook;
        private readonly Dictionary<string, SecurityPortfolioManager> _subAccounts;
        private readonly Dictionary<string, SecurityManager> _subAccountSecurityManagers;

        /// <summary>
        /// Creates a new RoutingCashBook that routes currency access to appropriate sub-accounts
        /// </summary>
        /// <param name="mainCashBook">The main portfolio's CashBook</param>
        /// <param name="subAccounts">Dictionary of sub-account portfolios</param>
        /// <param name="subAccountSecurityManagers">Dictionary of sub-account security managers</param>
        public RoutingCashBook(
            CashBook mainCashBook,
            Dictionary<string, SecurityPortfolioManager> subAccounts,
            Dictionary<string, SecurityManager> subAccountSecurityManagers)
        {
            _mainCashBook = mainCashBook ?? throw new ArgumentNullException(nameof(mainCashBook));
            _subAccounts = subAccounts ?? throw new ArgumentNullException(nameof(subAccounts));
            _subAccountSecurityManagers = subAccountSecurityManagers ?? throw new ArgumentNullException(nameof(subAccountSecurityManagers));

            // Set account currency to match main CashBook
            AccountCurrency = _mainCashBook.AccountCurrency;
        }

        /// <summary>
        /// Gets the Cash instance for the specified currency symbol, routing to the correct sub-account
        /// </summary>
        /// <param name="symbol">Currency symbol (e.g., "USD", "AAPL", "TSLA")</param>
        /// <returns>Cash instance from the appropriate CashBook</returns>
        public override Cash this[string symbol]
        {
            get
            {
                // Route to the correct sub-account based on the currency symbol
                var targetCashBook = GetTargetCashBook(symbol);

                if (targetCashBook == null)
                {
                    // Fallback to main CashBook
                    return _mainCashBook[symbol];
                }

                return targetCashBook[symbol];
            }
            set
            {
                // Delegate to main CashBook for backward compatibility
                _mainCashBook[symbol] = value;
            }
        }

        /// <summary>
        /// Determines which CashBook should handle the specified currency symbol
        /// </summary>
        /// <param name="currencySymbol">Currency symbol to lookup</param>
        /// <returns>The CashBook that owns this currency, or null to use main CashBook</returns>
        private CashBook GetTargetCashBook(string currencySymbol)
        {
            // Strategy:
            // 1. Check if this currency is a crypto asset (AAPL, TSLA, etc.)
            //    by looking for a corresponding crypto Symbol in sub-account SecurityManagers
            // 2. If found, return that sub-account's CashBook
            // 3. Otherwise, return null (will use main CashBook)

            foreach (var accountKvp in _subAccountSecurityManagers)
            {
                var accountName = accountKvp.Key;
                var securityManager = accountKvp.Value;

                // Look for a crypto security with this BaseCurrency
                foreach (var secKvp in securityManager)
                {
                    var security = secKvp.Value;

                    // Check if this is a crypto security with matching BaseCurrency
                    if (security is IBaseCurrencySymbol baseCurrencySymbol &&
                        baseCurrencySymbol.BaseCurrency.Symbol == currencySymbol)
                    {
                        // Found it! Return this sub-account's CashBook
                        return _subAccounts[accountName].CashBook;
                    }
                }
            }

            // Not a crypto asset currency, use main CashBook
            return null;
        }

        /// <summary>
        /// Checks if the CashBook contains the specified currency
        /// </summary>
        public override bool ContainsKey(string symbol)
        {
            var targetCashBook = GetTargetCashBook(symbol);
            return targetCashBook != null
                ? targetCashBook.ContainsKey(symbol)
                : _mainCashBook.ContainsKey(symbol);
        }

        /// <summary>
        /// Tries to get the Cash instance for the specified symbol
        /// </summary>
        public override bool TryGetValue(string symbol, out Cash value)
        {
            var targetCashBook = GetTargetCashBook(symbol);
            return targetCashBook != null
                ? targetCashBook.TryGetValue(symbol, out value)
                : _mainCashBook.TryGetValue(symbol, out value);
        }

        /// <summary>
        /// Gets the count of currencies in the main CashBook
        /// </summary>
        /// <remarks>
        /// For simplicity, we return the main CashBook's count.
        /// A full implementation could aggregate counts across all sub-accounts.
        /// </remarks>
        public override int Count => _mainCashBook.Count;

        /// <summary>
        /// Gets all currency symbols from the main CashBook
        /// </summary>
        /// <remarks>
        /// For simplicity, we return the main CashBook's keys.
        /// A full implementation could aggregate keys across all sub-accounts.
        /// </remarks>
        public ICollection<string> Keys => _mainCashBook.Keys;

        /// <summary>
        /// Gets all Cash instances from the main CashBook
        /// </summary>
        /// <remarks>
        /// For simplicity, we return the main CashBook's values.
        /// A full implementation could aggregate values across all sub-accounts.
        /// </remarks>
        public ICollection<Cash> Values => _mainCashBook.Values;

        /// <summary>
        /// Adds a currency to the main CashBook
        /// </summary>
        public Cash Add(string symbol, decimal quantity, decimal conversionRate)
        {
            return _mainCashBook.Add(symbol, quantity, conversionRate);
        }

        /// <summary>
        /// Returns a string representation of this CashBook
        /// </summary>
        public override string ToString()
        {
            return _mainCashBook.ToString();
        }
    }
}
