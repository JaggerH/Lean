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
    /// Grid-based arbitrage alpha model that generates ArbitrageInsight signals
    /// when spread crosses grid level entry/exit thresholds.
    ///
    /// This alpha model monitors TradingPair spreads and triggers:
    /// - Entry signals when spread crosses entry thresholds
    /// - Exit signals when spread crosses exit thresholds (for existing positions)
    ///
    /// The model handles both LONG_SPREAD and SHORT_SPREAD directions:
    /// - LONG_SPREAD: Long crypto, short stock (triggered when crypto is overpriced)
    /// - SHORT_SPREAD: Short crypto, long stock (triggered when stock is overpriced)
    /// </summary>
    public partial class GridArbitrageAlphaModel : IArbitrageAlphaModel
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
        /// Whether to allow multiple entry signals for the same grid level
        /// </summary>
        private readonly bool _allowMultipleEntriesPerLevel;

        /// <summary>
        /// Whether to require valid prices before generating signals
        /// </summary>
        private readonly bool _requireValidPrices;

        /// <summary>
        /// Tracks active insights by trading pair to prevent duplicates.
        /// Key: TradingPair.Key (e.g., "BTCUSD-MSTR")
        /// Value: HashSet of grid level natural keys (e.g., "-0.0200|LONG_SPREAD|ENTRY")
        /// </summary>
        private readonly Dictionary<string, HashSet<string>> _activeInsightsByPair;

        /// <summary>
        /// Creates a new GridArbitrageAlphaModel with the specified configuration.
        /// </summary>
        /// <param name="insightPeriod">How long insights remain valid (default: 5 minutes)</param>
        /// <param name="confidence">Confidence level for insights, 0-1 (default: 1.0)</param>
        /// <param name="allowMultipleEntriesPerLevel">Whether to allow multiple entries per grid level (default: false)</param>
        /// <param name="requireValidPrices">Whether to require valid prices before generating signals (default: true)</param>
        public GridArbitrageAlphaModel(
            TimeSpan? insightPeriod = null,
            double confidence = 1.0,
            bool allowMultipleEntriesPerLevel = false,
            bool requireValidPrices = true)
        {
            _insightPeriod = insightPeriod ?? TimeSpan.FromMinutes(5);
            _confidence = confidence;
            _allowMultipleEntriesPerLevel = allowMultipleEntriesPerLevel;
            _requireValidPrices = requireValidPrices;
            _activeInsightsByPair = new Dictionary<string, HashSet<string>>();

            if (_confidence < 0 || _confidence > 1)
            {
                throw new ArgumentOutOfRangeException(nameof(confidence),
                    "Confidence must be between 0 and 1");
            }
        }

        /// <summary>
        /// Updates this alpha model with the latest data from the arbitrage algorithm.
        /// This is called each time the algorithm receives data for subscribed securities.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance (provides access to TradingPairs)</param>
        /// <param name="data">The new data available</param>
        /// <returns>The new arbitrage insights generated</returns>
        public IEnumerable<ArbitrageInsight> Update(AIAlgorithm algorithm, Slice data)
        {
            var insights = new List<ArbitrageInsight>();

            // Track Slice update statistics (for optimization evaluation)
            TrackSliceUpdateStats(algorithm, data);

            // Update all trading pairs with latest market data
            algorithm.TradingPairs.UpdateAll();

            // Check each trading pair for grid triggers
            foreach (var pair in algorithm.TradingPairs)
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
                    var entryInsight = CheckEntrySignal(pair, levelPair, currentSpread);
                    if (entryInsight != null)
                    {
                        insights.Add(entryInsight);
                    }
                }

                // Check each active position for exit triggers
                // Use position.LevelPair instead of pair.LevelPairs for defensive exit checking
                foreach (var position in pair.GridPositions.Values)
                {
                    var exitInsight = CheckExitSignal(pair, position, currentSpread);
                    if (exitInsight != null)
                    {
                        insights.Add(exitInsight);
                    }
                }
            }

            // Set framework-managed fields for all insights
            foreach (var insight in insights)
            {
                insight.GeneratedTimeUtc = algorithm.UtcTime;
                insight.CloseTimeUtc = algorithm.UtcTime.Add(_insightPeriod);
                insight.SourceModel = nameof(GridArbitrageAlphaModel);
            }

            return insights;
        }

        /// <summary>
        /// Event fired when trading pairs are added or removed from the TradingPairManager.
        /// This allows the alpha model to initialize or clean up resources for trading pairs.
        /// </summary>
        /// <param name="algorithm">The AI algorithm instance</param>
        /// <param name="changes">The trading pair additions and removals</param>
        public void OnTradingPairsChanged(AIAlgorithm algorithm, TradingPairChanges changes)
        {
            // Clean up tracking for removed pairs
            foreach (var removedPair in changes.RemovedPairs)
            {
                string pairKey = removedPair.Key;
                if (_activeInsightsByPair.ContainsKey(pairKey))
                {
                    _activeInsightsByPair.Remove(pairKey);
                }
            }

            // Initialize tracking for added pairs
            foreach (var addedPair in changes.AddedPairs)
            {
                string pairKey = addedPair.Key;
                if (!_activeInsightsByPair.ContainsKey(pairKey))
                {
                    _activeInsightsByPair[pairKey] = new HashSet<string>();
                }
            }
        }

        /// <summary>
        /// Checks if the spread has crossed the entry threshold for a grid level.
        /// Generates an entry insight if triggered and no duplicate exists.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="levelPair">The grid level configuration</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <returns>ArbitrageInsight if entry triggered, null otherwise</returns>
        private ArbitrageInsight CheckEntrySignal(
            TradingPair pair,
            GridLevelPair levelPair,
            decimal currentSpread)
        {
            // Skip entry signals for pairs pending removal (allow graceful closure via exits only)
            if (pair.IsPendingRemoval)
            {
                return null;
            }

            // Determine spread direction from the entry level
            SpreadDirection direction = DetermineDirection(levelPair.Entry.Direction);

            // Check if spread has crossed the entry threshold
            bool triggered = false;
            if (direction == SpreadDirection.LongSpread)
            {
                // LONG_SPREAD: Entry when spread <= entry threshold (crypto overpriced)
                // Example: Entry at -2%, triggers when spread is -2.5%, -3%, etc.
                triggered = currentSpread <= levelPair.Entry.SpreadPct;
            }
            else if (direction == SpreadDirection.ShortSpread)
            {
                // SHORT_SPREAD: Entry when spread >= entry threshold (stock overpriced)
                // Example: Entry at +2%, triggers when spread is +2.5%, +3%, etc.
                triggered = currentSpread >= levelPair.Entry.SpreadPct;
            }

            if (!triggered)
            {
                return null;
            }

            // Check if we already have an active position at this level (avoid duplicate entries)
            if (!_allowMultipleEntriesPerLevel && pair.TryGetPosition(levelPair, out var position, out _))
            {
                if (position.Invested)
                {
                    return null;
                }
            }

            // Check if we already generated an insight for this level (avoid duplicate signals)
            string pairKey = pair.Key;
            string levelKey = levelPair.Entry.NaturalKey;
            if (!ShouldGenerateInsight(pairKey, levelKey))
            {
                return null;
            }

            // Generate entry insight
            var insight = new ArbitrageInsight(
                pair,
                levelPair,
                SignalType.Entry,
                direction,
                currentSpread,
                _insightPeriod,
                _confidence
            );

            // Track this insight to prevent duplicates
            TrackInsight(pairKey, levelKey);

            return insight;
        }

        /// <summary>
        /// Checks if the spread has crossed the exit threshold for an existing position.
        /// Uses the position's own LevelPair for defensive exit checking (independent of
        /// TradingPair.LevelPairs configuration changes).
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="position">The active grid position to check</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <returns>ArbitrageInsight if exit triggered, null otherwise</returns>
        private ArbitrageInsight CheckExitSignal(
            TradingPair pair,
            GridPosition position,
            decimal currentSpread)
        {
            // Only generate exit signals for invested positions
            if (!position.Invested)
            {
                return null;
            }

            // Check if spread crossed exit threshold using position's own LevelPair
            bool triggered = position.ShouldExit(currentSpread);

            if (!triggered)
            {
                return null;
            }

            // Check if we already generated an exit insight for this position
            string pairKey = pair.Key;
            string levelKey = position.LevelPair.Exit.NaturalKey;
            if (!ShouldGenerateInsight(pairKey, levelKey))
            {
                return null;
            }

            // Generate exit insight (direction is FlatSpread for closing)
            var insight = new ArbitrageInsight(
                pair,
                position.LevelPair,
                SignalType.Exit,
                SpreadDirection.FlatSpread,
                currentSpread,
                _insightPeriod,
                _confidence
            );

            // Track this insight to prevent duplicates
            TrackInsight(pairKey, levelKey);

            return insight;
        }

        /// <summary>
        /// Converts direction string to SpreadDirection enum.
        /// </summary>
        /// <param name="directionString">Direction string ("LONG_SPREAD" or "SHORT_SPREAD")</param>
        /// <returns>SpreadDirection enum value</returns>
        private SpreadDirection DetermineDirection(string directionString)
        {
            return directionString == "LONG_SPREAD"
                ? SpreadDirection.LongSpread
                : SpreadDirection.ShortSpread;
        }

        /// <summary>
        /// Checks if we should generate an insight for the given pair and level.
        /// Returns false if we've already generated an insight for this combination.
        /// </summary>
        /// <param name="pairKey">The trading pair key</param>
        /// <param name="levelKey">The grid level natural key</param>
        /// <returns>True if insight should be generated, false if duplicate</returns>
        private bool ShouldGenerateInsight(string pairKey, string levelKey)
        {
            if (!_activeInsightsByPair.TryGetValue(pairKey, out var activeLevels))
            {
                return true;
            }

            return !activeLevels.Contains(levelKey);
        }

        /// <summary>
        /// Tracks an insight to prevent duplicate generation.
        /// Adds the level key to the active insights set for the pair.
        /// </summary>
        /// <param name="pairKey">The trading pair key</param>
        /// <param name="levelKey">The grid level natural key</param>
        private void TrackInsight(string pairKey, string levelKey)
        {
            if (!_activeInsightsByPair.ContainsKey(pairKey))
            {
                _activeInsightsByPair[pairKey] = new HashSet<string>();
            }

            _activeInsightsByPair[pairKey].Add(levelKey);
        }
    }
}
