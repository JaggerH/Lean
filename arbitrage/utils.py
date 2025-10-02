"""
Utility functions for arbitrage trading
"""
import os
from typing import List, Dict


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


def add_xstocks_to_database(csv_rows: List[str], base_path: str = None) -> Dict[str, int]:
    """
    Add xStocks entries to symbol-properties-database.csv files, avoiding duplicates

    Args:
        csv_rows: List of CSV row strings from map_xstocks_to_symbol_database()
        base_path: Base path to Lean directory (default: auto-detect from __file__)

    Returns:
        Dict with 'added' and 'skipped' counts

    Updates two files:
        - Data/symbol-properties/symbol-properties-database.csv
        - Launcher/bin/Debug/symbol-properties/symbol-properties-database.csv
    """
    if base_path is None:
        # Auto-detect: go up from arbitrage/ to Lean/
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    csv_files = [
        os.path.join(base_path, 'Data', 'symbol-properties', 'symbol-properties-database.csv'),
        os.path.join(base_path, 'Launcher', 'bin', 'Debug', 'symbol-properties', 'symbol-properties-database.csv')
    ]

    results = {'added': 0, 'skipped': 0}

    for csv_file in csv_files:
        if not os.path.exists(csv_file):
            print(f"Warning: CSV file not found: {csv_file}")
            continue

        # Read existing entries
        existing_symbols = set()
        with open(csv_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split(',')
                if len(parts) >= 2:
                    market = parts[0]
                    symbol = parts[1]
                    # Store (market, symbol) tuple
                    existing_symbols.add((market, symbol))

        # Filter new rows to avoid duplicates
        new_rows = []
        for row in csv_rows:
            parts = row.split(',')
            if len(parts) >= 2:
                market = parts[0]
                symbol = parts[1]
                if (market, symbol) not in existing_symbols:
                    new_rows.append(row)
                    existing_symbols.add((market, symbol))  # Add to set to avoid duplicates within new_rows

        if new_rows:
            # Append new rows to file
            with open(csv_file, 'a', encoding='utf-8') as f:
                for row in new_rows:
                    f.write(row + '\n')

            # Only count added rows once (from first file)
            if csv_file == csv_files[0]:
                results['added'] = len(new_rows)
                results['skipped'] = len(csv_rows) - len(new_rows)

            print(f"Added {len(new_rows)} xStocks to {csv_file}")
        else:
            print(f"No new xStocks to add to {csv_file} (all already exist)")

    return results
