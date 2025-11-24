using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace QuantConnect.Algorithm.Framework.Alphas
{
    /// <summary>
    /// Thread-safe collection for managing ArbitrageInsights
    /// </summary>
    public class ArbitrageInsightCollection : IEnumerable<ArbitrageInsight>
    {
        private readonly Dictionary<string, ArbitrageInsight> _activeInsights;
        private readonly List<ArbitrageInsight> _allInsights;
        private readonly object _lock = new object();

        /// <summary>
        /// Number of currently active (non-expired) insights
        /// </summary>
        public int Count
        {
            get
            {
                lock (_lock)
                {
                    return _activeInsights.Count;
                }
            }
        }

        /// <summary>
        /// Total number of insights ever added to this collection (including expired ones)
        /// </summary>
        public int TotalCount
        {
            get
            {
                lock (_lock)
                {
                    return _allInsights.Count;
                }
            }
        }

        /// <summary>
        /// Creates a new empty ArbitrageInsightCollection
        /// </summary>
        public ArbitrageInsightCollection()
        {
            _activeInsights = new Dictionary<string, ArbitrageInsight>();
            _allInsights = new List<ArbitrageInsight>();
        }

        /// <summary>
        /// Adds an insight to the collection
        /// </summary>
        /// <param name="insight">The insight to add</param>
        public void Add(ArbitrageInsight insight)
        {
            if (insight == null)
            {
                throw new ArgumentNullException(nameof(insight));
            }

            lock (_lock)
            {
                var key = GetKey(insight.TradingPair, insight.LevelPair);
                _activeInsights[key] = insight;  // Overwrites if exists
                _allInsights.Add(insight);
            }
        }

        /// <summary>
        /// Adds multiple insights to the collection
        /// </summary>
        /// <param name="insights">The insights to add</param>
        public void AddRange(IEnumerable<ArbitrageInsight> insights)
        {
            if (insights == null)
            {
                throw new ArgumentNullException(nameof(insights));
            }

            foreach (var insight in insights)
            {
                Add(insight);
            }
        }

        /// <summary>
        /// Gets the active insight for a specific trading pair and grid level
        /// </summary>
        /// <param name="tradingPair">The trading pair</param>
        /// <param name="levelPair">The grid level</param>
        /// <returns>The insight if found, otherwise null</returns>
        public ArbitrageInsight GetInsight(TradingPairs.TradingPair tradingPair, TradingPairs.Grid.GridLevelPair levelPair)
        {
            if (tradingPair == null || levelPair == null)
            {
                return null;
            }

            lock (_lock)
            {
                var key = GetKey(tradingPair, levelPair);
                return _activeInsights.TryGetValue(key, out var insight) ? insight : null;
            }
        }

        /// <summary>
        /// Gets all active (non-expired) insights at the specified time
        /// </summary>
        /// <param name="utcTime">Current UTC time</param>
        /// <returns>List of active insights</returns>
        public List<ArbitrageInsight> GetActiveInsights(DateTime utcTime)
        {
            lock (_lock)
            {
                return _activeInsights.Values
                    .Where(i => i.IsActive(utcTime))
                    .ToList();
            }
        }

        /// <summary>
        /// Gets all insights (active or not) for a specific trading pair
        /// </summary>
        /// <param name="tradingPair">The trading pair</param>
        /// <returns>List of insights for the pair</returns>
        public List<ArbitrageInsight> GetInsightsForPair(TradingPairs.TradingPair tradingPair)
        {
            if (tradingPair == null)
            {
                return new List<ArbitrageInsight>();
            }

            lock (_lock)
            {
                return _activeInsights.Values
                    .Where(i => i.TradingPair == tradingPair)
                    .ToList();
            }
        }

        /// <summary>
        /// Removes all expired insights from the active collection and returns them
        /// </summary>
        /// <param name="utcTime">Current UTC time</param>
        /// <returns>List of removed expired insights</returns>
        public List<ArbitrageInsight> RemoveExpiredInsights(DateTime utcTime)
        {
            lock (_lock)
            {
                var expired = _activeInsights.Values
                    .Where(i => !i.IsActive(utcTime))
                    .ToList();

                foreach (var insight in expired)
                {
                    var key = GetKey(insight.TradingPair, insight.LevelPair);
                    _activeInsights.Remove(key);
                }

                return expired;
            }
        }

        /// <summary>
        /// Cancels an insight and removes it from the active collection
        /// </summary>
        /// <param name="insight">The insight to cancel</param>
        /// <param name="utcTime">Current UTC time</param>
        public void Cancel(ArbitrageInsight insight, DateTime utcTime)
        {
            if (insight == null)
            {
                return;
            }

            lock (_lock)
            {
                insight.Cancel(utcTime);
                var key = GetKey(insight.TradingPair, insight.LevelPair);
                _activeInsights.Remove(key);
            }
        }

        /// <summary>
        /// Cancels multiple insights and removes them from the active collection
        /// </summary>
        /// <param name="insights">The insights to cancel</param>
        /// <param name="utcTime">Current UTC time</param>
        public void Cancel(IEnumerable<ArbitrageInsight> insights, DateTime utcTime)
        {
            if (insights == null)
            {
                return;
            }

            foreach (var insight in insights.ToList())
            {
                Cancel(insight, utcTime);
            }
        }

        /// <summary>
        /// Generates a unique key for a (TradingPair, GridLevelPair) combination
        /// </summary>
        /// <param name="tradingPair">The trading pair</param>
        /// <param name="levelPair">The grid level pair</param>
        /// <returns>Unique string key</returns>
        private string GetKey(TradingPairs.TradingPair tradingPair, TradingPairs.Grid.GridLevelPair levelPair)
        {
            return $"{tradingPair.Leg1Symbol.Value}_{tradingPair.Leg2Symbol.Value}_{levelPair.Entry.NaturalKey}";
        }

        /// <summary>
        /// Returns an enumerator that iterates through the active insights
        /// </summary>
        public IEnumerator<ArbitrageInsight> GetEnumerator()
        {
            lock (_lock)
            {
                // Return a copy to avoid concurrent modification issues
                return _activeInsights.Values.ToList().GetEnumerator();
            }
        }

        /// <summary>
        /// Returns an enumerator that iterates through the active insights
        /// </summary>
        IEnumerator IEnumerable.GetEnumerator()
        {
            return GetEnumerator();
        }
    }
}
