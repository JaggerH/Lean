"""
Pytest 集成 - 运行 LEAN 集成测试

使用 pytest 运行 LEAN 算法测试并验证结果
"""

import pytest
import sys
from pathlib import Path

# Add arbitrage directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from testing.test_runner import LeanTestRunner


class TestLeanIntegration:
    """LEAN 集成测试类"""

    @pytest.fixture
    def test_runner(self):
        """创建测试运行器 fixture"""
        return LeanTestRunner()

    def test_order_execution(self, test_runner):
        """
        测试订单执行流程

        验证内容:
        1. 所有断言通过
        2. 订单成功创建和成交
        3. 持仓状态正确
        4. 回测统计合理
        """
        # 运行测试
        results = test_runner.run_test(
            config_path="../../../arbitrage/tests/configs/config_order_execution.json"
        )

        # 打印结果
        test_runner.print_results(results)

        # ========== 验证测试结果 ==========

        # 验证测试成功
        assert results['success'], "测试应该通过"

        # 验证有测试结果
        assert results['test_results'] is not None, "应该有测试结果"

        test_results = results['test_results']

        # 验证断言统计
        assert test_results['total_assertions'] > 0, "应该有断言"
        assert test_results['passed'] > 0, "应该有通过的断言"
        assert test_results['failed'] == 0, f"不应该有失败的断言，但有 {test_results['failed']} 个失败"

        # 验证通过率
        assert test_results['pass_rate'] == 1.0, f"通过率应为 100%，实际为 {test_results['pass_rate']*100:.1f}%"

        # 验证检查点
        assert len(test_results['checkpoints']) >= 3, "应该有至少3个检查点"

        # ========== 验证回测统计 ==========

        backtest_stats = results['backtest_stats']

        # 验证有交易
        if 'total_trades' in backtest_stats:
            assert backtest_stats['total_trades'] > 0, "应该有交易记录"

        # 验证盈亏合理
        if 'net_profit' in backtest_stats:
            # 允许小额亏损（手续费）
            assert backtest_stats['net_profit'] > -1.0, "盈亏应该在合理范围"

        print("\n✅ 所有 pytest 断言通过!")


def test_order_execution_simple():
    """简单的测试函数（不使用 fixture）"""
    runner = LeanTestRunner()
    results = runner.run_test(
        config_path="../../../arbitrage/tests/configs/config_order_execution.json"
    )

    # 基本验证
    assert results['success'], "测试应该通过"
    assert results['test_results'] is not None, "应该有测试结果"
    assert results['test_results']['failed'] == 0, "不应该有失败的断言"


if __name__ == "__main__":
    # 直接运行测试
    pytest.main([__file__, "-v", "-s"])
