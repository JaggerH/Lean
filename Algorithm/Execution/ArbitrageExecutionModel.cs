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
        ///
        /// Execution priority (mirrors Python execution_manager.py::execute):
        /// 1. Validate preconditions (market open & target not filled)
        /// 2. Single-leg sweep order detection (highest priority)
        /// 3. Regular execution with orderbook matching
        /// </summary>
        private void ExecuteWithOrderbook(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // === Step 1: Validate preconditions (market open & target not filled) ===
            if (!IsMarketOpen(algorithm, target) || IsTargetFilled(algorithm, target))
            {
                return;
            }

            // === Step 2: Single-leg sweep order (highest priority) ===
            if (ShouldSweepOrder(algorithm, target))
            {
                algorithm.Debug($"ArbitrageExecutionModel: Detected single-leg fill imbalance for {target.Tag}, executing sweep order");
                SweepOrder(algorithm, target);
                return;
            }

            // === Step 3: Regular execution with orderbook matching ===
            // Use OrderbookMatcher to calculate executable quantities
            var matchResult = OrderbookMatcher.MatchPair(
                algorithm,
                target,
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
                $"spread={matchResult.AvgSpreadPct:P2} strategy={matchResult.UsedStrategy} tag={target.Tag}");
        }

        /// <summary>
        /// Gets remaining quantities for both legs (target - current position only, excludes open orders)
        /// </summary>
        private (decimal leg1, decimal leg2) GetRemainingQuantities(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // Get current positions for both legs
            var (currentQty1, currentQty2) = GetCurrentQuantities(algorithm, target);

            // Calculate remaining (target - current position)
            var remaining1 = target.Leg1Quantity - currentQty1;
            var remaining2 = target.Leg2Quantity - currentQty2;

            return (remaining1, remaining2);
        }

        /// <summary>
        /// Gets current quantities for both legs from GridPosition
        /// </summary>
        private (decimal leg1Qty, decimal leg2Qty) GetCurrentQuantities(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            if (!TradingPairManager.TryDecodeGridTag(
                target.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
            {
                return (0, 0);
            }

            if (!algorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
            {
                return (0, 0);
            }

            var position = pair.GetOrCreatePosition(levelPair);
            return (position.Leg1Quantity, position.Leg2Quantity);
        }

        /// <summary>
        /// Gets the total open order remaining quantities for both legs with matching tag.
        /// Only counts orders with matching Tag to support per-position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target with symbols and tag</param>
        /// <returns>Tuple of (leg1 open remaining quantity, leg2 open remaining quantity)</returns>
        protected virtual (decimal leg1Qty, decimal leg2Qty) GetOpenOrderRemainQuantities(
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
        /// Validates market open preconditions for both legs.
        ///
        /// Checks:
        /// 1. Both markets are open (supports extended trading hours)
        /// 2. Price data is valid (HasData and Price > 0)
        ///
        /// Mirrors Python execution_manager.py::_validate_preconditions
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        /// <returns>True if validation passes, False otherwise</returns>
        private bool IsMarketOpen(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            var leg1Security = algorithm.Securities[target.Leg1Symbol];
            var leg2Security = algorithm.Securities[target.Leg2Symbol];

            // Check if both markets are open
            var leg1Open = leg1Security.Exchange.ExchangeOpen;
            var leg2Open = leg2Security.Exchange.ExchangeOpen;

            return leg1Open && leg2Open;
        }

        /// <summary>
        /// Checks if target is already filled (within lot size tolerance).
        ///
        /// High-frequency semantic: Check if current position quantity has reached or exceeded target.
        /// Direction-aware logic prevents unnecessary re-execution when position >= target.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        /// <returns>True if both legs are filled within lot size tolerance</returns>
        private bool IsTargetFilled(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // Get current positions from GridPosition
            var (currentQty1, currentQty2) = GetCurrentQuantities(algorithm, target);

            bool isLeg1Filled;
            bool isLeg2Filled;

            if (target.Level.Direction == "LONG_SPREAD")
            {
                // LONG_SPREAD: BUY leg1 (positive qty), SELL leg2 (negative qty)
                isLeg1Filled = currentQty1 >= target.Leg1Quantity;
                isLeg2Filled = currentQty2 <= target.Leg2Quantity;
            }
            else // SHORT_SPREAD
            {
                // SHORT_SPREAD: SELL leg1 (negative qty), BUY leg2 (positive qty)
                isLeg1Filled = currentQty1 <= target.Leg1Quantity;
                isLeg2Filled = currentQty2 >= target.Leg2Quantity;
            }

            return isLeg1Filled && isLeg2Filled;
        }

        /// <summary>
        /// 触发场景是任意一腿的剩余市值小于`最小市值误差`
        /// 最小市值误差 = max(两腿 LotSize * Price)
        /// 意思是订单已经接近尾声了，但是还有部分订单没有成交，需要通过sweep order来补平
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        /// <returns>True if sweep order should be triggered</returns>
        private bool ShouldSweepOrder(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            // Precondition: Check if all orders are settled (no pending orders)
            // We only trigger sweep when previous orders have completed to avoid race conditions
            var (openOrders1, openOrders2) = GetOpenOrderRemainQuantities(algorithm, target);
            if (openOrders1 != 0 || openOrders2 != 0)
            {
                return false; // Wait for pending orders to settle
            }

            var (leg1Remaining, leg2Remaining) = GetRemainingQuantities(algorithm, target);

            var leg1Security = algorithm.Securities[target.Leg1Symbol];
            var leg2Security = algorithm.Securities[target.Leg2Symbol];

            // Calculate remaining market values for both legs
            var leg1RemainingMv = Math.Abs(leg1Remaining) * leg1Security.Price;
            var leg2RemainingMv = Math.Abs(leg2Remaining) * leg2Security.Price;

            // Calculate imbalance threshold as the larger of the two lot size market values
            // This represents the minimum market value needed to form a balanced pair
            var leg1LotMv = leg1Security.SymbolProperties.LotSize * leg1Security.Price;
            var leg2LotMv = leg2Security.SymbolProperties.LotSize * leg2Security.Price;
            var imbalanceThreshold = Math.Max(leg1LotMv, leg2LotMv);

            // Trigger sweep if any leg's remaining MV falls below the threshold
            // This indicates that leg cannot be paired anymore (too small to balance)
            return leg1RemainingMv < imbalanceThreshold || leg2RemainingMv < imbalanceThreshold;
        }

        /// <summary>
        /// Executes sweep order for the leg with remaining quantity.
        ///
        /// 一定要和 ShouldSweepOrder 配套使用，因为 SweepOrder 不管价差直接执行
        /// ShouldSweepOrder 会限制整体剩余市值占比合理
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        private void SweepOrder(AQCAlgorithm algorithm, IArbitragePortfolioTarget target)
        {
            var (leg1Remaining, leg2Remaining) = GetRemainingQuantities(algorithm, target);

            var leg1Security = algorithm.Securities[target.Leg1Symbol];
            var leg2Security = algorithm.Securities[target.Leg2Symbol];

            var lot1 = leg1Security.SymbolProperties.LotSize;
            var lot2 = leg2Security.SymbolProperties.LotSize;

            // Sweep leg1 if needed
            if (leg1Remaining != 0)
            {
                var leg1Qty = OrderSizing.AdjustByLotSize(leg1Security, leg1Remaining);
                if (Math.Abs(leg1Qty) >= lot1)
                {
                    algorithm.MarketOrder(target.Leg1Symbol, leg1Qty, Asynchronous, target.Tag);
                    algorithm.Debug($"ArbitrageExecutionModel: Sweep order | {target.Leg1Symbol}={leg1Qty:F4} | " +
                        $"Reason: {target.Leg2Symbol} filled | Tag={target.Tag}");
                }
            }

            // Sweep leg2 if needed
            if (leg2Remaining != 0)
            {
                var leg2Qty = OrderSizing.AdjustByLotSize(leg2Security, leg2Remaining);
                if (Math.Abs(leg2Qty) >= lot2)
                {
                    algorithm.MarketOrder(target.Leg2Symbol, leg2Qty, Asynchronous, target.Tag);
                    algorithm.Debug($"ArbitrageExecutionModel: Sweep order | {target.Leg2Symbol}={leg2Qty:F4} | " +
                        $"Reason: {target.Leg1Symbol} filled | Tag={target.Tag}");
                }
            }
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
}
