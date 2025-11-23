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

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Represents a historical execution record from a brokerage
    /// </summary>
    public class ExecutionRecord
    {
        /// <summary>
        /// Unique execution identifier from the brokerage
        /// </summary>
        public string ExecutionId { get; set; }

        /// <summary>
        /// The symbol that was executed
        /// </summary>
        public Symbol Symbol { get; set; }

        /// <summary>
        /// Executed quantity (signed: positive=buy, negative=sell)
        /// </summary>
        public decimal Quantity { get; set; }

        /// <summary>
        /// Execution price
        /// </summary>
        public decimal Price { get; set; }

        /// <summary>
        /// Execution time in UTC
        /// </summary>
        public DateTime TimeUtc { get; set; }

        /// <summary>
        /// Order tag if available (e.g., Gate.io text field, may be null for IBKR)
        /// </summary>
        public string Tag { get; set; }

        /// <summary>
        /// Execution fee amount
        /// </summary>
        public decimal Fee { get; set; }

        /// <summary>
        /// Currency of the fee
        /// </summary>
        public string FeeCurrency { get; set; }
    }
}
