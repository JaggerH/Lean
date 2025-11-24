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
using QuantConnect.Brokerages;
using QuantConnect.Data;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Securities;

namespace QuantConnect.Lean.Engine
{
    /// <summary>
    /// Manages multiple brokerage connections for multi-account live trading.
    /// Routes order operations to the appropriate brokerage based on account name.
    /// Implements both IMultiBrokerageManager and IBrokerage for compatibility.
    /// </summary>
    public class MultiBrokerageManager : IMultiBrokerageManager, IBrokerage
    {
        private readonly Dictionary<string, IBrokerage> _brokerages;
        private readonly object _lock = new object();
        private bool _disposed;

        /// <summary>
        /// Event fired when order ID changes from any brokerage
        /// </summary>
        public event EventHandler<BrokerageOrderIdChangedEvent> OrderIdChanged;

        /// <summary>
        /// Event fired when order status changes from any brokerage
        /// </summary>
        public event EventHandler<List<OrderEvent>> OrdersStatusChanged;

        /// <summary>
        /// Event fired when order is updated from any brokerage
        /// </summary>
        public event EventHandler<OrderUpdateEvent> OrderUpdated;

        /// <summary>
        /// Event fired when an option position is assigned from any brokerage
        /// </summary>
        public event EventHandler<OrderEvent> OptionPositionAssigned;

        /// <summary>
        /// Event fired when option notification occurs from any brokerage
        /// </summary>
        public event EventHandler<OptionNotificationEventArgs> OptionNotification;

        /// <summary>
        /// Event fired when new brokerage order notification occurs
        /// </summary>
        public event EventHandler<NewBrokerageOrderNotificationEventArgs> NewBrokerageOrderNotification;

        /// <summary>
        /// Event fired when delisting notification occurs
        /// </summary>
        public event EventHandler<DelistingNotificationEventArgs> DelistingNotification;

        /// <summary>
        /// Event fired when account information changes from any brokerage
        /// </summary>
        public event EventHandler<AccountEvent> AccountChanged;

        /// <summary>
        /// Event fired when a message is received from any brokerage
        /// </summary>
        public event EventHandler<BrokerageMessageEvent> Message;

        /// <summary>
        /// Returns true if all brokerages are connected
        /// </summary>
        public bool IsConnected
        {
            get
            {
                lock (_lock)
                {
                    return _brokerages.Count > 0 && _brokerages.All(kvp => kvp.Value.IsConnected);
                }
            }
        }

        /// <summary>
        /// Initializes a new instance of the MultiBrokerageManager
        /// </summary>
        public MultiBrokerageManager()
        {
            _brokerages = new Dictionary<string, IBrokerage>();
        }

        /// <summary>
        /// Registers a brokerage instance for a specific account
        /// </summary>
        public void RegisterBrokerage(string accountName, IBrokerage brokerage)
        {
            if (string.IsNullOrEmpty(accountName))
            {
                throw new ArgumentException("Account name cannot be null or empty", nameof(accountName));
            }

            if (brokerage == null)
            {
                throw new ArgumentNullException(nameof(brokerage));
            }

            lock (_lock)
            {
                if (_brokerages.ContainsKey(accountName))
                {
                    throw new InvalidOperationException($"Brokerage for account '{accountName}' is already registered");
                }

                _brokerages[accountName] = brokerage;

                // Subscribe to all brokerage events and forward them
                brokerage.OrderIdChanged += (sender, e) => OrderIdChanged?.Invoke(this, e);
                brokerage.OrdersStatusChanged += (sender, orderEvents) =>
                {
                    // Log.Trace($"MultiBrokerageManager: OrdersStatusChanged from {accountName}: {orderEvents.Count} events");
                    OrdersStatusChanged?.Invoke(this, orderEvents);
                };
                brokerage.OrderUpdated += (sender, e) => OrderUpdated?.Invoke(this, e);
                brokerage.OptionPositionAssigned += (sender, fill) =>
                {
                    Log.Trace($"MultiBrokerageManager: OptionPositionAssigned from {accountName}");
                    OptionPositionAssigned?.Invoke(this, fill);
                };
                brokerage.OptionNotification += (sender, e) => OptionNotification?.Invoke(this, e);
                brokerage.NewBrokerageOrderNotification += (sender, e) => NewBrokerageOrderNotification?.Invoke(this, e);
                brokerage.DelistingNotification += (sender, e) => DelistingNotification?.Invoke(this, e);
                brokerage.AccountChanged += (sender, accountEvent) =>
                {
                    Log.Trace($"MultiBrokerageManager: AccountChanged from {accountName}");
                    AccountChanged?.Invoke(this, accountEvent);
                };
                brokerage.Message += (sender, messageEvent) =>
                {
                    Log.Trace($"MultiBrokerageManager: Message from {accountName}: {messageEvent.Message}");
                    Message?.Invoke(this, messageEvent);
                };

                Log.Trace($"MultiBrokerageManager: Registered brokerage for account '{accountName}'");
            }
        }

        /// <summary>
        /// Gets the brokerage instance for a specific account
        /// </summary>
        public IBrokerage GetBrokerage(string accountName)
        {
            lock (_lock)
            {
                if (!_brokerages.TryGetValue(accountName, out var brokerage))
                {
                    throw new KeyNotFoundException($"No brokerage registered for account '{accountName}'");
                }

                return brokerage;
            }
        }

        /// <summary>
        /// Gets all registered account names
        /// </summary>
        public IReadOnlyCollection<string> GetAccountNames()
        {
            lock (_lock)
            {
                return _brokerages.Keys.ToList().AsReadOnly();
            }
        }

        /// <summary>
        /// Places an order through the appropriate brokerage for the specified account
        /// </summary>
        public bool PlaceOrder(Order order, string accountName)
        {
            try
            {
                var brokerage = GetBrokerage(accountName);
                // Log.Trace($"MultiBrokerageManager: Routing order {order.Id} to {accountName} brokerage");
                return brokerage.PlaceOrder(order);
            }
            catch (Exception ex)
            {
                Log.Error($"MultiBrokerageManager: Error placing order {order.Id} to {accountName}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Updates an existing order through the appropriate brokerage
        /// </summary>
        public bool UpdateOrder(Order order, string accountName)
        {
            try
            {
                var brokerage = GetBrokerage(accountName);
                Log.Trace($"MultiBrokerageManager: Routing order update {order.Id} to {accountName} brokerage");
                return brokerage.UpdateOrder(order);
            }
            catch (Exception ex)
            {
                Log.Error($"MultiBrokerageManager: Error updating order {order.Id} to {accountName}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Cancels an order through the appropriate brokerage
        /// </summary>
        public bool CancelOrder(Order order, string accountName)
        {
            try
            {
                var brokerage = GetBrokerage(accountName);
                Log.Trace($"MultiBrokerageManager: Routing order cancel {order.Id} to {accountName} brokerage");
                return brokerage.CancelOrder(order);
            }
            catch (Exception ex)
            {
                Log.Error($"MultiBrokerageManager: Error cancelling order {order.Id} to {accountName}: {ex.Message}");
                return false;
            }
        }

        /// <summary>
        /// Gets open orders for a specific account
        /// </summary>
        public List<Order> GetOpenOrders(string accountName)
        {
            try
            {
                var brokerage = GetBrokerage(accountName);
                return brokerage.GetOpenOrders();
            }
            catch (Exception ex)
            {
                Log.Error($"MultiBrokerageManager: Error getting open orders from {accountName}: {ex.Message}");
                return new List<Order>();
            }
        }

        /// <summary>
        /// Connects all registered brokerages
        /// Throws exception if any brokerage fails to connect (fail-fast approach)
        /// </summary>
        public void ConnectAll()
        {
            var failedAccounts = new List<string>();

            lock (_lock)
            {
                Log.Trace($"MultiBrokerageManager: Connecting {_brokerages.Count} brokerages...");

                foreach (var kvp in _brokerages)
                {
                    var accountName = kvp.Key;
                    var brokerage = kvp.Value;

                    try
                    {
                        Log.Trace($"MultiBrokerageManager: Connecting {accountName} brokerage...");
                        brokerage.Connect();

                        if (!brokerage.IsConnected)
                        {
                            failedAccounts.Add(accountName);
                            Log.Error($"MultiBrokerageManager: {accountName} brokerage failed to connect");
                        }
                        else
                        {
                            Log.Trace($"MultiBrokerageManager: {accountName} brokerage connected successfully");
                        }
                    }
                    catch (Exception ex)
                    {
                        failedAccounts.Add(accountName);
                        Log.Error($"MultiBrokerageManager: Exception connecting {accountName} brokerage: {ex.Message}");
                    }
                }
            }

            // Fail-fast: If any brokerage failed to connect, disconnect all and throw
            if (failedAccounts.Any())
            {
                Log.Error($"MultiBrokerageManager: {failedAccounts.Count} brokerage(s) failed to connect: {string.Join(", ", failedAccounts)}");
                DisconnectAll();
                throw new Exception($"Failed to connect brokerages: {string.Join(", ", failedAccounts)}. All brokerages must connect successfully.");
            }

            Log.Trace("MultiBrokerageManager: All brokerages connected successfully");
        }

        /// <summary>
        /// Disconnects all registered brokerages
        /// </summary>
        public void DisconnectAll()
        {
            lock (_lock)
            {
                Log.Trace($"MultiBrokerageManager: Disconnecting {_brokerages.Count} brokerages...");

                foreach (var kvp in _brokerages)
                {
                    try
                    {
                        Log.Trace($"MultiBrokerageManager: Disconnecting {kvp.Key} brokerage...");
                        kvp.Value.Disconnect();
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error disconnecting {kvp.Key} brokerage: {ex.Message}");
                    }
                }

                Log.Trace("MultiBrokerageManager: All brokerages disconnected");
            }
        }

        #region IBrokerage Implementation (for compatibility)

        /// <summary>
        /// Name of the brokerage
        /// </summary>
        public string Name => "MultiBrokerageManager";

        /// <summary>
        /// Whether account balances are instantly updated
        /// </summary>
        public bool AccountInstantlyUpdated => true;

        /// <summary>
        /// Base currency - returns null for multi-brokerage (varies by account)
        /// </summary>
        public string AccountBaseCurrency => null;

        /// <summary>
        /// Enables/disables concurrent processing
        /// </summary>
        public bool ConcurrencyEnabled { get; set; }

        /// <summary>
        /// Places order - NOT SUPPORTED without account routing.
        /// Use IMultiBrokerageManager.PlaceOrder(order, accountName) instead.
        /// </summary>
        public bool PlaceOrder(Order order)
        {
            throw new NotSupportedException(
                "PlaceOrder without account parameter is not supported in MultiBrokerageManager. " +
                "Use IMultiBrokerageManager.PlaceOrder(order, accountName) or rely on automatic routing.");
        }

        /// <summary>
        /// Updates order - NOT SUPPORTED without account routing.
        /// </summary>
        public bool UpdateOrder(Order order)
        {
            throw new NotSupportedException(
                "UpdateOrder without account parameter is not supported in MultiBrokerageManager. " +
                "Use IMultiBrokerageManager.UpdateOrder(order, accountName).");
        }

        /// <summary>
        /// Cancels order - NOT SUPPORTED without account routing.
        /// </summary>
        public bool CancelOrder(Order order)
        {
            throw new NotSupportedException(
                "CancelOrder without account parameter is not supported in MultiBrokerageManager. " +
                "Use IMultiBrokerageManager.CancelOrder(order, accountName).");
        }

        /// <summary>
        /// Gets all open orders across all accounts
        /// </summary>
        public List<Order> GetOpenOrders()
        {
            var allOrders = new List<Order>();
            lock (_lock)
            {
                foreach (var kvp in _brokerages)
                {
                    try
                    {
                        var orders = kvp.Value.GetOpenOrders();
                        allOrders.AddRange(orders);
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error getting open orders from {kvp.Key}: {ex.Message}");
                    }
                }
            }
            return allOrders;
        }

        /// <summary>
        /// Gets all holdings across all accounts
        /// </summary>
        public List<Holding> GetAccountHoldings()
        {
            var allHoldings = new List<Holding>();
            lock (_lock)
            {
                foreach (var kvp in _brokerages)
                {
                    try
                    {
                        var holdings = kvp.Value.GetAccountHoldings();
                        allHoldings.AddRange(holdings);
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error getting holdings from {kvp.Key}: {ex.Message}");
                    }
                }
            }
            return allHoldings;
        }

        /// <summary>
        /// Gets cash balances across all accounts
        /// </summary>
        public List<CashAmount> GetCashBalance()
        {
            var allCash = new List<CashAmount>();
            lock (_lock)
            {
                foreach (var kvp in _brokerages)
                {
                    try
                    {
                        var cash = kvp.Value.GetCashBalance();
                        allCash.AddRange(cash);
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error getting cash from {kvp.Key}: {ex.Message}");
                    }
                }
            }
            return allCash;
        }

        /// <summary>
        /// Gets execution history across all accounts within a time range.
        /// Uses reflection to detect GetExecutionHistory method on each brokerage.
        /// </summary>
        /// <param name="startTimeUtc">Start time (UTC)</param>
        /// <param name="endTimeUtc">End time (UTC)</param>
        /// <returns>List of execution records from all brokerages</returns>
        public List<TradingPairs.ExecutionRecord> GetExecutionHistory(DateTime startTimeUtc, DateTime endTimeUtc)
        {
            var allExecutions = new List<TradingPairs.ExecutionRecord>();
            lock (_lock)
            {
                foreach (var kvp in _brokerages)
                {
                    var accountName = kvp.Key;
                    var brokerage = kvp.Value;

                    try
                    {
                        // Use reflection to detect and call GetExecutionHistory method
                        var getHistoryMethod = brokerage.GetType().GetMethod(
                            "GetExecutionHistory",
                            new[] { typeof(DateTime), typeof(DateTime) });

                        if (getHistoryMethod == null)
                        {
                            Log.Error($"MultiBrokerageManager.GetExecutionHistory(): Brokerage '{brokerage.Name}' (account '{accountName}') does not implement GetExecutionHistory method");
                            continue;
                        }

                        var executions = (List<TradingPairs.ExecutionRecord>)getHistoryMethod.Invoke(
                            brokerage,
                            new object[] { startTimeUtc, endTimeUtc });

                        if (executions != null && executions.Count > 0)
                        {
                            allExecutions.AddRange(executions);
                            Log.Trace($"MultiBrokerageManager.GetExecutionHistory(): Retrieved {executions.Count} executions from account '{accountName}'");
                        }
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager.GetExecutionHistory(): Error querying account '{accountName}': {ex.Message}");
                    }
                }
            }

            Log.Trace($"MultiBrokerageManager.GetExecutionHistory(): Total {allExecutions.Count} executions retrieved from {startTimeUtc:yyyy-MM-dd HH:mm:ss} to {endTimeUtc:yyyy-MM-dd HH:mm:ss}");
            return allExecutions;
        }

        /// <summary>
        /// Connects all brokerages
        /// </summary>
        public void Connect()
        {
            ConnectAll();
        }

        /// <summary>
        /// Disconnects all brokerages
        /// </summary>
        public void Disconnect()
        {
            DisconnectAll();
        }

        /// <summary>
        /// Gets history - NOT SUPPORTED in multi-brokerage mode
        /// </summary>
        public IEnumerable<BaseData> GetHistory(HistoryRequest request)
        {
            throw new NotSupportedException(
                "GetHistory is not supported in MultiBrokerageManager. " +
                "History should be requested from specific brokerage instances.");
        }

        /// <summary>
        /// Last synchronization time - returns earliest sync time across all brokerages
        /// </summary>
        public DateTime LastSyncDateTimeUtc
        {
            get
            {
                lock (_lock)
                {
                    if (_brokerages.Count == 0) return DateTime.MinValue;
                    return _brokerages.Values.Min(b => b.LastSyncDateTimeUtc);
                }
            }
        }

        /// <summary>
        /// Determines if cash sync should be performed at the given time
        /// </summary>
        public bool ShouldPerformCashSync(DateTime currentTimeUtc)
        {
            // Perform sync if ANY brokerage needs it
            lock (_lock)
            {
                return _brokerages.Values.Any(b => b.ShouldPerformCashSync(currentTimeUtc));
            }
        }

        /// <summary>
        /// Performs cash synchronization across all brokerages
        /// </summary>
        public bool PerformCashSync(IAlgorithm algorithm, DateTime currentTimeUtc, Func<TimeSpan> getTimeSinceLastFill)
        {
            var anySuccess = false;
            lock (_lock)
            {
                foreach (var kvp in _brokerages)
                {
                    try
                    {
                        var success = kvp.Value.PerformCashSync(algorithm, currentTimeUtc, getTimeSinceLastFill);
                        anySuccess |= success;
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error syncing cash for {kvp.Key}: {ex.Message}");
                    }
                }
            }
            return anySuccess;
        }

        #endregion

        /// <summary>
        /// Disposes all registered brokerages
        /// </summary>
        public void Dispose()
        {
            if (_disposed) return;

            DisconnectAll();

            lock (_lock)
            {
                foreach (var brokerage in _brokerages.Values)
                {
                    try
                    {
                        brokerage.Dispose();
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiBrokerageManager: Error disposing brokerage: {ex.Message}");
                    }
                }

                _brokerages.Clear();
            }

            _disposed = true;
        }
    }
}
