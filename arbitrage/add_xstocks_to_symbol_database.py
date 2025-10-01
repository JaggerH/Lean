#!/usr/bin/env python
"""
Script to add Kraken xStocks to symbol-properties-database.csv
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from utils import get_xstocks_from_kraken, map_xstocks_to_symbol_database, add_xstocks_to_database


def main():
    print("Fetching xStocks from Kraken API...")
    xstocks_data = get_xstocks_from_kraken()
    print(f"Found {len(xstocks_data)} xStocks")

    print("\nMapping xStocks to CSV format...")
    csv_rows = map_xstocks_to_symbol_database(xstocks_data)
    print(f"Generated {len(csv_rows)} CSV rows")

    # Show first 3 examples
    print("\nExample CSV rows:")
    for i, row in enumerate(csv_rows[:3]):
        print(f"  {i+1}. {row}")

    # Ask for confirmation
    response = input(f"\nAdd {len(csv_rows)} xStocks to database? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled.")
        return

    print("\nAdding xStocks to database...")
    results = add_xstocks_to_database(csv_rows)

    print(f"\nResults:")
    print(f"  Added: {results['added']}")
    print(f"  Skipped (already exist): {results['skipped']}")
    print("\nDone!")


if __name__ == '__main__':
    main()
