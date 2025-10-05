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
using System.Linq;
using System.Collections.Generic;

using QuantConnect.Data;
using QuantConnect.Orders;
using QuantConnect.Interfaces;

namespace QuantConnect.Algorithm.CSharp
{
    /// <summary>
    /// Regression algorithm asserting that spread market orders are filled correctly and atomically
    /// This algorithm tests the SpreadMarketOrder functionality for crypto arbitrage strategies
    /// </summary>
    public class SpreadMarketOrderRegressionAlgorithm : QCAlgorithm, IRegressionAlgorithmDefinition
    {
        private Symbol _btcusd;
        private Symbol _ethusd;
        private List<OrderTicket> _tickets;
        private List<OrderEvent> _fillOrderEvents = new();
        private bool _orderPlaced;

        public override void Initialize()
        {
            SetStartDate(2018, 4, 4);
            SetEndDate(2018, 4, 5);
            SetCash(100000);

            _btcusd = AddCrypto("BTCUSD", Resolution.Hour).Symbol;
            _ethusd = AddCrypto("ETHUSD", Resolution.Hour).Symbol;
        }

        public override void OnData(Slice slice)
        {
            if (!_orderPlaced && slice.ContainsKey(_btcusd) && slice.ContainsKey(_ethusd))
            {
                // Create a spread order: long BTC, short ETH
                var legs = new List<Leg>
                {
                    Leg.Create(_btcusd, 1),
                    Leg.Create(_ethusd, -10)  // Ratio to balance dollar amounts
                };

                _tickets = SpreadMarketOrder(legs, 1);
                _orderPlaced = true;

                if (_tickets.Count != 2)
                {
                    throw new RegressionTestException($"Expected 2 order tickets, found {_tickets.Count}");
                }

                foreach (var ticket in _tickets)
                {
                    if (ticket.OrderType != OrderType.SpreadMarket)
                    {
                        throw new RegressionTestException($"Expected SpreadMarket order type, found {ticket.OrderType}");
                    }
                }
            }
        }

        public override void OnOrderEvent(OrderEvent orderEvent)
        {
            Debug($"Order Event: {orderEvent}");

            if (orderEvent.Status == OrderStatus.Filled)
            {
                _fillOrderEvents.Add(orderEvent);
            }
        }

        public override void OnEndOfAlgorithm()
        {
            if (!_orderPlaced)
            {
                throw new RegressionTestException("Spread order was not placed");
            }

            if (_fillOrderEvents.Count != 2)
            {
                throw new RegressionTestException($"Expected 2 fill order events, found {_fillOrderEvents.Count}");
            }

            // Verify atomic execution: all fills must have the same timestamp
            var fillTimes = _fillOrderEvents.Select(x => x.UtcTime).ToHashSet();
            if (fillTimes.Count != 1)
            {
                throw new RegressionTestException($"Expected all fill order events to have the same time, found {string.Join(", ", fillTimes)}");
            }

            // Verify fill quantities match leg ratios
            var btcFill = _fillOrderEvents.FirstOrDefault(x => x.Symbol == _btcusd);
            var ethFill = _fillOrderEvents.FirstOrDefault(x => x.Symbol == _ethusd);

            if (btcFill == null || ethFill == null)
            {
                throw new RegressionTestException("Missing fill events for BTC or ETH");
            }

            if (btcFill.FillQuantity != 1)
            {
                throw new RegressionTestException($"Expected BTC fill quantity of 1, found {btcFill.FillQuantity}");
            }

            if (ethFill.FillQuantity != -10)
            {
                throw new RegressionTestException($"Expected ETH fill quantity of -10, found {ethFill.FillQuantity}");
            }

            Debug("SpreadMarketOrder regression test passed successfully");
        }

        public bool CanRunLocally => true;

        public List<Language> Languages => new() { Language.CSharp };

        public long DataPoints => 48;

        public int AlgorithmHistoryDataPoints => 0;

        public AlgorithmStatus AlgorithmStatus => AlgorithmStatus.Completed;

        public Dictionary<string, string> ExpectedStatistics => new Dictionary<string, string>
        {
            {"Total Orders", "2"},
            {"Average Win", "0%"},
            {"Average Loss", "0%"},
            {"Compounding Annual Return", "0%"},
            {"Drawdown", "0%"},
            {"Expectancy", "0"},
            {"Start Equity", "100000"},
            {"End Equity", "100000"},
            {"Net Profit", "0%"},
            {"Sharpe Ratio", "0"},
            {"Sortino Ratio", "0"},
            {"Probabilistic Sharpe Ratio", "0%"},
            {"Loss Rate", "0%"},
            {"Win Rate", "0%"},
            {"Profit-Loss Ratio", "0"},
            {"Alpha", "0"},
            {"Beta", "0"},
            {"Annual Standard Deviation", "0"},
            {"Annual Variance", "0"},
            {"Information Ratio", "0"},
            {"Tracking Error", "0"},
            {"Treynor Ratio", "0"},
            {"Total Fees", "$0.00"},
            {"Estimated Strategy Capacity", "$0"},
            {"Lowest Capacity Asset", ""},
            {"Portfolio Turnover", "0%"},
            {"OrderListHash", "e5c94e70d1e8e8f7c888f5dcaa938856"}
        };
    }
}
