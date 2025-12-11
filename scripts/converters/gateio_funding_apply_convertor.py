"""
Gate.io Funding Apply Converter for LEAN
Converts Gate.io funding rate data to QuantConnect LEAN margin_interest format
"""

import gzip
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Symbol mapping: Gate.io → LEAN format
SYMBOL_MAP = {
    'BTC_USDT': 'BTCUSDT',
    'ETH_USDT': 'ETHUSDT',
    'BNB_USDT': 'BNBUSDT',
}


def scan_files(data_dir, pattern="*.csv.gz"):
    """
    Scan directory for data files

    Args:
        data_dir: Data directory path
        pattern: File matching pattern

    Returns:
        list: List of Path objects
    """
    data_path = Path(data_dir)

    if not data_path.exists():
        logger.warning(f"Directory not found: {data_path}")
        return []

    files = sorted(data_path.glob(pattern))
    logger.info(f"Found {len(files)} files in {data_path}")

    return files


def parse_filename(filename):
    """
    Parse Gate.io funding apply filename to extract symbol and month

    Filename format: BTC_USDT-202510.csv.gz

    Args:
        filename: Filename string

    Returns:
        dict: {'symbol': str, 'month': str} or None
    """
    import re

    # Pattern: SYMBOL-YYYYMM.csv.gz
    pattern = r"(.+)-(\d{6})\.csv\.gz$"
    match = re.match(pattern, filename)

    if match:
        symbol = match.group(1)
        month_str = match.group(2)

        return {
            'symbol': symbol,
            'month': month_str  # YYYYMM
        }

    logger.warning(f"Cannot parse filename: {filename}")
    return None


def convert_funding_apply_file(src_file, dst_root, lean_symbol):
    """
    Convert a single funding apply file to LEAN margin_interest format

    Args:
        src_file: Source file path (csv.gz)
        dst_root: Output root directory
        lean_symbol: LEAN symbol name
    """
    logger.info(f"Processing funding apply file: {src_file.name}")

    # Read Gate.io funding apply data (no header in CSV)
    # Format: timestamp,funding_rate
    try:
        with gzip.open(src_file, 'rt') as f:
            df = pd.read_csv(
                f,
                header=None,
                names=['Timestamp', 'FundingRate']
            )
    except Exception as e:
        logger.error(f"Failed to read {src_file.name}: {e}")
        return

    if df.empty:
        logger.warning(f"No data in {src_file.name}")
        return

    logger.info(f"  Loaded {len(df)} funding rate records")

    # Convert timestamp to datetime
    df['DateTime'] = pd.to_datetime(df['Timestamp'], unit='s', utc=True)

    # Format datetime as "YYYYMMDD HH:MM:SS"
    df['DateTimeStr'] = df['DateTime'].dt.strftime('%Y%m%d %H:%M:%S')

    # Format funding rate with 8 decimal places
    df['RateStr'] = df['FundingRate'].map(lambda x: f"{x:.8f}")

    # Build output dataframe
    out_df = pd.DataFrame({
        'DateTime': df['DateTimeStr'],
        'Rate': df['RateStr']
    })

    # Sort by datetime
    out_df = out_df.sort_values('DateTime')

    # Create output directory
    dst_dir = Path(dst_root)
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Output file path: {symbol}.csv (lowercase)
    output_file = dst_dir / f"{lean_symbol.lower()}.csv"

    # Check if file exists (append mode)
    if output_file.exists():
        logger.info(f"  Appending to existing file: {output_file}")

        # Read existing data
        existing_df = pd.read_csv(output_file, header=None, names=['DateTime', 'Rate'])

        # Combine with new data
        combined_df = pd.concat([existing_df, out_df], ignore_index=True)

        # Remove duplicates (keep last occurrence for same datetime)
        combined_df = combined_df.drop_duplicates(subset=['DateTime'], keep='last')

        # Sort by datetime
        combined_df = combined_df.sort_values('DateTime')

        # Write combined data
        combined_df.to_csv(output_file, index=False, header=False)

        logger.info(f"  ✅ Updated: {output_file} ({len(combined_df)} total records, {len(out_df)} new)")
    else:
        logger.info(f"  Creating new file: {output_file}")

        # Write new file
        out_df.to_csv(output_file, index=False, header=False)

        logger.info(f"  ✅ Created: {output_file} ({len(out_df)} records)")


def main_convert(input_dir=None, output_dir=None, symbol=None, market_type='cryptofuture'):
    """
    Main conversion function (can be called from other scripts)

    Args:
        input_dir: Input directory containing Gate.io CSV files
        output_dir: Output directory for LEAN data
        symbol: Specific symbol to convert (Gate.io format)
        market_type: Market type - only 'cryptofuture' is supported
    """
    # Validate market type
    if market_type != 'cryptofuture':
        logger.error(f"Funding apply data is only available for cryptofuture market, not {market_type}")
        return

    # Use defaults if not provided
    if input_dir is None:
        input_dir = 'raw_data/gate_funding_apply'
    if output_dir is None:
        output_dir = f'Data/{market_type}/gate/margin_interest'

    # Determine target symbols
    if symbol:
        target_symbols = [symbol]
    else:
        target_symbols = list(SYMBOL_MAP.keys())

    logger.info("=" * 60)
    logger.info("Gate.io Funding Apply Converter for LEAN")
    logger.info("=" * 60)
    logger.info(f"Input:  {input_dir}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Symbols: {', '.join(target_symbols)}")
    logger.info("=" * 60)

    # Scan for files
    files = scan_files(input_dir, "*.csv.gz")

    if not files:
        logger.error("No files found!")
        return

    # Group files by symbol
    files_by_symbol = defaultdict(list)

    for file in files:
        metadata = parse_filename(file.name)
        if not metadata:
            continue

        gate_symbol = metadata['symbol']

        # Check if this symbol is in our target list
        if target_symbols and gate_symbol not in target_symbols:
            continue

        files_by_symbol[gate_symbol].append(file)

    # Process each symbol
    for gate_symbol in sorted(files_by_symbol.keys()):
        # Get LEAN symbol: use SYMBOL_MAP if exists, otherwise auto-generate by removing underscore
        if gate_symbol in SYMBOL_MAP:
            lean_symbol = SYMBOL_MAP[gate_symbol]
        else:
            # Auto-generate: BTC_USDT -> BTCUSDT
            lean_symbol = gate_symbol.replace('_', '').upper()
        logger.info(f"\n{'='*60}")
        logger.info(f"Symbol: {gate_symbol} → {lean_symbol}")
        logger.info(f"{'='*60}")

        symbol_files = files_by_symbol[gate_symbol]

        for src_file in sorted(symbol_files):
            convert_funding_apply_file(src_file, output_dir, lean_symbol)

    logger.info("\n" + "=" * 60)
    logger.info("✅ Conversion Complete!")
    logger.info("=" * 60)


def main():
    """
    Main function for command-line usage
    """
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert Gate.io funding apply data to LEAN format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all target symbols
  python gateio_funding_apply_convertor.py

  # Convert specific symbol
  python gateio_funding_apply_convertor.py --symbol BTC_USDT

  # Custom input/output paths
  python gateio_funding_apply_convertor.py --input raw_data/gate_funding_apply --output Data/cryptofuture/gate/margin_interest
        """
    )

    parser.add_argument(
        '--input',
        default='raw_data/gate_funding_apply',
        help='Input directory containing Gate.io CSV files (default: raw_data/gate_funding_apply)'
    )

    parser.add_argument(
        '--output',
        default='Data/cryptofuture/gate/margin_interest',
        help='Output directory for LEAN data (default: Data/cryptofuture/gate/margin_interest)'
    )

    parser.add_argument(
        '--symbol',
        help='Specific symbol to convert (Gate.io format, e.g., BTC_USDT). If not specified, converts all mapped symbols.'
    )

    args = parser.parse_args()

    # Call main conversion function
    main_convert(
        input_dir=args.input,
        output_dir=args.output,
        symbol=args.symbol,
        market_type='cryptofuture'
    )


if __name__ == "__main__":
    main()
