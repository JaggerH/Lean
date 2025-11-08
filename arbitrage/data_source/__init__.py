"""
Data source module for crypto exchange integrations

提供统一的接口从各交易所获取 tokenized stock 数据，并同步到 LEAN 数据库。

使用示例：
    # 自动同步模式（最常用）
    from arbitrage.data_source import GateSymbolManager

    manager = GateSymbolManager()  # 自动同步现货+期货到数据库
    future_pairs = manager.get_tokenized_stock_pairs(asset_type='future')

    # 手动控制模式
    manager = GateSymbolManager(auto_sync=False)
    pairs = manager.get_tokenized_stock_pairs(asset_type='spot')
"""
from .base_data_source import BaseDataSource, AssetType
from .kraken import KrakenSymbolManager
from .gate import GateSymbolManager

__all__ = [
    'BaseDataSource',
    'AssetType',
    'KrakenSymbolManager',
    'GateSymbolManager',
]
