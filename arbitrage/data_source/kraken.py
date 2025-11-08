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
    Kraken 交易所数据源

    支持：
        - 现货 xStocks (SecurityType.Crypto)
        - 不支持期货

    使用方式：
        # 自动同步模式（最常用）
        manager = KrakenSymbolManager()
        pairs = manager.get_pairs(type='spot')

        # 只查询不写库
        manager = KrakenSymbolManager(auto_sync=False)
        pairs = manager.get_pairs(type='spot')

    注意：
        Kraken 只支持现货 xStocks，不支持期货
        调用 get_pairs(type='future') 将返回空列表
    """

    def fetch_spot_data(self) -> Dict[str, Any]:
        """
        从 Kraken API 获取 tokenized assets 现货数据

        API: GET https://api.kraken.com/0/public/AssetPairs?aclass_base=tokenized_asset

        Returns:
            Dict[str, Any]: {market_ticker: pair_info, ...}
                格式: {
                    "AAPLxUSD": {
                        "altname": "AAPLxUSD",
                        "wsname": "AAPLx/USD",
                        "quote": "ZUSD",
                        "tick_size": "0.01",
                        "ordermin": "0.00000001",
                        ...
                    },
                    ...
                }

        Raises:
            requests.RequestException: 如果 API 请求失败
            ValueError: 如果 Kraken API 返回错误
        """
        url = 'https://api.kraken.com/0/public/AssetPairs'
        params = {'aclass_base': 'tokenized_asset'}

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            raise requests.RequestException(f"Failed to fetch Kraken asset pairs: {e}")

        data = response.json()

        # Check for Kraken API errors
        if data.get('error'):
            raise ValueError(f"Kraken API error: {data['error']}")

        # Store and return the result dictionary
        self.spot_data = data.get('result', {})

        print(f"[OK] Fetched {len(self.spot_data)} tokenized assets from Kraken")
        return self.spot_data

    def fetch_future_data(self) -> Dict[str, Any]:
        """
        Kraken 不支持期货

        Returns:
            Dict[str, Any]: 空字典
        """
        self.future_data = {}
        print("[INFO] Kraken does not support futures, future_data is empty")
        return self.future_data

    def is_tokenized_stock(self, symbol_info: Dict, asset_type: str) -> bool:
        """
        判断是否为 tokenized stock

        Kraken API 已经通过 aclass_base='tokenized_asset' 参数预过滤，
        所以现货数据都是 tokenized stocks

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            bool: spot 返回 True，future 返回 False
        """
        # Kraken 只支持现货 xStocks
        return asset_type == 'spot'

    def parse_symbol(self, symbol_info: Dict, asset_type: str) -> Tuple[Symbol, Symbol]:
        """
        将交易所数据转换为 LEAN Symbol 交易对

        Args:
            symbol_info: 交易对信息字典
            asset_type: 'spot' 或 'future'

        Returns:
            Tuple[Symbol, Symbol]: (crypto_symbol, equity_symbol)

        示例:
            输入: {"altname": "AAPLxUSD", "wsname": "AAPLx/USD", ...}
            输出: (Symbol("AAPLXUSD", Crypto, kraken), Symbol("AAPL", Equity, usa))

        注意:
            使用 rsplit('x', 1) 从右边分割，避免 ticker 包含 'x' 的问题
            例如："CVXxUSD" -> ["CVX", "USD"]（正确）
        """
        if asset_type != 'spot':
            raise ValueError(f"Kraken only supports spot, got asset_type={asset_type}")

        # 获取 altname（例如: "AAPLxUSD", "CVXxUSD"）
        market_ticker = symbol_info.get('altname', '')

        if not market_ticker:
            raise ValueError(f"Invalid Kraken data: missing altname")

        # 移除斜杠（"AAPLx/USD" -> "AAPLxUSD"）
        symbol_str = market_ticker.replace('/', '')

        # 从右边分割提取股票代码
        # 使用 rsplit 从右边分割，限制分割次数为1
        # 例如："CVXxUSD" -> ["CVX", "USD"]（正确）
        # 避免 split('x') -> ["CV", "", "USD"]（错误）
        if 'x' not in symbol_str:
            raise ValueError(f"Invalid Kraken symbol format: {symbol_str}")

        parts = symbol_str.rsplit('x', 1)
        if len(parts) < 2 or not parts[0]:
            raise ValueError(f"Failed to parse stock ticker from: {symbol_str}")

        stock_ticker = parts[0].upper()

        # 验证 ticker 格式
        if not stock_ticker.isalpha() or len(stock_ticker) > 10:
            raise ValueError(f"Invalid stock ticker: {stock_ticker}")

        # 创建 LEAN Symbol
        crypto_symbol = Symbol.Create(symbol_str, SecurityType.Crypto, Market.Kraken)
        equity_symbol = Symbol.Create(stock_ticker, SecurityType.Equity, Market.USA)

        return (crypto_symbol, equity_symbol)

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

        示例:
            "kraken,AAPLXUSD,crypto,AAPLx/USD,USD,1,0.01,0.00000001,AAPLxUSD,0.5,,"
        """
        if asset_type != 'spot':
            raise ValueError(f"Kraken only supports spot, got asset_type={asset_type}")

        # 提取字段
        market_ticker = list(symbol_info.keys())[0] if isinstance(symbol_info, dict) and not symbol_info.get('altname') else symbol_info.get('altname', '')

        # 如果 symbol_info 是从 self.spot_data.items() 来的，需要特殊处理
        # 获取实际的字段值
        altname = symbol_info.get('altname', market_ticker)
        wsname = symbol_info.get('wsname', '')
        quote = symbol_info.get('quote', 'ZUSD')
        tick_size = symbol_info.get('tick_size', '0.01')
        ordermin = symbol_info.get('ordermin', '0.00000001')
        costmin = symbol_info.get('costmin', '0.5')
        lot_multiplier = symbol_info.get('lot_multiplier', 1)

        # 映射到 CSV 字段
        market = 'kraken'
        symbol = altname.replace('/', '').upper()
        security_type = 'crypto'
        description = wsname
        quote_currency = CURRENCY_MAP.get(quote, quote)
        contract_multiplier = str(lot_multiplier)
        minimum_price_variation = str(tick_size)
        lot_size = str(ordermin)
        minimum_order_size = str(costmin)
        price_magnifier = ''
        strike_multiplier = ''

        # 构建 CSV 行
        return ','.join([
            market, symbol, security_type, description, quote_currency,
            contract_multiplier, minimum_price_variation, lot_size,
            altname,  # market_ticker 使用 altname
            minimum_order_size, price_magnifier, strike_multiplier
        ])
