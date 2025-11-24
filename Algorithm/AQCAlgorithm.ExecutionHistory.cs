using System;
using System.Collections.Generic;
using System.Linq;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm
{
    /// <summary>
    /// AQCAlgorithm partial class - Execution history functionality.
    /// Provides methods to retrieve historical execution records from brokerages.
    /// </summary>
    /// <remarks>
    /// This partial class contains all execution history retrieval methods, following
    /// the same pattern as QCAlgorithm.History.cs for market data history.
    /// Methods are designed to be similar to the History() API for consistency.
    /// </remarks>
    public partial class AQCAlgorithm
    {
        /// <summary>
        /// Get execution history for the specified time range
        /// </summary>
        /// <param name="startTimeUtc">Start time in UTC</param>
        /// <param name="endTimeUtc">End time in UTC</param>
        /// <returns>List of execution records, or empty list if provider not available</returns>
        /// <example>
        /// <code>
        /// var executions = ExecutionHistory(Time.AddHours(-1), Time);
        /// foreach (var exec in executions)
        /// {
        ///     Debug($"Execution: {exec.Symbol} {exec.Quantity} @ {exec.Price}");
        /// }
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(DateTime startTimeUtc, DateTime endTimeUtc)
        {
            if (ExecutionHistoryProvider == null)
            {
                Debug("ExecutionHistory: Provider not available. Set ExecutionHistoryProvider property.");
                return new List<ExecutionRecord>();
            }

            try
            {
                var records = ExecutionHistoryProvider.GetExecutionHistory(startTimeUtc, endTimeUtc);

                if (records == null)
                {
                    Debug("ExecutionHistory: Provider returned null");
                    return new List<ExecutionRecord>();
                }

                Debug($"ExecutionHistory: Retrieved {records.Count} records from {startTimeUtc:yyyy-MM-dd HH:mm:ss} to {endTimeUtc:yyyy-MM-dd HH:mm:ss}");
                return records;
            }
            catch (Exception ex)
            {
                Error($"ExecutionHistory: Error retrieving records: {ex.Message}");
                return new List<ExecutionRecord>();
            }
        }

        /// <summary>
        /// Get execution history for the last specified time period
        /// </summary>
        /// <param name="lookback">How far back to look</param>
        /// <returns>List of execution records</returns>
        /// <example>
        /// <code>
        /// // Get executions from the last hour
        /// var recentExecutions = ExecutionHistory(TimeSpan.FromHours(1));
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(TimeSpan lookback)
        {
            var endTime = Time;
            var startTime = endTime - lookback;
            return ExecutionHistory(startTime, endTime);
        }

        /// <summary>
        /// Get execution history for the last N executions
        /// </summary>
        /// <param name="count">Number of recent executions to retrieve</param>
        /// <returns>List of execution records, ordered by time (oldest first)</returns>
        /// <remarks>
        /// This method retrieves executions from the last 30 days and returns the most recent N records.
        /// If you need a longer time window, use ExecutionHistory(TimeSpan) or ExecutionHistory(DateTime, DateTime).
        /// </remarks>
        /// <example>
        /// <code>
        /// // Get the last 10 executions
        /// var last10 = ExecutionHistory(10);
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(int count)
        {
            if (count <= 0)
            {
                return new List<ExecutionRecord>();
            }

            // Get a reasonable time window (e.g., last 30 days)
            var records = ExecutionHistory(TimeSpan.FromDays(30));

            // Return the most recent N records, ordered by time (oldest first)
            return records.OrderByDescending(r => r.TimeUtc)
                         .Take(count)
                         .OrderBy(r => r.TimeUtc)
                         .ToList();
        }

        /// <summary>
        /// Get execution history for a specific symbol within a time period
        /// </summary>
        /// <param name="symbol">Symbol to filter by</param>
        /// <param name="lookback">How far back to look</param>
        /// <returns>List of execution records for the symbol</returns>
        /// <example>
        /// <code>
        /// var btcExecutions = ExecutionHistory(Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Binance), TimeSpan.FromHours(24));
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(Symbol symbol, TimeSpan lookback)
        {
            var allRecords = ExecutionHistory(lookback);
            return allRecords.Where(r => r.Symbol == symbol).ToList();
        }

        /// <summary>
        /// Get execution history for a specific symbol and time range
        /// </summary>
        /// <param name="symbol">Symbol to filter by</param>
        /// <param name="startTimeUtc">Start time in UTC</param>
        /// <param name="endTimeUtc">End time in UTC</param>
        /// <returns>List of execution records for the symbol</returns>
        /// <example>
        /// <code>
        /// var symbol = Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Binance);
        /// var executions = ExecutionHistory(symbol, Time.AddDays(-7), Time);
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(Symbol symbol, DateTime startTimeUtc, DateTime endTimeUtc)
        {
            var allRecords = ExecutionHistory(startTimeUtc, endTimeUtc);
            return allRecords.Where(r => r.Symbol == symbol).ToList();
        }

        /// <summary>
        /// Get execution history for multiple symbols within a time period
        /// </summary>
        /// <param name="symbols">Symbols to filter by</param>
        /// <param name="lookback">How far back to look</param>
        /// <returns>List of execution records for the specified symbols</returns>
        /// <example>
        /// <code>
        /// var symbols = new[] {
        ///     Symbol.Create("BTCUSD", SecurityType.Crypto, Market.Binance),
        ///     Symbol.Create("ETHUSD", SecurityType.Crypto, Market.Binance)
        /// };
        /// var executions = ExecutionHistory(symbols, TimeSpan.FromHours(24));
        /// </code>
        /// </example>
        public List<ExecutionRecord> ExecutionHistory(IEnumerable<Symbol> symbols, TimeSpan lookback)
        {
            var symbolSet = new HashSet<Symbol>(symbols);
            var allRecords = ExecutionHistory(lookback);
            return allRecords.Where(r => symbolSet.Contains(r.Symbol)).ToList();
        }

        /// <summary>
        /// Get execution history for multiple symbols and time range
        /// </summary>
        /// <param name="symbols">Symbols to filter by</param>
        /// <param name="startTimeUtc">Start time in UTC</param>
        /// <param name="endTimeUtc">End time in UTC</param>
        /// <returns>List of execution records for the specified symbols</returns>
        public List<ExecutionRecord> ExecutionHistory(IEnumerable<Symbol> symbols, DateTime startTimeUtc, DateTime endTimeUtc)
        {
            var symbolSet = new HashSet<Symbol>(symbols);
            var allRecords = ExecutionHistory(startTimeUtc, endTimeUtc);
            return allRecords.Where(r => symbolSet.Contains(r.Symbol)).ToList();
        }
    }
}
