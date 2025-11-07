"""
Data source module for crypto exchange integrations
"""
from .base_data_source import BaseDataSource
from .kraken import KrakenSymbolManager
from .gate import GateSymbolManager

__all__ = ['BaseDataSource', 'KrakenSymbolManager', 'GateSymbolManager']
