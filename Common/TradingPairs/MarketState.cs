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

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Represents the market state of a trading pair based on spread conditions
    /// </summary>
    public enum MarketState
    {
        /// <summary>
        /// Normal market condition with positive spread
        /// </summary>
        Normal,

        /// <summary>
        /// Market is crossed - arbitrage opportunity exists
        /// </summary>
        Crossed,

        /// <summary>
        /// Market is inverted but not crossed
        /// </summary>
        Inverted,

        /// <summary>
        /// Insufficient data to determine market state
        /// </summary>
        Unknown
    }
}