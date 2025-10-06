"""
Utility functions for arbitrage trading
"""
import os
import sys
from pathlib import Path
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


def init_lean() -> bool:
    """
    Initialize LEAN environment for running Python code with AlgorithmImports

    This function adds the Launcher/bin/Debug directory to sys.path and changes
    the working directory to that location, enabling imports from AlgorithmImports.py

    Can be called from:
    - arbitrage/tests/test_spread_manager.py
    - arbitrage/tests/data_source/test_kraken.py
    - arbitrage/main.py

    Returns:
        bool: True if initialization succeeded, False otherwise

    Example:
        from utils import init_lean

        if init_lean():
            from AlgorithmImports import QCAlgorithm, Symbol
            # Your code here
        else:
            print("LEAN initialization failed")
    """
    # Determine the LEAN root directory
    # From arbitrage/utils.py, go up one level to reach Lean/
    current_file = Path(__file__).resolve()
    arbitrage_dir = current_file.parent
    lean_root = arbitrage_dir.parent
    launcher_bin = lean_root / "Launcher" / "bin" / "Debug"

    # Check if Launcher/bin/Debug exists
    if not launcher_bin.exists():
        print(f"❌ LEAN bin directory not found: {launcher_bin}")
        print(f"   Please build LEAN first: dotnet build QuantConnect.Lean.sln")
        return False

    # Check if AlgorithmImports.py exists
    algorithm_imports = launcher_bin / "AlgorithmImports.py"
    if not algorithm_imports.exists():
        print(f"❌ AlgorithmImports.py not found: {algorithm_imports}")
        print(f"   Please build LEAN first: dotnet build QuantConnect.Lean.sln")
        return False

    # Add Launcher/bin/Debug to sys.path if not already there
    launcher_bin_str = str(launcher_bin)
    if launcher_bin_str not in sys.path:
        sys.path.insert(0, launcher_bin_str)
        print(f"✅ Added to sys.path: {launcher_bin_str}")

    # Change working directory to Launcher/bin/Debug
    # This is important because AlgorithmImports.py loads DLLs from current directory
    original_cwd = os.getcwd()
    os.chdir(launcher_bin_str)
    print(f"✅ Changed working directory to: {launcher_bin_str}")
    print(f"   (Original: {original_cwd})")

    # Verify PYTHONNET_PYDLL is set
    pythonnet_dll = os.environ.get('PYTHONNET_PYDLL')
    if pythonnet_dll:
        print(f"✅ PYTHONNET_PYDLL: {pythonnet_dll}")
    else:
        print(f"⚠️  PYTHONNET_PYDLL not set (may cause issues)")
        print(f"   Set it to: <conda_env_path>/python311.dll")

    return True


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
