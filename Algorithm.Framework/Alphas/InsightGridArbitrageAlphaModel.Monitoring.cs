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
using QuantConnect.Data;
using QuantConnect.Interfaces;
using QuantConnect.Logging;

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Monitoring and performance tracking functionality for InsightGridArbitrageAlphaModel.
    /// This partial class handles Slice update rate statistics to help evaluate
    /// whether optimization (filtering by updated symbols) would be beneficial.
    /// </summary>
    public partial class InsightGridArbitrageAlphaModel
    {
        /// <summary>
        /// Time of last statistics report
        /// </summary>
        private DateTime _lastStatsReport;

        /// <summary>
        /// Total number of Slice updates since last report
        /// </summary>
        private int _totalSliceUpdates;

        /// <summary>
        /// Total number of symbols updated across all Slices since last report
        /// </summary>
        private long _totalSymbolsUpdated;

        /// <summary>
        /// Total number of symbols available (sum of Securities.Count at each update)
        /// </summary>
        private long _totalSymbolsAvailable;

        /// <summary>
        /// Interval between statistics reports (default: 5 minutes)
        /// </summary>
        private readonly TimeSpan _statsReportInterval = TimeSpan.FromMinutes(5);

        /// <summary>
        /// Tracks Slice update statistics and logs a report every 5 minutes.
        /// This helps determine if optimizing Update() to only process changed symbols would be beneficial.
        /// Only tracks statistics in Live mode.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="data">The current Slice data</param>
        private void TrackSliceUpdateStats(AIAlgorithm algorithm, Slice data)
        {
            // Only track statistics in Live mode
            if (!algorithm.LiveMode)
            {
                return;
            }

            // Initialize on first call
            if (_lastStatsReport == DateTime.MinValue)
            {
                _lastStatsReport = algorithm.UtcTime;
            }

            // Accumulate statistics
            _totalSliceUpdates++;
            _totalSymbolsUpdated += data.Keys.Count;
            _totalSymbolsAvailable += algorithm.Securities.Count;

            // Check if it's time to report
            if (algorithm.UtcTime - _lastStatsReport >= _statsReportInterval)
            {
                ReportSliceUpdateStats();
                ResetSliceUpdateStats(algorithm.UtcTime);
            }
        }

        /// <summary>
        /// Logs a comprehensive report of Slice update statistics.
        /// Includes recommendations on whether optimization would be beneficial.
        /// </summary>
        private void ReportSliceUpdateStats()
        {
            if (_totalSliceUpdates == 0)
            {
                return;
            }

            // Calculate averages
            double avgSymbolsUpdated = (double)_totalSymbolsUpdated / _totalSliceUpdates;
            double avgSymbolsAvailable = (double)_totalSymbolsAvailable / _totalSliceUpdates;
            double avgUpdateRate = avgSymbolsAvailable > 0
                ? (avgSymbolsUpdated / avgSymbolsAvailable * 100)
                : 0;

            // Generate recommendation
            string recommendation;
            if (avgUpdateRate < 10)
            {
                recommendation = "STRONG BENEFIT - Optimization highly recommended (10x+ speedup expected)";
            }
            else if (avgUpdateRate < 20)
            {
                recommendation = "MODERATE BENEFIT - Optimization recommended (5x+ speedup expected)";
            }
            else if (avgUpdateRate < 50)
            {
                recommendation = "SMALL BENEFIT - Optimization may help (2-5x speedup expected)";
            }
            else
            {
                recommendation = "NO BENEFIT - Current approach is optimal";
            }

            // Log the report
            Log.Trace($"═══════════════════════════════════════════════════════════════");
            Log.Trace($"InsightGridArbitrageAlphaModel - Slice Update Statistics Report");
            Log.Trace($"═══════════════════════════════════════════════════════════════");
            Log.Trace($"Time Period: {_statsReportInterval.TotalMinutes:F0} minutes");
            Log.Trace($"Total Slice Updates: {_totalSliceUpdates:N0}");
            Log.Trace($"Avg Symbols per Slice: {avgSymbolsUpdated:F1}");
            Log.Trace($"Avg Total Symbols: {avgSymbolsAvailable:F1}");
            Log.Trace($"Avg Update Rate: {avgUpdateRate:F2}%");
            Log.Trace($"───────────────────────────────────────────────────────────────");
            Log.Trace($"Optimization Recommendation: {recommendation}");
            Log.Trace($"═══════════════════════════════════════════════════════════════");
        }

        /// <summary>
        /// Resets statistics counters for the next reporting period.
        /// </summary>
        /// <param name="currentTime">Current UTC time</param>
        private void ResetSliceUpdateStats(DateTime currentTime)
        {
            _lastStatsReport = currentTime;
            _totalSliceUpdates = 0;
            _totalSymbolsUpdated = 0;
            _totalSymbolsAvailable = 0;
        }
    }
}
