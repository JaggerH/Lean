"""
Gate.io Trade Converter for LEAN
Converts Gate.io trade data to QuantConnect LEAN format
"""

import gzip
import logging
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Symbol mapping: Gate.io → Gate LEAN format
SYMBOL_MAP = {
    'AAPLX_USDT': 'AAPLXUSDT',  # Fixed: Added 'T' suffix for correct LEAN symbol
    'TSLAX_USDT': 'TSLAXUSDT',  # Fixed: Added 'T' suffix for correct LEAN symbol
    'BTC_USDT': 'BTCUSDT',      # Bitcoin
    'ETH_USDT': 'ETHUSDT',      # Ethereum
    'BNB_USDT': 'BNBUSDT',      # Binance Coin
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
    Parse Gate.io trade filename to extract symbol and month

    Filename format: AAPLX_USDT-202509.csv.gz

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


def convert_trade_file(src_file, dst_root, lean_symbol):
    """
    Convert a single trade file (containing one month of data) to LEAN format

    Args:
        src_file: Source file path (csv.gz)
        dst_root: Output root directory
        lean_symbol: LEAN symbol name
    """
    logger.info(f"Processing trade file: {src_file.name}")

    # Read Gate.io trade data (no header in CSV)
    # Spot format (5 columns): timestamp,id,price,amount,side (side: 1=sell, 2=buy)
    # Future format (4 columns): timestamp,id,price,size (size: positive=buy, negative=sell)
    try:
        with gzip.open(src_file, 'rt') as f:
            # First, read without column names to detect format
            df_raw = pd.read_csv(f, header=None)
    except Exception as e:
        logger.error(f"Failed to read {src_file.name}: {e}")
        return

    if df_raw.empty:
        logger.warning(f"No data in {src_file.name}")
        return

    # Detect format based on column count
    num_cols = len(df_raw.columns)

    if num_cols == 5:
        # Spot format: timestamp,id,price,amount,side
        df_raw.columns = ['Timestamp', 'ID', 'Price', 'Amount', 'Side']
        logger.info(f"  Detected spot format (5 columns), loaded {len(df_raw)} trades")
        df = df_raw.copy()
    elif num_cols == 4:
        # Future format: timestamp,id,price,size (signed)
        df_raw.columns = ['Timestamp', 'ID', 'Price', 'Size']
        logger.info(f"  Detected future format (4 columns), loaded {len(df_raw)} trades")

        # Convert signed size to amount + side
        df = df_raw.copy()
        df['Amount'] = df['Size'].abs()
        # Positive size = buy (side=2), negative size = sell (side=1)
        df['Side'] = (df['Size'] > 0).astype(int) + 1  # True->2, False->1
    else:
        logger.error(f"Unexpected column count: {num_cols}, expected 4 or 5")
        return

    # Convert timestamp to datetime
    df['DateTime'] = pd.to_datetime(df['Timestamp'], unit='s', utc=True)

    # Group by date
    df['Date'] = df['DateTime'].dt.date

    # Create output directory
    dst_dir = Path(dst_root) / lean_symbol.lower()
    dst_dir.mkdir(parents=True, exist_ok=True)

    # Process each day
    for date, day_df in df.groupby('Date'):
        date_str = date.strftime('%Y%m%d')
        logger.info(f"  Processing date: {date_str} ({len(day_df)} trades)")

        # Get base date (midnight of this day in UTC)
        base_date = pd.Timestamp(date, tz='UTC')

        # Calculate milliseconds since midnight
        time_delta = day_df['DateTime'] - base_date
        time_ms = (time_delta.dt.total_seconds() * 1000).astype(int)

        # Build LEAN Trade Tick format
        # Format: Time,TradeSale,TradeVolume,Exchange,TradeSaleCondition,Suspicious
        # Price in deci-cents (10000 * price for stocks, but crypto uses different scale)
        # For crypto, we use 8 decimal places, so multiply by 100000000
        out_df = pd.DataFrame({
            "col1": time_ms,
            "col2": (day_df["Price"] * 100000000).astype(int),  # price in satoshis
            "col3": (day_df["Amount"] * 100000000).astype(int),  # amount in satoshis
            "col4": "X",  # Exchange: X for crypto (Kraken convention)
            "col5": "",   # No condition
            "col6": ""    # Not suspicious
        })

        # Output filenames
        zip_filename = f"{date_str}_trade.zip"
        csv_filename = f"{date_str}_{lean_symbol.lower()}_trade_tick.csv"
        zip_path = dst_dir / zip_filename

        # Write to zip file
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            with zf.open(csv_filename, 'w') as f:
                # Write without header
                out_df.to_csv(f, index=False, header=False)

        logger.info(f"  ✅ Created: {zip_path} ({len(out_df)} trades)")


def main_convert(input_dir=None, output_dir=None, symbol=None, market_type='crypto'):
    """
    Main conversion function (can be called from other scripts)

    Args:
        input_dir: Input directory containing Gate.io CSV files
        output_dir: Output directory for LEAN data
        symbol: Specific symbol to convert (Gate.io format)
        market_type: Market type - 'crypto' (spot) or 'cryptofuture' (futures_usdt)
    """
    # Use defaults if not provided
    if input_dir is None:
        input_dir = 'raw_data/gate_trade_tick'
    if output_dir is None:
        output_dir = f'Data/{market_type}/gate/tick'

    # Determine target symbols
    if symbol:
        target_symbols = [symbol]
    else:
        target_symbols = list(SYMBOL_MAP.keys())

    logger.info("=" * 60)
    logger.info("Gate.io Trade Converter for LEAN")
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
            convert_trade_file(src_file, output_dir, lean_symbol)

    logger.info("\n" + "=" * 60)
    logger.info("✅ Conversion Complete!")
    logger.info("=" * 60)


def main():
    """
    Main function for command-line usage
    """
    import argparse

    parser = argparse.ArgumentParser(
        description='Convert Gate.io trade data to LEAN format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all target symbols
  python gateio_trade_convertor.py

  # Convert specific symbol
  python gateio_trade_convertor.py --symbol AAPLX_USDT

  # Custom input/output paths
  python gateio_trade_convertor.py --input raw_data/gate_trade_tick --output Data/crypto/kraken/tick
        """
    )

    parser.add_argument(
        '--input',
        default='raw_data/gate_trade_tick',
        help='Input directory containing Gate.io CSV files (default: raw_data/gate_trade_tick)'
    )

    parser.add_argument(
        '--output',
        default='Data/crypto/kraken/tick',
        help='Output directory for LEAN data (default: Data/crypto/kraken/tick)'
    )

    parser.add_argument(
        '--symbol',
        help='Specific symbol to convert (Gate.io format, e.g., AAPLX_USDT). If not specified, converts all mapped symbols.'
    )

    args = parser.parse_args()

    # Call main conversion function
    main_convert(
        input_dir=args.input,
        output_dir=args.output,
        symbol=args.symbol
    )


if __name__ == "__main__":
    main()
