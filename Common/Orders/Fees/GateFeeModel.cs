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

using QuantConnect.Securities;

namespace QuantConnect.Orders.Fees
{
    /// <summary>
    /// Provides the fee model for Gate.io cryptocurrency exchange
    /// </summary>
    public class GateFeeModel : FeeModel
    {
        /// <summary>
        /// Tier 1 maker fee (VIP 0)
        /// </summary>
        public const decimal MakerFee = 0.002m; // 0.2%

        /// <summary>
        /// Tier 1 taker fee (VIP 0)
        /// </summary>
        public const decimal TakerFee = 0.002m; // 0.2%

        /// <summary>
        /// Gets the order fee associated with the specified order.
        /// </summary>
        /// <param name="parameters">A <see cref="OrderFeeParameters"/> object containing the security and order</param>
        /// <returns>The cost of the order in a <see cref="CashAmount"/> instance</returns>
        public override OrderFee GetOrderFee(OrderFeeParameters parameters)
        {
            var order = parameters.Order;
            var security = parameters.Security;

            // Get the fee rate (use taker fee as default)
            var fee = TakerFee;

            // For limit orders that are posted (maker), fee would be lower, but for simplicity we use taker fee
            // In production, you might want to differentiate between maker and taker based on order type
            if (order.Type == OrderType.Limit)
            {
                fee = MakerFee;
            }

            // Calculate the fee amount
            var orderValue = order.GetValue(security);
            var feeAmount = fee * orderValue;

            // Gate fees are charged in the quote currency
            // For crypto pairs like BTCUSDT, fees are in USDT
            var quoteCurrency = security.QuoteCurrency.Symbol;

            return new OrderFee(new CashAmount(feeAmount, quoteCurrency));
        }
    }
}