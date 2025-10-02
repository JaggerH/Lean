"""
Unit tests for utils module

Note: Tests for Kraken-specific functions have been moved to
tests/data_source/test_kraken.py since they are now part of KrakenSymbolManager.
"""
import unittest
import sys
import os

# Add parent directory to path to import utils
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import CURRENCY_MAP, add_xstocks_to_database


class TestCurrencyMap(unittest.TestCase):
    """Test CURRENCY_MAP constant"""

    def test_currency_map_exists(self):
        """Test that CURRENCY_MAP is defined and contains expected mappings"""
        self.assertIsInstance(CURRENCY_MAP, dict)
        self.assertGreater(len(CURRENCY_MAP), 0)

    def test_common_currencies(self):
        """Test common currency mappings"""
        expected_mappings = {
            'ZUSD': 'USD',
            'ZEUR': 'EUR',
            'ZGBP': 'GBP',
            'XXBT': 'BTC',
            'XETH': 'ETH',
        }

        for kraken_code, standard_code in expected_mappings.items():
            self.assertEqual(CURRENCY_MAP.get(kraken_code), standard_code,
                           f"Expected {kraken_code} -> {standard_code}")


class TestAddXStocksToDatabase(unittest.TestCase):
    """Test add_xstocks_to_database function"""

    def test_function_exists(self):
        """Test that function is importable"""
        self.assertTrue(callable(add_xstocks_to_database))


if __name__ == '__main__':
    unittest.main(verbosity=2)
