using QuantConnect.Interfaces;

namespace QuantConnect.Interfaces
{
    /// <summary>
    /// Arbitrage Algorithm Interface - Extends IAlgorithm with arbitrage-specific features.
    /// This interface provides execution history access and trading pair management for arbitrage strategies.
    /// </summary>
    /// <remarks>
    /// AIAlgorithm extends the standard IAlgorithm interface without modifying LEAN core.
    /// It adds arbitrage-specific capabilities like execution history reconciliation and
    /// trading pair management, which are essential for spread trading and arbitrage strategies.
    ///
    /// Classes implementing this interface (like AQCAlgorithm) inherit all IAlgorithm
    /// functionality while gaining access to additional arbitrage features.
    /// </remarks>
    public interface AIAlgorithm : IAlgorithm
    {
        /// <summary>
        /// Gets or sets the execution history provider for the algorithm.
        /// This provider allows retrieval of historical execution records from brokerages
        /// for reconciliation, monitoring, and strategy evaluation.
        /// </summary>
        /// <remarks>
        /// Set by the Engine layer or manually injected for testing.
        /// If null, execution history methods will return empty results.
        /// </remarks>
        IExecutionHistoryProvider ExecutionHistoryProvider { get; set; }

        /// <summary>
        /// Gets the trading pair collection that manages pairs of securities for spread trading and arbitrage strategies.
        /// Trading pairs automatically calculate spreads and market states based on their constituent securities.
        /// </summary>
        TradingPairs.TradingPairManager TradingPairs { get; }

        /// <summary>
        /// Gets whether the algorithm supports execution history reconciliation.
        /// Returns true if ExecutionHistoryProvider is set and available.
        /// </summary>
        /// <remarks>
        /// Use this property to check if reconciliation features are available before using them.
        /// If false, the brokerage does not support execution history queries or the provider was not injected.
        /// </remarks>
        bool SupportsExecutionHistory { get; }
    }
}
