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
        private readonly Dictionary<string, decimal> _borrowingMarginRates;
        private readonly Dictionary<string, List<(decimal threshold, decimal rate)>> _borrowingTierRates;

        /// <summary>
        /// Creates a new instance of the unified account margin model
        /// </summary>
        /// <param name="leverage">The leverage to use, default 5x</param>
        /// <param name="defaultMaintenanceRate">The default maintenance margin rate, default 2%</param>
        /// <param name="maintenanceAmount">The maintenance amount which will reduce maintenance margin requirements, default 0</param>
        /// <param name="currencyDiscounts">Dictionary of currency discount rates (haircuts). If null, uses default configuration</param>
        /// <param name="tierMaintenanceRates">Dictionary of tiered maintenance margin rates by position value. If null, uses default 3-tier system</param>
        /// <param name="borrowingMarginRates">Dictionary of borrowing initial margin rates for opening positions. If null, uses default configuration</param>
        /// <param name="borrowingTierRates">Dictionary of tiered maintenance margin rates for borrowing by currency. If null, uses default configuration (USDT only)</param>
        public UnifiedAccountMarginModel(
            decimal leverage = 5,
            decimal defaultMaintenanceRate = 0.02m,
            decimal maintenanceAmount = 0,
            Dictionary<string, decimal> currencyDiscounts = null,
            Dictionary<decimal, decimal> tierMaintenanceRates = null,
            Dictionary<string, decimal> borrowingMarginRates = null,
            Dictionary<string, List<(decimal threshold, decimal rate)>> borrowingTierRates = null)
            : base(leverage, defaultMaintenanceRate, maintenanceAmount)
        {
            _currencyDiscounts = currencyDiscounts ?? GetDefaultCurrencyDiscounts();
            _tierMaintenanceRates = tierMaintenanceRates ?? GetDefaultTierMaintenanceRates();
            _borrowingMarginRates = borrowingMarginRates ?? GetDefaultBorrowingMarginRates();
            _borrowingTierRates = borrowingTierRates ?? GetDefaultBorrowingTierRates();

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

            // Validate borrowing margin rates
            foreach (var kvp in _borrowingMarginRates)
            {
                if (kvp.Value < 0 || kvp.Value > 1)
                {
                    throw new ArgumentException(
                        $"Borrowing margin rate for {kvp.Key} must be between 0 and 1, but was {kvp.Value}",
                        nameof(borrowingMarginRates));
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
        /// Uses the complete Gate.io Unified Account margin calculation:
        /// - Total Margin Balance (with borrowing support via negative CashBook)
        /// - Total Initial Margin (futures + borrowing)
        /// - Discount rates for different currencies
        /// - Support for USDT borrowing (negative CashBook["USDT"])
        /// </remarks>
        protected override decimal GetMarginRemaining(
            SecurityPortfolioManager portfolio,
            Security security,
            OrderDirection direction)
        {
            // === New Complete Unified Account Calculation ===

            // Step 1: Calculate total margin balance (asset side)
            var totalMarginBalance = CalculateTotalMarginBalance(portfolio);

            // Step 2: Calculate total initial margin (liability side)
            var totalInitialMargin = CalculateTotalInitialMargin(portfolio);

            // Step 3: Available margin = Total margin balance - Total initial margin
            var availableMargin = totalMarginBalance - totalInitialMargin;

            // Step 4: Handle position reversal (closing and opening opposite direction)
            if (direction != OrderDirection.Hold)
            {
                var holdings = security.Holdings;

                if (holdings.IsLong && direction == OrderDirection.Sell)
                {
                    // Selling to close long: releases margin
                    availableMargin += this.GetMaintenanceMargin(security);
                    availableMargin += this.GetInitialMarginRequirement(security, holdings.AbsoluteQuantity);
                }
                else if (holdings.IsShort && direction == OrderDirection.Buy)
                {
                    // Buying to close short: releases margin
                    availableMargin += this.GetMaintenanceMargin(security);
                    availableMargin += this.GetInitialMarginRequirement(security, holdings.AbsoluteQuantity);
                }
            }

            // Step 5: Reserve buffer percentage
            availableMargin -= totalMarginBalance * RequiredFreeBuyingPowerPercent;

            // Step 6: Convert to buying power (multiply by leverage)
            // Note: availableMargin is already in USD, no conversion needed
            var buyingPower = availableMargin * GetLeverage(security);

            return buyingPower < 0 ? 0 : buyingPower;
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
        /// Gets the default borrowing margin rates (conservative strategy)
        /// </summary>
        /// <returns>Dictionary mapping currency symbols to borrowing margin rates</returns>
        /// <remarks>
        /// Conservative configuration:
        /// - USDT: 25% initial margin = 4x leverage (official: 20% = 5x)
        /// - BTC/ETH: 30% initial margin = 3.33x leverage (official: 25% = 4x)
        /// - Default: 33% initial margin = 3x leverage
        ///
        /// These rates are INITIAL MARGIN rates for opening positions.
        /// For MAINTENANCE MARGIN, see GetDefaultBorrowingTierRates() which uses tiered rates.
        ///
        /// These rates are higher (more conservative) than Gate.io official rates
        /// to provide a safety buffer and avoid triggering margin calls.
        /// </remarks>
        private static Dictionary<string, decimal> GetDefaultBorrowingMarginRates()
        {
            return new Dictionary<string, decimal>
            {
                { "USDT", 0.25m },  // 25% initial margin = 4x leverage
                { "BTC", 0.30m },   // 30% initial margin = 3.33x leverage
                { "ETH", 0.30m },   // 30% initial margin = 3.33x leverage
            };
        }

        /// <summary>
        /// Gets the default tiered maintenance margin rates for borrowing
        /// </summary>
        /// <returns>Dictionary mapping currency to list of (threshold, rate) tuples</returns>
        /// <remarks>
        /// Gate.io official tiered maintenance margin rates for USDT borrowing:
        ///
        /// Tier (USD)              Maintenance Rate    Max Leverage
        /// 0 – 100,000            1%                  20x
        /// 100,000 – 500,000      2%                  10x
        /// 500,000 – 1,000,000    4%                  8x
        /// 1,000,000 – 2,000,000  6%                  5x
        /// 2,000,000 – 5,000,000  8%                  4x
        /// 5,000,000 – 10,000,000 10%                 2.5x
        /// 10,000,000 – 20,000,000 15%                1.5x
        /// > 20,000,000           30%                 0x (no borrowing allowed)
        ///
        /// Calculation is cumulative (like tax brackets):
        /// Example: Borrowed 3M USDT
        /// - First 100k:    100k × 1%  = 1,000
        /// - Next 400k:     400k × 2%  = 8,000
        /// - Next 500k:     500k × 4%  = 20,000
        /// - Next 1M:       1M × 6%    = 60,000
        /// - Next 1M:       1M × 8%    = 80,000
        /// Total maintenance margin = 169,000 (5.63% effective rate)
        /// </remarks>
        private static Dictionary<string, List<(decimal threshold, decimal rate)>> GetDefaultBorrowingTierRates()
        {
            return new Dictionary<string, List<(decimal threshold, decimal rate)>>
            {
                {
                    "USDT", new List<(decimal threshold, decimal rate)>
                    {
                        (100000m,    0.01m),   // 0-100k: 1%
                        (500000m,    0.02m),   // 100k-500k: 2%
                        (1000000m,   0.04m),   // 500k-1M: 4%
                        (2000000m,   0.06m),   // 1M-2M: 6%
                        (5000000m,   0.08m),   // 2M-5M: 8%
                        (10000000m,  0.10m),   // 5M-10M: 10%
                        (20000000m,  0.15m),   // 10M-20M: 15%
                        (decimal.MaxValue, 0.30m)  // >20M: 30% (effectively no borrowing)
                    }
                }
                // Future expansion: add BTC, ETH tiers here
                // {
                //     "BTC", new List<(decimal threshold, decimal rate)>
                //     {
                //         (100m, 0.02m),
                //         ...
                //     }
                // }
            };
        }

        /// <summary>
        /// Gets the USDT borrowed amount (supports USDT borrowing only)
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>The absolute value of borrowed USDT, or 0 if no borrowing</returns>
        /// <remarks>
        /// Negative CashBook balance indicates borrowing.
        /// This simplified implementation only tracks USDT borrowing.
        /// </remarks>
        private decimal GetUSDTBorrowed(SecurityPortfolioManager portfolio)
        {
            if (!portfolio.CashBook.ContainsKey("USDT"))
            {
                return 0m;
            }

            var usdtAmount = portfolio.CashBook["USDT"].Amount;

            // Negative balance indicates borrowing
            return usdtAmount < 0 ? Math.Abs(usdtAmount) : 0m;
        }

        /// <summary>
        /// Gets the index price for a currency (simplified: uses ConversionRate)
        /// </summary>
        /// <param name="cash">The cash object</param>
        /// <returns>Index price in USD</returns>
        /// <remarks>
        /// Simplified implementation: uses ConversionRate as index price.
        /// For more accuracy, could fetch from Gate.io API in live mode.
        /// </remarks>
        private decimal GetIndexPrice(Cash cash)
        {
            // Simplified: ConversionRate represents the price in account currency
            // For BTC: ConversionRate = 50000 means 1 BTC = 50000 USD
            return cash.ConversionRate > 0 ? cash.ConversionRate : 0m;
        }

        /// <summary>
        /// Calculates the total margin balance for the unified account
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total margin balance in USD</returns>
        /// <remarks>
        /// Formula (Gate.io official):
        /// Total Margin Balance = ∑(Positive Currency Equity × Index Price × Discount Rate)
        ///                      + ∑(Negative Currency Equity × Index Price)
        ///                      - Pending Order Loss
        ///                      - Options Value
        ///
        /// Simplifications:
        /// - Index Price = ConversionRate (close approximation)
        /// - Pending Order Loss = 0 (portfolio margin mode)
        /// - Options Value = 0 (not trading options)
        /// </remarks>
        private decimal CalculateTotalMarginBalance(SecurityPortfolioManager portfolio)
        {
            decimal total = 0;

            // Part 1: Add pure cash balances and borrowing from CashBook
            foreach (var kvp in portfolio.CashBook)
            {
                var currency = kvp.Key;
                var cash = kvp.Value;
                var amount = cash.Amount;  // Can be negative (borrowed)

                // Skip zero balances
                if (amount == 0)
                {
                    continue;
                }

                // Get index price (simplified: use ConversionRate)
                var indexPrice = GetIndexPrice(cash);

                if (amount > 0)
                {
                    // Positive balance: apply discount rate
                    var discount = GetCurrencyDiscount(currency);
                    total += amount * indexPrice * discount;
                }
                else
                {
                    // Negative balance (borrowed): no discount
                    total += amount * indexPrice;  // This is negative
                }
            }

            // Part 2: Add spot crypto holdings as collateral (with discounts)
            foreach (var kvp in portfolio.Securities)
            {
                var security = kvp.Value;

                // Only consider spot crypto holdings
                if (security.Type == SecurityType.Crypto &&
                    security.Holdings.Invested &&
                    security.Price > 0 &&
                    security is Crypto.Crypto crypto)
                {
                    // Calculate spot value in USD
                    var spotValue = security.Holdings.AbsoluteQuantity * security.Price;

                    // Apply currency discount rate (haircut)
                    // Use base currency for discount (e.g., BTC in BTCUSDT)
                    var discount = GetCurrencyDiscount(crypto.BaseCurrency.Symbol);
                    var discountedValue = spotValue * discount;

                    total += discountedValue;
                }
            }

            // Simplified: Pending order loss = 0, Options value = 0
            return total;
        }

        /// <summary>
        /// Calculates the initial margin for all futures positions
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total futures initial margin in USD</returns>
        private decimal CalculateFuturesInitialMargin(SecurityPortfolioManager portfolio)
        {
            decimal total = 0;

            foreach (var kvp in portfolio.Securities)
            {
                var security = kvp.Value;

                if (security.Type == SecurityType.CryptoFuture && security.Holdings.Invested)
                {
                    var quantity = security.Holdings.Quantity;
                    var price = security.Price;  // Simplified: use market price instead of mark price
                    var leverage = GetLeverage(security);

                    // Initial margin = abs(position quantity) × price / leverage
                    total += Math.Abs(quantity) * price / leverage;
                }
            }

            return total;
        }

        /// <summary>
        /// Calculates the initial margin for borrowing (USDT only)
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total borrowing initial margin in USD</returns>
        /// <remarks>
        /// Formula: Borrowing Initial Margin = Borrowed Amount × Borrowing Margin Rate
        /// Only supports USDT borrowing in this simplified implementation.
        /// </remarks>
        private decimal CalculateBorrowingInitialMargin(SecurityPortfolioManager portfolio)
        {
            // Get USDT borrowed amount
            var usdtBorrowed = GetUSDTBorrowed(portfolio);

            if (usdtBorrowed == 0)
            {
                return 0m;
            }

            // Get USDT borrowing margin rate
            var marginRate = _borrowingMarginRates.GetValueOrDefault("USDT", 0.33m);

            // Borrowing initial margin = borrowed amount × margin rate
            return usdtBorrowed * marginRate;
        }

        /// <summary>
        /// Calculates the total initial margin for the unified account
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total initial margin in USD</returns>
        /// <remarks>
        /// Formula: Total Initial Margin = ∑Futures Initial Margin + ∑Borrowing Initial Margin
        /// </remarks>
        private decimal CalculateTotalInitialMargin(SecurityPortfolioManager portfolio)
        {
            decimal total = 0;

            // 1. Futures initial margin
            total += CalculateFuturesInitialMargin(portfolio);

            // 2. Borrowing initial margin (USDT only)
            total += CalculateBorrowingInitialMargin(portfolio);

            // 3. Options initial margin (if supported)
            // total += CalculateOptionsInitialMargin(portfolio);

            return total;
        }

        /// <summary>
        /// Calculates the total maintenance margin for the unified account
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total maintenance margin in USD</returns>
        /// <remarks>
        /// Formula: Total Maintenance Margin = ∑Futures Maintenance Margin + ∑Borrowing Maintenance Margin
        /// </remarks>
        private decimal CalculateTotalMaintenanceMargin(SecurityPortfolioManager portfolio)
        {
            decimal total = 0;

            // 1. Futures maintenance margin (using existing GetMaintenanceMargin method)
            foreach (var kvp in portfolio.Securities)
            {
                var security = kvp.Value;

                if (security.Type == SecurityType.CryptoFuture && security.Holdings.Invested)
                {
                    var maintenanceMargin = GetMaintenanceMargin(
                        MaintenanceMarginParameters.ForCurrentHoldings(security));

                    total += maintenanceMargin.Value;
                }
            }

            // 2. Borrowing maintenance margin (using tiered rates)
            total += CalculateBorrowingMaintenanceMargin(portfolio);

            return total;
        }

        /// <summary>
        /// Calculates the maintenance margin for all borrowing using tiered rates
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Total borrowing maintenance margin in USD</returns>
        /// <remarks>
        /// Uses tiered maintenance margin rates for each currency.
        /// For USDT, applies Gate.io official 8-tier system.
        /// For other currencies without tiers, uses simple fixed rate.
        /// </remarks>
        private decimal CalculateBorrowingMaintenanceMargin(SecurityPortfolioManager portfolio)
        {
            decimal total = 0;

            foreach (var kvp in portfolio.CashBook)
            {
                var currency = kvp.Key;
                var cash = kvp.Value;
                var amount = cash.Amount;

                if (amount >= 0) continue;  // Only negative balances (borrowed)

                var borrowedAmount = Math.Abs(amount);
                var borrowedValueUSD = borrowedAmount * cash.ConversionRate;

                if (_borrowingTierRates.TryGetValue(currency, out var tiers))
                {
                    // Use tiered rates (e.g., USDT)
                    total += CalculateTieredBorrowingMargin(borrowedValueUSD, tiers);
                }
                else
                {
                    // Use simple fixed rate for currencies without tiers
                    var rate = _borrowingMarginRates.GetValueOrDefault(currency, 0.30m);
                    total += borrowedValueUSD * rate;
                }
            }

            return total;
        }

        /// <summary>
        /// Calculates tiered borrowing maintenance margin (like tax brackets)
        /// </summary>
        /// <param name="borrowedAmountUSD">Total borrowed amount in USD</param>
        /// <param name="tiers">List of (threshold, rate) tuples</param>
        /// <returns>Total maintenance margin using tiered calculation</returns>
        /// <remarks>
        /// Example: Borrowed 300,000 USDT
        /// - First 100k:    100k × 1%  = 1,000
        /// - Next 400k:     400k × 2%  = 8,000
        /// - Next 500k:     Not reached
        /// Total = 9,000 (3% effective rate)
        /// </remarks>
        private decimal CalculateTieredBorrowingMargin(decimal borrowedAmountUSD, List<(decimal threshold, decimal rate)> tiers)
        {
            decimal total = 0;
            decimal previousThreshold = 0;

            foreach (var (threshold, rate) in tiers.OrderBy(t => t.threshold))
            {
                if (borrowedAmountUSD <= previousThreshold)
                    break;

                var tierAmount = Math.Min(borrowedAmountUSD, threshold) - previousThreshold;
                total += tierAmount * rate;

                previousThreshold = threshold;
            }

            return total;
        }

        /// <summary>
        /// Gets the unified account risk ratio
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Risk ratio as a percentage (e.g., 150 means 150%)</returns>
        /// <remarks>
        /// Formula: Risk Ratio = Total Margin Balance / Total Maintenance Margin × 100
        ///
        /// Interpretation:
        /// - > 100%: Safe
        /// - 50% - 100%: Warning
        /// - &lt; 50%: Danger (close to liquidation)
        /// </remarks>
        public decimal GetAccountRiskRatio(SecurityPortfolioManager portfolio)
        {
            var totalMarginBalance = CalculateTotalMarginBalance(portfolio);
            var totalMaintenanceMargin = CalculateTotalMaintenanceMargin(portfolio);

            if (totalMaintenanceMargin == 0)
            {
                return decimal.MaxValue;  // No positions, no risk
            }

            return (totalMarginBalance / totalMaintenanceMargin) * 100m;
        }

        /// <summary>
        /// Gets the available margin for the unified account
        /// </summary>
        /// <param name="portfolio">The algorithm's portfolio</param>
        /// <returns>Available margin in USD</returns>
        /// <remarks>
        /// Formula: Available Margin = Total Margin Balance - Total Initial Margin
        /// </remarks>
        public decimal GetAvailableMargin(SecurityPortfolioManager portfolio)
        {
            var totalMarginBalance = CalculateTotalMarginBalance(portfolio);
            var totalInitialMargin = CalculateTotalInitialMargin(portfolio);

            return totalMarginBalance - totalInitialMargin;
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
