"""
Base Spread Analysis Algorithm

Provides reusable logic for collecting and visualizing spread data between two legs.
"""

from AlgorithmImports import *
from QuantConnect.Algorithm import AQCAlgorithm
from pathlib import Path
from abc import abstractmethod


class BaseSpreadAnalysis(AQCAlgorithm):
    """价差分析基类 - 基于 leg1/leg2 通用设计

    子类只需实现 get_config() 方法提供配置即可。
    """

    def __init__(self):
        super().__init__()
        self.config = None
        self.leg1 = None
        self.leg2 = None
        self.pair = None
        self.collector = None
        self.last_log_time = None

    @abstractmethod
    def get_config(self) -> dict:
        """子类必须实现：返回交易对配置

        Returns:
            {
                # === Leg 1 配置 ===
                'leg1_symbol': str,
                'leg1_security_type': SecurityType,
                'leg1_market': Market,
                'leg1_resolution': Resolution,
                'leg1_data_normalization': DataNormalizationMode,  # 可选
                'leg1_extended_hours': bool,  # 可选，仅股票

                # === Leg 2 配置 ===
                'leg2_symbol': str,
                'leg2_security_type': SecurityType,
                'leg2_market': Market,
                'leg2_resolution': Resolution,
                'leg2_data_normalization': DataNormalizationMode,  # 可选
                'leg2_extended_hours': bool,  # 可选，仅股票

                # === 回测配置 ===
                'start_date': tuple,  # (year, month, day)
                'end_date': tuple,
                'initial_cash': int,  # 可选，默认 100000
                'timezone': str,  # 可选，默认 'UTC'
                'brokerage': BrokerageName,  # 可选，默认 Kraken
                'account_type': AccountType,  # 可选，默认 Cash

                # === 价差分析配置 ===
                'collect_executable_spread': bool,  # 可选，默认 True
                'entry_threshold': float,  # 开仓阈值（百分比）
                'exit_threshold': float,  # 平仓阈值（百分比）
                'output_path': Path,  # 图表输出路径

                # === 可视化配置 ===
                'plot_title': str,  # 可选
                'plot_figsize': tuple,  # 可选，默认 (16, 9)
                'plot_dpi': int,  # 可选，默认 150
            }
        """
        raise NotImplementedError

    def Initialize(self):
        """通用初始化逻辑"""
        # 获取配置
        self.config = self.get_config()
        cfg = self.config

        # 设置回测参数
        self.SetStartDate(*cfg['start_date'])
        self.SetEndDate(*cfg['end_date'])
        self.SetCash(cfg.get('initial_cash', 100000))
        self.SetTimeZone(cfg.get('timezone', 'UTC'))

        # 设置经纪商
        self.SetBrokerageModel(
            cfg.get('brokerage', BrokerageName.Kraken),
            cfg.get('account_type', AccountType.Cash)
        )

        # 禁用基准
        self.SetBenchmark(lambda x: 0)

        # === 添加 Leg 1 ===
        self.leg1 = self._add_security(
            cfg['leg1_symbol'],
            cfg['leg1_security_type'],
            cfg['leg1_resolution'],
            cfg['leg1_market'],
            cfg.get('leg1_data_normalization', DataNormalizationMode.Raw),
            cfg.get('leg1_extended_hours', False)
        )

        # === 添加 Leg 2 ===
        self.leg2 = self._add_security(
            cfg['leg2_symbol'],
            cfg['leg2_security_type'],
            cfg['leg2_resolution'],
            cfg['leg2_market'],
            cfg.get('leg2_data_normalization', DataNormalizationMode.Raw),
            cfg.get('leg2_extended_hours', False)
        )

        # === 创建交易对 ===
        self.pair = self.TradingPairs.AddPair(
            self.leg1.Symbol,
            self.leg2.Symbol,
            "leg1_leg2"
        )

        # === 创建数据收集器 ===
        from .spread_collector import SpreadCollector
        self.collector = SpreadCollector(
            self,
            cfg.get('collect_executable_spread', True)
        )

        self.Debug(f"✅ Initialized: {cfg['leg1_symbol']} vs {cfg['leg2_symbol']}")

    def _add_security(self, symbol, security_type, resolution, market,
                     data_normalization, extended_hours):
        """添加证券的通用方法

        Args:
            symbol: 证券代码
            security_type: 证券类型
            resolution: 分辨率
            market: 市场
            data_normalization: 数据规范化模式
            extended_hours: 是否包含盘前盘后（仅股票）

        Returns:
            Security object
        """
        if security_type == SecurityType.Equity:
            security = self.AddEquity(symbol, resolution, market, extended_hours)
        elif security_type == SecurityType.Crypto:
            security = self.AddCrypto(symbol, resolution, market)
        elif security_type == SecurityType.CryptoFuture:
            security = self.AddCryptoFuture(symbol, resolution, market)
        elif security_type == SecurityType.Future:
            security = self.AddFuture(symbol, resolution, market)
        else:
            raise ValueError(f"Unsupported security type: {security_type}")

        security.DataNormalizationMode = data_normalization
        return security

    def OnData(self, data: Slice):
        """数据处理 - 调用基类更新，然后收集数据"""
        # 调用 AQCAlgorithm 的 OnData 来更新 TradingPairs
        super().OnData(data)

        # 收集价差数据
        self.collector.collect_spread_data(self.pair)

        # 每小时日志
        self._log_hourly_status()

    def _log_hourly_status(self):
        """每小时输出一次状态"""
        if len(self.collector.theoretical_spread_data) == 0:
            return

        if self.last_log_time is None or \
           (self.Time - self.last_log_time).total_seconds() >= 3600:
            _, theoretical_spread = self.collector.theoretical_spread_data[-1]
            executable_count = len(self.collector.executable_spread_data)

            self.Debug(
                f"📊 {self.Time} | "
                f"Theoretical Spread: {theoretical_spread*100:.2f}% | "
                f"Executable Opportunities: {executable_count:,}"
            )
            self.last_log_time = self.Time

    def OnEndOfAlgorithm(self):
        """算法结束 - 统计 + 绘图"""
        self._print_statistics()
        self._plot_spread_chart()

    def _print_statistics(self):
        """输出统计信息"""
        self.Debug("\n" + "="*60)
        self.Debug(f"📊 Spread Analysis: {self.config['leg1_symbol']} vs {self.config['leg2_symbol']}")
        self.Debug("="*60)

        # 理论价差统计
        if len(self.collector.theoretical_spread_data) > 0:
            spreads_pct = [s[1] * 100 for s in self.collector.theoretical_spread_data]
            self.Debug(f"\nTheoretical Spread Statistics:")
            self.Debug(f"  Data Points: {len(spreads_pct):,}")
            self.Debug(f"  Min: {min(spreads_pct):.2f}%")
            self.Debug(f"  Max: {max(spreads_pct):.2f}%")
            self.Debug(f"  Avg: {sum(spreads_pct)/len(spreads_pct):.2f}%")

        # 可执行价差统计
        if len(self.collector.executable_spread_data) > 0:
            self.Debug(f"\nExecutable Opportunities: {len(self.collector.executable_spread_data):,}")

            from QuantConnect.TradingPairs import MarketState
            crossed = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                         if state == MarketState.Crossed)
            limit = sum(1 for _, _, state, _ in self.collector.executable_spread_data
                       if state == MarketState.LimitOpportunity)

            self.Debug(f"  CROSSED: {crossed:,}")
            self.Debug(f"  LIMIT_OPPORTUNITY: {limit:,}")

        self.Debug("="*60)

    def _plot_spread_chart(self):
        """绘制价差图表"""
        if len(self.collector.theoretical_spread_data) == 0:
            self.Debug("⚠️ No data to plot")
            return

        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates

            cfg = self.config

            # 准备数据
            timestamps = [s[0] for s in self.collector.theoretical_spread_data]
            spreads_pct = [s[1] * 100 for s in self.collector.theoretical_spread_data]

            # 创建图表
            fig, ax = plt.subplots(
                figsize=cfg.get('plot_figsize', (16, 9))
            )

            # 绘制理论价差（连续曲线）
            ax.plot(timestamps, spreads_pct,
                   linewidth=1.5, color='blue', alpha=0.7,
                   label=f'Theoretical Spread ({len(spreads_pct):,} points)')

            # 绘制可执行价差（散点标注）
            if len(self.collector.executable_spread_data) > 0:
                from QuantConnect.TradingPairs import MarketState
                crossed_ts = []
                crossed_spreads = []
                for ts, spread, state, _ in self.collector.executable_spread_data:
                    if state == MarketState.Crossed:
                        crossed_ts.append(ts)
                        crossed_spreads.append(spread * 100)

                if len(crossed_ts) > 0:
                    ax.scatter(crossed_ts, crossed_spreads,
                              s=30, color='red', alpha=0.8, marker='o',
                              label=f'CROSSED Market ({len(crossed_spreads):,} points)')

            # 添加阈值线
            ax.axhline(y=0, color='black', linestyle='-', linewidth=1.5, alpha=0.5)
            ax.axhline(y=cfg.get('entry_threshold', -1.0), color='green',
                      linestyle='--', linewidth=1.5, alpha=0.7,
                      label=f"Entry: {cfg.get('entry_threshold', -1.0)}%")
            ax.axhline(y=cfg.get('exit_threshold', 2.0), color='blue',
                      linestyle='--', linewidth=1.5, alpha=0.7,
                      label=f"Exit: {cfg.get('exit_threshold', 2.0)}%")

            # 格式化
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=12))
            plt.xticks(rotation=45, ha='right')

            ax.set_xlabel('Time', fontsize=12)
            ax.set_ylabel('Spread %', fontsize=12)
            ax.set_title(
                cfg.get('plot_title', f"{cfg['leg1_symbol']} vs {cfg['leg2_symbol']} Spread"),
                fontsize=14, fontweight='bold'
            )
            ax.grid(True, alpha=0.3)
            ax.legend(loc='best')

            plt.tight_layout()

            # 保存
            output_path = cfg['output_path']
            plt.savefig(str(output_path), dpi=cfg.get('plot_dpi', 150), bbox_inches='tight')
            plt.close()

            self.Debug(f"✅ Chart saved: {output_path}")

        except Exception as e:
            self.Error(f"❌ Plot failed: {str(e)}")
            import traceback
            self.Debug(traceback.format_exc())
