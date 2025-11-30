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

using System.Linq;
using QuantConnect.Algorithm.Framework.Alphas;
using QuantConnect.Algorithm.Framework.Execution;
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data;
using QuantConnect.Data.UniverseSelection;
using QuantConnect.Interfaces;

namespace QuantConnect.Algorithm
{
    /// <summary>
    /// AQCAlgorithm Framework extension - Provides arbitrage-specific Framework support.
    /// This partial class extends AQCAlgorithm with arbitrage-specific Portfolio Construction
    /// and Execution models that support Tag-based per-position tracking.
    /// </summary>
    public partial class AQCAlgorithm
    {
        /// <summary>
        /// Arbitrage-specific portfolio construction model.
        /// Returns ArbitragePortfolioTarget instead of IPortfolioTarget.
        /// </summary>
        public IArbitragePortfolioConstructionModel ArbitragePortfolioConstruction { get; set; }

        /// <summary>
        /// Arbitrage-specific execution model.
        /// Accepts ArbitragePortfolioTarget instead of IPortfolioTarget.
        /// </summary>
        public IArbitrageExecutionModel ArbitrageExecution { get; set; }

        /// <summary>
        /// Sets the arbitrage portfolio construction model.
        /// Use this instead of SetPortfolioConstruction() for arbitrage trading.
        /// </summary>
        /// <param name="model">The arbitrage portfolio construction model</param>
        public void SetArbitragePortfolioConstruction(IArbitragePortfolioConstructionModel model)
        {
            ArbitragePortfolioConstruction = model;
        }

        /// <summary>
        /// Sets the arbitrage execution model.
        /// Use this instead of SetExecution() for arbitrage trading.
        /// </summary>
        /// <param name="model">The arbitrage execution model</param>
        public void SetArbitrageExecution(IArbitrageExecutionModel model)
        {
            ArbitrageExecution = model;
        }

        /// <summary>
        /// Override ProcessInsights to use arbitrage-specific framework.
        /// </summary>
        /// <param name="insights">The insights to process</param>
        protected override void ProcessInsights(Insight[] insights)
        {
            // Use arbitrage-specific framework
            ProcessArbitrageInsights(insights);
        }

        /// <summary>
        /// Processes insights using arbitrage-specific framework.
        /// Skips RiskManagement and uses ArbitragePortfolioTarget.
        /// </summary>
        /// <param name="insights">The insights to process</param>
        private void ProcessArbitrageInsights(Insight[] insights)
        {
            // Create arbitrage targets
            var targets = ArbitragePortfolioConstruction.CreateArbitrageTargets(this, insights);

            if (DebugMode && targets.Length > 0)
            {
                Log($"{Time}: ARBITRAGE PORTFOLIO: {string.Join(" | ", targets.Select(t => t.ToString()))}");
            }

            // Skip RiskManagement - directly execute
            // Note: Arbitrage strategies typically have their own risk controls
            ArbitrageExecution.Execute(this, targets);
        }
    }
}
