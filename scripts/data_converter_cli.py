"""
LEAN Data Converter - Interactive CLI
统一的交互式数据转换入口

支持的数据源:
- Gate.io: 加密货币深度数据 (Depth) + 交易数据 (Trade)
- Nasdaq: 股票交易和报价数据 (Trade + Quote)
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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

    DEFAULT_DEPTH_INPUT = "raw_data/gate_orderbook_tick/202509"
    DEFAULT_TRADE_INPUT = "raw_data/gate_trade_tick"
    DEFAULT_OUTPUT = "Data/crypto/gate/tick"  # Fixed: Changed from kraken to gate

    SYMBOLS = {
        '1': ('AAPLX_USDT', 'AAPLXUSDT'),  # Fixed: Added 'T' suffix
        '2': ('TSLAX_USDT', 'TSLAXUSDT'),  # Fixed: Added 'T' suffix
        '3': ('ALL', 'ALL')
    }

    def __init__(self):
        self.depth_input = None
        self.trade_input = None
        self.output_dir = None
        self.data_type = None
        self.symbols = []
        self.market_type = 'crypto'  # Default to crypto (spot)

    def detect_market_type(self, base_dir: str) -> str:
        """
        Auto-detect market type from directory structure

        Checks for crypto/ and cryptofuture/ subdirectories.
        If both exist, asks user to select.
        If neither exist, assumes legacy flat structure (crypto).

        Args:
            base_dir: Base directory to check (e.g., 'raw_data/gate_orderbook_tick')

        Returns:
            'crypto' or 'cryptofuture'
        """
        from pathlib import Path

        base_path = Path(base_dir)
        has_crypto = (base_path / 'crypto').exists()
        has_cryptofuture = (base_path / 'cryptofuture').exists()

        if has_crypto and has_cryptofuture:
            # Both exist - ask user
            print_info("\n检测到多种市场类型:")
            print("  [1] crypto (现货)")
            print("  [2] cryptofuture (USDT永续合约)")
            choice = get_choice("请选择市场类型", ['1', '2'], '1')
            return 'crypto' if choice == '1' else 'cryptofuture'
        elif has_crypto:
            print_info(f"检测到市场类型: crypto (现货)")
            return 'crypto'
        elif has_cryptofuture:
            print_info(f"检测到市场类型: cryptofuture (USDT永续合约)")
            return 'cryptofuture'
        else:
            # Neither exists - legacy flat structure or empty directory
            print_info("未检测到市场类型子目录，假定为 crypto (现货)")
            return 'crypto'

    def configure(self) -> bool:
        """
        配置 Gate.io 转换参数

        Returns:
            True 表示配置成功
        """
        print_header("Gate.io 数据转换配置")

        # 选择数据类型
        print_info("\n数据类型:")
        print("  [1] Depth + Trade (深度 + 交易)")
        print("  [2] Depth only (仅深度)")
        print("  [3] Trade only (仅交易)")

        type_choice = get_choice("请选择", ['1', '2', '3'], '1')

        if type_choice == '1':
            self.data_type = 'all'
        elif type_choice == '2':
            self.data_type = 'depth'
        else:
            self.data_type = 'trade'

        # Depth 输入目录
        if self.data_type in ['depth', 'all']:
            while True:
                base_depth_input = get_input("Depth 数据路径", "raw_data/gate_orderbook_tick")

                # Detect market type from directory structure
                self.market_type = self.detect_market_type(base_depth_input)

                # Build full path with market type and month subdirectories
                # For new structure: raw_data/gate_orderbook_tick/crypto/202509
                # For legacy: raw_data/gate_orderbook_tick/202509
                from pathlib import Path
                base_path = Path(base_depth_input)

                # Check if new structure exists
                if (base_path / self.market_type).exists():
                    # Find month subdirectories
                    month_dirs = sorted([d for d in (base_path / self.market_type).iterdir() if d.is_dir()])
                    if month_dirs:
                        # Use most recent month directory
                        self.depth_input = str(month_dirs[-1])
                    else:
                        self.depth_input = str(base_path / self.market_type)
                else:
                    # Legacy flat structure
                    self.depth_input = base_depth_input

                file_count = scan_directory(self.depth_input, "*.csv.gz")
                if file_count > 0:
                    print_info(f"找到 {file_count} 个 Depth 数据文件")
                    break
                else:
                    print_warning(f"未找到 Depth 数据文件 (*.csv.gz)")
                    if not confirm("继续使用此路径?", False):
                        continue
                    break

        # Trade 输入目录
        if self.data_type in ['trade', 'all']:
            while True:
                # Auto-suggest trade path based on depth path structure
                if hasattr(self, 'depth_input') and self.depth_input:
                    # If depth input is like "raw_data/gate_orderbook_tick/crypto/202510"
                    # Suggest "raw_data/gate_trade_tick/crypto/202510"
                    from pathlib import Path
                    depth_path = Path(self.depth_input)

                    # Try to extract market_type and month from depth path
                    if len(depth_path.parts) >= 2:
                        # Get last two parts (e.g., crypto/202510)
                        market_and_month = '/'.join(depth_path.parts[-2:])
                        default_trade = f"raw_data/gate_trade_tick/{market_and_month}"
                    else:
                        default_trade = self.DEFAULT_TRADE_INPUT
                else:
                    default_trade = self.DEFAULT_TRADE_INPUT

                self.trade_input = get_input("Trade 数据路径", default_trade)

                # Detect market type from trade path if not already detected from depth
                if self.data_type == 'trade':  # Trade-only mode
                    # Extract market type from path if present
                    from pathlib import Path
                    trade_path = Path(self.trade_input)

                    # Check if path contains 'crypto' or 'cryptofuture'
                    if 'cryptofuture' in trade_path.parts:
                        self.market_type = 'cryptofuture'
                        print_info("检测到市场类型: cryptofuture (USDT永续合约)")
                    elif 'crypto' in trade_path.parts:
                        self.market_type = 'crypto'
                        print_info("检测到市场类型: crypto (现货)")
                    else:
                        # Fallback: detect from base directory
                        self.market_type = self.detect_market_type(str(trade_path.parent.parent))

                file_count = scan_directory(self.trade_input, "*.csv.gz")
                if file_count > 0:
                    print_info(f"找到 {file_count} 个 Trade 数据文件")
                    break
                else:
                    print_warning(f"未找到 Trade 数据文件 (*.csv.gz)")
                    if not confirm("继续使用此路径?", False):
                        continue
                    break

        # 输出目录 - use market type in default path
        default_output = f"Data/{self.market_type}/gate/tick"
        self.output_dir = get_input("输出路径", default_output)
        if not validate_directory(self.output_dir, create_if_missing=True):
            return False

        # 选择符号 - detect from actual files
        print_info("\n检测符号...")
        from pathlib import Path
        import re

        detected_symbols = set()

        # Detect from depth files if available
        if self.data_type in ['depth', 'all'] and self.depth_input:
            depth_path = Path(self.depth_input)
            for file in depth_path.glob("*.csv.gz"):
                # Parse filename: SYMBOL-YYYYMMDDHH.csv.gz
                match = re.match(r"(.+)-\d{10}\.csv\.gz", file.name)
                if match:
                    detected_symbols.add(match.group(1))

        # Detect from trade files if available
        if self.data_type in ['trade', 'all'] and self.trade_input:
            trade_path = Path(self.trade_input)
            for file in trade_path.glob("*.csv.gz"):
                # Parse filename: SYMBOL-YYYYMM.csv.gz
                match = re.match(r"(.+)-\d{6}\.csv\.gz", file.name)
                if match:
                    detected_symbols.add(match.group(1))

        if detected_symbols:
            # Build dynamic symbol list
            from converters.gateio_trade_convertor import SYMBOL_MAP

            symbol_choices = {}
            idx = 1
            print_info("\n检测到的符号:")
            for gate_symbol in sorted(detected_symbols):
                # Get LEAN symbol from converter's mapping, or construct default
                if gate_symbol in SYMBOL_MAP:
                    lean_symbol = SYMBOL_MAP[gate_symbol]
                else:
                    # Default: remove underscore (e.g., BTC_USDT -> BTCUSDT)
                    lean_symbol = gate_symbol.replace('_', '')

                symbol_choices[str(idx)] = (gate_symbol, lean_symbol)
                print(f"  [{idx}] {gate_symbol} → {lean_symbol}")
                idx += 1

            # Add "ALL" option
            symbol_choices[str(idx)] = ('ALL', 'ALL')
            print(f"  [{idx}] ALL → 全部")

            # Support multi-select: user can enter "1,2,3" or "1 2 3" or just "1"
            print_info("\n提示: 可以选择多个符号，用逗号或空格分隔（例如: 1,2 或 1 2 3）")
            user_input = get_input("请选择", str(idx)).strip()

            # Parse input - split by comma or space
            import re
            choices = re.split(r'[,\s]+', user_input)
            choices = [c.strip() for c in choices if c.strip()]

            # Validate and collect selected symbols
            selected_symbols = []
            for choice in choices:
                if choice not in symbol_choices:
                    print_warning(f"无效选择: {choice}，已忽略")
                    continue

                gate_symbol, lean_symbol = symbol_choices[choice]
                if gate_symbol == 'ALL':
                    # If "ALL" is selected, use all symbols
                    selected_symbols = [(s, l) for s, l in symbol_choices.values() if s != 'ALL']
                    break
                else:
                    selected_symbols.append((gate_symbol, lean_symbol))

            if not selected_symbols:
                # Default to ALL if nothing valid selected
                print_warning("未选择有效符号，使用全部符号")
                selected_symbols = [(s, l) for s, l in symbol_choices.values() if s != 'ALL']

            self.symbols = selected_symbols
        else:
            # Fallback to hardcoded symbols if no files detected
            print_warning("未检测到符号，使用默认符号列表")
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

        if self.depth_input:
            print(f"  Depth 输入: {Colors.CYAN}{self.depth_input}{Colors.ENDC}")
        if self.trade_input:
            print(f"  Trade 输入: {Colors.CYAN}{self.trade_input}{Colors.ENDC}")

        print(f"  输出路径: {Colors.CYAN}{self.output_dir}{Colors.ENDC}")

        type_str = {
            'all': 'Depth + Trade',
            'depth': 'Depth only',
            'trade': 'Trade only'
        }[self.data_type]
        print(f"  数据格式: {Colors.CYAN}{type_str}{Colors.ENDC}")
        print(f"  目标符号: {Colors.CYAN}{', '.join([s[1] for s in self.symbols])}{Colors.ENDC}")

    def execute(self) -> bool:
        """
        执行转换

        Returns:
            True 表示转换成功
        """
        try:
            # Import converters
            from converters import gateio_depth_convertor, gateio_trade_convertor

            print_header("开始转换 Gate.io 数据")

            for gate_symbol, lean_symbol in self.symbols:
                print_info(f"\n处理符号: {gate_symbol} → {lean_symbol}")

                # Convert Depth data
                if self.data_type in ['depth', 'all']:
                    print_info(f"  转换 Depth 数据...")
                    gateio_depth_convertor.main_convert(
                        input_dir=self.depth_input,
                        output_dir=self.output_dir,
                        symbol=gate_symbol if gate_symbol != 'ALL' else None,
                        market_type=self.market_type
                    )

                # Convert Trade data
                if self.data_type in ['trade', 'all']:
                    print_info(f"  转换 Trade 数据...")
                    gateio_trade_convertor.main_convert(
                        input_dir=self.trade_input,
                        output_dir=self.output_dir,
                        symbol=gate_symbol if gate_symbol != 'ALL' else None,
                        market_type=self.market_type
                    )

            print_success("\n✓ Gate.io 数据转换完成!")
            return True

        except ImportError as e:
            print_error(f"无法导入转换器: {e}")
            print_info("请确保转换器在 scripts/converters/ 目录下")
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
            from converters import nasdaq_data_convertor

            print_header("开始转换 Nasdaq 数据")

            # 调用转换器
            nasdaq_data_convertor.main_convert(
                trade_dir=self.trade_dir,
                quote_dir=self.quote_dir,
                output_dir=self.output_dir,
                data_type=self.data_type,
                symbol=self.symbol
            )

            print_success("\n✓ Nasdaq 数据转换完成!")
            return True

        except ImportError as e:
            print_error(f"无法导入转换器: {e}")
            print_info("请确保转换器在 scripts/converters/ 目录下")
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
    print("  • Gate.io: 加密货币深度 + 交易数据")
    print("  • Nasdaq: 股票交易和报价数据")
    print()

    while True:
        # 选择数据源
        print_info("\n步骤 1: 选择数据源")
        print("  [1] Gate.io (加密货币深度和交易数据)")
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
