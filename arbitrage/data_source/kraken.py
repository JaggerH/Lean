"""
Kraken exchange data source implementation
"""
from __future__ import annotations
import sys
import os



import requests
from typing import List, Tuple, Dict, Any
from AlgorithmImports import *

from .base_data_source import BaseDataSource

# Currency mapping from Kraken format to standard format
CURRENCY_MAP = {
    'ZUSD': 'USD',
    'ZEUR': 'EUR',
    'ZGBP': 'GBP',
    'ZAUD': 'AUD',
    'ZCAD': 'CAD',
    'ZJPY': 'JPY',
    'XXBT': 'BTC',
    'XXRP': 'XRP',
    'XLTC': 'LTC',
    'XETH': 'ETH'
}


class KrakenSymbolManager(BaseDataSource):
    """
    Kraken交易所的符号管理器

    负责从Kraken API获取tokenized stock (xStocks)数据，
    并将其转换为LEAN算法所需的格式
    """

    def __init__(self):
        """初始化Kraken符号管理器"""
        super().__init__()
        self.source = None  # 存储从Kraken API获取的原始xStocks数据

    def get_tokenize_stocks(self) -> Dict[str, Any]:
        """
        从Kraken API获取tokenized stocks (xStocks)

        调用Kraken的AssetPairs API，筛选aclass_base='tokenized_asset'的交易对

        Returns:
            Dict[str, Any]: Kraken API返回的xStocks数据
            格式: {
                "AAPLxUSD": {
                    "altname": "AAPLxUSD",
                    "wsname": "AAPLx/USD",
                    "quote": "ZUSD",
                    "tick_size": "0.01",
                    ...
                },
                ...
            }

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果Kraken API返回错误
        """
        url = 'https://api.kraken.com/0/public/AssetPairs'
        params = {'aclass_base': 'tokenized_asset'}

        response = requests.get(url, params=params)
        response.raise_for_status()

        data = response.json()

        # Check for Kraken API errors
        if data.get('error'):
            raise ValueError(f"Kraken API error: {data['error']}")

        # Store and return the result dictionary
        self.source = data.get('result', {})
        return self.source

    def get_trade_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        将Kraken xStocks转换为(crypto_symbol, equity_symbol)交易对

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

        for market_ticker, pair_data in self.source.items():
            try:
                # 从Kraken格式提取altname (如 "AAPLxUSD", "CVXxUSD")
                altname = pair_data.get('altname', market_ticker)

                # 转换为LEAN crypto symbol格式（保留'x'后缀，只移除斜杠）
                # "AAPLxUSD" -> "AAPLxUSD" 或 "AAPLx/USD" -> "AAPLxUSD"
                crypto_symbol_str = altname.replace('/', '')

                # 提取对应的股票代码
                # 移除任何斜杠 (e.g., "AAPLx/USD" -> "AAPLxUSD")
                symbol = altname.replace('/', '')

                # 找到'x'并分割（从右边分割，避免ticker本身包含'x'的问题）
                if 'x' not in symbol:
                    continue

                # 使用 rsplit 从右边分割，限制分割次数为1
                # 例如："CVXxUSD" -> ["CVX", "USD"]（正确）
                # 而不是 split('x') -> ["CV", "", "USD"]（错误）
                parts = symbol.rsplit('x', 1)
                if len(parts) < 2 or not parts[0]:
                    continue

                equity_symbol_str = parts[0].upper()

                # 验证提取的ticker是否合理
                if not equity_symbol_str.isalpha() or len(equity_symbol_str) > 10:
                    continue

                # 创建LEAN Security对象
                crypto_symbol = Symbol.Create(crypto_symbol_str, SecurityType.Crypto, Market.Kraken)
                equity_symbol = Symbol.Create(equity_symbol_str, SecurityType.Equity, Market.USA)

                trade_pairs.append((crypto_symbol, equity_symbol))

            except Exception as e:
                # 跳过格式无效的交易对
                continue

        return trade_pairs

    def get_records_to_database(self) -> List[str]:
        """
        将Kraken xStocks转换为LEAN数据库CSV格式

        Returns:
            List[str]: CSV格式的记录列表，每行是一个完整的CSV记录

        CSV格式:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        Example:
            ["kraken,AAPLxUSD,crypto,AAPLx/USD,USD,1,0.01,0.00000001,AAPLxUSD,0.5,,"]

        Note:
            必须先调用get_tokenize_stocks()以填充self.source

        Raises:
            ValueError: 如果self.source为空
        """
        if self.source is None:
            raise ValueError("Must call get_tokenize_stocks() first")

        csv_rows = []

        for market_ticker, pair_data in self.source.items():
            # Extract fields from Kraken API
            altname = pair_data.get('altname', market_ticker)
            wsname = pair_data.get('wsname', '')
            quote = pair_data.get('quote', 'ZUSD')
            tick_size = pair_data.get('tick_size', '0.01')
            ordermin = pair_data.get('ordermin', '0.00000001')
            costmin = pair_data.get('costmin', '0.5')
            lot_multiplier = pair_data.get('lot_multiplier', 1)

            # Map to CSV fields
            market = 'kraken'
            symbol = altname.replace('/', '').upper()  # 转换为大写：AAPLxUSD -> AAPLXUSD (LEAN要求大写)
            security_type = 'crypto'
            description = wsname  # AAPLx/USD
            quote_currency = CURRENCY_MAP.get(quote, quote)  # ZUSD -> USD
            contract_multiplier = str(lot_multiplier)
            minimum_price_variation = str(tick_size)
            lot_size = str(ordermin)
            minimum_order_size = str(costmin)
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
