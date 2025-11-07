# region imports
from AlgorithmImports import *
# endregion

class MultiAccountLiveTest(QCAlgorithm):
    """Multi-Account Live Trading Integration Test"""

    def Initialize(self):
        self.SetStartDate(2024, 1, 1)

        # Add symbols from different markets
        self.btc_binance = self.AddCryptoFuture("BTCUSDT", Resolution.TICK, Market.BINANCE).Symbol
        self.btc_gate = self.AddCryptoFuture("BTCUSDT", Resolution.TICK, Market.GATE).Symbol

        self.Log(f"[INIT] Binance: {self.btc_binance} | Gate: {self.btc_gate}")
        self.Log(f"[INIT] Portfolio type: {type(self.Portfolio).__name__}")

        self.cycle_count = 0
        self.binance_orders = 0
        self.gate_orders = 0

        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.Every(timedelta(seconds=10)),
            self.TradingCycle
        )

        # Note: Per-account holdings will be logged automatically by the system after setup completes
        # with correct conversion rates. Do not log here to avoid showing uninitialized conversion rates.

    def OnData(self, data):
        pass

    def TradingCycle(self):
        try:
            self.cycle_count += 1
            self.Log(f"\n[CYCLE {self.cycle_count}]")

            binance_qty = self.Portfolio[self.btc_binance].Quantity
            gate_qty = self.Portfolio[self.btc_gate].Quantity

            self.Log(f"Binance: {binance_qty:.4f} | Gate: {gate_qty:.4f}")

            # Trade Binance
            if abs(binance_qty) < 0.001:
                self.MarketOrder(self.btc_binance, 0.001)
                self.binance_orders += 1
            else:
                self.liquidate(self.btc_binance, True)

            # Trade Gate
            if abs(gate_qty) < 10:
                self.MarketOrder(self.btc_gate, 10)
                self.gate_orders += 1
            else:
                self.liquidate(self.btc_gate, True)

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
        self.Log(f"[END] Binance orders: {self.binance_orders}")
        self.Log(f"[END] Gate orders: {self.gate_orders}")
        self.Log(f"[END] Total value: ${self.Portfolio.TotalPortfolioValue:.2f}")

        # Log final per-account holdings
        if hasattr(self.Portfolio, 'GetSubAccountHoldingsDetails'):
            self.Log(self.Portfolio.GetSubAccountHoldingsDetails())
