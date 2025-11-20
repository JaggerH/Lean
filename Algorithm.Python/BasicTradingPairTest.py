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

class BasicTradingPairTest(QCAlgorithm):
    '''
    Basic test algorithm to verify TradingPair functionality.
    Tests the creation of trading pairs and automatic spread calculation.
    '''

    def Initialize(self):
        '''Initialize the algorithm with simple trading pair setup'''

        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 1, 31)
        self.SetCash(10000)

        # Add two equities
        self.aapl = self.AddEquity("AAPL", Resolution.Minute).Symbol
        self.msft = self.AddEquity("MSFT", Resolution.Minute).Symbol

        # Create a trading pair
        self.pair = self.AddTradingPair(self.aapl, self.msft, "tech_spread")

        self.Log(f"Created trading pair: {self.pair.Key}")
        self.Log(f"Pair type: {self.pair.PairType}")

        # Schedule periodic logging
        self.Schedule.On(
            self.DateRules.EveryDay(self.aapl),
            self.TimeRules.Every(timedelta(hours=1)),
            self.LogPairStatus
        )

        self.data_points = 0
        self.crossed_count = 0
        self.inverted_count = 0

    def OnData(self, slice):
        '''Process incoming data'''

        if self.IsWarmingUp:
            return

        self.data_points += 1

        # Access the pair - use saved reference for best performance
        pair = self.pair
        # Alternative: Access by tuple
        # pair = self.TradingPairs[(self.aapl, self.msft)]

        # Check if we have valid prices
        if not pair.HasValidPrices:
            return

        # Track market states
        if pair.MarketState == MarketState.Crossed:
            self.crossed_count += 1
            self.Log(f"[{self.Time}] CROSSED MARKET DETECTED!")
            self.Log(f"  Spread: {pair.Spread:.4f}")
            self.Log(f"  Direction: {pair.Direction}")
            self.Log(f"  AAPL Bid/Ask: {pair.Leg1BidPrice:.2f}/{pair.Leg1AskPrice:.2f}")
            self.Log(f"  MSFT Bid/Ask: {pair.Leg2BidPrice:.2f}/{pair.Leg2AskPrice:.2f}")

        elif pair.MarketState == MarketState.Inverted:
            self.inverted_count += 1

        # Log first few data points for verification
        if self.data_points <= 10:
            self.Debug(f"Data point {self.data_points}:")
            self.Debug(f"  AAPL: {pair.Leg1BidPrice:.2f}/{pair.Leg1AskPrice:.2f}")
            self.Debug(f"  MSFT: {pair.Leg2BidPrice:.2f}/{pair.Leg2AskPrice:.2f}")
            self.Debug(f"  Theoretical Spread: {pair.TheoreticalSpread:.4f}")
            self.Debug(f"  Market State: {pair.MarketState}")

    def LogPairStatus(self):
        '''Log current status of the trading pair'''

        # Use saved reference
        pair = self.pair

        if pair.HasValidPrices:
            self.Log(f"=== Pair Status at {self.Time} ===")
            self.Log(f"Pair: {pair.Key}")
            self.Log(f"AAPL Mid: {pair.Leg1MidPrice:.2f}")
            self.Log(f"MSFT Mid: {pair.Leg2MidPrice:.2f}")
            self.Log(f"Theoretical Spread: {pair.TheoreticalSpread:.4f}")
            self.Log(f"Bid Spread: {pair.BidSpread:.4f}")
            self.Log(f"Ask Spread: {pair.AskSpread:.4f}")
            self.Log(f"Market State: {pair.MarketState}")

    def OnEndOfAlgorithm(self):
        '''Log final statistics'''

        self.Log("=== Algorithm Complete ===")
        self.Log(f"Total data points: {self.data_points}")
        self.Log(f"Crossed markets detected: {self.crossed_count}")
        self.Log(f"Inverted markets detected: {self.inverted_count}")

        # Check TradingPairs manager functionality
        self.Log(f"Number of trading pairs: {self.TradingPairs.Count}")

        # Test iteration
        self.Log("All trading pairs:")
        for pair in self.TradingPairs:
            self.Log(f"  - {pair.Key} ({pair.PairType})")

        # Test GetCrossedPairs
        crossed = list(self.TradingPairs.GetCrossedPairs())
        self.Log(f"Currently crossed pairs: {len(crossed)}")

        # Test GetByState
        normal_pairs = list(self.TradingPairs.GetByState(MarketState.Normal))
        self.Log(f"Normal state pairs: {len(normal_pairs)}")