# QUANTCONNECT.COM - Democratizing Finance, Empowering Individuals.
# Lean Algorithmic Trading Engine v2.0. Copyright 2014 QuantConnect Corporation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from AlgorithmImports import *
from QuantConnect.TradingPairs import MarketState

class TradingPairArbitrageAlgorithm(QCAlgorithm):
    '''
    Demonstrates the usage of TradingPair functionality for arbitrage trading.
    This algorithm creates trading pairs and monitors them for arbitrage opportunities.
    '''

    def Initialize(self):
        '''Initialize the algorithm and setup trading pairs'''

        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 12, 31)
        self.SetCash(100000)

        # Add securities
        self.spy = self.AddEquity("SPY", Resolution.Minute).Symbol
        self.qqq = self.AddEquity("QQQ", Resolution.Minute).Symbol
        self.btc = self.AddCrypto("BTCUSD", Resolution.Minute).Symbol
        self.eth = self.AddCrypto("ETHUSD", Resolution.Minute).Symbol

        # Create trading pairs
        self.spy_qqq_pair = self.AddTradingPair(self.spy, self.qqq, "spread")
        self.btc_eth_pair = self.AddTradingPair(self.btc, self.eth, "crypto_spread")

        self.Log(f"Created trading pairs: {self.spy_qqq_pair.Key} and {self.btc_eth_pair.Key}")

        # Track arbitrage opportunities
        self.last_arbitrage_time = {}
        self.min_time_between_trades = timedelta(minutes=5)

        # Set warmup period
        self.SetWarmUp(100)

    def OnData(self, slice):
        '''Process incoming data and check for arbitrage opportunities'''

        if self.IsWarmingUp:
            return

        # Access trading pairs through the TradingPairs manager
        # Method 1: Access by tuple (type-safe)
        spy_qqq = self.TradingPairs[(self.spy, self.qqq)]
        btc_eth = self.TradingPairs[(self.btc, self.eth)]

        # Method 2: Direct access to saved reference (recommended for performance)
        # spy_qqq = self.spy_qqq_pair
        # btc_eth = self.btc_eth_pair

        # Check SPY-QQQ pair
        self.CheckArbitrage(spy_qqq, 0.01)  # 1% threshold

        # Check BTC-ETH pair
        self.CheckArbitrage(btc_eth, 0.005)  # 0.5% threshold

        # Log spread information every hour
        if self.Time.minute == 0 and self.Time.hour % 1 == 0:
            self.LogSpreadInfo()

    def CheckArbitrage(self, pair, threshold):
        '''Check if a trading pair has arbitrage opportunity'''

        # Check if prices are valid
        if not pair.HasValidPrices:
            return

        # Check market state
        if pair.MarketState == MarketState.Crossed:
            # Check if we've traded this pair recently
            if pair.Key in self.last_arbitrage_time:
                time_since_last = self.Time - self.last_arbitrage_time[pair.Key]
                if time_since_last < self.min_time_between_trades:
                    return

            # Log arbitrage opportunity
            self.Log(f"ARBITRAGE OPPORTUNITY: {pair.Key}")
            self.Log(f"  Executable Spread: {pair.ExecutableSpread:.4%}")
            self.Log(f"  Direction: {pair.Direction}")
            self.Log(f"  Leg1 Bid/Ask: {pair.Leg1BidPrice}/{pair.Leg1AskPrice}")
            self.Log(f"  Leg2 Bid/Ask: {pair.Leg2BidPrice}/{pair.Leg2AskPrice}")

            # Execute arbitrage (simplified example)
            self.ExecuteArbitrage(pair, threshold)

            # Update last trade time
            self.last_arbitrage_time[pair.Key] = self.Time

        # Monitor inverted spreads
        elif pair.MarketState == MarketState.Inverted:
            if abs(pair.TheoreticalSpread) > threshold * 100:
                self.Debug(f"Warning: {pair.Key} is inverted with spread {pair.TheoreticalSpread:.4f}")

    def ExecuteArbitrage(self, pair, threshold):
        '''Execute arbitrage trade (simplified example)'''

        # Calculate position sizes
        portfolio_value = self.Portfolio.TotalPortfolioValue
        position_size = portfolio_value * 0.1  # Use 10% of portfolio

        if pair.Direction == "SHORT_SPREAD":
            # SHORT_SPREAD: sell leg1, buy leg2
            leg1_quantity = int(position_size / pair.Leg1BidPrice)
            leg2_quantity = int(position_size / pair.Leg2AskPrice)

            if leg1_quantity > 0 and leg2_quantity > 0:
                self.MarketOrder(pair.Leg1Symbol, -leg1_quantity)
                self.MarketOrder(pair.Leg2Symbol, leg2_quantity)
                self.Log(f"Executed arbitrage: Sell {leg1_quantity} {pair.Leg1Symbol.Value}, Buy {leg2_quantity} {pair.Leg2Symbol.Value}")

        elif pair.Direction == "LONG_SPREAD":
            # LONG_SPREAD: buy leg1, sell leg2
            leg1_quantity = int(position_size / pair.Leg1AskPrice)
            leg2_quantity = int(position_size / pair.Leg2BidPrice)

            if leg1_quantity > 0 and leg2_quantity > 0:
                self.MarketOrder(pair.Leg1Symbol, leg1_quantity)
                self.MarketOrder(pair.Leg2Symbol, -leg2_quantity)
                self.Log(f"Executed arbitrage: Buy {leg1_quantity} {pair.Leg1Symbol.Value}, Sell {leg2_quantity} {pair.Leg2Symbol.Value}")

    def LogSpreadInfo(self):
        '''Log current spread information for all pairs'''

        self.Log("=== Hourly Spread Report ===")

        # Iterate through all trading pairs
        for pair in self.TradingPairs:
            if pair.HasValidPrices:
                self.Log(f"{pair.Key}:")
                self.Log(f"  Theoretical Spread: {pair.TheoreticalSpread:.4%}")
                self.Log(f"  Short Spread: {pair.ShortSpread:.4%}")
                self.Log(f"  Long Spread: {pair.LongSpread:.4%}")
                self.Log(f"  Market State: {pair.MarketState}")

    def OnEndOfAlgorithm(self):
        '''Called at the end of the algorithm'''

        self.Log("=== Final Trading Pair Statistics ===")

        # Get all crossed pairs
        crossed_pairs = self.TradingPairs.GetCrossedPairs()
        self.Log(f"Total crossed pairs at end: {len(list(crossed_pairs))}")

        # Log final state of all pairs
        for pair in self.TradingPairs:
            exec_spread = f"{pair.ExecutableSpread:.4%}" if pair.ExecutableSpread is not None else "None"
            self.Log(f"{pair.Key}: Theoretical={pair.TheoreticalSpread:.4%}, Executable={exec_spread}, State={pair.MarketState}")