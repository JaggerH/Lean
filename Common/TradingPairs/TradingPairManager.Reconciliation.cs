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
        /// <summary>
        /// Lightweight execution snapshot for deduplication and time-based filtering.
        /// Serializable for potential persistence needs.
        /// </summary>
        [Serializable]
        internal class ExecutionSnapshot
        {
            /// <summary>
            /// Brokerage-provided execution ID
            /// </summary>
            public string ExecutionId { get; set; }

            /// <summary>
            /// Execution timestamp (UTC)
            /// </summary>
            public DateTime TimeUtc { get; set; }

            /// <summary>
            /// Market identifier (Symbol.ID.Market)
            /// </summary>
            public string Market { get; set; }
        }

        // Baseline账本: Symbol → 认可的差异数量 (LP - GP)
        private readonly Dictionary<Symbol, decimal> _baseline = new();

        /// <summary>
        /// 初始化 Baseline 账本
        /// </summary>
        /// <param name="portfolio">Portfolio 管理器</param>
        public void InitializeBaseline(SecurityPortfolioManager portfolio)
        {
            if (_lastFillTimeByMarket.Count == 0)
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
            else
            {
                // Consistency confirmed - safe to cleanup old execution records
                CleanupProcessedExecutions();
            }
            PersistState();
        }

        /// <summary>
        /// Performs reconciliation by querying execution history from brokerage and processing records.
        /// This is a self-contained method that determines the time range and queries executions automatically.
        /// Uses min(_lastFillTimeByMarket) - 5 minutes as query start time for comprehensive coverage.
        /// </summary>
        public void Reconciliation()
        {
            lock(_lock)
            {
                // 1. Determine query time range (use min - 5 minutes for buffer)
                var earliestTime = DateTime.UtcNow.AddMinutes(-30); // Default fallback
                if (_lastFillTimeByMarket.Any())
                {
                    earliestTime = _lastFillTimeByMarket.Values.Min().AddMinutes(-5);
                }

                var endTime = DateTime.UtcNow;

                Log.Trace($"TradingPairManager.Reconciliation: Querying executions from {earliestTime:yyyy-MM-dd HH:mm:ss} to {endTime:yyyy-MM-dd HH:mm:ss}");

                try
                {
                    // Use ExecutionHistoryProvider from AIAlgorithm interface (type-safe, no reflection)
                    if (_algorithm.ExecutionHistoryProvider == null)
                    {
                        Log.Trace("TradingPairManager.Reconciliation: ExecutionHistoryProvider not available");
                        return;
                    }

                    var executions = _algorithm.ExecutionHistoryProvider.GetExecutionHistory(earliestTime, endTime);

                    if (executions == null || executions.Count == 0)
                    {
                        Log.Trace("TradingPairManager.Reconciliation: No executions found");
                        return;
                    }

                    // 2. Time filtering + ExecutionId deduplication
                    var filteredExecutions = executions
                        .Where(e => ShouldProcessExecution(e))
                        .OrderBy(e => e.TimeUtc)
                        .ToList();

                    Log.Trace($"TradingPairManager.Reconciliation: Processing {filteredExecutions.Count}/{executions.Count} executions after filtering");

                    // 3. Process filtered executions
                    foreach (var execution in filteredExecutions)
                    {
                        try
                        {
                            var orderEvent = ConvertToOrderEvent(execution);
                            ProcessGridOrderEvent(orderEvent); // Includes deduplication logic
                        }
                        catch (Exception ex)
                        {
                            Log.Error($"TradingPairManager.Reconciliation: Error processing execution {execution.ExecutionId}: {ex.Message}");
                        }
                    }

                    Log.Trace($"TradingPairManager.Reconciliation: Successfully processed {filteredExecutions.Count} executions");
                }
                catch (Exception ex)
                {
                    Log.Error($"TradingPairManager.Reconciliation: Error querying executions: {ex.Message}");
                }
            }
        }

        /// <summary>
        /// Determines if an execution should be processed based on time filtering and ExecutionId deduplication.
        /// </summary>
        /// <param name="execution">The execution record to check</param>
        /// <returns>True if execution should be processed, false otherwise</returns>
        private bool ShouldProcessExecution(ExecutionRecord execution)
        {
            var market = execution.Symbol.ID.Market;

            // 1. ExecutionId deduplication (first layer)
            if (_processedExecutions.ContainsKey(execution.ExecutionId))
            {
                return false;
            }

            // 2. Time filtering (second layer)
            if (_lastFillTimeByMarket.TryGetValue(market, out var lastFillTime))
            {
                // execution.TimeUtc < lastFillTime: discard
                // execution.TimeUtc >= lastFillTime: keep (including time-equal cases, rely on ExecutionId dedup)
                if (execution.TimeUtc < lastFillTime)
                {
                    return false;
                }
            }

            return true;
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
                "Replayed from brokerage history"
            )
            {
                Ticket = ticket,
                ExecutionId = execution.ExecutionId
            };

            return orderEvent;
        }

        // Thread-safe virtual order ID generator (negative IDs)
        private static int _virtualOrderId = 0;
        private static int GetNextVirtualOrderId()
        {
            return System.Threading.Interlocked.Decrement(ref _virtualOrderId);
        }

        /// <summary>
        /// Cleans up old execution records from the processed executions cache.
        /// Removes executions with TimeUtc less than lastFillTime for each market, keeping time-equal ones.
        /// Only called after CompareBaseline confirms consistency.
        /// </summary>
        private void CleanupProcessedExecutions()
        {
            lock(_lock)
            {
                var toRemove = new List<string>();

                foreach (var kvp in _processedExecutions)
                {
                    var snapshot = kvp.Value;
                    var market = snapshot.Market;

                    if (_lastFillTimeByMarket.TryGetValue(market, out var lastFillTime))
                    {
                        // Remove executions with TimeUtc < lastFillTime
                        // Keep time-equal ones (may have concurrent orders not yet processed)
                        if (snapshot.TimeUtc < lastFillTime)
                        {
                            toRemove.Add(kvp.Key);
                        }
                    }
                }

                foreach (var executionId in toRemove)
                {
                    _processedExecutions.Remove(executionId);
                }

                if (toRemove.Count > 0)
                {
                    Log.Trace($"CleanupProcessedExecutions: Removed {toRemove.Count} old executions, remaining: {_processedExecutions.Count}");
                }
            }
        }

        /// <summary>
        /// Persists complete TradingPairManager state to ObjectStore with versioning.
        /// Saves 3 critical components: GridPositions, _lastFillTimeByMarket, _processedExecutions.
        /// </summary>
        private void PersistState()
        {
            try
            {
                var timestamp = DateTime.UtcNow;

                // 1. 扁平化收集所有 GridPositions（直接添加对象，无额外包装）
                var allGridPositions = new List<Grid.GridPosition>();
                foreach (var pair in GetAll())
                {
                    foreach (var position in pair.GridPositions.Values)
                    {
                        allGridPositions.Add(position);
                    }
                }

                // 2. 构建状态对象
                var stateData = new
                {
                    timestamp = timestamp,
                    version = "1.0",

                    // Component 1: 扁平化的 GridPositions 数组（GridPosition 已有完整 JsonProperty）
                    grid_positions = allGridPositions,

                    // Component 2: Last fill time by market
                    last_fill_time_by_market = _lastFillTimeByMarket.Select(kvp => new
                    {
                        market = kvp.Key,
                        last_fill_time = kvp.Value
                    }),

                    // Component 3: Processed executions (ExecutionId deduplication cache)
                    processed_executions = _processedExecutions.Select(kvp => new
                    {
                        execution_id = kvp.Key,
                        snapshot = new
                        {
                            execution_id = kvp.Value.ExecutionId,
                            time_utc = kvp.Value.TimeUtc,
                            market = kvp.Value.Market
                        }
                    })
                };

                var json = Newtonsoft.Json.JsonConvert.SerializeObject(stateData, Newtonsoft.Json.Formatting.Indented);

                // Save latest version
                var latestPath = "trade_data/trading_pair_manager/state";
                _algorithm.ObjectStore.Save(latestPath, json);

                // Save timestamped backup (for version history)
                var backupPath = $"trade_data/trading_pair_manager/backups/{timestamp:yyyyMMdd_HHmmss}";
                _algorithm.ObjectStore.Save(backupPath, json);

                Log.Trace($"Persisted TradingPairManager state: {allGridPositions.Count} positions, " +
                         $"{_lastFillTimeByMarket.Count} markets, {_processedExecutions.Count} executions at {timestamp}");
            }
            catch (Exception ex)
            {
                Log.Error($"Failed to persist TradingPairManager state: {ex.Message}");
            }
        }

        /// <summary>
        /// Restores complete TradingPairManager state from ObjectStore on algorithm startup.
        /// Restores 3 critical components: GridPositions, _lastFillTimeByMarket, _processedExecutions.
        /// </summary>
        public void RestoreState()
        {
            try
            {
                var path = "trade_data/trading_pair_manager/state";

                if (!_algorithm.ObjectStore.ContainsKey(path))
                {
                    Log.Trace("No saved state found for TradingPairManager - starting fresh");
                    return;
                }

                var json = _algorithm.ObjectStore.Read(path);
                var stateData = Newtonsoft.Json.JsonConvert.DeserializeObject<dynamic>(json);

                var timestamp = stateData.timestamp;
                Log.Trace($"Restoring TradingPairManager state from {timestamp}");

                // Restore Component 1: GridPositions
                // Use AddPair + EncodeGridTag to rebuild structure from flat array
                foreach (var posData in stateData.grid_positions)
                {
                    // 1. Deserialize GridPosition directly (GridPosition has JsonConstructor)
                    var position = Newtonsoft.Json.JsonConvert.DeserializeObject<Grid.GridPosition>(
                        posData.ToString()
                    );

                    // 2. Ensure TradingPair exists (AddPair is idempotent, handles duplicates)
                    var pair = AddPair(position.Leg1Symbol, position.Leg2Symbol);

                    // 3. Get position tag using Tag property
                    var tag = position.Tag;

                    // 4. Restore parent reference (GridPosition needs TradingPair for Invested property)
                    position.SetTradingPair(pair);

                    // 5. Add to pair's GridPositions dictionary
                    pair.GridPositions[tag] = position;
                }

                // Restore Component 2: _lastFillTimeByMarket
                _lastFillTimeByMarket.Clear();
                foreach (var marketData in stateData.last_fill_time_by_market)
                {
                    string market = marketData.market;
                    DateTime lastFillTime = marketData.last_fill_time;
                    _lastFillTimeByMarket[market] = lastFillTime;
                }

                // Restore Component 3: _processedExecutions
                _processedExecutions.Clear();
                foreach (var execData in stateData.processed_executions)
                {
                    string executionId = execData.execution_id;
                    var snapshot = new ExecutionSnapshot
                    {
                        ExecutionId = execData.snapshot.execution_id,
                        TimeUtc = execData.snapshot.time_utc,
                        Market = execData.snapshot.market
                    };
                    _processedExecutions[executionId] = snapshot;
                }

                var totalPositions = GetAll().Sum(p => p.GridPositions.Count);
                Log.Trace($"Restored TradingPairManager state: {totalPositions} positions, " +
                         $"{_lastFillTimeByMarket.Count} markets, {_processedExecutions.Count} executions from {timestamp}");
            }
            catch (Exception ex)
            {
                Log.Error($"Failed to restore TradingPairManager state: {ex.Message}");
            }
        }
    }
}
