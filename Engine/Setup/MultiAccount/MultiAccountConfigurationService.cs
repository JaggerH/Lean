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
using QuantConnect.Brokerages;
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

            /// <summary>
            /// Market to BrokerageModel mapping (e.g., { "Gate": GateBrokerageModel, "USA": IBKRBrokerageModel })
            /// </summary>
            /// <remarks>
            /// Used by RoutedBrokerageModel to route securities to their appropriate brokerage models
            /// based on the security's market (Symbol.ID.Market)
            /// </remarks>
            public Dictionary<string, IBrokerageModel> MarketToBrokerageModel { get; set; }
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
                BrokerageConfigs = new Dictionary<string, JObject>(),
                MarketToBrokerageModel = new Dictionary<string, IBrokerageModel>(StringComparer.OrdinalIgnoreCase)
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

                // Extract cash
                var initialCash = accountConfig["cash"]?.Value<decimal>() ?? 0m;
                config.AccountInitialCash[accountName] = initialCash;

                // Extract brokerage name
                var brokerageName = accountConfig["brokerage"]?.Value<string>();
                if (string.IsNullOrEmpty(brokerageName))
                {
                    throw new ArgumentException($"Account '{accountName}' missing 'brokerage' field");
                }

                // Extract market name (optional, defaults to account name if not specified)
                var market = accountConfig["market"]?.Value<string>();
                if (string.IsNullOrEmpty(market))
                {
                    market = accountName;
                    Log.Trace($"MultiAccountConfigurationService.ParseMultiBrokerageConfig(): Account '{accountName}' missing 'market' field, using account name as market");
                }

                // Extract brokerage-params (optional)
                var brokerageParams = accountConfig["brokerage-params"] as JObject;

                // Check if brokerageModelType is specified in brokerage-params
                string brokerageModelTypeName = null;
                if (brokerageParams != null)
                {
                    var modelTypeToken = brokerageParams["brokerageModelType"];
                    if (modelTypeToken != null)
                    {
                        brokerageModelTypeName = modelTypeToken.Value<string>();
                    }
                }

                // Create BrokerageModel with custom parameters
                try
                {
                    var brokerageFactory = Composer.Instance.Single<IBrokerageFactory>(
                        bf => bf.BrokerageType.MatchesTypeName(brokerageName));

                    // Create BrokerageModel with parameters if provided
                    IBrokerageModel brokerageModel;
                    if (brokerageParams != null && brokerageParams.HasValues)
                    {
                        brokerageModel = CreateBrokerageModelWithParams(brokerageFactory, brokerageParams, uninitializedAlgorithm.Transactions, accountName, brokerageModelTypeName);
                    }
                    else
                    {
                        // Use default (via factory)
                        brokerageModel = brokerageFactory.GetBrokerageModel(uninitializedAlgorithm.Transactions);
                    }

                    var defaultCurrency = brokerageModel.DefaultAccountCurrency;

                    config.AccountCurrencies[accountName] = defaultCurrency;
                    config.BrokerageConfigs[accountName] = accountConfig;

                    // Build market → BrokerageModel mapping
                    if (!config.MarketToBrokerageModel.ContainsKey(market))
                    {
                        config.MarketToBrokerageModel[market] = brokerageModel;
                        Log.Trace($"MultiAccountConfigurationService.ParseMultiBrokerageConfig(): Market '{market}' → BrokerageModel '{brokerageModel.GetType().Name}'");
                    }

                    Log.Trace($"MultiAccountConfigurationService.ParseMultiBrokerageConfig(): '{accountName}' → Brokerage '{brokerageName}' → Market '{market}' → Currency '{defaultCurrency}'");
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

        /// <summary>
        /// Creates a BrokerageModel instance with custom parameters using reflection
        /// </summary>
        /// <param name="brokerageFactory">The brokerage factory</param>
        /// <param name="brokerageParams">Parameters from config.json</param>
        /// <param name="transactions">SecurityTransactionManager</param>
        /// <param name="accountName">Account name for logging</param>
        /// <param name="brokerageModelTypeName">Optional: specific BrokerageModel type name to create</param>
        /// <returns>BrokerageModel instance</returns>
        private IBrokerageModel CreateBrokerageModelWithParams(
            IBrokerageFactory brokerageFactory,
            JObject brokerageParams,
            Securities.SecurityTransactionManager transactions,
            string accountName,
            string brokerageModelTypeName = null)
        {
            // Determine the BrokerageModel type
            Type brokerageModelType;
            if (!string.IsNullOrEmpty(brokerageModelTypeName))
            {
                // Use specified type name
                try
                {
                    brokerageModelType = AppDomain.CurrentDomain.GetAssemblies()
                        .SelectMany(a => a.GetTypes())
                        .FirstOrDefault(t => t.Name.Equals(brokerageModelTypeName, StringComparison.OrdinalIgnoreCase) &&
                                            typeof(IBrokerageModel).IsAssignableFrom(t));

                    if (brokerageModelType == null)
                    {
                        throw new ArgumentException($"Could not find BrokerageModel type: {brokerageModelTypeName}");
                    }
                }
                catch (Exception ex)
                {
                    Log.Error($"MultiAccountConfigurationService.CreateBrokerageModelWithParams(): Failed to find type '{brokerageModelTypeName}': {ex.Message}");
                    throw;
                }
            }
            else
            {
                // Get the BrokerageModel type from the factory
                var defaultModel = brokerageFactory.GetBrokerageModel(transactions);
                brokerageModelType = defaultModel.GetType();
            }

            // Find constructors
            var constructors = brokerageModelType.GetConstructors();

            // Try to find a constructor that matches the provided parameters
            foreach (var constructor in constructors.OrderByDescending(c => c.GetParameters().Length))
            {
                var parameters = constructor.GetParameters();
                var args = new object[parameters.Length];
                var allMatched = true;

                for (int i = 0; i < parameters.Length; i++)
                {
                    var param = parameters[i];
                    var paramName = param.Name;

                    // Try to find matching parameter in brokerageParams (case-insensitive)
                    var configValue = brokerageParams.Properties()
                        .FirstOrDefault(p => string.Equals(p.Name, paramName, StringComparison.OrdinalIgnoreCase));

                    if (configValue != null)
                    {
                        // Parse the value based on parameter type
                        try
                        {
                            args[i] = ConvertJsonValueToType(configValue.Value, param.ParameterType);
                            Log.Trace($"  Parameter '{paramName}' = {args[i]} ({param.ParameterType.Name})");
                        }
                        catch (Exception ex)
                        {
                            Log.Error($"  Failed to convert parameter '{paramName}': {ex.Message}");
                            allMatched = false;
                            break;
                        }
                    }
                    else if (param.HasDefaultValue)
                    {
                        // Use default value
                        args[i] = param.DefaultValue;
                        Log.Trace($"  Parameter '{paramName}' using default = {args[i]}");
                    }
                    else
                    {
                        // Required parameter not provided
                        allMatched = false;
                        break;
                    }
                }

                if (allMatched)
                {
                    // Found a matching constructor, create the instance
                    try
                    {
                        var instance = Activator.CreateInstance(brokerageModelType, args) as IBrokerageModel;
                        Log.Trace($"MultiAccountConfigurationService.CreateBrokerageModelWithParams(): Successfully created {brokerageModelType.Name}");
                        return instance;
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"MultiAccountConfigurationService.CreateBrokerageModelWithParams(): Failed to instantiate {brokerageModelType.Name}: {ex.Message}");
                        throw;
                    }
                }
            }

            // If no matching constructor found, create with default constructor
            try
            {
                var instance = Activator.CreateInstance(brokerageModelType) as IBrokerageModel;
                if (instance != null)
                {
                    return instance;
                }
            }
            catch (Exception ex)
            {
                Log.Error($"MultiAccountConfigurationService.CreateBrokerageModelWithParams(): Failed to create default instance: {ex.Message}");
            }

            // Final fallback: use factory default
            return brokerageFactory.GetBrokerageModel(transactions);
        }

        /// <summary>
        /// Converts a JToken value to the specified type
        /// </summary>
        private object ConvertJsonValueToType(JToken value, Type targetType)
        {
            // Handle enums
            if (targetType.IsEnum)
            {
                var stringValue = value.Value<string>();
                return Enum.Parse(targetType, stringValue, ignoreCase: true);
            }

            // Handle common types
            if (targetType == typeof(string))
                return value.Value<string>();
            if (targetType == typeof(int))
                return value.Value<int>();
            if (targetType == typeof(decimal))
                return value.Value<decimal>();
            if (targetType == typeof(bool))
                return value.Value<bool>();
            if (targetType == typeof(double))
                return value.Value<double>();
            if (targetType == typeof(long))
                return value.Value<long>();

            // Try generic ToObject
            return value.ToObject(targetType);
        }
    }
}
