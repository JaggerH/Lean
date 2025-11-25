using QuantConnect.Data;
using QuantConnect.Interfaces;

namespace QuantConnect.Algorithm
{
    /// <summary>
    /// Arbitrage QCAlgorithm - Extended base class with arbitrage-specific features.
    /// Inherits all functionality from QCAlgorithm and implements AIAlgorithm interface.
    /// </summary>
    /// <remarks>
    /// This class extends QCAlgorithm with arbitrage-specific capabilities without modifying
    /// the core LEAN framework. Use this as the base class for arbitrage trading algorithms
    /// that require execution history reconciliation and advanced order management.
    ///
    /// By implementing AIAlgorithm interface, this class provides:
    /// - ExecutionHistoryProvider for accessing brokerage execution records
    /// - ExecutionHistory() methods for querying historical executions
    /// - TradingPairs manager for spread trading strategies
    /// - Framework integration for Alpha models, Portfolio Construction, and Execution
    /// - All standard QCAlgorithm functionality (inherited)
    ///
    /// The ExecutionHistoryProvider can be set by the Engine layer or manually injected
    /// for testing. If the provider is set, all ExecutionHistory() methods will work;
    /// otherwise they return empty results.
    /// </remarks>
    public partial class AQCAlgorithm : QCAlgorithm, AIAlgorithm
    {
        /// <summary>
        /// Gets or sets the execution history provider for the algorithm.
        /// Implementation of AIAlgorithm.ExecutionHistoryProvider.
        /// </summary>
        public IExecutionHistoryProvider ExecutionHistoryProvider { get; set; }

        /// <summary>
        /// Gets the trading pair collection that manages pairs of securities for spread trading and arbitrage strategies.
        /// Trading pairs automatically calculate spreads and market states based on their constituent securities.
        /// Implementation of AIAlgorithm.TradingPairs.
        /// </summary>
        public TradingPairs.TradingPairManager TradingPairs { get; private set; }

        /// <summary>
        /// Gets whether the algorithm supports execution history reconciliation.
        /// Implementation of AIAlgorithm.SupportsExecutionHistory.
        /// </summary>
        public bool SupportsExecutionHistory => ExecutionHistoryProvider != null;

        /// <summary>
        /// Initializes a new instance of the <see cref="AQCAlgorithm"/> class.
        /// </summary>
        public AQCAlgorithm()
        {
            // Initialize TradingPairs manager for arbitrage strategies
            TradingPairs = new TradingPairs.TradingPairManager(this);

            // Initialize Framework components (Alpha, Insights, etc.)
            InitializeFramework();
        }

        /// <summary>
        /// Called after the algorithm has been initialized and securities are added.
        /// Sets up reconciliation scheduling for live trading.
        /// </summary>
        public override void PostInitialize()
        {
            base.PostInitialize();

            // Only setup reconciliation in live mode
            if (LiveMode && TradingPairs != null)
            {
                // Restore TradingPairManager state from ObjectStore if available
                TradingPairs.RestoreState();
                Debug("AQCAlgorithm: Restored TradingPairs state from ObjectStore");

                // Initialize baseline for trading pairs reconciliation
                TradingPairs.InitializeBaseline(Portfolio);
                Debug("AQCAlgorithm: Initialized TradingPairs baseline for reconciliation");

                // Setup periodic reconciliation if ExecutionHistoryProvider is available
                if (ExecutionHistoryProvider != null)
                {
                    // Schedule reconciliation every 5 minutes
                    Schedule.On(
                        DateRules.EveryDay(),
                        TimeRules.Every(System.TimeSpan.FromMinutes(5)),
                        () =>
                        {
                            if (!IsWarmingUp)
                            {
                                TradingPairs.CompareBaseline(Portfolio);
                            }
                        }
                    );
                    Debug("AQCAlgorithm: Scheduled periodic reconciliation every 5 minutes");
                }
                else
                {
                    Debug("AQCAlgorithm: Warning - ExecutionHistoryProvider not set. Reconciliation features disabled.");
                }
            }
        }

        /// <summary>
        /// Called when the brokerage connection is restored after being lost.
        /// Triggers immediate reconciliation to detect any discrepancies during disconnection.
        /// </summary>
        public override void OnBrokerageReconnect()
        {
            base.OnBrokerageReconnect();

            if (TradingPairs != null && ExecutionHistoryProvider != null && !IsWarmingUp)
            {
                Debug("AQCAlgorithm: Brokerage reconnected - triggering reconciliation");
                TradingPairs.CompareBaseline(Portfolio);
            }
        }

        /// <summary>
        /// Event handler for data updates. Calls framework models and user custom logic.
        /// </summary>
        /// <param name="data">The data slice containing all market data</param>
        public override void OnData(Slice data)
        {
            // Call framework to update alpha model and process insights
            OnFrameworkData(data);

            // User custom logic can be added here in derived classes
        }

        /// <summary>
        /// Creates and adds a new trading pair for spread trading and arbitrage strategies
        /// </summary>
        /// <param name="leg1">The first leg symbol</param>
        /// <param name="leg2">The second leg symbol</param>
        /// <param name="pairType">The type of trading pair (e.g., "spread", "tokenized", "futures")</param>
        /// <returns>The new <see cref="TradingPairs.TradingPair"/> object</returns>
        public TradingPairs.TradingPair AddTradingPair(Symbol leg1, Symbol leg2, string pairType = "spread")
        {
            if (!Securities.ContainsKey(leg1))
            {
                throw new System.ArgumentException($"Security {leg1} must be added to the algorithm before creating a trading pair");
            }
            if (!Securities.ContainsKey(leg2))
            {
                throw new System.ArgumentException($"Security {leg2} must be added to the algorithm before creating a trading pair");
            }

            return TradingPairs.AddPair(leg1, leg2, pairType);
        }
    }
}
