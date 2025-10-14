"""
监控服务启动器

功能:
- 使用Docker Compose启动Redis
- 启动监控服务器
- 打开浏览器监控界面

使用:
    python start_monitor.py

注意: 交易程序需要手动启动
"""
import subprocess
import time
import sys
import os
import webbrowser
from pathlib import Path


class MonitorLauncher:
    """监控系统启动器"""

    def __init__(self):
        self.root = Path(__file__).parent
        self.monitor_proc = None
        self.monitor_port = None  # 将在启动时自动查找可用端口

    def check_docker(self):
        """检查Docker是否可用"""
        print("检查Docker...")
        try:
            result = subprocess.run(
                ['docker', 'compose', 'version'],
                capture_output=True,
                check=True,
                timeout=10
            )
            print("✓ Docker Compose可用")
            return True
        except FileNotFoundError:
            print("❌ Docker未安装")
            print("   请先安装Docker Desktop: https://docs.docker.com/get-docker/")
            return False
        except subprocess.TimeoutExpired:
            print("❌ Docker命令超时")
            return False
        except subprocess.CalledProcessError as e:
            print(f"❌ Docker Compose不可用: {e}")
            return False
        except Exception as e:
            print(f"❌ Docker检查失败: {e}")
            return False

    def start_redis(self):
        """启动Redis (Docker Compose)"""
        print("\n[1/3] 启动Redis (Docker)...")

        # 检查Redis是否已运行
        try:
            result = subprocess.run(
                ['docker', 'compose', 'ps', '-q', 'redis'],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.stdout.strip():
                # 检查容器是否真的在运行
                check_result = subprocess.run(
                    ['docker', 'exec', 'trading_redis', 'redis-cli', 'ping'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if check_result.returncode == 0 and 'PONG' in check_result.stdout:
                    print("✓ Redis已在运行")
                    return True
        except Exception as e:
            print(f"   检查Redis状态失败: {e}")

        # 启动Redis
        print("   启动Redis容器...")
        try:
            subprocess.run(
                ['docker', 'compose', 'up', '-d', 'redis'],
                cwd=self.root,
                check=True,
                timeout=60
            )
        except Exception as e:
            raise Exception(f"启动Redis失败: {e}")

        # 等待Redis就绪
        print("   等待Redis就绪...", end='', flush=True)
        for i in range(15):
            try:
                result = subprocess.run(
                    ['docker', 'exec', 'trading_redis', 'redis-cli', 'ping'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0 and 'PONG' in result.stdout:
                    print(" ✓")
                    print("✓ Redis启动完成")
                    return True
            except:
                pass

            print('.', end='', flush=True)
            time.sleep(1)

        raise Exception("Redis启动超时")

    def install_dependencies(self):
        """安装Python依赖"""
        req_file = self.root / 'monitoring' / 'requirements.txt'
        if not req_file.exists():
            print("⚠️ requirements.txt不存在,跳过依赖安装")
            return

        print("   检查Python依赖...")
        try:
            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '-q', '-r', str(req_file)],
                check=True,
                timeout=120
            )
            print("✓ Python依赖已就绪")
        except Exception as e:
            print(f"⚠️ 依赖安装失败: {e}")
            print("   请手动运行: pip install -r monitoring/requirements.txt")

    def start_monitor(self):
        """启动监控服务器"""
        print("\n[2/3] 启动监控服务器...")

        # self.install_dependencies()  # 注释掉自动安装依赖

        monitor_dir = self.root / 'monitoring'
        if not monitor_dir.exists():
            raise Exception(f"监控目录不存在: {monitor_dir}")

        # 查找可用端口 (从8000开始)
        print("   检测可用端口...", end='', flush=True)
        try:
            # 导入端口检测工具
            sys.path.insert(0, str(monitor_dir))
            from config_utils import is_port_in_use, find_available_port

            # 先检测8000端口状态
            if is_port_in_use(8000):
                print(" 8000被占用", end='', flush=True)
                self.monitor_port = find_available_port(8000)
                print(f"✓ 端口 {8000} 被占用，自动切换到端口 {self.monitor_port}")
            else:
                self.monitor_port = 8000
                print(" → 使用8000")
        except Exception as e:
            print(f"\n⚠️ 端口检测失败: {e}")
            self.monitor_port = 8000  # 默认端口

        # 设置环境变量（让FastAPI知道实际端口）
        env = os.environ.copy()
        env['UVICORN_PORT'] = str(self.monitor_port)
        env['MONITOR_LOG_LEVEL'] = 'DEBUG'  # 启用调试日志

        # 使用conda环境启动uvicorn
        try:
            if sys.platform == 'win32':
                # Windows: 新窗口启动（显示日志）
                self.monitor_proc = subprocess.Popen(
                    ['conda', 'run', '-n', 'lean', 'python', '-m', 'uvicorn', 'api_server:app',
                     '--host', '0.0.0.0', '--port', str(self.monitor_port), '--log-level', 'debug'],
                    cwd=monitor_dir,
                    env=env,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                # Linux/Mac: 后台启动
                self.monitor_proc = subprocess.Popen(
                    ['conda', 'run', '-n', 'lean', 'python', '-m', 'uvicorn', 'api_server:app',
                     '--host', '0.0.0.0', '--port', str(self.monitor_port)],
                    cwd=monitor_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception as e:
            raise Exception(f"启动监控服务器失败: {e}")

        # 等待服务器就绪
        print("   等待监控服务器启动...", end='', flush=True)
        for i in range(10):
            try:
                import urllib.request
                urllib.request.urlopen(f'http://localhost:{self.monitor_port}/api/health', timeout=1)
                print(" ✓")
                print("✓ 监控服务器启动完成")
                return
            except:
                print('.', end='', flush=True)
                time.sleep(1)

        print(" ✓")
        print("✓ 监控服务器已启动 (可能需要几秒才能完全就绪)")

    def open_browser(self):
        """打开监控界面（智能检测已打开的标签页）"""
        print("\n[3/3] 打开监控界面...")

        if not self.monitor_port:
            self.monitor_port = 8000  # 默认端口

        url = f'http://localhost:{self.monitor_port}'

        # 添加时间戳参数，用于触发前端刷新检测
        # 前端会通过 Broadcast Channel API 检测并刷新已打开的标签页
        refresh_url = f'{url}?t={int(time.time())}'

        try:
            webbrowser.open(refresh_url)
            print(f"✓ 浏览器已打开: {url}")
            print(f"   提示: 如果页面已打开，将自动刷新")
        except Exception as e:
            print(f"⚠️ 自动打开浏览器失败: {e}")
            print(f"   请手动访问: {url}")

        time.sleep(1)

    def cleanup(self):
        """清理进程"""
        print("\n停止服务...")

        # 停止监控服务器
        if self.monitor_proc:
            print("→ 停止监控服务器...")

            # Windows需要特殊处理：直接kill uvicorn进程
            if sys.platform == 'win32':
                try:
                    # 方法1: 尝试通过taskkill结束整个进程树
                    subprocess.run(
                        ['taskkill', '/F', '/T', '/PID', str(self.monitor_proc.pid)],
                        capture_output=True,
                        timeout=3
                    )
                    print("✓ 监控服务器已停止 (taskkill)")
                except Exception as e:
                    print(f"⚠️ taskkill失败: {e}, 尝试kill...")
                    try:
                        self.monitor_proc.kill()
                        print("✓ 监控服务器已停止 (kill)")
                    except:
                        print("⚠️ 监控服务器可能未完全停止")
            else:
                # Linux/Mac: 标准终止流程
                self.monitor_proc.terminate()
                try:
                    self.monitor_proc.wait(timeout=5)
                    print("✓ 监控服务器已停止")
                except:
                    print("⚠️ 监控服务器强制停止")
                    self.monitor_proc.kill()

            # 额外检查端口是否释放（Windows专用）
            if sys.platform == 'win32' and self.monitor_port:
                time.sleep(1)  # 等待端口释放
                from config_utils import is_port_in_use
                if is_port_in_use(self.monitor_port):
                    print(f"⚠️ 端口 {self.monitor_port} 仍被占用，可能需要手动清理")
                else:
                    print(f"✓ 端口 {self.monitor_port} 已释放")

        # Redis保持运行（不关闭）
        print("\n✓ Redis容器保持运行 (用于交易系统)")
        print("✓ 清理完成!")

    def run(self):
        """主流程"""
        print("\n" + "=" * 70)
        print("  LEAN交易系统实时监控")
        print("=" * 70 + "\n")

        try:
            # 检查Docker
            if not self.check_docker():
                input("\n按Enter键退出...")
                return

            # 1. 启动Redis
            self.start_redis()

            # 2. 启动监控服务器
            self.start_monitor()

            # 3. 打开浏览器
            self.open_browser()

            # 4. 保持运行
            print("\n" + "=" * 70)
            print("  监控服务已启动!")
            print(f"  监控界面: http://localhost:{self.monitor_port or 8000}")
            print("  按 Ctrl+C 停止服务")
            print("=" * 70 + "\n")

            # 等待用户中断
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n\n收到中断信号 (Ctrl+C)...")

        except Exception as e:
            print(f"\n\n❌ 错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # 清理
            self.cleanup()


if __name__ == "__main__":
    launcher = MonitorLauncher()
    launcher.run()
