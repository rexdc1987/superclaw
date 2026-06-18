"""SuperClaw V2 启动入口"""
import sys
import os

# 确保 src 目录在搜索路径中
project_root = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from main import main

if __name__ == "__main__":
    # 默认启动 GUI 模式
    if "--gui" not in sys.argv and "--cli" not in sys.argv:
        sys.argv.append("--gui")
    main()
