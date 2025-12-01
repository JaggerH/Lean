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
    /// Provides an implementation of <see cref="IArbitrageExecutionModel"/> that does nothing.
    /// This is the default model for AQCAlgorithm when arbitrage framework is not configured.
    /// </summary>
    public class NullArbitrageExecutionModel : IArbitrageExecutionModel
    {
        /// <summary>
        /// Execute arbitrage targets; Does nothing in this implementation
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="targets">The arbitrage targets to execute</param>
        public void Execute(AQCAlgorithm algorithm, IArbitragePortfolioTarget[] targets)
        {
            // No action needed
        }

        /// <summary>
        /// Event fired on order events (fills, partial fills, cancellations)
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="orderEvent">The order event</param>
        public void OnOrderEvent(AQCAlgorithm algorithm, OrderEvent orderEvent)
        {
            // No action needed
        }
    }
}
