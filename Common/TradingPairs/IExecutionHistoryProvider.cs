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
using System.Collections.Generic;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Provides historical execution query functionality for brokerages
    /// </summary>
    public interface IExecutionHistoryProvider
    {
        /// <summary>
        /// Gets historical execution records for a symbol within a time range
        /// </summary>
        /// <param name="symbol">The symbol to query</param>
        /// <param name="startTimeUtc">Start time (UTC)</param>
        /// <param name="endTimeUtc">End time (UTC)</param>
        /// <returns>List of execution records</returns>
        List<ExecutionRecord> GetExecutionHistory(Symbol symbol, DateTime startTimeUtc, DateTime endTimeUtc);
    }
}
