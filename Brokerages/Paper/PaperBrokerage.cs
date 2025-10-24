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
 *
*/

using System;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json;
using QuantConnect.Brokerages.Backtesting;
using QuantConnect.Configuration;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Packets;
using QuantConnect.Securities;

namespace QuantConnect.Brokerages.Paper
{
    /// <summary>
    /// Paper Trading Brokerage
    /// </summary>
    public class PaperBrokerage : BacktestingBrokerage
    {
        private DateTime _lastScanTime;
        private readonly LiveNodePacket _job;

        /// <summary>
        /// Enables or disables concurrent processing of messages to and from the brokerage.
        /// </summary>
        public override bool ConcurrencyEnabled { get; set; } = true;

        /// <summary>
        /// Creates a new PaperBrokerage
        /// </summary>
        /// <param name="algorithm">The algorithm under analysis</param>
        /// <param name="job">The job packet</param>
        public PaperBrokerage(IAlgorithm algorithm, LiveNodePacket job)
            : base(algorithm, "Paper Brokerage")
        {
            _job = job;
        }

        /// <summary>
        /// Gets the current cash balance for each currency held in the brokerage account
        /// </summary>
        /// <returns>The current cash balance for each currency available for trading</returns>
        public override List<CashAmount> GetCashBalance()
        {
            return GetCashBalance(_job.BrokerageData, Algorithm.Portfolio.CashBook);
        }

        /// <summary>
        /// Gets all holdings for the account
        /// </summary>
        /// <returns>The current holdings from the account</returns>
        public override List<Holding> GetAccountHoldings()
        {
            return base.GetAccountHoldings(_job.BrokerageData, Algorithm.Securities.Values);
        }

        /// <summary>
        /// Scans all the outstanding orders and applies the algorithm model fills to generate the order events.
        /// This override adds dividend detection and application
        /// </summary>
        public override void Scan()
        {
            // Scan is called twice per time loop, this check enforces that we only check
            // on the first call for each time loop
            if (Algorithm.UtcTime != _lastScanTime && Algorithm.CurrentSlice != null)
            {
                _lastScanTime = Algorithm.UtcTime;

                // apply each dividend directly to the quote cash holdings of the security
                // this assumes dividends are paid out in a security's quote cash (reasonable assumption)
                foreach (var dividend in Algorithm.CurrentSlice.Dividends.Values)
                {
                    Security security;
                    if (Algorithm.Securities.TryGetValue(dividend.Symbol, out security))
                    {
                        // compute the total distribution and apply as security's quote currency
                        var distribution = security.Holdings.Quantity * dividend.Distribution;
                        security.QuoteCurrency.AddAmount(distribution);
                    }
                }
            }

            base.Scan();
        }

        /// <summary>
        /// Gets cash balance for a specific account from state file or BrokerageData (fallback)
        /// Used for multi-account state recovery
        /// </summary>
        /// <param name="accountName">The name of the account</param>
        /// <returns>List of cash amounts for the specified account</returns>
        public override List<CashAmount> GetCashBalanceForAccount(string accountName)
        {
            // Level 1: Try to read from state file (via base class)
            var result = base.GetCashBalanceForAccount(accountName);
            if (result != null && result.Count > 0)
            {
                return result;
            }

            // Level 2: Fallback to BrokerageData (backward compatibility for live trading)
            var key = $"live-cash-balance:{accountName}";
            if (_job.BrokerageData != null && _job.BrokerageData.Remove(key, out var value) && !string.IsNullOrEmpty(value))
            {
                try
                {
                    var brokerageDataResult = JsonConvert.DeserializeObject<List<CashAmount>>(value);
                    if (brokerageDataResult != null)
                    {
                        return brokerageDataResult;
                    }
                }
                catch (Exception ex)
                {
                    Log.Error($"PaperBrokerage.GetCashBalanceForAccount(): Failed to deserialize cash balance for account '{accountName}' from BrokerageData: {ex.Message}");
                }
            }

            // Level 3: Return empty list (fresh start)
            return new List<CashAmount>();
        }

        /// <summary>
        /// Gets holdings for a specific account from state file or BrokerageData (fallback)
        /// Used for multi-account state recovery
        /// </summary>
        /// <param name="accountName">The name of the account</param>
        /// <returns>List of holdings for the specified account</returns>
        public override List<Holding> GetAccountHoldingsForAccount(string accountName)
        {
            // Level 1: Try to read from state file (via base class)
            var result = base.GetAccountHoldingsForAccount(accountName);
            if (result != null && result.Count > 0)
            {
                return result;
            }

            // Level 2: Fallback to BrokerageData (backward compatibility for live trading)
            var key = $"live-holdings:{accountName}";
            if (_job.BrokerageData != null && _job.BrokerageData.Remove(key, out var value) && !string.IsNullOrEmpty(value))
            {
                try
                {
                    var brokerageDataResult = JsonConvert.DeserializeObject<List<Holding>>(value);
                    if (brokerageDataResult != null)
                    {
                        return brokerageDataResult;
                    }
                }
                catch (Exception ex)
                {
                    Log.Error($"PaperBrokerage.GetAccountHoldingsForAccount(): Failed to deserialize holdings for account '{accountName}' from BrokerageData: {ex.Message}");
                }
            }

            // Level 3: Return empty list (fresh start)
            return new List<Holding>();
        }
    }
}
