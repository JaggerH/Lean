# region imports
from AlgorithmImports import *
# endregion

class MultiAccountLiveTest(QCAlgorithm):
    """Multi-Account Live Trading Integration Test"""

    def Initialize(self):
        self.SetStartDate(2024, 1, 1)

        # Add symbols from different markets
        self.aapl_ibkr = self.add_equity("AAPL", Resolution.TICK, Market.USA, extended_market_hours=True).Symbol
        self.btc_gate = self.add_crypto_future("BTCUSDT", Resolution.TICK, Market.GATE).Symbol

        self.Log(f"[INIT] IBKR: {self.aapl_ibkr} | Gate: {self.btc_gate}")
        self.Log(f"[INIT] Portfolio type: {type(self.Portfolio).__name__}")

        self.cycle_count = 0
        self.ibkr_orders = 0
        self.gate_orders = 0

        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.Every(timedelta(seconds=10)),
            self.TmpTradingCycle
        )

        # Note: Per-account holdings will be logged automatically by the system after setup completes
        # with correct conversion rates. Do not log here to avoid showing uninitialized conversion rates.

    def OnData(self, data):
        pass

    def TmpTradingCycle(self):
        """Temporary single-account trading cycle for IBKR AAPL testing during pre-market hours"""
        try:
            self.cycle_count += 1
            self.Log(f"\n[TMP CYCLE {self.cycle_count}] Testing IBKR AAPL only")

            aapl_qty = self.Portfolio[self.aapl_ibkr].Quantity
            self.Log(f"IBKR AAPL Quantity: {aapl_qty}")

            # Simple buy/sell cycle for AAPL on IBKR
            if aapl_qty == 0:
                # Buy 1 share
                self.MarketOrder(self.aapl_ibkr, 100)
                self.ibkr_orders += 1
                self.Log(f"[TMP] Placed BUY order for 1 share AAPL")
            else:
                # Liquidate position
                self.Liquidate(self.aapl_ibkr, True)
                self.Log(f"[TMP] Liquidating AAPL position")

        except Exception as e:
            self.Error(f"TmpTradingCycle error: {str(e)}")

    def TradingCycle(self):
        """Original dual-account trading cycle (currently disabled)"""
        try:
            self.cycle_count += 1
            self.Log(f"\n[CYCLE {self.cycle_count}]")

            aapl_qty = self.Portfolio[self.aapl_ibkr].Quantity
            gate_qty = self.Portfolio[self.btc_gate].Quantity

            self.Log(f"IBKR: {aapl_qty} | Gate: {gate_qty:.4f}")

            # Trade IBKR
            if aapl_qty == 0:
                self.MarketOrder(self.aapl_ibkr, 1)
                self.ibkr_orders += 1
            else:
                self.Liquidate(self.aapl_ibkr, True)

            # Trade Gate
            if abs(gate_qty) < 10:
                self.MarketOrder(self.btc_gate, 10)
                self.gate_orders += 1
            else:
                self.Liquidate(self.btc_gate, True)

        except Exception as e:
            self.Error(f"TradingCycle error: {str(e)}")

    def OnOrderEvent(self, orderEvent):
        if orderEvent.Status == OrderStatus.Filled:
            market = orderEvent.Symbol.ID.Market
            self.Log(f"[ORDER] {market} | {orderEvent.OrderId} | FILLED")

            # Log per-account holdings after each fill
            # if hasattr(self.Portfolio, 'GetSubAccountHoldingsDetails'):
                # self.Log(self.Portfolio.GetSubAccountHoldingsDetails())

    def OnEndOfAlgorithm(self):
        self.Log(f"\n[END] Cycles: {self.cycle_count}")
        self.Log(f"[END] IBKR orders: {self.ibkr_orders}")
        self.Log(f"[END] Gate orders: {self.gate_orders}")
        self.Log(f"[END] Total value: ${self.Portfolio.TotalPortfolioValue:.2f}")

        # Log final per-account holdings
        if hasattr(self.Portfolio, 'GetSubAccountHoldingsDetails'):
            self.Log(self.Portfolio.GetSubAccountHoldingsDetails())
