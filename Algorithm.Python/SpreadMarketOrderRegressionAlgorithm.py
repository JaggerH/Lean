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

class SpreadMarketOrderRegressionAlgorithm(QCAlgorithm):
    """
    Regression algorithm asserting that spread market orders are filled correctly and atomically
    This algorithm tests the SpreadMarketOrder functionality for crypto arbitrage strategies in Python
    """

    def initialize(self):
        self.set_start_date(2018, 4, 4)
        self.set_end_date(2018, 4, 5)
        self.set_cash(100000)

        self.btc_usd = self.add_crypto("BTCUSD", Resolution.HOUR).symbol
        self.eth_usd = self.add_crypto("ETHUSD", Resolution.HOUR).symbol

        self.tickets = []
        self.fill_order_events = []
        self.order_placed = False

    def on_data(self, slice):
        if not self.order_placed and self.btc_usd in slice and self.eth_usd in slice:
            # Create a spread order: long BTC, short ETH
            legs = [
                Leg.create(self.btc_usd, 1),
                Leg.create(self.eth_usd, -10)  # Ratio to balance dollar amounts
            ]

            self.tickets = self.spread_market_order(legs, 1)
            self.order_placed = True

            if len(self.tickets) != 2:
                raise Exception(f"Expected 2 order tickets, found {len(self.tickets)}")

            for ticket in self.tickets:
                if ticket.order_type != OrderType.SPREAD_MARKET:
                    raise Exception(f"Expected SpreadMarket order type, found {ticket.order_type}")

    def on_order_event(self, order_event):
        self.debug(f"Order Event: {order_event}")

        if order_event.status == OrderStatus.FILLED:
            self.fill_order_events.append(order_event)

    def on_end_of_algorithm(self):
        if not self.order_placed:
            raise Exception("Spread order was not placed")

        if len(self.fill_order_events) != 2:
            raise Exception(f"Expected 2 fill order events, found {len(self.fill_order_events)}")

        # Verify atomic execution: all fills must have the same timestamp
        fill_times = set([x.utc_time for x in self.fill_order_events])
        if len(fill_times) != 1:
            raise Exception(f"Expected all fill order events to have the same time, found {fill_times}")

        # Verify fill quantities match leg ratios
        btc_fill = next((x for x in self.fill_order_events if x.symbol == self.btc_usd), None)
        eth_fill = next((x for x in self.fill_order_events if x.symbol == self.eth_usd), None)

        if btc_fill is None or eth_fill is None:
            raise Exception("Missing fill events for BTC or ETH")

        if btc_fill.fill_quantity != 1:
            raise Exception(f"Expected BTC fill quantity of 1, found {btc_fill.fill_quantity}")

        if eth_fill.fill_quantity != -10:
            raise Exception(f"Expected ETH fill quantity of -10, found {eth_fill.fill_quantity}")

        self.debug("SpreadMarketOrder regression test passed successfully")
