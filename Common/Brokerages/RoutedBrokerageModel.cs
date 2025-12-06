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
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Orders.Fills;
using QuantConnect.Orders.Slippage;
using QuantConnect.Securities;
using QuantConnect.Securities.Interfaces;
using QuantConnect.Util;

namespace QuantConnect.Brokerages
{
    /// <summary>
    /// Routed brokerage model that delegates to specific brokerage models based on the security's market.
    /// This is designed for multi-account, multi-brokerage scenarios where different securities
    /// trade on different exchanges with different brokerages.
    /// </summary>
    /// <remarks>
    /// Example: Gate.io for crypto (market="Gate"), Interactive Brokers for equities (market="USA")
    /// Each market routes to its corresponding BrokerageModel, ensuring correct leverage, fees, etc.
    /// </remarks>
    public class RoutedBrokerageModel : DefaultBrokerageModel
    {
        private readonly Dictionary<string, IBrokerageModel> _marketToBrokerageModel;
        private readonly IReadOnlyDictionary<SecurityType, string> _mergedDefaultMarkets;
        private readonly IBrokerageModel _fallbackModel;

        /// <summary>
        /// Creates a new RoutedBrokerageModel
        /// </summary>
        /// <param name="marketToBrokerageModel">Dictionary mapping market names to their respective BrokerageModels</param>
        /// <param name="fallbackModel">Optional fallback model to use when market is not found. If null, uses the first model in the dictionary.</param>
        public RoutedBrokerageModel(
            Dictionary<string, IBrokerageModel> marketToBrokerageModel,
            IBrokerageModel fallbackModel = null)
        {
            if (marketToBrokerageModel == null || marketToBrokerageModel.Count == 0)
            {
                throw new ArgumentException("marketToBrokerageModel cannot be null or empty");
            }

            // Use case-insensitive dictionary for market lookups (e.g., "USA" vs "usa")
            _marketToBrokerageModel = new Dictionary<string, IBrokerageModel>(StringComparer.OrdinalIgnoreCase);
            foreach (var kvp in marketToBrokerageModel)
            {
                _marketToBrokerageModel[kvp.Key] = kvp.Value;
            }

            _fallbackModel = fallbackModel ?? _marketToBrokerageModel.Values.First();

            // Merge DefaultMarkets from all brokerage models
            var mergedMarkets = new Dictionary<SecurityType, string>();
            foreach (var brokerageModel in _marketToBrokerageModel.Values)
            {
                foreach (var kvp in brokerageModel.DefaultMarkets)
                {
                    // If not yet added, add it
                    if (!mergedMarkets.ContainsKey(kvp.Key))
                    {
                        mergedMarkets[kvp.Key] = kvp.Value;
                        Log.Trace($"RoutedBrokerageModel: Added default market '{kvp.Value}' for {kvp.Key}");
                    }
                }
            }
            _mergedDefaultMarkets = mergedMarkets;

            Log.Trace($"RoutedBrokerageModel: Created with {_marketToBrokerageModel.Count} market mappings, {_mergedDefaultMarkets.Count} default markets");
        }

        /// <summary>
        /// Gets the appropriate brokerage model for a given security based on its market
        /// </summary>
        /// <param name="security">The security to route</param>
        /// <returns>The brokerage model that handles this security's market</returns>
        private IBrokerageModel GetBrokerageModelForSecurity(Security security)
        {
            var market = security.Symbol.ID.Market;

            if (_marketToBrokerageModel.TryGetValue(market, out var model))
            {
                return model;
            }

            Log.Trace($"RoutedBrokerageModel: Market '{market}' not found for {security.Symbol}, using fallback model");
            return _fallbackModel;
        }

        /// <summary>
        /// Gets the merged default markets from all underlying brokerage models
        /// </summary>
        public override IReadOnlyDictionary<SecurityType, string> DefaultMarkets => _mergedDefaultMarkets;

        /// <summary>
        /// Gets the appropriate buying power model for a security, routed by market
        /// </summary>
        public override IBuyingPowerModel GetBuyingPowerModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetBuyingPowerModel(security);
        }

        /// <summary>
        /// Gets the appropriate buying power model for a security with account type, routed by market
        /// </summary>
        /// <remarks>
        /// Note: This method cannot override the base implementation as it's not virtual in DefaultBrokerageModel.
        /// It's provided for future compatibility if the base class is updated.
        /// </remarks>
        public new IBuyingPowerModel GetBuyingPowerModel(Security security, AccountType accountType)
        {
            var model = GetBrokerageModelForSecurity(security);

            // Check if the model supports the overload with AccountType
            if (model is DefaultBrokerageModel defaultModel)
            {
                return defaultModel.GetBuyingPowerModel(security, accountType);
            }

            return model.GetBuyingPowerModel(security);
        }

        /// <summary>
        /// Gets the leverage for a security, routed by market
        /// </summary>
        public override decimal GetLeverage(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetLeverage(security);
        }

        /// <summary>
        /// Gets the fee model for a security, routed by market
        /// </summary>
        public override IFeeModel GetFeeModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetFeeModel(security);
        }

        /// <summary>
        /// Gets the fill model for a security, routed by market
        /// </summary>
        public override IFillModel GetFillModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetFillModel(security);
        }

        /// <summary>
        /// Gets the slippage model for a security, routed by market
        /// </summary>
        public override ISlippageModel GetSlippageModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetSlippageModel(security);
        }

        /// <summary>
        /// Gets the settlement model for a security, routed by market
        /// </summary>
        public override ISettlementModel GetSettlementModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetSettlementModel(security);
        }

        /// <summary>
        /// Gets the settlement model for a security and account type, routed by market
        /// </summary>
        /// <remarks>
        /// Note: This method cannot override the base implementation as it's not virtual in DefaultBrokerageModel.
        /// It's provided for future compatibility if the base class is updated.
        /// </remarks>
        public new ISettlementModel GetSettlementModel(Security security, AccountType accountType)
        {
            var model = GetBrokerageModelForSecurity(security);

            // Check if the model supports the overload with AccountType
            if (model is DefaultBrokerageModel defaultModel)
            {
                return defaultModel.GetSettlementModel(security, accountType);
            }

            return model.GetSettlementModel(security);
        }

        /// <summary>
        /// Gets the margin interest rate model for a security, routed by market
        /// </summary>
        public override IMarginInterestRateModel GetMarginInterestRateModel(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetMarginInterestRateModel(security);
        }

        /// <summary>
        /// Gets the shortable provider for a security, routed by market
        /// </summary>
        public override IShortableProvider GetShortableProvider(Security security)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.GetShortableProvider(security);
        }

        /// <summary>
        /// Gets the benchmark for the account, using the fallback model
        /// </summary>
        public override IBenchmark GetBenchmark(Securities.SecurityManager securities)
        {
            // Use the fallback model for benchmark
            return _fallbackModel.GetBenchmark(securities);
        }

        /// <summary>
        /// Returns true if the brokerage could accept this order
        /// Uses the fallback model for general order validation
        /// </summary>
        public override bool CanSubmitOrder(Security security, Order order, out BrokerageMessageEvent message)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.CanSubmitOrder(security, order, out message);
        }

        /// <summary>
        /// Returns true if the brokerage would allow updating the order
        /// </summary>
        public override bool CanUpdateOrder(Security security, Order order, UpdateOrderRequest request, out BrokerageMessageEvent message)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.CanUpdateOrder(security, order, request, out message);
        }

        /// <summary>
        /// Returns true if the brokerage would be able to execute this order at this time
        /// </summary>
        public override bool CanExecuteOrder(Security security, Order order)
        {
            var model = GetBrokerageModelForSecurity(security);
            return model.CanExecuteOrder(security, order);
        }

        /// <summary>
        /// Applies the split to the open orders, routed by market
        /// </summary>
        public override void ApplySplit(List<OrderTicket> tickets, Split split)
        {
            // Get the model based on the split's symbol
            var market = split.Symbol.ID.Market;
            if (_marketToBrokerageModel.TryGetValue(market, out var model))
            {
                model.ApplySplit(tickets, split);
                return;
            }

            // Fallback
            _fallbackModel.ApplySplit(tickets, split);
        }

        /// <summary>
        /// Gets a map of the default markets for each security type
        /// </summary>
        public IReadOnlyDictionary<string, IBrokerageModel> GetMarketMappings()
        {
            return _marketToBrokerageModel;
        }
    }
}
