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

using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;
using QuantConnect.Orders;

namespace QuantConnect.Algorithm.Framework.Execution
{
    /// <summary>
    /// Execution model interface for arbitrage trading.
    /// Accepts ArbitragePortfolioTarget instead of IPortfolioTarget to support
    /// paired leg execution with Tag-based tracking for grid positions.
    /// </summary>
    public interface IArbitrageExecutionModel
    {
        /// <summary>
        /// Executes arbitrage portfolio targets by placing orders for both legs.
        /// Tags are propagated from targets to orders for position tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="targets">The arbitrage targets to execute</param>
        void Execute(AQCAlgorithm algorithm, IArbitragePortfolioTarget[] targets);

        /// <summary>
        /// Event fired on order events (fills, partial fills, cancellations)
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="orderEvent">The order event</param>
        void OnOrderEvent(AQCAlgorithm algorithm, OrderEvent orderEvent);
    }
}
