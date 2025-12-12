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
using QuantConnect.Securities.CryptoFuture;
using QuantConnect.Util;

namespace QuantConnect.Brokerages
{
    /// <summary>
    /// Provides Gate.io Unified Account specific properties and settings
    /// Supports simultaneous trading of both Spot (Crypto) and Futures (CryptoFuture) markets
    /// </summary>
    /// <remarks>
    /// <para><strong>Gate.io Unified Account - Simplified Implementation</strong></para>
    ///
    /// <para><strong>Supported Features:</strong></para>
    /// <list type="bullet">
    /// <item>Spot holdings (BTC, ETH, etc.) serve as collateral for futures positions</item>
    /// <item>Currency-specific discount rates (haircuts) applied to spot collateral</item>
    /// <item>Cross-margin across all futures sharing the same collateral currency</item>
    /// <item>Tiered maintenance margin rates based on position size</item>
    /// <item>Futures trading with up to 5x leverage (configurable)</item>
    /// </list>
    ///
    /// <para><strong>Limitations (Simplifications vs Official Gate.io):</strong></para>
    /// <list type="bullet">
    /// <item><strong>NO spot margin trading</strong> - spot cannot borrow funds (no USDT/crypto borrowing)</item>
    /// <item><strong>NO interest payments</strong> - since no borrowing is supported</item>
    /// <item>Spot leverage is always 1x (cash-only trading)</item>
    /// <item>3-tier maintenance margin system instead of official 7-tier</item>
    /// <item>Fixed leverage (no automatic position-size adjustment)</item>
    /// </list>
    ///
    /// <para><strong>Use Case:</strong></para>
    /// <para>
    /// User holds spot crypto assets + USDT. Spot assets contribute to futures margin
    /// with currency-specific discounts. Futures can be traded with leverage. No borrowing involved.
    /// </para>
    ///
    /// <para><strong>Example:</strong></para>
    /// <code>
    /// Holdings: $10,000 USDT + 1 BTC ($50,000)
    /// Total Collateral: $10,000 + ($50,000 × 0.95 discount) = $57,500
    /// Futures Buying Power: $57,500 × 5x leverage = $287,500
    /// </code>
    /// </remarks>
    public class GateUnifiedBrokerageModel : DefaultBrokerageModel
    {
        /// <summary>
        /// Market name for Gate.io
        /// </summary>
        protected virtual string MarketName => Market.Gate;

        /// <summary>
        /// Gets the default account currency for Gate.io Unified Account (USDT)
        /// </summary>
        public override string DefaultAccountCurrency => "USDT";

        /// <summary>
        /// Gets a map of the default markets to be used for each security type
        /// Unified account supports both Crypto (Spot) and CryptoFuture markets
        /// </summary>
        public override IReadOnlyDictionary<SecurityType, string> DefaultMarkets { get; } = GetDefaultMarkets();

        /// <summary>
        /// Represents a set of order types supported by the unified account model
        /// </summary>
        private readonly HashSet<OrderType> _supportedOrderTypes = new()
        {
            OrderType.Market,
            OrderType.Limit,
            OrderType.StopMarket,
            OrderType.StopLimit,
        };

        /// <summary>
        /// Initializes a new instance of the <see cref="GateUnifiedBrokerageModel"/> class
        /// </summary>
        /// <param name="accountType">The type of account to be modeled, defaults to <see cref="AccountType.Margin"/></param>
        /// <remarks>
        /// Unified accounts use Margin type because spot funds serve as margin for futures trading
        /// </remarks>
        public GateUnifiedBrokerageModel(AccountType accountType = AccountType.Margin) : base(accountType)
        {
            if (accountType == AccountType.Cash)
            {
                throw new InvalidOperationException(
                    "Gate.io Unified Account requires Margin account type. " +
                    "Use AccountType.Margin to enable cross-margin trading between Spot and Futures.");
            }
        }

        /// <summary>
        /// Gets the leverage for the specified security
        /// Returns different leverage based on security type:
        /// - Spot (Crypto): 1x (NO leverage, cash-only trading)
        ///   Note: Spot holdings serve as collateral for futures but cannot borrow for spot trading
        /// - Futures (CryptoFuture): 5x (configurable via SetLeverage, max 100x for major pairs)
        /// </summary>
        /// <param name="security">The security to get leverage for</param>
        /// <returns>The leverage to use for this security</returns>
        /// <remarks>
        /// Simplified Implementation:
        /// - Spot margin trading (borrowing) is NOT supported
        /// - Spot leverage is always 1x (cash-only)
        /// - Only futures can use leverage (default 5x)
        /// - Spot assets contribute to futures margin with currency-specific discounts
        /// </remarks>
        public override decimal GetLeverage(Security security)
        {
            if (AccountType == AccountType.Cash || security.IsInternalFeed() || security.Type == SecurityType.Base)
            {
                return 1m;
            }

            return security.Type switch
            {
                SecurityType.Crypto => 1m,         // Spot: NO leverage (cash-only, no borrowing)
                SecurityType.CryptoFuture => 5m,   // Futures: 5x default leverage (adjustable via SetLeverage)
                _ => throw new ArgumentException(
                    $"Gate.io Unified Account does not support security type {security.Type}. " +
                    $"Only Crypto (Spot) and CryptoFuture are supported.",
                    nameof(security))
            };
        }

        /// <summary>
        /// Provides appropriate fee model based on security type
        /// </summary>
        /// <param name="security">The security to get a fee model for</param>
        /// <returns>The fee model for this brokerage</returns>
        public override IFeeModel GetFeeModel(Security security)
        {
            return security.Type switch
            {
                SecurityType.Crypto => new GateFeeModel(),              // Spot trading fees
                SecurityType.CryptoFuture => new GateFuturesFeeModel(), // Futures trading fees
                SecurityType.Base => base.GetFeeModel(security),
                _ => throw new ArgumentOutOfRangeException(
                    nameof(security), security,
                    $"Gate.io Unified Account does not support security type {security.Type}")
            };
        }

        /// <summary>
        /// Gets a new buying power model for the security
        /// Different models are used for Spot vs Futures trading
        /// </summary>
        /// <param name="security">The security to get a buying power model for</param>
        /// <returns>The buying power model for this brokerage/security</returns>
        /// <remarks>
        /// <para><strong>Futures (CryptoFuture):</strong></para>
        /// <list type="bullet">
        /// <item>Uses UnifiedAccountMarginModel with cross-margin support</item>
        /// <item>Spot crypto balances contribute as collateral with currency-specific discounts</item>
        /// <item>Supports up to 5x leverage (configurable via SetLeverage)</item>
        /// <item>Tiered maintenance margin rates based on position size</item>
        /// </list>
        ///
        /// <para><strong>Spot (Crypto):</strong></para>
        /// <list type="bullet">
        /// <item>Uses default cash-based buying power model (NO leverage)</item>
        /// <item>NO margin trading / NO borrowing supported (simplified implementation)</item>
        /// <item>Spot holdings serve ONLY as collateral for futures positions</item>
        /// <item>Leverage is always 1x (cash-only trading)</item>
        /// </list>
        ///
        /// <para><strong>Why Spot Doesn't Use UnifiedAccountMarginModel:</strong></para>
        /// <para>
        /// Implementing spot margin trading (borrowing) requires:
        /// 1. Negative cash balance management (borrowing USDT/crypto)
        /// 2. Interest payment mechanism for borrowed funds
        /// 3. Borrow limit checks (exchange liquidity)
        /// 4. Interest rate fluctuation handling in backtesting
        /// These features are not currently supported in LEAN's architecture.
        /// </para>
        /// </remarks>
        public override IBuyingPowerModel GetBuyingPowerModel(Security security)
        {
            if (security.Type == SecurityType.CryptoFuture)
            {
                // Futures use unified account margin model with cross-margin support
                // Spot crypto balances contribute as collateral for futures positions
                // with currency-specific discount rates (haircuts)
                return new UnifiedAccountMarginModel(
                    leverage: GetLeverage(security),
                    defaultMaintenanceRate: 0.02m,  // 2% mid-tier maintenance margin
                    maintenanceAmount: 0
                );
            }

            // Spot trading uses cash-based buying power (NO leverage, NO borrowing)
            // Spot holdings serve ONLY as collateral for futures positions
            // If you need spot margin trading (borrowing), this model does NOT support it
            return base.GetBuyingPowerModel(security);
        }

        /// <summary>
        /// Gets a new margin interest rate model for the security
        /// </summary>
        /// <param name="security">The security to get a margin interest rate model for</param>
        /// <returns>The margin interest rate model for this brokerage</returns>
        public override IMarginInterestRateModel GetMarginInterestRateModel(Security security)
        {
            // Perpetual futures use funding rate mechanism
            if (security.Type == SecurityType.CryptoFuture &&
                security.Symbol.ID.Date == SecurityIdentifier.DefaultDate)
            {
                // Gate.io funding rate: exchanged every 8 hours between long/short positions
                return new GateFutureMarginInterestRateModel();
            }

            return base.GetMarginInterestRateModel(security);
        }

        /// <summary>
        /// Get the benchmark for this model
        /// </summary>
        /// <param name="securities">SecurityService to create the security with if needed</param>
        /// <returns>The benchmark for this brokerage</returns>
        public override IBenchmark GetBenchmark(SecurityManager securities)
        {
            // Use BTC perpetual future as benchmark for unified account
            var symbol = Symbol.Create("BTCUSDT", SecurityType.CryptoFuture, MarketName);
            return SecurityBenchmark.CreateInstance(securities, symbol);
        }

        /// <summary>
        /// Returns true if the brokerage could accept this order
        /// Validates order type, security type, and lot size requirements
        /// </summary>
        /// <param name="security">The security of the order</param>
        /// <param name="order">The order to be processed</param>
        /// <param name="message">If this function returns false, a brokerage message detailing why the order may not be submitted</param>
        /// <returns>True if the brokerage could process the order, false otherwise</returns>
        public override bool CanSubmitOrder(Security security, Order order, out BrokerageMessageEvent message)
        {
            message = null;

            // Validate security type
            if (security.Type != SecurityType.Crypto && security.Type != SecurityType.CryptoFuture)
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    $"Gate.io Unified Account only supports Crypto (Spot) and CryptoFuture security types. " +
                    $"Received: {security.Type}");
                return false;
            }

            // Validate order type
            if (!_supportedOrderTypes.Contains(order.Type))
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, -1,
                    $"Gate.io Unified Account does not support {order.Type} order type. Supported types: {string.Join(", ", _supportedOrderTypes)}");
                return false;
            }

            // Validate lot size
            var lotSize = security.SymbolProperties.LotSize;
            if (order.Quantity % lotSize != 0)
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    $"Order quantity {order.Quantity} must be a multiple of lot size {lotSize}");
                return false;
            }

            return base.CanSubmitOrder(security, order, out message);
        }

        /// <summary>
        /// Checks whether an order can be updated in the unified account model
        /// </summary>
        /// <param name="security">The security of the order</param>
        /// <param name="order">The order to be updated</param>
        /// <param name="request">The update request</param>
        /// <param name="message">If this function returns false, a brokerage message detailing why the order may not be updated</param>
        /// <returns>True if the update requested quantity is valid, false otherwise</returns>
        public override bool CanUpdateOrder(Security security, Order order, UpdateOrderRequest request, out BrokerageMessageEvent message)
        {
            // If quantity is not being updated, allow the update
            if (request.Quantity == null)
            {
                message = null;
                return true;
            }

            // Validate new quantity is a multiple of lot size
            var requestedQuantity = (decimal)request.Quantity;
            var lotSize = security.SymbolProperties.LotSize;
            if (requestedQuantity % lotSize != 0)
            {
                message = new BrokerageMessageEvent(BrokerageMessageType.Warning, "NotSupported",
                    $"Order quantity {requestedQuantity} must be a multiple of lot size {lotSize}");
                return false;
            }

            message = null;
            return true;
        }

        /// <summary>
        /// Gets the default markets for Gate.io Unified Account
        /// </summary>
        /// <returns>The default market map</returns>
        private static IReadOnlyDictionary<SecurityType, string> GetDefaultMarkets()
        {
            var map = DefaultMarketMap.ToDictionary();
            map[SecurityType.Crypto] = Market.Gate;         // Spot market
            map[SecurityType.CryptoFuture] = Market.Gate;   // Futures market
            return map.ToReadOnlyDictionary();
        }
    }
}
