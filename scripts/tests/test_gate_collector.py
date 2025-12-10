"""
Gate.io Data Collector Tests

Unit tests for the Gate.io data collector module that downloads historical market data.
Tests URL generation, file validation, and download functionality using November 2025 data.
"""

import gzip
import io
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.collectors.gate_collector import (
    GateCollector,
    DownloadConfig,
    DownloadTask,
    DownloadResult,
    DownloadStats
)


class TestDownloadConfig:
    """Tests for DownloadConfig dataclass"""

    def test_config_creation(self):
        """Test creating a valid configuration"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT', 'AAPLX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 30),
            concurrent_workers=5,
            output_dir='raw_data/gate_orderbook_tick'
        )

        assert config.market_type == 'crypto'
        assert config.data_type == 'orderbook'
        assert len(config.symbols) == 2
        assert config.concurrent_workers == 5


class TestURLGeneration:
    """Tests for URL generation logic"""

    def test_crypto_orderbook_url(self):
        """Test URL generation for crypto (spot) orderbook data"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        url = collector.build_url('TSLAX_USDT', 2025, 11, 15, 10)

        expected = 'https://download.gatedata.org/spot/orderbooks/202511/TSLAX_USDT-2025111510.csv.gz'
        assert url == expected

    def test_crypto_trade_url(self):
        """Test URL generation for crypto (spot) trade data"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='trade',
            symbols=['AAPLX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 30),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        url = collector.build_url('AAPLX_USDT', 2025, 11)

        expected = 'https://download.gatedata.org/spot/deals/202511/AAPLX_USDT-202511.csv.gz'
        assert url == expected

    def test_cryptofuture_orderbook_url(self):
        """Test URL generation for cryptofuture (perpetual) orderbook data"""
        config = DownloadConfig(
            market_type='cryptofuture',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        url = collector.build_url('TSLAX_USDT', 2025, 11, 20, 23)

        expected = 'https://download.gatedata.org/futures_usdt/orderbooks/202511/TSLAX_USDT-2025112023.csv.gz'
        assert url == expected

    def test_cryptofuture_trade_url(self):
        """Test URL generation for cryptofuture (perpetual) trade data"""
        config = DownloadConfig(
            market_type='cryptofuture',
            data_type='trade',
            symbols=['AAPLX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 30),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        url = collector.build_url('AAPLX_USDT', 2025, 11)

        # CryptoFuture uses 'trades' not 'deals'
        expected = 'https://download.gatedata.org/futures_usdt/trades/202511/AAPLX_USDT-202511.csv.gz'
        assert url == expected

    def test_url_missing_day_hour_for_orderbook(self):
        """Test that orderbook URLs require day and hour parameters"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)

        with pytest.raises(ValueError, match="day and hour are required"):
            collector.build_url('TSLAX_USDT', 2025, 11)


class TestTaskGeneration:
    """Tests for download task generation"""

    def test_orderbook_task_count_one_day(self):
        """Test that orderbook generates 24 tasks per symbol per day (hourly)"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        tasks = collector.generate_tasks()

        assert len(tasks) == 24  # 1 symbol × 1 day × 24 hours

    def test_orderbook_task_count_multiple_symbols(self):
        """Test task generation for multiple symbols"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT', 'AAPLX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        tasks = collector.generate_tasks()

        assert len(tasks) == 48  # 2 symbols × 1 day × 24 hours

    def test_trade_task_count_one_month(self):
        """Test that trade generates 1 task per symbol per month (monthly)"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='trade',
            symbols=['AAPLX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 30),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)
        tasks = collector.generate_tasks()

        assert len(tasks) == 1  # 1 symbol × 1 month

    def test_task_output_path_structure(self):
        """Test that tasks generate correct output paths"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='raw_data/gate_orderbook_tick'
        )

        collector = GateCollector(config)
        tasks = collector.generate_tasks()

        # Check first task path
        task = tasks[0]
        expected_path = Path('raw_data/gate_orderbook_tick/crypto/202511/TSLAX_USDT-2025110100.csv.gz')
        assert task.local_path == expected_path


class TestFileValidation:
    """Tests for file validation logic"""

    def test_validate_valid_gzip(self, temp_dir):
        """Test validation of valid gzip file"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)

        # Create a valid gzip file with enough data (> MIN_FILE_SIZE = 100 bytes)
        test_file = temp_dir / 'test.csv.gz'
        with gzip.open(test_file, 'wt') as f:
            # Write multiple lines to ensure compressed file is > 100 bytes
            for i in range(20):
                f.write(f'timestamp,id,price,amount,side,{i}\n')

        is_valid, error_msg = collector.validate_file(test_file)
        assert is_valid is True
        assert error_msg == ""

    def test_validate_file_too_small(self, temp_dir):
        """Test validation rejects files that are too small"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)

        # Create a file that's too small
        test_file = temp_dir / 'test.csv.gz'
        with open(test_file, 'wb') as f:
            f.write(b'x' * 50)  # Less than MIN_FILE_SIZE (100 bytes)

        is_valid, error_msg = collector.validate_file(test_file)
        assert is_valid is False
        assert "too small" in error_msg.lower()

    def test_validate_invalid_gzip(self, temp_dir):
        """Test validation rejects non-gzip files"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)

        # Create a file with invalid gzip header
        test_file = temp_dir / 'test.csv.gz'
        with open(test_file, 'wb') as f:
            f.write(b'This is not a gzip file!' * 10)  # 240 bytes, but not gzip

        is_valid, error_msg = collector.validate_file(test_file)
        assert is_valid is False
        assert "gzip" in error_msg.lower()

    def test_validate_nonexistent_file(self):
        """Test validation of non-existent file"""
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir='test'
        )

        collector = GateCollector(config)

        nonexistent_file = Path('/tmp/nonexistent_file.csv.gz')
        is_valid, error_msg = collector.validate_file(nonexistent_file)
        assert is_valid is False
        assert "not exist" in error_msg.lower()


class TestConfigValidation:
    """Tests for configuration validation"""

    def test_invalid_market_type(self):
        """Test that invalid market types are rejected"""
        with pytest.raises(ValueError, match="Invalid market_type"):
            config = DownloadConfig(
                market_type='invalid_market',
                data_type='orderbook',
                symbols=['TSLAX_USDT'],
                start_date=datetime(2025, 11, 1),
                end_date=datetime(2025, 11, 1),
                concurrent_workers=1,
                output_dir='test'
            )
            GateCollector(config)

    def test_invalid_data_type(self):
        """Test that invalid data types are rejected"""
        with pytest.raises(ValueError, match="Invalid data_type"):
            config = DownloadConfig(
                market_type='crypto',
                data_type='invalid_data',
                symbols=['TSLAX_USDT'],
                start_date=datetime(2025, 11, 1),
                end_date=datetime(2025, 11, 1),
                concurrent_workers=1,
                output_dir='test'
            )
            GateCollector(config)

    def test_empty_symbols_list(self):
        """Test that empty symbols list is rejected"""
        with pytest.raises(ValueError, match="symbols list cannot be empty"):
            config = DownloadConfig(
                market_type='crypto',
                data_type='orderbook',
                symbols=[],
                start_date=datetime(2025, 11, 1),
                end_date=datetime(2025, 11, 1),
                concurrent_workers=1,
                output_dir='test'
            )
            GateCollector(config)

    def test_invalid_date_range(self):
        """Test that invalid date ranges are rejected"""
        with pytest.raises(ValueError, match="start_date must be before"):
            config = DownloadConfig(
                market_type='crypto',
                data_type='orderbook',
                symbols=['TSLAX_USDT'],
                start_date=datetime(2025, 11, 30),
                end_date=datetime(2025, 11, 1),  # End before start
                concurrent_workers=1,
                output_dir='test'
            )
            GateCollector(config)


class TestDownloadIntegration:
    """Integration tests for actual downloads (requires network)"""

    @pytest.mark.skip(reason="Network test - run manually with: pytest -m network")
    def test_download_single_file_crypto_orderbook(self, temp_dir):
        """
        Integration test: Download one hour of real crypto orderbook data from November 2025

        To run this test:
            pytest scripts/tests/test_gate_collector.py::TestDownloadIntegration::test_download_single_file_crypto_orderbook -v -s
        """
        config = DownloadConfig(
            market_type='crypto',
            data_type='orderbook',
            symbols=['TSLAX_USDT'],
            start_date=datetime(2025, 11, 1),
            end_date=datetime(2025, 11, 1),
            concurrent_workers=1,
            output_dir=str(temp_dir)
        )

        collector = GateCollector(config)
        stats = collector.execute_downloads()

        # Verify download succeeded or file doesn't exist (404)
        assert stats.failed == 0, f"Download failed: {stats.failed} failures"
        assert (stats.successful > 0 or stats.skipped > 0), "No files downloaded or skipped"

        # If successful, verify file exists
        if stats.successful > 0:
            output_path = temp_dir / 'crypto' / '202511'
            files = list(output_path.glob('TSLAX_USDT-*.csv.gz'))
            assert len(files) > 0, "No files created despite successful download"

            # Verify file is valid gzip
            test_file = files[0]
            is_valid, error_msg = collector.validate_file(test_file)
            assert is_valid, f"Downloaded file failed validation: {error_msg}"


# Pytest fixtures
@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for test files"""
    return tmp_path


if __name__ == '__main__':
    # Allow running tests directly
    pytest.main([__file__, '-v'])
