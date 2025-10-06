"""
Base data source abstraction for crypto exchange integration
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Any
import sys
import os


from AlgorithmImports import *

class BaseDataSource(ABC):
    """
    BaseDataSource是一个抽象接口，用于从虚拟货币交易所获取可交易对信息，
    并根据需要的功能实现对应转换

    这个抽象类定义了所有数据源必须实现的核心接口，用于：
    1. 从交易所API获取tokenized stock交易对
    2. 将交易所格式转换为LEAN符号格式
    3. 生成LEAN数据库所需的记录格式
    """

    def __init__(self):
        """初始化数据源"""
        self.source = None  # 用于记录从交易所获得的可交易对的raw data

    @abstractmethod
    def get_tokenize_stocks(self):
        """
        访问交易所API获取用于套利的交易对基础信息

        此方法应该：
        1. 调用交易所API
        2. 获取tokenized stock交易对数据
        3. 将原始数据存储在self.source中

        Returns:
            Dict[str, Any]: 交易所返回的原始交易对数据

        Raises:
            requests.RequestException: 如果API请求失败
            ValueError: 如果交易所API返回错误
        """
        pass

    @abstractmethod
    def get_trade_pairs(self) -> List[Tuple[Symbol, Symbol]]:
        """
        将交易所获得的交易对信息转换成LEAN Crypto Symbol和Equity Symbol

        此方法应该：
        1. 从self.source中读取原始交易对数据
        2. 解析每个交易对，提取crypto symbol和对应的stock symbol
        3. 使用Symbol.Create()创建LEAN Symbol对象
        4. 返回(crypto_symbol, equity_symbol)元组列表

        Returns:
            List[Tuple[Symbol, Symbol]]: [(CryptoSymbol, EquitySymbol), ...]
            例如: [
                (Symbol.Create("AAPLUSD", SecurityType.Crypto, Market.Kraken),
                 Symbol.Create("AAPL", SecurityType.Equity, Market.USA)),
                (Symbol.Create("TSLAUSD", SecurityType.Crypto, Market.Kraken),
                 Symbol.Create("TSLA", SecurityType.Equity, Market.USA))
            ]

        Note:
            - 返回的是LEAN Symbol对象（不是Security对象，也不是字符串）
            - 使用 algorithm.add_security(symbol) 可以将Symbol转换为Security并订阅行情
            - crypto_symbol: SecurityType.Crypto + 对应交易所的market
            - equity_symbol: SecurityType.Equity + Market.USA
        """
        pass

    @abstractmethod
    def get_records_to_database(self) -> List[str]:
        """
        将可交易symbol转换成LEAN Database需要的格式

        此方法应该：
        1. 从self.source中读取原始交易对数据
        2. 将每个交易对转换为符合symbol-properties-database.csv格式的CSV行
        3. 返回CSV行字符串列表

        Returns:
            List[str]: CSV格式的记录列表

        CSV格式:
            market,symbol,type,description,quote_currency,contract_multiplier,
            minimum_price_variation,lot_size,market_ticker,minimum_order_size,
            price_magnifier,strike_multiplier

        Example:
            ["kraken,AAPLUSD,crypto,AAPLx/USD,USD,1,0.01,0.00000001,AAPLxUSD,0.5,,"]
        """
        pass
