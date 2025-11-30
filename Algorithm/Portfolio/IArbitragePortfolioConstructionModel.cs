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

using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Portfolio construction model interface for arbitrage trading.
    /// Returns ArbitragePortfolioTarget instead of IPortfolioTarget to support
    /// per-position tracking with Tag-based management for multiple grid levels.
    /// </summary>
    public interface IArbitragePortfolioConstructionModel
    {
        /// <summary>
        /// Creates arbitrage portfolio targets from insights.
        /// Each insight should contain a Tag with grid position information.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="insights">The insights to create targets from</param>
        /// <returns>Array of arbitrage portfolio targets (one per grid position)</returns>
        IArbitragePortfolioTarget[] CreateArbitrageTargets(
            IAlgorithm algorithm, Insight[] insights);

        /// <summary>
        /// Event fired when securities are added or removed from the algorithm
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The security additions and removals</param>
        void OnSecuritiesChanged(IAlgorithm algorithm, SecurityChanges changes);
    }
}
