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
    /// Provides the fee model for Gate.io USDT-margined perpetual futures
    /// </summary>
    public class GateFuturesFeeModel : FeeModel
    {
        /// <summary>
        /// Tier 1 maker fee for USDT-margined futures (VIP 0)
        /// Negative value indicates maker rebate
        /// https://www.gate.io/fee
        /// </summary>
        public const decimal MakerFee = 0.0002m; // 0.02%

        /// <summary>
        /// Tier 1 taker fee for USDT-margined futures (VIP 0)
        /// https://www.gate.io/fee
        /// </summary>
        public const decimal TakerFee = 0.0005m; // 0.05%

        private readonly decimal _makerFee;
        private readonly decimal _takerFee;

        /// <summary>
        /// Creates Gate.io Futures fee model with custom fee rates
        /// </summary>
        /// <param name="makerFee">Maker fee rate (default: 0.02%)</param>
        /// <param name="takerFee">Taker fee rate (default: 0.05%)</param>
        public GateFuturesFeeModel(decimal makerFee = MakerFee, decimal takerFee = TakerFee)
        {
            _makerFee = makerFee;
            _takerFee = takerFee;
        }

        /// <summary>
        /// Gets the order fee associated with the specified order.
        /// </summary>
        /// <param name="parameters">A <see cref="OrderFeeParameters"/> object containing the security and order</param>
        /// <returns>The cost of the order in a <see cref="CashAmount"/> instance</returns>
        public override OrderFee GetOrderFee(OrderFeeParameters parameters)
        {
            var order = parameters.Order;
            var security = parameters.Security;

            // Determine fee rate based on order type
            // Limit orders are assumed to be maker orders (posted to order book)
            // Market orders are assumed to be taker orders (removed from order book)
            var feeRate = order.Type == OrderType.Limit ? _makerFee : _takerFee;

            // Calculate the fee amount
            // For futures, fee is based on notional value (contract size * price)
            var orderValue = order.GetValue(security);
            var feeAmount = feeRate * orderValue;

            // Gate.io futures fees are charged in the quote currency (USDT)
            var quoteCurrency = security.QuoteCurrency.Symbol;

            return new OrderFee(new CashAmount(feeAmount, quoteCurrency));
        }
    }
}
