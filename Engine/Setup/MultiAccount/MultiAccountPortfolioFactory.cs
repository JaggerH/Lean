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
using QuantConnect.Algorithm;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Orders;
using QuantConnect.Securities;
using QuantConnect.Securities.MultiAccount;

namespace QuantConnect.Lean.Engine.Setup.MultiAccount
{
    /// <summary>
    /// Factory for creating and attaching MultiSecurityPortfolioManager
    /// </summary>
    public class MultiAccountPortfolioFactory
    {
        /// <summary>
        /// Creates MultiSecurityPortfolioManager and replaces algorithm.Portfolio
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="accountInitialCash">Account initial cash amounts</param>
        /// <param name="accountCurrencies">Account currencies (CRITICAL parameter)</param>
        /// <param name="router">Order router</param>
        /// <returns>Created multi-account portfolio</returns>
        public MultiSecurityPortfolioManager CreateAndAttach(
            IAlgorithm algorithm,
            Dictionary<string, decimal> accountInitialCash,
            Dictionary<string, string> accountCurrencies,
            IOrderRouter router)
        {
            // CRITICAL: Validate accountCurrencies before proceeding
            if (accountCurrencies == null || accountCurrencies.Count == 0)
            {
                throw new ArgumentNullException(nameof(accountCurrencies),
                    "accountCurrencies must not be null or empty - this indicates a configuration bug");
            }

            Log.Trace($"MultiAccountPortfolioFactory.CreateAndAttach(): Creating portfolio with {accountCurrencies.Count} accounts");

            // Unwrap Python wrapper if necessary
            var qcAlgorithm = UnwrapAlgorithm(algorithm);

            // Create MultiSecurityPortfolioManager
            // IMPORTANT: Pass accountCurrencies to ensure correct currency setup
            var multiPortfolio = new MultiSecurityPortfolioManager(
                accountInitialCash,
                router,
                qcAlgorithm.Securities,
                qcAlgorithm.Transactions,
                qcAlgorithm.Settings,
                qcAlgorithm.DefaultOrderProperties,
                qcAlgorithm.TimeKeeper,
                accountCurrencies);  // ← CRITICAL PARAMETER

            // Validate creation
            ValidatePortfolioCreation(multiPortfolio, accountCurrencies);

            // Replace algorithm.Portfolio
            ReplacePortfolio(qcAlgorithm, multiPortfolio);

            return multiPortfolio;
        }

        /// <summary>
        /// Validates that portfolio was created with correct currencies
        /// </summary>
        /// <param name="multiPortfolio">The created portfolio</param>
        /// <param name="expectedCurrencies">Expected currencies for each account</param>
        private void ValidatePortfolioCreation(
            MultiSecurityPortfolioManager multiPortfolio,
            Dictionary<string, string> expectedCurrencies)
        {
            foreach (var kvp in expectedCurrencies)
            {
                var accountName = kvp.Key;
                var expectedCurrency = kvp.Value;

                var subAccount = multiPortfolio.GetAccount(accountName);
                var actualCurrency = subAccount.CashBook.AccountCurrency;

                if (actualCurrency != expectedCurrency)
                {
                    throw new InvalidOperationException(
                        $"CRITICAL: Account '{accountName}' created with wrong currency: expected '{expectedCurrency}', got '{actualCurrency}'");
                }

                Log.Trace($"MultiAccountPortfolioFactory.ValidatePortfolioCreation(): ✓ Account '{accountName}' uses '{actualCurrency}'");
            }
        }

        /// <summary>
        /// Unwraps Python algorithm wrapper
        /// </summary>
        /// <param name="algorithm">The algorithm (possibly wrapped)</param>
        /// <returns>Unwrapped QCAlgorithm</returns>
        private QCAlgorithm UnwrapAlgorithm(IAlgorithm algorithm)
        {
            var qcAlgorithm = algorithm as QCAlgorithm;

            // Handle Python wrapper
            if (qcAlgorithm == null)
            {
                var wrapperType = algorithm.GetType();
                var baseAlgorithmProperty = wrapperType.GetProperty("BaseAlgorithm");

                if (baseAlgorithmProperty != null)
                {
                    qcAlgorithm = baseAlgorithmProperty.GetValue(algorithm) as QCAlgorithm;
                }
            }

            if (qcAlgorithm == null)
            {
                throw new InvalidOperationException("Unable to unwrap algorithm");
            }

            return qcAlgorithm;
        }

        /// <summary>
        /// Replaces algorithm.Portfolio via reflection
        /// </summary>
        /// <param name="algorithm">The algorithm</param>
        /// <param name="multiPortfolio">The new portfolio to set</param>
        private void ReplacePortfolio(
            QCAlgorithm algorithm,
            MultiSecurityPortfolioManager multiPortfolio)
        {
            // Portfolio is now a public property with a setter, so we can set it directly
            algorithm.Portfolio = multiPortfolio;

            Log.Trace("MultiAccountPortfolioFactory.ReplacePortfolio(): Replaced algorithm.Portfolio with MultiSecurityPortfolioManager");
        }
    }
}
