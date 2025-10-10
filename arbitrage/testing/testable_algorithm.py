"""
TestableAlgorithm - 可测试的算法基类

在回测流程中嵌入单元测试能力：
1. 内置断言方法
2. 测试结果自动收集
3. 检查点机制
4. 双重统计输出（回测 + 测试）
"""

from AlgorithmImports import *
from typing import List, Dict, Any, Callable
import json
import inspect


class AssertionResult:
    """单个断言结果"""

    def __init__(self, name: str, passed: bool, message: str,
                 timestamp, location: str):
        self.name = name
        self.passed = passed
        self.message = message
        self.timestamp = timestamp
        self.location = location


class TestableAlgorithm(QCAlgorithm):
    """
    可测试的算法基类

    特性:
    1. 内置断言方法（assert_equal, assert_true, assert_greater 等）
    2. 自动收集断言结果
    3. 测试检查点机制
    4. 测试阶段管理
    5. 双重统计输出

    使用示例:
        class MyTest(TestableAlgorithm):
            def on_order_event(self, order_event):
                if order_event.status == OrderStatus.Filled:
                    self.assert_equal(order_event.fill_quantity, 100)
                    self.assert_true(self.portfolio.invested)
    """

    def __init__(self):
        super().__init__()
        self._assertions: List[AssertionResult] = []
        self._test_checkpoints: Dict[str, Any] = {}
        self._current_test_phase = None

    # ========== 断言方法 ==========

    def assert_equal(self, actual, expected, msg: str = "") -> bool:
        """
        断言相等

        Args:
            actual: 实际值
            expected: 期望值
            msg: 附加消息

        Returns:
            bool: 断言是否通过
        """
        passed = actual == expected
        full_msg = f"{msg} | Expected: {expected}, Actual: {actual}" if msg else f"Expected: {expected}, Actual: {actual}"
        self._record_assertion("assert_equal", passed, full_msg)
        return passed

    def assert_true(self, condition, msg: str = "") -> bool:
        """
        断言为真

        Args:
            condition: 条件表达式
            msg: 附加消息

        Returns:
            bool: 断言是否通过
        """
        passed = bool(condition)
        full_msg = f"{msg} | Condition: {condition}" if msg else f"Condition: {condition}"
        self._record_assertion("assert_true", passed, full_msg)
        return passed

    def assert_false(self, condition, msg: str = "") -> bool:
        """
        断言为假

        Args:
            condition: 条件表达式
            msg: 附加消息

        Returns:
            bool: 断言是否通过
        """
        passed = not bool(condition)
        full_msg = f"{msg} | Condition should be False: {condition}" if msg else f"Condition should be False: {condition}"
        self._record_assertion("assert_false", passed, full_msg)
        return passed

    def assert_greater(self, value, threshold, msg: str = "") -> bool:
        """
        断言大于

        Args:
            value: 值
            threshold: 阈值
            msg: 附加消息

        Returns:
            bool: 断言是否通过
        """
        passed = value > threshold
        full_msg = f"{msg} | Value: {value}, Threshold: {threshold}" if msg else f"Value: {value} should be > {threshold}"
        self._record_assertion("assert_greater", passed, full_msg)
        return passed

    def assert_less(self, value, threshold, msg: str = "") -> bool:
        """
        断言小于

        Args:
            value: 值
            threshold: 阈值
            msg: 附加消息

        Returns:
            bool: 断言是否通过
        """
        passed = value < threshold
        full_msg = f"{msg} | Value: {value}, Threshold: {threshold}" if msg else f"Value: {value} should be < {threshold}"
        self._record_assertion("assert_less", passed, full_msg)
        return passed

    def assert_greater_equal(self, value, threshold, msg: str = "") -> bool:
        """断言大于等于"""
        passed = value >= threshold
        full_msg = f"{msg} | Value: {value}, Threshold: {threshold}" if msg else f"Value: {value} should be >= {threshold}"
        self._record_assertion("assert_greater_equal", passed, full_msg)
        return passed

    def assert_not_none(self, value, msg: str = "") -> bool:
        """断言不为 None"""
        passed = value is not None
        full_msg = f"{msg} | Value should not be None" if msg else "Value should not be None"
        self._record_assertion("assert_not_none", passed, full_msg)
        return passed

    # ========== 测试检查点 ==========

    def checkpoint(self, name: str, **kwargs):
        """
        创建测试检查点 - 记录特定时刻的状态

        Args:
            name: 检查点名称
            **kwargs: 要记录的状态数据

        Example:
            self.checkpoint('order_filled',
                          quantity=position.quantity,
                          price=order_event.fill_price)
        """
        self._test_checkpoints[name] = {
            'timestamp': self.time,
            'data': kwargs
        }
        self.debug(f"📍 Checkpoint '{name}' created at {self.time}")

    def verify_checkpoint(self, name: str, assertions: Dict[str, Any]):
        """
        验证检查点数据

        Args:
            name: 检查点名称
            assertions: 验证条件字典

        Example:
            self.verify_checkpoint('order_filled', {
                'quantity': 100,
                'price': lambda p: 140 < p < 160
            })
        """
        if name not in self._test_checkpoints:
            self.assert_true(False, f"Checkpoint '{name}' not found")
            return

        checkpoint = self._test_checkpoints[name]
        self.debug(f"🔍 Verifying checkpoint '{name}'")

        for key, expected in assertions.items():
            actual = checkpoint['data'].get(key)

            if callable(expected):
                # 支持 lambda 验证
                try:
                    passed = expected(actual)
                    self._record_assertion(
                        f"checkpoint:{name}.{key}",
                        passed,
                        f"Custom validation {'passed' if passed else 'failed'} for {key}={actual}"
                    )
                except Exception as e:
                    self._record_assertion(
                        f"checkpoint:{name}.{key}",
                        False,
                        f"Validation error: {str(e)}"
                    )
            else:
                self.assert_equal(actual, expected, f"checkpoint:{name}.{key}")

    # ========== 测试阶段标记 ==========

    def begin_test_phase(self, phase_name: str):
        """
        标记测试阶段开始

        Args:
            phase_name: 阶段名称
        """
        self._current_test_phase = phase_name
        self.debug(f"{'='*50}")
        self.debug(f"🧪 TEST PHASE: {phase_name}")
        self.debug(f"{'='*50}")

    def end_test_phase(self):
        """标记测试阶段结束并输出该阶段统计"""
        if self._current_test_phase:
            phase_assertions = [a for a in self._assertions
                               if self._current_test_phase in a.location]
            passed = sum(1 for a in phase_assertions if a.passed)
            total = len(phase_assertions)

            # self.debug(f"📊 Phase '{self._current_test_phase}' Results:")
            # self.debug(f"   Passed: {passed}/{total}")
            if total > 0 and passed < total:
                self.debug(f"   ⚠️ {total - passed} assertion(s) failed")

            self._current_test_phase = None

    # ========== 内部方法 ==========

    def _record_assertion(self, name: str, passed: bool, message: str):
        """
        记录断言结果

        Args:
            name: 断言名称
            passed: 是否通过
            message: 消息
        """
        # 获取调用位置
        frame = inspect.currentframe().f_back.f_back
        location = f"{frame.f_code.co_name}:{frame.f_lineno}"

        # 添加测试阶段前缀
        if self._current_test_phase:
            location = f"{self._current_test_phase}::{location}"

        result = AssertionResult(
            name=name,
            passed=passed,
            message=message,
            timestamp=self.time,
            location=location
        )
        self._assertions.append(result)

        # 实时输出
        status = "✅ PASS" if passed else "❌ FAIL"
        self.debug(f"{status} | {name} | {message}")

    def _get_test_summary(self) -> Dict:
        """
        生成测试摘要

        Returns:
            dict: 测试统计信息
        """
        passed = sum(1 for a in self._assertions if a.passed)
        failed = sum(1 for a in self._assertions if not a.passed)

        return {
            'total_assertions': len(self._assertions),
            'passed': passed,
            'failed': failed,
            'pass_rate': passed / len(self._assertions) if self._assertions else 0,
            'checkpoints': list(self._test_checkpoints.keys()),
            'assertions': [
                {
                    'name': a.name,
                    'passed': a.passed,
                    'message': a.message,
                    'timestamp': str(a.timestamp),
                    'location': a.location
                }
                for a in self._assertions
            ]
        }

    # ========== 重写 LEAN 回调 ==========

    def on_end_of_algorithm(self):
        """算法结束 - 输出测试统计"""
        summary = self._get_test_summary()

        self.debug("\n" + "="*60)
        self.debug("📝 UNIT TEST RESULTS")
        self.debug("="*60)
        self.debug(f"Total Assertions: {summary['total_assertions']}")
        self.debug(f"Passed: {summary['passed']} ✅")
        self.debug(f"Failed: {summary['failed']} ❌")
        self.debug(f"Pass Rate: {summary['pass_rate']*100:.1f}%")
        self.debug(f"Checkpoints: {len(summary['checkpoints'])}")

        if summary['failed'] > 0:
            self.debug("\n❌ FAILED ASSERTIONS:")
            for a in summary['assertions']:
                if not a['passed']:
                    self.debug(f"  - [{a['location']}] {a['message']}")
        else:
            self.debug("\n✅ All tests passed!")

        # 输出 JSON 结果（供外部工具解析）
        json_output = json.dumps(summary, indent=2)
        self.debug(f"\n__TEST_RESULTS_JSON__")
        self.debug(json_output)
        self.debug(f"__END_TEST_RESULTS__")

        self.debug("="*60)
