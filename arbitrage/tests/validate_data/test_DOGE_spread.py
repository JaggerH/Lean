"""
DOGE 期现价差分析 - Gate DOGEUSDT 现货 vs 期货

期现套利（Spot-Futures Arbitrage）分析：
- Leg1: Gate DOGEUSDT 现货
- Leg2: Gate DOGEUSDT 永续合约
- 日期范围: 2025-10-01 至 2025-10-31
- 目标: 分析现货和期货之间的价差，寻找期现套利机会
"""

import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from tests.validate_data.base.base_spread_analysis import BaseSpreadAnalysis


class DOGESpreadAnalysis(BaseSpreadAnalysis):
    """DOGE 期现价差分析 - 现货 vs 永续合约"""

    def get_config(self):
        return {
            # Leg 1: Spot (现货)
            'leg1_symbol': 'DOGEUSDT',
            'leg1_security_type': SecurityType.Crypto,
            'leg1_market': Market.Gate,
            'leg1_resolution': Resolution.Orderbook,
            'leg1_data_normalization': DataNormalizationMode.Raw,

            # Leg 2: Perpetual Futures (永续合约)
            'leg2_symbol': 'DOGEUSDT',
            'leg2_security_type': SecurityType.CryptoFuture,
            'leg2_market': Market.Gate,
            'leg2_resolution': Resolution.Orderbook,
            'leg2_data_normalization': DataNormalizationMode.Raw,

            # Backtest Configuration
            'start_date': (2025, 10, 1),
            'end_date': (2025, 10, 10),
            'initial_cash': 100000,
            'timezone': 'UTC',
            # Note: brokerage 设置留空，使用默认值
            # 'brokerage': BrokerageName.GateFutures,
            # 'account_type': AccountType.Cash,

            # Spread Analysis Configuration
            'collect_executable_spread': True,  # 收集可执行价差
            'entry_threshold': -0.5,  # 开仓阈值 -0.5% (期货升水)
            'exit_threshold': 0.5,    # 平仓阈值 +0.5% (期货贴水)

            # Visualization Configuration
            'output_path': Path(__file__).parent / 'DOGE_spot_futures_spread.png',
            'plot_title': 'DOGE Spot-Futures Spread Analysis (Gate)',
            'plot_figsize': (16, 9),
            'plot_dpi': 150,
        }
