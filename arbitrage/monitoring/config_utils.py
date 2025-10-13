"""
配置工具 - 从docker-compose.yml读取配置
"""
import re
import socket
from pathlib import Path


def is_port_in_use(port: int, host: str = '127.0.0.1') -> bool:
    """
    检查端口是否被占用

    使用双重检测：
    1. 尝试连接端口（检测是否有服务在监听）
    2. 尝试bind端口（检测是否能独占使用）

    Args:
        port: 端口号
        host: 主机地址

    Returns:
        bool: True=端口被占用, False=端口可用
    """
    # 方法1: 尝试连接端口（检测是否有服务正在监听）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)  # 100ms超时
        try:
            # 如果能连接成功，说明有服务在监听
            result = s.connect_ex((host, port))
            if result == 0:
                return True  # 端口被占用（有服务监听）
        except:
            pass

    # 方法2: 尝试bind到0.0.0.0（检测是否能独占端口）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False  # 端口可用
        except OSError:
            return True  # 端口被占用


def find_available_port(start_port: int, max_attempts: int = 10, host: str = '127.0.0.1') -> int:
    """
    从start_port开始查找可用端口

    Args:
        start_port: 起始端口号
        max_attempts: 最大尝试次数
        host: 主机地址（用于检测）

    Returns:
        int: 可用端口号

    Raises:
        RuntimeError: 找不到可用端口
    """
    for i in range(max_attempts):
        port = start_port + i
        # 使用指定的host检测端口
        if not is_port_in_use(port, host):
            if i > 0:
                print(f"[OK] 端口 {start_port} 被占用，自动切换到端口 {port}")
            return port

    raise RuntimeError(f"无法找到可用端口 (尝试范围: {start_port}-{start_port + max_attempts - 1})")


def get_redis_port_from_compose() -> int:
    """
    从arbitrage/docker-compose.yml读取Redis对外暴露的端口

    Returns:
        int: Redis端口号，默认6379

    docker-compose.yml格式示例:
        ports:
          - "6380:6379"  # 宿主机端口:容器端口
    """
    # 定位docker-compose.yml文件
    compose_file = Path(__file__).parent.parent / 'docker-compose.yml'

    if not compose_file.exists():
        print(f"[WARN] docker-compose.yml未找到: {compose_file}")
        return 6379  # 默认端口

    try:
        # 读取文件内容
        content = compose_file.read_text(encoding='utf-8')

        # 查找Redis服务的端口映射
        # 匹配格式: - "6380:6379" 或 - 6380:6379
        pattern = r'ports:\s*\n\s*-\s*["\']?(\d+):6379["\']?'
        match = re.search(pattern, content)

        if match:
            port = int(match.group(1))
            print(f"[OK] 从docker-compose.yml读取Redis端口: {port}")
            return port
        else:
            print("[WARN] 未找到Redis端口配置,使用默认端口6379")
            return 6379

    except Exception as e:
        print(f"[WARN] 读取docker-compose.yml失败: {e}")
        return 6379  # 默认端口
