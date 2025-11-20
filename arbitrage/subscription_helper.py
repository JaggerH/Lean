"""
Subscription Helper for Trading Pairs

Provides unified subscription functionality for trading pairs in LEAN.
Replaces the subscription logic previously in SpreadManager.
"""

from AlgorithmImports import *
from typing import Tuple, Optional


class SubscriptionHelper:
    """
    Unified subscription helper for trading pairs

    Responsibilities:
    - Subscribe securities via LEAN APIs
    - Configure security properties (fee model, leverage, normalization)
    - Register pairs with TradingPairManager (triggers CollectionChanged event)

    NOT responsible for:
    - Spread calculation (handled by TradingPair)
    - Observer notifications (handled by CollectionChanged event)
    - Strategy logic
    """

    def __init__(self, algorithm: QCAlgorithm):
        """
        Initialize the subscription helper

        Args:
            algorithm: The QCAlgorithm instance
        """
        self.algorithm = algorithm

    def subscribe_pair(
        self,
        leg1_symbol: Symbol,
        leg2_symbol: Symbol,
        pair_type: str,
        resolution: Tuple[Resolution, Resolution] = (Resolution.TICK, Resolution.TICK),
        fee_model: Tuple = None,
        leverage: Tuple[float, float] = (5.0, 5.0),
        extended_market_hours: bool = False
    ) -> Tuple[Security, Security]:
        """
        Subscribe to a trading pair

        Args:
            leg1_symbol: First leg symbol
            leg2_symbol: Second leg symbol
            pair_type: Pair type (REQUIRED) - "spot_future", "crypto_stock", "cryptofuture_stock"
            resolution: (leg1_resolution, leg2_resolution)
            fee_model: (leg1_fee, leg2_fee) or None for defaults
            leverage: (leg1_leverage, leg2_leverage)
            extended_market_hours: Extended market hours for Equity (default: False)

        Returns:
            (leg1_security, leg2_security) - Maintains caller's order

        Raises:
            ValueError: If pair_type is not supported
            ArgumentException: If symbols are not found or invalid
        """
        # Parse tuple parameters
        leg1_res, leg2_res = resolution
        leg1_lev, leg2_lev = leverage
        leg1_fee = fee_model[0] if fee_model else None
        leg2_fee = fee_model[1] if fee_model else None

        # Subscribe both legs using unified logic
        leg1_sec = self._subscribe_leg(
            leg1_symbol,
            leg1_res,
            leg1_lev,
            leg1_fee,
            extended_market_hours
        )

        leg2_sec = self._subscribe_leg(
            leg2_symbol,
            leg2_res,
            leg2_lev,
            leg2_fee,
            extended_market_hours
        )

        # Register with TradingPairManager (triggers CollectionChanged event)
        self.algorithm.AddTradingPair(leg1_symbol, leg2_symbol, pair_type)

        return (leg1_sec, leg2_sec)

    def _subscribe_leg(
        self,
        symbol: Symbol,
        resolution: Resolution,
        leverage: float,
        fee_model,
        extended_market_hours: bool
    ) -> Security:
        """
        Subscribe to a single security with unified logic

        Args:
            symbol: Security symbol
            resolution: Data resolution
            leverage: Leverage multiplier
            fee_model: Fee model instance or None
            extended_market_hours: Extended market hours (only for Equity)

        Returns:
            Security object

        Raises:
            ValueError: If security type is not supported
        """
        # Deduplication check
        if symbol in self.algorithm.Securities:
            security = self.algorithm.Securities[symbol]
            self.algorithm.Debug(
                f"Security {symbol.Value} already subscribed, reusing"
            )
            return security

        # Subscribe based on SecurityType
        sec_type = symbol.SecurityType

        if sec_type == SecurityType.Crypto:
            security = self.algorithm.AddCrypto(
                symbol.Value,
                resolution,
                symbol.ID.Market,
                True,  # fillForward
                leverage
            )
        elif sec_type == SecurityType.CryptoFuture:
            security = self.algorithm.AddCryptoFuture(
                symbol.Value,
                resolution,
                symbol.ID.Market,
                True,  # fillForward
                leverage
            )
        elif sec_type == SecurityType.Equity:
            security = self.algorithm.AddEquity(
                symbol.Value,
                resolution,
                symbol.ID.Market,
                True,  # fillForward
                leverage,
                extended_market_hours
            )
        else:
            raise ValueError(
                f"Unsupported security type: {sec_type}. "
                f"Supported types: Crypto, CryptoFuture, Equity"
            )

        # Configure security properties
        security.DataNormalizationMode = DataNormalizationMode.RAW
        security.SetBuyingPowerModel(SecurityMarginModel(leverage))

        if fee_model is not None:
            security.FeeModel = fee_model

        return security
