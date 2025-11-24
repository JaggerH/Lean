using System;
using System.Collections.Generic;
using QuantConnect.Interfaces;
using QuantConnect.TradingPairs;

namespace QuantConnect.Lean.Engine.ExecutionHistory
{
    /// <summary>
    /// Provides execution history by aggregating from one or more brokerages.
    /// Adapts MultiBrokerageManager GetExecutionHistory capability to IExecutionHistoryProvider interface.
    /// </summary>
    /// <remarks>
    /// This adapter follows the same pattern as BrokerageHistoryProvider, which wraps IBrokerage
    /// to implement IHistoryProvider. It allows the algorithm layer to access execution history
    /// through a clean interface without direct dependency on MultiBrokerageManager or IBrokerage.
    /// </remarks>
    public class BrokerageExecutionHistoryProvider : IExecutionHistoryProvider
    {
        private readonly MultiBrokerageManager _multiBrokerageManager;

        /// <summary>
        /// Initializes a new instance of the <see cref="BrokerageExecutionHistoryProvider"/> class
        /// </summary>
        /// <param name="multiBrokerageManager">The multi-brokerage manager that aggregates execution history from multiple brokerages</param>
        /// <exception cref="ArgumentNullException">Thrown when multiBrokerageManager is null</exception>
        public BrokerageExecutionHistoryProvider(MultiBrokerageManager multiBrokerageManager)
        {
            _multiBrokerageManager = multiBrokerageManager ?? throw new ArgumentNullException(nameof(multiBrokerageManager));
        }

        /// <summary>
        /// Gets execution history for the specified time range by delegating to MultiBrokerageManager
        /// </summary>
        /// <param name="startTimeUtc">Start time in UTC</param>
        /// <param name="endTimeUtc">End time in UTC</param>
        /// <returns>List of execution records aggregated from all brokerages</returns>
        /// <remarks>
        /// This method delegates to MultiBrokerageManager.GetExecutionHistory(), which:
        /// 1. Iterates through all registered brokerages
        /// 2. Calls GetExecutionHistory on each brokerage (via reflection if not interface-based)
        /// 3. Aggregates and returns all execution records
        /// </remarks>
        public List<ExecutionRecord> GetExecutionHistory(DateTime startTimeUtc, DateTime endTimeUtc)
        {
            return _multiBrokerageManager.GetExecutionHistory(startTimeUtc, endTimeUtc);
        }
    }
}
