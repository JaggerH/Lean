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
    Test algorithm to verify TradingPair functionality with Slice integration.
    Tests accessing TradingPairs through the slice object in OnData.
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
        self.slice_access_count = 0
        self.pairs_in_slice_count = []
        self.crossed_detected_via_slice = 0
        self.inverted_detected_via_slice = 0

        # Schedule periodic status reports
        self.Schedule.On(
            self.DateRules.EveryDay(self.spy),
            self.TimeRules.Every(timedelta(hours=2)),
            self.LogSliceStatus
        )

    def OnData(self, slice):
        '''Process data and test slice.TradingPairs access'''

        if self.IsWarmingUp:
            return

        # Test 1: Access TradingPairs through slice
        if hasattr(slice, 'TradingPairs') and slice.TradingPairs is not None:
            self.slice_access_count += 1
            self.pairs_in_slice_count.append(len(slice.TradingPairs))

            # Test 2: Iterate through pairs in slice
            for pair in slice.TradingPairs:
                if pair.HasValidPrices:
                    # Test 3: Check market states via slice
                    if pair.MarketState == MarketState.Crossed:
                        self.crossed_detected_via_slice += 1
                        self.Log(f"[SLICE] Crossed market detected: {pair.Key}")
                        self.Log(f"  Spread: {pair.Spread:.4f}")
                        self.Log(f"  Direction: {pair.Direction}")
                    elif pair.MarketState == MarketState.Inverted:
                        self.inverted_detected_via_slice += 1

            # Test 4: Access specific pair via slice using tuple key
            if slice.TradingPairs.ContainsKey((self.spy, self.qqq)):
                spy_qqq = slice.TradingPairs[(self.spy, self.qqq)]
                if self.slice_access_count <= 5:  # Log first few accesses
                    self.Debug(f"Accessed SPY-QQQ pair via slice:")
                    self.Debug(f"  HasValidPrices: {spy_qqq.HasValidPrices}")
                    if spy_qqq.HasValidPrices:
                        self.Debug(f"  Theoretical Spread: {spy_qqq.TheoreticalSpread:.4f}")
                        self.Debug(f"  Market State: {spy_qqq.MarketState}")

            # Test 5: Use GetCrossedPairs from slice
            if self.Time.minute == 30:  # Check every half hour
                crossed = list(slice.TradingPairs.GetCrossedPairs())
                if len(crossed) > 0:
                    self.Log(f"[SLICE] Found {len(crossed)} crossed pairs at {self.Time}")

            # Test 6: Use GetByState from slice
            if self.Time.minute == 0 and self.Time.hour % 3 == 0:  # Every 3 hours
                normal = list(slice.TradingPairs.GetByState(MarketState.Normal))
                inverted = list(slice.TradingPairs.GetByState(MarketState.Inverted))
                self.Log(f"[SLICE] State counts - Normal: {len(normal)}, Inverted: {len(inverted)}")
        else:
            # This shouldn't happen if integration is correct
            self.Error("TradingPairs not available in slice!")

    def LogSliceStatus(self):
        '''Log the status of TradingPairs accessed via slice'''

        self.Log(f"=== Slice Integration Status at {self.Time} ===")
        self.Log(f"Slice access count: {self.slice_access_count}")

        if len(self.pairs_in_slice_count) > 0:
            avg_pairs = sum(self.pairs_in_slice_count) / len(self.pairs_in_slice_count)
            self.Log(f"Average pairs in slice: {avg_pairs:.1f}")
            self.Log(f"Max pairs in slice: {max(self.pairs_in_slice_count)}")
            self.Log(f"Min pairs in slice: {min(self.pairs_in_slice_count)}")

        self.Log(f"Crossed markets via slice: {self.crossed_detected_via_slice}")
        self.Log(f"Inverted markets via slice: {self.inverted_detected_via_slice}")

    def OnEndOfAlgorithm(self):
        '''Final validation of slice integration'''

        self.Log("=== Slice Integration Test Complete ===")
        self.Log(f"Total slice accesses: {self.slice_access_count}")

        # Verify we actually accessed TradingPairs via slice
        if self.slice_access_count == 0:
            self.Error("FAILED: Never accessed TradingPairs via slice!")
        else:
            self.Log("SUCCESS: TradingPairs accessed via slice")

        # Verify consistent pair count
        if len(self.pairs_in_slice_count) > 0:
            if all(count == 3 for count in self.pairs_in_slice_count):
                self.Log("SUCCESS: Consistent pair count in all slices")
            else:
                self.Error(f"WARNING: Inconsistent pair counts: {set(self.pairs_in_slice_count)}")

        # Log detection statistics
        self.Log(f"Crossed markets detected via slice: {self.crossed_detected_via_slice}")
        self.Log(f"Inverted markets detected via slice: {self.inverted_detected_via_slice}")

        # Final comparison: slice vs manager
        self.Log(f"Manager pair count: {self.TradingPairs.Count}")
        if len(self.pairs_in_slice_count) > 0:
            self.Log(f"Last slice pair count: {self.pairs_in_slice_count[-1]}")