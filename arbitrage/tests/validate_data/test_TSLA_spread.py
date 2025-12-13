"""
TSLA 价差分析 - 可视化 TSLAUSD vs TSLA 价差走势（Framework版本）

更新内容 (2025-12-13):
- 改用 BaseSpreadAnalysis 基类
- 使用 leg1/leg2 命名规则
- 配置化设计，仅需提供 get_config()
- 代码从 232 行减少到 20 行

测试场景:
- 数据源: Databento (股票) + Kraken (加密货币)
- 交易对: TSLAUSD / TSLA
- 日期范围: 2025-09-02 至 2025-09-05
- 目标: 绘制价差走势图
"""

import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from AlgorithmImports import *
from tests.validate_data.base.base_spread_analysis import BaseSpreadAnalysis


class TSLASpreadAnalysis(BaseSpreadAnalysis):
    """TSLA 价差分析 - TSLAUSD vs TSLA"""

    def get_config(self):
        return {
            # Leg 1: Crypto (TSLAUSD on Kraken)
            'leg1_symbol': 'TSLAUSD',
            'leg1_security_type': SecurityType.Crypto,
            'leg1_market': Market.Kraken,
            'leg1_resolution': Resolution.Tick,
            'leg1_data_normalization': DataNormalizationMode.Raw,

            # Leg 2: Stock (TSLA on USA market)
            'leg2_symbol': 'TSLA',
            'leg2_security_type': SecurityType.Equity,
            'leg2_market': Market.USA,
            'leg2_resolution': Resolution.Tick,
            'leg2_data_normalization': DataNormalizationMode.Raw,
            'leg2_extended_hours': False,

            # Backtest Configuration
            'start_date': (2025, 9, 2),
            'end_date': (2025, 9, 5),
            'initial_cash': 100000,
            'timezone': 'UTC',
            'brokerage': BrokerageName.Kraken,
            'account_type': AccountType.Cash,

            # Spread Analysis Configuration
            'collect_executable_spread': False,  # 仅收集理论价差
            'entry_threshold': -1.0,
            'exit_threshold': 0.0,

            # Visualization Configuration
            'output_path': Path(__file__).parent / 'TSLA_spread_analysis_framework.png',
            'plot_title': 'TSLAUSD vs TSLA Spread Analysis (Framework API)',
            'plot_figsize': (16, 8),
            'plot_dpi': 150,
        }
