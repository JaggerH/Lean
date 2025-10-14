"""
LEAN Data Converter - Interactive CLI
统一的交互式数据转换入口

支持的数据源:
- Gate.io: 加密货币深度数据 (Depth)
- Nasdaq: 股票交易和报价数据 (Trade + Quote)
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ANSI 颜色代码
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_header(text: str):
    """打印标题"""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{text}{Colors.ENDC}")
    print("=" * len(text))


def print_success(text: str):
    """打印成功消息"""
    print(f"{Colors.GREEN}✓ {text}{Colors.ENDC}")


def print_error(text: str):
    """打印错误消息"""
    print(f"{Colors.RED}✗ {text}{Colors.ENDC}")


def print_warning(text: str):
    """打印警告消息"""
    print(f"{Colors.YELLOW}⚠ {text}{Colors.ENDC}")


def print_info(text: str):
    """打印信息"""
    print(f"{Colors.BLUE}ℹ {text}{Colors.ENDC}")


def get_input(prompt: str, default: str = None) -> str:
    """
    获取用户输入，支持默认值

    Args:
        prompt: 提示文本
        default: 默认值

    Returns:
        用户输入或默认值
    """
    if default:
        prompt_text = f"{prompt} [{Colors.CYAN}{default}{Colors.ENDC}]: "
    else:
        prompt_text = f"{prompt}: "

    user_input = input(prompt_text).strip()
    return user_input if user_input else default


def get_choice(prompt: str, choices: List[str], default: str = None) -> str:
    """
    获取用户选择

    Args:
        prompt: 提示文本
        choices: 有效选项列表
        default: 默认选项

    Returns:
        用户选择
    """
    while True:
        choice = get_input(prompt, default)
        if choice in choices:
            return choice
        print_error(f"无效选择，请输入 {', '.join(choices)} 之一")


def confirm(prompt: str = "确认继续?", default: bool = True) -> bool:
    """
    获取用户确认

    Args:
        prompt: 提示文本
        default: 默认值

    Returns:
        True 表示确认，False 表示取消
    """
    default_str = "Y/n" if default else "y/N"
    choice = get_input(f"{prompt} [{default_str}]", "y" if default else "n").lower()

    if choice in ['y', 'yes']:
        return True
    elif choice in ['n', 'no']:
        return False
    else:
        return default


def validate_directory(path: str, create_if_missing: bool = False) -> bool:
    """
    验证目录是否存在

    Args:
        path: 目录路径
        create_if_missing: 如果不存在是否创建

    Returns:
        True 表示目录有效或已创建
    """
    path_obj = Path(path)

    if path_obj.exists():
        if not path_obj.is_dir():
            print_error(f"路径存在但不是目录: {path}")
            return False
        return True
    else:
        if create_if_missing:
            try:
                path_obj.mkdir(parents=True, exist_ok=True)
                print_success(f"创建目录: {path}")
                return True
            except Exception as e:
                print_error(f"无法创建目录 {path}: {e}")
                return False
        else:
            print_error(f"目录不存在: {path}")
            return False


def scan_directory(path: str, pattern: str = "*") -> int:
    """
    扫描目录中的文件数量

    Args:
        path: 目录路径
        pattern: 文件匹配模式

    Returns:
        文件数量
    """
    path_obj = Path(path)
    if not path_obj.exists():
        return 0

    files = list(path_obj.glob(pattern))
    return len(files)


class GateIOConverter:
    """Gate.io 数据转换器"""

    DEFAULT_INPUT = "raw_data/gate_tick/202509"
    DEFAULT_OUTPUT = "Data/crypto/kraken/tick"

    SYMBOLS = {
        '1': ('AAPLX_USDT', 'AAPLXUSD'),
        '2': ('TSLAX_USDT', 'TSLAXUSD'),
        '3': ('ALL', 'ALL')
    }

    def __init__(self):
        self.input_dir = None
        self.output_dir = None
        self.symbols = []

    def configure(self) -> bool:
        """
        配置 Gate.io 转换参数

        Returns:
            True 表示配置成功
        """
        print_header("Gate.io 深度数据转换配置")

        # 输入目录
        while True:
            self.input_dir = get_input("输入数据路径", self.DEFAULT_INPUT)

            file_count = scan_directory(self.input_dir, "*.csv.gz")
            if file_count > 0:
                print_info(f"找到 {file_count} 个数据文件")
                break
            else:
                print_warning(f"未找到数据文件 (*.csv.gz)")
                if not confirm("继续使用此路径?", False):
                    continue
                break

        # 输出目录
        self.output_dir = get_input("输出路径", self.DEFAULT_OUTPUT)
        if not validate_directory(self.output_dir, create_if_missing=True):
            return False

        # 选择符号
        print_info("\n目标符号:")
        for key, (gate_symbol, lean_symbol) in self.SYMBOLS.items():
            print(f"  [{key}] {gate_symbol} → {lean_symbol}")

        choice = get_choice("请选择", list(self.SYMBOLS.keys()), '3')

        gate_symbol, lean_symbol = self.SYMBOLS[choice]
        if gate_symbol == 'ALL':
            self.symbols = [self.SYMBOLS['1'], self.SYMBOLS['2']]
        else:
            self.symbols = [(gate_symbol, lean_symbol)]

        return True

    def show_summary(self):
        """显示配置摘要"""
        print_header("Gate.io 转换配置摘要")
        print(f"  数据源: {Colors.CYAN}Gate.io{Colors.ENDC}")
        print(f"  输入路径: {Colors.CYAN}{self.input_dir}{Colors.ENDC}")
        print(f"  输出路径: {Colors.CYAN}{self.output_dir}{Colors.ENDC}")
        print(f"  数据格式: {Colors.CYAN}Depth (深度数据){Colors.ENDC}")
        print(f"  目标符号: {Colors.CYAN}{', '.join([s[1] for s in self.symbols])}{Colors.ENDC}")

    def execute(self) -> bool:
        """
        执行转换

        Returns:
            True 表示转换成功
        """
        try:
            import gateio_depth_convertor as gate_converter

            print_header("开始转换 Gate.io 数据")

            for gate_symbol, lean_symbol in self.symbols:
                print_info(f"\n处理符号: {gate_symbol} → {lean_symbol}")

                # 调用转换器
                gate_converter.main_convert(
                    input_dir=self.input_dir,
                    output_dir=self.output_dir,
                    symbol=gate_symbol if gate_symbol != 'ALL' else None
                )

            print_success("\n✓ Gate.io 数据转换完成!")
            return True

        except ImportError as e:
            print_error(f"无法导入 gateio_depth_convertor: {e}")
            print_info("请确保 gateio_depth_convertor.py 在同一目录下")
            return False
        except Exception as e:
            print_error(f"转换过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False


class NasdaqConverter:
    """Nasdaq 数据转换器"""

    DEFAULT_TRADE_DIR = "raw_data/us_trade_tick"
    DEFAULT_QUOTE_DIR = "raw_data/us_mbp_tick"
    DEFAULT_OUTPUT = "Data/equity/usa/tick"

    def __init__(self):
        self.trade_dir = None
        self.quote_dir = None
        self.output_dir = None
        self.data_type = None
        self.symbol = None

    def configure(self) -> bool:
        """
        配置 Nasdaq 转换参数

        Returns:
            True 表示配置成功
        """
        print_header("Nasdaq 数据转换配置")

        # 选择数据格式
        print_info("\n目标格式:")
        print("  [1] Quote + Trade (报价 + 交易)")
        print("  [2] Quote only (仅报价)")
        print("  [3] Trade only (仅交易)")

        format_choice = get_choice("请选择", ['1', '2', '3'], '1')

        if format_choice == '1':
            self.data_type = 'all'
        elif format_choice == '2':
            self.data_type = 'quote'
        else:
            self.data_type = 'trade'

        # Trade 数据路径
        if self.data_type in ['trade', 'all']:
            while True:
                self.trade_dir = get_input("Trade 数据路径", self.DEFAULT_TRADE_DIR)

                file_count = scan_directory(self.trade_dir, "*.trades.csv.zst")
                if file_count > 0:
                    print_info(f"找到 {file_count} 个 Trade 数据文件")
                    break
                else:
                    print_warning(f"未找到 Trade 数据文件 (*.trades.csv.zst)")
                    if not confirm("继续使用此路径?", False):
                        continue
                    break

        # Quote 数据路径
        if self.data_type in ['quote', 'all']:
            while True:
                self.quote_dir = get_input("Quote 数据路径", self.DEFAULT_QUOTE_DIR)

                file_count = scan_directory(self.quote_dir, "*.mbp-1.*.csv.zst")
                if file_count > 0:
                    print_info(f"找到 {file_count} 个 Quote 数据文件")
                    break
                else:
                    print_warning(f"未找到 Quote 数据文件 (*.mbp-1.*.csv.zst)")
                    if not confirm("继续使用此路径?", False):
                        continue
                    break

        # 输出目录
        self.output_dir = get_input("输出路径", self.DEFAULT_OUTPUT)
        if not validate_directory(self.output_dir, create_if_missing=True):
            return False

        # 目标符号
        self.symbol = get_input("目标符号 (如 AAPL, TSLA，或 all 表示全部)", "all")

        return True

    def show_summary(self):
        """显示配置摘要"""
        print_header("Nasdaq 转换配置摘要")
        print(f"  数据源: {Colors.CYAN}Nasdaq{Colors.ENDC}")

        if self.trade_dir:
            print(f"  Trade 输入: {Colors.CYAN}{self.trade_dir}{Colors.ENDC}")
        if self.quote_dir:
            print(f"  Quote 输入: {Colors.CYAN}{self.quote_dir}{Colors.ENDC}")

        print(f"  输出路径: {Colors.CYAN}{self.output_dir}{Colors.ENDC}")

        format_str = {
            'all': 'Quote + Trade',
            'quote': 'Quote only',
            'trade': 'Trade only'
        }[self.data_type]
        print(f"  数据格式: {Colors.CYAN}{format_str}{Colors.ENDC}")
        print(f"  目标符号: {Colors.CYAN}{self.symbol.upper()}{Colors.ENDC}")

    def execute(self) -> bool:
        """
        执行转换

        Returns:
            True 表示转换成功
        """
        try:
            import nasdaq_data_convertor as nasdaq_converter

            print_header("开始转换 Nasdaq 数据")

            # 调用转换器
            nasdaq_converter.main_convert(
                trade_dir=self.trade_dir,
                quote_dir=self.quote_dir,
                output_dir=self.output_dir,
                data_type=self.data_type,
                symbol=self.symbol
            )

            print_success("\n✓ Nasdaq 数据转换完成!")
            return True

        except ImportError as e:
            print_error(f"无法导入 nasdaq_data_convertor: {e}")
            print_info("请确保 nasdaq_data_convertor.py 在同一目录下")
            return False
        except Exception as e:
            print_error(f"转换过程出错: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """主函数"""
    # 显示欢迎信息
    print_header("欢迎使用 LEAN 数据转换工具")
    print(f"{Colors.BLUE}支持的数据源:{Colors.ENDC}")
    print("  • Gate.io: 加密货币深度数据")
    print("  • Nasdaq: 股票交易和报价数据")
    print()

    while True:
        # 选择数据源
        print_info("\n步骤 1: 选择数据源")
        print("  [1] Gate.io (加密货币深度数据)")
        print("  [2] Nasdaq (股票报价和交易数据)")
        print("  [0] 退出")

        choice = get_choice("请选择 (0-2)", ['0', '1', '2'])

        if choice == '0':
            print_info("感谢使用，再见!")
            break

        # 创建转换器
        if choice == '1':
            converter = GateIOConverter()
        else:
            converter = NasdaqConverter()

        # 配置转换器
        if not converter.configure():
            print_error("配置失败，请重试")
            continue

        # 显示摘要
        print()
        converter.show_summary()

        # 确认执行
        print()
        if not confirm("确认开始转换?"):
            print_warning("已取消转换")
            continue

        # 执行转换
        success = converter.execute()

        if success:
            print_success("\n✓ 所有转换任务完成!")
        else:
            print_error("\n✗ 转换过程中出现错误")

        # 询问是否继续
        print()
        if not confirm("是否继续转换其他数据?"):
            print_info("感谢使用，再见!")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print_warning("\n\n用户中断操作")
        sys.exit(0)
    except Exception as e:
        print_error(f"\n程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
