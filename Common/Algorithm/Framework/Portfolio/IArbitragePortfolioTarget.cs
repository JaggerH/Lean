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

using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Portfolio target interface for arbitrage trading with paired legs.
    /// Represents both legs of an arbitrage position with Tag-based tracking.
    /// </summary>
    public interface IArbitragePortfolioTarget
    {
        /// <summary>
        /// Symbol for the first leg of the arbitrage pair
        /// </summary>
        Symbol Leg1Symbol { get; }

        /// <summary>
        /// Symbol for the second leg of the arbitrage pair
        /// </summary>
        Symbol Leg2Symbol { get; }

        /// <summary>
        /// Delta quantity for the first leg (amount to trade, not absolute target)
        /// </summary>
        decimal Leg1Quantity { get; }

        /// <summary>
        /// Delta quantity for the second leg (amount to trade, not absolute target)
        /// </summary>
        decimal Leg2Quantity { get; }

        /// <summary>
        /// Grid level containing spread and direction information for this execution.
        /// Eliminates need for Tag parsing in execution model.
        /// </summary>
        GridLevel Level { get; }

        /// <summary>
        /// Tag for tracking this specific grid position.
        /// Format: "{Symbol1}|{Symbol2}|{EntrySpread}|{ExitSpread}|{Direction}|{PositionSize}"
        /// </summary>
        string Tag { get; }
    }
}
