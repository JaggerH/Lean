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
using QuantConnect.Brokerages;
using QuantConnect.Orders;
using QuantConnect.Securities;

namespace QuantConnect.Interfaces
{
    /// <summary>
    /// Manages multiple brokerage connections for multi-account live trading.
    /// Routes order operations and events to the appropriate brokerage based on account name.
    /// </summary>
    public interface IMultiBrokerageManager : IDisposable
    {
        /// <summary>
        /// Registers a brokerage instance for a specific account
        /// </summary>
        /// <param name="accountName">The account name (e.g., "Binance", "Gate")</param>
        /// <param name="brokerage">The brokerage instance to register</param>
        void RegisterBrokerage(string accountName, IBrokerage brokerage);

        /// <summary>
        /// Gets the brokerage instance for a specific account
        /// </summary>
        /// <param name="accountName">The account name</param>
        /// <returns>The brokerage instance for the account</returns>
        IBrokerage GetBrokerage(string accountName);

        /// <summary>
        /// Gets all registered account names
        /// </summary>
        IReadOnlyCollection<string> GetAccountNames();

        /// <summary>
        /// Places an order through the appropriate brokerage for the specified account
        /// </summary>
        /// <param name="order">The order to place</param>
        /// <param name="accountName">The account to route the order to</param>
        /// <returns>True if the order was successfully placed</returns>
        bool PlaceOrder(Order order, string accountName);

        /// <summary>
        /// Updates an existing order through the appropriate brokerage
        /// </summary>
        /// <param name="order">The order to update</param>
        /// <param name="accountName">The account the order belongs to</param>
        /// <returns>True if the order was successfully updated</returns>
        bool UpdateOrder(Order order, string accountName);

        /// <summary>
        /// Cancels an order through the appropriate brokerage
        /// </summary>
        /// <param name="order">The order to cancel</param>
        /// <param name="accountName">The account the order belongs to</param>
        /// <returns>True if the order was successfully cancelled</returns>
        bool CancelOrder(Order order, string accountName);

        /// <summary>
        /// Gets open orders for a specific account
        /// </summary>
        /// <param name="accountName">The account name</param>
        /// <returns>List of open orders for the account</returns>
        List<Order> GetOpenOrders(string accountName);

        /// <summary>
        /// Connects all registered brokerages
        /// </summary>
        /// <exception cref="Exception">Thrown if any brokerage fails to connect</exception>
        void ConnectAll();

        /// <summary>
        /// Disconnects all registered brokerages
        /// </summary>
        void DisconnectAll();

        /// <summary>
        /// Returns true if all brokerages are connected
        /// </summary>
        bool IsConnected { get; }

        /// <summary>
        /// Event fired when order status changes from any brokerage.
        /// OrderEvents are tagged with Symbol information that includes Market,
        /// allowing identification of the source brokerage.
        /// </summary>
        event EventHandler<List<OrderEvent>> OrdersStatusChanged;

        /// <summary>
        /// Event fired when account information changes from any brokerage
        /// </summary>
        event EventHandler<AccountEvent> AccountChanged;

        /// <summary>
        /// Event fired when a message is received from any brokerage
        /// </summary>
        event EventHandler<BrokerageMessageEvent> Message;

        /// <summary>
        /// Event fired when an option position is assigned from any brokerage
        /// </summary>
        event EventHandler<OrderEvent> OptionPositionAssigned;
    }
}
