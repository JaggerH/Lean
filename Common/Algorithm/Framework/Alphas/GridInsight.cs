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

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Specialized Insight for grid-based arbitrage strategies.
    /// Carries GridLevel metadata to enable efficient querying and deduplication.
    ///
    /// Note: Each GridInsight represents ONE leg of the arbitrage pair.
    /// Two GridInsight instances are created and linked via GroupId.
    /// This design maintains compatibility with LEAN's InsightCollection which indexes by Symbol.
    /// </summary>
    public class GridInsight : Insight
    {
        /// <summary>
        /// The grid level associated with this insight (Entry or Exit).
        /// For Entry insights, this is the Entry level.
        /// For Exit insights, this is the Exit level.
        /// </summary>
        public GridLevel Level { get; private set; }

        /// <summary>
        /// Creates a new GridInsight for price prediction with grid metadata.
        /// </summary>
        /// <param name="symbol">The symbol for THIS leg (either Leg1 or Leg2)</param>
        /// <param name="period">How long the insight remains valid</param>
        /// <param name="direction">The predicted direction for THIS leg</param>
        /// <param name="level">The GridLevel (Entry or Exit) this insight represents</param>
        /// <param name="confidence">Confidence level (0-1)</param>
        /// <param name="tag">Optional tag (typically encoded grid configuration)</param>
        public GridInsight(
            Symbol symbol,
            TimeSpan period,
            InsightDirection direction,
            GridLevel level,
            double? confidence = null,
            string tag = "")
            : base(symbol, period, InsightType.Price, direction, null, confidence, null, null, tag)
        {
            // GridLevel is a struct, so it cannot be null
            // We rely on struct's default validation
            Level = level;
        }

        /// <summary>
        /// Creates a deep clone of this GridInsight instance.
        /// </summary>
        public override Insight Clone()
        {
            return new GridInsight(Symbol, Period, Direction, Level, Confidence, Tag)
            {
                GeneratedTimeUtc = GeneratedTimeUtc,
                CloseTimeUtc = CloseTimeUtc,
                Score = Score,
                Id = Id,
                EstimatedValue = EstimatedValue,
                ReferenceValue = ReferenceValue,
                ReferenceValueFinal = ReferenceValueFinal,
                SourceModel = SourceModel,
                GroupId = GroupId
            };
        }
    }
}
