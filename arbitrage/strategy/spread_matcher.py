"""
SpreadMatcher - 配对交易价差撮合器（纯静态方法实现）

职责：
1. 自动检测 OrderbookDepth 支持情况
2. 根据检测结果选择单腿或双腿撮合算法
3. 以市值相等为对冲原则进行撮合
4. 返回可直接用于 SpreadMarketOrder 的订单数量

核心原则：
- 市值对冲：确保两侧市值相等（usd_buy ≈ usd_sell）
- 股数为撮合单位：遍历 orderbook 时以股数累积
- 部分成交：允许在最后一层做部分成交
- Lot 对齐：使用 LEAN 原生的 security.SymbolProperties.LotSize

使用方式：
    from arbitrage.strategy.spread_matcher import SpreadMatcher

    # 做多价差：期望 crypto 便宜 1%
    result = SpreadMatcher.match_pair(
        algorithm=self,
        symbol1=btcusd_symbol,
        symbol2=btc_symbol,
        target_usd=3000,
        direction="LONG_SPREAD",
        expected_spread_pct=-1.0
    )

    if result and result.executable:
        tickets = []
        for symbol, qty in result.legs:
            ticket = self.market_order(symbol, qty)
            tickets.append(ticket)
"""

from AlgorithmImports import QCAlgorithm, Symbol
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass


@dataclass
class MatchResult:
    """
    撮合结果数据类

    包含完整的撮合统计和可直接用于下单的订单数量
    """
    legs: List[Tuple[Symbol, float]]  # [(symbol, qty), ...] 可直接传给 SpreadMarketOrder
    matched_details: List[Dict]       # 每层撮合明细（用于调试）
    total_shares_ob: float            # OrderbookDepth 侧总股数
    total_shares_counter: float       # 对手侧总股数
    total_usd_buy: float              # 总买入市值
    total_usd_sell: float             # 总卖出市值
    avg_buy_price: float              # 买入加权平均价
    avg_sell_price: float             # 卖出加权平均价
    avg_spread_pct: float             # 加权平均价差
    reached_target: bool              # 是否达到目标市值
    remaining_usd: float              # 剩余未成交金额
    executable: bool                  # 是否可执行


class SpreadMatcher:
    """
    配对交易价差撮合器（纯静态方法实现）

    支持两种场景：
    1. 单腿：一侧 OrderbookDepth，另一侧 BestBid/Ask（流动性无限假设）
    2. 双腿：两侧都是 OrderbookDepth

    对冲原则：市值相等（不是股数相等）

    所有方法都是静态方法，无需实例化对象。
    """

    @staticmethod
    def match_pair(
        algorithm: QCAlgorithm,
        symbol1: Symbol,
        symbol2: Symbol,
        target_usd: float,
        direction: str,  # "LONG_SPREAD" 或 "SHORT_SPREAD"
        expected_spread_pct: float,
        debug: bool = False
    ) -> Optional[MatchResult]:
        """
        主入口：自动检测并选择撮合算法

        Args:
            algorithm: QCAlgorithm 实例
            symbol1: 第一个 Symbol（通常是 crypto，如 BTCUSD）
            symbol2: 第二个 Symbol（通常是 stock，如 BTC）
            target_usd: 目标市值（美元，正数）
            direction: "LONG_SPREAD" 表示买入 symbol1, 卖出 symbol2（期望 crypto 便宜）
                      "SHORT_SPREAD" 表示卖出 symbol1, 买入 symbol2（期望 crypto 贵）
            expected_spread_pct: 预期价差百分比
                               - LONG_SPREAD: 期望 spread <= expected_spread_pct（负值，crypto 便宜）
                               - SHORT_SPREAD: 期望 spread >= expected_spread_pct（正值，crypto 贵）
            debug: 是否输出调试信息

        Returns:
            MatchResult 或 None（如果无法撮合）

        Example:
            # 做多价差：期望 crypto 便宜 1%
            result = SpreadMatcher.match_pair(
                algorithm=self,
                symbol1=btcusd_symbol,
                symbol2=btc_symbol,
                target_usd=3000,
                direction="LONG_SPREAD",
                expected_spread_pct=-1.0
            )

            # 做空价差：期望 crypto 贵 1%
            result = SpreadMatcher.match_pair(
                algorithm=self,
                symbol1=btcusd_symbol,
                symbol2=btc_symbol,
                target_usd=3000,
                direction="SHORT_SPREAD",
                expected_spread_pct=1.0
            )

            if result and result.executable:
                tickets = []
                for symbol, qty in result.legs:
                    ticket = self.market_order(symbol, qty)
                    tickets.append(ticket)
        """
        # 1. 检测 OrderbookDepth 支持情况
        has_ob1 = SpreadMatcher._has_orderbook_depth(algorithm, symbol1)
        has_ob2 = SpreadMatcher._has_orderbook_depth(algorithm, symbol2)

        # 2. 根据检测结果选择撮合算法
        if has_ob1 and has_ob2:
            # 双腿场景
            return SpreadMatcher._match_dual_leg(
                algorithm, symbol1, symbol2, target_usd, direction, expected_spread_pct, debug
            )
        elif has_ob1 and not has_ob2:
            # 单腿场景：symbol1 有 orderbook，symbol2 只有 BestPrice
            return SpreadMatcher._match_single_leg(
                algorithm, symbol1, symbol2, target_usd, direction, expected_spread_pct, debug
            )
        elif not has_ob1 and has_ob2:
            # 单腿场景：symbol2 有 orderbook，symbol1 只有 BestPrice
            # 交换 symbol 顺序，反转方向
            reversed_direction = "SHORT_SPREAD" if direction == "LONG_SPREAD" else "LONG_SPREAD"
            result = SpreadMatcher._match_single_leg(
                algorithm, symbol2, symbol1, target_usd, reversed_direction, expected_spread_pct, debug
            )

            # 交换回来
            if result and result.executable:
                result.legs = [(result.legs[1][0], result.legs[1][1]), (result.legs[0][0], result.legs[0][1])]
            return result
        else:
            # 两侧都没有 orderbook，使用简化逻辑（BestBid/Ask）
            return SpreadMatcher._match_fallback(
                algorithm, symbol1, symbol2, target_usd, direction, expected_spread_pct, debug
            )

    @staticmethod
    def _has_orderbook_depth(algorithm: QCAlgorithm, symbol: Symbol) -> bool:
        """
        检测是否支持 OrderbookDepth

        Args:
            algorithm: QCAlgorithm 实例
            symbol: Symbol

        Returns:
            True if OrderbookDepth 可用且有效，False otherwise
        """
        security = algorithm.securities[symbol]
        orderbook = security.cache.orderbook_depth

        if orderbook is None:
            return False

        if orderbook.bids is None or len(orderbook.bids) == 0:
            return False

        if orderbook.asks is None or len(orderbook.asks) == 0:
            return False

        return True

    @staticmethod
    def _match_single_leg(
        algorithm: QCAlgorithm,
        symbol_ob: Symbol,      # 有 OrderbookDepth 的一侧
        symbol_bp: Symbol,      # 只有 BestPrice 的一侧（流动性无限假设）
        target_usd: float,
        direction: str,
        expected_spread_pct: float,
        debug: bool
    ) -> Optional[MatchResult]:
        """
        单腿撮合：一侧 OrderbookDepth，另一侧 BestPrice（流动性无限）

        核心逻辑：
        1. 根据 direction 选择 orderbook 的正确档位（asks/bids）
        2. 遍历 orderbook 深度，计算每档与对手价格的市场价差
        3. 验证价差是否符合预期（根据 direction）
        4. 累积满足条件的股数并计算对冲数量（市值相等原则）

        Args:
            algorithm: QCAlgorithm 实例
            symbol_ob: 有 OrderbookDepth 的 Symbol（symbol1，通常是 crypto）
            symbol_bp: 只有 BestPrice 的 Symbol（symbol2，通常是 stock）
            target_usd: 目标市值（正数）
            direction: "LONG_SPREAD"（买 symbol1 卖 symbol2）或 "SHORT_SPREAD"（卖 symbol1 买 symbol2）
            expected_spread_pct: 预期价差百分比
            debug: 调试开关

        Returns:
            MatchResult 或 None
        """
        # 1. 获取 orderbook 侧的深度
        security_ob = algorithm.securities[symbol_ob]
        orderbook = security_ob.cache.orderbook_depth

        # 2. 根据方向选择正确的档位和对手价格
        # LONG_SPREAD: 买 symbol1 (asks)，卖 symbol2 (bid_price)
        # SHORT_SPREAD: 卖 symbol1 (bids)，买 symbol2 (ask_price)
        is_buying_ob = (direction == "LONG_SPREAD")
        levels_ob = orderbook.asks if is_buying_ob else orderbook.bids

        # 3. 获取对手侧的 BestPrice（流动性无限假设）
        security_bp = algorithm.securities[symbol_bp]
        # 对手侧方向相反
        is_buying_bp = not is_buying_ob
        price_bp = security_bp.ask_price if is_buying_bp else security_bp.bid_price

        # Fallback to last price
        if price_bp == 0:
            price_bp = security_bp.price

        if price_bp <= 0:
            if debug:
                algorithm.debug(f"[SpreadMatcher] ❌ Invalid BestPrice for {symbol_bp}: {price_bp} (direction: {direction})")
            return None

        # 4. 获取 lot size
        lot_ob = security_ob.symbol_properties.lot_size
        lot_bp = security_bp.symbol_properties.lot_size

        # 5. 遍历 orderbook 侧的深度档位
        matched = []
        total_shares_ob = 0.0
        total_usd_ob = 0.0

        # 用于计算符合价差条件的最大支持流动性
        max_supported_shares_ob = 0.0
        max_supported_value_ob = 0.0
        valid_levels_count = 0

        for level in levels_ob:
            price_ob = float(level.price)
            size_ob = float(level.size)

            # 5a. 计算市场价差（始终基于 symbol 位置）
            # symbol_ob 是 symbol1 (crypto), symbol_bp 是 symbol2 (stock)
            spread_pct = SpreadMatcher._calc_spread_pct(price_ob, price_bp)

            # 5b. 验证价差是否符合预期
            spread_valid = SpreadMatcher._validate_spread(spread_pct, expected_spread_pct, direction)

            if debug:
                if spread_valid:
                    algorithm.debug(
                        f"[SpreadMatcher] ✅ Spread MEETS expected | {symbol_ob} @ ${price_ob:.2f}, {symbol_bp} @ ${price_bp:.2f}, "
                        f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                    )
                else:
                    algorithm.debug(
                        f"[SpreadMatcher] ❌ Spread NOT meet expected | {symbol_ob} @ ${price_ob:.2f}, {symbol_bp} @ ${price_bp:.2f}, "
                        f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                    )

            if not spread_valid:
                break  # 价差不满足，停止累积

            # 累积符合价差条件的最大流动性（不受 target_usd 限制）
            max_supported_shares_ob += SpreadMatcher._round_to_lot(size_ob, lot_ob)
            max_supported_value_ob += size_ob * price_ob
            valid_levels_count += 1

            # 5c. 计算可消耗的股数（按 orderbook 侧的市值）
            remaining_usd = max(0.0, target_usd - total_usd_ob)
            if remaining_usd <= 1e-9:
                break

            # 按 orderbook 侧的价格计算剩余可用股数
            max_shares_by_usd = remaining_usd / price_ob
            available_shares = SpreadMatcher._round_to_lot(size_ob, lot_ob)
            consumable_shares = min(available_shares, max_shares_by_usd)
            consumable_shares = SpreadMatcher._round_to_lot(consumable_shares, lot_ob)

            if consumable_shares <= 0:
                continue

            # 5d. 计算本层的市值
            usd_ob_layer = consumable_shares * price_ob
            usd_bp_layer = consumable_shares * price_bp

            # 5e. 累积
            matched.append({
                "price_ob": price_ob,
                "price_bp": price_bp,
                "qty_ob": consumable_shares,
                "usd_ob": usd_ob_layer,
                "usd_bp": usd_bp_layer,
                "spread_pct": spread_pct
            })

            total_shares_ob += consumable_shares
            total_usd_ob += usd_ob_layer

            # 检查是否达到目标
            if total_usd_ob >= target_usd - 1e-6:
                break

        # 6. 如果没有成功撮合任何股数
        if total_shares_ob <= 0:
            return None

        # 7. 计算对手侧的对冲数量（市值相等原则）
        # total_usd_ob 是 orderbook 侧的市值
        # 对手侧需要对冲相等的市值
        total_shares_bp = total_usd_ob / price_bp
        total_shares_bp = SpreadMatcher._round_to_lot(total_shares_bp, lot_bp)

        # 检查对冲侧数量是否为零（_round_to_lot 可能将小数量舍入为0）
        if total_shares_bp <= 0:
            return None

        # 8. 计算统计数据
        # 加权平均价格
        avg_price_ob = total_usd_ob / total_shares_ob if total_shares_ob > 0 else 0
        avg_price_bp = price_bp  # BestPrice 侧没有加权，直接使用 BestPrice

        # 加权平均价差
        avg_spread_pct = sum(m["spread_pct"] * m["qty_ob"] for m in matched) / total_shares_ob if total_shares_ob > 0 else 0

        # 9. 组装返回结果（带符号）
        qty_ob_signed = total_shares_ob if is_buying_ob else -total_shares_ob
        qty_bp_signed = -total_shares_bp if is_buying_ob else total_shares_bp

        result = MatchResult(
            legs=[(symbol_ob, qty_ob_signed), (symbol_bp, qty_bp_signed)],
            matched_details=matched,
            total_shares_ob=total_shares_ob,
            total_shares_counter=total_shares_bp,
            total_usd_buy=total_usd_ob if is_buying_ob else total_shares_bp * price_bp,
            total_usd_sell=total_shares_bp * price_bp if is_buying_ob else total_usd_ob,
            avg_buy_price=avg_price_ob if is_buying_ob else avg_price_bp,
            avg_sell_price=avg_price_bp if is_buying_ob else avg_price_ob,
            avg_spread_pct=avg_spread_pct,
            reached_target=total_usd_ob >= target_usd - 1e-6,
            remaining_usd=max(0.0, target_usd - total_usd_ob),
            executable=True
        )

        if debug:
            # 计算符合价差条件的最大支持流动性的平均价格
            max_avg_price_ob = max_supported_value_ob / max_supported_shares_ob if max_supported_shares_ob > 0 else 0
            max_supported_usd = max_supported_value_ob

            algorithm.debug(
                f"[SpreadMatcher] ✅ Single-leg matched | "
                f"{symbol_ob}: {qty_ob_signed:.4f} @ ${avg_price_ob:.2f} | "
                f"{symbol_bp}: {qty_bp_signed:.4f} @ ${avg_price_bp:.2f} | "
                f"Spread: {avg_spread_pct:.2f}%"
            )
            algorithm.debug(
                f"[SpreadMatcher] 📊 MAX supported (spread-valid) | "
                f"{symbol_ob}: {max_supported_shares_ob:.4f} shares @ ${max_avg_price_ob:.2f} avg | "
                f"Max USD: ${max_supported_usd:.2f} | "
                f"Levels: {valid_levels_count}"
            )

        return result

    @staticmethod
    def _match_dual_leg(
        algorithm: QCAlgorithm,
        symbol1: Symbol,
        symbol2: Symbol,
        target_usd: float,
        direction: str,
        expected_spread_pct: float,
        debug: bool
    ) -> Optional[MatchResult]:
        """
        双腿撮合：两侧都有 OrderbookDepth

        核心逻辑：
        1. 根据 direction 选择两侧 orderbook 的正确档位
        2. 双指针遍历两侧 orderbook，计算市场价差
        3. 验证价差是否符合预期（根据 direction）
        4. 撮合时确保市值相等（不是股数相等）
        5. 直到达到目标市值或深度耗尽

        Args:
            algorithm: QCAlgorithm 实例
            symbol1: 第一个 Symbol（通常是 crypto）
            symbol2: 第二个 Symbol（通常是 stock）
            target_usd: 目标市值（正数）
            direction: "LONG_SPREAD"（买 symbol1 卖 symbol2）或 "SHORT_SPREAD"（卖 symbol1 买 symbol2）
            expected_spread_pct: 预期价差百分比
            debug: 调试开关

        Returns:
            MatchResult 或 None
        """
        # 1. 获取两侧的 orderbook
        security1 = algorithm.securities[symbol1]
        security2 = algorithm.securities[symbol2]
        orderbook1 = security1.cache.orderbook_depth
        orderbook2 = security2.cache.orderbook_depth

        # 2. 根据方向选择正确的档位
        # LONG_SPREAD: 买 symbol1 (asks)，卖 symbol2 (bids)
        # SHORT_SPREAD: 卖 symbol1 (bids)，买 symbol2 (asks)
        is_buying_s1 = (direction == "LONG_SPREAD")
        levels1 = list(orderbook1.asks) if is_buying_s1 else list(orderbook1.bids)
        levels2 = list(orderbook2.bids) if is_buying_s1 else list(orderbook2.asks)

        # 3. 获取 lot size
        lot1 = security1.symbol_properties.lot_size
        lot2 = security2.symbol_properties.lot_size

        # 4. 双指针遍历
        i = 0
        j = 0
        matched = []
        total_shares1 = 0.0
        total_shares2 = 0.0
        total_usd_buy = 0.0
        total_usd_sell = 0.0

        while i < len(levels1) and j < len(levels2):
            price1 = float(levels1[i].price)
            size1 = float(levels1[i].size)
            price2 = float(levels2[j].price)
            size2 = float(levels2[j].size)

            # 4a. 计算市场价差（始终基于 symbol 位置）
            spread_pct = SpreadMatcher._calc_spread_pct(price1, price2)

            # 4b. 验证价差是否符合预期
            spread_valid = SpreadMatcher._validate_spread(spread_pct, expected_spread_pct, direction)

            if debug:
                if spread_valid:
                    algorithm.debug(
                        f"[SpreadMatcher] ✅ Dual-leg Spread MEETS expected | {symbol1} @ ${price1:.2f}, {symbol2} @ ${price2:.2f}, "
                        f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                    )
                else:
                    algorithm.debug(
                        f"[SpreadMatcher] ❌ Dual-leg Spread NOT meet expected | {symbol1} @ ${price1:.2f}, {symbol2} @ ${price2:.2f}, "
                        f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                    )

            if not spread_valid:
                # 尝试移动对手侧指针以寻找更优价格
                j += 1
                continue

            # 4c. 计算可撮合的股数
            available1 = SpreadMatcher._round_to_lot(size1, lot1)
            available2 = SpreadMatcher._round_to_lot(size2, lot2)

            if available1 <= 0:
                i += 1
                continue
            if available2 <= 0:
                j += 1
                continue

            # 双腿撮合：以市值相等为原则
            # 计算在当前价格对下，目标市值还剩多少
            remaining_usd = max(0.0, target_usd - total_usd_buy)
            if remaining_usd <= 1e-9:
                break

            # 计算剩余可撮合的股数（按买入侧计算）
            max_shares_by_usd = remaining_usd / buy_price

            # 撮合数量：以买入侧的股数为准，卖出侧按市值对冲
            match_qty1 = min(available1, max_shares_by_usd)
            match_qty1 = SpreadMatcher._round_to_lot(match_qty1, lot1)

            # 计算对手侧需要对冲的股数（市值相等）
            market_value = match_qty1 * price1
            match_qty2 = market_value / price2
            match_qty2 = SpreadMatcher._round_to_lot(match_qty2, lot2)

            # 确保对手侧不超过可用量
            if match_qty2 > available2:
                # 按对手侧可用量重新计算
                match_qty2 = available2
                market_value = match_qty2 * price2
                match_qty1 = market_value / price1
                match_qty1 = SpreadMatcher._round_to_lot(match_qty1, lot1)

            if match_qty1 <= 0 or match_qty2 <= 0:
                break

            # 4d. 计算本层的市值
            usd1_layer = match_qty1 * price1
            usd2_layer = match_qty2 * price2

            matched.append({
                "price1": price1,
                "price2": price2,
                "qty1": match_qty1,
                "qty2": match_qty2,
                "usd1": usd1_layer,
                "usd2": usd2_layer,
                "spread_pct": spread_pct
            })

            # 4e. 更新累积值
            total_shares1 += match_qty1
            total_shares2 += match_qty2
            # 根据方向计算买入/卖出市值
            if is_buying_s1:
                total_usd_buy += usd1_layer
                total_usd_sell += usd2_layer
            else:
                total_usd_buy += usd2_layer
                total_usd_sell += usd1_layer

            # 4f. 更新档位剩余量
            size1 -= match_qty1
            size2 -= match_qty2

            # 4g. 移动指针
            if size1 < lot1 + 1e-12:
                i += 1
            if size2 < lot2 + 1e-12:
                j += 1

            # 4h. 检查是否达到目标
            if total_usd_buy >= target_usd - 1e-6:
                break

        # 5. 如果没有成功撮合
        if total_shares1 <= 0 or total_shares2 <= 0:
            if debug:
                algorithm.debug("[SpreadMatcher] ❌ No shares matched in dual-leg")
            return None

        # 6. 计算统计数据
        total_usd1 = sum(m["usd1"] for m in matched)
        total_usd2 = sum(m["usd2"] for m in matched)

        avg_price1 = total_usd1 / total_shares1 if total_shares1 > 0 else 0
        avg_price2 = total_usd2 / total_shares2 if total_shares2 > 0 else 0

        avg_buy_price = avg_price1 if is_buying_s1 else avg_price2
        avg_sell_price = avg_price2 if is_buying_s1 else avg_price1

        avg_spread_pct = sum(m["spread_pct"] * m["qty1"] for m in matched) / total_shares1 if total_shares1 > 0 else 0

        # 7. 组装返回结果（带符号）
        qty1_signed = total_shares1 if is_buying_s1 else -total_shares1
        qty2_signed = -total_shares2 if is_buying_s1 else total_shares2

        result = MatchResult(
            legs=[(symbol1, qty1_signed), (symbol2, qty2_signed)],
            matched_details=matched,
            total_shares_ob=total_shares1,
            total_shares_counter=total_shares2,
            total_usd_buy=total_usd_buy,
            total_usd_sell=total_usd_sell,
            avg_buy_price=avg_buy_price,
            avg_sell_price=avg_sell_price,
            avg_spread_pct=avg_spread_pct,
            reached_target=total_usd_buy >= target_usd - 1e-6,
            remaining_usd=max(0.0, target_usd - total_usd_buy),
            executable=True
        )

        if debug:
            algorithm.debug(
                f"[SpreadMatcher] ✅ Dual-leg matched | "
                f"{symbol1}: {qty1_signed:.4f} | {symbol2}: {qty2_signed:.4f} | "
                f"Spread: {avg_spread_pct:.2f}%"
            )

        return result

    @staticmethod
    def _match_fallback(
        algorithm: QCAlgorithm,
        symbol1: Symbol,
        symbol2: Symbol,
        target_usd: float,
        direction: str,
        expected_spread_pct: float,
        debug: bool
    ) -> Optional[MatchResult]:
        """
        回退逻辑：两侧都没有 OrderbookDepth
        使用 BestBid/Ask 进行简化计算

        Args:
            algorithm: QCAlgorithm 实例
            symbol1: 第一个 Symbol（通常是 crypto）
            symbol2: 第二个 Symbol（通常是 stock）
            target_usd: 目标市值（正数）
            direction: "LONG_SPREAD"（买 symbol1 卖 symbol2）或 "SHORT_SPREAD"（卖 symbol1 买 symbol2）
            expected_spread_pct: 预期价差百分比
            debug: 调试开关

        Returns:
            MatchResult 或 None
        """
        security1 = algorithm.securities[symbol1]
        security2 = algorithm.securities[symbol2]

        is_buying_s1 = (direction == "LONG_SPREAD")

        # 根据方向选择正确的价格
        # LONG_SPREAD: 买 symbol1 (ask)，卖 symbol2 (bid)
        # SHORT_SPREAD: 卖 symbol1 (bid)，买 symbol2 (ask)
        price1 = security1.ask_price if is_buying_s1 else security1.bid_price
        price2 = security2.bid_price if is_buying_s1 else security2.ask_price

        # Fallback to last price
        if price1 == 0:
            price1 = security1.price
        if price2 == 0:
            price2 = security2.price

        if price1 <= 0 or price2 <= 0:
            if debug:
                algorithm.debug(f"[SpreadMatcher] ❌ Invalid prices: {symbol1}={price1:.2f}, {symbol2}={price2:.2f} (direction: {direction})")
            return None

        # 计算市场价差（始终基于 symbol 位置）
        spread_pct = SpreadMatcher._calc_spread_pct(price1, price2)

        # 验证价差是否符合预期
        spread_valid = SpreadMatcher._validate_spread(spread_pct, expected_spread_pct, direction)

        if debug:
            if spread_valid:
                algorithm.debug(
                    f"[SpreadMatcher] ✅ Fallback Spread MEETS expected | {symbol1} @ ${price1:.2f}, {symbol2} @ ${price2:.2f}, "
                    f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                )
            else:
                algorithm.debug(
                    f"[SpreadMatcher] ❌ Fallback Spread NOT meet expected | {symbol1} @ ${price1:.2f}, {symbol2} @ ${price2:.2f}, "
                    f"spread={spread_pct*100:.2f}%, expected={expected_spread_pct*100:.2f}%, direction={direction}"
                )

        if not spread_valid:
            return None

        # 计算数量（市值相等）
        qty1 = target_usd / price1
        qty2 = target_usd / price2

        lot1 = security1.symbol_properties.lot_size
        lot2 = security2.symbol_properties.lot_size

        qty1 = SpreadMatcher._round_to_lot(qty1, lot1)
        qty2 = SpreadMatcher._round_to_lot(qty2, lot2)

        # 带符号
        qty1_signed = qty1 if is_buying_s1 else -qty1
        qty2_signed = -qty2 if is_buying_s1 else qty2

        # 计算买入/卖出价格和市值
        buy_price = price1 if is_buying_s1 else price2
        sell_price = price2 if is_buying_s1 else price1

        result = MatchResult(
            legs=[(symbol1, qty1_signed), (symbol2, qty2_signed)],
            matched_details=[],
            total_shares_ob=qty1,
            total_shares_counter=qty2,
            total_usd_buy=qty1 * price1 if is_buying_s1 else qty2 * price2,
            total_usd_sell=qty2 * price2 if is_buying_s1 else qty1 * price1,
            avg_buy_price=buy_price,
            avg_sell_price=sell_price,
            avg_spread_pct=spread_pct,
            reached_target=True,
            remaining_usd=0.0,
            executable=True
        )

        if debug:
            algorithm.debug(
                f"[SpreadMatcher] ✅ Fallback matched | "
                f"{symbol1}: {qty1_signed:.4f} @ ${price1:.2f} | "
                f"{symbol2}: {qty2_signed:.4f} @ ${price2:.2f} | "
                f"Spread: {spread_pct:.2f}%"
            )

        return result

    @staticmethod
    def _calc_spread_pct(symbol1_price: float, symbol2_price: float) -> float:
        """
        计算市场价差百分比（始终基于 symbol 位置）

        Formula: (symbol1_price - symbol2_price) / symbol1_price

        符合 SpreadManager.calculate_spread_pct 的逻辑：
        - 正值：symbol1 (crypto) 贵于 symbol2 (stock)，适合 SHORT_SPREAD
        - 负值：symbol1 (crypto) 便宜于 symbol2 (stock)，适合 LONG_SPREAD

        Args:
            symbol1_price: symbol1 的价格（通常是 crypto）
            symbol2_price: symbol2 的价格（通常是 stock）

        Returns:
            价差百分比（例如 -1.5 表示 crypto 便宜 1.5%）
        """
        if symbol1_price == 0:
            return float("-inf")
        return (symbol1_price - symbol2_price) / symbol1_price

    @staticmethod
    def _validate_spread(spread_pct: float, expected_spread_pct: float, direction: str) -> bool:
        """
        验证价差是否满足预期（根据方向判断）

        逻辑：
        - LONG_SPREAD（买 crypto，卖 stock）：期望 crypto 便宜，spread_pct <= expected_spread_pct
        - SHORT_SPREAD（卖 crypto，买 stock）：期望 crypto 贵，spread_pct >= expected_spread_pct

        Args:
            spread_pct: 实际市场价差百分比
            expected_spread_pct: 预期价差百分比
            direction: 交易方向 "LONG_SPREAD" 或 "SHORT_SPREAD"

        Returns:
            True if 价差符合预期, False otherwise
        """
        if direction == "LONG_SPREAD":
            return spread_pct <= expected_spread_pct
        else:  # SHORT_SPREAD
            return spread_pct >= expected_spread_pct

    @staticmethod
    def _round_to_lot(qty: float, lot_size: float) -> float:
        """
        对齐到最小交易单位（使用 LEAN 原生 LotSize）

        Args:
            qty: 原始数量
            lot_size: 最小交易单位（来自 security.SymbolProperties.LotSize）

        Returns:
            对齐后的数量（向下取整）
        """
        if lot_size <= 0:
            return qty
        return (int(qty / lot_size)) * lot_size
