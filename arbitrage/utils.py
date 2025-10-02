"""
Utility functions for arbitrage trading
"""
import requests
import csv
import os
from typing import Dict, Any, List


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


def get_xstocks_from_kraken() -> Dict[str, Any]:
    """
    Fetch tokenized stocks (xStocks) from Kraken API

    Returns:
        Dict of xStocks pairs with their details (the 'result' field from API response)

    Raises:
        requests.RequestException: If API request fails
        ValueError: If Kraken API returns an error
    """
    url = 'https://api.kraken.com/0/public/AssetPairs'
    params = {'aclass_base': 'tokenized_asset'}

    response = requests.get(url, params=params)
    response.raise_for_status()

    data = response.json()

    # Check for Kraken API errors
    if data.get('error'):
        raise ValueError(f"Kraken API error: {data['error']}")

    # Return only the result dictionary
    return data.get('result', {})


def map_xstocks_to_symbol_database(xstocks_data: Dict[str, Any]) -> List[str]:
    """
    Map Kraken xStocks data to symbol-properties-database CSV format

    Args:
        xstocks_data: Dictionary from get_xstocks_from_kraken()

    Returns:
        List of CSV rows as strings

    CSV Format:
        market,symbol,type,description,quote_currency,contract_multiplier,
        minimum_price_variation,lot_size,market_ticker,minimum_order_size,
        price_magnifier,strike_multiplier
    """
    csv_rows = []

    for market_ticker, pair_data in xstocks_data.items():
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
        symbol = altname.replace('x', '').replace('/', '')  # AAPLxUSD -> AAPLUSD
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


def get_kraken_trade_pair(kraken_symbol: str) -> str:
    """
    Map Kraken xStock symbol to underlying stock ticker

    Args:
        kraken_symbol: Kraken symbol (e.g., "AAPLxUSD", "TSLAxUSD", "AAPLx/USD")

    Returns:
        Stock ticker symbol (e.g., "AAPL", "TSLA")

    Examples:
        >>> get_kraken_trade_pair("AAPLxUSD")
        "AAPL"
        >>> get_kraken_trade_pair("TSLAxUSD")
        "TSLA"
        >>> get_kraken_trade_pair("AAPLx/USD")
        "AAPL"

    Raises:
        ValueError: If symbol format is invalid
    """
    if not kraken_symbol:
        raise ValueError("Kraken symbol cannot be empty")

    # Remove any slashes (e.g., "AAPLx/USD" -> "AAPLxUSD")
    symbol = kraken_symbol.replace('/', '')

    # Find 'x' followed by currency (USD, EUR, etc.)
    # Pattern: <TICKER>x<CURRENCY>
    if 'x' not in symbol:
        raise ValueError(f"Invalid Kraken xStock symbol format: {kraken_symbol}")

    # Split on 'x' and take the first part
    parts = symbol.split('x')
    if len(parts) < 2 or not parts[0]:
        raise ValueError(f"Invalid Kraken xStock symbol format: {kraken_symbol}")

    stock_ticker = parts[0]

    # Validate that we have a reasonable ticker (alphanumeric, 1-5 chars typically)
    if not stock_ticker.isalpha() or len(stock_ticker) > 10:
        raise ValueError(f"Extracted ticker '{stock_ticker}' seems invalid from {kraken_symbol}")

    return stock_ticker.upper()


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
