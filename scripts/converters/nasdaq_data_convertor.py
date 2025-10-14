"""
Nasdaq Data Converter for LEAN
Converts Nasdaq ITCH format data (Trade and Quote) to QuantConnect LEAN format
"""

import argparse
import logging
import os
import re
import zipfile
from pathlib import Path

import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def scan_files(data_dir, pattern="*.csv.zst"):
    """
    扫描指定目录下的文件

    Args:
        data_dir: 数据目录路径
        pattern: 文件匹配模式

    Returns:
        list: 文件Path对象列表
    """
    data_path = Path(data_dir)

    if not data_path.exists():
        logger.warning(f"Directory not found: {data_path}")
        return []

    files = list(data_path.glob(pattern))
    logger.info(f"Found {len(files)} files in {data_path}")

    return files


def parse_filename(filename, data_type):
    """
    解析文件名提取symbol和日期

    Args:
        filename: 文件名
        data_type: 'trade' or 'quote'

    Returns:
        dict: {'date': str, 'symbol': str} 或 None
    """
    if data_type == 'trade':
        # xnas-itch-20250827.trades.csv.zst (multi-symbol file)
        pattern = r"xnas-itch-(\d{8})\.trades\.csv\.zst$"
        match = re.match(pattern, filename)
        if match:
            return {'date': match.group(1), 'symbol': 'multi'}

    elif data_type == 'quote':
        # xnas-itch-20250827.mbp-1.AAPL.csv.zst (single-symbol file)
        pattern = r"xnas-itch-(\d{8})\.mbp-1\.(.+)\.csv\.zst$"
        match = re.match(pattern, filename)
        if match:
            return {'date': match.group(1), 'symbol': match.group(2)}

    logger.warning(f"Cannot parse filename: {filename}")
    return None


def convert_trade_tick(src_file, dst_root, target_symbol=None):
    """
    转换Trade Tick数据到LEAN格式

    Args:
        src_file: 源文件路径
        dst_root: 输出根目录
        target_symbol: 目标symbol (None表示处理所有)
    """
    logger.info(f"Processing Trade file: {src_file.name}")

    # 读取数据
    df = pd.read_csv(src_file, compression="zstd")

    # 筛选symbol
    if target_symbol and target_symbol.upper() != 'ALL':
        df = df[df['symbol'] == target_symbol.upper()]
        if df.empty:
            logger.warning(f"No data found for symbol {target_symbol}")
            return

    # 按symbol分组处理
    for symbol, g in df.groupby("symbol"):
        logger.info(f"  Processing symbol: {symbol}")

        # 目标目录
        dst_dir = Path(dst_root) / symbol.lower()
        dst_dir.mkdir(parents=True, exist_ok=True)

        # 日期
        date_str = pd.to_datetime(g["ts_event"].iloc[0]).strftime("%Y%m%d")

        # LEAN文件名
        zip_filename = f"{date_str}_trade.zip"
        csv_filename = f"{date_str}_{symbol.lower()}_Trade_Tick.csv"
        zip_path = dst_dir / zip_filename

        # 时间转换 - 保持UTC时区并计算从午夜开始的毫秒数
        timestamps = pd.to_datetime(g["ts_event"])
        if timestamps.dt.tz is None:
            timestamps = timestamps.dt.tz_localize('UTC')
        else:
            timestamps = timestamps.dt.tz_convert('UTC')

        midnight = timestamps.dt.normalize()
        time_ms = ((timestamps - midnight).dt.total_seconds() * 1000).astype(int)

        # 构建LEAN Trade Tick格式
        # Format: Time,TradeSale,Trade Volume,Exchange,Trade Sale Condition,Suspicious
        out_df = pd.DataFrame({
            "col1": time_ms,
            "col2": (g["price"] * 10000).astype(int),  # price in deci-cents
            "col3": g["size"].astype(int),
            "col4": "T",  # NASDAQ
            "col5": "0",  # No condition
            "col6": "0"   # Not suspicious
        })

        # 写入zip
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            with zf.open(csv_filename, "w") as f:
                out_df.to_csv(f, index=False, header=False)

        logger.info(f"  ✅ Created: {zip_path} ({len(out_df)} ticks)")


def convert_quote_tick(src_file, dst_root, target_symbol=None):
    """
    转换Quote Tick数据到LEAN格式

    Args:
        src_file: 源文件路径
        dst_root: 输出根目录
        target_symbol: 目标symbol (None表示处理所有)
    """
    logger.info(f"Processing Quote file: {src_file.name}")

    # 解析文件名获取symbol
    metadata = parse_filename(src_file.name, 'quote')
    if not metadata:
        logger.error(f"Cannot parse quote filename: {src_file.name}")
        return

    symbol = metadata['symbol']
    date_str = metadata['date']

    # 检查是否是目标symbol
    if target_symbol and target_symbol.upper() != 'ALL':
        if symbol.upper() != target_symbol.upper():
            logger.info(f"  Skipping {symbol} (not target symbol)")
            return

    logger.info(f"  Processing symbol: {symbol}")

    # 读取数据
    df = pd.read_csv(src_file, compression="zstd")

    # 检查必需列
    required_cols = ['ts_event', 'bid_px_00', 'ask_px_00', 'bid_sz_00', 'ask_sz_00']
    if not all(col in df.columns for col in required_cols):
        logger.error(f"Missing required columns in {src_file.name}")
        return

    # 数据清洗 - 只保留有效的报价
    df = df[
        (df['bid_px_00'] > 0) &
        (df['ask_px_00'] > 0) &
        (df['bid_sz_00'] > 0) &
        (df['ask_sz_00'] > 0) &
        (df['bid_px_00'] < df['ask_px_00'])
    ].copy()

    if df.empty:
        logger.warning(f"No valid quotes found in {src_file.name}")
        return

    # 去重 - 只保留报价变化
    df['quote_key'] = (
        df['bid_px_00'].astype(str) + '_' +
        df['bid_sz_00'].astype(str) + '_' +
        df['ask_px_00'].astype(str) + '_' +
        df['ask_sz_00'].astype(str)
    )
    df = df.drop_duplicates(subset=['quote_key'], keep='first')
    df = df.drop(columns=['quote_key'])

    # 时间转换
    timestamps = pd.to_datetime(df["ts_event"])
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize('UTC')
    else:
        timestamps = timestamps.dt.tz_convert('UTC')

    midnight = timestamps.dt.normalize()
    time_ms = ((timestamps - midnight).dt.total_seconds() * 1000).astype(int)

    # 构建LEAN Quote Tick格式
    # Format: Time,Bid Sale,Bid Size,Ask Sale,Ask Size,Exchange,Quote Sale Condition,Suspicious
    out_df = pd.DataFrame({
        "col1": time_ms,
        "col2": (df["bid_px_00"] * 10000).astype(int),  # bid price in deci-cents
        "col3": df["bid_sz_00"].astype(int),
        "col4": (df["ask_px_00"] * 10000).astype(int),  # ask price in deci-cents
        "col5": df["ask_sz_00"].astype(int),
        "col6": "T",  # NASDAQ
        "col7": "0",  # No condition
        "col8": "0"   # Not suspicious
    })

    # 目标目录
    dst_dir = Path(dst_root) / symbol.lower()
    dst_dir.mkdir(parents=True, exist_ok=True)

    # LEAN文件名
    zip_filename = f"{date_str}_quote.zip"
    csv_filename = f"{date_str}_{symbol.lower()}_Quote_Tick.csv"
    zip_path = dst_dir / zip_filename

    # 写入zip
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with zf.open(csv_filename, "w") as f:
            out_df.to_csv(f, index=False, header=False)

    logger.info(f"  ✅ Created: {zip_path} ({len(out_df)} ticks)")


def main_convert(trade_dir=None, quote_dir=None, output_dir=None, data_type='all', symbol='all'):
    """
    Main conversion function (can be called from other scripts)

    Args:
        trade_dir: Trade data directory
        quote_dir: Quote data directory
        output_dir: Output directory for LEAN data
        data_type: Type of data to convert ('trade', 'quote', or 'all')
        symbol: Symbol to convert (or 'all')
    """
    # Use defaults if not provided
    if trade_dir is None:
        trade_dir = "raw_data/us_trade_tick"
    if quote_dir is None:
        quote_dir = "raw_data/us_mbp_tick"
    if output_dir is None:
        output_dir = "Data/equity/usa/tick"

    logger.info("=" * 60)
    logger.info("Nasdaq Data Converter for LEAN")
    logger.info("=" * 60)
    logger.info(f"Type: {data_type}")
    logger.info(f"Symbol: {symbol}")
    logger.info("=" * 60)

    # 转换Trade数据
    if data_type in ['trade', 'all']:
        logger.info("\n📊 Converting Trade Tick Data...")
        trade_files = scan_files(trade_dir, "*.csv.zst")

        for file in trade_files:
            convert_trade_tick(
                file,
                output_dir,
                target_symbol=symbol
            )

    # 转换Quote数据
    if data_type in ['quote', 'all']:
        logger.info("\n📈 Converting Quote Tick Data...")
        quote_files = scan_files(quote_dir, "*.csv.zst")

        for file in quote_files:
            convert_quote_tick(
                file,
                output_dir,
                target_symbol=symbol
            )

    logger.info("\n" + "=" * 60)
    logger.info("✅ Conversion Complete!")
    logger.info("=" * 60)


def main():
    """
    主函数 (命令行入口)
    """
    parser = argparse.ArgumentParser(
        description='Convert Nasdaq ITCH data to LEAN format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all trade data for all symbols
  python nasdaq_data_convertor.py --type trade

  # Convert all quote data for AAPL only
  python nasdaq_data_convertor.py --type quote --symbol AAPL

  # Convert both trade and quote for TSLA
  python nasdaq_data_convertor.py --type all --symbol TSLA

  # Convert everything (default)
  python nasdaq_data_convertor.py
        """
    )

    parser.add_argument(
        '--type',
        choices=['trade', 'quote', 'all'],
        default='all',
        help='Data type to convert (default: all)'
    )

    parser.add_argument(
        '--symbol',
        default='all',
        help='Symbol to convert (e.g., AAPL, TSLA, or all for all symbols, default: all)'
    )

    args = parser.parse_args()

    # Call main conversion function
    main_convert(
        data_type=args.type,
        symbol=args.symbol
    )


if __name__ == "__main__":
    main()
