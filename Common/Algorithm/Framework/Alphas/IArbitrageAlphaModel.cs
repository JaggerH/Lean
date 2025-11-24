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

using System.Collections.Generic;
using QuantConnect.Data;
using QuantConnect.Interfaces;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Arbitrage alpha model interface for AI algorithms.
    /// Generates ArbitrageInsight objects based on TradingPair spread analysis.
    /// </summary>
    public interface IArbitrageAlphaModel
    {
        /// <summary>
        /// Updates this alpha model with the latest data from the arbitrage algorithm.
        /// This is called each time the algorithm receives data for subscribed securities.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance (provides access to TradingPairs)</param>
        /// <param name="data">The new data available</param>
        /// <returns>The new arbitrage insights generated</returns>
        IEnumerable<ArbitrageInsight> Update(AIAlgorithm algorithm, Slice data);

        /// <summary>
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// This allows the alpha model to initialize or clean up resources for trading pairs.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        void OnTradingPairsChanged(AIAlgorithm algorithm, TradingPairChanges changes);
    }
}
