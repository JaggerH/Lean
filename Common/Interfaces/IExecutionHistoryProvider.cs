using System;
using System.Collections.Generic;
using QuantConnect.TradingPairs;

namespace QuantConnect.Interfaces
{
    /// <summary>
    /// Provides access to execution history from brokerages
    /// </summary>
    public interface IExecutionHistoryProvider
    {
        /// <summary>
        /// Gets execution history for the specified time range
        /// </summary>
        /// <param name="startTimeUtc">Start time (UTC)</param>
        /// <param name="endTimeUtc">End time (UTC)</param>
        /// <returns>List of execution records</returns>
        List<ExecutionRecord> GetExecutionHistory(DateTime startTimeUtc, DateTime endTimeUtc);
    }
}
