/*
 * QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
 * Lean Algorithmic Trading Engine v2.0. Copyright 2.0 QuantConnect Corporation.
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
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Securities.CurrencyConversion;

namespace QuantConnect.Securities.MultiAccount
{
    /// <summary>
    /// Coordinates currency conversion setup and synchronization for multi-account mode
    /// </summary>
    /// <remarks>
    /// This class handles the complex task of setting up currency conversions across multiple accounts:
    /// 1. Each sub-account creates conversions based on its own AccountCurrency (e.g., Gate uses USDT not USD)
    /// 2. Main account aggregates currencies from all sub-accounts
    /// 3. Main account does NOT create its own subscriptions - it copies from sub-accounts
    /// </remarks>
    public class CurrencyConversionCoordinator
    {
        /// <summary>
        /// Sets up currency conversions for all sub-accounts
        /// </summary>
        /// <param name="multiPortfolio">The multi-account portfolio manager</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="securityService">The security service for creating conversion securities</param>
        /// <remarks>
        /// Each sub-account creates its own conversion subscriptions based on its AccountCurrency.
        /// Example: Gate account with AccountCurrency=USDT will subscribe to BTCUSDT, not BTCUSD.
        /// </remarks>
        public void SetupSubAccountConversions(
            MultiSecurityPortfolioManager multiPortfolio,
            IAlgorithm algorithm,
            ISecurityService securityService)
        {
            foreach (var kvp in multiPortfolio.SubAccounts)
            {
                var accountName = kvp.Key;
                var subAccount = kvp.Value;
                var subCashBook = subAccount.CashBook;

                Log.Trace($"CurrencyConversionCoordinator.SetupSubAccountConversions(): Account '{accountName}' (AccountCurrency={subCashBook.AccountCurrency})");

                // Create conversion subscriptions for this sub-account
                var configs = subCashBook.EnsureCurrencyDataFeeds(
                    algorithm.Securities,
                    algorithm.SubscriptionManager,
                    algorithm.BrokerageModel.DefaultMarkets,
                    SecurityChanges.None,
                    securityService);

                Log.Trace($"CurrencyConversionCoordinator.SetupSubAccountConversions(): Created {configs?.Count ?? 0} conversions for '{accountName}'");
            }
        }

        /// <summary>
        /// Synchronizes cash and conversions from sub-accounts to main account
        /// </summary>
        /// <param name="multiPortfolio">The multi-account portfolio manager</param>
        /// <remarks>
        /// CRITICAL: This method clears the main account CashBook first (removing default $100,000 USD),
        /// then aggregates all currencies from sub-accounts.
        ///
        /// Result:
        /// - If no sub-accounts have USD → main account USD = 0
        /// - If some sub-accounts have USD → main account USD = SUM(sub-account USD)
        /// </remarks>
        public void SyncConversionsToMain(MultiSecurityPortfolioManager multiPortfolio)
        {
            var baseCashBook = ((SecurityPortfolioManager)multiPortfolio).CashBook;

            // Step 1: Clear main account (remove default $100,000 USD and any other currencies)
            var currenciesToClear = baseCashBook.Keys.ToList();
            foreach (var currency in currenciesToClear)
            {
                baseCashBook[currency].SetAmount(0);
            }

            Log.Trace($"CurrencyConversionCoordinator.SyncConversionsToMain(): Cleared {currenciesToClear.Count} currencies from main account");

            // Step 2: Aggregate from sub-accounts
            var currencyTotals = new Dictionary<string, decimal>();
            var currencyConversions = new Dictionary<string, ICurrencyConversion>();

            foreach (var subAccountKvp in multiPortfolio.SubAccounts)
            {
                var accountName = subAccountKvp.Key;
                var subAccount = subAccountKvp.Value;

                Log.Trace($"CurrencyConversionCoordinator.SyncConversionsToMain(): Aggregating from '{accountName}' (AccountCurrency={subAccount.CashBook.AccountCurrency})");

                foreach (var cashKvp in subAccount.CashBook)
                {
                    var currency = cashKvp.Key;
                    var cash = cashKvp.Value;
                    var amount = cash.Amount;

                    // Aggregate amounts
                    if (!currencyTotals.ContainsKey(currency))
                    {
                        currencyTotals[currency] = 0;
                    }
                    currencyTotals[currency] += amount;

                    // Store first valid CurrencyConversion
                    if (!currencyConversions.ContainsKey(currency) &&
                        cash.CurrencyConversion != null &&
                        cash.CurrencyConversion.DestinationCurrency != null)
                    {
                        currencyConversions[currency] = cash.CurrencyConversion;
                    }
                }
            }

            // Step 3: Set aggregated values to main account
            foreach (var currencyTotal in currencyTotals)
            {
                var currency = currencyTotal.Key;
                var totalAmount = currencyTotal.Value;
                var conversionRate = UsdPeggedStablecoinRegistry.GetUsdConversionRate(currency);

                // Add or update
                if (baseCashBook.ContainsKey(currency))
                {
                    baseCashBook[currency].SetAmount(totalAmount);
                }
                else
                {
                    baseCashBook.Add(currency, totalAmount, conversionRate);
                }

                // Copy conversion from sub-account
                if (currencyConversions.ContainsKey(currency))
                {
                    baseCashBook[currency].CurrencyConversion = currencyConversions[currency];
                    Log.Trace($"CurrencyConversionCoordinator.SyncConversionsToMain(): {currency} = {totalAmount} (conversion copied from sub-account)");
                }

                // Set Identity conversion for USD-pegged stablecoins
                if (UsdPeggedStablecoinRegistry.IsUsdPegged(currency) &&
                    currency != baseCashBook.AccountCurrency)
                {
                    baseCashBook[currency].CurrencyConversion =
                        ConstantCurrencyConversion.Identity(currency, baseCashBook.AccountCurrency);

                    Log.Trace($"CurrencyConversionCoordinator.SyncConversionsToMain(): {currency} set as USD-pegged (Identity conversion)");
                }
            }

            Log.Trace($"CurrencyConversionCoordinator.SyncConversionsToMain(): Synced {currencyTotals.Count} currencies to main account");
        }
    }
}
