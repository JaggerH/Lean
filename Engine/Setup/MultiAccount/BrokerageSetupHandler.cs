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
using System.Globalization;
using System.Linq;
using System.Reflection;
using Fasterflect;
using QuantConnect.AlgorithmFactory;
using QuantConnect.Brokerages;
using QuantConnect.Configuration;
using QuantConnect.Data;
using QuantConnect.Data.Market;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Lean.Engine.DataFeeds;
using QuantConnect.Lean.Engine.DataFeeds.Enumerators;
using QuantConnect.Lean.Engine.Results;
using QuantConnect.Lean.Engine.TransactionHandlers;
using QuantConnect.Logging;
using QuantConnect.Packets;
using QuantConnect.Securities;
using QuantConnect.Securities.MultiAccount;
using QuantConnect.Util;

namespace QuantConnect.Lean.Engine.Setup.MultiAccount
{
    /// <summary>
    /// Multi-account brokerage setup handler that initializes the algorithm with multiple trading accounts
    /// </summary>
    /// <remarks>
    /// This handler supports two multi-account modes:
    /// 1. Single brokerage, multiple accounts (e.g., Gate.io with multiple sub-accounts)
    /// 2. Multiple brokerages, multiple accounts (e.g., Gate.io + Binance)
    /// </remarks>
    public class BrokerageSetupHandler : ISetupHandler
    {
        private bool _disposed;
        private IBrokerageFactory _factory;
        private IBrokerage _dataQueueHandlerBrokerage;
        private IBrokerageModel _compositeBrokerageModel;

        // Multi-account services
        private MultiAccountConfigurationService _configService;
        private MultiAccountPortfolioFactory _portfolioFactory;
        private CurrencyConversionCoordinator _conversionCoordinator;

        /// <summary>
        /// Max allocation limit configuration variable name
        /// </summary>
        public static string MaxAllocationLimitConfig = "max-allocation-limit";

        /// <summary>
        /// The worker thread instance the setup handler should use
        /// </summary>
        public WorkerThread WorkerThread { get; set; }

        /// <summary>
        /// Any errors from the initialization stored here:
        /// </summary>
        public List<Exception> Errors { get; set; }

        /// <summary>
        /// Get the maximum runtime for this algorithm job.
        /// </summary>
        public TimeSpan MaximumRuntime { get; }

        /// <summary>
        /// Algorithm starting capital for statistics calculations
        /// </summary>
        public decimal StartingPortfolioValue { get; private set; }

        /// <summary>
        /// Start date for analysis loops to search for data.
        /// </summary>
        public DateTime StartingDate { get; private set; }

        /// <summary>
        /// Maximum number of orders for the algorithm run -- applicable for backtests only.
        /// </summary>
        public int MaxOrders { get; }

        /// <summary>
        /// Initializes a new multi-account BrokerageSetupHandler
        /// </summary>
        public BrokerageSetupHandler()
        {
            Errors = new List<Exception>();
            MaximumRuntime = TimeSpan.FromDays(10 * 365);
            MaxOrders = int.MaxValue;

            // Initialize multi-account services
            _configService = new MultiAccountConfigurationService();
            _portfolioFactory = new MultiAccountPortfolioFactory();
            _conversionCoordinator = new CurrencyConversionCoordinator();
        }

        /// <summary>
        /// Create a new instance of an algorithm from a physical dll path.
        /// </summary>
        /// <param name="assemblyPath">The path to the assembly's location</param>
        /// <param name="algorithmNodePacket">Details of the task required</param>
        /// <returns>A new instance of IAlgorithm, or throws an exception if there was an error</returns>
        public IAlgorithm CreateAlgorithmInstance(AlgorithmNodePacket algorithmNodePacket, string assemblyPath)
        {
            string error;
            IAlgorithm algorithm;

            // limit load times to 10 seconds and force the assembly to have exactly one derived type
            var loader = new Loader(false, algorithmNodePacket.Language, BaseSetupHandler.AlgorithmCreationTimeout, names => names.SingleOrAlgorithmTypeName(Config.Get("algorithm-type-name", algorithmNodePacket.AlgorithmId)), WorkerThread);
            var complete = loader.TryCreateAlgorithmInstanceWithIsolator(assemblyPath, algorithmNodePacket.RamAllocation, out algorithm, out error);
            if (!complete) throw new AlgorithmSetupException($"During the algorithm initialization, the following exception has occurred: {error}");

            return algorithm;
        }

        /// <summary>
        /// Creates the multi-brokerage manager as specified by the multi-account configuration
        /// </summary>
        /// <param name="algorithmNodePacket">Job packet</param>
        /// <param name="uninitializedAlgorithm">The algorithm instance before Initialize has been called</param>
        /// <param name="factory">The brokerage factory</param>
        /// <returns>The MultiBrokerageManager instance</returns>
        public IBrokerage CreateBrokerage(AlgorithmNodePacket algorithmNodePacket, IAlgorithm uninitializedAlgorithm, out IBrokerageFactory factory)
        {
            var liveJob = algorithmNodePacket as LiveNodePacket;
            if (liveJob == null)
            {
                throw new ArgumentException("Multi-account BrokerageSetupHandler requires a LiveNodePacket");
            }

            Log.Trace($"BrokerageSetupHandler.CreateBrokerage(): Multi-brokerage multi-account mode");

            // Parse configuration using ConfigurationService
            var configString = Config.Get("multi-account-config");
            if (string.IsNullOrEmpty(configString))
            {
                throw new ArgumentException("Multi-account mode requires 'multi-account-config' in config");
            }

            var configToken = Newtonsoft.Json.Linq.JObject.Parse(configString);

            return CreateMultiBrokerageBrokerage(liveJob, uninitializedAlgorithm, configToken, out factory);
        }

        /// <summary>
        /// Creates multi-brokerage manager (multiple brokerages, multiple accounts)
        /// </summary>
        private IBrokerage CreateMultiBrokerageBrokerage(
            LiveNodePacket liveJob,
            IAlgorithm uninitializedAlgorithm,
            Newtonsoft.Json.Linq.JObject configToken,
            out IBrokerageFactory factory)
        {
            Log.Trace("BrokerageSetupHandler.CreateMultiBrokerageBrokerage(): Multi-brokerage mode");

            // Parse and validate configuration
            var routerNode = configToken["router"];
            configToken["router"] = routerNode ?? new Newtonsoft.Json.Linq.JObject
            {
                ["type"] = "Market",
                ["mappings"] = new Newtonsoft.Json.Linq.JObject()
            };

            var multiConfig = _configService.ParseMultiBrokerageConfig(configToken, uninitializedAlgorithm);
            _configService.ValidateConfiguration(multiConfig);

            // Create portfolio
            _portfolioFactory.CreateAndAttach(
                uninitializedAlgorithm,
                multiConfig.AccountInitialCash,
                multiConfig.AccountCurrencies,
                multiConfig.Router);

            // Create MultiBrokerageManager
            var multiBrokerageManager = new MultiBrokerageManager();
            var brokerageFactories = new List<IBrokerageFactory>();

            // Create each brokerage
            foreach (var kvp in multiConfig.BrokerageConfigs)
            {
                var accountName = kvp.Key;
                var accountConfig = kvp.Value;
                var brokerageName = accountConfig["brokerage"]?.ToString();

                Log.Trace($"BrokerageSetupHandler.CreateMultiBrokerageBrokerage(): Creating '{brokerageName}' for '{accountName}'");

                // Find the brokerage factory
                var brokerageFactory = Composer.Instance.Single<IBrokerageFactory>(
                    bf => bf.BrokerageType.MatchesTypeName(brokerageName));

                brokerageFactories.Add(brokerageFactory);

                // Create temporary LiveNodePacket for this brokerage
                var brokerageJob = new LiveNodePacket
                {
                    Brokerage = brokerageName,
                    DataQueueHandler = liveJob.DataQueueHandler,
                    BrokerageData = new Dictionary<string, string>(liveJob.BrokerageData),
                    Controls = liveJob.Controls,
                    UserId = liveJob.UserId,
                    ProjectId = liveJob.ProjectId
                };

                // Create the brokerage instance
                var accountBrokerage = brokerageFactory.CreateBrokerage(brokerageJob, uninitializedAlgorithm);

                // Register with MultiBrokerageManager
                multiBrokerageManager.RegisterBrokerage(accountName, accountBrokerage);

                Log.Trace($"BrokerageSetupHandler.CreateMultiBrokerageBrokerage(): Registered '{brokerageName}' for '{accountName}'");
            }

            // Create routed brokerage model
            _compositeBrokerageModel = CreateRoutedBrokerageModel(multiConfig.MarketToBrokerageModel);
            Log.Trace($"BrokerageSetupHandler.CreateMultiBrokerageBrokerage(): Created routed brokerage model with {_compositeBrokerageModel.DefaultMarkets.Count} markets");

            // Return first factory for Engine compatibility
            _factory = brokerageFactories.First();
            factory = _factory;

            return multiBrokerageManager;
        }


        /// <summary>
        /// Primary entry point to setup a new algorithm
        /// </summary>
        /// <param name="parameters">The parameters object to use</param>
        /// <returns>True on successfully setting up the algorithm state, or false on error.</returns>
        public bool Setup(SetupHandlerParameters parameters)
        {
            var algorithm = parameters.Algorithm;
            var brokerage = parameters.Brokerage;

            // Verify we were given the correct job packet type
            var liveJob = parameters.AlgorithmNodePacket as LiveNodePacket;
            if (liveJob == null)
            {
                AddInitializationError("Multi-account BrokerageSetupHandler requires a LiveNodePacket");
                return false;
            }

            algorithm.Name = liveJob.GetAlgorithmName();

            // Verify the brokerage was specified
            if (string.IsNullOrWhiteSpace(liveJob.Brokerage))
            {
                AddInitializationError("A brokerage must be specified");
                return false;
            }

            BaseSetupHandler.Setup(parameters);

            // Attach to the message event to relay brokerage specific initialization messages
            EventHandler<BrokerageMessageEvent> brokerageOnMessage = (sender, args) =>
            {
                if (args.Type == BrokerageMessageType.Error)
                {
                    AddInitializationError($"Brokerage Error Code: {args.Code} - {args.Message}");
                }
            };

            try
            {
                // Let the world know what we're doing since logging in can take a minute
                parameters.ResultHandler.SendStatusUpdate(AlgorithmStatus.LoggingIn, "Logging into brokerage...");

                brokerage.Message += brokerageOnMessage;

                Log.Trace("BrokerageSetupHandler.Setup(): Connecting to brokerage...");
                try
                {
                    // this can fail for various reasons, such as already being logged in somewhere else
                    brokerage.Connect();
                }
                catch (Exception err)
                {
                    Log.Error(err);
                    AddInitializationError(
                        $"Error connecting to brokerage: {err.Message}. " +
                        "This may be caused by incorrect login credentials or an unsupported account type.", err);
                    return false;
                }

                if (!brokerage.IsConnected)
                {
                    // if we're reporting that we're not connected, bail
                    AddInitializationError("Unable to connect to brokerage.");
                    return false;
                }

                var message = $"{brokerage.Name} account base currency: {brokerage.AccountBaseCurrency ?? algorithm.AccountCurrency}";

                var accountCurrency = brokerage.AccountBaseCurrency;
                if (liveJob.BrokerageData.ContainsKey(MaxAllocationLimitConfig))
                {
                    accountCurrency = Currencies.USD;
                    message += ". Allocation limited, will use 'USD' account currency";
                }

                Log.Trace($"BrokerageSetupHandler.Setup(): {message}");
                algorithm.Debug(message);

                if (accountCurrency != null && accountCurrency != algorithm.AccountCurrency)
                {
                    algorithm.SetAccountCurrency(accountCurrency);
                }

                Log.Trace("BrokerageSetupHandler.Setup(): Initializing algorithm...");
                parameters.ResultHandler.SendStatusUpdate(AlgorithmStatus.Initializing, "Initializing algorithm...");

                // Execute the initialize code
                var controls = liveJob.Controls;
                var isolator = new Isolator();
                var initializeComplete = isolator.ExecuteWithTimeLimit(TimeSpan.FromSeconds(300), () =>
                {
                    try
                    {
                        // Set the brokerage model
                        if (_compositeBrokerageModel != null)
                        {
                            // Multi-brokerage mode: use composite model
                            algorithm.SetBrokerageModel(_compositeBrokerageModel);
                            Log.Trace($"BrokerageSetupHandler.Setup(): Set composite brokerage model with {_compositeBrokerageModel.DefaultMarkets.Count} markets");
                        }
                        else
                        {
                            // Single-brokerage mode: use brokerage's model
                            algorithm.SetBrokerageModel(_factory.GetBrokerageModel(algorithm.Transactions));
                        }

                        // Margin calls are disabled by default in live mode
                        algorithm.Portfolio.MarginCallModel = MarginCallModel.Null;

                        // Set our parameters
                        algorithm.SetParameters(liveJob.Parameters);
                        algorithm.SetAvailableDataTypes(BaseSetupHandler.GetConfiguredDataFeeds());

                        // Algorithm is live, not backtesting
                        algorithm.SetAlgorithmMode(liveJob.AlgorithmMode);

                        // Initialize the algorithm's starting date
                        algorithm.SetDateTime(DateTime.UtcNow);

                        // Set the source impl for the event scheduling
                        algorithm.Schedule.SetEventSchedule(parameters.RealTimeHandler);

                        // Set option chain provider
                        var optionChainProvider = Composer.Instance.GetPart<IOptionChainProvider>();
                        if (optionChainProvider == null)
                        {
                            var baseOptionChainProvider = new LiveOptionChainProvider();
                            baseOptionChainProvider.Initialize(new(parameters.MapFileProvider, algorithm.HistoryProvider));
                            optionChainProvider = new CachingOptionChainProvider(baseOptionChainProvider);
                            Composer.Instance.AddPart(optionChainProvider);
                        }
                        algorithm.SetOptionChainProvider(optionChainProvider);

                        // Set future chain provider
                        var futureChainProvider = Composer.Instance.GetPart<IFutureChainProvider>();
                        if (futureChainProvider == null)
                        {
                            var baseFutureChainProvider = new LiveFutureChainProvider();
                            baseFutureChainProvider.Initialize(new(parameters.MapFileProvider, algorithm.HistoryProvider));
                            futureChainProvider = new CachingFutureChainProvider(baseFutureChainProvider);
                            Composer.Instance.AddPart(futureChainProvider);
                        }
                        algorithm.SetFutureChainProvider(futureChainProvider);

                        // Inject ExecutionHistoryProvider for AIAlgorithm
                        if (algorithm is Interfaces.AIAlgorithm aiAlgorithm)
                        {
                            var multiBrokerage = (MultiBrokerageManager)brokerage;

                            // Validate execution history support before injecting provider
                            var unsupportedAccounts = ValidateExecutionHistorySupport(multiBrokerage);
                            if (unsupportedAccounts.Any())
                            {
                                var accountList = string.Join(", ", unsupportedAccounts);
                                var message = $"Warning: The following brokerage accounts do not support execution history (GetExecutionHistory): {accountList}. " +
                                             "Reconciliation features may not work correctly for these accounts.";
                                algorithm.Debug(message);
                                Log.Error($"BrokerageSetupHandler.Setup(): {message}");
                            }

                            aiAlgorithm.ExecutionHistoryProvider = new ExecutionHistory.BrokerageExecutionHistoryProvider(multiBrokerage);
                            Log.Trace("BrokerageSetupHandler.Setup(): ExecutionHistoryProvider injected successfully");
                        }

                        // Initialize the algorithm
                        algorithm.Initialize();
                    }
                    catch (Exception err)
                    {
                        AddInitializationError(err.ToString(), err);
                    }
                }, controls.RamAllocation,
                    sleepIntervalMillis: 100);

                if (Errors.Count != 0)
                {
                    return false;
                }

                if (!initializeComplete)
                {
                    AddInitializationError("Initialization timed out.");
                    return false;
                }

                // Zero the CashBook - we'll populate directly from brokerage
                if (liveJob.Brokerage != "PaperBrokerage")
                {
                    var multiAccountPortfolio = (MultiSecurityPortfolioManager)algorithm.Portfolio;

                    // Zero main account CashBook
                    foreach (var kvp in algorithm.Portfolio.CashBook)
                    {
                        kvp.Value.SetAmount(0);
                    }

                    // Zero all sub-account CashBooks
                    foreach (var accountName in multiAccountPortfolio.SubAccounts.Keys)
                    {
                        var subAccount = multiAccountPortfolio.GetAccount(accountName);
                        foreach (var kvp in subAccount.CashBook)
                        {
                            kvp.Value.SetAmount(0);
                        }
                    }
                }

                // Load cash balance from brokerage
                if (!LoadCashBalance(brokerage, algorithm))
                {
                    return false;
                }

                // Load existing holdings and orders BEFORE currency conversion setup
                // This ensures securities are created as user-facing (isInternalFeed: false) first,
                // so currency conversions can reuse them instead of creating internal-only feeds
                if (!LoadExistingHoldingsAndOrders(brokerage, algorithm, parameters))
                {
                    return false;
                }

                // PostInitialize must run after holdings/orders loaded but before currency conversion setup
                // This ensures subscriptions are created before SetupCurrencyConversions tries to use them
                algorithm.PostInitialize();

                // Multi-account currency conversion setup
                var multiPortfolio = (MultiSecurityPortfolioManager)algorithm.Portfolio;

                // Get ISecurityService from universeSelection
                var securityServiceField = parameters.UniverseSelection.GetType().GetField("_securityService",
                    BindingFlags.NonPublic | BindingFlags.Instance);

                if (securityServiceField == null)
                {
                    Log.Error("BrokerageSetupHandler.Setup(): Could not get _securityService field from UniverseSelection");
                }
                else
                {
                    var securityService = securityServiceField.GetValue(parameters.UniverseSelection) as ISecurityService;
                    if (securityService == null)
                    {
                        Log.Error("BrokerageSetupHandler.Setup(): _securityService field value is null or not ISecurityService");
                    }
                    else
                    {
                        // Step 1: Setup sub-account currency conversions
                        _conversionCoordinator.SetupSubAccountConversions(multiPortfolio, algorithm, securityService);

                        // Step 2: Sync sub-account cash and conversions to main CashBook
                        _conversionCoordinator.SyncConversionsToMain(multiPortfolio);

                        // Step 3: OnEndOfTimeStep to update conversion rates
                        algorithm.OnEndOfTimeStep();
                    }
                }

                // Setup main account currency conversions (will skip currencies already converted by sub-accounts)
                BaseSetupHandler.SetupCurrencyConversions(algorithm, parameters.UniverseSelection);

                // Set trading days per year for portfolio statistics
                BaseSetupHandler.SetBrokerageTradingDayPerYear(algorithm);

                var dataAggregator = Composer.Instance.GetPart<IDataAggregator>();
                dataAggregator?.Initialize(new() { AlgorithmSettings = algorithm.Settings });

                if (algorithm.Portfolio.TotalPortfolioValue == 0)
                {
                    algorithm.Debug("Warning: No cash balances or holdings were found in the brokerage account.");
                }

                // Check allocation limit
                string maxCashLimitStr;
                if (liveJob.BrokerageData.TryGetValue(MaxAllocationLimitConfig, out maxCashLimitStr))
                {
                    var maxCashLimit = decimal.Parse(maxCashLimitStr, NumberStyles.Any, CultureInfo.InvariantCulture);

                    if (algorithm.Portfolio.TotalPortfolioValue > (maxCashLimit + 10000m))
                    {
                        var exceptionMessage = $"TotalPortfolioValue '{algorithm.Portfolio.TotalPortfolioValue}' exceeds allocation limit '{maxCashLimit}'";
                        algorithm.Debug(exceptionMessage);
                        throw new ArgumentException(exceptionMessage);
                    }
                }

                // Set the starting portfolio value for the strategy to calculate performance
                StartingPortfolioValue = algorithm.Portfolio.TotalPortfolioValue;
                StartingDate = DateTime.Now;
            }
            catch (Exception err)
            {
                AddInitializationError(err.ToString(), err);
            }
            finally
            {
                if (brokerage != null)
                {
                    brokerage.Message -= brokerageOnMessage;
                }
            }

            return Errors.Count == 0;
        }

        /// <summary>
        /// Loads cash balance from multi-brokerage manager into multi-account portfolio
        /// </summary>
        private bool LoadCashBalance(IBrokerage brokerage, IAlgorithm algorithm)
        {
            Log.Trace("BrokerageSetupHandler.LoadCashBalance(): Fetching cash balance from multi-brokerage...");
            try
            {
                var multiPortfolio = (MultiSecurityPortfolioManager)algorithm.Portfolio;
                var multiBrokerage = (MultiBrokerageManager)brokerage;

                foreach (var accountName in multiBrokerage.GetAccountNames())
                {
                    var accountBrokerage = multiBrokerage.GetBrokerage(accountName);
                    var cashBalance = accountBrokerage.GetCashBalance();
                    var subAccount = multiPortfolio.GetAccount(accountName);

                    foreach (var cash in cashBalance)
                    {
                        var conversionRate = UsdPeggedStablecoinRegistry.GetUsdConversionRate(cash.Currency);
                        subAccount.SetCash(cash.Currency, cash.Amount, conversionRate);

                        // Set Identity conversion for stablecoins
                        if (UsdPeggedStablecoinRegistry.IsUsdPegged(cash.Currency))
                        {
                            var accountCurrency = subAccount.CashBook.AccountCurrency;
                            subAccount.CashBook[cash.Currency].CurrencyConversion =
                                QuantConnect.Securities.CurrencyConversion.ConstantCurrencyConversion.Identity(cash.Currency, accountCurrency);

                            Log.Trace($"BrokerageSetupHandler.LoadCashBalance(): Set {cash.Currency} as stablecoin for '{accountName}'");
                        }
                    }

                    Log.Trace($"BrokerageSetupHandler.LoadCashBalance(): Loaded cash to account '{accountName}'");
                }
            }
            catch (Exception err)
            {
                Log.Error(err);
                AddInitializationError("Error getting cash balance from brokerage: " + err.Message, err);
                return false;
            }
            return true;
        }

        /// <summary>
        /// Loads existing holdings and orders
        /// </summary>
        private bool LoadExistingHoldingsAndOrders(IBrokerage brokerage, IAlgorithm algorithm, SetupHandlerParameters parameters)
        {
            try
            {
                GetOpenOrders(algorithm, parameters.ResultHandler, parameters.TransactionHandler, brokerage);
            }
            catch (Exception err)
            {
                Log.Error(err);
                AddInitializationError("Error getting open orders from brokerage: " + err.Message, err);
                return false;
            }

            try
            {
                var utcNow = DateTime.UtcNow;

                // populate the algorithm with the account's current holdings
                var holdings = brokerage.GetAccountHoldings();

                // add options first to ensure raw data normalization mode is set on the equity underlyings
                foreach (var holding in holdings.OrderByDescending(x => x.Type))
                {
                    Log.Trace("BrokerageSetupHandler.LoadExistingHoldingsAndOrders(): Has existing holding: " + holding);

                    // verify existing holding security type
                    Security security;
                    if (!GetOrAddUnrequestedSecurity(algorithm, holding.Symbol, holding.Type, out security))
                    {
                        continue;
                    }

                    var exchangeTime = utcNow.ConvertFromUtc(security.Exchange.TimeZone);

                    security.Holdings.SetHoldings(holding.AveragePrice, holding.Quantity);

                    if (holding.MarketPrice == 0)
                    {
                        // try warming current market price
                        holding.MarketPrice = algorithm.GetLastKnownPrice(security)?.Price ?? 0;
                    }

                    if (holding.MarketPrice != 0)
                    {
                        security.SetMarketPrice(new TradeBar
                        {
                            Time = exchangeTime,
                            Open = holding.MarketPrice,
                            High = holding.MarketPrice,
                            Low = holding.MarketPrice,
                            Close = holding.MarketPrice,
                            Volume = 0,
                            Symbol = holding.Symbol,
                            DataType = MarketDataType.TradeBar
                        });
                    }
                }
            }
            catch (Exception err)
            {
                Log.Error(err);
                AddInitializationError("Error getting account holdings from brokerage: " + err.Message, err);
                return false;
            }

            return true;
        }

        /// <summary>
        /// Gets or adds unrequested security
        /// </summary>
        private bool GetOrAddUnrequestedSecurity(IAlgorithm algorithm, Symbol symbol, SecurityType securityType, out Security security)
        {
            return algorithm.GetOrAddUnrequestedSecurity(symbol, out security,
                onError: (supportedSecurityTypes) => AddInitializationError(
                    "Found unsupported security type in existing brokerage holdings: " + securityType + ". " +
                    "QuantConnect currently supports the following security types: " + string.Join(",", supportedSecurityTypes)));
        }

        /// <summary>
        /// Get the open orders from a brokerage
        /// </summary>
        private void GetOpenOrders(IAlgorithm algorithm, IResultHandler resultHandler, ITransactionHandler transactionHandler, IBrokerage brokerage)
        {
            // populate the algorithm with the account's outstanding orders
            var openOrders = brokerage.GetOpenOrders();

            // add options first to ensure raw data normalization mode is set on the equity underlyings
            foreach (var order in openOrders.OrderByDescending(x => x.SecurityType))
            {
                // verify existing holding security type
                Security security;
                if (!GetOrAddUnrequestedSecurity(algorithm, order.Symbol, order.SecurityType, out security))
                {
                    continue;
                }

                transactionHandler.AddOpenOrder(order, algorithm);
                order.PriceCurrency = security?.SymbolProperties.QuoteCurrency;

                Log.Trace($"BrokerageSetupHandler.GetOpenOrders(): Has open order: {order}");
                resultHandler.DebugMessage($"BrokerageSetupHandler.GetOpenOrders(): Open order detected. Creating order tickets for open order {order.Symbol.Value} with quantity {order.Quantity}. Beware that this order ticket may not accurately reflect the quantity of the order if the open order is partially filled.");
            }
        }

        /// <summary>
        /// Adds initialization error to the Errors list
        /// </summary>
        private void AddInitializationError(string message, Exception inner = null)
        {
            Errors.Add(new AlgorithmSetupException("During the algorithm initialization, the following exception has occurred: " + message, inner));
        }

        /// <summary>
        /// Creates a routed brokerage model that delegates to specific brokerage models based on security market
        /// </summary>
        /// <param name="marketToBrokerageModel">Dictionary mapping markets to their respective brokerage models</param>
        /// <returns>A RoutedBrokerageModel instance</returns>
        private IBrokerageModel CreateRoutedBrokerageModel(Dictionary<string, IBrokerageModel> marketToBrokerageModel)
        {
            if (marketToBrokerageModel == null || marketToBrokerageModel.Count == 0)
            {
                throw new ArgumentException("marketToBrokerageModel cannot be null or empty");
            }

            Log.Trace($"BrokerageSetupHandler.CreateRoutedBrokerageModel(): Creating routed model with {marketToBrokerageModel.Count} market mappings");
            foreach (var kvp in marketToBrokerageModel)
            {
                Log.Trace($"BrokerageSetupHandler.CreateRoutedBrokerageModel(): Market '{kvp.Key}' → {kvp.Value.GetType().Name}");
            }

            return new RoutedBrokerageModel(marketToBrokerageModel);
        }

        /// <summary>
        /// Preloads data queue handler using custom BrokerageFactory attribute
        /// </summary>
        private void PreloadDataQueueHandler(LiveNodePacket liveJob, IAlgorithm algorithm, IBrokerageFactory factory)
        {
            // preload the data queue handler using custom BrokerageFactory attribute
            var dataQueueHandlerType = Assembly.GetAssembly(typeof(Brokerage))
                .GetTypes()
                .FirstOrDefault(x =>
                    x.FullName != null &&
                    x.FullName.EndsWith(liveJob.DataQueueHandler) &&
                    x.HasAttribute(typeof(BrokerageFactoryAttribute)));

            if (dataQueueHandlerType != null)
            {
                var attribute = dataQueueHandlerType.GetCustomAttribute<BrokerageFactoryAttribute>();

                // only load the data queue handler if the factory is different from our brokerage factory
                if (attribute.Type != factory.GetType())
                {
                    var brokerageFactory = (BrokerageFactory)Activator.CreateInstance(attribute.Type);

                    // copy the brokerage data (usually credentials)
                    foreach (var kvp in brokerageFactory.BrokerageData)
                    {
                        if (!liveJob.BrokerageData.ContainsKey(kvp.Key))
                        {
                            liveJob.BrokerageData.Add(kvp.Key, kvp.Value);
                        }
                    }

                    // create the data queue handler and add it to composer
                    _dataQueueHandlerBrokerage = brokerageFactory.CreateBrokerage(liveJob, algorithm);

                    // open connection for subscriptions
                    _dataQueueHandlerBrokerage.Connect();
                }
            }
        }

        /// <summary>
        /// Validates which brokerage accounts in the MultiBrokerageManager support execution history.
        /// </summary>
        /// <param name="manager">The MultiBrokerageManager to validate</param>
        /// <returns>List of account names that do not support GetExecutionHistory</returns>
        private List<string> ValidateExecutionHistorySupport(MultiBrokerageManager manager)
        {
            var unsupportedAccounts = new List<string>();

            // Get all brokerages from the manager using reflection
            var brokeragesField = typeof(MultiBrokerageManager).GetField("_brokerages",
                System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance);

            if (brokeragesField != null)
            {
                var brokerages = brokeragesField.GetValue(manager) as Dictionary<string, IBrokerage>;
                if (brokerages != null)
                {
                    foreach (var kvp in brokerages)
                    {
                        var accountName = kvp.Key;
                        var brokerage = kvp.Value;

                        // Check if this brokerage has GetExecutionHistory method
                        var method = brokerage.GetType().GetMethod(
                            "GetExecutionHistory",
                            new[] { typeof(DateTime), typeof(DateTime) });

                        if (method == null)
                        {
                            unsupportedAccounts.Add($"{accountName} ({brokerage.Name})");
                            Log.Trace($"BrokerageSetupHandler.ValidateExecutionHistorySupport(): " +
                                     $"Account '{accountName}' brokerage '{brokerage.Name}' does not implement GetExecutionHistory");
                        }
                        else
                        {
                            Log.Trace($"BrokerageSetupHandler.ValidateExecutionHistorySupport(): " +
                                     $"Account '{accountName}' brokerage '{brokerage.Name}' supports GetExecutionHistory");
                        }
                    }
                }
            }

            return unsupportedAccounts;
        }

        /// <summary>
        /// Performs application-defined tasks associated with freeing, releasing, or resetting unmanaged resources.
        /// </summary>
        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
            _factory?.DisposeSafely();

            if (_dataQueueHandlerBrokerage != null)
            {
                if (_dataQueueHandlerBrokerage.IsConnected)
                {
                    _dataQueueHandlerBrokerage.Disconnect();
                }
                _dataQueueHandlerBrokerage.DisposeSafely();
            }
            else
            {
                var dataQueueHandler = Composer.Instance.GetPart<IDataQueueHandler>();
                if (dataQueueHandler != null)
                {
                    Log.Trace($"BrokerageSetupHandler.Dispose(): Found data queue handler to dispose: {dataQueueHandler.GetType()}");
                    dataQueueHandler.DisposeSafely();
                }
                else
                {
                    Log.Trace("BrokerageSetupHandler.Dispose(): did not find any data queue handler to dispose");
                }
            }
        }
    }
}
