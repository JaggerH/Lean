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

class TradingPairSliceIntegrationTest(QCAlgorithm):
    '''
    Test algorithm to verify TradingPair functionality with algorithm-level access.
    Tests accessing TradingPairs through self.TradingPairs in OnData.

    NOTE: TradingPairs are accessed via algorithm.TradingPairs, not slice.TradingPairs.
    This aligns with the arbitrage framework refactor where TradingPairs are
    algorithm-managed state rather than time-series market data.
    '''

    def Initialize(self):
        '''Initialize the algorithm with trading pairs and schedule checks'''

        self.SetStartDate(2024, 1, 1)
        self.SetEndDate(2024, 1, 31)
        self.SetCash(50000)

        # Add securities for trading pairs
        self.spy = self.AddEquity("SPY", Resolution.Minute).Symbol
        self.qqq = self.AddEquity("QQQ", Resolution.Minute).Symbol
        self.iwm = self.AddEquity("IWM", Resolution.Minute).Symbol

        # Create multiple trading pairs
        self.pair1 = self.AddTradingPair(self.spy, self.qqq, "spy_qqq_pair")
        self.pair2 = self.AddTradingPair(self.spy, self.iwm, "spy_iwm_pair")
        self.pair3 = self.AddTradingPair(self.qqq, self.iwm, "qqq_iwm_pair")

        self.Log(f"Created {self.TradingPairs.Count} trading pairs")

        # Track data for validation
        self.algorithm_access_count = 0
        self.pairs_count_history = []
        self.crossed_detected = 0
        self.inverted_detected = 0

        # Schedule periodic status reports
        self.Schedule.On(
            self.DateRules.EveryDay(self.spy),
            self.TimeRules.Every(timedelta(hours=2)),
            self.LogTradingPairStatus
        )

    def OnData(self, slice):
        '''Process data and test algorithm.TradingPairs access'''

        if self.IsWarmingUp:
            return

        # Test 1: Access TradingPairs through algorithm (not slice)
        if hasattr(self, 'TradingPairs') and self.TradingPairs is not None:
            self.algorithm_access_count += 1
            self.pairs_count_history.append(self.TradingPairs.Count)

            # Test 2: Iterate through pairs
            for pair in self.TradingPairs:
                if pair.HasValidPrices:
                    # Test 3: Check market states
                    if pair.MarketState == MarketState.Crossed:
                        self.crossed_detected += 1
                        self.Log(f"[ALGORITHM] Crossed market detected: {pair.Key}")
                        self.Log(f"  Spread: {pair.Spread:.4f}")
                        self.Log(f"  Direction: {pair.Direction}")
                    elif pair.MarketState == MarketState.Inverted:
                        self.inverted_detected += 1

            # Test 4: Access specific pair using TryGetPair
            spy_qqq_pair = self.TradingPairs.TryGetPair(self.spy, self.qqq)
            if spy_qqq_pair is not None:
                if self.algorithm_access_count <= 5:  # Log first few accesses
                    self.Debug(f"Accessed SPY-QQQ pair via algorithm:")
                    self.Debug(f"  HasValidPrices: {spy_qqq_pair.HasValidPrices}")
                    if spy_qqq_pair.HasValidPrices:
                        self.Debug(f"  Theoretical Spread: {spy_qqq_pair.TheoreticalSpread:.4f}")
                        self.Debug(f"  Market State: {spy_qqq_pair.MarketState}")

            # Test 5: Use GetCrossedPairs
            if self.Time.minute == 30:  # Check every half hour
                crossed = list(self.TradingPairs.GetCrossedPairs())
                if len(crossed) > 0:
                    self.Log(f"[ALGORITHM] Found {len(crossed)} crossed pairs at {self.Time}")

            # Test 6: Use GetByState
            if self.Time.minute == 0 and self.Time.hour % 3 == 0:  # Every 3 hours
                normal = list(self.TradingPairs.GetByState(MarketState.Normal))
                inverted = list(self.TradingPairs.GetByState(MarketState.Inverted))
                self.Log(f"[ALGORITHM] State counts - Normal: {len(normal)}, Inverted: {len(inverted)}")
        else:
            # This shouldn't happen
            self.Error("TradingPairs not available in algorithm!")

    def LogTradingPairStatus(self):
        '''Log the status of TradingPairs accessed via algorithm'''

        self.Log(f"=== TradingPair Status at {self.Time} ===")
        self.Log(f"Algorithm access count: {self.algorithm_access_count}")

        if len(self.pairs_count_history) > 0:
            avg_pairs = sum(self.pairs_count_history) / len(self.pairs_count_history)
            self.Log(f"Average pair count: {avg_pairs:.1f}")
            self.Log(f"Current pair count: {self.TradingPairs.Count}")

        self.Log(f"Crossed markets detected: {self.crossed_detected}")
        self.Log(f"Inverted markets detected: {self.inverted_detected}")

    def OnEndOfAlgorithm(self):
        '''Final validation of TradingPair integration'''

        self.Log("=== TradingPair Integration Test Complete ===")
        self.Log(f"Total algorithm accesses: {self.algorithm_access_count}")

        # Verify we actually accessed TradingPairs
        if self.algorithm_access_count == 0:
            self.Error("FAILED: Never accessed TradingPairs via algorithm!")
        else:
            self.Log("SUCCESS: TradingPairs accessed via algorithm")

        # Verify consistent pair count
        if len(self.pairs_count_history) > 0:
            if all(count == 3 for count in self.pairs_count_history):
                self.Log("SUCCESS: Consistent pair count throughout")
            else:
                self.Error(f"WARNING: Inconsistent pair counts: {set(self.pairs_count_history)}")

        # Log detection statistics
        self.Log(f"Crossed markets detected: {self.crossed_detected}")
        self.Log(f"Inverted markets detected: {self.inverted_detected}")

        # Final validation
        self.Log(f"Final pair count: {self.TradingPairs.Count}")
        expected_pairs = 3
        if self.TradingPairs.Count == expected_pairs:
            self.Log(f"SUCCESS: Expected {expected_pairs} pairs, got {self.TradingPairs.Count}")
        else:
            self.Error(f"FAILED: Expected {expected_pairs} pairs, got {self.TradingPairs.Count}")
