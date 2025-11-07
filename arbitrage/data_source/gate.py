"""
Gate.io exchange data source implementation
Supports both xStock (Backed Finance) and Ondo Tokenized stocks
"""
from __future__ import annotations
import sys
import os

import requests
from typing import List, Tuple, Dict, Any
from AlgorithmImports import *

from .base_data_source import BaseDataSource


class GateSymbolManager(BaseDataSource):
    """
    Gate.io交易所的符号管理器

    负责从Gate.io API获取tokenized stock (xStocks和Ondo Tokenized)数据，
    并将其转换为LEAN算法所需的格式

    支持两种tokenized stock提供商:
    1. xStock (Backed Finance) - 后缀 'X', base_name包含 'xStock'
    2. Ondo Tokenized (Ondo Finance) - 后缀 'ON', base_name包含 'Ondo Tokenized'

    同时支持获取Gate.io期货合约数据
    """

    def __init__(self, auto_sync: bool = True):
        """
        初始化Gate符号管理器

        Args:
            auto_sync: 是否自动同步symbol到数据库(默认True)
        """
        # Ensure Gate market is registered
        # In Python.NET, static constructors may not auto-execute,
        # so we explicitly add the market if it's not already registered
        try:
            if Market.Encode("gate") is None:
                Market.Add("gate", 42)  # Gate market ID from Market.cs
        except:
            # Market already registered or other error
            pass

        self.source = None  # 存储从Gate.io API获取的现货原始数据
        self.futures_source = None  # 存储从Gate.io API获取的合约原始数据
        super().__init__(auto_sync=auto_sync)

    def get_tokenize_stocks(self) -> Dict[str, Any]:
        """
        从Gate.io API获取tokenized stocks (xStocks和Ondo Tokenized)

        调用Gate.io的currency_pairs API，筛选base_name包含'xStock'或'Ondo Tokenized'的交易对

        Returns:
            Dict[str, Any]: 以pair_id为key的tokenized stocks字典
            格式: {
                "AAPLX_USDT": {
                    "id": "AAPLX_USDT",
                    "base": "AAPLX",
                    "base_name": "Apple xStock",
                    "quote": "USDT",
                    "min_base_amount": "0.001",
                    ...
                },
                "AAPLON_USDT": {
                    "id": "AAPLON_USDT",
                    "base": "AAPLON",
                    "base_name": "Apple Ondo Tokenized",
                    "quote": "USDT",
                    ...
                },
                ...
            }

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果Gate.io API返回错误
        """
        url = 'https://api.gateio.ws/api/v4/spot/currency_pairs'

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io currency pairs: {e}")

        all_pairs = response.json()

        if not isinstance(all_pairs, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_pairs)}")

        # Filter for tokenized stocks
        # xStock: base_name contains 'xStock' (e.g., "Apple xStock")
        # Ondo: base_name contains 'Ondo Tokenized' (e.g., "Apple Ondo Tokenized")
        tokenized_stocks = {}
        for pair in all_pairs:
            base_name = pair.get('base_name', '')
            if 'xStock' in base_name or 'Ondo Tokenized' in base_name:
                pair_id = pair.get('id')
                if pair_id:
                    tokenized_stocks[pair_id] = pair

        # Store and return
        self.source = tokenized_stocks
        return self.source

    def get_trade_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        将Gate.io tokenized stocks转换为(crypto_symbol, equity_symbol)交易对

        Returns:
            List[Tuple[Symbol, Symbol]]: 交易对列表 [(crypto_symbol, equity_symbol), ...]

        Note:
            - 必须先调用get_tokenize_stocks()以填充self.source
            - 返回的是LEAN Symbol对象（不是Security对象，也不是字符串）
            - 使用 algorithm.add_security(symbol) 可以订阅行情并获取Security对象

        Raises:
            ValueError: 如果self.source为空或符号格式无效
        """
        if self.source is None:
            raise ValueError("Must call get_tokenize_stocks() first")

        trade_pairs = []

        for pair_id, pair_data in self.source.items():
            try:
                # Get base and quote currencies
                base = pair_data.get('base', '')  # e.g., "AAPLX" or "AAPLON"
                quote = pair_data.get('quote', '')  # e.g., "USDT"

                if not base or not quote:
                    continue

                # Extract stock ticker
                stock_ticker = self._extract_stock_ticker(base, pair_data.get('base_name', ''))

                if not stock_ticker:
                    continue

                # Create LEAN crypto symbol (Gate format: remove underscore)
                # AAPLX_USDT -> AAPLXUSDT
                crypto_symbol_str = f"{base}{quote}"

                # Create LEAN Symbol objects
                crypto_symbol = Symbol.Create(crypto_symbol_str, SecurityType.Crypto, "gate")
                equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, "usa")

                trade_pairs.append((crypto_symbol, equity_symbol))

            except Exception as e:
                # Debug: print exceptions
                import traceback
                print(f"[DEBUG] Failed to process {pair_id}: {e}")
                traceback.print_exc()
                continue

        return trade_pairs

    def _extract_stock_ticker(self, base: str, base_name: str) -> str:
        """
        从base currency中提取股票代码

        Args:
            base: 基础货币，如 "AAPLX", "AAPLON"
            base_name: 完整名称，如 "Apple xStock", "Apple Ondo Tokenized"

        Returns:
            股票代码，如 "AAPL"，如果无法提取则返回空字符串

        Logic:
            - xStock: 移除后缀 'X' (AAPLX -> AAPL)
            - Ondo: 移除后缀 'ON' (AAPLON -> AAPL)
            - 特殊情况: 像 "MA" (Mastercard) 使用 "MAX" 作为xStock, 需要特殊处理
        """
        if not base:
            return ''

        # xStock: ends with 'X'
        if 'xStock' in base_name and base.endswith('X'):
            ticker = base[:-1]  # Remove trailing 'X'
            # Validate ticker (should be 1-5 uppercase letters)
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        # Ondo Tokenized: ends with 'ON'
        elif 'Ondo Tokenized' in base_name and base.endswith('ON'):
            ticker = base[:-2]  # Remove trailing 'ON'
            # Validate ticker
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        return ''

    def get_records_to_database(self) -> List[str]:
        """
        将Gate.io tokenized stocks转换为LEAN数据库CSV格式

        Returns:
            List[str]: CSV格式的记录列表，每行是一个完整的CSV记录

        CSV格式:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        Example:
            ["gate,AAPLXUSDT,crypto,Apple xStock,USDT,1,0.01,0.001,AAPLX_USDT,3,,"]

        Note:
            必须先调用get_tokenize_stocks()以填充self.source

        Raises:
            ValueError: 如果self.source为空
        """
        if self.source is None:
            raise ValueError("Must call get_tokenize_stocks() first")

        csv_rows = []

        for pair_id, pair_data in self.source.items():
            # Extract fields from Gate.io API
            base = pair_data.get('base', '')
            base_name = pair_data.get('base_name', '')
            quote = pair_data.get('quote', '')
            min_base_amount = pair_data.get('min_base_amount', '0.001')
            min_quote_amount = pair_data.get('min_quote_amount', '3')
            precision = pair_data.get('precision', 2)
            amount_precision = pair_data.get('amount_precision', 3)

            # Map to CSV fields
            market = 'gate'
            symbol = f"{base}{quote}".upper()  # AAPLXUSDT (no underscore for LEAN)
            security_type = 'crypto'
            description = base_name  # "Apple xStock" or "Apple Ondo Tokenized"
            quote_currency = quote  # "USDT"
            contract_multiplier = '1'
            minimum_price_variation = f"{10 ** -precision}"  # precision=2 -> 0.01
            lot_size = min_base_amount
            market_ticker = pair_id  # "AAPLX_USDT" (Gate.io format with underscore)
            minimum_order_size = min_quote_amount
            price_magnifier = ''  # Empty for crypto
            strike_multiplier = ''  # Empty for crypto

            # Build CSV row
            csv_row = ','.join([
                market,
                symbol,
                security_type,
                description,
                quote_currency,
                contract_multiplier,
                minimum_price_variation,
                lot_size,
                market_ticker,
                minimum_order_size,
                price_magnifier,
                strike_multiplier
            ])

            csv_rows.append(csv_row)

        return csv_rows

    # ========== Futures Contract Methods ==========

    def get_futures_contracts(self, settle: str = "usdt", filter_tokenized: bool = False) -> Dict[str, Any]:
        """
        从Gate.io API批量获取期货合约信息

        Args:
            settle: 结算货币，可选 "usdt", "btc", "usd" (默认 "usdt")
            filter_tokenized: 是否只返回tokenized stocks相关的合约 (默认 False)

        Returns:
            Dict[str, Any]: 以contract name为key的合约字典
            格式: {
                "BTC_USDT": {
                    "name": "BTC_USDT",
                    "type": "direct",
                    "quanto_multiplier": "0.0001",
                    "order_size_min": 1,
                    "order_price_round": "0.1",
                    "mark_price": "38000",
                    ...
                },
                "AAPLX_USDT": {
                    "name": "AAPLX_USDT",
                    "quanto_multiplier": "0.001",
                    "order_size_min": 1,
                    ...
                },
                ...
            }

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果Gate.io API返回错误或settle参数无效
        """
        valid_settles = ["usdt", "btc", "usd"]
        if settle.lower() not in valid_settles:
            raise ValueError(f"Invalid settle parameter: {settle}. Must be one of {valid_settles}")

        url = f'https://api.gateio.ws/api/v4/futures/{settle.lower()}/contracts'

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io futures contracts: {e}")

        all_contracts = response.json()

        if not isinstance(all_contracts, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_contracts)}")

        # Convert list to dict with contract name as key
        contracts_dict = {}
        for contract in all_contracts:
            contract_name = contract.get('name')
            if contract_name:
                # Filter for tokenized stocks if requested
                if filter_tokenized:
                    # Check if contract name contains xStock or Ondo patterns
                    # Examples: AAPLX_USDT, AAPLON_USDT
                    if 'X_' in contract_name or 'ON_' in contract_name:
                        contracts_dict[contract_name] = contract
                else:
                    contracts_dict[contract_name] = contract

        # Store and return
        self.futures_source = contracts_dict
        return self.futures_source

    def get_single_futures_contract(self, contract: str, settle: str = "usdt") -> Dict[str, Any]:
        """
        查询单个期货合约的详细信息

        Args:
            contract: 合约名称，如 "BTC_USDT", "AAPLX_USDT"
            settle: 结算货币，可选 "usdt", "btc", "usd" (默认 "usdt")

        Returns:
            Dict[str, Any]: 合约详细信息
            格式: {
                "name": "BTC_USDT",
                "type": "direct",
                "quanto_multiplier": "0.0001",
                "order_size_min": 1,
                "order_price_round": "0.1",
                "mark_price": "38000",
                ...
            }

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果settle参数无效或合约不存在
        """
        valid_settles = ["usdt", "btc", "usd"]
        if settle.lower() not in valid_settles:
            raise ValueError(f"Invalid settle parameter: {settle}. Must be one of {valid_settles}")

        url = f'https://api.gateio.ws/api/v4/futures/{settle.lower()}/contracts/{contract}'

        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch contract {contract}: {e}")

        contract_data = response.json()

        if not isinstance(contract_data, dict):
            raise ValueError(f"Unexpected API response format: expected dict, got {type(contract_data)}")

        # Store in futures_source (create dict if not exists)
        if self.futures_source is None:
            self.futures_source = {}

        contract_name = contract_data.get('name', contract)
        self.futures_source[contract_name] = contract_data

        return contract_data

    def get_futures_records_to_database(self) -> List[str]:
        """
        将Gate.io期货合约转换为LEAN数据库CSV格式

        Returns:
            List[str]: CSV格式的记录列表，每行是一个完整的CSV记录

        CSV格式:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        Example:
            ["gate,BTCUSDT,cryptofuture,BTC Perpetual,USDT,0.0001,0.1,1,BTC_USDT,,,"]

        Field Mapping:
            - quanto_multiplier → contract_multiplier
            - order_size_min → lot_size
            - order_price_round → minimum_price_variation
            - name → market_ticker

        Note:
            必须先调用get_futures_contracts()或get_single_futures_contract()以填充self.futures_source

        Raises:
            ValueError: 如果self.futures_source为空
        """
        if self.futures_source is None or len(self.futures_source) == 0:
            raise ValueError("Must call get_futures_contracts() or get_single_futures_contract() first")

        csv_rows = []

        for contract_name, contract_data in self.futures_source.items():
            # Extract fields from Gate.io Futures API
            name = contract_data.get('name', '')  # e.g., "BTC_USDT"
            contract_type = contract_data.get('type', 'direct')  # "direct", "inverse", etc.
            quanto_multiplier = contract_data.get('quanto_multiplier', '1')
            order_size_min = contract_data.get('order_size_min', 1)
            order_price_round = contract_data.get('order_price_round', '0.01')

            # Parse contract name to get base and quote
            # Format: BASE_QUOTE (e.g., "BTC_USDT")
            parts = name.split('_')
            if len(parts) >= 2:
                base = parts[0]
                quote = parts[1]
            else:
                # Fallback: use original name
                base = name
                quote = 'USDT'

            # Map to CSV fields
            market = 'gate'
            symbol = f"{base}{quote}".upper()  # BTCUSDT (no underscore for LEAN)
            security_type = 'cryptofuture'
            description = f"{base} Perpetual"  # Simple description
            quote_currency = quote
            contract_multiplier = quanto_multiplier
            minimum_price_variation = order_price_round
            lot_size = str(order_size_min)
            market_ticker = name  # "BTC_USDT" (Gate.io format with underscore)
            minimum_order_size = ''  # Not applicable for futures
            price_magnifier = ''  # Empty for crypto futures
            strike_multiplier = ''  # Empty for crypto futures

            # Build CSV row
            csv_row = ','.join([
                market,
                symbol,
                security_type,
                description,
                quote_currency,
                contract_multiplier,
                minimum_price_variation,
                lot_size,
                market_ticker,
                minimum_order_size,
                price_magnifier,
                strike_multiplier
            ])

            csv_rows.append(csv_row)

        return csv_rows
