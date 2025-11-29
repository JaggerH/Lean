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
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Interfaces;

namespace QuantConnect.Algorithm.Framework.Portfolio
{
    /// <summary>
    /// Provides an implementation of <see cref="IArbitragePortfolioConstructionModel"/> that does nothing.
    /// This is the default model for AQCAlgorithm when arbitrage framework is not configured.
    /// </summary>
    public class NullArbitragePortfolioConstructionModel : IArbitragePortfolioConstructionModel
    {
        /// <summary>
        /// Create arbitrage targets; Does nothing in this implementation and returns an empty array
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="insights">The insights to create portfolio targets from</param>
        /// <returns>Empty array of <see cref="ArbitragePortfolioTarget"/>s</returns>
        public IArbitragePortfolioTarget[] CreateArbitrageTargets(IAlgorithm algorithm, Insight[] insights)
        {
            return Array.Empty<IArbitragePortfolioTarget>();
        }

        /// <summary>
        /// Event fired when securities are added or removed from the algorithm
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The security additions and removals</param>
        public void OnSecuritiesChanged(IAlgorithm algorithm, Data.UniverseSelection.SecurityChanges changes)
        {
            // No action needed
        }
    }
}
