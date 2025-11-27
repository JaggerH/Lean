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
    /// This alpha model uses Insight.Group() to associate paired legs (crypto + stock)
    /// for each arbitrage opportunity. Each signal generates:
    /// - 2 Insights (one per leg, grouped by GroupId)
    /// - Tag containing grid configuration (using TradingPairManager.EncodeGridTag)
    ///
    /// The model handles both LONG_SPREAD and SHORT_SPREAD directions:
    /// - LONG_SPREAD: Long crypto (Up), short stock (Down)
    /// - SHORT_SPREAD: Short crypto (Down), long stock (Up)
    /// </summary>
    public partial class InsightGridArbitrageAlphaModel : AlphaModel
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
        /// Creates a new InsightGridArbitrageAlphaModel with the specified configuration.
        /// </summary>
        /// <param name="insightPeriod">How long insights remain valid (default: 5 minutes)</param>
        /// <param name="confidence">Confidence level for insights, 0-1 (default: 1.0)</param>
        /// <param name="allowMultipleEntriesPerLevel">Whether to allow multiple entries per grid level (default: false)</param>
        /// <param name="requireValidPrices">Whether to require valid prices before generating signals (default: true)</param>
        public InsightGridArbitrageAlphaModel(
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

            Name = nameof(InsightGridArbitrageAlphaModel);
        }

        /// <summary>
        /// Updates this alpha model with the latest data from the algorithm.
        /// This is called each time the algorithm receives data for subscribed securities.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="data">The new data available</param>
        /// <returns>The new insights generated (paired insights with GroupId)</returns>
        public override IEnumerable<Insight> Update(QCAlgorithm algorithm, Slice data)
        {
            // Cast to AIAlgorithm to access TradingPairs
            var aiAlgo = algorithm as AIAlgorithm;
            if (aiAlgo == null)
            {
                throw new InvalidOperationException(
                    $"{nameof(InsightGridArbitrageAlphaModel)} requires an AIAlgorithm instance");
            }

            // Track Slice update statistics (for optimization evaluation)
            TrackSliceUpdateStats(aiAlgo, data);

            // Update all trading pairs with latest market data
            aiAlgo.TradingPairs.UpdateAll();

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
        /// Event fired each time the we add/remove securities from the data feed.
        /// Maps to TradingPairChanges for managing pair-specific tracking.
        /// </summary>
        /// <param name="algorithm">The algorithm instance that experienced the change in securities</param>
        /// <param name="changes">The security additions and removals from the algorithm</param>
        public override void OnSecuritiesChanged(QCAlgorithm algorithm, Data.UniverseSelection.SecurityChanges changes)
        {
            // Note: This is called for individual security changes.
            // For TradingPair-level changes, AIAlgorithm should call OnTradingPairsChanged directly
            // if needed, or we can infer changes from added/removed securities.
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
        /// Generates a pair of insights (one per leg) if triggered and no duplicate exists.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="levelPair">The grid level configuration</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Enumerable of paired Insights (with GroupId) if entry triggered, empty otherwise</returns>
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

            // Check if we already have an active position at this level
            if (!_allowMultipleEntriesPerLevel && pair.TryGetPosition(levelPair, out var position, out _))
            {
                if (position.Invested)
                {
                    yield break;
                }
            }

            // Check if we already generated an insight for this level
            string pairKey = pair.Key;
            string levelKey = levelPair.Entry.NaturalKey;
            if (!ShouldGenerateInsight(pairKey, levelKey))
            {
                yield break;
            }

            // Generate paired insights with GroupId
            var pairedInsights = GeneratePairedInsights(
                pair,
                levelPair,
                direction,
                SignalType.Entry,
                algorithm);

            // Track this insight to prevent duplicates
            TrackInsight(pairKey, levelKey);

            foreach (var insight in pairedInsights)
            {
                yield return insight;
            }
        }

        /// <summary>
        /// Checks if the spread has crossed the exit threshold for an existing position.
        /// Uses the position's own LevelPair for defensive exit checking.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="position">The active grid position to check</param>
        /// <param name="currentSpread">The current spread value</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Enumerable of paired Insights (with GroupId) if exit triggered, empty otherwise</returns>
        private IEnumerable<Insight> CheckExitSignal(
            TradingPair pair,
            GridPosition position,
            decimal currentSpread,
            AIAlgorithm algorithm)
        {
            // Only generate exit signals for invested positions
            if (!position.Invested)
            {
                yield break;
            }

            // Check if spread crossed exit threshold
            bool triggered = position.ShouldExit(currentSpread);

            if (!triggered)
            {
                yield break;
            }

            // Check if we already generated an exit insight for this position
            string pairKey = pair.Key;
            string levelKey = position.LevelPair.Exit.NaturalKey;
            if (!ShouldGenerateInsight(pairKey, levelKey))
            {
                yield break;
            }

            // Generate paired insights for exit (Flat direction)
            var pairedInsights = GeneratePairedInsights(
                pair,
                position.LevelPair,
                SpreadDirection.FlatSpread,
                SignalType.Exit,
                algorithm);

            // Track this insight to prevent duplicates
            TrackInsight(pairKey, levelKey);

            foreach (var insight in pairedInsights)
            {
                yield return insight;
            }
        }

        /// <summary>
        /// Generates a pair of Insights (one per leg) and associates them using Insight.Group().
        /// Uses TradingPairManager.EncodeGridTag() to create the Tag for both insights.
        /// </summary>
        /// <param name="pair">The trading pair</param>
        /// <param name="levelPair">The grid level configuration</param>
        /// <param name="direction">The spread direction</param>
        /// <param name="signalType">Entry or Exit signal type</param>
        /// <param name="algorithm">The algorithm instance</param>
        /// <returns>Enumerable of paired Insights with shared GroupId and Tag</returns>
        private IEnumerable<Insight> GeneratePairedInsights(
            TradingPair pair,
            GridLevelPair levelPair,
            SpreadDirection direction,
            SignalType signalType,
            AIAlgorithm algorithm)
        {
            // Map SpreadDirection to InsightDirection for each leg
            var (leg1Dir, leg2Dir) = MapSpreadDirectionToInsightDirection(direction);

            // Encode tag using existing TradingPairManager method
            var tag = TradingPairManager.EncodeGridTag(
                pair.Leg1Symbol,
                pair.Leg2Symbol,
                levelPair);

            // Create Insight for Leg1 (Crypto)
            var leg1Insight = Insight.Price(
                pair.Leg1Symbol,
                _insightPeriod,
                leg1Dir,
                confidence: _confidence,
                tag: tag);

            // Create Insight for Leg2 (Stock)
            var leg2Insight = Insight.Price(
                pair.Leg2Symbol,
                _insightPeriod,
                leg2Dir,
                confidence: _confidence,
                tag: tag);

            var GeneratedTimeUtc = algorithm.UtcTime;
            var CloseTimeUtc = algorithm.UtcTime.Add(_insightPeriod);

            // Set framework-managed fields
            leg1Insight.GeneratedTimeUtc = GeneratedTimeUtc;
            leg1Insight.CloseTimeUtc = CloseTimeUtc;
            leg1Insight.SourceModel = Name;

            leg2Insight.GeneratedTimeUtc = GeneratedTimeUtc;
            leg2Insight.CloseTimeUtc = CloseTimeUtc;
            leg2Insight.SourceModel = Name;

            // Group the insights together (sets shared GroupId)
            return Insight.Group(leg1Insight, leg2Insight);
        }

        /// <summary>
        /// Maps SpreadDirection to InsightDirection for each leg.
        /// </summary>
        /// <param name="direction">The spread direction</param>
        /// <returns>Tuple of (Leg1Direction, Leg2Direction)</returns>
        private (InsightDirection, InsightDirection) MapSpreadDirectionToInsightDirection(
            SpreadDirection direction)
        {
            switch (direction)
            {
                case SpreadDirection.LongSpread:
                    // LONG_SPREAD: Buy crypto (Up), Sell stock (Down)
                    return (InsightDirection.Up, InsightDirection.Down);

                case SpreadDirection.ShortSpread:
                    // SHORT_SPREAD: Sell crypto (Down), Buy stock (Up)
                    return (InsightDirection.Down, InsightDirection.Up);

                case SpreadDirection.FlatSpread:
                    // Exit: Close both legs (Flat)
                    return (InsightDirection.Flat, InsightDirection.Flat);

                default:
                    throw new ArgumentException($"Unknown SpreadDirection: {direction}");
            }
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
