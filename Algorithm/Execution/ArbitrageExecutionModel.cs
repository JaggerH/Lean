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
using System.Linq;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Execution
{
    /// <summary>
    /// Execution model for arbitrage trading that handles ArbitragePortfolioTarget.
    /// Executes both legs of paired positions with Tag-based tracking for per-position management.
    /// This is fundamentally different from standard ExecutionModel which handles IPortfolioTarget.
    /// </summary>
    public class ArbitrageExecutionModel : IArbitrageExecutionModel
    {
        private readonly ArbitragePortfolioTargetCollection _targetsCollection = new ArbitragePortfolioTargetCollection();

        /// <summary>
        /// Gets whether orders should be submitted asynchronously
        /// </summary>
        protected bool Asynchronous { get; }

        /// <summary>
        /// Gets the preferred matching strategy for orderbook execution
        /// </summary>
        protected MatchingStrategy PreferredStrategy { get; }

        /// <summary>
        /// Creates a new ArbitrageExecutionModel
        /// </summary>
        /// <param name="asynchronous">True to submit orders asynchronously, false for synchronous</param>
        /// <param name="preferredStrategy">Preferred matching strategy (default: AutoDetect)</param>
        public ArbitrageExecutionModel(
            bool asynchronous = true,
            MatchingStrategy preferredStrategy = MatchingStrategy.AutoDetect)
        {
            Asynchronous = asynchronous;
            PreferredStrategy = preferredStrategy;
        }

        /// <summary>
        /// Executes arbitrage portfolio targets by placing orders for both legs.
        /// Tags are propagated from targets to orders for position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="targets">The arbitrage targets to execute</param>
        public void Execute(AQCAlgorithm algorithm, IArbitragePortfolioTarget[] targets)
        {
            // Add new targets to collection (will overwrite existing targets with same Tag)
            _targetsCollection.AddRange(targets);

            if (!_targetsCollection.IsEmpty)
            {
                // Execute all targets using orderbook-aware matching
                foreach (var target in _targetsCollection.GetTargets())
                {
                    ExecuteWithOrderbook(algorithm, target);
                }

                // Clear fulfilled targets
                _targetsCollection.ClearFulfilled(algorithm);
            }
        }

        /// <summary>
        /// Executes target using orderbook-aware matching.
        /// Validates spreads and respects market depth before placing orders.
        /// </summary>
        private void ExecuteWithOrderbook(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // Get spread parameters directly from Level (no parsing needed)
            var direction = target.Level.Direction == "LONG_SPREAD"
                ? ArbitrageDirection.LongSpread
                : ArbitrageDirection.ShortSpread;
            var expectedSpreadPct = target.Level.SpreadPct;

            // Calculate remaining quantities to execute
            var (leg1Remaining, leg2Remaining) = CalculateRemainingQuantities(algorithm, target);

            // Check if already filled
            var lot1 = algorithm.Securities[target.Leg1Symbol].SymbolProperties.LotSize;
            var lot2 = algorithm.Securities[target.Leg2Symbol].SymbolProperties.LotSize;

            if (Math.Abs(leg1Remaining) < lot1 && Math.Abs(leg2Remaining) < lot2)
            {
                return; // Already filled
            }

            // Calculate target USD based on remaining quantity
            var security1 = algorithm.Securities[target.Leg1Symbol];
            var targetUsd = Math.Abs(leg1Remaining) * security1.Price;

            if (targetUsd <= 0)
            {
                return;
            }

            // Use OrderbookMatcher to calculate executable quantities
            var matchResult = OrderbookMatcher.MatchPair(
                algorithm,
                target.Leg1Symbol,
                target.Leg2Symbol,
                targetUsd,
                direction,
                expectedSpreadPct,
                PreferredStrategy
            );

            // Validate match result
            if (matchResult == null || !matchResult.Executable)
            {
                algorithm.Debug($"ArbitrageExecutionModel: Orderbook matching rejected for {target.Tag}: {matchResult?.RejectReason ?? "null result"}");
                return;
            }

            // Place orders for both legs using matched quantities
            PlaceMatchedOrders(algorithm, target, matchResult);
        }

        /// <summary>
        /// Places orders based on orderbook match result
        /// </summary>
        private void PlaceMatchedOrders(AQCAlgorithm algorithm, IArbitragePortfolioTarget target, MatchResult matchResult)
        {
            // Place leg1 order
            var lot1 = algorithm.Securities[target.Leg1Symbol].SymbolProperties.LotSize;
            if (Math.Abs(matchResult.Symbol1Quantity) >= lot1)
            {
                algorithm.MarketOrder(target.Leg1Symbol, matchResult.Symbol1Quantity, Asynchronous, target.Tag);
            }

            // Place leg2 order
            var lot2 = algorithm.Securities[target.Leg2Symbol].SymbolProperties.LotSize;
            if (Math.Abs(matchResult.Symbol2Quantity) >= lot2)
            {
                algorithm.MarketOrder(target.Leg2Symbol, matchResult.Symbol2Quantity, Asynchronous, target.Tag);
            }

            algorithm.Debug($"ArbitrageExecutionModel: Orderbook-matched orders placed | " +
                $"{target.Leg1Symbol}={matchResult.Symbol1Quantity:F4} {target.Leg2Symbol}={matchResult.Symbol2Quantity:F4} | " +
                $"spread={matchResult.AvgSpreadPct * 100:F2}% strategy={matchResult.UsedStrategy} tag={target.Tag}");
        }

        /// <summary>
        /// Calculates remaining quantities for both legs
        /// </summary>
        private (decimal leg1, decimal leg2) CalculateRemainingQuantities(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // Get current positions for both legs
            var (currentQty1, currentQty2) = GetCurrentQuantities(algorithm, target);

            // Get open orders for both legs
            var (openOrders1, openOrders2) = GetOpenOrderQuantitiesForTag(algorithm, target);

            // Calculate remaining
            var remaining1 = target.Leg1Quantity - currentQty1 - openOrders1;
            var remaining2 = target.Leg2Quantity - currentQty2 - openOrders2;

            return (remaining1, remaining2);
        }

        /// <summary>
        /// Gets current quantities for both legs from GridPosition
        /// </summary>
        private (decimal leg1Qty, decimal leg2Qty) GetCurrentQuantities(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            if (!(algorithm is Interfaces.AIAlgorithm aiAlgorithm))
            {
                return (0, 0);
            }

            if (!TradingPairs.TradingPairManager.TryDecodeGridTag(
                target.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
            {
                return (0, 0);
            }

            if (!aiAlgorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
            {
                return (0, 0);
            }

            var position = pair.GetOrCreatePosition(levelPair);
            return (position.Leg1Quantity, position.Leg2Quantity);
        }

        /// <summary>
        /// Gets the total open order quantities for both legs with matching tag.
        /// Only counts orders with matching Tag to support per-position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target with symbols and tag</param>
        /// <returns>Tuple of (leg1 open quantity, leg2 open quantity)</returns>
        protected virtual (decimal leg1Qty, decimal leg2Qty) GetOpenOrderQuantitiesForTag(
            AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            var leg1Qty = algorithm.Transactions.GetOpenOrderTickets(target.Leg1Symbol)
                .Where(o => o.Tag == target.Tag)
                .Sum(o => o.QuantityRemaining);

            var leg2Qty = algorithm.Transactions.GetOpenOrderTickets(target.Leg2Symbol)
                .Where(o => o.Tag == target.Tag)
                .Sum(o => o.QuantityRemaining);

            return (leg1Qty, leg2Qty);
        }

        /// <summary>
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// Allows the execution model to initialize or clean up resources for trading pairs.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        public virtual void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            // For removed pairs: clean up any pending orders if needed
            // Default implementation is empty - derived classes can override
        }

        /// <summary>
        /// Event fired on order events (fills, partial fills, cancellations)
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="orderEvent">The order event</param>
        public virtual void OnOrderEvent(AQCAlgorithm algorithm, OrderEvent orderEvent)
        {
            // No action needed for order events in default implementation
            // GridPosition is updated by AQCAlgorithm.OnOrderEvent
        }
    }

    /// <summary>
    /// Helper class for order sizing operations specific to arbitrage execution
    /// </summary>
    internal static class ArbitrageOrderSizing
    {
        /// <summary>
        /// Adjusts a quantity to the nearest lot size
        /// </summary>
        /// <param name="security">The security</param>
        /// <param name="quantity">The quantity to adjust</param>
        /// <returns>Adjusted quantity</returns>
        public static decimal AdjustByLotSize(Security security, decimal quantity)
        {
            var lotSize = security.SymbolProperties.LotSize;

            if (lotSize == 0)
            {
                return quantity;
            }

            // Round to nearest lot size
            var lots = Math.Round(quantity / lotSize, MidpointRounding.ToEven);
            return lots * lotSize;
        }
    }
}
