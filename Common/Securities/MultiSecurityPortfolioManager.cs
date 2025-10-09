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
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;

namespace QuantConnect.Securities
{
    /// <summary>
    /// Multi-account portfolio manager that maintains separate sub-portfolios for each account
    /// while providing aggregated views for backtesting and reporting
    /// </summary>
    public class MultiSecurityPortfolioManager : SecurityPortfolioManager
    {
        private readonly Dictionary<string, SecurityPortfolioManager> _subAccounts;
        private readonly Dictionary<string, SecurityManager> _subAccountSecurityManagers;
        private readonly IOrderRouter _router;

        /// <summary>
        /// Creates a new multi-account portfolio manager
        /// </summary>
        /// <param name="accountConfigs">Dictionary of account name to initial cash</param>
        /// <param name="router">Order router to determine account for each order</param>
        /// <param name="securityManager">The algorithm's security manager</param>
        /// <param name="transactionManager">The algorithm's transaction manager</param>
        /// <param name="algorithmSettings">The algorithm's settings</param>
        /// <param name="defaultOrderProperties">Default order properties</param>
        /// <param name="timeKeeper">The time keeper for synchronizing time across sub-accounts</param>
        public MultiSecurityPortfolioManager(
            Dictionary<string, decimal> accountConfigs,
            IOrderRouter router,
            SecurityManager securityManager,
            SecurityTransactionManager transactionManager,
            IAlgorithmSettings algorithmSettings,
            IOrderProperties defaultOrderProperties,
            ITimeKeeper timeKeeper)
            : base(securityManager, transactionManager, algorithmSettings, defaultOrderProperties)
        {
            if (accountConfigs == null || accountConfigs.Count == 0)
            {
                throw new ArgumentException("At least one account must be configured", nameof(accountConfigs));
            }

            _router = router ?? throw new ArgumentNullException(nameof(router));

            if (timeKeeper == null)
            {
                throw new ArgumentNullException(nameof(timeKeeper));
            }

            _subAccounts = new Dictionary<string, SecurityPortfolioManager>();
            _subAccountSecurityManagers = new Dictionary<string, SecurityManager>();

            // Initialize sub-accounts with independent SecurityManagers
            // Each sub-account has its own SecurityManager for independent Holdings tracking
            // but shares the same TimeKeeper for synchronized time management
            foreach (var config in accountConfigs)
            {
                // Create independent SecurityManager for this sub-account
                var subSecurityManager = new SecurityManager(timeKeeper);
                _subAccountSecurityManagers[config.Key] = subSecurityManager;

                var subPortfolio = new SecurityPortfolioManager(
                    subSecurityManager,
                    transactionManager,
                    algorithmSettings,
                    defaultOrderProperties);

                subPortfolio.SetCash(config.Value);
                _subAccounts[config.Key] = subPortfolio;

                Log.Trace($"MultiSecurityPortfolioManager: Initialized account '{config.Key}' with ${config.Value:N2}");
            }

            // Set aggregated cash in main portfolio
            SetCash(accountConfigs.Values.Sum());

            // Subscribe to SecurityManager changes to sync Securities to sub-accounts
            securityManager.CollectionChanged += OnSecurityManagerCollectionChanged;

            Log.Trace($"MultiSecurityPortfolioManager: Created with {_subAccounts.Count} accounts");
        }

        /// <summary>
        /// Handles SecurityManager collection changes to sync Securities to sub-accounts
        /// </summary>
        /// <remarks>
        /// Routes each Security to the appropriate sub-account based on the router configuration.
        /// This ensures each sub-account only contains Securities it will actually trade,
        /// allowing for truly independent Holdings tracking.
        /// </remarks>
        private void OnSecurityManagerCollectionChanged(object sender, System.Collections.Specialized.NotifyCollectionChangedEventArgs e)
        {
            if (e.Action == System.Collections.Specialized.NotifyCollectionChangedAction.Add)
            {
                Log.Trace($"MultiSecurityPortfolioManager.OnSecurityManagerCollectionChanged: Event triggered with {e.NewItems?.Count ?? 0} items");

                if (e.NewItems == null || e.NewItems.Count == 0)
                {
                    Log.Trace("MultiSecurityPortfolioManager.OnSecurityManagerCollectionChanged: No items to process");
                    return;
                }

                // Route each Security to its designated sub-account
                foreach (var item in e.NewItems)
                {
                    // Debug: Log the actual type of the item
                    Log.Trace($"MultiSecurityPortfolioManager.OnSecurityManagerCollectionChanged: Item type = {item?.GetType().Name ?? "null"}");

                    // FIXED: SecurityManager.Add() passes Security object, not KeyValuePair
                    if (item is Security security)
                    {
                        var symbol = security.Symbol;

                        Log.Trace($"MultiSecurityPortfolioManager: Processing Security {symbol} (Type: {symbol.SecurityType}, Market: {symbol.ID.Market})");

                        // Create a temporary order to determine routing target
                        // Using MarketOrder with quantity 0 as a routing probe
                        var tempOrder = new MarketOrder(symbol, 0, DateTime.UtcNow);
                        var targetAccount = _router.Route(tempOrder);

                        Log.Trace($"MultiSecurityPortfolioManager: Router determined target account '{targetAccount}' for {symbol}");

                        // Add the Security only to the target sub-account's SecurityManager
                        // This ensures independent Holdings: IBKR gets AAPL (stock), Kraken gets AAPLUSD (crypto)
                        if (_subAccountSecurityManagers.TryGetValue(targetAccount, out var subSecurityManager))
                        {
                            if (!subSecurityManager.ContainsKey(symbol))
                            {
                                subSecurityManager.Add(symbol, security);
                                Log.Trace($"MultiSecurityPortfolioManager: ✅ Successfully added {symbol} to account '{targetAccount}' SecurityManager");
                                Log.Trace($"MultiSecurityPortfolioManager: Account '{targetAccount}' now contains {subSecurityManager.Count} securities: [{string.Join(", ", subSecurityManager.Keys)}]");

                                // Synchronize Cash entries for Crypto/Forex securities (IBaseCurrencySymbol)
                                // This ensures sub-account CashBooks contain all necessary currencies for order fills
                                if (security is IBaseCurrencySymbol baseCurrencySymbol)
                                {
                                    var subAccount = _subAccounts[targetAccount];
                                    var subAccountCashBook = subAccount.CashBook;

                                    Log.Trace($"MultiSecurityPortfolioManager: Synchronizing Cash entries for {symbol} (IBaseCurrencySymbol)");

                                    // Sync BaseCurrency (e.g., "TSLA" for TSLAUSD crypto, "EUR" for EURUSD forex)
                                    var baseCurrencySymbolStr = baseCurrencySymbol.BaseCurrency.Symbol;
                                    if (!subAccountCashBook.ContainsKey(baseCurrencySymbolStr))
                                    {
                                        if (CashBook.ContainsKey(baseCurrencySymbolStr))
                                        {
                                            var mainCash = CashBook[baseCurrencySymbolStr];
                                            subAccountCashBook.Add(baseCurrencySymbolStr, mainCash.Amount, mainCash.ConversionRate);
                                            Log.Trace($"MultiSecurityPortfolioManager: ✅ Added {baseCurrencySymbolStr} to account '{targetAccount}' CashBook (Amount: {mainCash.Amount}, Rate: {mainCash.ConversionRate})");
                                        }
                                        else
                                        {
                                            Log.Trace($"MultiSecurityPortfolioManager: ⚠️ BaseCurrency {baseCurrencySymbolStr} not found in main CashBook");
                                        }
                                    }

                                    // Sync QuoteCurrency (usually "USD" but could be different)
                                    var quoteCurrencySymbolStr = security.QuoteCurrency.Symbol;
                                    if (!subAccountCashBook.ContainsKey(quoteCurrencySymbolStr))
                                    {
                                        if (CashBook.ContainsKey(quoteCurrencySymbolStr))
                                        {
                                            var mainQuoteCash = CashBook[quoteCurrencySymbolStr];
                                            subAccountCashBook.Add(quoteCurrencySymbolStr, mainQuoteCash.Amount, mainQuoteCash.ConversionRate);
                                            Log.Trace($"MultiSecurityPortfolioManager: ✅ Added {quoteCurrencySymbolStr} to account '{targetAccount}' CashBook (Amount: {mainQuoteCash.Amount}, Rate: {mainQuoteCash.ConversionRate})");
                                        }
                                        else
                                        {
                                            Log.Trace($"MultiSecurityPortfolioManager: ⚠️ QuoteCurrency {quoteCurrencySymbolStr} not found in main CashBook");
                                        }
                                    }

                                    // Log final CashBook state for this sub-account
                                    Log.Trace($"MultiSecurityPortfolioManager: Account '{targetAccount}' CashBook now contains: [{string.Join(", ", subAccountCashBook.Keys)}]");
                                }
                            }
                            else
                            {
                                Log.Trace($"MultiSecurityPortfolioManager: Security {symbol} already exists in account '{targetAccount}', skipping");
                            }
                        }
                        else
                        {
                            Log.Error($"MultiSecurityPortfolioManager: ❌ Router returned unknown account '{targetAccount}' for {symbol}");
                            Log.Error($"MultiSecurityPortfolioManager: Available accounts: [{string.Join(", ", _subAccountSecurityManagers.Keys)}]");
                        }
                    }
                    else
                    {
                        Log.Error($"MultiSecurityPortfolioManager: ❌ Unexpected item type in CollectionChanged event: {item?.GetType().FullName ?? "null"}");
                    }
                }

                // Log final state of all sub-accounts
                Log.Trace("MultiSecurityPortfolioManager: === Sub-Account Securities Summary ===");
                foreach (var kvp in _subAccountSecurityManagers)
                {
                    Log.Trace($"  Account '{kvp.Key}': {kvp.Value.Count} securities [{string.Join(", ", kvp.Value.Keys)}]");
                }
                Log.Trace("MultiSecurityPortfolioManager: ======================================");
            }
        }

        /// <summary>
        /// Gets all sub-account portfolios
        /// </summary>
        public IReadOnlyDictionary<string, SecurityPortfolioManager> SubAccounts => _subAccounts;

        /// <summary>
        /// Gets the portfolio for a specific account
        /// </summary>
        /// <param name="accountName">Name of the account</param>
        /// <returns>The SecurityPortfolioManager for the specified account</returns>
        public SecurityPortfolioManager GetAccount(string accountName)
        {
            if (!_subAccounts.TryGetValue(accountName, out var account))
            {
                throw new ArgumentException($"Account '{accountName}' not found", nameof(accountName));
            }
            return account;
        }

        /// <summary>
        /// Gets the holdings for a specific symbol in a specific account
        /// </summary>
        /// <param name="accountName">Name of the account</param>
        /// <param name="symbol">The symbol to get holdings for</param>
        /// <returns>The SecurityHolding for the symbol in the specified account</returns>
        public SecurityHolding GetAccountHolding(string accountName, Symbol symbol)
        {
            var account = GetAccount(accountName);
            return account[symbol];
        }

        /// <summary>
        /// Gets the cash balance for a specific account
        /// </summary>
        /// <param name="accountName">Name of the account</param>
        /// <returns>The cash balance of the specified account</returns>
        public decimal GetAccountCash(string accountName)
        {
            var account = GetAccount(accountName);
            return account.Cash;
        }

        /// <summary>
        /// Gets the CashBook for a specific account
        /// </summary>
        /// <param name="accountName">Name of the account</param>
        /// <returns>The CashBook of the specified account</returns>
        public CashBook GetAccountCashBook(string accountName)
        {
            var account = GetAccount(accountName);
            return account.CashBook;
        }

        /// <summary>
        /// Validates if there is sufficient buying power for the given orders by routing to appropriate sub-accounts
        /// </summary>
        public new HasSufficientBuyingPowerForOrderResult HasSufficientBuyingPowerForOrder(List<Order> orders)
        {
            if (orders == null || orders.Count == 0)
            {
                return new HasSufficientBuyingPowerForOrderResult(true);
            }

            foreach (var order in orders)
            {
                try
                {
                    // Route order to determine which account should handle it
                    var accountName = _router.Route(order);

                    if (!_subAccounts.TryGetValue(accountName, out var subAccount))
                    {
                        return new HasSufficientBuyingPowerForOrderResult(false,
                            $"Account '{accountName}' not found for order {order.Id}");
                    }

                    // Check buying power in the specific sub-account
                    var result = subAccount.HasSufficientBuyingPowerForOrder(new List<Order> { order });

                    if (!result.IsSufficient)
                    {
                        Log.Error($"MultiSecurityPortfolioManager: Insufficient buying power in account '{accountName}' for order {order.Id}");
                        return result;
                    }

                    Log.Trace($"MultiSecurityPortfolioManager: Order {order.Id} validated for account '{accountName}'");
                }
                catch (Exception ex)
                {
                    Log.Error($"MultiSecurityPortfolioManager.HasSufficientBuyingPowerForOrder(): Error validating order {order.Id}: {ex.Message}");
                    return new HasSufficientBuyingPowerForOrderResult(false,
                        $"Error validating order: {ex.Message}");
                }
            }

            return new HasSufficientBuyingPowerForOrderResult(true);
        }

        /// <summary>
        /// Processes order fills by routing to the appropriate sub-account
        /// </summary>
        /// <remarks>
        /// IMPORTANT: We do NOT call base.ProcessFills() because:
        /// 1. Sub-accounts already update Security.Holdings (shared across accounts)
        /// 2. Calling base.ProcessFills() would duplicate the holdings update
        /// 3. Aggregated values are computed on-demand via properties (TotalPortfolioValue, Cash, etc.)
        /// </remarks>
        public override void ProcessFills(List<OrderEvent> fills)
        {
            if (fills == null || fills.Count == 0)
            {
                return;
            }

            Log.Trace($"MultiSecurityPortfolioManager.ProcessFills: Processing {fills.Count} fill(s)");

            // Route fills to appropriate sub-accounts
            foreach (var fill in fills)
            {
                Log.Trace($"MultiSecurityPortfolioManager.ProcessFills: Fill - OrderId: {fill.OrderId}, Symbol: {fill.Symbol}, Quantity: {fill.FillQuantity}, Price: {fill.FillPrice}");

                // Route order directly using the router
                var order = Transactions.GetOrderById(fill.OrderId);
                if (order == null)
                {
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ❌ Cannot route order {fill.OrderId} - order not found in Transactions");
                    continue;
                }

                var accountName = _router.Route(order);
                Log.Trace($"MultiSecurityPortfolioManager.ProcessFills: Routed order {fill.OrderId} to account '{accountName}'");

                // Check if symbol exists in sub-account SecurityManager
                var accountForSymbol = FindAccountForSymbol(fill.Symbol);
                if (accountForSymbol == null)
                {
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ❌ Symbol {fill.Symbol} not found in any sub-account SecurityManager!");
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): This indicates the Security was not properly routed during Initialize()");
                    Log.Error(GetSubAccountSecuritiesSummary());
                    continue;
                }
                else if (accountForSymbol != accountName)
                {
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ⚠️ Symbol {fill.Symbol} found in account '{accountForSymbol}' but order routed to '{accountName}'");
                }

                if (_subAccounts.TryGetValue(accountName, out var subAccount))
                {
                    Log.Trace($"MultiSecurityPortfolioManager.ProcessFills: Calling subAccount.ProcessFills() for account '{accountName}'");

                    try
                    {
                        subAccount.ProcessFills(new List<OrderEvent> { fill });
                        Log.Trace($"MultiSecurityPortfolioManager: ✅ Successfully processed fill for order {fill.OrderId} (Symbol: {fill.Symbol}) in account '{accountName}'");
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ❌ Error processing fill in account '{accountName}': {ex.Message}");
                        Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): Stack trace: {ex.StackTrace}");
                        throw;
                    }
                }
                else
                {
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ❌ Account '{accountName}' not found for order {fill.OrderId}");
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): Available accounts: [{string.Join(", ", _subAccounts.Keys)}]");
                }
            }

            // Invalidate cached portfolio value to trigger recalculation
            InvalidateTotalPortfolioValue();
        }

        /// <summary>
        /// Gets aggregated total portfolio value from all sub-accounts
        /// </summary>
        /// <remarks>
        /// Since each sub-account has independent Holdings (each Security belongs to only one account),
        /// we can simply sum the TotalPortfolioValue of all sub-accounts.
        /// No risk of double-counting as Securities are routed exclusively to their respective accounts.
        /// </remarks>
        public new decimal TotalPortfolioValue
        {
            get
            {
                return _subAccounts.Values.Sum(account => account.TotalPortfolioValue);
            }
        }

        /// <summary>
        /// Gets aggregated total margin used from all sub-accounts
        /// </summary>
        public new decimal TotalMarginUsed
        {
            get
            {
                return _subAccounts.Values.Sum(account => account.TotalMarginUsed);
            }
        }

        /// <summary>
        /// Gets aggregated cash (all currencies) from all sub-accounts
        /// </summary>
        /// <remarks>
        /// Returns the sum of CashBook.TotalValueInAccountCurrency from all sub-accounts,
        /// which includes USD and crypto currencies like AAPL, TSLA, etc.
        /// </remarks>
        public new decimal Cash
        {
            get
            {
                // Aggregate total cash value from all sub-account CashBooks
                return _subAccounts.Values.Sum(account => account.Cash);
            }
        }

        /// <summary>
        /// Gets the total value of all sub-accounts
        /// </summary>
        public Dictionary<string, decimal> GetAccountValues()
        {
            return _subAccounts.ToDictionary(
                kvp => kvp.Key,
                kvp => kvp.Value.TotalPortfolioValue
            );
        }

        /// <summary>
        /// Gets summary statistics for all accounts
        /// </summary>
        public string GetAccountsSummary()
        {
            var summary = "=== Multi-Account Portfolio Summary ===\n";
            var totalValue = 0m;

            foreach (var kvp in _subAccounts)
            {
                var accountName = kvp.Key;
                var account = kvp.Value;
                var accountValue = account.TotalPortfolioValue;
                totalValue += accountValue;

                summary += $"\nAccount: {accountName}\n";
                summary += $"  Cash: ${account.Cash:N2}\n";
                summary += $"  Margin Used: ${account.TotalMarginUsed:N2}\n";
                summary += $"  Total Value: ${accountValue:N2}\n";
            }

            summary += $"\nTotal Portfolio Value: ${totalValue:N2}\n";
            summary += "======================================";

            return summary;
        }

        /// <summary>
        /// Gets diagnostic information about sub-account SecurityManagers
        /// </summary>
        /// <remarks>
        /// Used for debugging to verify that Securities are correctly routed to sub-accounts
        /// </remarks>
        public string GetSubAccountSecuritiesSummary()
        {
            var summary = "=== Sub-Account Securities Summary ===\n";

            foreach (var kvp in _subAccountSecurityManagers)
            {
                var accountName = kvp.Key;
                var securityManager = kvp.Value;

                summary += $"\nAccount: {accountName}\n";
                summary += $"  Security Count: {securityManager.Count}\n";

                if (securityManager.Count > 0)
                {
                    summary += "  Securities:\n";
                    foreach (var secKvp in securityManager)
                    {
                        var symbol = secKvp.Key;
                        var security = secKvp.Value;
                        summary += $"    - {symbol} (Type: {symbol.SecurityType}, Market: {symbol.ID.Market})\n";
                        summary += $"      Holdings: {security.Holdings.Quantity} @ ${security.Holdings.AveragePrice:F2}\n";
                    }
                }
                else
                {
                    summary += "  (No securities)\n";
                }
            }

            summary += "======================================";
            return summary;
        }

        /// <summary>
        /// Checks if a symbol exists in any sub-account SecurityManager
        /// </summary>
        /// <param name="symbol">The symbol to check</param>
        /// <returns>Account name if found, null otherwise</returns>
        public string FindAccountForSymbol(Symbol symbol)
        {
            foreach (var kvp in _subAccountSecurityManagers)
            {
                if (kvp.Value.ContainsKey(symbol))
                {
                    return kvp.Key;
                }
            }
            return null;
        }
    }
}
