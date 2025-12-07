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
using QuantConnect.Data;
using QuantConnect.Interfaces;
using QuantConnect.TradingPairs;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Grid-based arbitrage alpha model that generates standard Framework Insight signals
    /// when spread crosses grid level entry/exit thresholds.
    ///
    /// This alpha model generates a single Insight for Leg1 (crypto) with Tag-based pairing.
    /// Each signal generates:
    /// - 1 Insight (Leg1 only, crypto symbol)
    /// - Tag containing grid configuration and Leg2 info (using TradingPairManager.EncodeGridTag)
    /// - PCM decodes the Tag to generate paired PortfolioTargets for both legs
    ///
    /// The model handles both LONG_SPREAD and SHORT_SPREAD directions:
    /// - LONG_SPREAD: Long crypto (Up), short stock (Down)
    /// - SHORT_SPREAD: Short crypto (Down), long stock (Up)
    /// </summary>
    public partial class ArbitrageAlphaModel : AlphaModel, IArbitrageAlphaModel
    {
        /// <summary>
        /// How long each generated insight remains valid
        /// </summary>
        private readonly TimeSpan _insightPeriod;

        /// <summary>
        /// Confidence level for generated insights (0-1 scale)
        /// </summary>
        private readonly double _confidence;

        /// <summary>
        /// Whether to require valid prices before generating signals
        /// </summary>
        private readonly bool _requireValidPrices;

        /// <summary>
        /// Grid level templates for auto-configuration by pair type.
        /// Key: pairType (e.g., "crypto_stock", "spot_future")
        /// Value: Factory functions that create GridLevelPair instances
        /// </summary>
        private readonly Dictionary<string, List<Func<GridLevelPair>>> _gridTemplates;

        /// <summary>
        /// Creates a new ArbitrageAlphaModel with the specified configuration.
        /// </summary>
        /// <param name="insightPeriod">How long insights remain valid (default: 5 minutes)</param>
        /// <param name="confidence">Confidence level for insights, 0-1 (default: 1.0)</param>
        /// <param name="requireValidPrices">Whether to require valid prices before generating signals (default: true)</param>
        /// <param name="gridTemplates">Optional custom grid templates by pair type. Merges with or overrides default templates.</param>
        public ArbitrageAlphaModel(
            TimeSpan? insightPeriod = null,
            double confidence = 1.0,
            bool requireValidPrices = true,
            Dictionary<string, List<Func<GridLevelPair>>> gridTemplates = null)
        {
            _insightPeriod = insightPeriod ?? TimeSpan.FromMinutes(5);
            _confidence = confidence;
            _requireValidPrices = requireValidPrices;

            if (_confidence < 0 || _confidence > 1)
            {
                throw new ArgumentOutOfRangeException(nameof(confidence),
                    "Confidence must be between 0 and 1");
            }

            // Initialize with default templates
            _gridTemplates = CreateDefaultTemplates();

            // Merge/override with user-provided templates
            if (gridTemplates != null)
            {
                foreach (var kvp in gridTemplates)
                {
                    _gridTemplates[kvp.Key] = kvp.Value;
                }
            }

            Name = nameof(ArbitrageAlphaModel);
        }

        /// <summary>
        /// Updates this alpha model with the latest data from the algorithm.
        /// This is called each time the algorithm receives data for subscribed securities.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="data">The new data available</param>
        /// <returns>The new insights generated (single Leg1 insights with Tag)</returns>
        public override IEnumerable<Insight> Update(QCAlgorithm algorithm, Slice data)
        {
            // Cast to AIAlgorithm to access TradingPairs
            var aiAlgo = algorithm as AIAlgorithm;

            // Track Slice update statistics (for optimization evaluation)
            TrackSliceUpdateStats(aiAlgo, data);

            // Update all trading pairs with latest market data
            aiAlgo.TradingPairs.UpdateAll();

            // Track spread percentage statistics (for debugging signal generation)
            TrackSpreadStats(aiAlgo);

            // Check each trading pair for grid triggers
            foreach (var pair in aiAlgo.TradingPairs)
            {
                // Skip if prices are invalid and we require valid prices
                if (_requireValidPrices && !pair.HasValidPrices)
                {
                    continue;
                }

                // Get current spread for this pair
                decimal currentSpread = pair.TheoreticalSpread;

                // Check each grid level for entry triggers
                foreach (var levelPair in pair.LevelPairs)
                {
                    var entryInsights = CheckEntrySignal(pair, levelPair, currentSpread, aiAlgo);
                    foreach (var insight in entryInsights)
                    {
                        yield return insight;
                    }
                }

                // Check each active position for exit triggers
                foreach (var position in pair.GridPositions.Values)
                {
                    var exitInsights = CheckExitSignal(pair, position, currentSpread, aiAlgo);
                    foreach (var insight in exitInsights)
                    {
                        yield return insight;
                    }
                }
            }
        }

        /// <summary>
        /// Checks if the spread has crossed the entry threshold for a grid level.
        /// Generates a single insight for Leg1 if triggered and no duplicate exists.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="levelPair">The grid level configuration</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Enumerable of single Leg1 Insight (with Tag) if entry triggered, empty otherwise</returns>
        private IEnumerable<Insight> CheckEntrySignal(
            TradingPair pair,
            GridLevelPair levelPair,
            decimal currentSpread,
            AIAlgorithm algorithm)
        {
            // Skip entry signals for pairs pending removal
            if (pair.IsPendingRemoval)
            {
                yield break;
            }

            // Determine spread direction from the entry level
            SpreadDirection direction = DetermineDirection(levelPair.Entry.Direction);

            // Check if spread has crossed the entry threshold
            bool triggered = false;
            if (direction == SpreadDirection.LongSpread)
            {
                // LONG_SPREAD: Entry when spread <= entry threshold (crypto overpriced)
                triggered = currentSpread <= levelPair.Entry.SpreadPct;
            }
            else if (direction == SpreadDirection.ShortSpread)
            {
                // SHORT_SPREAD: Entry when spread >= entry threshold (stock overpriced)
                triggered = currentSpread >= levelPair.Entry.SpreadPct;
            }

            if (!triggered)
            {
                yield break;
            }

            // Check if we already generated an insight for this level
            if (!ShouldGenerateInsight((QCAlgorithm)algorithm, pair, levelPair.Entry))
            {
                yield break;
            }

            // Generate single insight for Leg1 (PCM will generate paired targets)
            var insight = GenerateSingleInsight(
                pair,
                levelPair,
                direction,
                SignalType.Entry,
                algorithm);

            yield return insight;
        }

        /// <summary>
        /// Checks if the spread has crossed the exit threshold for an existing position.
        /// Uses the position's own LevelPair for defensive exit checking.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="position">The active grid position to check</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Enumerable of single Leg1 Insight (with Tag) if exit triggered, empty otherwise</returns>
        private IEnumerable<Insight> CheckExitSignal(
            TradingPair pair,
            GridPosition position,
            decimal currentSpread,
            AIAlgorithm algorithm)
        {
            // Check if spread crossed exit threshold
            bool triggered = position.ShouldExit(currentSpread);

            if (!triggered)
            {
                yield break;
            }

            // Check if we already generated an exit insight for this position
            if (!ShouldGenerateInsight((QCAlgorithm)algorithm, pair, position.LevelPair.Exit))
            {
                yield break;
            }

            // Generate single insight for exit (Flat direction, PCM will generate paired targets)
            var insight = GenerateSingleInsight(
                pair,
                position.LevelPair,
                SpreadDirection.FlatSpread,
                SignalType.Exit,
                algorithm);

            yield return insight;
        }

        /// <summary>
        /// Generates a single GridInsight for Leg1 (crypto) only.
        /// Uses TradingPairManager.EncodeGridTag() to create the Tag containing pairing information.
        /// PCM will decode the Tag to generate paired PortfolioTargets for both legs.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="levelPair">The grid level configuration</param>
        /// <param name="direction">The spread direction</param>
        /// <param name="signalType">Entry or Exit signal type</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Single GridInsight for Leg1 with Tag containing pairing info</returns>
        private GridInsight GenerateSingleInsight(
            TradingPair pair,
            GridLevelPair levelPair,
            SpreadDirection direction,
            SignalType signalType,
            AIAlgorithm algorithm)
        {
            // Map SpreadDirection to InsightDirection for Leg1 only
            var leg1Dir = direction switch
            {
                SpreadDirection.LongSpread => InsightDirection.Up,
                SpreadDirection.ShortSpread => InsightDirection.Down,
                SpreadDirection.FlatSpread => InsightDirection.Flat,
                _ => throw new ArgumentException($"Unknown SpreadDirection: {direction}")
            };

            // Encode tag using existing TradingPairManager method
            var tag = TradingPairManager.EncodeGridTag(
                pair.Leg1Symbol,
                pair.Leg2Symbol,
                levelPair);

            // Determine which GridLevel to use based on signal type
            GridLevel level = signalType == SignalType.Entry ? levelPair.Entry : levelPair.Exit;

            // Create GridInsight for Leg1 (Crypto) only
            var insight = new GridInsight(
                pair.Leg1Symbol,
                _insightPeriod,
                leg1Dir,
                level,
                _confidence,
                tag)
            {
                // Set framework-managed fields
                GeneratedTimeUtc = algorithm.UtcTime,
                CloseTimeUtc = algorithm.UtcTime.Add(_insightPeriod),
                SourceModel = Name
            };

            return insight;
        }

        /// <summary>
        /// Converts direction string to SpreadDirection enum.
        /// </summary>
        /// <param name="directionString">Direction string ("LONG_SPREAD" or "SHORT_SPREAD")</param>
        /// <returns>SpreadDirection enum value</returns>
        private static SpreadDirection DetermineDirection(string directionString)
        {
            return directionString == "LONG_SPREAD"
                ? SpreadDirection.LongSpread
                : SpreadDirection.ShortSpread;
        }

        /// <summary>
        /// Checks if we should generate an insight for the given pair and level.
        /// Returns false if we've already generated an insight for this combination.
        /// Queries the framework's InsightCollection instead of maintaining separate tracking.
        ///
        /// Note: Since we now generate only Leg1 insights, we only check for Leg1Symbol duplicates.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="pair">The trading pair</param>
        /// <param name="targetLevel">The grid level to check</param>
        /// <returns>True if insight should be generated, false if duplicate</returns>
        private bool ShouldGenerateInsight(
            QCAlgorithm algorithm,
            TradingPair pair,
            GridLevel targetLevel)
        {
            // Get all active insights from framework
            var activeInsights = algorithm.Insights.GetActiveInsights(algorithm.UtcTime);

            // Filter for GridInsights related to Leg1Symbol and level
            // We only generate Leg1 insights now, so check both Leg1Symbol and Level
            var duplicates = activeInsights
                .OfType<GridInsight>()
                .Where(gi =>
                    // Match by both Symbol and GridLevel (uses value equality comparison)
                    gi.Symbol == pair.Leg1Symbol &&
                    gi.Level == targetLevel)
                .ToList();

            // Allow generation if no duplicates exist
            return duplicates.Count == 0;
        }

        /// <summary>
        /// Creates default grid level templates for common pair types.
        /// These templates can be overridden by passing custom templates to the constructor.
        /// </summary>
        /// <returns>Dictionary of default grid templates by pair type</returns>
        private Dictionary<string, List<Func<GridLevelPair>>> CreateDefaultTemplates()
        {
            return new Dictionary<string, List<Func<GridLevelPair>>>
            {
                // crypto_stock: Cryptocurrency vs Stock pairs
                // Typical for tokenized stock arbitrage
                ["crypto_stock"] = new List<Func<GridLevelPair>>
                {
                    // LONG_SPREAD: Long crypto when underpriced vs stock
                    () => new GridLevelPair(
                        entrySpreadPct: -0.02m,      // Entry at -2% spread
                        exitSpreadPct: 0.01m,         // Exit at +1% spread
                        direction: "LONG_SPREAD",
                        positionSizePct: 0.5m         // 50% position size
                    ),
                    // SHORT_SPREAD: Short crypto when overpriced vs stock
                    () => new GridLevelPair(
                        entrySpreadPct: 0.03m,        // Entry at +3% spread
                        exitSpreadPct: -0.005m,       // Exit at -0.5% spread
                        direction: "SHORT_SPREAD",
                        positionSizePct: 0.5m         // 50% position size
                    )
                },

                // spot_future: Spot vs Futures pairs
                // Typical for basis trading
                ["spot_future"] = new List<Func<GridLevelPair>>
                {
                    // LONG_SPREAD: Long spot when basis is negative
                    () => new GridLevelPair(
                        entrySpreadPct: -0.015m,      // Entry at -1.5% basis
                        exitSpreadPct: 0.008m,        // Exit at +0.8% basis
                        direction: "LONG_SPREAD",
                        positionSizePct: 0.3m         // 30% position size
                    ),
                    // SHORT_SPREAD: Short spot when basis is positive
                    () => new GridLevelPair(
                        entrySpreadPct: 0.025m,       // Entry at +2.5% basis
                        exitSpreadPct: -0.008m,       // Exit at -0.8% basis
                        direction: "SHORT_SPREAD",
                        positionSizePct: 0.3m         // 30% position size
                    )
                }

                // Note: "spread" type has no default template
                // Users must manually configure grid levels for this generic type
            };
        }

        /// <summary>
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// Auto-configures grid levels for added pairs based on their pairType if a template exists.
        /// Cancels active insights for removed pairs.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        public void OnTradingPairsChanged(IAlgorithm algorithm, TradingPairChanges changes)
        {
            // Auto-configure grid levels for newly added pairs
            foreach (var addedPair in changes.AddedPairs)
            {
                // Check if we have a template for this pair type
                if (_gridTemplates.TryGetValue(addedPair.PairType, out var factories))
                {
                    // Apply each grid level template
                    foreach (var factory in factories)
                    {
                        var levelPair = factory(); // Create new instance
                        addedPair.AddLevelPair(levelPair);
                    }

                    algorithm.Debug($"ArbitrageAlphaModel: Auto-configured {factories.Count} grid level(s) for " +
                                  $"{addedPair.Key} (type: {addedPair.PairType})");
                }
                // If no template exists (e.g., "spread" type), user must configure manually
            }

            // Cancel active insights for removed pairs
            foreach (var removedPair in changes.RemovedPairs)
            {
                var insightsToCancel = algorithm.Insights
                    .GetActiveInsights(algorithm.UtcTime)
                    .OfType<GridInsight>()
                    .Where(gi => gi.Symbol == removedPair.Leg1Symbol ||
                                 gi.Symbol == removedPair.Leg2Symbol)
                    .Cast<Insight>()
                    .ToList();

                if (insightsToCancel.Any())
                {
                    algorithm.Insights.Cancel(insightsToCancel);
                }
            }
        }
    }
}
