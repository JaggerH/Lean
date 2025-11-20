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
using QuantConnect.Securities;

namespace QuantConnect.TradingPairs
{
    /// <summary>
    /// Represents a trading pair consisting of two securities with automatic spread calculation
    /// </summary>
    public class TradingPair
    {
        private const decimal EPSILON = 1e-10m;

        /// <summary>
        /// Gets the symbol of the first leg
        /// </summary>
        public Symbol Leg1Symbol { get; }

        /// <summary>
        /// Gets the symbol of the second leg
        /// </summary>
        public Symbol Leg2Symbol { get; }

        /// <summary>
        /// Gets the security object for the first leg
        /// </summary>
        public Security Leg1Security { get; }

        /// <summary>
        /// Gets the security object for the second leg
        /// </summary>
        public Security Leg2Security { get; }

        /// <summary>
        /// Gets the type of trading pair (e.g., "spread", "tokenized", "futures")
        /// </summary>
        public string PairType { get; }

        /// <summary>
        /// Gets the string key representation of this trading pair (for display and logging only)
        /// </summary>
        public string Key => $"{Leg1Symbol}-{Leg2Symbol}";

        // Dynamic properties that read from Security.Cache
        /// <summary>
        /// Gets the current bid price of the first leg
        /// </summary>
        public decimal Leg1BidPrice => Leg1Security.BidPrice;

        /// <summary>
        /// Gets the current ask price of the first leg
        /// </summary>
        public decimal Leg1AskPrice => Leg1Security.AskPrice;

        /// <summary>
        /// Gets the current bid price of the second leg
        /// </summary>
        public decimal Leg2BidPrice => Leg2Security.BidPrice;

        /// <summary>
        /// Gets the current ask price of the second leg
        /// </summary>
        public decimal Leg2AskPrice => Leg2Security.AskPrice;

        /// <summary>
        /// Gets the current mid price of the first leg
        /// </summary>
        public decimal Leg1MidPrice => (Leg1BidPrice + Leg1AskPrice) / 2;

        /// <summary>
        /// Gets the current mid price of the second leg
        /// </summary>
        public decimal Leg2MidPrice => (Leg2BidPrice + Leg2AskPrice) / 2;

        // Calculated spread properties (all values are percentages)
        /// <summary>
        /// Gets the theoretical spread percentage (selected from short_spread or long_spread by absolute value, keeps sign)
        /// Positive: leg1 > leg2, Negative: leg2 > leg1
        /// </summary>
        public decimal TheoreticalSpread { get; private set; }

        /// <summary>
        /// Gets the executable spread percentage when an opportunity exists (CROSSED or LIMIT_OPPORTUNITY)
        /// For CROSSED: equals ShortSpread or LongSpread depending on direction
        /// For LIMIT_OPPORTUNITY: calculated based on overlapping quote ranges
        /// For other states: null
        /// </summary>
        public decimal? ExecutableSpread { get; private set; }

        /// <summary>
        /// Gets the short spread percentage: profit when selling leg1 and buying leg2
        /// Formula: (leg1_bid - leg2_ask) / leg1_bid
        /// </summary>
        public decimal ShortSpread { get; private set; }

        /// <summary>
        /// Gets the long spread percentage: profit when buying leg1 and selling leg2
        /// Formula: (leg1_ask - leg2_bid) / leg1_ask
        /// Note: Negative when leg2 > leg1 (which is when this arbitrage is profitable)
        /// </summary>
        public decimal LongSpread { get; private set; }

        /// <summary>
        /// Gets the current market state
        /// </summary>
        public MarketState MarketState { get; private set; }

        /// <summary>
        /// Gets the arbitrage direction ("buy_leg1_sell_leg2", "buy_leg2_sell_leg1", or "none")
        /// </summary>
        public string Direction { get; private set; }

        /// <summary>
        /// Gets whether valid price data is available for both legs
        /// </summary>
        public bool HasValidPrices { get; private set; }

        /// <summary>
        /// Gets the timestamp of the most recent update
        /// </summary>
        public DateTime LastUpdateTime { get; private set; }

        /// <summary>
        /// Initializes a new instance of the <see cref="TradingPair"/> class
        /// </summary>
        public TradingPair(Symbol leg1Symbol, Symbol leg2Symbol, string pairType, Security leg1Security, Security leg2Security)
        {
            Leg1Symbol = leg1Symbol;
            Leg2Symbol = leg2Symbol;
            PairType = pairType;
            Leg1Security = leg1Security;
            Leg2Security = leg2Security;
            Direction = "none";
            MarketState = MarketState.Unknown;
        }

        /// <summary>
        /// Updates the spread calculations based on current security prices
        /// </summary>
        public void Update()
        {
            LastUpdateTime = Leg1Security.LocalTime;

            // Check if we have valid prices
            HasValidPrices = CheckValidPrices();

            if (!HasValidPrices)
            {
                MarketState = MarketState.Unknown;
                Direction = "none";
                ExecutableSpread = null;
                return;
            }

            CalculateSpreads();
            DetermineMarketState();
            DetermineArbitrageDirection();
            CalculateExecutableSpread();
        }

        /// <summary>
        /// Checks if both legs have valid price data
        /// </summary>
        private bool CheckValidPrices()
        {
            return Leg1BidPrice > EPSILON &&
                   Leg1AskPrice > EPSILON &&
                   Leg2BidPrice > EPSILON &&
                   Leg2AskPrice > EPSILON &&
                   Leg1BidPrice <= Leg1AskPrice &&
                   Leg2BidPrice <= Leg2AskPrice;
        }

        /// <summary>
        /// Calculates various spread metrics using percentage-based formulas
        /// Ported from Python calculate_spread_pct method
        /// </summary>
        private void CalculateSpreads()
        {
            // Calculate short spread: profit percentage when selling leg1 and buying leg2
            // Formula: (leg1_bid - leg2_ask) / leg1_bid
            ShortSpread = Leg1BidPrice > EPSILON
                ? (Leg1BidPrice - Leg2AskPrice) / Leg1BidPrice
                : 0m;

            // Calculate long spread: profit percentage when buying leg1 and selling leg2
            // Formula: (leg1_ask - leg2_bid) / leg1_ask
            // Note: This is negative when leg2 > leg1 (which is when longing the spread is profitable)
            LongSpread = Leg1AskPrice > EPSILON
                ? (Leg1AskPrice - Leg2BidPrice) / Leg1AskPrice
                : 0m;

            // Theoretical spread: select by absolute value magnitude, keep the sign
            // Positive indicates leg1 > leg2, negative indicates leg2 > leg1
            TheoreticalSpread = Math.Abs(ShortSpread) >= Math.Abs(LongSpread)
                ? ShortSpread
                : LongSpread;
        }

        /// <summary>
        /// Determines the current market state based on spreads
        /// Ported from Python calculate_spread_pct method
        /// </summary>
        private void DetermineMarketState()
        {
            // Check for CROSSED market: leg1_bid > leg2_ask (SHORT_SPREAD opportunity)
            if (Leg1BidPrice > Leg2AskPrice)
            {
                MarketState = MarketState.Crossed;
                return;
            }

            // Check for CROSSED market: leg2_bid > leg1_ask (LONG_SPREAD opportunity)
            if (Leg2BidPrice > Leg1AskPrice)
            {
                MarketState = MarketState.Crossed;
                return;
            }

            // Check for LIMIT_OPPORTUNITY (overlapping quote ranges)
            // Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid
            if (Leg1AskPrice > Leg2AskPrice && Leg2AskPrice > Leg1BidPrice && Leg1BidPrice > Leg2BidPrice)
            {
                MarketState = MarketState.LimitOpportunity;
                return;
            }

            // Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid
            if (Leg2AskPrice > Leg1AskPrice && Leg1AskPrice > Leg2BidPrice && Leg2BidPrice > Leg1BidPrice)
            {
                MarketState = MarketState.LimitOpportunity;
                return;
            }

            // Otherwise NO_OPPORTUNITY
            MarketState = MarketState.NoOpportunity;
        }

        /// <summary>
        /// Determines the arbitrage direction based on market state
        /// Ported from Python calculate_spread_pct method
        /// </summary>
        private void DetermineArbitrageDirection()
        {
            // CROSSED market
            if (MarketState == MarketState.Crossed)
            {
                // Check which type of crossing: SHORT_SPREAD or LONG_SPREAD
                if (Leg1BidPrice > Leg2AskPrice)
                {
                    // SHORT_SPREAD: sell leg1, buy leg2
                    Direction = "SHORT_SPREAD";
                }
                else if (Leg2BidPrice > Leg1AskPrice)
                {
                    // LONG_SPREAD: buy leg1, sell leg2
                    Direction = "LONG_SPREAD";
                }
                else
                {
                    Direction = "none";
                }
                return;
            }

            // LIMIT_OPPORTUNITY market
            if (MarketState == MarketState.LimitOpportunity)
            {
                // Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid -> SHORT_SPREAD
                if (Leg1AskPrice > Leg2AskPrice && Leg2AskPrice > Leg1BidPrice && Leg1BidPrice > Leg2BidPrice)
                {
                    Direction = "SHORT_SPREAD";
                }
                // Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid -> LONG_SPREAD
                else if (Leg2AskPrice > Leg1AskPrice && Leg1AskPrice > Leg2BidPrice && Leg2BidPrice > Leg1BidPrice)
                {
                    Direction = "LONG_SPREAD";
                }
                else
                {
                    Direction = "none";
                }
                return;
            }

            // No opportunity
            Direction = "none";
        }

        /// <summary>
        /// Calculates the executable spread based on market state and direction
        /// Ported from Python calculate_spread_pct method
        /// </summary>
        private void CalculateExecutableSpread()
        {
            // CROSSED market: executable spread is either short_spread or long_spread
            if (MarketState == MarketState.Crossed)
            {
                if (Direction == "SHORT_SPREAD")
                {
                    ExecutableSpread = ShortSpread;
                }
                else if (Direction == "LONG_SPREAD")
                {
                    ExecutableSpread = LongSpread;
                }
                else
                {
                    ExecutableSpread = null;
                }
                return;
            }

            // LIMIT_OPPORTUNITY market: calculate based on overlapping quote ranges
            if (MarketState == MarketState.LimitOpportunity)
            {
                // Pattern 1: leg1_ask > leg2_ask > leg1_bid > leg2_bid -> SHORT_SPREAD
                if (Leg1AskPrice > Leg2AskPrice && Leg2AskPrice > Leg1BidPrice && Leg1BidPrice > Leg2BidPrice)
                {
                    var spread1 = Leg1AskPrice > EPSILON ? (Leg1AskPrice - Leg2AskPrice) / Leg1AskPrice : 0m;
                    var spread2 = Leg1BidPrice > EPSILON ? (Leg1BidPrice - Leg2BidPrice) / Leg1BidPrice : 0m;
                    ExecutableSpread = Math.Max(spread1, spread2);
                }
                // Pattern 2: leg2_ask > leg1_ask > leg2_bid > leg1_bid -> LONG_SPREAD
                else if (Leg2AskPrice > Leg1AskPrice && Leg1AskPrice > Leg2BidPrice && Leg2BidPrice > Leg1BidPrice)
                {
                    var spread1 = Leg1AskPrice > EPSILON ? (Leg1AskPrice - Leg2BidPrice) / Leg1AskPrice : 0m;
                    var spread2 = Leg1BidPrice > EPSILON ? (Leg1BidPrice - Leg2AskPrice) / Leg1BidPrice : 0m;
                    ExecutableSpread = Math.Min(spread1, spread2);
                }
                else
                {
                    ExecutableSpread = null;
                }
                return;
            }

            // No opportunity
            ExecutableSpread = null;
        }

        /// <summary>
        /// Returns a string representation of the trading pair
        /// </summary>
        public override string ToString()
        {
            var execSpreadStr = ExecutableSpread.HasValue ? $"{ExecutableSpread.Value:P2}" : "None";
            return $"TradingPair({Key}, Type={PairType}, TheoreticalSpread={TheoreticalSpread:P2}, ExecutableSpread={execSpreadStr}, State={MarketState}, Direction={Direction})";
        }
    }
}