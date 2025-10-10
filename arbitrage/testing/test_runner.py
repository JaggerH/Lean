"""
LeanTestRunner - LEAN 测试运行器

运行 LEAN 算法并解析测试结果
"""

import subprocess
import json
import re
from pathlib import Path
from typing import Dict, Optional


class LeanTestRunner:
    """运行 LEAN 测试算法并解析结果"""

    def __init__(self, lean_bin_path: str = None):
        """
        初始化测试运行器

        Args:
            lean_bin_path: LEAN Launcher bin 目录路径
                          默认为 Launcher/bin/Debug
        """
        if lean_bin_path is None:
            # 默认路径相对于当前文件
            self.lean_bin_path = Path(__file__).parent.parent.parent / "Launcher" / "bin" / "Debug"
        else:
            self.lean_bin_path = Path(lean_bin_path)

    def run_test(self, config_path: str) -> Dict:
        """
        运行测试算法

        Args:
            config_path: 配置文件路径（相对于 Lean 根目录）

        Returns:
            dict: 包含测试结果和回测统计
                {
                    'success': bool,
                    'test_results': dict,
                    'backtest_stats': dict,
                    'output': str
                }
        """
        # 构建命令
        cmd = [
            "dotnet",
            "QuantConnect.Lean.Launcher.dll",
            "--config", config_path
        ]

        print(f"🚀 Running LEAN test...")
        print(f"   Config: {config_path}")
        print(f"   Working dir: {self.lean_bin_path}")

        # 运行 LEAN
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(self.lean_bin_path),
            timeout=120  # 2分钟超时
        )

        # 合并输出
        output = result.stdout + result.stderr

        # 解析结果
        test_results = self._extract_test_results(output)
        backtest_stats = self._extract_backtest_stats(output)

        success = False
        if test_results:
            success = test_results['failed'] == 0
        else:
            # 如果没有测试结果，检查是否有错误
            success = "Runtime Error" not in output

        return {
            'success': success,
            'test_results': test_results,
            'backtest_stats': backtest_stats,
            'output': output,
            'return_code': result.returncode
        }

    def _extract_test_results(self, output: str) -> Optional[Dict]:
        """
        从输出中提取测试结果 JSON

        Args:
            output: LEAN 输出

        Returns:
            dict: 测试结果，如果未找到则返回 None
        """
        pattern = r'__TEST_RESULTS_JSON__(.*?)__END_TEST_RESULTS__'
        match = re.search(pattern, output, re.DOTALL)

        if match:
            json_str = match.group(1).strip()
            # 移除 Debug: 前缀（如果有）
            json_str = re.sub(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} TRACE:: Debug: ', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ', '', json_str, flags=re.MULTILINE)

            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                print(f"⚠️ Failed to parse test results JSON: {e}")
                print(f"   Raw JSON: {json_str[:500]}...")
                return None
        return None

    def _extract_backtest_stats(self, output: str) -> Dict:
        """
        提取回测统计数据

        Args:
            output: LEAN 输出

        Returns:
            dict: 回测统计
        """
        stats = {}

        # 提取关键统计数据的模式
        patterns = {
            'total_trades': r'STATISTICS:: Total Orders (\d+)',
            'sharpe_ratio': r'STATISTICS:: Sharpe Ratio ([-\d.]+)',
            'net_profit': r'STATISTICS:: Net Profit ([-\d.]+)%',
            'win_rate': r'STATISTICS:: Win Rate ([-\d.]+)%',
            'max_drawdown': r'STATISTICS:: Drawdown ([-\d.]+)%',
            'total_fees': r'STATISTICS:: Total Fees \$?([-\d.]+)',
            'end_equity': r'STATISTICS:: End Equity ([-\d.]+)',
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, output)
            if match:
                try:
                    value = match.group(1)
                    # 尝试转换为数字
                    if '.' in value:
                        stats[key] = float(value)
                    else:
                        stats[key] = int(value)
                except (ValueError, IndexError):
                    stats[key] = value

        return stats

    def print_results(self, results: Dict):
        """
        打印测试结果

        Args:
            results: run_test() 返回的结果
        """
        print("\n" + "="*60)
        print("📊 TEST RESULTS")
        print("="*60)

        if results['test_results']:
            test = results['test_results']
            print(f"Total Assertions: {test['total_assertions']}")
            print(f"Passed: {test['passed']} ✅")
            print(f"Failed: {test['failed']} ❌")
            print(f"Pass Rate: {test['pass_rate']*100:.1f}%")

            if test['failed'] > 0:
                print("\n❌ Failed Assertions:")
                for assertion in test['assertions']:
                    if not assertion['passed']:
                        print(f"  - [{assertion['location']}] {assertion['message']}")
        else:
            print("⚠️ No test results found")

        print("\n" + "="*60)
        print("📈 BACKTEST STATISTICS")
        print("="*60)

        if results['backtest_stats']:
            for key, value in results['backtest_stats'].items():
                formatted_key = key.replace('_', ' ').title()
                print(f"{formatted_key}: {value}")
        else:
            print("⚠️ No backtest stats found")

        print("="*60)

        if results['success']:
            print("\n✅ TEST PASSED")
        else:
            print("\n❌ TEST FAILED")

        print("="*60)


def run_lean_test(config_path: str, lean_bin_path: str = None) -> Dict:
    """
    便捷函数：运行 LEAN 测试

    Args:
        config_path: 配置文件路径
        lean_bin_path: LEAN bin 目录路径（可选）

    Returns:
        dict: 测试结果
    """
    runner = LeanTestRunner(lean_bin_path)
    return runner.run_test(config_path)


if __name__ == "__main__":
    # 示例用法
    import sys

    if len(sys.argv) < 2:
        print("Usage: python test_runner.py <config_path>")
        print("Example: python test_runner.py arbitrage/tests/configs/config_order_execution.json")
        sys.exit(1)

    config_path = sys.argv[1]
    runner = LeanTestRunner()
    results = runner.run_test(config_path)
    runner.print_results(results)

    sys.exit(0 if results['success'] else 1)
