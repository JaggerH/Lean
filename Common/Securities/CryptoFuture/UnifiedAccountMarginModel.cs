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
using QuantConnect.Orders;

namespace QuantConnect.Securities.CryptoFuture
{
    /// <summary>
    /// Margin model for Gate.io Unified Account supporting cross-margin between
    /// spot and futures positions. Spot crypto holdings serve as collateral with
    /// currency-specific discount rates (haircuts).
    /// </summary>
    /// <remarks>
    /// Key Features:
    /// - Spot assets contribute to futures margin with discount rates
    /// - Tiered maintenance margin based on position size
    /// - Cross-margin across all futures sharing same collateral currency
    ///
    /// Simplifications vs Gate.io Official:
    /// - 3-tier system instead of 7-tier
    /// - Fixed leverage (no position-size adjustment)
    /// - No pending order loss calculation
    ///
    /// Default Configuration:
    /// - Leverage: 5x
    /// - Maintenance rate: 2% (mid-tier default)
    /// - Currency discounts: USDT 100%, BTC/ETH 95%, others 85%
    /// </remarks>
    public class UnifiedAccountMarginModel : CryptoFutureMarginModel
    {
        private readonly Dictionary<string, decimal> _currencyDiscounts;
        private readonly Dictionary<decimal, decimal> _tierMaintenanceRates;

        /// <summary>
        /// Creates a new instance of the unified account margin model
        /// </summary>
        /// <param name="leverage">The leverage to use, default 5x</param>
        /// <param name="defaultMaintenanceRate">The default maintenance margin rate, default 2%</param>
        /// <param name="maintenanceAmount">The maintenance amount which will reduce maintenance margin requirements, default 0</param>
        /// <param name="currencyDiscounts">Dictionary of currency discount rates (haircuts). If null, uses default configuration</param>
        /// <param name="tierMaintenanceRates">Dictionary of tiered maintenance margin rates by position value. If null, uses default 3-tier system</param>
        public UnifiedAccountMarginModel(
            decimal leverage = 5,
            decimal defaultMaintenanceRate = 0.02m,
            decimal maintenanceAmount = 0,
            Dictionary<string, decimal> currencyDiscounts = null,
            Dictionary<decimal, decimal> tierMaintenanceRates = null)
            : base(leverage, defaultMaintenanceRate, maintenanceAmount)
        {
            _currencyDiscounts = currencyDiscounts ?? GetDefaultCurrencyDiscounts();
            _tierMaintenanceRates = tierMaintenanceRates ?? GetDefaultTierMaintenanceRates();

            // Validate tier maintenance rates
            if (_tierMaintenanceRates.Count == 0)
            {
                throw new ArgumentException("Tier maintenance rates cannot be empty", nameof(tierMaintenanceRates));
            }

            foreach (var kvp in _tierMaintenanceRates)
            {
                if (kvp.Key <= 0)
                {
                    throw new ArgumentException(
                        $"Tier threshold must be positive, but was {kvp.Key}",
                        nameof(tierMaintenanceRates));
                }

                if (kvp.Value < 0 || kvp.Value > 1)
                {
                    throw new ArgumentException(
                        $"Maintenance rate must be between 0 and 1, but was {kvp.Value}",
                        nameof(tierMaintenanceRates));
                }
            }

            // Validate currency discounts
            foreach (var kvp in _currencyDiscounts)
            {
                if (kvp.Value < 0 || kvp.Value > 1)
                {
                    throw new ArgumentException(
                        $"Currency discount for {kvp.Key} must be between 0 and 1, but was {kvp.Value}",
                        nameof(currencyDiscounts));
                }
            }
        }

        /// <summary>
        /// Gets the margin cash available for a trade
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <param name="security">The security to be traded</param>
        /// <param name="direction">The direction of the trade</param>
        /// <returns>The margin available for the trade</returns>
        /// <remarks>
        /// This method aggregates collateral from both spot crypto holdings and base currency (USDT).
        /// Spot holdings are valued with currency-specific discount rates to account for volatility.
        /// </remarks>
        protected override decimal GetMarginRemaining(
            SecurityPortfolioManager portfolio,
            Security security,
            OrderDirection direction)
        {
            var collateralCurrency = GetCollateralCash(security);

            // Step 1: Calculate total collateral value including spot assets
            var totalCollateral = CalculateTotalCollateralValue(portfolio, security);

            // Step 2: Calculate total margin used by all futures positions
            var totalFuturesMarginUsed = CalculateTotalFuturesMarginUsed(portfolio, security);

            // Step 3: Available margin = Total collateral - Used margin - Reserve
            var result = totalCollateral - totalFuturesMarginUsed;

            // Step 4: Handle position reversal (closing and opening opposite direction)
            if (direction != OrderDirection.Hold)
            {
                var holdings = security.Holdings;

                // If the order is in the opposite direction, we can use more margin
                // because we're closing the existing position
                if (holdings.IsLong)
                {
                    switch (direction)
                    {
                        case OrderDirection.Sell:
                            result +=
                                // portion of margin to close the existing position
                                this.GetMaintenanceMargin(security) +
                                // portion of margin to open the new position
                                this.GetInitialMarginRequirement(security, security.Holdings.AbsoluteQuantity);
                            break;
                    }
                }
                else if (holdings.IsShort)
                {
                    switch (direction)
                    {
                        case OrderDirection.Buy:
                            result +=
                                // portion of margin to close the existing position
                                this.GetMaintenanceMargin(security) +
                                // portion of margin to open the new position
                                this.GetInitialMarginRequirement(security, security.Holdings.AbsoluteQuantity);
                            break;
                    }
                }
            }

            // Step 5: Reserve buffer percentage
            result -= totalCollateral * RequiredFreeBuyingPowerPercent;

            // Step 6: Convert into account currency
            result *= collateralCurrency.ConversionRate;

            // Step 7: Apply leverage to convert margin to buying power
            // Note: GetMarginRemaining should return buying power, not just available margin
            result *= GetLeverage(security);

            return result < 0 ? 0 : result;
        }

        /// <summary>
        /// Calculates the total collateral value including spot crypto holdings with discount rates
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <param name="futuresSecurity">The futures security being traded</param>
        /// <returns>Total collateral value in collateral currency units</returns>
        private decimal CalculateTotalCollateralValue(
            SecurityPortfolioManager portfolio,
            Security futuresSecurity)
        {
            var collateralCurrency = GetCollateralCash(futuresSecurity);
            var totalValue = collateralCurrency.Amount; // Start with base currency (e.g., USDT)

            // Iterate through all spot crypto holdings
            foreach (var kvp in portfolio.Securities)
            {
                var security = kvp.Value;

                // Only consider spot crypto that shares the same quote currency as the futures
                // e.g., for BTCUSDT futures, only count BTCUSDT, ETHUSDT spot (all have USDT quote)
                if (security.Type == SecurityType.Crypto &&
                    security.Holdings.Invested &&
                    security.Price > 0 &&
                    security.QuoteCurrency.Symbol == collateralCurrency.Symbol)
                {
                    // Use safer pattern matching cast
                    if (security is Crypto.Crypto crypto)
                    {
                        // Calculate spot value in collateral currency
                        var spotValue = security.Holdings.AbsoluteQuantity * security.Price;

                        // Apply currency discount rate (haircut)
                        var discount = GetCurrencyDiscount(crypto.BaseCurrency.Symbol);
                        var discountedValue = spotValue * discount;

                        totalValue += discountedValue;
                    }
                }
            }

            return totalValue;
        }

        /// <summary>
        /// Gets the currency discount rate (haircut) for a specific currency
        /// </summary>
        /// <param name="currency">The currency symbol (e.g., "BTC", "ETH")</param>
        /// <returns>Discount rate between 0 and 1 (e.g., 0.95 = 5% haircut)</returns>
        private decimal GetCurrencyDiscount(string currency)
        {
            if (_currencyDiscounts.TryGetValue(currency, out var discount))
            {
                return discount;
            }

            // Default: 15% haircut for unknown currencies
            return 0.85m;
        }

        /// <summary>
        /// Calculates the total margin used by all futures positions sharing the same collateral
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <param name="currentSecurity">The current futures security</param>
        /// <returns>Total maintenance margin used by all futures positions</returns>
        private decimal CalculateTotalFuturesMarginUsed(
            SecurityPortfolioManager portfolio,
            Security currentSecurity)
        {
            var collateralCurrency = GetCollateralCash(currentSecurity);
            var totalUsed = 0m;

            foreach (var kvp in portfolio.Securities)
            {
                var security = kvp.Value;

                // Only aggregate futures that share the same collateral currency (excluding current security)
                if (security.Type == SecurityType.CryptoFuture &&
                    security.Holdings.Invested &&
                    security.Symbol != currentSecurity.Symbol)
                {
                    var otherCollateral = GetCollateralCash(security);
                    // Compare currency symbols instead of Cash object references
                    if (otherCollateral.Symbol == collateralCurrency.Symbol)
                    {
                        totalUsed += security.BuyingPowerModel.GetMaintenanceMargin(
                            MaintenanceMarginParameters.ForCurrentHoldings(security));
                    }
                }
            }

            return totalUsed;
        }

        /// <summary>
        /// Gets the margin currently allocated to the specified holding with tiered maintenance margin rates
        /// </summary>
        /// <param name="parameters">An object containing the security and holdings quantity</param>
        /// <returns>The maintenance margin required for the provided holdings</returns>
        public override MaintenanceMargin GetMaintenanceMargin(MaintenanceMarginParameters parameters)
        {
            var security = parameters.Security;
            var quantity = parameters.Quantity;

            if (security?.GetLastData() == null || quantity == 0m)
            {
                return MaintenanceMargin.Zero;
            }

            // Calculate position value in USD
            var positionValue = security.Holdings.GetQuantityValue(quantity, security.Price);
            var positionValueUSD = Math.Abs(positionValue.Amount * positionValue.Cash.ConversionRate);

            // Get tiered maintenance margin rate based on position size
            var maintenanceRate = GetTieredMaintenanceRate(positionValueUSD);

            // Calculate maintenance margin requirement
            var marginRequirement = positionValueUSD * maintenanceRate;

            return new MaintenanceMargin(marginRequirement);
        }

        /// <summary>
        /// Gets the tiered maintenance margin rate based on position value
        /// </summary>
        /// <param name="positionValueUSD">Position value in USD</param>
        /// <returns>Maintenance margin rate as a decimal (e.g., 0.02 = 2%)</returns>
        private decimal GetTieredMaintenanceRate(decimal positionValueUSD)
        {
            // Iterate through tiers in ascending order of position value
            foreach (var tier in _tierMaintenanceRates.OrderBy(t => t.Key))
            {
                if (positionValueUSD < tier.Key)
                {
                    return tier.Value;
                }
            }

            // Fallback to highest tier rate
            return _tierMaintenanceRates.Last().Value;
        }

        /// <summary>
        /// Gets the default currency discount rates (haircuts)
        /// </summary>
        /// <returns>Dictionary mapping currency symbols to discount rates</returns>
        private static Dictionary<string, decimal> GetDefaultCurrencyDiscounts()
        {
            return new Dictionary<string, decimal>
            {
                { "USDT", 1.0m },   // Stablecoins: no discount
                { "USDC", 1.0m },   // Stablecoins: no discount
                { "BTC", 0.95m },   // Bitcoin: 5% haircut
                { "ETH", 0.95m },   // Ethereum: 5% haircut
                { "BNB", 0.90m },   // Binance Coin: 10% haircut
                { "SOL", 0.90m },   // Solana: 10% haircut
                { "DOGE", 0.85m },  // Dogecoin: 15% haircut
                { "ADA", 0.85m },   // Cardano: 15% haircut
                { "DOT", 0.85m },   // Polkadot: 15% haircut
                { "MATIC", 0.80m }, // Polygon: 20% haircut
            };
        }

        /// <summary>
        /// Gets the default tiered maintenance margin rates
        /// </summary>
        /// <returns>Dictionary mapping position value thresholds to maintenance margin rates</returns>
        /// <remarks>
        /// Default 3-tier system:
        /// - Tier 1: Positions &lt; $50,000 → 0.5% maintenance margin
        /// - Tier 2: Positions &lt; $500,000 → 2% maintenance margin
        /// - Tier 3: Positions ≥ $500,000 → 5% maintenance margin
        /// </remarks>
        private static Dictionary<decimal, decimal> GetDefaultTierMaintenanceRates()
        {
            return new Dictionary<decimal, decimal>
            {
                { 50000m, 0.005m },       // Tier 1: < $50k → 0.5%
                { 500000m, 0.02m },       // Tier 2: < $500k → 2%
                { decimal.MaxValue, 0.05m } // Tier 3: >= $500k → 5%
            };
        }

        /// <summary>
        /// Helper method to determine what's the collateral currency for the given crypto future
        /// </summary>
        /// <param name="security">The futures security</param>
        /// <returns>The cash object representing the collateral currency</returns>
        /// <exception cref="ArgumentException">Thrown when security is not a CryptoFuture</exception>
        private static Cash GetCollateralCash(Security security)
        {
            if (security is not CryptoFuture cryptoFuture)
            {
                throw new ArgumentException(
                    $"Security must be CryptoFuture type, but was {security.GetType().Name}",
                    nameof(security));
            }

            var collateralCurrency = cryptoFuture.BaseCurrency;
            if (!cryptoFuture.IsCryptoCoinFuture())
            {
                collateralCurrency = cryptoFuture.QuoteCurrency;
            }

            return collateralCurrency;
        }
    }
}
