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
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Portfolio target for arbitrage trading representing a complete GridPosition.
    /// Contains both legs with absolute target quantities (not deltas).
    /// ExecutionModel calculates deltas by comparing target quantities with current holdings.
    /// This class does NOT implement IPortfolioTarget as it has different semantics
    /// specific to arbitrage trading with paired legs.
    /// </summary>
    public class ArbitragePortfolioTarget : IArbitragePortfolioTarget
    {
        /// <summary>
        /// First leg symbol
        /// </summary>
        public Symbol Leg1Symbol { get; }

        /// <summary>
        /// Second leg symbol
        /// </summary>
        public Symbol Leg2Symbol { get; }

        /// <summary>
        /// Target quantity for leg1 (absolute position target, not delta).
        /// ExecutionModel will calculate the delta (difference from current holdings).
        /// </summary>
        public decimal Leg1Quantity { get; }

        /// <summary>
        /// Target quantity for leg2 (absolute position target, not delta).
        /// ExecutionModel will calculate the delta (difference from current holdings).
        /// </summary>
        public decimal Leg2Quantity { get; }

        /// <summary>
        /// Grid level containing spread and direction information for this execution.
        /// Eliminates need for Tag parsing in execution model.
        /// </summary>
        public GridLevel Level { get; }

        /// <summary>
        /// Tag for tracking back to GridPosition.
        /// Format: "{Symbol1.ID}|{Symbol2.ID}|{EntrySpread}|{ExitSpread}|{Direction}|{PositionSize}"
        /// Use TradingPairManager.TryDecodeGridTag() to retrieve GridPosition from this Tag.
        /// </summary>
        public string Tag { get; }

        /// <summary>
        /// Creates a new ArbitragePortfolioTarget for a grid position
        /// </summary>
        /// <param name="leg1Symbol">First leg symbol</param>
        /// <param name="leg2Symbol">Second leg symbol</param>
        /// <param name="leg1Quantity">Target quantity for leg1 (absolute position target)</param>
        /// <param name="leg2Quantity">Target quantity for leg2 (absolute position target)</param>
        /// <param name="level">Grid level with spread and direction information</param>
        /// <param name="tag">Tag identifying the grid position</param>
        public ArbitragePortfolioTarget(
            Symbol leg1Symbol,
            Symbol leg2Symbol,
            decimal leg1Quantity,
            decimal leg2Quantity,
            GridLevel level,
            string tag)
        {
            Leg1Symbol = leg1Symbol ?? throw new ArgumentNullException(nameof(leg1Symbol));
            Leg2Symbol = leg2Symbol ?? throw new ArgumentNullException(nameof(leg2Symbol));
            Leg1Quantity = leg1Quantity;
            Leg2Quantity = leg2Quantity;
            Level = level;
            Tag = tag ?? throw new ArgumentNullException(nameof(tag));
        }

        /// <summary>
        /// Returns a string representation of the arbitrage portfolio target
        /// </summary>
        public override string ToString()
        {
            return $"[{Tag}] Leg1: {Leg1Symbol} {Leg1Quantity:F2}, Leg2: {Leg2Symbol} {Leg2Quantity:F2}";
        }
    }
}
