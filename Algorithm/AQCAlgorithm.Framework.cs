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
using System.Collections.Specialized;
using System.Linq;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Data;
using QuantConnect.TradingPairs;

namespace QuantConnect.Algorithm
{
    /// <summary>
    /// Framework integration for AQCAlgorithm.
    /// Provides alpha model, portfolio construction, and execution capabilities for arbitrage trading.
    /// </summary>
    public partial class AQCAlgorithm
    {
        /// <summary>
        /// Gets or sets the alpha model for generating arbitrage insights
        /// </summary>
        public IArbitrageAlphaModel Alpha { get; set; }

        /// <summary>
        /// Gets the insight collection that manages all arbitrage insights
        /// </summary>
        public ArbitrageInsightCollection Insights { get; private set; }

        /// <summary>
        /// Initializes the framework components.
        /// Called from AQCAlgorithm constructor.
        /// </summary>
        private void InitializeFramework()
        {
            // Initialize the insight collection
            Insights = new ArbitrageInsightCollection();

            // Subscribe to TradingPairManager collection changes
            TradingPairs.CollectionChanged += OnTradingPairsCollectionChanged;
        }

        /// <summary>
        /// Sets the alpha model for generating arbitrage insights
        /// </summary>
        /// <param name="alpha">The arbitrage alpha model instance</param>
        public void SetAlpha(IArbitrageAlphaModel alpha)
        {
            Alpha = alpha;
        }

        /// <summary>
        /// Called when trading pairs are added or removed from the TradingPairManager.
        /// Notifies the alpha model of the changes.
        /// </summary>
        private void OnTradingPairsCollectionChanged(object sender, NotifyCollectionChangedEventArgs e)
        {
            if (Alpha == null) return;

            // Convert NotifyCollectionChangedEventArgs to TradingPairChanges
            var addedPairs = e.Action == NotifyCollectionChangedAction.Add && e.NewItems != null
                ? e.NewItems.Cast<TradingPair>().ToList()
                : new List<TradingPair>();

            var removedPairs = e.Action == NotifyCollectionChangedAction.Remove && e.OldItems != null
                ? e.OldItems.Cast<TradingPair>().ToList()
                : new List<TradingPair>();

            // Reset action clears all pairs
            if (e.Action == NotifyCollectionChangedAction.Reset)
            {
                removedPairs = TradingPairs.ToList();
            }

            var changes = new TradingPairChanges(addedPairs, removedPairs);

            if (changes.HasChanges)
            {
                // Notify alpha model of trading pair changes (cast to AIAlgorithm for interface compatibility)
                Alpha.OnTradingPairsChanged((Interfaces.AIAlgorithm)this, changes);

                // TODO: Notify Portfolio Construction, Execution, Risk Management
            }
        }

        /// <summary>
        /// Called on each data slice to update framework models.
        /// Triggers alpha model update and processes generated insights.
        /// </summary>
        protected void OnFrameworkData(Slice slice)
        {
            if (Alpha == null) return;

            // Update alpha model and get new insights (cast to AIAlgorithm for interface compatibility)
            var insightsEnumerable = Alpha.Update((Interfaces.AIAlgorithm)this, slice);

            // Convert to array for efficient processing
            var insights = insightsEnumerable == Enumerable.Empty<ArbitrageInsight>()
                ? new ArbitrageInsight[] { }
                : insightsEnumerable.ToArray();

            if (insights.Length > 0)
            {
                // Initialize insight fields managed by the framework
                InitializeInsights(insights);

                // Add to insight collection
                Insights.AddRange(insights);

                // Process insights through portfolio construction and execution
                ProcessInsights(insights);
            }
        }

        /// <summary>
        /// Initializes insight fields that are managed by the framework.
        /// Sets timestamps and other framework-controlled properties.
        /// </summary>
        /// <param name="insights">The insights to initialize</param>
        private void InitializeInsights(ArbitrageInsight[] insights)
        {
            foreach (var insight in insights)
            {
                // Set the generation timestamp
                insight.GeneratedTimeUtc = UtcTime;

                // Calculate close time based on period
                insight.CloseTimeUtc = UtcTime.Add(insight.Period);
            }
        }

        /// <summary>
        /// Processes insights through portfolio construction and execution.
        /// This will be implemented when Portfolio Construction and Execution models are added.
        /// </summary>
        /// <param name="insights">The insights to process</param>
        private void ProcessInsights(ArbitrageInsight[] insights)
        {
            // TODO: Implement portfolio construction
            // var targets = PortfolioConstruction.CreateTargets(this, insights);

            // TODO: Implement risk management
            // var riskAdjustedTargets = RiskManagement.ManageRisk(this, targets);

            // TODO: Implement execution
            // Execution.Execute(this, riskAdjustedTargets);
        }
    }
}
