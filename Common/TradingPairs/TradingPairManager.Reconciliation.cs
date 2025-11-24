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
using System.Linq;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Orders.Fees;
using QuantConnect.Securities;
using QuantConnect.Util;

namespace QuantConnect.TradingPairs
{
    public partial class TradingPairManager
    {
        // Baseline账本: Symbol → 认可的差异数量 (LP - GP)
        private readonly Dictionary<Symbol, decimal> _baseline = new();

        // 每个市场的最新OrderEvent时间（用于确定回放时间窗口）
        private readonly Dictionary<string, DateTime> _lastOrderEventTime = new();

        /// <summary>
        /// 初始化 Baseline 账本
        /// </summary>
        /// <param name="portfolio">Portfolio 管理器</param>
        public void InitializeBaseline(SecurityPortfolioManager portfolio)
        {
            if (_lastOrderEventTime.Count == 0)
            {
                _baseline.Clear();
                var calculated = CalculateBaseline(portfolio);
                foreach (var kvp in calculated)
                {
                    _baseline[kvp.Key] = kvp.Value;
                }
            }
        }

        /// <summary>
        /// 计算 Baseline (LP - GP)
        /// </summary>
        private Dictionary<Symbol, decimal> CalculateBaseline(SecurityPortfolioManager portfolio)
        {
            var gp = AggregateGridPositions();

            return portfolio.Keys.Union(gp.Keys)
                .Select(symbol => new
                {
                    Symbol = symbol,
                    Diff = (portfolio.TryGetValue(symbol, out var holding) ? holding.Quantity : 0m) -
                           LinqExtensions.GetValueOrDefault(gp, symbol, 0m)
                })
                .Where(x => x.Diff != 0m)
                .ToDictionary(x => x.Symbol, x => x.Diff);
        }

        /// <summary>
        /// 聚合所有 GridPosition 的持仓
        /// </summary>
        private Dictionary<Symbol, decimal> AggregateGridPositions()
        {
            var result = new Dictionary<Symbol, decimal>();

            foreach (var pair in GetAll())
            {
                foreach (var position in pair.GridPositions.Values)
                {
                    if (!result.ContainsKey(position.Leg1Symbol))
                        result[position.Leg1Symbol] = 0m;
                    result[position.Leg1Symbol] += position.Leg1Quantity;

                    if (!result.ContainsKey(position.Leg2Symbol))
                        result[position.Leg2Symbol] = 0m;
                    result[position.Leg2Symbol] += position.Leg2Quantity;
                }
            }

            return result;
        }

        /// <summary>
        /// 对比 Baseline 与当前差异，发现不一致时触发对账
        /// </summary>
        /// <param name="portfolio">Portfolio 管理器</param>
        public void CompareBaseline(SecurityPortfolioManager portfolio)
        {
            var currentDiff = CalculateBaseline(portfolio);
            var allSymbols = _baseline.Keys.Union(currentDiff.Keys);
            var hasDiscrepancies = false;

            foreach (var symbol in allSymbols)
            {
                var baselineValue = LinqExtensions.GetValueOrDefault(_baseline, symbol, 0m);
                var currentValue = LinqExtensions.GetValueOrDefault(currentDiff, symbol, 0m);

                if (baselineValue != currentValue)
                {
                    Log.Trace($"Baseline discrepancy detected: {symbol}, " +
                            $"Baseline={baselineValue}, Current={currentValue}, " +
                            $"Diff={currentValue - baselineValue}");
                    hasDiscrepancies = true;
                }
            }

            if (hasDiscrepancies)
            {
                Reconciliation();
            }
        }

        /// <summary>
        /// Performs reconciliation by querying execution history from brokerage and processing records.
        /// This is a self-contained method that determines the time range and queries executions automatically.
        /// </summary>
        public void Reconciliation()
        {
            // Determine query time range
            var earliestTime = DateTime.UtcNow.AddMinutes(-30); // Default to last 30 minutes
            if (_lastOrderEventTime.Any())
            {
                var minTime = _lastOrderEventTime.Values.Min();
                if (minTime < earliestTime)
                {
                    earliestTime = minTime;
                }
            }

            var endTime = DateTime.UtcNow;

            Log.Trace($"TradingPairManager.Reconciliation: Querying executions from {earliestTime:yyyy-MM-dd HH:mm:ss} to {endTime:yyyy-MM-dd HH:mm:ss}");

            try
            {
                // Use ExecutionHistoryProvider from AIAlgorithm interface (type-safe, no reflection)
                if (_algorithm.ExecutionHistoryProvider == null)
                {
                    Log.Trace("TradingPairManager.Reconciliation: ExecutionHistoryProvider not set on algorithm");
                    return;
                }

                var executions = _algorithm.ExecutionHistoryProvider.GetExecutionHistory(earliestTime, endTime);

                if (executions == null || executions.Count == 0)
                {
                    Log.Trace("TradingPairManager.Reconciliation: No executions found");
                    return;
                }

                Log.Trace($"TradingPairManager.Reconciliation: Processing {executions.Count} execution records");

                // Sort by time
                var sortedExecutions = executions.OrderBy(e => e.TimeUtc).ToList();

                // Process each execution
                foreach (var execution in sortedExecutions)
                {
                    try
                    {
                        var orderEvent = ConvertToOrderEvent(execution);
                        ProcessGridOrderEvent(orderEvent);

                        // Update last order event time for this market
                        var market = execution.Symbol.ID.Market;
                        if (!_lastOrderEventTime.ContainsKey(market) || _lastOrderEventTime[market] < execution.TimeUtc)
                        {
                            _lastOrderEventTime[market] = execution.TimeUtc;
                        }
                    }
                    catch (Exception ex)
                    {
                        Log.Error($"TradingPairManager.Reconciliation: Error processing execution {execution.ExecutionId}: {ex.Message}");
                    }
                }

                Log.Trace($"TradingPairManager.Reconciliation: Successfully processed {executions.Count} executions");
            }
            catch (Exception ex)
            {
                Log.Error($"TradingPairManager.Reconciliation: Error querying executions: {ex.Message}");
            }
        }

        /// <summary>
        /// 将 ExecutionRecord 转换为 OrderEvent
        /// </summary>
        private OrderEvent ConvertToOrderEvent(ExecutionRecord execution)
        {
            // Create virtual SubmitOrderRequest with Tag
            var request = new SubmitOrderRequest(
                OrderType.Market,
                execution.Symbol.SecurityType,
                execution.Symbol,
                execution.Quantity,
                0,
                0,
                execution.TimeUtc,
                execution.Tag ?? string.Empty
            );

            // Create virtual OrderTicket (transactionManager=null is safe, no registration)
            var ticket = new OrderTicket(null, request);

            // Create OrderEvent
            var orderEvent = new OrderEvent(
                GetNextVirtualOrderId(),
                execution.Symbol,
                execution.TimeUtc,
                OrderStatus.Filled,
                execution.Quantity > 0 ? OrderDirection.Buy : OrderDirection.Sell,
                execution.Price,
                execution.Quantity,
                new OrderFee(new CashAmount(execution.Fee, execution.FeeCurrency)),
                $"Replayed from execution {execution.ExecutionId}"
            )
            {
                Ticket = ticket
            };

            return orderEvent;
        }

        // Thread-safe virtual order ID generator (negative IDs)
        private static int _virtualOrderId = 0;
        private static int GetNextVirtualOrderId()
        {
            return System.Threading.Interlocked.Decrement(ref _virtualOrderId);
        }
    }
}
