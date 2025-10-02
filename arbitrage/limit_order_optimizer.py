"""
LimitOrderOptimizer - Kraken限价单价格计算

两个静态函数,用于计算Maker限价单价格
"""


class LimitOrderOptimizer:
    """限价单优化器 - 仅静态方法"""

    @staticmethod
    def calculate_buy_limit_price(best_bid: float, best_ask: float,
                                   aggression: float = 0.6) -> float:
        """
        计算买入限价单价格

        Args:
            best_bid: 当前最高买价
            best_ask: 当前最低卖价
            aggression: 激进度 (0.0-0.99)

        Returns:
            限价买入价格 (在spread内,确保Maker)
        """
        aggression = max(0.0, min(aggression, 0.99))
        spread = best_ask - best_bid
        return best_bid + spread * aggression

    @staticmethod
    def calculate_sell_limit_price(best_bid: float, best_ask: float,
                                    aggression: float = 0.6) -> float:
        """
        计算卖出限价单价格

        Args:
            best_bid: 当前最高买价
            best_ask: 当前最低卖价
            aggression: 激进度 (0.0-0.99)

        Returns:
            限价卖出价格 (在spread内,确保Maker)
        """
        aggression = max(0.0, min(aggression, 0.99))
        spread = best_ask - best_bid
        return best_ask - spread * aggression
