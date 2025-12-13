"""
Base classes for validate_data tests

This module provides reusable base classes for:
- Spread Analysis: Collect and visualize spread data
- Data Validation: Execute trades and validate data quality
"""

from .spread_collector import SpreadCollector
from .base_spread_analysis import BaseSpreadAnalysis
from .base_data_validation import BaseDataValidation

__all__ = [
    'SpreadCollector',
    'BaseSpreadAnalysis',
    'BaseDataValidation',
]
