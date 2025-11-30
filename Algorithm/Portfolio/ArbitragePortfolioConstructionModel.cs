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
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Portfolio construction model for arbitrage trading using Tag-based pairing.
    /// Consumes single Leg1 insights from ArbitrageAlphaModel and generates
    /// paired portfolio targets atomically by decoding Tags.
    ///
    /// This model:
    /// - Receives single insights (Leg1 only) with Tag containing pairing info
    /// - Decodes Tag to get Leg2 symbol and grid configuration
    /// - Generates ArbitragePortfolioTarget with both legs
    /// - Allocates portfolio percentage based on PositionSizePct
    /// - Propagates Tags to targets for ExecutionModel
    ///
    /// This implementation does NOT inherit from PortfolioConstructionModel
    /// as arbitrage trading has different semantics and requirements.
    /// </summary>
    public class ArbitragePortfolioConstructionModel : IArbitragePortfolioConstructionModel
    {
        private Func<DateTime, DateTime?> _rebalancingFunc;
        private DateTime? _rebalancingTime;
        private bool _insightChanges;

        /// <summary>
        /// The algorithm instance
        /// </summary>
        protected IAlgorithm Algorithm { get; set; }
        /// <summary>
        /// Creates a new ArbitragePortfolioConstructionModel
        /// </summary>
        /// <param name="rebalance">Rebalancing function. If null, rebalances on every insight change</param>
        public ArbitragePortfolioConstructionModel(
            Func<DateTime, DateTime?> rebalance = null)
        {
            _rebalancingFunc = rebalance;
        }

        /// <summary>
        /// Gets the target insights to generate portfolio targets.
        /// Returns all active Leg1 insights (no GroupId filtering needed).
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>List of active Leg1 insights with Tags</returns>
        private List<Insight> GetTargetInsights(QCAlgorithm algorithm)
        {
            // Get all active insights
            var activeInsights = algorithm.Insights
                .GetActiveInsights(algorithm.UtcTime)
                .Where(ShouldCreateTargetForInsight)
                .OrderByDescending(x => x.GeneratedTimeUtc)
                .ToList();

            if (activeInsights.Count != 0)
            {
                Log.Trace($"ArbitragePortfolioConstructionModel.GetTargetInsights: " +
                         $"Total active insights = {activeInsights.Count}");
            }

            return activeInsights;
        }

        /// <summary>
        /// Determines if we should create a target for the given insight
        /// </summary>
        /// <param name="insight">The insight to check</param>
        /// <returns>True if a target should be created</returns>
        private bool ShouldCreateTargetForInsight(Insight insight)
        {
            // Only create targets for insights with valid Tags
            return !string.IsNullOrEmpty(insight.Tag);
        }

        /// <summary>
        /// Determines the target allocation percentage for each insight.
        /// Decodes Tags to get PositionSizePct and calculates allocation.
        /// </summary>
        /// <param name="activeInsights">Active Leg1 insights with Tags</param>
        /// <returns>Dictionary mapping each insight to its target allocation percentage</returns>
        private Dictionary<Insight, double> DetermineTargetPercent(List<Insight> activeInsights)
        {
            var result = new Dictionary<Insight, double>();

            Log.Trace($"ArbitragePortfolioConstructionModel.DetermineTargetPercent: activeInsights.Count = {activeInsights.Count}");

            if (activeInsights.Count == 0)
            {
                return result;
            }

            // Allocate equal percentage to each insight (1 insight per trading pair)
            var percentPerInsight = 1.0 / activeInsights.Count;

            foreach (var insight in activeInsights)
            {
                // Decode Tag to get grid configuration
                if (!TradingPairManager.TryDecodeGridTag(
                    insight.Tag, out _, out _, out var levelPair))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel: Failed to decode grid tag: " +
                              $"{insight.Tag ?? "null"}");
                    continue;
                }

                // Calculate allocation based on PositionSizePct from grid configuration
                var targetPercent = percentPerInsight * (double)levelPair.Entry.PositionSizePct;

                // Set allocation with direction sign (Up=1, Down=-1, Flat=0)
                var direction = (int)insight.Direction;
                result[insight] = targetPercent * direction;
            }

            return result;
        }

        /// <summary>
        /// Determines if rebalancing is due based on insights and time
        /// </summary>
        /// <param name="insights">The insights array</param>
        /// <param name="algorithmUtc">Current algorithm UTC time</param>
        /// <returns>True if rebalancing should occur</returns>
        protected virtual bool IsRebalanceDue(Insight[] insights, DateTime algorithmUtc)
        {
            // Check if we have any new insights
            if (insights != null && insights.Length > 0)
            {
                _insightChanges = true;
            }

            // If no rebalancing function provided, rebalance on insight changes
            if (_rebalancingFunc == null)
            {
                if (_insightChanges)
                {
                    _insightChanges = false;
                    return true;
                }
                return false;
            }

            // Check if scheduled rebalancing time has been reached
            if (_rebalancingTime == null || algorithmUtc >= _rebalancingTime)
            {
                _rebalancingTime = _rebalancingFunc(algorithmUtc);
            }

            // Rebalance if scheduled time has been reached
            if (_rebalancingTime != null && algorithmUtc >= _rebalancingTime)
            {
                _insightChanges = false;
                return true;
            }

            return false;
        }

        /// <summary>
        /// Creates arbitrage portfolio targets from insights using the Tag-based approach.
        /// This is the arbitrage-specific version that returns IArbitragePortfolioTarget
        /// instead of IPortfolioTarget, supporting per-position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="insights">Array of insights</param>
        /// <returns>Array of arbitrage portfolio targets (one per grid position)</returns>
        public IArbitragePortfolioTarget[] CreateArbitrageTargets(
            IAlgorithm algorithm, Insight[] insights)
        {
            // Cast to QCAlgorithm for base class methods
            if (!(algorithm is QCAlgorithm qcAlgorithm))
            {
                Log.Error("ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                          "Algorithm must be QCAlgorithm");
                return Array.Empty<IArbitragePortfolioTarget>();
            }

            // Set Algorithm property for base class methods
            Algorithm = qcAlgorithm;

            // Check if algorithm implements AIAlgorithm
            if (!(algorithm is AIAlgorithm aiAlgorithm))
            {
                Log.Error("ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                          "Algorithm must implement AIAlgorithm interface");
                return Array.Empty<IArbitragePortfolioTarget>();
            }

            // Check if rebalancing is due
            if (!IsRebalanceDue(insights, qcAlgorithm.UtcTime))
            {
                return Array.Empty<IArbitragePortfolioTarget>();
            }

            // Get target insights (Leg1 insights with Tags)
            var targetInsights = GetTargetInsights(qcAlgorithm);

            Log.Trace($"ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                     $"targetInsights.Count = {targetInsights.Count}");

            if (targetInsights.Count == 0)
            {
                return Array.Empty<IArbitragePortfolioTarget>();
            }

            // Calculate target allocations
            var targetPercents = DetermineTargetPercent(targetInsights);

            Log.Trace($"ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                     $"targetPercents.Count = {targetPercents.Count}");

            var targets = new List<IArbitragePortfolioTarget>();

            // Create arbitrage portfolio targets (one per insight/grid position)
            foreach (var insight in targetInsights)
            {
                if (!targetPercents.TryGetValue(insight, out var percent))
                {
                    Log.Error("ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                             "Failed to get percent for insight");
                    continue;
                }

                // Decode Tag to get symbols and grid configuration
                if (!TradingPairManager.TryDecodeGridTag(
                    insight.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                             $"Failed to decode grid tag: {insight.Tag ?? "null"}");
                    continue;
                }

                // Get trading pair
                if (!aiAlgorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                             $"Trading pair not found: ({leg1Symbol}, {leg2Symbol})");
                    continue;
                }

                // Calculate delta quantities for both legs
                var leg1Delta = CalculateLegDelta(qcAlgorithm, leg1Symbol, percent);

                // Leg2 has opposite direction for entry, same for exit (Flat)
                var leg2Percent = insight.Direction == InsightDirection.Flat
                    ? percent
                    : percent * -1;  // Opposite direction for spread trading

                var leg2Delta = CalculateLegDelta(qcAlgorithm, leg2Symbol, leg2Percent);

                // Create ArbitragePortfolioTarget with Tag (no GridPosition reference needed)
                var target = new ArbitragePortfolioTarget(
                    leg1Symbol,
                    leg2Symbol,
                    leg1Delta,
                    leg2Delta,
                    insight.Tag);
                targets.Add(target);

                Log.Trace($"ArbitragePortfolioConstructionModel.CreateArbitrageTargets: " +
                         $"Created target: {target}");
            }

            // Clean up expired insights
            Algorithm.Insights.RemoveExpiredInsights(qcAlgorithm.UtcTime);

            return targets.ToArray();
        }

        /// <summary>
        /// Event fired when securities are added or removed from the algorithm
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The security additions and removals</param>
        public void OnSecuritiesChanged(IAlgorithm algorithm, SecurityChanges changes)
        {
            // Arbitrage strategies don't need special handling for security changes
            // as the TradingPairManager handles pair-level lifecycle
        }

        /// <summary>
        /// Calculates the delta quantity for a leg based on target percent
        /// </summary>
        private decimal CalculateLegDelta(
            QCAlgorithm algorithm,
            Symbol symbol,
            double targetPercent)
        {
            // Use PortfolioTarget.Percent with returnDeltaQuantity=true to get delta
            var target = PortfolioTarget.Percent(
                algorithm,
                symbol,
                (decimal)targetPercent,
                returnDeltaQuantity: true);

            if (target == null)
            {
                Log.Error($"ArbitragePortfolioConstructionModel.CalculateLegDelta: " +
                         $"Failed to calculate target for {symbol}");
                return 0;
            }

            return target.Quantity;
        }

    }
}
