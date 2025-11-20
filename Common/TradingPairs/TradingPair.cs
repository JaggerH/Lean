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

        // Calculated spread properties
        /// <summary>
        /// Gets the current spread between the two legs
        /// </summary>
        public decimal Spread { get; private set; }

        /// <summary>
        /// Gets the theoretical spread based on mid prices
        /// </summary>
        public decimal TheoreticalSpread { get; private set; }

        /// <summary>
        /// Gets the bid spread (best case when buying leg1 and selling leg2)
        /// </summary>
        public decimal BidSpread { get; private set; }

        /// <summary>
        /// Gets the ask spread (best case when selling leg1 and buying leg2)
        /// </summary>
        public decimal AskSpread { get; private set; }

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
                return;
            }

            CalculateSpreads();
            DetermineMarketState();
            DetermineArbitrageDirection();
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
        /// Calculates various spread metrics
        /// </summary>
        private void CalculateSpreads()
        {
            // Theoretical spread (mid-to-mid)
            TheoreticalSpread = Leg1MidPrice - Leg2MidPrice;

            // Bid spread: profit when buying leg1 at ask and selling leg2 at bid
            BidSpread = Leg2BidPrice - Leg1AskPrice;

            // Ask spread: profit when selling leg1 at bid and buying leg2 at ask
            AskSpread = Leg1BidPrice - Leg2AskPrice;

            // The main spread is the best executable spread
            Spread = Math.Max(BidSpread, AskSpread);
        }

        /// <summary>
        /// Determines the current market state based on spreads
        /// </summary>
        private void DetermineMarketState()
        {
            if (BidSpread > EPSILON || AskSpread > EPSILON)
            {
                MarketState = MarketState.Crossed;
            }
            else if (TheoreticalSpread < -EPSILON)
            {
                MarketState = MarketState.Inverted;
            }
            else
            {
                MarketState = MarketState.Normal;
            }
        }

        /// <summary>
        /// Determines the arbitrage direction if market is crossed
        /// </summary>
        private void DetermineArbitrageDirection()
        {
            if (MarketState != MarketState.Crossed)
            {
                Direction = "none";
                return;
            }

            if (BidSpread > AskSpread)
            {
                // More profitable to buy leg1 and sell leg2
                Direction = "buy_leg1_sell_leg2";
            }
            else
            {
                // More profitable to sell leg1 and buy leg2
                Direction = "buy_leg2_sell_leg1";
            }
        }

        /// <summary>
        /// Returns a string representation of the trading pair
        /// </summary>
        public override string ToString()
        {
            return $"TradingPair({Key}, Type={PairType}, Spread={Spread:F4}, State={MarketState})";
        }
    }
}