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
 *
*/

using System;
using System.Linq;
using QuantConnect.Util;
using QuantConnect.Logging;
using QuantConnect.Packets;
using QuantConnect.Interfaces;
using QuantConnect.Configuration;
using System.Collections.Generic;
using QuantConnect.AlgorithmFactory;
using QuantConnect.Lean.Engine.DataFeeds;
using QuantConnect.Brokerages.Backtesting;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Data.Market;
using Newtonsoft.Json;
using QuantConnect.Algorithm;

namespace QuantConnect.Lean.Engine.Setup
{
    /// <summary>
    /// Backtesting setup handler processes the algorithm initialize method and sets up the internal state of the algorithm class.
    /// </summary>
    public class BacktestingSetupHandler : ISetupHandler
    {
        /// <summary>
        /// Get the maximum time that the initialization of an algorithm can take
        /// </summary>
        protected TimeSpan InitializationTimeOut { get; set; } = TimeSpan.FromMinutes(5);

        /// <summary>
        /// Get the maximum time that the creation of an algorithm can take
        /// </summary>
        protected TimeSpan AlgorithmCreationTimeout { get; set; } = BaseSetupHandler.AlgorithmCreationTimeout;

        /// <summary>
        /// The worker thread instance the setup handler should use
        /// </summary>
        public WorkerThread WorkerThread { get; set; }

        /// <summary>
        /// Internal errors list from running the setup procedures.
        /// </summary>
        public List<Exception> Errors { get; set; }

        /// <summary>
        /// Maximum runtime of the algorithm in seconds.
        /// </summary>
        /// <remarks>Maximum runtime is a formula based on the number and resolution of symbols requested, and the days backtesting</remarks>
        public TimeSpan MaximumRuntime { get; protected set; }

        /// <summary>
        /// Starting capital according to the users initialize routine.
        /// </summary>
        /// <remarks>Set from the user code.</remarks>
        /// <seealso cref="QCAlgorithm.SetCash(decimal)"/>
        public decimal StartingPortfolioValue { get; protected set; }

        /// <summary>
        /// Start date for analysis loops to search for data.
        /// </summary>
        /// <seealso cref="QCAlgorithm.SetStartDate(DateTime)"/>
        public DateTime StartingDate { get; protected set; }

        /// <summary>
        /// Maximum number of orders for this backtest.
        /// </summary>
        /// <remarks>To stop algorithm flooding the backtesting system with hundreds of megabytes of order data we limit it to 100 per day</remarks>
        public int MaxOrders { get; protected set; }

        /// <summary>
        /// Initialize the backtest setup handler.
        /// </summary>
        public BacktestingSetupHandler()
        {
            MaximumRuntime = TimeSpan.FromSeconds(300);
            Errors = new List<Exception>();
            StartingDate = new DateTime(1998, 01, 01);
        }

        /// <summary>
        /// Create a new instance of an algorithm from a physical dll path.
        /// </summary>
        /// <param name="assemblyPath">The path to the assembly's location</param>
        /// <param name="algorithmNodePacket">Details of the task required</param>
        /// <returns>A new instance of IAlgorithm, or throws an exception if there was an error</returns>
        public virtual IAlgorithm CreateAlgorithmInstance(AlgorithmNodePacket algorithmNodePacket, string assemblyPath)
        {
            string error;
            IAlgorithm algorithm;

            var debugNode = algorithmNodePacket as BacktestNodePacket;
            var debugging = debugNode != null && debugNode.Debugging || Config.GetBool("debugging", false);

            if (debugging && !BaseSetupHandler.InitializeDebugging(algorithmNodePacket, WorkerThread))
            {
                throw new AlgorithmSetupException("Failed to initialize debugging");
            }

            // Limit load times to 90 seconds and force the assembly to have exactly one derived type
            var loader = new Loader(debugging, algorithmNodePacket.Language, AlgorithmCreationTimeout, names => names.SingleOrAlgorithmTypeName(Config.Get("algorithm-type-name", algorithmNodePacket.AlgorithmId)), WorkerThread);
            var complete = loader.TryCreateAlgorithmInstanceWithIsolator(assemblyPath, algorithmNodePacket.RamAllocation, out algorithm, out error);
            if (!complete) throw new AlgorithmSetupException($"During the algorithm initialization, the following exception has occurred: {error}");

            return algorithm;
        }

        /// <summary>
        /// Creates a new <see cref="BacktestingBrokerage"/> instance
        /// </summary>
        /// <param name="algorithmNodePacket">Job packet</param>
        /// <param name="uninitializedAlgorithm">The algorithm instance before Initialize has been called</param>
        /// <param name="factory">The brokerage factory</param>
        /// <returns>The brokerage instance, or throws if error creating instance</returns>
        public virtual IBrokerage CreateBrokerage(AlgorithmNodePacket algorithmNodePacket, IAlgorithm uninitializedAlgorithm, out IBrokerageFactory factory)
        {
            // Check for multi-account configuration
            var (accountConfigs, router) = ParseMultiAccountConfig();

            if (accountConfigs != null && router != null)
            {
                Log.Trace($"BacktestingSetupHandler.CreateBrokerage(): Multi-account mode enabled with {accountConfigs.Count} accounts");

                // Get the underlying QCAlgorithm instance
                // For C# algorithms: cast directly
                // For Python algorithms: unwrap via AlgorithmPythonWrapper.BaseAlgorithm
                QCAlgorithm algorithm = uninitializedAlgorithm as QCAlgorithm;

                // If not a direct QCAlgorithm (e.g., Python wrapper), try to get BaseAlgorithm
                if (algorithm == null)
                {
                    var wrapperType = uninitializedAlgorithm.GetType();
                    var baseAlgorithmProperty = wrapperType.GetProperty("BaseAlgorithm");
                    if (baseAlgorithmProperty != null)
                    {
                        algorithm = baseAlgorithmProperty.GetValue(uninitializedAlgorithm) as QCAlgorithm;
                        Log.Trace("BacktestingSetupHandler.CreateBrokerage(): Unwrapped Python algorithm to access BaseAlgorithm");
                    }
                }

                if (algorithm != null)
                {
                    // Replace Algorithm's Portfolio with MultiSecurityPortfolioManager
                    // This MUST happen before algorithm.Initialize() is called
                    algorithm.Portfolio = new MultiSecurityPortfolioManager(
                        accountConfigs,
                        router,
                        algorithm.Securities,
                        algorithm.Transactions,
                        algorithm.Settings,
                        algorithm.DefaultOrderProperties,
                        algorithm.TimeKeeper
                    );

                    Log.Trace("BacktestingSetupHandler.CreateBrokerage(): Portfolio replaced with MultiSecurityPortfolioManager");
                }
                else
                {
                    Log.Error("BacktestingSetupHandler.CreateBrokerage(): Could not access QCAlgorithm instance, cannot replace Portfolio");
                }
            }

            // Create standard backtesting brokerage
            factory = new BacktestingBrokerageFactory();
            return new BacktestingBrokerage(uninitializedAlgorithm);
        }

        /// <summary>
        /// Setup the algorithm cash, dates and data subscriptions as desired.
        /// </summary>
        /// <param name="parameters">The parameters object to use</param>
        /// <returns>Boolean true on successfully initializing the algorithm</returns>
        public virtual bool Setup(SetupHandlerParameters parameters)
        {
            var algorithm = parameters.Algorithm;
            var job = parameters.AlgorithmNodePacket as BacktestNodePacket;
            if (job == null)
            {
                throw new ArgumentException("Expected BacktestNodePacket but received " + parameters.AlgorithmNodePacket.GetType().Name);
            }

            BaseSetupHandler.Setup(parameters);

            if (algorithm == null)
            {
                Errors.Add(new AlgorithmSetupException("Could not create instance of algorithm"));
                return false;
            }

            algorithm.Name = job.Name;

            //Make sure the algorithm start date ok.
            if (job.PeriodStart == default(DateTime))
            {
                Errors.Add(new AlgorithmSetupException("Algorithm start date was never set"));
                return false;
            }

            var controls = job.Controls;
            var isolator = new Isolator();
            var initializeComplete = isolator.ExecuteWithTimeLimit(InitializationTimeOut, () =>
            {
                try
                {
                    parameters.ResultHandler.SendStatusUpdate(AlgorithmStatus.Initializing, "Initializing algorithm...");
                    //Set our parameters
                    algorithm.SetParameters(job.Parameters);
                    algorithm.SetAvailableDataTypes(BaseSetupHandler.GetConfiguredDataFeeds());

                    //Algorithm is backtesting, not live:
                    algorithm.SetAlgorithmMode(job.AlgorithmMode);

                    //Set the source impl for the event scheduling
                    algorithm.Schedule.SetEventSchedule(parameters.RealTimeHandler);

                    // set the option chain provider
                    var optionChainProvider = new BacktestingOptionChainProvider();
                    var initParameters = new ChainProviderInitializeParameters(parameters.MapFileProvider, algorithm.HistoryProvider);
                    optionChainProvider.Initialize(initParameters);
                    algorithm.SetOptionChainProvider(new CachingOptionChainProvider(optionChainProvider));

                    // set the future chain provider
                    var futureChainProvider = new BacktestingFutureChainProvider();
                    futureChainProvider.Initialize(initParameters);
                    algorithm.SetFutureChainProvider(new CachingFutureChainProvider(futureChainProvider));

                    // before we call initialize
                    BaseSetupHandler.LoadBacktestJobAccountCurrency(algorithm, job);

                    //Initialise the algorithm, get the required data:
                    algorithm.Initialize();

                    // set start and end date if present in the job
                    if (job.PeriodStart.HasValue)
                    {
                        algorithm.SetStartDate(job.PeriodStart.Value);
                    }
                    if (job.PeriodFinish.HasValue)
                    {
                        algorithm.SetEndDate(job.PeriodFinish.Value);
                    }

                    if(job.OutOfSampleMaxEndDate.HasValue)
                    {
                        if(algorithm.EndDate > job.OutOfSampleMaxEndDate.Value)
                        {
                            Log.Trace($"BacktestingSetupHandler.Setup(): setting end date to {job.OutOfSampleMaxEndDate.Value:yyyyMMdd}");
                            algorithm.SetEndDate(job.OutOfSampleMaxEndDate.Value);

                            if (algorithm.StartDate > algorithm.EndDate)
                            {
                                algorithm.SetStartDate(algorithm.EndDate);
                            }
                        }
                    }

                    // after we call initialize
                    BaseSetupHandler.LoadBacktestJobCashAmount(algorithm, job);

                    // Load multi-account state from file if available (for state recovery testing)
                    LoadMultiAccountState(algorithm, parameters.Brokerage);

                    // after algorithm was initialized, should set trading days per year for our great portfolio statistics
                    BaseSetupHandler.SetBrokerageTradingDayPerYear(algorithm);

                    // finalize initialization
                    algorithm.PostInitialize();
                }
                catch (Exception err)
                {
                    Errors.Add(new AlgorithmSetupException("During the algorithm initialization, the following exception has occurred: ", err));
                }
            }, controls.RamAllocation,
                sleepIntervalMillis: 100,  // entire system is waiting on this, so be as fast as possible
                workerThread: WorkerThread);

            if (Errors.Count > 0)
            {
                // if we already got an error just exit right away
                return false;
            }

            //Before continuing, detect if this is ready:
            if (!initializeComplete) return false;

            MaximumRuntime = TimeSpan.FromMinutes(job.Controls.MaximumRuntimeMinutes);

            BaseSetupHandler.SetupCurrencyConversions(algorithm, parameters.UniverseSelection);
            StartingPortfolioValue = algorithm.Portfolio.Cash;

            // Get and set maximum orders for this job
            MaxOrders = job.Controls.BacktestingMaxOrders;
            algorithm.SetMaximumOrders(MaxOrders);

            //Starting date of the algorithm:
            StartingDate = algorithm.StartDate;

            //Put into log for debugging:
            Log.Trace("SetUp Backtesting: User: " + job.UserId + " ProjectId: " + job.ProjectId + " AlgoId: " + job.AlgorithmId);
            Log.Trace($"Dates: Start: {algorithm.StartDate.ToStringInvariant("d")} " +
                      $"End: {algorithm.EndDate.ToStringInvariant("d")} " +
                      $"Cash: {StartingPortfolioValue.ToStringInvariant("C")} " +
                      $"MaximumRuntime: {MaximumRuntime} " +
                      $"MaxOrders: {MaxOrders}");

            return initializeComplete;
        }

        #region Multi-Account Configuration

        /// <summary>
        /// Configuration class for multi-account setup
        /// </summary>
        private class MultiAccountConfig
        {
            [JsonProperty("accounts")]
            public Dictionary<string, decimal> Accounts { get; set; }

            [JsonProperty("router")]
            public RouterConfig Router { get; set; }
        }

        private class RouterConfig
        {
            [JsonProperty("type")]
            public string Type { get; set; }

            [JsonProperty("mappings")]
            public Dictionary<string, string> Mappings { get; set; }

            [JsonProperty("default")]
            public string Default { get; set; }
        }

        /// <summary>
        /// Parses multi-account configuration from JSON
        /// </summary>
        /// <returns>Tuple of (account configs, router) or (null, null) if not configured</returns>
        private (Dictionary<string, decimal> accounts, IOrderRouter router) ParseMultiAccountConfig()
        {
            var configString = Configuration.Config.Get("multi-account-config");

            if (string.IsNullOrEmpty(configString))
            {
                return (null, null);
            }

            try
            {
                Log.Trace("BacktestingSetupHandler: Parsing multi-account configuration");

                // Parse JSON configuration
                var config = JsonConvert.DeserializeObject<MultiAccountConfig>(configString);

                if (config?.Accounts == null || config.Accounts.Count == 0)
                {
                    throw new ArgumentException("No accounts defined in multi-account-config");
                }

                // Log account configurations
                foreach (var account in config.Accounts)
                {
                    Log.Trace($"BacktestingSetupHandler: Account '{account.Key}' with initial cash ${account.Value:N2}");
                }

                // Create router based on config
                var router = CreateRouterFromConfig(config);

                return (config.Accounts, router);
            }
            catch (JsonException ex)
            {
                throw new ArgumentException($"Invalid JSON format in multi-account-config: {ex.Message}", ex);
            }
            catch (Exception ex)
            {
                throw new ArgumentException($"Failed to parse multi-account-config: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Creates order router from configuration
        /// </summary>
        private IOrderRouter CreateRouterFromConfig(MultiAccountConfig config)
        {
            var defaultAccount = config.Router?.Default ?? config.Accounts.Keys.First();

            // If no router config, use simple router to default account
            if (config.Router == null || config.Router.Mappings == null || config.Router.Mappings.Count == 0)
            {
                Log.Trace($"BacktestingSetupHandler: No router mappings, using SimpleOrderRouter to '{defaultAccount}'");
                return new SimpleOrderRouter(defaultAccount);
            }

            var routerType = config.Router.Type?.ToLowerInvariant() ?? "market";

            switch (routerType)
            {
                case "market":
                    Log.Trace($"BacktestingSetupHandler: Creating MarketBasedRouter with {config.Router.Mappings.Count} market mappings");
                    foreach (var mapping in config.Router.Mappings)
                    {
                        Log.Trace($"  Market '{mapping.Key}' → Account '{mapping.Value}'");
                    }
                    return new MarketBasedRouter(config.Router.Mappings, defaultAccount);

                case "securitytype":
                    Log.Trace($"BacktestingSetupHandler: Creating SecurityTypeRouter");
                    var typeMappings = ParseSecurityTypeMappings(config.Router.Mappings);
                    return new SecurityTypeRouter(typeMappings, defaultAccount);

                case "symbol":
                    Log.Error("BacktestingSetupHandler: Symbol-based routing not fully implemented, falling back to MarketBasedRouter");
                    return new MarketBasedRouter(config.Router.Mappings, defaultAccount);

                default:
                    Log.Error($"BacktestingSetupHandler: Unknown router type '{routerType}', using MarketBasedRouter");
                    return new MarketBasedRouter(config.Router.Mappings, defaultAccount);
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
                    Log.Trace($"  SecurityType '{securityType}' → Account '{kvp.Value}'");
                }
                else
                {
                    Log.Error($"BacktestingSetupHandler: Invalid SecurityType '{kvp.Key}' in router mappings");
                }
            }

            return result;
        }

        #endregion

        /// <summary>
        /// Loads multi-account state from file if configured
        /// This enables state recovery in backtest mode for testing purposes
        /// </summary>
        private void LoadMultiAccountState(IAlgorithm algorithm, IBrokerage brokerage)
        {
            try
            {
                // Check if this is multi-account mode
                if (algorithm.Portfolio is MultiSecurityPortfolioManager multiPortfolio)
                {
                    // Check if brokerage supports multi-account state recovery
                    if (brokerage is BacktestingBrokerage backtestingBrokerage)
                    {

                        foreach (var accountKvp in multiPortfolio.SubAccounts)
                        {
                            var accountName = accountKvp.Key;
                            var subAccount = accountKvp.Value;

                            // Try to restore cash balance for this account
                            var accountCashBalance = backtestingBrokerage.GetCashBalanceForAccount(accountName);

                            if (accountCashBalance != null && accountCashBalance.Count > 0)
                            {
                                // Restore cash balance
                                foreach (var cash in accountCashBalance)
                                {

                                    // Add currency if it doesn't exist with initial conversion rate
                                    // LEAN will update the conversion rate from market data as the algorithm runs
                                    if (!subAccount.CashBook.ContainsKey(cash.Currency))
                                    {
                                        // Use 1.0 as initial conversion rate for crypto, LEAN will update it from market data
                                        subAccount.SetCash(cash.Currency, 0, 1.0m);
                                    }

                                    // Set the amount directly
                                    subAccount.CashBook[cash.Currency].SetAmount(cash.Amount);
                                }
                            }

                            // Try to restore holdings for this account
                            var accountHoldings = backtestingBrokerage.GetAccountHoldingsForAccount(accountName);

                            if (accountHoldings != null && accountHoldings.Count > 0)
                            {

                                var utcNow = DateTime.UtcNow;
                                foreach (var holding in accountHoldings)
                                {
                                    // Find the matching security by ticker and type (don't use Symbol.ID directly as it changes between runs)
                                    Security security = null;
                                    foreach (var kvp in algorithm.Securities)
                                    {
                                        if (kvp.Key.Value == holding.Symbol.Value &&
                                            kvp.Key.SecurityType == holding.Symbol.SecurityType)
                                        {
                                            security = kvp.Value;
                                            break;
                                        }
                                    }

                                    if (security == null)
                                    {
                                        Log.Error($"BacktestingSetupHandler.LoadMultiAccountState(): Could not find security for {holding.Symbol.Value} ({holding.Symbol.SecurityType}) in account '{accountName}'");
                                        continue;
                                    }

                                    security.Holdings.SetHoldings(holding.AveragePrice, holding.Quantity);

                                    // Set market price
                                    security.SetMarketPrice(new TradeBar
                                    {
                                        Time = utcNow,
                                        Symbol = security.Symbol,
                                        Open = holding.MarketPrice,
                                        High = holding.MarketPrice,
                                        Low = holding.MarketPrice,
                                        Close = holding.MarketPrice
                                    });

                                }
                            }

                            // Note: Open orders restoration is handled by the Python algorithm
                            // Orders are saved to the state file but restored via Python code
                            // This allows the algorithm to use its normal order submission methods
                            var accountOrders = backtestingBrokerage.GetOpenOrdersForAccount(accountName);
                            if (accountOrders != null && accountOrders.Count > 0)
                            {
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Log.Error($"BacktestingSetupHandler.LoadMultiAccountState(): Failed to load multi-account state: {ex.Message}");
            }
        }

        /// <summary>
        /// Performs application-defined tasks associated with freeing, releasing, or resetting unmanaged resources.
        /// </summary>
        /// <filterpriority>2</filterpriority>
        public void Dispose()
        {
        }
    } // End Result Handler Thread:

} // End Namespace
