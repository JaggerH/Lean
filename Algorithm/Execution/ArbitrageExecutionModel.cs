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
        /// Creates a new ArbitrageExecutionModel
        /// </summary>
        /// <param name="asynchronous">True to submit orders asynchronously, false for synchronous</param>
        public ArbitrageExecutionModel(bool asynchronous = true)
        {
            Asynchronous = asynchronous;
        }

        /// <summary>
        /// Executes arbitrage portfolio targets by placing orders for both legs.
        /// Tags are propagated from targets to orders for position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="targets">The arbitrage targets to execute</param>
        public void Execute(IAlgorithm algorithm, IArbitragePortfolioTarget[] targets)
        {
            // Add new targets to collection (will overwrite existing targets with same Tag)
            _targetsCollection.AddRange(targets);

            if (!_targetsCollection.IsEmpty)
            {
                // Execute all targets
                foreach (var target in _targetsCollection.GetTargets())
                {
                    // Execute both legs
                    ExecuteLeg(algorithm, target, isLeg1: true);
                    ExecuteLeg(algorithm, target, isLeg1: false);
                }

                // Clear fulfilled targets
                _targetsCollection.ClearFulfilled(algorithm);
            }
        }

        /// <summary>
        /// Executes a single leg of an arbitrage target
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">The arbitrage target</param>
        /// <param name="isLeg1">True to execute leg1, false to execute leg2</param>
        protected virtual void ExecuteLeg(IAlgorithm algorithm, IArbitragePortfolioTarget target, bool isLeg1)
        {
            // Cast to QCAlgorithm for order placement
            if (!(algorithm is QCAlgorithm qcAlgorithm))
            {
                return;
            }

            var symbol = isLeg1 ? target.Leg1Symbol : target.Leg2Symbol;
            var targetDelta = isLeg1 ? target.Leg1Quantity : target.Leg2Quantity;

            // Get GridPosition from Tag
            decimal currentQty = 0;
            if (algorithm is Interfaces.AIAlgorithm aiAlgorithm)
            {
                if (TradingPairs.TradingPairManager.TryDecodeGridTag(
                    target.Tag, out var leg1Symbol, out var leg2Symbol, out var levelPair))
                {
                    if (aiAlgorithm.TradingPairs.TryGetValue((leg1Symbol, leg2Symbol), out var pair))
                    {
                        var position = pair.GetOrCreatePosition(levelPair);
                        currentQty = isLeg1 ? position.Leg1Quantity : position.Leg2Quantity;
                    }
                }
            }

            // Check if security exists
            if (!algorithm.Securities.ContainsKey(symbol))
            {
                qcAlgorithm.Error($"ArbitrageExecutionModel.ExecuteLeg: Security {symbol} not found");
                return;
            }

            var security = algorithm.Securities[symbol];

            // Calculate unordered quantity
            // Simplified: assume initial position = 0
            var alreadyTraded = currentQty;

            // Only count open orders with same Tag to avoid cross-contamination
            var openOrdersQty = GetOpenOrderQuantityForTag(algorithm, symbol, target.Tag);

            var unorderedQty = targetDelta - alreadyTraded - openOrdersQty;

            // Adjust to lot size
            unorderedQty = ArbitrageOrderSizing.AdjustByLotSize(security, unorderedQty);

            // Check if we need to place an order
            if (Math.Abs(unorderedQty) < security.SymbolProperties.LotSize)
            {
                return;
            }

            // Submit market order with Tag for tracking
            qcAlgorithm.MarketOrder(security, unorderedQty, Asynchronous, target.Tag);

            qcAlgorithm.Debug($"ArbitrageExecutionModel: Placed order for {symbol} " +
                          $"quantity={unorderedQty:F2} tag={target.Tag}");
        }

        /// <summary>
        /// Gets the total open order quantity for a specific symbol and tag.
        /// Only counts orders with matching Tag to support per-position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="symbol">The symbol to check</param>
        /// <param name="tag">The tag to filter by</param>
        /// <returns>Total open order quantity for this tag</returns>
        protected virtual decimal GetOpenOrderQuantityForTag(IAlgorithm algorithm, Symbol symbol, string tag)
        {
            // Use GetOpenOrderTickets to access QuantityRemaining
            return algorithm.Transactions.GetOpenOrderTickets(symbol)
                .Where(o => o.Tag == tag)
                .Sum(o => o.QuantityRemaining);
        }

        /// <summary>
        /// Event fired when securities are added or removed from the algorithm
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The security additions and removals</param>
        public virtual void OnSecuritiesChanged(IAlgorithm algorithm, SecurityChanges changes)
        {
            // No action needed for securities changes in default implementation
        }

        /// <summary>
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// Allows the execution model to initialize or clean up resources for trading pairs.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        public virtual void OnTradingPairsChanged(AIAlgorithm algorithm, TradingPairChanges changes)
        {
            // For removed pairs: clean up any pending orders if needed
            // Default implementation is empty - derived classes can override
        }

        /// <summary>
        /// Event fired on order events (fills, partial fills, cancellations)
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="orderEvent">The order event</param>
        public virtual void OnOrderEvent(IAlgorithm algorithm, OrderEvent orderEvent)
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
