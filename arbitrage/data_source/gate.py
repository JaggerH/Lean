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
    Gate.io 交易所数据源

    支持：
        - 现货 (SecurityType.Crypto)
        - USDT 永续合约 (SecurityType.CryptoFuture)
        - xStock (Backed Finance) 和 Ondo Tokenized stocks

    使用方式：
        # 自动同步模式（最常用）
        manager = GateSymbolManager()
        pairs = manager.get_pairs(type='future')

        # 只查询不写库
        manager = GateSymbolManager(auto_sync=False)
        pairs = manager.get_pairs(type='spot')

        # 手动刷新
        result = manager.refresh()

    支持的 tokenized stock 提供商:
        1. xStock (Backed Finance) - 后缀 'X', base_name 包含 'xStock'
        2. Ondo Tokenized (Ondo Finance) - 后缀 'ON', base_name 包含 'Ondo Tokenized'
    """

    # Tokenized stock 提供商标识
    TOKENIZED_PROVIDERS = ['xStock', 'Ondo Tokenized']

    # API 端点
    SPOT_API = 'https://api.gateio.ws/api/v4/spot/currency_pairs'
    FUTURES_API = 'https://api.gateio.ws/api/v4/futures/usdt/contracts'

    def fetch_spot_data(self) -> Dict[str, Any]:
        """
        从 Gate.io API 获取现货交易对数据

        API: GET https://api.gateio.ws/api/v4/spot/currency_pairs

        Returns:
            Dict[str, Any]: {pair_id: pair_info, ...}
                格式: {
                    "AAPLX_USDT": {
                        "id": "AAPLX_USDT",
                        "base": "AAPLX",
                        "base_name": "Apple xStock",
                        "quote": "USDT",
                        "min_base_amount": "0.001",
                        "precision": 2,
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.SPOT_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io spot pairs: {e}")

        all_pairs = response.json()

        if not isinstance(all_pairs, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_pairs)}")

        # 转换为字典格式（以 pair_id 为 key）
        self.spot_data = {pair.get('id'): pair for pair in all_pairs if pair.get('id')}

        print(f"[OK] Fetched {len(self.spot_data)} spot pairs from Gate.io")
        return self.spot_data

    def fetch_future_data(self) -> Dict[str, Any]:
        """
        从 Gate.io API 获取 USDT 永续合约数据

        API: GET https://api.gateio.ws/api/v4/futures/usdt/contracts

        Returns:
            Dict[str, Any]: {contract_name: contract_info, ...}
                格式: {
                    "BTC_USDT": {
                        "name": "BTC_USDT",
                        "type": "direct",
                        "quanto_multiplier": "0.0001",
                        "order_size_min": 1,
                        "order_price_round": "0.1",
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
        """
        try:
            response = requests.get(self.FUTURES_API, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Gate.io futures contracts: {e}")

        all_contracts = response.json()

        if not isinstance(all_contracts, list):
            raise ValueError(f"Unexpected API response format: expected list, got {type(all_contracts)}")

        # 转换为字典格式（以 contract name 为 key）
        self.future_data = {contract.get('name'): contract for contract in all_contracts if contract.get('name')}

        print(f"[OK] Fetched {len(self.future_data)} futures contracts from Gate.io")
        return self.future_data

    def is_tokenized_stock(self, symbol_info: Dict, asset_type: str) -> bool:
        """
        判断是否为 xStock 或 onStock tokenized asset

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            bool: True 表示是 tokenized stock

        现货判断逻辑:
            检查 base_name 是否包含 'xStock' 或 'Ondo Tokenized'

        期货判断逻辑:
            检查合约名称是否包含 X_ 或 ON_ 前缀
            （例如: AAPLX_USDT, AAPLON_USDT）
        """
        if asset_type == 'spot':
            # 现货：检查 base_name
            base_name = symbol_info.get('base_name', '')
            return any(provider in base_name for provider in self.TOKENIZED_PROVIDERS)

        elif asset_type == 'future':
            # 期货：检查合约名称
            name = symbol_info.get('name', '')
            if not name:
                return False

            # 解析 base（例如: "AAPLX_USDT" -> "AAPLX"）
            base = name.split('_')[0]
            return base.endswith('X') or base.endswith('ON')

        return False

    def parse_symbol(self, symbol_info: Dict, asset_type: str) -> Tuple[Symbol, Symbol]:
        """
        将交易所数据转换为 LEAN Symbol 交易对

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            Tuple[Symbol, Symbol]: (crypto_symbol, equity_symbol)

        现货示例:
            输入: {"id": "AAPLX_USDT", "base": "AAPLX", "quote": "USDT", "base_name": "Apple xStock"}
            输出: (Symbol("AAPLXUSDT", Crypto, gate), Symbol("AAPL", Equity, usa))

        期货示例:
            输入: {"name": "AAPLX_USDT", ...}
            输出: (Symbol("AAPLXUSDT", CryptoFuture, gate), Symbol("AAPL", Equity, usa))
        """
        if asset_type == 'spot':
            # 现货处理
            base = symbol_info.get('base', '')
            quote = symbol_info.get('quote', '')
            base_name = symbol_info.get('base_name', '')

            if not base or not quote:
                raise ValueError(f"Invalid spot data: missing base or quote")

            # 提取股票代码
            stock_ticker = self._extract_stock_ticker(base, base_name)

            if not stock_ticker:
                raise ValueError(f"Failed to extract stock ticker from base={base}, base_name={base_name}")

            # 创建 Symbol（LEAN 格式：无下划线）
            crypto_symbol = Symbol.Create(f"{base}{quote}", SecurityType.Crypto, "gate")
            equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, Market.USA)

            return (crypto_symbol, equity_symbol)

        elif asset_type == 'future':
            # 期货处理
            name = symbol_info.get('name', '')

            if not name:
                raise ValueError(f"Invalid future data: missing name")

            # 解析合约名称（格式: "AAPLX_USDT"）
            parts = name.split('_')
            if len(parts) < 2:
                raise ValueError(f"Invalid futures contract name format: {name}")

            base = parts[0]
            quote = parts[1]

            # 提取股票代码
            stock_ticker = self._extract_stock_ticker(base, "")

            if not stock_ticker:
                raise ValueError(f"Failed to extract stock ticker from futures contract: {name}")

            # 创建 Symbol
            crypto_symbol = Symbol.Create(f"{base}{quote}", SecurityType.CryptoFuture, "gate")
            equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, Market.USA)

            return (crypto_symbol, equity_symbol)

        else:
            raise ValueError(f"Unsupported asset_type: {asset_type}")

    def to_csv_row(self, symbol_info: Dict, asset_type: str) -> str:
        """
        将交易对信息转换为 CSV 行

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            str: CSV 格式字符串（不含换行符）

        CSV 格式（12 个字段）:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier
        """
        if asset_type == 'spot':
            return self._spot_to_csv(symbol_info)
        elif asset_type == 'future':
            return self._future_to_csv(symbol_info)
        else:
            raise ValueError(f"Unsupported asset_type: {asset_type}")

    def _spot_to_csv(self, pair_data: Dict) -> str:
        """
        现货交易对转 CSV

        示例:
            "gate,AAPLXUSDT,crypto,Apple xStock,USDT,1,0.01,0.001,AAPLX_USDT,3,,"
        """
        # 提取字段
        pair_id = pair_data.get('id', '')
        base = pair_data.get('base', '')
        base_name = pair_data.get('base_name', '')
        quote = pair_data.get('quote', '')
        min_base_amount = pair_data.get('min_base_amount', '0.001')
        min_quote_amount = pair_data.get('min_quote_amount', '3')
        precision = pair_data.get('precision', 2)

        # 映射到 CSV 字段
        market = 'gate'
        symbol = f"{base}{quote}".upper()
        security_type = 'crypto'
        description = base_name
        quote_currency = quote
        contract_multiplier = '1'
        minimum_price_variation = f"{10 ** -precision}"
        lot_size = min_base_amount
        market_ticker = pair_id
        minimum_order_size = min_quote_amount
        price_magnifier = ''
        strike_multiplier = ''

        # 构建 CSV 行
        return ','.join([
            market, symbol, security_type, description, quote_currency,
            contract_multiplier, minimum_price_variation, lot_size,
            market_ticker, minimum_order_size, price_magnifier, strike_multiplier
        ])

    def _future_to_csv(self, contract_data: Dict) -> str:
        """
        期货合约转 CSV

        示例:
            "gate,BTCUSDT,cryptofuture,BTC Perpetual,USDT,0.0001,0.1,1,BTC_USDT,,,"
        """
        # 提取字段
        name = contract_data.get('name', '')
        quanto_multiplier = contract_data.get('quanto_multiplier', '1')
        order_size_min = contract_data.get('order_size_min', 1)
        order_price_round = contract_data.get('order_price_round', '0.01')

        # 解析合约名称
        parts = name.split('_')
        if len(parts) >= 2:
            base = parts[0]
            quote = parts[1]
        else:
            base = name
            quote = 'USDT'

        # 映射到 CSV 字段
        market = 'gate'
        symbol = f"{base}{quote}".upper()
        security_type = 'cryptofuture'
        description = f"{base} Perpetual"
        quote_currency = quote
        contract_multiplier = quanto_multiplier
        minimum_price_variation = order_price_round
        lot_size = str(order_size_min)
        market_ticker = name
        minimum_order_size = ''
        price_magnifier = ''
        strike_multiplier = ''

        # 构建 CSV 行
        return ','.join([
            market, symbol, security_type, description, quote_currency,
            contract_multiplier, minimum_price_variation, lot_size,
            market_ticker, minimum_order_size, price_magnifier, strike_multiplier
        ])

    def _extract_stock_ticker(self, base: str, base_name: str) -> str:
        """
        从 base currency 中提取股票代码

        Args:
            base: 基础货币，如 "AAPLX", "AAPLON"
            base_name: 完整名称，如 "Apple xStock", "Apple Ondo Tokenized"

        Returns:
            股票代码，如 "AAPL"，如果无法提取则返回空字符串

        逻辑:
            - xStock: 移除后缀 'X' (AAPLX -> AAPL)
            - Ondo: 移除后缀 'ON' (AAPLON -> AAPL)
            - 验证: 1-6 个大写字母
        """
        if not base:
            return ''

        # xStock: ends with 'X'
        if base.endswith('X') and (not base_name or 'xStock' in base_name):
            ticker = base[:-1]
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        # Ondo Tokenized: ends with 'ON'
        elif base.endswith('ON') and (not base_name or 'Ondo Tokenized' in base_name):
            ticker = base[:-2]
            if ticker and ticker.isalpha() and ticker.isupper() and 1 <= len(ticker) <= 6:
                return ticker

        return ''
