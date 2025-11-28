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
using QuantConnect.Logging;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Portfolio construction model for arbitrage trading using Tag-based pairing.
    /// Consumes single Leg1 insights from GridArbitrageAlphaModel and generates
    /// paired portfolio targets atomically by decoding Tags.
    ///
    /// This model:
    /// - Receives single insights (Leg1 only) with Tag containing pairing info
    /// - Decodes Tag to get Leg2 symbol and grid configuration
    /// - Generates 2 PortfolioTargets (both legs) with same Tag
    /// - Allocates portfolio percentage based on PositionSizePct
    /// - Propagates Tags to PortfolioTargets for ExecutionModel
    /// </summary>
    public class ArbitragePortfolioConstructionModel : PortfolioConstructionModel
    {
        /// <summary>
        /// Creates a new ArbitragePortfolioConstructionModel
        /// </summary>
        /// <param name="rebalance">Rebalancing function. If null, rebalances on every insight change</param>
        public ArbitragePortfolioConstructionModel(
            Func<DateTime, DateTime?> rebalance = null)
            : base(rebalance)
        {
        }

        /// <summary>
        /// Gets the target insights to generate portfolio targets.
        /// Returns all active Leg1 insights (no GroupId filtering needed).
        /// </summary>
        /// <returns>List of active Leg1 insights with Tags</returns>
        protected override List<Insight> GetTargetInsights()
        {
            // Get all active insights (no GroupId filtering)
            var activeInsights = Algorithm.Insights
                .GetActiveInsights(Algorithm.UtcTime)
                .Where(ShouldCreateTargetForInsight)
                .OrderByDescending(x => x.GeneratedTimeUtc)
                .ToList();

            if (activeInsights.Count != 0)
            {
                Log.Trace($"ArbitragePortfolioConstructionModel.GetTargetInsights: Total active insights = {activeInsights.Count}");
            }

            return activeInsights;
        }

        /// <summary>
        /// Determines the target allocation percentage for each insight.
        /// Decodes Tags to get PositionSizePct and calculates allocation.
        /// </summary>
        /// <param name="activeInsights">Active Leg1 insights with Tags</param>
        /// <returns>Dictionary mapping each insight to its target allocation percentage</returns>
        protected override Dictionary<Insight, double> DetermineTargetPercent(List<Insight> activeInsights)
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
        /// Creates portfolio targets from insights with Tag propagation.
        /// Decodes each insight's Tag to generate paired targets for both legs.
        /// </summary>
        /// <param name="algorithm">Algorithm instance</param>
        /// <param name="insights">Array of insights</param>
        /// <returns>Enumerable of portfolio targets (2 per insight)</returns>
        public override IEnumerable<IPortfolioTarget> CreateTargets(
            QCAlgorithm algorithm, Insight[] insights)
        {
            // Set Algorithm property for base class methods
            Algorithm = algorithm;

            // Check if rebalancing is due
            if (!IsRebalanceDue(insights, algorithm.UtcTime))
            {
                yield break;
            }

            // Get target insights (Leg1 insights with Tags)
            var targetInsights = GetTargetInsights();

            Log.Trace($"ArbitragePortfolioConstructionModel.CreateTargets: targetInsights.Count = {targetInsights.Count}");

            if (targetInsights.Count == 0)
            {
                yield break;
            }

            // Calculate target allocations
            var targetPercents = DetermineTargetPercent(targetInsights);

            Log.Trace($"ArbitragePortfolioConstructionModel.CreateTargets: targetPercents.Count = {targetPercents.Count}");

            // Create paired portfolio targets (2 per insight)
            foreach (var insight in targetInsights)
            {
                if (!targetPercents.TryGetValue(insight, out var percent))
                {
                    continue;
                }

                // Decode Tag to get both symbols
                if (!TradingPairManager.TryDecodeGridTag(
                    insight.Tag, out var leg1Symbol, out var leg2Symbol, out _))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel: Failed to decode grid tag: " +
                              $"{insight.Tag ?? "null"}");
                    continue;
                }

                // Determine Leg2 direction (opposite for entry, same for exit)
                var leg2Direction = insight.Direction == InsightDirection.Flat
                    ? InsightDirection.Flat
                    : (insight.Direction == InsightDirection.Up
                        ? InsightDirection.Down
                        : InsightDirection.Up);

                // Generate 2 targets with same Tag
                var leg1Target = PortfolioTarget.Percent(
                    algorithm,
                    leg1Symbol,
                    percent,
                    insight.Tag);

                var leg2Target = PortfolioTarget.Percent(
                    algorithm,
                    leg2Symbol,
                    percent * (int)leg2Direction / (int)insight.Direction,
                    insight.Tag);

                // Only yield if both targets were successfully created
                if (leg1Target != null && leg2Target != null)
                {
                    yield return leg1Target;
                    yield return leg2Target;
                }
            }

            // Handle expired insights - flatten positions for both legs
            var expiredInsights = Algorithm.Insights.RemoveExpiredInsights(algorithm.UtcTime);

            foreach (var expired in expiredInsights)
            {
                // Only flatten if no active insights remain for this symbol
                if (!Algorithm.Insights.HasActiveInsights(expired.Symbol, algorithm.UtcTime))
                {
                    // Decode Tag to flatten both legs
                    if (TradingPairManager.TryDecodeGridTag(
                        expired.Tag, out var leg1Symbol, out var leg2Symbol, out _))
                    {
                        yield return new PortfolioTarget(leg1Symbol, 0, expired.Tag);
                        yield return new PortfolioTarget(leg2Symbol, 0, expired.Tag);
                    }
                    else
                    {
                        // Fallback: flatten the expired symbol
                        yield return new PortfolioTarget(expired.Symbol, 0, expired.Tag);
                    }
                }
            }
        }

    }
}
