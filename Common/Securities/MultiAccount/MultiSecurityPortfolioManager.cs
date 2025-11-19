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

namespace QuantConnect.Securities.MultiAccount
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
        private readonly RoutingCashBook _routingCashBook;

        /// <summary>
        /// Gets the order router for this portfolio manager
        /// </summary>
        public IOrderRouter Router => _router;

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
        /// <param name="accountCurrencies">Optional dictionary mapping account names to their base currencies</param>
        public MultiSecurityPortfolioManager(
            Dictionary<string, decimal> accountConfigs,
            IOrderRouter router,
            SecurityManager securityManager,
            SecurityTransactionManager transactionManager,
            IAlgorithmSettings algorithmSettings,
            IOrderProperties defaultOrderProperties,
            ITimeKeeper timeKeeper,
            Dictionary<string, string> accountCurrencies = null)
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

                // Set account currency BEFORE SetCash if provided
                if (accountCurrencies != null && accountCurrencies.TryGetValue(config.Key, out var currency))
                {
                    subPortfolio.SetAccountCurrency(currency);
                    Log.Trace($"MultiSecurityPortfolioManager: Account '{config.Key}' using currency '{currency}'");
                }
                else
                {
                    Log.Trace($"MultiSecurityPortfolioManager: Account '{config.Key}' using default currency '{subPortfolio.CashBook.AccountCurrency}'");
                }

                subPortfolio.SetCash(config.Value);
                _subAccounts[config.Key] = subPortfolio;

                Log.Trace($"MultiSecurityPortfolioManager: Account '{config.Key}' initialized with {config.Value} {subPortfolio.CashBook.AccountCurrency}");
            }

            // Set aggregated cash in main portfolio (for internal state initialization)
            // This will be cleared and re-aggregated later via SyncConversionsToMain during Setup
            SetCash(accountConfigs.Values.Sum());
            Log.Trace($"MultiSecurityPortfolioManager: Main portfolio initialized with {accountConfigs.Values.Sum()} {base.CashBook.AccountCurrency} (temporary, will be synced from sub-accounts)");

            // Subscribe to main CashBook's Updated event for delayed BaseCurrency synchronization
            // This ensures CurrencyConversion is initialized before syncing to sub-accounts
            // Use base.CashBook to access the actual CashBook before _routingCashBook is initialized
            base.CashBook.Updated += OnMainCashBookUpdated;

            // Subscribe to SecurityManager changes to sync Securities to sub-accounts
            securityManager.CollectionChanged += OnSecurityManagerCollectionChanged;

            // Process any securities that were added BEFORE the event subscription
            // This handles test scenarios where securities are added before portfolio creation
            foreach (var kvp in securityManager)
            {
                var security = kvp.Value;
                var symbol = security.Symbol;

                // Create a temporary order to determine routing target
                var tempOrder = new MarketOrder(symbol, 0, DateTime.UtcNow);
                var targetAccount = _router.Route(tempOrder);

                // Add to the target sub-account's SecurityManager
                if (_subAccountSecurityManagers.TryGetValue(targetAccount, out var subSecurityManager))
                {
                    if (!subSecurityManager.ContainsKey(symbol))
                    {
                        subSecurityManager.Add(symbol, security);
                        Log.Trace($"MultiSecurityPortfolioManager: Routed pre-existing {symbol} to account '{targetAccount}'");
                    }
                }
                else
                {
                    Log.Error($"MultiSecurityPortfolioManager: ❌ Router returned unknown account '{targetAccount}' for pre-existing {symbol}");
                }
            }

            // Create RoutingCashBook for transparent currency routing
            _routingCashBook = new RoutingCashBook(base.CashBook, _subAccounts, _subAccountSecurityManagers);

            Log.Trace($"MultiSecurityPortfolioManager: Created with {_subAccounts.Count} accounts");
        }

        /// <summary>
        /// Handles main CashBook Updated events to sync BaseCurrency to sub-accounts
        /// </summary>
        /// <remarks>
        /// This method is called AFTER EnsureCurrencyDataFeed has initialized CurrencyConversion.
        /// This ensures we sync BaseCurrency only when ConversionRate is properly set.
        /// Flow: SecurityService.CreateSecurity → UniverseSelection.EnsureCurrencyDataFeeds
        ///       → CashBook.Updated event → OnMainCashBookUpdated (sync happens here)
        /// </remarks>
        private void OnMainCashBookUpdated(object sender, CashBookUpdatedEventArgs args)
        {
            // Sync when currencies are added OR when CurrencyConversion is updated (UpdateType.Updated)
            // Added: Initial currency creation (Rate still 0 at this point)
            // Updated: When CurrencyConversion is set by EnsureCurrencyDataFeed
            if (args.UpdateType != CashBookUpdateType.Added && args.UpdateType != CashBookUpdateType.Updated)
            {
                return;
            }

            var cash = args.Cash;
            var currencySymbol = cash.Symbol;

            // Log.Trace($"MultiSecurityPortfolioManager.OnMainCashBookUpdated: Currency '{currencySymbol}' {args.UpdateType}, ConversionRate={cash.ConversionRate}, CurrencyConversion={(cash.CurrencyConversion != null ? "SET" : "NULL")}");

            // Only sync if CurrencyConversion has been properly initialized
            // This happens after EnsureCurrencyDataFeed completes
            if (cash.CurrencyConversion == null)
            {
                Log.Trace($"MultiSecurityPortfolioManager.OnMainCashBookUpdated: ⚠️ Skipping '{currencySymbol}' sync - CurrencyConversion is NULL (will retry when Updated event fires)");
                return;
            }

            // Check if any sub-account needs this currency as BaseCurrency
            foreach (var subAccountKvp in _subAccountSecurityManagers)
            {
                var accountName = subAccountKvp.Key;
                var subSecurityManager = subAccountKvp.Value;
                var subCashBook = _subAccounts[accountName].CashBook;

                // Check each security in this sub-account
                foreach (var securityKvp in subSecurityManager)
                {
                    var security = securityKvp.Value;

                    // Only sync for IBaseCurrencySymbol (Crypto/Forex)
                    if (security is IBaseCurrencySymbol baseCurrencySymbol
                        && baseCurrencySymbol.BaseCurrency.Symbol == currencySymbol)
                    {
                        // Check if this currency is not already in the sub-account CashBook
                        if (!subCashBook.ContainsKey(currencySymbol))
                        {
                            // Create independent Cash with same CurrencyConversion
                            var independentCash = new Cash(currencySymbol, 0m, cash.ConversionRate);
                            independentCash.CurrencyConversion = cash.CurrencyConversion;

                            subCashBook.Add(currencySymbol, independentCash);
                            Log.Trace($"MultiSecurityPortfolioManager.OnMainCashBookUpdated: ✅ Synced '{currencySymbol}' to account '{accountName}' (ConversionRate={cash.ConversionRate})");
                        }
                        // else
                        // {
                            // Log.Trace($"MultiSecurityPortfolioManager.OnMainCashBookUpdated: '{currencySymbol}' already exists in account '{accountName}'");
                        // }

                        // No need to check other securities once we've processed this currency
                        break;
                    }
                }
            }
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
                if (e.NewItems == null || e.NewItems.Count == 0)
                {
                    return;
                }

                // Route each Security to its designated sub-account
                foreach (var item in e.NewItems)
                {
                    // FIXED: SecurityManager.Add() passes Security object, not KeyValuePair
                    if (item is Security security)
                    {
                        var symbol = security.Symbol;

                        // Create a temporary order to determine routing target
                        // Using MarketOrder with quantity 0 as a routing probe
                        var tempOrder = new MarketOrder(symbol, 0, DateTime.UtcNow);
                        var targetAccount = _router.Route(tempOrder);

                        // 🔧 FIX: Add Security to BOTH main and sub-account SecurityManagers
                        // Main SecurityManager is needed by BacktestingBrokerage.Scan() for order filling
                        // Sub-account SecurityManager is needed for independent Holdings tracking

                        // Add to main SecurityManager (used by BacktestingBrokerage.Scan())
                        if (!this.Securities.ContainsKey(symbol))
                        {
                            this.Securities.Add(symbol, security);
                        }

                        // Add to the target sub-account's SecurityManager (for Holdings tracking)
                        if (_subAccountSecurityManagers.TryGetValue(targetAccount, out var subSecurityManager))
                        {
                            if (!subSecurityManager.ContainsKey(symbol))
                            {
                                subSecurityManager.Add(symbol, security);

                                // Synchronize Cash entries for Crypto/Forex securities (IBaseCurrencySymbol)
                                // This ensures sub-account CashBooks contain all necessary currencies for order fills
                                if (security is IBaseCurrencySymbol baseCurrencySymbol)
                                {
                                    var subAccount = _subAccounts[targetAccount];
                                    var subAccountCashBook = subAccount.CashBook;

                                    // ⚠️ DO NOT sync BaseCurrency here - it will be synced later via OnMainCashBookUpdated event
                                    // Reason: At this point, CurrencyConversion has not been initialized yet (ConversionRate = 0)
                                    // Flow: SecurityService.CreateSecurity (Rate=0) → THIS METHOD → UniverseSelection.EnsureCurrencyDataFeeds (Rate initialized)
                                    //       → CashBook.Updated event → OnMainCashBookUpdated (BaseCurrency synced with correct Rate)

                                    // Sync QuoteCurrency (usually "USD" but could be different)
                                    var quoteCurrencySymbolStr = security.QuoteCurrency.Symbol;
                                    if (!subAccountCashBook.ContainsKey(quoteCurrencySymbolStr))
                                    {
                                        if (CashBook.ContainsKey(quoteCurrencySymbolStr))
                                        {
                                            var mainQuoteCash = CashBook[quoteCurrencySymbolStr];

                                            // Get the sub-account's existing USD balance (set during initialization via SetCash)
                                            // We need to preserve this initial balance when creating the independent Cash object
                                            var subAccountInitialCash = _subAccounts[targetAccount].CashBook.TryGetValue(quoteCurrencySymbolStr, out var existingCash)
                                                ? existingCash.Amount
                                                : 0m;

                                            // ✅ Create independent Cash object with sub-account's initial balance but shared CurrencyConversion
                                            var independentQuoteCash = new Cash(quoteCurrencySymbolStr, subAccountInitialCash, mainQuoteCash.ConversionRate);
                                            independentQuoteCash.CurrencyConversion = mainQuoteCash.CurrencyConversion;

                                            // Replace the existing entry if it was already created during SetCash()
                                            if (subAccountCashBook.ContainsKey(quoteCurrencySymbolStr))
                                            {
                                                subAccountCashBook.Remove(quoteCurrencySymbolStr);
                                            }

                                            subAccountCashBook.Add(quoteCurrencySymbolStr, independentQuoteCash);
                                        }
                                    }

                                    // 🔧 DEFENSIVE FIX: Force-initialize BaseCurrency for CryptoFuture securities
                                    // Problem: OnMainCashBookUpdated event may not fire if CurrencyConversion is null
                                    // Solution: Pre-initialize with rate=0 so SetupCurrencyConversions can find it
                                    // This ensures BaseCurrency exists in CashBook even if event-based sync fails
                                    if (symbol.SecurityType == SecurityType.CryptoFuture)
                                    {
                                        var baseCurrencySymbolStr = baseCurrencySymbol.BaseCurrency.Symbol;
                                        if (!subAccountCashBook.ContainsKey(baseCurrencySymbolStr))
                                        {
                                            // Set rate=0 (not 1.0) so SetupCurrencyConversions filter can find it
                                            // CurrencyConversion will be created by EnsureCurrencyDataFeed
                                            var defensiveCash = new Cash(baseCurrencySymbolStr, 0m, 0m);

                                            subAccountCashBook.Add(baseCurrencySymbolStr, defensiveCash);
                                            Log.Trace($"MultiSecurityPortfolioManager.OnSecurityManagerCollectionChanged: " +
                                                $"Pre-initialized '{baseCurrencySymbolStr}' in account '{targetAccount}' for {symbol} " +
                                                $"(Rate=0, awaiting conversion setup)");
                                        }
                                    }
                                }
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
            }
        }

        /// <summary>
        /// Gets the RoutingCashBook that automatically routes currency access to the correct sub-account
        /// </summary>
        /// <remarks>
        /// This property returns a RoutingCashBook instead of the base CashBook.
        /// When accessing crypto asset currencies (e.g., AAPL, TSLA), it automatically
        /// routes to the appropriate sub-account's CashBook (e.g., Kraken).
        /// For standard currencies (e.g., USD), it uses the main CashBook.
        ///
        /// This enables transparent multi-account support without modifying existing code
        /// that accesses portfolio.cash_book[currency].
        /// </remarks>
        public new CashBook CashBook => _routingCashBook;

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

            // Route fills to appropriate sub-accounts
            foreach (var fill in fills)
            {
                // Route order directly using the router
                var order = Transactions.GetOrderById(fill.OrderId);
                if (order == null)
                {
                    Log.Error($"MultiSecurityPortfolioManager.ProcessFills(): ❌ Cannot route order {fill.OrderId} - order not found in Transactions");
                    continue;
                }

                var accountName = _router.Route(order);

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
                    try
                    {
                        subAccount.ProcessFills(new List<OrderEvent> { fill });
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
        public override decimal TotalPortfolioValue
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
        /// Gets detailed holdings information for each sub-account including CashBook breakdown
        /// </summary>
        /// <returns>Formatted string showing per-account holdings with currency breakdown</returns>
        public string GetSubAccountHoldingsDetails()
        {
            var summary = new System.Text.StringBuilder();
            summary.AppendLine("=== Per-Account Holdings Details ===");

            foreach (var kvp in _subAccounts)
            {
                var accountName = kvp.Key;
                var account = kvp.Value;

                summary.AppendLine($"\n【{accountName}】");
                summary.AppendLine();

                // Use CashBook's ToString() method to get formatted currency breakdown
                summary.AppendLine(account.CashBook.ToString());

                // Show security holdings
                var securityManager = _subAccountSecurityManagers[accountName];
                if (securityManager.Count > 0)
                {
                    var hasHoldings = false;
                    foreach (var secKvp in securityManager)
                    {
                        var security = secKvp.Value;
                        var holding = security.Holdings;
                        if (holding.Quantity != 0)
                        {
                            if (!hasHoldings)
                            {
                                summary.AppendLine("\nSecurity Holdings:");
                                hasHoldings = true;
                            }
                            summary.AppendLine($"  {security.Symbol}: {holding.Quantity} @ ${holding.AveragePrice:F2} = ${holding.HoldingsValue:N2}");
                        }
                    }

                    if (!hasHoldings)
                    {
                        summary.AppendLine("(No security holdings)");
                    }
                }
                else
                {
                    summary.AppendLine("(No securities in this account)");
                }

                summary.AppendLine($"\nTotal Portfolio Value: ${account.TotalPortfolioValue:N2}");
                summary.AppendLine($"Total Margin Used: ${account.TotalMarginUsed:N2}");
            }

            summary.AppendLine("\n======================================");
            return summary.ToString();
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

        /// <summary>
        /// Synchronizes currency conversions from the main CashBook to all sub-account CashBooks.
        /// This method should be called after SetupCurrencyConversions has initialized the main CashBook.
        /// </summary>
        /// <remarks>
        /// This is the critical fix for "conversion rate not available" errors in multi-account mode.
        /// Problem: When LoadCashBalance adds currencies to sub-accounts, they have ConversionRate=0.
        ///          SetupCurrencyConversions only updates the main CashBook, not sub-accounts.
        /// Solution: Explicitly sync initialized CurrencyConversion objects to all sub-account CashBooks.
        /// </remarks>
        public void SyncCurrencyConversionsFromMain()
        {
            // Access the base CashBook (the actual main CashBook, not the RoutingCashBook)
            var mainCashBook = ((SecurityPortfolioManager)this).CashBook;

            // Log.Trace("MultiSecurityPortfolioManager.SyncCurrencyConversionsFromMain: Starting sync...");

            foreach (var mainCashKvp in mainCashBook)
            {
                var currency = mainCashKvp.Key;
                var mainCash = mainCashKvp.Value;
                var currencyConversion = mainCash.CurrencyConversion;

                // Skip currencies that haven't been properly initialized yet
                if (currencyConversion == null || mainCash.ConversionRate == 0)
                {
                    // Log.Trace($"MultiSecurityPortfolioManager.SyncCurrencyConversionsFromMain: ⏭️ Skipping '{currency}' - CurrencyConversion not initialized (Rate={mainCash.ConversionRate})");
                    continue;
                }

                // Sync to all sub-accounts that have this currency
                foreach (var subAccountKvp in _subAccounts)
                {
                    var accountName = subAccountKvp.Key;
                    var subCashBook = subAccountKvp.Value.CashBook;

                    if (subCashBook.ContainsKey(currency))
                    {
                        var subCash = subCashBook[currency];

                        // Update the CurrencyConversion object
                        subCash.CurrencyConversion = currencyConversion;

                        // Log.Trace($"MultiSecurityPortfolioManager.SyncCurrencyConversionsFromMain: ✅ Synced '{currency}' to account '{accountName}' (Rate={currencyConversion.ConversionRate})");
                    }
                }
            }

            // Log.Trace("MultiSecurityPortfolioManager.SyncCurrencyConversionsFromMain: Sync completed");
        }
    }
}
