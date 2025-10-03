"""
SpreadManager - Core position and subscription management for crypto-stock arbitrage

Manages many-to-one relationships between crypto tokens (e.g., TSLAx on Kraken)
and underlying stocks (e.g., TSLA on IBKR).
"""
from AlgorithmImports import *
from typing import Dict, Set, List, Tuple, Optional
import sys
import os
sys.path.append(os.path.dirname(__file__))
from limit_order_optimizer import LimitOrderOptimizer


class SpreadManager:
    """
    Manages crypto-stock trading pairs with automatic deduplication and position tracking.

    Key Features:
    - Automatic stock subscription with deduplication (many tokens -> one stock)
    - Track all crypto-stock pairs
    - Calculate spread percentage
    - (Phase 2) Manage net positions to avoid risk exposure

    Example Usage:
        manager = SpreadManager(algorithm)

        # Subscribe crypto and auto-subscribe corresponding stock
        crypto = algorithm.AddCrypto("TSLAxUSD", Resolution.Tick, Market.Kraken)
        stock = manager.subscribe_stock_by_crypto(crypto)
        manager.add_pair(crypto, stock)
    """

    def __init__(self, algorithm: QCAlgorithm, strategy=None, aggression: float = 0.6):
        """
        Initialize SpreadManager

        Args:
            algorithm: QCAlgorithm instance for accessing trading APIs
            strategy: GridStrategy instance
            aggression: 限价单激进度
        """
        self.algorithm = algorithm
        self.strategy = strategy
        self.aggression = aggression

        # Crypto Symbol -> Stock Symbol mapping
        self.pairs: Dict[Symbol, Symbol] = {}

        # Stock Symbol -> List of Crypto Symbols (for many-to-one tracking)
        self.stock_to_cryptos: Dict[Symbol, List[Symbol]] = {}

        # Already subscribed stocks (Security objects)
        self.stocks: Set[Security] = set()

        # Already subscribed cryptos (Security objects)
        self.cryptos: Set[Security] = set()

        # Phase 2: Position tracking (to be implemented)
        # Format: {(crypto_symbol, stock_symbol): {'token_qty': -300, 'stock_qty': 300}}
        self.pair_positions: Dict[Tuple[Symbol, Symbol], Dict[str, float]] = {}

        # Order tracking
        # Format: {(crypto_symbol, stock_symbol): {'crypto_order': order_id, 'is_close': bool}}
        self.orders: Dict[Tuple[Symbol, Symbol], Dict] = {}

    def add_pair(self, crypto: Security, stock: Security):
        """
        Register a crypto-stock trading pair

        Args:
            crypto: Crypto Security object
            stock: Stock Security object

        Side Effects:
            - Adds pair to self.pairs
            - Updates self.stock_to_cryptos for many-to-one tracking
            - Adds securities to self.cryptos and self.stocks

        Example:
            >>> manager.add_pair(crypto, stock)
            >>> pairs = manager.get_all_pairs()
            >>> print(pairs)  # [(TSLAxUSD, TSLA), ...]
        """
        crypto_symbol = crypto.Symbol
        stock_symbol = stock.Symbol

        # Add to pairs mapping
        self.pairs[crypto_symbol] = stock_symbol

        # Update reverse mapping (stock -> list of cryptos)
        if stock_symbol not in self.stock_to_cryptos:
            self.stock_to_cryptos[stock_symbol] = []
        self.stock_to_cryptos[stock_symbol].append(crypto_symbol)

        # Track securities
        self.cryptos.add(crypto)
        self.stocks.add(stock)

        self.algorithm.Debug(f"Added pair: {crypto_symbol} <-> {stock_symbol}")
        self.algorithm.Debug(f"  Stock {stock_symbol} now paired with {len(self.stock_to_cryptos[stock_symbol])} crypto(s)")

    def get_all_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        Get all registered crypto-stock pairs

        Returns:
            List of (crypto_symbol, stock_symbol) tuples

        Example:
            >>> pairs = manager.get_all_pairs()
            >>> for crypto_sym, stock_sym in pairs:
            ...     print(f"{crypto_sym} -> {stock_sym}")
        """
        return list(self.pairs.items())

    def get_cryptos_for_stock(self, stock_symbol: Symbol) -> List[Symbol]:
        """
        !!! 目前没有任何函数引用他
        Get all crypto symbols paired with a given stock (many-to-one relationship)

        Args:
            stock_symbol: Stock Symbol

        Returns:
            List of crypto Symbols paired with this stock

        Example:
            >>> cryptos = manager.get_cryptos_for_stock(tsla_symbol)
            >>> print(cryptos)  # [TSLAxUSD, TSLAON, ...]
        """
        return self.stock_to_cryptos.get(stock_symbol, [])

    def get_pair_symbol_from_crypto(self, crypto_symbol: Symbol) -> Optional[Tuple[Symbol, Symbol]]:
        """
        Get pair symbol from crypto symbol

        Args:
            crypto_symbol: Crypto Symbol

        Returns:
            (crypto_symbol, stock_symbol) tuple, or None if not found
        """
        stock_symbol = self.pairs.get(crypto_symbol)
        if stock_symbol:
            return (crypto_symbol, stock_symbol)
        return None
    
    @staticmethod
    def calculate_spread_pct(token_bid: float, token_ask: float,
                            stock_bid: float, stock_ask: float) -> float:
        """
        Calculate bidirectional spread percentage for arbitrage opportunities

        Compares two arbitrage scenarios and returns the one with largest absolute value:
        1. Short token, Long stock: (token_bid - stock_ask) / token_bid
        2. Long token, Short stock: (token_ask - stock_bid) / token_ask

        By using (token - stock) consistently, the sign indicates direction:
        - Positive spread: token overpriced → short token, long stock
        - Negative spread: token underpriced → long token, short stock

        Args:
            token_bid: Crypto token best bid price
            token_ask: Crypto token best ask price
            stock_bid: Underlying stock best bid price
            stock_ask: Underlying stock best ask price

        Returns:
            Spread percentage with largest absolute value (preserves sign)

        Example:
            >>> # AAPLx bid=150.5, ask=150.6, AAPL bid=150.0, ask=150.1
            >>> spread = SpreadManager.calculate_spread_pct(150.5, 150.6, 150.0, 150.1)
            >>> # Scenario 1: (150.5 - 150.1) / 150.5 = 0.266%
            >>> # Scenario 2: (150.6 - 150.0) / 150.6 = 0.398%
            >>> # Returns: 0.398 (larger abs value, positive = short token)
        """
        if token_bid == 0 or token_ask == 0:
            return 0.0

        # Scenario 1: Short token (sell at bid), Long stock (buy at ask)
        spread_short_token = ((token_bid - stock_ask) / token_bid)

        # Scenario 2: Long token (buy at ask), Short stock (sell at bid)
        spread_long_token = ((token_ask - stock_bid) / token_ask)

        # Return the spread with largest absolute value (best opportunity)
        if abs(spread_short_token) >= abs(spread_long_token):
            return spread_short_token
        else:
            return spread_long_token

    def monitor_spread(self, latest_quotes: dict):
        """
        监控所有交易对的spread并触发策略

        Args:
            latest_quotes: {symbol: QuoteTick} 字典
        """
        if not self.strategy:
            return

        for crypto_symbol, stock_symbol in self.get_all_pairs():
            crypto_quote = latest_quotes.get(crypto_symbol)
            stock_quote = latest_quotes.get(stock_symbol)

            if not crypto_quote or not stock_quote:
                continue

            # 计算限价单价格
            crypto_bid_price = LimitOrderOptimizer.calculate_buy_limit_price(
                crypto_quote.BidPrice, crypto_quote.AskPrice, self.aggression
            )
            crypto_ask_price = LimitOrderOptimizer.calculate_sell_limit_price(
                crypto_quote.BidPrice, crypto_quote.AskPrice, self.aggression
            )

            # 计算spread (用限价单价格)
            spread_pct = self.calculate_spread_pct(
                crypto_bid_price,  # 我们的卖出限价
                crypto_ask_price,  # 我们的买入限价
                stock_quote.BidPrice,
                stock_quote.AskPrice
            )

            # 触发策略
            self.strategy.on_spread_update(
                crypto_symbol, stock_symbol, spread_pct,
                crypto_quote, stock_quote,
                crypto_bid_price, crypto_ask_price
            )

    # ============================================================================
    # Phase 2: Position Management (To Be Implemented)
    # ============================================================================

    def record_position(self, crypto_symbol: Symbol, stock_symbol: Symbol,
                       crypto_qty: float, stock_qty: float):
        """
        Record a position for a crypto-stock pair

        Args:
            crypto_symbol: Crypto Symbol
            stock_symbol: Stock Symbol
            crypto_qty: Crypto quantity (negative for short)
            stock_qty: Stock quantity (positive for long)

        Note: To be implemented in Phase 2
        """
        pair_key = (crypto_symbol, stock_symbol)
        self.pair_positions[pair_key] = {
            'token_qty': crypto_qty,
            'stock_qty': stock_qty
        }
        self.algorithm.Debug(f"Recorded position: {crypto_symbol} ({crypto_qty}) <-> {stock_symbol} ({stock_qty})")

    def get_net_stock_position(self, stock_symbol: Symbol) -> float:
        """
        Calculate net position for a stock across all crypto pairs

        Important for many-to-one hedging:
        - TSLAx(-300) -> TSLA(+300)
        - TSLAON(-400) -> TSLA(+400)
        - Net TSLA position: +700

        Args:
            stock_symbol: Stock Symbol

        Returns:
            Net stock position (sum of all pair positions)

        Note: To be implemented in Phase 2
        """
        net_position = 0.0

        for (crypto_sym, stock_sym), position in self.pair_positions.items():
            if stock_sym == stock_symbol:
                net_position += position['stock_qty']

        return net_position

    def close_partial_position(self, crypto_symbol: Symbol, close_qty: float) -> Dict:
        """
        Close a partial position for a crypto-stock pair while maintaining hedge

        Example:
            - Initial: TSLAx(-300), TSLA(+300)
            - Close 100: TSLAx(-200), TSLA(+200)

        Args:
            crypto_symbol: Crypto Symbol to partially close
            close_qty: Quantity to close (positive number)

        Returns:
            Dict with 'crypto_close_qty' and 'stock_close_qty'

        Note: To be implemented in Phase 2
        """
        # Find the stock paired with this crypto
        stock_symbol = self.pairs.get(crypto_symbol)
        if not stock_symbol:
            raise ValueError(f"No stock paired with crypto {crypto_symbol}")

        pair_key = (crypto_symbol, stock_symbol)
        position = self.pair_positions.get(pair_key)

        if not position:
            raise ValueError(f"No position found for pair {crypto_symbol} <-> {stock_symbol}")

        # Calculate proportional close amounts
        current_crypto_qty = position['token_qty']
        current_stock_qty = position['stock_qty']

        # Update positions
        position['token_qty'] += close_qty  # Close short (add positive)
        position['stock_qty'] -= close_qty  # Close long (subtract)

        self.algorithm.Debug(f"Closed {close_qty} of {crypto_symbol} <-> {stock_symbol}")

        return {
            'crypto_close_qty': close_qty,
            'stock_close_qty': close_qty
        }

    # ============================================================================
    # ExecutionEngine Integration Methods
    # ============================================================================

    def add_order(self, pair_symbol: Tuple[Symbol, Symbol], order_id: int, is_close: bool = False):
        """
        Add order to tracking

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            order_id: Order ID
            is_close: 是否平仓单
        """
        # 检查是否已有订单或仓位
        if pair_symbol in self.orders and not is_close:
            self.algorithm.Debug(f"⚠️ Order already exists for {pair_symbol}")
            return

        self.orders[pair_symbol] = {
            'crypto_order': order_id,
            'is_close': is_close
        }

        self.algorithm.Debug(f"Added order tracking: {pair_symbol[0].Value} <-> {pair_symbol[1].Value}")

    def get_order(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[Dict]:
        """
        Get order info

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            Order info dict, or None if not found
        """
        return self.orders.get(pair_symbol)

    def get_pair_position(self, pair_symbol: Tuple[Symbol, Symbol]) -> Optional[Tuple[float, float]]:
        """
        Get pair position

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            (crypto_qty, stock_qty) tuple, or None if no position
        """
        position = self.pair_positions.get(pair_symbol)
        if position:
            return (position.get('token_qty', 0.0), position.get('stock_qty', 0.0))
        return None

    def update_pair_position(self, pair_symbol: Tuple[Symbol, Symbol],
                            crypto_qty: float, stock_qty: float):
        """
        Update pair position (累加)

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            crypto_qty: Crypto数量变化
            stock_qty: Stock数量变化
        """
        if pair_symbol not in self.pair_positions:
            self.pair_positions[pair_symbol] = {
                'token_qty': 0.0,
                'stock_qty': 0.0
            }

        position = self.pair_positions[pair_symbol]
        position['token_qty'] += crypto_qty
        position['stock_qty'] += stock_qty

        self.algorithm.Debug(
            f"Updated position: {pair_symbol[0].Value} ({position['token_qty']}) <-> "
            f"{pair_symbol[1].Value} ({position['stock_qty']})"
        )
