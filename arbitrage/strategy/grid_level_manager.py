"""
Grid Level Manager - 网格线配置和验证管理器

功能:
1. 管理网格线定义（进场线/出场线）
2. 验证网格线配置的合理性（预期盈利 > 2 * 手续费）
3. 提供网格线查询接口（根据价差查找触发的网格线）
"""
from AlgorithmImports import QCAlgorithm, Symbol
from typing import Dict, List, Tuple, Optional
from .grid_models import GridLevel


class GridLevelManager:
    """
    网格线配置和验证管理器

    职责:
    - 存储和管理每个交易对的网格线配置
    - 验证网格线的合理性（盈利 vs 手续费）
    - 根据当前价差查找被触发的网格线
    """

    def __init__(self, algorithm: QCAlgorithm):
        """
        初始化 GridLevelManager

        Args:
            algorithm: QCAlgorithm 实例
        """
        self.algorithm = algorithm

        # 网格线定义
        # {pair_symbol: List[GridLevel]}
        self.grid_levels: Dict[Tuple[Symbol, Symbol], List[GridLevel]] = {}

        # 网格线配对关系缓存（entry -> exit）
        # {pair_symbol: {entry_level_id: exit_level_id}}
        self.entry_exit_pairs: Dict[Tuple[Symbol, Symbol], Dict[str, str]] = {}

    def add_grid_levels(self, pair_symbol: Tuple[Symbol, Symbol], levels: List[GridLevel]):
        """
        添加交易对的网格线配置

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            levels: GridLevel 列表

        Example:
            >>> levels = [
            ...     GridLevel("entry_1", "ENTRY", -0.01, "exit_1", 0.25),
            ...     GridLevel("exit_1", "EXIT", 0.02, None, 0.25)
            ... ]
            >>> manager.add_grid_levels((crypto_sym, stock_sym), levels)
        """
        if pair_symbol not in self.grid_levels:
            self.grid_levels[pair_symbol] = []

        self.grid_levels[pair_symbol].extend(levels)

        # 建立进场线和出场线的配对关系
        self._build_entry_exit_pairs(pair_symbol)

        self.algorithm.debug(
            f"✅ Added {len(levels)} grid levels for {pair_symbol[0].value} <-> {pair_symbol[1].value}"
        )

    def _build_entry_exit_pairs(self, pair_symbol: Tuple[Symbol, Symbol]):
        """
        建立进场线和出场线的配对关系

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
        """
        if pair_symbol not in self.entry_exit_pairs:
            self.entry_exit_pairs[pair_symbol] = {}

        levels = self.grid_levels.get(pair_symbol, [])

        for level in levels:
            if level.type == "ENTRY" and level.paired_exit_level_id:
                self.entry_exit_pairs[pair_symbol][level.level_id] = level.paired_exit_level_id

    def validate_grid_levels(self, pair_symbol: Tuple[Symbol, Symbol],
                            crypto_fee_pct: float = 0.0026,
                            stock_fee_pct: float = 0.0005) -> bool:
        """
        验证网格线配置的合理性

        验证规则：
        1. 每个进场线必须有配对的出场线
        2. 预期盈利 > 2 * 预估手续费（确保套利可行）

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            crypto_fee_pct: Crypto 手续费百分比（默认 0.26%，Kraken Maker Fee）
            stock_fee_pct: Stock 手续费百分比（默认 0.05%，IBKR 估算）

        Returns:
            True if valid, False otherwise

        Raises:
            ValueError: 如果配置不合理
        """
        levels = self.grid_levels.get(pair_symbol, [])

        if not levels:
            raise ValueError(f"No grid levels defined for {pair_symbol}")

        # 分类进场线和出场线
        entry_levels = [l for l in levels if l.type == "ENTRY"]
        exit_levels = [l for l in levels if l.type == "EXIT"]

        if not entry_levels:
            raise ValueError(f"No entry levels defined for {pair_symbol}")

        if not exit_levels:
            raise ValueError(f"No exit levels defined for {pair_symbol}")

        # 验证每个进场线
        all_valid = True
        errors = []

        for entry_level in entry_levels:
            # 1. 检查是否有配对的出场线
            if not entry_level.paired_exit_level_id:
                errors.append(f"Entry level '{entry_level.level_id}' has no paired exit level")
                entry_level.is_valid = False
                all_valid = False
                continue

            # 2. 查找配对的出场线
            exit_level = next(
                (l for l in exit_levels if l.level_id == entry_level.paired_exit_level_id),
                None
            )

            if not exit_level:
                errors.append(
                    f"Entry level '{entry_level.level_id}' references non-existent exit level "
                    f"'{entry_level.paired_exit_level_id}'"
                )
                entry_level.is_valid = False
                all_valid = False
                continue

            # 3. 计算预期盈利和手续费
            expected_profit_pct = self.calculate_expected_profit(entry_level, exit_level)
            estimated_fee_pct = self.estimate_total_fees(crypto_fee_pct, stock_fee_pct)

            # 更新网格线的验证信息
            entry_level.expected_profit_pct = expected_profit_pct
            entry_level.estimated_fee_pct = estimated_fee_pct

            # 4. 验证盈利 > 2 * 手续费
            if expected_profit_pct <= 2 * estimated_fee_pct:
                error_msg = (
                    f"Grid level pair '{entry_level.level_id}' <-> '{exit_level.level_id}' is unprofitable: "
                    f"Expected profit {expected_profit_pct*100:.3f}% <= 2 * Fees {2*estimated_fee_pct*100:.3f}%"
                )
                errors.append(error_msg)
                entry_level.is_valid = False
                entry_level.validation_error = error_msg
                all_valid = False
            else:
                entry_level.is_valid = True
                entry_level.validation_error = None
                self.algorithm.debug(
                    f"✅ Grid level pair '{entry_level.level_id}' <-> '{exit_level.level_id}': "
                    f"Profit {expected_profit_pct*100:.3f}% > Fees {2*estimated_fee_pct*100:.3f}%"
                )

        # 如果有错误，抛出异常
        if not all_valid:
            error_summary = "\n".join(errors)
            raise ValueError(f"Grid level validation failed:\n{error_summary}")

        return True

    def calculate_expected_profit(self, entry_level: GridLevel, exit_level: GridLevel) -> float:
        """
        计算网格线对的预期盈利百分比

        盈利 = |exit_spread - entry_spread|

        Args:
            entry_level: 进场线配置
            exit_level: 出场线配置

        Returns:
            预期盈利百分比

        Example:
            >>> # Entry at -1%, Exit at +2%
            >>> profit = calculate_expected_profit(entry_at_neg1, exit_at_pos2)
            >>> # Returns: 0.03 (3%)
        """
        return abs(exit_level.spread_pct - entry_level.spread_pct)

    def estimate_total_fees(self, crypto_fee_pct: float, stock_fee_pct: float) -> float:
        """
        估算一次完整交易（开仓+平仓）的总手续费百分比

        总手续费 = (crypto_fee + stock_fee) * 2（开仓一次，平仓一次）

        Args:
            crypto_fee_pct: Crypto 手续费百分比
            stock_fee_pct: Stock 手续费百分比

        Returns:
            总手续费百分比

        Example:
            >>> # Kraken 0.26% + IBKR 0.05% = 0.31%
            >>> # 开仓 + 平仓 = 0.31% * 2 = 0.62%
            >>> fees = estimate_total_fees(0.0026, 0.0005)
            >>> # Returns: 0.0062 (0.62%)
        """
        return (crypto_fee_pct + stock_fee_pct) * 2

    def get_active_level(self, pair_symbol: Tuple[Symbol, Symbol],
                         spread_pct: float) -> Optional[GridLevel]:
        """
        获取当前活跃的网格线（ENTRY 或 EXIT）

        核心概念：对于给定的价差，只有一个活跃的网格线
        - 价差在某个区间 → 触发对应的 ENTRY 线
        - 价差在另一个区间 → 触发对应的 EXIT 线

        触发规则（根据方向）:
        - LONG_SPREAD:
          * ENTRY: spread_pct <= level.spread_pct (价差为负时触发进场)
          * EXIT: spread_pct >= level.spread_pct (价差回正时触发出场)
        - SHORT_SPREAD:
          * ENTRY: spread_pct >= level.spread_pct (价差为正时触发进场)
          * EXIT: spread_pct <= level.spread_pct (价差回负时触发出场)

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比

        Returns:
            被触发的 GridLevel (ENTRY or EXIT)，如果没有则返回 None

        Note:
            如果多个网格线同时触发，返回最接近当前价差的那个
        """
        levels = self.grid_levels.get(pair_symbol, [])
        valid_levels = [l for l in levels if l.is_valid]

        triggered_levels = []

        for level in valid_levels:
            is_triggered = False

            # 根据方向和类型判断是否触发
            if level.direction == "LONG_SPREAD":
                if level.type == "ENTRY":
                    # 做多价差：价差为负时触发进场（spread_pct <= trigger）
                    is_triggered = spread_pct <= level.spread_pct
                elif level.type == "EXIT":
                    # 做多价差：价差回正时触发出场（spread_pct >= trigger）
                    is_triggered = spread_pct >= level.spread_pct

            elif level.direction == "SHORT_SPREAD":
                if level.type == "ENTRY":
                    # 做空价差：价差为正时触发进场（spread_pct >= trigger）
                    is_triggered = spread_pct >= level.spread_pct
                elif level.type == "EXIT":
                    # 做空价差：价差回负时触发出场（spread_pct <= trigger）
                    is_triggered = spread_pct <= level.spread_pct

            if is_triggered:
                triggered_levels.append(level)

        # 如果有多个触发，返回最接近当前价差的（最激进的）
        if triggered_levels:
            # 按距离排序（距离 = |spread_pct - level.spread_pct|）
            triggered_levels.sort(key=lambda l: abs(spread_pct - l.spread_pct))
            return triggered_levels[0]

        return None

    def get_triggered_entry_level(self, pair_symbol: Tuple[Symbol, Symbol],
                                   spread_pct: float) -> Optional[GridLevel]:
        """
        获取被触发的进场线（如果有）

        DEPRECATED: 使用 get_active_level() 替代
        保留此方法用于向后兼容

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比

        Returns:
            被触发的 GridLevel，如果没有则返回 None
        """
        level = self.get_active_level(pair_symbol, spread_pct)
        if level and level.type == "ENTRY":
            return level
        return None

    def get_triggered_exit_levels(self, pair_symbol: Tuple[Symbol, Symbol],
                                  spread_pct: float,
                                  active_grid_ids: List[str]) -> List[GridLevel]:
        """
        获取被触发的出场线列表

        DEPRECATED: 使用 get_active_level() 替代
        保留此方法用于向后兼容

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            spread_pct: 当前价差百分比
            active_grid_ids: 活跃的网格线ID列表

        Returns:
            被触发的 GridLevel 列表
        """
        level = self.get_active_level(pair_symbol, spread_pct)
        if level and level.type == "EXIT":
            return [level]
        return []

    def get_level_by_id(self, pair_symbol: Tuple[Symbol, Symbol], level_id: str) -> Optional[GridLevel]:
        """
        根据 level_id 查找网格线配置

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)
            level_id: 网格线ID

        Returns:
            GridLevel 或 None
        """
        levels = self.grid_levels.get(pair_symbol, [])
        return next((l for l in levels if l.level_id == level_id), None)

    def get_all_levels(self, pair_symbol: Tuple[Symbol, Symbol]) -> List[GridLevel]:
        """
        获取交易对的所有网格线

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            GridLevel 列表
        """
        return self.grid_levels.get(pair_symbol, [])

    def get_summary(self, pair_symbol: Tuple[Symbol, Symbol]) -> str:
        """
        生成网格线配置摘要

        Args:
            pair_symbol: (crypto_symbol, stock_symbol)

        Returns:
            格式化的摘要字符串
        """
        levels = self.grid_levels.get(pair_symbol, [])

        if not levels:
            return f"No grid levels configured for {pair_symbol[0].value} <-> {pair_symbol[1].value}"

        entry_levels = [l for l in levels if l.type == "ENTRY"]
        exit_levels = [l for l in levels if l.type == "EXIT"]

        summary_lines = [
            f"Grid Levels for {pair_symbol[0].value} <-> {pair_symbol[1].value}:",
            f"  Entry Levels: {len(entry_levels)}",
            f"  Exit Levels: {len(exit_levels)}",
            "",
            "Entry -> Exit Pairs:"
        ]

        for entry in entry_levels:
            exit_id = entry.paired_exit_level_id
            exit_level = next((l for l in exit_levels if l.level_id == exit_id), None)

            if exit_level:
                summary_lines.append(
                    f"  {entry.level_id} ({entry.spread_pct*100:+.2f}%) -> "
                    f"{exit_level.level_id} ({exit_level.spread_pct*100:+.2f}%) | "
                    f"Profit: {entry.expected_profit_pct*100:.3f}% | "
                    f"Fees: {entry.estimated_fee_pct*100:.3f}% | "
                    f"Valid: {entry.is_valid}"
                )
            else:
                summary_lines.append(
                    f"  {entry.level_id} ({entry.spread_pct*100:+.2f}%) -> "
                    f"EXIT NOT FOUND ({exit_id})"
                )

        return "\n".join(summary_lines)
