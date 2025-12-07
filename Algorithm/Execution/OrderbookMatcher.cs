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
using QuantConnect.Algorithm.Framework.Portfolio;
using QuantConnect.Data.Market;
using QuantConnect.Interfaces;
using QuantConnect.Logging;
using QuantConnect.Securities;
using QuantConnect.TradingPairs.Grid;

namespace QuantConnect.Algorithm.Framework.Execution
{
    /// <summary>
    /// Direction of arbitrage trade
    /// </summary>
    public enum ArbitrageDirection
    {
        /// <summary>
        /// Long spread: Buy symbol1, sell symbol2 (expect symbol1 cheaper)
        /// </summary>
        LongSpread,

        /// <summary>
        /// Short spread: Sell symbol1, buy symbol2 (expect symbol1 more expensive)
        /// </summary>
        ShortSpread
    }

    /// <summary>
    /// Matching strategy for orderbook-based execution
    /// </summary>
    public enum MatchingStrategy
    {
        /// <summary>
        /// Auto-select based on orderbook availability
        /// </summary>
        AutoDetect,

        /// <summary>
        /// Force dual-orderbook matching (both sides have depth)
        /// </summary>
        DualOrderbook,

        /// <summary>
        /// Force single-orderbook matching (one side has depth)
        /// </summary>
        SingleOrderbook,

        /// <summary>
        /// Force best price matching (no orderbook depth used)
        /// </summary>
        BestPrices
    }

    /// <summary>
    /// Result of orderbook matching operation
    /// </summary>
    public class MatchResult
    {
        /// <summary>
        /// Executable quantity for symbol1 (signed: + = buy, - = sell)
        /// </summary>
        public decimal Symbol1Quantity { get; set; }

        /// <summary>
        /// Executable quantity for symbol2 (signed: + = buy, - = sell)
        /// </summary>
        public decimal Symbol2Quantity { get; set; }

        /// <summary>
        /// Average buy price across all matched levels
        /// </summary>
        public decimal AvgBuyPrice { get; set; }

        /// <summary>
        /// Average sell price across all matched levels
        /// </summary>
        public decimal AvgSellPrice { get; set; }

        /// <summary>
        /// Average spread percentage across all matched levels
        /// </summary>
        public decimal AvgSpreadPct { get; set; }

        /// <summary>
        /// Total USD value of buy side
        /// </summary>
        public decimal TotalBuyUsd { get; set; }

        /// <summary>
        /// Total USD value of sell side
        /// </summary>
        public decimal TotalSellUsd { get; set; }

        /// <summary>
        /// Whether the match is executable
        /// </summary>
        public bool Executable { get; set; }

        /// <summary>
        /// Reason for rejection if not executable
        /// </summary>
        public string RejectReason { get; set; }

        /// <summary>
        /// Detailed match levels (for debugging/logging)
        /// </summary>
        public List<MatchLevel> MatchedLevels { get; set; }

        /// <summary>
        /// Strategy used for this match
        /// </summary>
        public MatchingStrategy UsedStrategy { get; set; }

        /// <summary>
        /// Initializes a new instance of the <see cref="MatchResult"/> class
        /// </summary>
        public MatchResult()
        {
            MatchedLevels = new List<MatchLevel>();
        }
    }

    /// <summary>
    /// Detailed information about a single matched orderbook level
    /// </summary>
    public class MatchLevel
    {
        /// <summary>
        /// Price for symbol1 at this level
        /// </summary>
        public decimal Price1 { get; set; }

        /// <summary>
        /// Price for symbol2 at this level
        /// </summary>
        public decimal Price2 { get; set; }

        /// <summary>
        /// Quantity matched for symbol1
        /// </summary>
        public decimal Quantity1 { get; set; }

        /// <summary>
        /// Quantity matched for symbol2
        /// </summary>
        public decimal Quantity2 { get; set; }

        /// <summary>
        /// USD value of this match level
        /// </summary>
        public decimal UsdValue { get; set; }

        /// <summary>
        /// Spread percentage at this level
        /// </summary>
        public decimal SpreadPct { get; set; }
    }

    /// <summary>
    /// Orderbook matching engine for arbitrage execution.
    /// Provides orderbook-aware execution that validates spreads and respects market depth.
    /// </summary>
    public static class OrderbookMatcher
    {
        /// <summary>
        /// Match a pair of symbols using the specified strategy.
        /// Auto-detects best strategy if AutoDetect is specified.
        /// </summary>
        /// <param name="algorithm">The algorithm instance</param>
        /// <param name="target">Arbitrage portfolio target containing symbols, quantities, and grid level</param>
        /// <param name="targetUsd">Target USD amount to match (for market value equality)</param>
        /// <param name="preferredStrategy">Preferred matching strategy</param>
        /// <returns>Match result with executable quantities, or null if matching fails</returns>
        public static MatchResult MatchPair(
            IAlgorithm algorithm,
            IArbitragePortfolioTarget target,
            decimal targetUsd,
            MatchingStrategy preferredStrategy = MatchingStrategy.AutoDetect)
        {
            if (target == null)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Target cannot be null"
                };
            }

            if (targetUsd <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Target USD must be positive"
                };
            }

            // Auto-detect strategy if requested
            var strategy = preferredStrategy;
            if (strategy == MatchingStrategy.AutoDetect)
            {
                var hasOb1 = HasOrderbook(algorithm, target.Leg1Symbol);
                var hasOb2 = HasOrderbook(algorithm, target.Leg2Symbol);

                if (hasOb1 && hasOb2)
                {
                    strategy = MatchingStrategy.DualOrderbook;
                }
                else if (hasOb1 || hasOb2)
                {
                    strategy = MatchingStrategy.SingleOrderbook;
                }
                else
                {
                    strategy = MatchingStrategy.BestPrices;
                }
            }

            // Execute matching based on strategy
            switch (strategy)
            {
                case MatchingStrategy.DualOrderbook:
                    return MatchDualOrderbook(algorithm, target, targetUsd);

                case MatchingStrategy.SingleOrderbook:
                    return MatchSingleOrderbook(algorithm, target, targetUsd);

                case MatchingStrategy.BestPrices:
                    return MatchBestPrices(algorithm, target, targetUsd);

                default:
                    return new MatchResult
                    {
                        Executable = false,
                        RejectReason = $"Unknown strategy: {strategy}"
                    };
            }
        }

        /// <summary>
        /// Match using dual orderbook (both sides have depth).
        /// Highest quality execution - validates spread at each level.
        /// </summary>
        private static MatchResult MatchDualOrderbook(
            IAlgorithm algorithm,
            IArbitragePortfolioTarget target,
            decimal targetUsd)
        {
            // Extract basic information
            var leg1Symbol = target.Leg1Symbol;
            var leg2Symbol = target.Leg2Symbol;
            var expectedSpreadPct = target.Level.SpreadPct;
            var leg1IsBuy = IsLeg1Buy(target);  // LONG_SPREAD: true, SHORT_SPREAD: false

            // Get orderbooks
            var leg1Orderbook = GetOrderbook(algorithm, leg1Symbol);
            var leg2Orderbook = GetOrderbook(algorithm, leg2Symbol);

            if (leg1Orderbook == null || leg2Orderbook == null)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Orderbook not available for one or both legs",
                    UsedStrategy = MatchingStrategy.DualOrderbook
                };
            }

            // Get corresponding levels (buy side uses asks, sell side uses bids)
            var leg1Levels = GetOrderbookLevels(leg1Orderbook, leg1IsBuy);
            var leg2Levels = GetOrderbookLevels(leg2Orderbook, !leg1IsBuy);

            if (leg1Levels == null || leg1Levels.Count == 0 ||
                leg2Levels == null || leg2Levels.Count == 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Orderbook levels empty",
                    UsedStrategy = MatchingStrategy.DualOrderbook
                };
            }

            // Get lot sizes
            var leg1LotSize = algorithm.Securities[leg1Symbol].SymbolProperties.LotSize;
            var leg2LotSize = algorithm.Securities[leg2Symbol].SymbolProperties.LotSize;

            // Two-pointer matching algorithm
            int i = 0, j = 0;
            decimal accumulatedUsd = 0;
            var matchedLevels = new List<MatchLevel>();

            while (i < leg1Levels.Count && j < leg2Levels.Count && accumulatedUsd < targetUsd)
            {
                var leg1Price = leg1Levels[i].Price;
                var leg2Price = leg2Levels[j].Price;
                var leg1Size = leg1Levels[i].Size;
                var leg2Size = leg2Levels[j].Size;

                // Calculate spread (no conversion needed!)
                var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);

                // Validate spread
                if (!ValidateSpread(spreadPct, expectedSpreadPct, leg1IsBuy))
                {
                    // Try better price on leg2 side
                    j++;
                    continue;
                }

                // Calculate matched quantities
                var remainingUsd = targetUsd - accumulatedUsd;
                var (matchedLeg1Qty, matchedLeg2Qty, matchUsd) = CalculateMatchedQuantitiesForLegs(
                    leg1Price, leg2Price,
                    leg1Size, leg2Size,
                    remainingUsd,
                    leg1LotSize, leg2LotSize,
                    leg1IsBuy
                );

                // Record valid match
                if (matchUsd > 0 && matchedLeg1Qty > 0 && matchedLeg2Qty > 0)
                {
                    matchedLevels.Add(new MatchLevel
                    {
                        Price1 = leg1Price,      // Direct correspondence!
                        Price2 = leg2Price,      // Direct correspondence!
                        Quantity1 = matchedLeg1Qty,  // Direct correspondence!
                        Quantity2 = matchedLeg2Qty,  // Direct correspondence!
                        UsdValue = matchUsd,
                        SpreadPct = spreadPct
                    });

                    accumulatedUsd += matchUsd;

                    // Move pointers based on consumed liquidity
                    if (matchedLeg1Qty >= leg1Size - leg1LotSize * 0.1m) // Within 10% of lot size
                    {
                        i++;
                    }
                    if (matchedLeg2Qty >= leg2Size - leg2LotSize * 0.1m)
                    {
                        j++;
                    }
                }
                else
                {
                    // No valid match at this level, move to next
                    i++;
                }
            }

            // Build and return result (no conversion needed!)
            return BuildMatchResult(matchedLevels, leg1IsBuy, leg1Symbol, leg2Symbol, MatchingStrategy.DualOrderbook);
        }

        /// <summary>
        /// Match using single orderbook (one side has depth, other uses best price).
        /// Medium quality execution - assumes infinite liquidity on price-only side.
        /// </summary>
        private static MatchResult MatchSingleOrderbook(
            IAlgorithm algorithm,
            IArbitragePortfolioTarget target,
            decimal targetUsd)
        {
            // Extract basic information
            var leg1Symbol = target.Leg1Symbol;
            var leg2Symbol = target.Leg2Symbol;
            var expectedSpreadPct = target.Level.SpreadPct;
            var leg1IsBuy = IsLeg1Buy(target);

            // Determine which leg has orderbook
            var hasOb1 = HasOrderbook(algorithm, leg1Symbol);
            var hasOb2 = HasOrderbook(algorithm, leg2Symbol);

            Symbol orderbookSymbol;
            Symbol priceOnlySymbol;
            bool orderbookIsLeg1;

            if (hasOb1)
            {
                orderbookSymbol = leg1Symbol;
                priceOnlySymbol = leg2Symbol;
                orderbookIsLeg1 = true;
            }
            else if (hasOb2)
            {
                orderbookSymbol = leg2Symbol;
                priceOnlySymbol = leg1Symbol;
                orderbookIsLeg1 = false;
            }
            else
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "No orderbook available for either leg",
                    UsedStrategy = MatchingStrategy.SingleOrderbook
                };
            }

            // Get orderbook and price-only security
            var orderbook = GetOrderbook(algorithm, orderbookSymbol);
            var priceOnlySecurity = algorithm.Securities[priceOnlySymbol];

            // Determine which leg is buy side
            bool orderbookIsBuy = orderbookIsLeg1 ? leg1IsBuy : !leg1IsBuy;

            // Get corresponding levels and price
            var orderbookLevels = GetOrderbookLevels(orderbook, orderbookIsBuy);
            var priceOnlyPrice = GetExecutionPrice(priceOnlySecurity, !orderbookIsBuy);

            if (priceOnlyPrice <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = $"Invalid price for {priceOnlySymbol}: {priceOnlyPrice}",
                    UsedStrategy = MatchingStrategy.SingleOrderbook
                };
            }

            // Get lot sizes
            var obLotSize = algorithm.Securities[orderbookSymbol].SymbolProperties.LotSize;
            var poLotSize = algorithm.Securities[priceOnlySymbol].SymbolProperties.LotSize;

            // Iterate through orderbook levels
            decimal accumulatedUsd = 0;
            var matchedLevels = new List<MatchLevel>();

            foreach (var level in orderbookLevels)
            {
                if (accumulatedUsd >= targetUsd)
                {
                    break;
                }

                var obPrice = level.Price;
                var obSize = level.Size;

                // Determine leg1/leg2 prices
                var leg1Price = orderbookIsLeg1 ? obPrice : priceOnlyPrice;
                var leg2Price = orderbookIsLeg1 ? priceOnlyPrice : obPrice;

                // Calculate spread
                var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);

                // Validate spread
                if (!ValidateSpread(spreadPct, expectedSpreadPct, leg1IsBuy))
                {
                    break; // Stop matching if spread no longer favorable
                }

                // Calculate matched quantities
                var remainingUsd = targetUsd - accumulatedUsd;

                // Set available sizes based on which leg has orderbook
                var leg1AvailableSize = orderbookIsLeg1 ? obSize : decimal.MaxValue;
                var leg2AvailableSize = orderbookIsLeg1 ? decimal.MaxValue : obSize;

                var (matchedLeg1Qty, matchedLeg2Qty, matchUsd) = CalculateMatchedQuantitiesForLegs(
                    leg1Price, leg2Price,
                    leg1AvailableSize, leg2AvailableSize,
                    remainingUsd,
                    orderbookIsLeg1 ? obLotSize : poLotSize,
                    orderbookIsLeg1 ? poLotSize : obLotSize,
                    leg1IsBuy
                );

                if (matchUsd > 0)
                {
                    matchedLevels.Add(new MatchLevel
                    {
                        Price1 = leg1Price,
                        Price2 = leg2Price,
                        Quantity1 = matchedLeg1Qty,
                        Quantity2 = matchedLeg2Qty,
                        UsdValue = matchUsd,
                        SpreadPct = spreadPct
                    });

                    accumulatedUsd += matchUsd;
                }
            }

            return BuildMatchResult(matchedLevels, leg1IsBuy, leg1Symbol, leg2Symbol, MatchingStrategy.SingleOrderbook);
        }

        /// <summary>
        /// Match using best prices only (no orderbook depth).
        /// Fallback strategy - simple matching using best bid/ask.
        /// </summary>
        private static MatchResult MatchBestPrices(
            IAlgorithm algorithm,
            IArbitragePortfolioTarget target,
            decimal targetUsd)
        {
            // Extract basic information
            var leg1Symbol = target.Leg1Symbol;
            var leg2Symbol = target.Leg2Symbol;
            var expectedSpreadPct = target.Level.SpreadPct;
            var leg1IsBuy = IsLeg1Buy(target);

            // Get securities
            if (!algorithm.Securities.ContainsKey(leg1Symbol) || !algorithm.Securities.ContainsKey(leg2Symbol))
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "One or both legs not found in securities",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            var leg1Security = algorithm.Securities[leg1Symbol];
            var leg2Security = algorithm.Securities[leg2Symbol];

            // Get execution prices (buy at ask, sell at bid)
            var leg1Price = GetExecutionPrice(leg1Security, leg1IsBuy);
            var leg2Price = GetExecutionPrice(leg2Security, !leg1IsBuy);

            if (leg1Price <= 0 || leg2Price <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = $"Invalid prices: leg1={leg1Price}, leg2={leg2Price}",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Calculate spread
            var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);
            if (!ValidateSpread(spreadPct, expectedSpreadPct, leg1IsBuy))
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = $"Spread {spreadPct:P2} does not meet expected {expectedSpreadPct:P2}",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Get lot sizes
            var leg1LotSize = leg1Security.SymbolProperties.LotSize;
            var leg2LotSize = leg2Security.SymbolProperties.LotSize;

            // Calculate quantities (assume infinite liquidity)
            var (leg1Qty, leg2Qty, matchUsd) = CalculateMatchedQuantitiesForLegs(
                leg1Price, leg2Price,
                decimal.MaxValue, decimal.MaxValue,
                targetUsd,
                leg1LotSize, leg2LotSize,
                leg1IsBuy
            );

            if (matchUsd <= 0 || leg1Qty <= 0 || leg2Qty <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Failed to calculate valid quantities",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Create match level (no conversion needed!)
            var matchedLevels = new List<MatchLevel>
            {
                new MatchLevel
                {
                    Price1 = leg1Price,
                    Price2 = leg2Price,
                    Quantity1 = leg1Qty,
                    Quantity2 = leg2Qty,
                    UsdValue = matchUsd,
                    SpreadPct = spreadPct
                }
            };

            return BuildMatchResult(matchedLevels, leg1IsBuy, leg1Symbol, leg2Symbol, MatchingStrategy.BestPrices);
        }

        #region Helper Methods

        /// <summary>
        /// Determine if Leg1 is the buy side based on arbitrage direction
        /// </summary>
        /// <param name="target">The arbitrage portfolio target</param>
        /// <returns>True if Leg1 is buy side (LONG_SPREAD), false if Leg1 is sell side (SHORT_SPREAD)</returns>
        private static bool IsLeg1Buy(IArbitragePortfolioTarget target)
        {
            // LONG_SPREAD: Buy Leg1, Sell Leg2
            // SHORT_SPREAD: Sell Leg1, Buy Leg2
            return target.Level.Direction == "LONG_SPREAD";
        }

        /// <summary>
        /// Get execution price for a security based on whether we're buying or selling
        /// </summary>
        /// <param name="security">The security</param>
        /// <param name="isBuy">True if buying (use ask), false if selling (use bid)</param>
        /// <returns>Execution price</returns>
        private static decimal GetExecutionPrice(Security security, bool isBuy)
        {
            return isBuy ? security.AskPrice : security.BidPrice;
        }

        /// <summary>
        /// Get orderbook levels for a security based on whether we're buying or selling
        /// </summary>
        /// <param name="orderbook">The orderbook depth</param>
        /// <param name="isBuy">True if buying (use asks), false if selling (use bids)</param>
        /// <returns>Orderbook levels</returns>
        private static IReadOnlyList<OrderbookLevel> GetOrderbookLevels(OrderbookDepth orderbook, bool isBuy)
        {
            return isBuy ? orderbook.Asks : orderbook.Bids;
        }

        /// <summary>
        /// Check if a symbol has orderbook depth available
        /// </summary>
        private static bool HasOrderbook(IAlgorithm algorithm, Symbol symbol)
        {
            if (!algorithm.Securities.ContainsKey(symbol))
            {
                return false;
            }

            var security = algorithm.Securities[symbol];
            var orderbook = security.Cache.OrderbookDepth;

            return orderbook != null
                && orderbook.Bids != null && orderbook.Bids.Count > 0
                && orderbook.Asks != null && orderbook.Asks.Count > 0;
        }

        /// <summary>
        /// Get orderbook depth for a symbol
        /// </summary>
        private static OrderbookDepth GetOrderbook(IAlgorithm algorithm, Symbol symbol)
        {
            if (!algorithm.Securities.ContainsKey(symbol))
            {
                return null;
            }

            return algorithm.Securities[symbol].Cache.OrderbookDepth;
        }

        /// <summary>
        /// Calculate spread percentage using unified formula: (Leg1Price - Leg2Price) / Leg1Price
        /// This matches TradingPair spread definition:
        /// - Long Spread: Buy leg1 at ask, sell leg2 at bid → (leg1_ask - leg2_bid) / leg1_ask
        /// - Short Spread: Sell leg1 at bid, buy leg2 at ask → (leg1_bid - leg2_ask) / leg1_bid
        ///
        /// In both cases, we use Leg1 as the numerator base.
        /// </summary>
        /// <param name="leg1Price">Price for symbol1 (leg1)</param>
        /// <param name="leg2Price">Price for symbol2 (leg2)</param>
        /// <returns>Spread percentage as decimal (e.g., 0.01 for 1%)</returns>
        private static decimal CalculateSpreadPct(decimal leg1Price, decimal leg2Price)
        {
            if (leg1Price == 0)
            {
                return decimal.MinValue;
            }

            return (leg1Price - leg2Price) / leg1Price;
        }

        /// <summary>
        /// Validate that actual spread meets expected spread threshold (using leg1IsBuy flag)
        /// </summary>
        /// <param name="actualSpreadPct">Actual spread percentage</param>
        /// <param name="expectedSpreadPct">Expected spread threshold</param>
        /// <param name="leg1IsBuy">True if leg1 is buy side (LONG_SPREAD), false if leg1 is sell side (SHORT_SPREAD)</param>
        /// <returns>True if spread is favorable</returns>
        private static bool ValidateSpread(
            decimal actualSpreadPct,
            decimal expectedSpreadPct,
            bool leg1IsBuy)
        {
            // For LONG_SPREAD (leg1IsBuy = true): We want spread to be LOW (negative is better)
            //   Spread = (Leg1Price - Leg2Price) / Leg1Price
            //   If Leg1 cheap, Leg2 expensive → negative spread → we buy cheap Leg1, sell expensive Leg2
            //   Validate: actualSpread <= expectedSpread (actual should be lower/more negative)
            //
            // For SHORT_SPREAD (leg1IsBuy = false): We want spread to be HIGH (positive is better)
            //   If Leg1 expensive, Leg2 cheap → positive spread → we sell expensive Leg1, buy cheap Leg2
            //   Validate: actualSpread >= expectedSpread (actual should be higher/more positive)

            return leg1IsBuy
                ? actualSpreadPct <= expectedSpreadPct  // LONG_SPREAD: Lower is better
                : actualSpreadPct >= expectedSpreadPct; // SHORT_SPREAD: Higher is better
        }

        /// <summary>
        /// Validate that actual spread meets expected spread threshold (using ArbitrageDirection enum)
        /// </summary>
        private static bool ValidateSpread(
            decimal actualSpreadPct,
            decimal expectedSpreadPct,
            ArbitrageDirection direction)
        {
            // For LONG_SPREAD: We want spread to be LOW (negative is better)
            //   Spread = (Leg1Price - Leg2Price) / Leg1Price
            //   If Leg1 cheap, Leg2 expensive → negative spread → we buy cheap Leg1, sell expensive Leg2
            //   Validate: actualSpread <= expectedSpread (actual should be lower/more negative)
            //
            // For SHORT_SPREAD: We want spread to be HIGH (positive is better)
            //   If Leg1 expensive, Leg2 cheap → positive spread → we sell expensive Leg1, buy cheap Leg2
            //   Validate: actualSpread >= expectedSpread (actual should be higher/more positive)

            return direction == ArbitrageDirection.LongSpread
                ? actualSpreadPct <= expectedSpreadPct  // ORIGINAL LOGIC: Lower is better for LONG
                : actualSpreadPct >= expectedSpreadPct; // Higher is better for SHORT
        }

        /// <summary>
        /// Round quantity to lot size
        /// </summary>
        private static decimal RoundToLot(decimal quantity, decimal lotSize)
        {
            if (lotSize <= 0)
            {
                return quantity;
            }

            // Round down to nearest lot
            return Math.Floor(Math.Abs(quantity) / lotSize) * lotSize * Math.Sign(quantity);
        }

        /// <summary>
        /// Calculate matched quantities for leg1 and leg2, ensuring market value equality
        /// </summary>
        /// <param name="leg1Price">Price for leg1</param>
        /// <param name="leg2Price">Price for leg2</param>
        /// <param name="availableLeg1Size">Available liquidity for leg1</param>
        /// <param name="availableLeg2Size">Available liquidity for leg2</param>
        /// <param name="targetUsd">Target USD value to match</param>
        /// <param name="leg1LotSize">Lot size for leg1</param>
        /// <param name="leg2LotSize">Lot size for leg2</param>
        /// <param name="leg1IsBuy">True if leg1 is buy side, false if leg1 is sell side</param>
        /// <returns>Tuple of (leg1Qty, leg2Qty, matchUsd)</returns>
        private static (decimal leg1Qty, decimal leg2Qty, decimal matchUsd) CalculateMatchedQuantitiesForLegs(
            decimal leg1Price,
            decimal leg2Price,
            decimal availableLeg1Size,
            decimal availableLeg2Size,
            decimal targetUsd,
            decimal leg1LotSize,
            decimal leg2LotSize,
            bool leg1IsBuy)
        {
            if (leg1Price <= 0 || leg2Price <= 0)
            {
                return (0, 0, 0);
            }

            // Determine which leg is buy and which is sell
            decimal buyPrice = leg1IsBuy ? leg1Price : leg2Price;
            decimal sellPrice = leg1IsBuy ? leg2Price : leg1Price;
            decimal availableBuySize = leg1IsBuy ? availableLeg1Size : availableLeg2Size;
            decimal availableSellSize = leg1IsBuy ? availableLeg2Size : availableLeg1Size;
            decimal buyLotSize = leg1IsBuy ? leg1LotSize : leg2LotSize;
            decimal sellLotSize = leg1IsBuy ? leg2LotSize : leg1LotSize;

            // Start with buy side
            var maxBuyQty = Math.Min(availableBuySize, targetUsd / buyPrice);
            maxBuyQty = RoundToLot(maxBuyQty, buyLotSize);

            if (maxBuyQty <= 0)
            {
                return (0, 0, 0);
            }

            // Calculate sell side for market value equality
            var buyUsd = maxBuyQty * buyPrice;
            var sellQty = buyUsd / sellPrice;
            sellQty = RoundToLot(sellQty, sellLotSize);

            // Check if sell side has enough liquidity
            if (sellQty > availableSellSize)
            {
                // Recalculate based on sell side constraint
                sellQty = RoundToLot(availableSellSize, sellLotSize);
                var sellUsd = sellQty * sellPrice;
                maxBuyQty = sellUsd / buyPrice;
                maxBuyQty = RoundToLot(maxBuyQty, buyLotSize);
                buyUsd = maxBuyQty * buyPrice;
            }

            // Convert back to leg1/leg2
            var leg1Qty = leg1IsBuy ? maxBuyQty : sellQty;
            var leg2Qty = leg1IsBuy ? sellQty : maxBuyQty;

            return (leg1Qty, leg2Qty, buyUsd);
        }

        /// <summary>
        /// Calculate matched quantities ensuring market value equality
        /// </summary>
        private static (decimal buyQty, decimal sellQty, decimal matchUsd) CalculateMatchedQuantities(
            decimal buyPrice,
            decimal sellPrice,
            decimal availableBuySize,
            decimal availableSellSize,
            decimal targetUsd,
            decimal buyLotSize,
            decimal sellLotSize)
        {
            if (buyPrice <= 0 || sellPrice <= 0)
            {
                return (0, 0, 0);
            }

            // Start with buy side
            var maxBuyQty = Math.Min(availableBuySize, targetUsd / buyPrice);
            maxBuyQty = RoundToLot(maxBuyQty, buyLotSize);

            if (maxBuyQty <= 0)
            {
                return (0, 0, 0);
            }

            // Calculate sell side for market value equality
            var buyUsd = maxBuyQty * buyPrice;
            var sellQty = buyUsd / sellPrice;
            sellQty = RoundToLot(sellQty, sellLotSize);

            // Check if sell side has enough liquidity
            if (sellQty > availableSellSize)
            {
                // Recalculate based on sell side constraint
                sellQty = RoundToLot(availableSellSize, sellLotSize);
                var sellUsd = sellQty * sellPrice;
                maxBuyQty = sellUsd / buyPrice;
                maxBuyQty = RoundToLot(maxBuyQty, buyLotSize);
                buyUsd = maxBuyQty * buyPrice;
            }

            return (maxBuyQty, sellQty, buyUsd);
        }

        /// <summary>
        /// Build final match result from matched levels (using leg1/leg2 naming)
        /// </summary>
        /// <param name="levels">List of matched orderbook levels</param>
        /// <param name="leg1IsBuy">True if leg1 is buy side, false if leg1 is sell side</param>
        /// <param name="leg1Symbol">Symbol for leg1</param>
        /// <param name="leg2Symbol">Symbol for leg2</param>
        /// <param name="usedStrategy">The matching strategy used</param>
        /// <returns>Match result with signed quantities</returns>
        private static MatchResult BuildMatchResult(
            List<MatchLevel> levels,
            bool leg1IsBuy,
            Symbol leg1Symbol,
            Symbol leg2Symbol,
            MatchingStrategy usedStrategy)
        {
            if (levels == null || levels.Count == 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "No valid matches found",
                    UsedStrategy = usedStrategy
                };
            }

            // Accumulate all levels
            decimal totalLeg1Qty = 0;
            decimal totalLeg2Qty = 0;
            decimal totalLeg1Usd = 0;
            decimal totalLeg2Usd = 0;
            decimal weightedSpreadSum = 0;

            foreach (var level in levels)
            {
                // Direct accumulation - no need to determine buy/sell
                totalLeg1Qty += level.Quantity1;
                totalLeg2Qty += level.Quantity2;
                totalLeg1Usd += level.Quantity1 * level.Price1;
                totalLeg2Usd += level.Quantity2 * level.Price2;
                weightedSpreadSum += level.SpreadPct * level.UsdValue;
            }

            // Calculate average prices
            var avgLeg1Price = totalLeg1Qty > 0 ? totalLeg1Usd / totalLeg1Qty : 0;
            var avgLeg2Price = totalLeg2Qty > 0 ? totalLeg2Usd / totalLeg2Qty : 0;
            var avgSpreadPct = (totalLeg1Usd + totalLeg2Usd) > 0
                ? weightedSpreadSum / (totalLeg1Usd + totalLeg2Usd)
                : 0;

            // Determine buy/sell average prices and USD
            var avgBuyPrice = leg1IsBuy ? avgLeg1Price : avgLeg2Price;
            var avgSellPrice = leg1IsBuy ? avgLeg2Price : avgLeg1Price;
            var totalBuyUsd = leg1IsBuy ? totalLeg1Usd : totalLeg2Usd;
            var totalSellUsd = leg1IsBuy ? totalLeg2Usd : totalLeg1Usd;

            // Set signed quantities (buy = positive, sell = negative)
            var symbol1Qty = leg1IsBuy ? totalLeg1Qty : -totalLeg1Qty;
            var symbol2Qty = leg1IsBuy ? -totalLeg2Qty : totalLeg2Qty;

            // Diagnostic logging
            Log.Trace($"[OrderbookMatcher.BuildMatchResult]");
            Log.Trace($"  → Leg1Symbol={leg1Symbol}, Leg2Symbol={leg2Symbol}, Leg1IsBuy={leg1IsBuy}");
            Log.Trace($"  → TotalLeg1Qty={totalLeg1Qty}, TotalLeg2Qty={totalLeg2Qty}");
            Log.Trace($"  → Symbol1Qty={symbol1Qty}, Symbol2Qty={symbol2Qty}");

            return new MatchResult
            {
                Symbol1Quantity = symbol1Qty,
                Symbol2Quantity = symbol2Qty,
                AvgBuyPrice = avgBuyPrice,
                AvgSellPrice = avgSellPrice,
                AvgSpreadPct = avgSpreadPct,
                TotalBuyUsd = totalBuyUsd,
                TotalSellUsd = totalSellUsd,
                Executable = true,
                MatchedLevels = levels,
                UsedStrategy = usedStrategy
            };
        }

        /// <summary>
        /// Build final match result from matched levels
        /// </summary>
        private static MatchResult BuildMatchResult(
            List<MatchLevel> levels,
            Symbol buySymbol,
            Symbol sellSymbol,
            Symbol symbol1,
            Symbol symbol2,
            MatchingStrategy usedStrategy)
        {
            if (levels == null || levels.Count == 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "No valid matches found",
                    UsedStrategy = usedStrategy
                };
            }

            // Aggregate results
            decimal totalBuyQty = 0;
            decimal totalSellQty = 0;
            decimal totalBuyUsd = 0;
            decimal totalSellUsd = 0;
            decimal weightedSpreadSum = 0;

            foreach (var level in levels)
            {
                // Determine which is buy and which is sell
                if (level.Price1 > level.Price2) // Assuming price1 is buy price
                {
                    totalBuyQty += level.Quantity1;
                    totalSellQty += level.Quantity2;
                    totalBuyUsd += level.Quantity1 * level.Price1;
                    totalSellUsd += level.Quantity2 * level.Price2;
                }
                else
                {
                    totalBuyQty += level.Quantity2;
                    totalSellQty += level.Quantity1;
                    totalBuyUsd += level.Quantity2 * level.Price2;
                    totalSellUsd += level.Quantity1 * level.Price1;
                }

                weightedSpreadSum += level.SpreadPct * level.UsdValue;
            }

            var avgBuyPrice = totalBuyQty > 0 ? totalBuyUsd / totalBuyQty : 0;
            var avgSellPrice = totalSellQty > 0 ? totalSellUsd / totalSellQty : 0;
            var avgSpreadPct = (totalBuyUsd + totalSellUsd) > 0
                ? weightedSpreadSum / (totalBuyUsd + totalSellUsd)
                : 0;

            // Determine signed quantities for symbol1 and symbol2
            var symbol1Qty = buySymbol == symbol1 ? totalBuyQty : -totalSellQty;
            var symbol2Qty = buySymbol == symbol2 ? totalBuyQty : -totalSellQty;

            // 🔍 DIAGNOSTIC: Log quantity assignment
            Log.Trace($"[OrderbookMatcher.BuildMatchResult]");
            Log.Trace($"  → BuySymbol={buySymbol}, SellSymbol={sellSymbol}");
            Log.Trace($"  → Symbol1={symbol1}, Symbol2={symbol2}");
            Log.Trace($"  → TotalBuyQty={totalBuyQty}, TotalSellQty={totalSellQty}");
            Log.Trace($"  → Symbol1Qty={symbol1Qty}, Symbol2Qty={symbol2Qty}");

            return new MatchResult
            {
                Symbol1Quantity = symbol1Qty,
                Symbol2Quantity = symbol2Qty,
                AvgBuyPrice = avgBuyPrice,
                AvgSellPrice = avgSellPrice,
                AvgSpreadPct = avgSpreadPct,
                TotalBuyUsd = totalBuyUsd,
                TotalSellUsd = totalSellUsd,
                Executable = true,
                MatchedLevels = levels,
                UsedStrategy = usedStrategy
            };
        }

        #endregion
    }
}
