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
using Newtonsoft.Json.Linq;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Util;

namespace QuantConnect.Lean.Engine.Setup.MultiAccount
{
    /// <summary>
    /// Service for parsing and validating multi-account configuration
    /// </summary>
    public class MultiAccountConfigurationService
    {
        /// <summary>
        /// Represents a parsed multi-account configuration
        /// </summary>
        public class MultiAccountConfiguration
        {
            /// <summary>
            /// Account initial cash amounts (e.g., { "gate": 10000, "binance": 5000 })
            /// </summary>
            public Dictionary<string, decimal> AccountInitialCash { get; set; }

            /// <summary>
            /// Account currencies (e.g., { "gate": "USDT", "binance": "USDT" })
            /// </summary>
            /// <remarks>
            /// CRITICAL: Must be populated from BrokerageModel.DefaultAccountCurrency
            /// </remarks>
            public Dictionary<string, string> AccountCurrencies { get; set; }

            /// <summary>
            /// Order router for routing orders to accounts
            /// </summary>
            public IOrderRouter Router { get; set; }

            /// <summary>
            /// Whether this is multi-brokerage mode (each account has different brokerage)
            /// </summary>
            public bool IsMultiBrokerageMode { get; set; }

            /// <summary>
            /// Brokerage configs per account (multi-brokerage mode only)
            /// </summary>
            public Dictionary<string, JObject> BrokerageConfigs { get; set; }
        }

        /// <summary>
        /// Parses multi-brokerage configuration
        /// </summary>
        /// <param name="multiBrokerageConfig">The multi-brokerage configuration JSON</param>
        /// <param name="uninitializedAlgorithm">The uninitialized algorithm instance</param>
        /// <returns>Parsed configuration</returns>
        public MultiAccountConfiguration ParseMultiBrokerageConfig(
            JObject multiBrokerageConfig,
            IAlgorithm uninitializedAlgorithm)
        {
            var config = new MultiAccountConfiguration
            {
                IsMultiBrokerageMode = true,
                AccountInitialCash = new Dictionary<string, decimal>(),
                AccountCurrencies = new Dictionary<string, string>(),
                BrokerageConfigs = new Dictionary<string, JObject>()
            };

            var accountsNode = multiBrokerageConfig["accounts"] as JObject;
            if (accountsNode == null)
            {
                throw new ArgumentException("multi-account-config missing 'accounts' node");
            }

            foreach (var kvp in accountsNode)
            {
                var accountName = kvp.Key;
                var accountConfig = kvp.Value as JObject;

                // Extract initial-cash
                var initialCash = accountConfig["initial-cash"]?.Value<decimal>() ?? 0m;
                config.AccountInitialCash[accountName] = initialCash;

                // Extract brokerage name
                var brokerageName = accountConfig["brokerage"]?.Value<string>();
                if (string.IsNullOrEmpty(brokerageName))
                {
                    throw new ArgumentException($"Account '{accountName}' missing 'brokerage' field");
                }

                // Query BrokerageModel.DefaultAccountCurrency
                try
                {
                    var brokerageFactory = Composer.Instance.Single<IBrokerageFactory>(
                        bf => bf.BrokerageType.MatchesTypeName(brokerageName));

                    var brokerageModel = brokerageFactory.GetBrokerageModel(uninitializedAlgorithm.Transactions);
                    var defaultCurrency = brokerageModel.DefaultAccountCurrency;

                    config.AccountCurrencies[accountName] = defaultCurrency;
                    config.BrokerageConfigs[accountName] = accountConfig;

                    Log.Trace($"MultiAccountConfigurationService.ParseMultiBrokerageConfig(): '{accountName}' → Brokerage '{brokerageName}' → Currency '{defaultCurrency}'");
                }
                catch (Exception ex)
                {
                    throw new ArgumentException($"Failed to find brokerage factory for '{brokerageName}' (account '{accountName}'): {ex.Message}", ex);
                }
            }

            // Parse router
            var routerNode = multiBrokerageConfig["router"];
            if (routerNode != null)
            {
                config.Router = CreateRouter(routerNode, uninitializedAlgorithm);
            }

            return config;
        }

        /// <summary>
        /// Parses single-brokerage multi-account configuration
        /// </summary>
        /// <param name="configToken">The configuration JSON</param>
        /// <param name="brokerageFactory">The brokerage factory</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Parsed configuration</returns>
        public MultiAccountConfiguration ParseSingleBrokerageConfig(
            JToken configToken,
            IBrokerageFactory brokerageFactory,
            IAlgorithm algorithm)
        {
            var config = new MultiAccountConfiguration
            {
                IsMultiBrokerageMode = false,
                AccountInitialCash = new Dictionary<string, decimal>(),
                AccountCurrencies = new Dictionary<string, string>()
            };

            // Query DefaultAccountCurrency from brokerage model
            var brokerageModel = brokerageFactory.GetBrokerageModel(algorithm.Transactions);
            var defaultCurrency = brokerageModel.DefaultAccountCurrency;

            Log.Trace($"MultiAccountConfigurationService.ParseSingleBrokerageConfig(): Using '{defaultCurrency}' for all accounts");

            // Parse accounts
            var accountsNode = configToken["accounts"];
            if (accountsNode == null)
            {
                throw new ArgumentException("multi-account-config missing 'accounts'");
            }

            foreach (var kvp in ((JObject)accountsNode))
            {
                var accountName = kvp.Key;
                var initialCash = kvp.Value.Value<decimal>();

                config.AccountInitialCash[accountName] = initialCash;
                config.AccountCurrencies[accountName] = defaultCurrency;

                Log.Trace($"MultiAccountConfigurationService.ParseSingleBrokerageConfig(): Account '{accountName}' → {initialCash} {defaultCurrency}");
            }

            // Parse router
            var routerNode = configToken["router"];
            if (routerNode != null)
            {
                config.Router = CreateRouter(routerNode, algorithm);
            }

            return config;
        }

        /// <summary>
        /// Creates order router from configuration
        /// </summary>
        /// <param name="routerNode">The router configuration JSON</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Created router</returns>
        private IOrderRouter CreateRouter(JToken routerNode, IAlgorithm algorithm)
        {
            var routerType = routerNode["type"]?.Value<string>()?.ToLowerInvariant();
            var mappings = routerNode["mappings"]?.ToObject<Dictionary<string, string>>();

            if (mappings == null || !mappings.Any())
            {
                throw new ArgumentException("Router mappings cannot be null or empty");
            }

            var defaultAccount = mappings.First().Value;

            switch (routerType)
            {
                case "market":
                    return new MarketBasedRouter(mappings, defaultAccount);

                case "securitytype":
                    var typeMappings = ParseSecurityTypeMappings(mappings);
                    return new SecurityTypeRouter(typeMappings, defaultAccount);

                case "symbol":
                    // Symbol-based routing requires Symbol objects, fall back to market-based
                    Log.Trace("MultiAccountConfigurationService: Symbol-based routing not fully implemented, using MarketBasedRouter");
                    return new MarketBasedRouter(mappings, defaultAccount);

                default:
                    throw new ArgumentException($"Unknown router type: {routerType}. Supported types: Market, SecurityType");
            }
        }

        /// <summary>
        /// Parses security type mappings from string dictionary
        /// </summary>
        private Dictionary<SecurityType, string> ParseSecurityTypeMappings(Dictionary<string, string> mappings)
        {
            var result = new Dictionary<SecurityType, string>();

            foreach (var kvp in mappings)
            {
                if (Enum.TryParse<SecurityType>(kvp.Key, true, out var securityType))
                {
                    result[securityType] = kvp.Value;
                    Log.Trace($"MultiAccountConfigurationService: SecurityType '{securityType}' → Account '{kvp.Value}'");
                }
                else
                {
                    Log.Error($"MultiAccountConfigurationService: Invalid SecurityType '{kvp.Key}' in router mappings");
                }
            }

            return result;
        }

        /// <summary>
        /// Validates configuration to ensure accountCurrencies is properly populated
        /// </summary>
        /// <param name="config">The configuration to validate</param>
        public void ValidateConfiguration(MultiAccountConfiguration config)
        {
            if (config.AccountCurrencies == null || config.AccountCurrencies.Count == 0)
            {
                throw new InvalidOperationException("CRITICAL: AccountCurrencies is empty - this is a bug in configuration parsing");
            }

            foreach (var accountName in config.AccountInitialCash.Keys)
            {
                if (!config.AccountCurrencies.ContainsKey(accountName))
                {
                    throw new InvalidOperationException($"Account '{accountName}' missing currency mapping");
                }

                var currency = config.AccountCurrencies[accountName];
                if (string.IsNullOrEmpty(currency))
                {
                    throw new InvalidOperationException($"Account '{accountName}' has empty currency");
                }
            }

            Log.Trace($"MultiAccountConfigurationService.ValidateConfiguration(): ✓ {config.AccountCurrencies.Count} accounts validated");
        }
    }
}
