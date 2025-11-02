# region imports
from AlgorithmImports import *
# endregion

class GateIntegrationTest(QCAlgorithm):
    """
    Gate.io Integration Test Algorithm

    Tests basic Gate.io brokerage functionality:
    - Connection and authentication
    - Market data subscription
    - Order placement (market buy/sell)
    - Position tracking
    - Order cancellation

    Strategy: Simple 30-second interval trading
    - Opens position with market order
    - Closes position after 30 seconds
    - Repeats cycle continuously
    """

    def Initialize(self):
        """Initialize algorithm parameters and schedule trading cycle"""
        self.SetStartDate(2024, 1, 1)
        self.SetCash(10000)  # Test with $10,000

        # Add BTCUSDT on Gate.io (Crypto spot trading)
        self.symbol = self.add_crypto_future("BTCUSDT", Resolution.TICK, Market.Gate).Symbol

        self.Log(f"[INIT] Algorithm initialized with symbol: {self.symbol}")

        # Trading state tracking
        self.position_opened = False
        self.last_order_time = None
        self.order_count = 0
        self.cycle_count = 0

        # Schedule trading cycle every 30 seconds
        self.Schedule.On(
            self.DateRules.EveryDay(),
            self.TimeRules.Every(timedelta(seconds=10)),
            self.TradingCycle
        )

        self.Log("[INIT] Scheduled 30-second trading cycle")

    def OnData(self, data: Slice):
        """Process market data updates"""
        pass

    def TradingCycle(self):
        """Execute one trading cycle: open or close position"""
        try:
            self.cycle_count += 1
            holdings = self.Portfolio[self.symbol]
            quantity = holdings.Quantity

            if not self.Securities[self.symbol].HasData:
                self.Log(f"[CYCLE {self.cycle_count}] No data available")
                return

            current_price = self.Securities[self.symbol].Price
            action = "OPEN" if abs(quantity) < 1 else "CLOSE"

            self.Log(f"[CYCLE {self.cycle_count}] {action} | Pos: {quantity:.2f} | Price: ${current_price:.2f} | Value: ${self.Portfolio.TotalPortfolioValue:.2f}")

            # If no position, open long position
            if abs(quantity) < 1:
                self.OpenPosition()
            else:
                # If has position, close it
                self.ClosePosition()

        except Exception as e:
            self.Log(f"[ERROR] TradingCycle: {str(e)}")
            self.Error(f"TradingCycle error: {str(e)}")

    def OpenPosition(self):
        """Open a long position with market order"""
        try:
            # quantity = self.calculate_order_quantity(self.symbol, 0.5)
            quantity = 10
            ticket = self.MarketOrder(self.symbol, quantity)

            self.order_count += 1
            self.position_opened = True
            self.last_order_time = self.Time

            self.Log(f"[OPEN] Qty: {quantity:.2f} | OrderID: {ticket.OrderId} | Total: {self.order_count}")

        except Exception as e:
            self.Log(f"[ERROR] OpenPosition: {str(e)}")
            self.Error(f"OpenPosition error: {str(e)}")

    def ClosePosition(self):
        """Close current position with market order"""
        try:
            holdings = self.Portfolio[self.symbol]
            quantity = holdings.Quantity

            if abs(quantity) < 1:
                self.Log(f"[CLOSE] No position")
                return

            current_price = self.Securities[self.symbol].Price
            unrealized_pnl = holdings.UnrealizedProfit
            unrealized_pnl_pct = (unrealized_pnl / holdings.HoldingsCost * 100) if holdings.HoldingsCost != 0 else 0

            # Place market sell order to liquidate entire position
            tickets = self.liquidate(self.symbol, True)

            # Liquidate returns a list of tickets, handle accordingly
            if isinstance(tickets, list):
                self.order_count += len(tickets)
                ticket_ids = [ticket.OrderId for ticket in tickets]
                self.Log(f"[CLOSE] Qty: {quantity:.2f} | Price: ${current_price:.2f} | PnL: ${unrealized_pnl:.2f} ({unrealized_pnl_pct:+.2f}%) | OrderIDs: {ticket_ids}")
            else:
                # Single ticket returned
                self.order_count += 1
                self.Log(f"[CLOSE] Qty: {quantity:.2f} | Price: ${current_price:.2f} | PnL: ${unrealized_pnl:.2f} ({unrealized_pnl_pct:+.2f}%) | OrderID: {tickets.OrderId}")

            self.position_opened = False
            self.last_order_time = self.Time

        except Exception as e:
            self.Log(f"[ERROR] ClosePosition: {str(e)}")
            self.Error(f"ClosePosition error: {str(e)}")

    def OnOrderEvent(self, orderEvent: OrderEvent):
        """Handle order status updates"""
        order = self.Transactions.GetOrderById(orderEvent.OrderId)
        holdings = self.Portfolio[self.symbol]

        # Build a concise one-line log
        if orderEvent.Status == OrderStatus.Filled:
            self.Log(f"[ORDER_EVENT] ID: {orderEvent.OrderId} | {orderEvent.Status} | {order.Direction} | NewPos: {holdings.Quantity:.2f}")
        elif orderEvent.Status == OrderStatus.Invalid:
            self.Log(f"[ORDER_EVENT] ID: {orderEvent.OrderId} | INVALID | {order.Direction} | Msg: {orderEvent.Message}")
        elif orderEvent.Status == OrderStatus.Canceled:
            self.Log(f"[ORDER_EVENT] ID: {orderEvent.OrderId} | CANCELED | {order.Direction} | Msg: {orderEvent.Message}")
        else:
            self.Log(f"[ORDER_EVENT] ID: {orderEvent.OrderId} | {orderEvent.Status} | {order.Direction}")

    def OnEndOfAlgorithm(self):
        """Log final statistics when algorithm terminates"""
        self.Log(f"\n{'='*80}")
        self.Log("[END] Algorithm Terminating")
        self.Log(f"[END] Total cycles executed: {self.cycle_count}")
        self.Log(f"[END] Total orders placed: {self.order_count}")
        self.Log(f"[END] Final portfolio value: ${self.Portfolio.TotalPortfolioValue:.2f}")

        holdings = self.Portfolio[self.symbol]
        if abs(holdings.Quantity) > 0.0001:
            self.Log(f"[END] WARNING: Open position remaining: {holdings.Quantity:.4f} BTC")
        else:
            self.Log(f"[END] All positions closed")

        self.Log(f"{'='*80}\n")
