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
        /// <param name="preferredStrategy">Preferred matching strategy</param>
        /// <returns>Match result with executable quantities, or null if matching fails</returns>
        public static MatchResult MatchPair(
            IAlgorithm algorithm,
            IArbitragePortfolioTarget target,
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

            // Extract parameters from target
            var symbol1 = target.Leg1Symbol;
            var symbol2 = target.Leg2Symbol;
            var targetQuantity1 = Math.Abs(target.Leg1Quantity);
            var expectedSpreadPct = target.Level.SpreadPct;

            // Convert grid level direction to ArbitrageDirection
            var direction = target.Level.Direction == "LONG_SPREAD"
                ? ArbitrageDirection.LongSpread
                : ArbitrageDirection.ShortSpread;

            if (targetQuantity1 <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Target quantity must be positive"
                };
            }

            // Calculate target USD from quantity for internal matching logic
            var security1 = algorithm.Securities[symbol1];
            var targetUsd = targetQuantity1 * security1.Price;

            // Auto-detect strategy if requested
            var strategy = preferredStrategy;
            if (strategy == MatchingStrategy.AutoDetect)
            {
                var hasOb1 = HasOrderbook(algorithm, symbol1);
                var hasOb2 = HasOrderbook(algorithm, symbol2);

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
                    return MatchDualOrderbook(algorithm, symbol1, symbol2, targetUsd, direction, expectedSpreadPct);

                case MatchingStrategy.SingleOrderbook:
                    return MatchSingleOrderbook(algorithm, symbol1, symbol2, targetUsd, direction, expectedSpreadPct);

                case MatchingStrategy.BestPrices:
                    return MatchBestPrices(algorithm, symbol1, symbol2, targetUsd, direction, expectedSpreadPct);

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
            Symbol symbol1,
            Symbol symbol2,
            decimal targetUsd,
            ArbitrageDirection direction,
            decimal expectedSpreadPct)
        {
            // Determine which symbol to buy and which to sell
            var (buySymbol, sellSymbol) = DetermineBuySellSides(symbol1, symbol2, direction);

            // Get orderbooks
            var buyOrderbook = GetOrderbook(algorithm, buySymbol);
            var sellOrderbook = GetOrderbook(algorithm, sellSymbol);

            if (buyOrderbook == null || sellOrderbook == null)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Orderbook not available for one or both symbols",
                    UsedStrategy = MatchingStrategy.DualOrderbook
                };
            }

            // Get buy and sell levels
            var buyLevels = buyOrderbook.Asks;  // Buy from asks
            var sellLevels = sellOrderbook.Bids; // Sell to bids

            if (buyLevels == null || buyLevels.Count == 0 || sellLevels == null || sellLevels.Count == 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Orderbook levels empty",
                    UsedStrategy = MatchingStrategy.DualOrderbook
                };
            }

            // Get lot sizes
            var buyLotSize = algorithm.Securities[buySymbol].SymbolProperties.LotSize;
            var sellLotSize = algorithm.Securities[sellSymbol].SymbolProperties.LotSize;

            // Two-pointer matching algorithm
            int i = 0, j = 0;
            decimal accumulatedUsd = 0;
            var matchedLevels = new List<MatchLevel>();

            while (i < buyLevels.Count && j < sellLevels.Count && accumulatedUsd < targetUsd)
            {
                var buyPrice = buyLevels[i].Price;
                var sellPrice = sellLevels[j].Price;
                var buySize = buyLevels[i].Size;
                var sellSize = sellLevels[j].Size;

                // Calculate spread using leg1/leg2 prices
                var leg1Price = (buySymbol == symbol1) ? buyPrice : sellPrice;
                var leg2Price = (buySymbol == symbol2) ? buyPrice : sellPrice;
                var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);

                // Validate spread meets expected threshold
                if (!ValidateSpread(spreadPct, expectedSpreadPct, direction))
                {
                    // Try to find better price on sell side
                    j++;
                    continue;
                }

                // Calculate matched quantities with market value equality
                var remainingUsd = targetUsd - accumulatedUsd;
                var (matchedBuyQty, matchedSellQty, matchUsd) = CalculateMatchedQuantities(
                    buyPrice,
                    sellPrice,
                    buySize,
                    sellSize,
                    remainingUsd,
                    buyLotSize,
                    sellLotSize
                );

                // If we got a valid match, record it
                if (matchUsd > 0 && matchedBuyQty > 0 && matchedSellQty > 0)
                {
                    // Determine price1 and price2 based on symbol order
                    var price1 = buySymbol == symbol1 ? buyPrice : sellPrice;
                    var price2 = buySymbol == symbol2 ? buyPrice : sellPrice;
                    var qty1 = buySymbol == symbol1 ? matchedBuyQty : matchedSellQty;
                    var qty2 = buySymbol == symbol2 ? matchedBuyQty : matchedSellQty;

                    matchedLevels.Add(new MatchLevel
                    {
                        Price1 = price1,
                        Price2 = price2,
                        Quantity1 = qty1,
                        Quantity2 = qty2,
                        UsdValue = matchUsd,
                        SpreadPct = spreadPct
                    });

                    accumulatedUsd += matchUsd;

                    // Move pointers based on consumed liquidity
                    if (matchedBuyQty >= buySize - buyLotSize * 0.1m) // Within 10% of lot size
                    {
                        i++;
                    }
                    if (matchedSellQty >= sellSize - sellLotSize * 0.1m)
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

            // Build and return result
            return BuildMatchResult(matchedLevels, buySymbol, sellSymbol, symbol1, symbol2, MatchingStrategy.DualOrderbook);
        }

        /// <summary>
        /// Match using single orderbook (one side has depth, other uses best price).
        /// Medium quality execution - assumes infinite liquidity on price-only side.
        /// </summary>
        private static MatchResult MatchSingleOrderbook(
            IAlgorithm algorithm,
            Symbol symbol1,
            Symbol symbol2,
            decimal targetUsd,
            ArbitrageDirection direction,
            decimal expectedSpreadPct)
        {
            // Determine which symbol has orderbook
            var hasOb1 = HasOrderbook(algorithm, symbol1);
            var hasOb2 = HasOrderbook(algorithm, symbol2);

            Symbol orderbookSymbol, priceOnlySymbol;
            if (hasOb1)
            {
                orderbookSymbol = symbol1;
                priceOnlySymbol = symbol2;
            }
            else if (hasOb2)
            {
                orderbookSymbol = symbol2;
                priceOnlySymbol = symbol1;
            }
            else
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "No orderbook available for either symbol",
                    UsedStrategy = MatchingStrategy.SingleOrderbook
                };
            }

            // Determine buy/sell sides
            var (buySymbol, sellSymbol) = DetermineBuySellSides(symbol1, symbol2, direction);

            // Get orderbook and best price
            var orderbook = GetOrderbook(algorithm, orderbookSymbol);
            var priceOnlySecurity = algorithm.Securities[priceOnlySymbol];

            // Determine which side has orderbook
            var isOrderbookBuy = (orderbookSymbol == buySymbol);
            var orderbookLevels = isOrderbookBuy ? orderbook.Asks : orderbook.Bids;
            var priceOnlyPrice = isOrderbookBuy ? priceOnlySecurity.BidPrice : priceOnlySecurity.AskPrice;

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

                // Calculate spread using leg1/leg2 prices
                var buyPrice = isOrderbookBuy ? obPrice : priceOnlyPrice;
                var sellPrice = isOrderbookBuy ? priceOnlyPrice : obPrice;
                var leg1Price = (orderbookSymbol == symbol1) ? obPrice : priceOnlyPrice;
                var leg2Price = (orderbookSymbol == symbol2) ? obPrice : priceOnlyPrice;
                var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);

                // Validate spread
                if (!ValidateSpread(spreadPct, expectedSpreadPct, direction))
                {
                    break; // Stop matching if spread no longer favorable
                }

                // Calculate matched quantities
                var remainingUsd = targetUsd - accumulatedUsd;
                var (matchedBuyQty, matchedSellQty, matchUsd) = isOrderbookBuy
                    ? CalculateMatchedQuantities(buyPrice, sellPrice, obSize, decimal.MaxValue, remainingUsd, obLotSize, poLotSize)
                    : CalculateMatchedQuantities(buyPrice, sellPrice, decimal.MaxValue, obSize, remainingUsd, poLotSize, obLotSize);

                if (matchUsd > 0)
                {
                    // Determine price1/price2 and qty1/qty2
                    var price1 = orderbookSymbol == symbol1 ? obPrice : priceOnlyPrice;
                    var price2 = orderbookSymbol == symbol2 ? obPrice : priceOnlyPrice;
                    var qty1 = orderbookSymbol == symbol1
                        ? (isOrderbookBuy ? matchedBuyQty : matchedSellQty)
                        : (isOrderbookBuy ? matchedSellQty : matchedBuyQty);
                    var qty2 = orderbookSymbol == symbol2
                        ? (isOrderbookBuy ? matchedBuyQty : matchedSellQty)
                        : (isOrderbookBuy ? matchedSellQty : matchedBuyQty);

                    matchedLevels.Add(new MatchLevel
                    {
                        Price1 = price1,
                        Price2 = price2,
                        Quantity1 = qty1,
                        Quantity2 = qty2,
                        UsdValue = matchUsd,
                        SpreadPct = spreadPct
                    });

                    accumulatedUsd += matchUsd;
                }
            }

            return BuildMatchResult(matchedLevels, buySymbol, sellSymbol, symbol1, symbol2, MatchingStrategy.SingleOrderbook);
        }

        /// <summary>
        /// Match using best prices only (no orderbook depth).
        /// Fallback strategy - simple matching using best bid/ask.
        /// </summary>
        private static MatchResult MatchBestPrices(
            IAlgorithm algorithm,
            Symbol symbol1,
            Symbol symbol2,
            decimal targetUsd,
            ArbitrageDirection direction,
            decimal expectedSpreadPct)
        {
            // Get securities
            if (!algorithm.Securities.ContainsKey(symbol1) || !algorithm.Securities.ContainsKey(symbol2))
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "One or both symbols not found in securities",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            var security1 = algorithm.Securities[symbol1];
            var security2 = algorithm.Securities[symbol2];

            // Determine buy/sell sides
            var (buySymbol, sellSymbol) = DetermineBuySellSides(symbol1, symbol2, direction);
            var buySecurity = buySymbol == symbol1 ? security1 : security2;
            var sellSecurity = buySymbol == symbol1 ? security2 : security1;

            // Get best prices
            var buyPrice = buySecurity.AskPrice; // Buy at ask
            var sellPrice = sellSecurity.BidPrice; // Sell at bid

            if (buyPrice <= 0 || sellPrice <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = $"Invalid prices: buy={buyPrice}, sell={sellPrice}",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Calculate spread using leg1/leg2 prices
            var leg1Price = (buySymbol == symbol1) ? buyPrice : sellPrice;
            var leg2Price = (buySymbol == symbol2) ? buyPrice : sellPrice;
            var spreadPct = CalculateSpreadPct(leg1Price, leg2Price);
            if (!ValidateSpread(spreadPct, expectedSpreadPct, direction))
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = $"Spread {spreadPct:P2} does not meet expected {expectedSpreadPct:P2}",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Get lot sizes
            var buyLotSize = buySecurity.SymbolProperties.LotSize;
            var sellLotSize = sellSecurity.SymbolProperties.LotSize;

            // Calculate quantities for market value equality
            var (buyQty, sellQty, matchUsd) = CalculateMatchedQuantities(
                buyPrice,
                sellPrice,
                decimal.MaxValue, // Assume infinite liquidity
                decimal.MaxValue,
                targetUsd,
                buyLotSize,
                sellLotSize
            );

            if (matchUsd <= 0 || buyQty <= 0 || sellQty <= 0)
            {
                return new MatchResult
                {
                    Executable = false,
                    RejectReason = "Failed to calculate valid quantities",
                    UsedStrategy = MatchingStrategy.BestPrices
                };
            }

            // Create match level
            var price1 = buySymbol == symbol1 ? buyPrice : sellPrice;
            var price2 = buySymbol == symbol2 ? buyPrice : sellPrice;
            var qty1 = buySymbol == symbol1 ? buyQty : sellQty;
            var qty2 = buySymbol == symbol2 ? buyQty : sellQty;

            var matchedLevels = new List<MatchLevel>
            {
                new MatchLevel
                {
                    Price1 = price1,
                    Price2 = price2,
                    Quantity1 = qty1,
                    Quantity2 = qty2,
                    UsdValue = matchUsd,
                    SpreadPct = spreadPct
                }
            };

            return BuildMatchResult(matchedLevels, buySymbol, sellSymbol, symbol1, symbol2, MatchingStrategy.BestPrices);
        }

        #region Helper Methods

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
        /// Determine which symbol to buy and which to sell based on direction
        /// </summary>
        private static (Symbol buy, Symbol sell) DetermineBuySellSides(
            Symbol symbol1,
            Symbol symbol2,
            ArbitrageDirection direction)
        {
            // LongSpread: Buy symbol1, sell symbol2 (expect symbol1 cheaper)
            // ShortSpread: Sell symbol1, buy symbol2 (expect symbol1 more expensive)
            return direction == ArbitrageDirection.LongSpread
                ? (symbol1, symbol2)
                : (symbol2, symbol1);
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
        /// Validate that actual spread meets expected spread threshold
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
