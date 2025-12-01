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
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Securities.MultiAccount;
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
        protected AIAlgorithm Algorithm { get; set; }
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
        private List<Insight> GetTargetInsights(AIAlgorithm algorithm)
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
        /// <param name="algorithm">The algorithm instance (must be AIAlgorithm)</param>
        /// <param name="insights">Array of insights</param>
        /// <returns>Array of arbitrage portfolio targets (one per grid position)</returns>
        public IArbitragePortfolioTarget[] CreateArbitrageTargets(
            IAlgorithm algorithm, Insight[] insights)
        {
            // Framework guarantees algorithm is AIAlgorithm (which extends QCAlgorithm)
            // Only AQCAlgorithm calls this method
            Algorithm = (AIAlgorithm)algorithm;

            // Check if rebalancing is due
            if (!IsRebalanceDue(insights, Algorithm.UtcTime))
            {
                return Array.Empty<IArbitragePortfolioTarget>();
            }

            var targets = new List<IArbitragePortfolioTarget>();

            // Get active insights
            var activeInsights = GetTargetInsights(Algorithm);

            foreach (var insight in activeInsights)
            {
                // Decode Tag to get symbols and grid configuration
                if (!TradingPairManager.TryDecodeGridTag(
                    insight.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel: " +
                             $"Failed to decode grid tag: {insight.Tag ?? "null"}");
                    continue;
                }

                // Validate trading pair exists
                if (!Algorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
                {
                    Log.Error($"ArbitragePortfolioConstructionModel: " +
                             $"Trading pair not found: ({leg1Symbol}, {leg2Symbol})");
                    continue;
                }

                // Get GridLevel from insight (GridInsight carries Level property)
                var level = ((GridInsight)insight).Level;

                // Calculate target percent from GridLevel (NOT divided by insight count)
                var targetPercent = level.PositionSizePct;

                // Apply direction
                if (insight.Direction == InsightDirection.Down)
                {
                    targetPercent = -targetPercent;
                }
                else if (insight.Direction == InsightDirection.Flat)
                {
                    // Flat = Exit signal, generate zero-quantity target for closing
                    targets.Add(new ArbitragePortfolioTarget(
                        leg1Symbol,
                        leg2Symbol,
                        0,  // Target quantity = 0 (close position)
                        0,
                        level,
                        insight.Tag));
                    continue;
                }

                // Calculate target quantities using multi-account logic
                var pairTargets = CalculatePairTargets(leg1Symbol, leg2Symbol, targetPercent);

                if (!pairTargets.HasValue)
                {
                    Log.Error($"ArbitragePortfolioConstructionModel: " +
                             $"Failed to calculate targets for {leg1Symbol}/{leg2Symbol}");
                    continue;
                }

                // Create ArbitragePortfolioTarget with ABSOLUTE quantities
                var target = new ArbitragePortfolioTarget(
                    leg1Symbol,
                    leg2Symbol,
                    pairTargets.Value.leg1Qty,  // Absolute target quantity
                    pairTargets.Value.leg2Qty,  // Absolute target quantity
                    level,
                    insight.Tag);

                targets.Add(target);
            }

            // Clean up expired insights (no Target generation needed)
            // ExecutionModel will handle Target cleanup via ClearFulfilled()
            Algorithm.Insights.RemoveExpiredInsights(Algorithm.UtcTime);
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
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// Allows the portfolio construction model to initialize or clean up resources for trading pairs.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        public virtual void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            // For removed pairs: clean up any tracking or cached portfolio targets
            // Default implementation is empty - derived classes can override
        }

        /// <summary>
        /// Calculate absolute target quantities for both legs of an arbitrage pair.
        /// Handles multi-account setup and buying power constraints.
        /// </summary>
        /// <param name="leg1Symbol">First leg symbol</param>
        /// <param name="leg2Symbol">Second leg symbol</param>
        /// <param name="targetPercent">Target percentage (signed)</param>
        /// <returns>Tuple of (leg1 target qty, leg2 target qty), or null if failed</returns>
        private (decimal leg1Qty, decimal leg2Qty)? CalculatePairTargets(
            Symbol leg1Symbol,
            Symbol leg2Symbol,
            decimal targetPercent)
        {
            // Step 1: Calculate max tradable market value
            var maxTradableValue = CalculateMaxTradableMarketValue(
                leg1Symbol, leg2Symbol, targetPercent, respectBuyingPower: true);

            if (maxTradableValue <= 0)
            {
                return null;
            }

            // Step 2: Get portfolios for each leg
            var portfolio1 = GetPortfolioForSymbol(leg1Symbol);
            var portfolio2 = GetPortfolioForSymbol(leg2Symbol);

            // Step 3: Calculate target percent for each account
            var targetPercent1 = maxTradableValue / portfolio1.TotalPortfolioValue * Math.Sign(targetPercent);
            var targetPercent2 = maxTradableValue / portfolio2.TotalPortfolioValue * -Math.Sign(targetPercent);

            // Step 4: Use PortfolioTarget.Percent to calculate target quantities
            var target1 = PortfolioTarget.Percent(
                Algorithm,
                leg1Symbol,
                targetPercent1,
                returnDeltaQuantity: false,  // Absolute quantity
                portfolio: portfolio1);

            var target2 = PortfolioTarget.Percent(
                Algorithm,
                leg2Symbol,
                targetPercent2,
                returnDeltaQuantity: false,  // Absolute quantity
                portfolio: portfolio2);

            // Step 5: Validate results
            if (target1 == null || target2 == null)
            {
                return null;
            }

            return (target1.Quantity, target2.Quantity);
        }

        /// <summary>
        /// Calculate maximum tradable market value considering both accounts' constraints.
        /// </summary>
        private decimal CalculateMaxTradableMarketValue(
            Symbol symbol1,
            Symbol symbol2,
            decimal targetPercent,
            bool respectBuyingPower)
        {
            // Get portfolios
            var portfolio1 = GetPortfolioForSymbol(symbol1);
            var portfolio2 = GetPortfolioForSymbol(symbol2);

            // Calculate planned market values
            var plannedValue1 = portfolio1.TotalPortfolioValue * Math.Abs(targetPercent);
            var plannedValue2 = portfolio2.TotalPortfolioValue * Math.Abs(targetPercent);

            decimal targetValue;

            if (respectBuyingPower)
            {
                // Get buying powers
                var (buyingPower1, buyingPower2) = GetAccountBuyingPowers(
                    symbol1, symbol2, targetPercent);

                // Take minimum across all constraints
                targetValue = Math.Min(
                    Math.Min(plannedValue1, plannedValue2),
                    Math.Min(buyingPower1, buyingPower2));
            }
            else
            {
                // Only consider portfolio values
                targetValue = Math.Min(plannedValue1, plannedValue2);
            }

            return targetValue;
        }

        /// <summary>
        /// Get buying power for both accounts based on order direction.
        /// </summary>
        private (decimal buyingPower1, decimal buyingPower2) GetAccountBuyingPowers(
            Symbol symbol1,
            Symbol symbol2,
            decimal targetPercent)
        {
            // Determine order directions
            var direction1 = targetPercent > 0 ? OrderDirection.Buy : OrderDirection.Sell;
            var direction2 = targetPercent > 0 ? OrderDirection.Sell : OrderDirection.Buy;  // Opposite

            // Get portfolios
            var portfolio1 = GetPortfolioForSymbol(symbol1);
            var portfolio2 = GetPortfolioForSymbol(symbol2);

            // Get buying powers
            var buyingPower1 = portfolio1.GetBuyingPower(symbol1, direction1);
            var buyingPower2 = portfolio2.GetBuyingPower(symbol2, direction2);

            return (buyingPower1, buyingPower2);
        }

        /// <summary>
        /// Get the appropriate portfolio manager for a symbol.
        /// Uses multi-account routing to determine which account should hold this symbol.
        /// Falls back to main portfolio if not using multi-account setup.
        /// </summary>
        private SecurityPortfolioManager GetPortfolioForSymbol(Symbol symbol)
        {
            // Check if using multi-account portfolio
            if (Algorithm.Portfolio is MultiSecurityPortfolioManager multiPortfolio)
            {
                // Create temporary order to determine routing
                var tempOrder = new MarketOrder(symbol, 0, Algorithm.UtcTime);

                // Access router via reflection
                var router = multiPortfolio.GetType()
                    .GetField("_router", System.Reflection.BindingFlags.NonPublic |
                                         System.Reflection.BindingFlags.Instance)
                    ?.GetValue(multiPortfolio) as IOrderRouter;

                if (router == null)
                {
                    throw new InvalidOperationException(
                        "ArbitragePortfolioConstructionModel: Failed to access IOrderRouter from MultiSecurityPortfolioManager");
                }

                var accountName = router.Route(tempOrder);
                return multiPortfolio.GetAccount(accountName);
            }

            // Fallback to main portfolio (single account scenario)
            return Algorithm.Portfolio;
        }

    }
}
