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
using QuantConnect.Benchmarks;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Util;

namespace QuantConnect.Brokerages
{
    /// <summary>
    /// Provides Gate.io Futures specific properties for USDT-margined perpetual futures
    /// </summary>
    public class GateFuturesBrokerageModel : GateBrokerageModel
    {
        private const decimal _futuresLeverage = 10m;

        /// <summary>
        /// Represents a set of order types supported by Gate.io Futures
        /// </summary>
        private readonly HashSet<OrderType> _supportedOrderTypes = new()
        {
            OrderType.Market,
            OrderType.Limit,
            OrderType.StopMarket,
            OrderType.StopLimit,
        };

        /// <summary>
        /// Gets a map of the default markets to be used for each security type
        /// </summary>
        public override IReadOnlyDictionary<SecurityType, string> DefaultMarkets { get; } = GetDefaultMarkets();

        /// <summary>
        /// Gets the default account currency for Gate.io Futures (USDT-margined)
        /// </summary>
        public override string DefaultAccountCurrency => "USDT";

        /// <summary>
        /// Initializes a new instance of the <see cref="GateFuturesBrokerageModel"/> class
        /// Gate.io Futures requires Margin account type
        /// </summary>
        public GateFuturesBrokerageModel()
            : base(AccountType.Margin)
        {
        }

        /// <summary>
        /// Gate.io Futures leverage rule - defaults to 10x for safety
        /// </summary>
        /// <param name="security">The security to get leverage for</param>
        /// <returns>The leverage for the security</returns>
        public override decimal GetLeverage(Security security)
        {
            if (security.IsInternalFeed() || security.Type == SecurityType.Base)
            {
                return 1m;
            }

            if (security.Type == SecurityType.CryptoFuture)
            {
                return _futuresLeverage;
            }

            throw new ArgumentException(Messages.DefaultBrokerageModel.InvalidSecurityTypeForLeverage(security), nameof(security));
        }

        /// <summary>
        /// Provides Gate.io Futures fee model
        /// </summary>
        /// <param name="security">The security to get the fee model for</param>
        /// <returns>The fee model for Gate.io Futures</returns>
        public override IFeeModel GetFeeModel(Security security)
        {
            return new GateFuturesFeeModel();
        }

        /// <summary>
        /// Returns true if the brokerage could accept this order. This takes into account
        /// order type, security type, and order size limits.
        /// </summary>
        /// <param name="security">The security of the order</param>
        /// <param name="order">The order to be processed</param>
        /// <param name="message">If this function returns false, a brokerage message detailing why the order may not be submitted</param>
        /// <returns>True if the brokerage could process the order, false otherwise</returns>
        public override bool CanSubmitOrder(Security security, Order order, out BrokerageMessageEvent message)
        {
            message = null;

            // Validate order quantity is a multiple of lot size
            var lotSize = security.SymbolProperties.LotSize;
            if (order.Quantity % lotSize != 0)
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    $"Order quantity {order.Quantity} must be a multiple of lot size {lotSize}");
                return false;
            }

            // Gate.io Futures only supports CryptoFuture security type
            if (security.Type != SecurityType.CryptoFuture)
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    Messages.DefaultBrokerageModel.UnsupportedSecurityType(this, security));

                return false;
            }

            // Don't call base.CanSubmitOrder() because GateBrokerageModel only accepts Crypto, not CryptoFuture
            // Instead, validate supported order types directly
            if (!_supportedOrderTypes.Contains(order.Type))
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    Messages.DefaultBrokerageModel.UnsupportedOrderType(this, order, _supportedOrderTypes));
                return false;
            }

            return true;
        }

        private static IReadOnlyDictionary<SecurityType, string> GetDefaultMarkets()
        {
            var map = DefaultMarketMap.ToDictionary();
            // Include both Crypto (for currency conversions like BTCUSDT) and CryptoFuture (for trading)
            map[SecurityType.Crypto] = Market.Gate;
            map[SecurityType.CryptoFuture] = Market.Gate;
            return map.ToReadOnlyDictionary();
        }
    }
}
