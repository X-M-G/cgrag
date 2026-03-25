#!/usr/bin/env python3
"""
Django服务器启动脚本
"""

import os
import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """检查依赖是否安装"""
    required_packages = [
        ('Django', 'django'),
        ('django-cors-headers', 'corsheaders'),
        ('python-docx', 'docx'),
        ('pdfplumber', 'pdfplumber'),
        ('pandas', 'pandas'),
        ('pywin32', 'win32com.client')
    ]
    
    missing_packages = []
    for display_name, import_name in required_packages:
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(display_name)
    
    if missing_packages:
        print("❌ 缺少以下依赖包:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\n请运行以下命令安装依赖:")
        print("pip install -r requirements.txt")
        return False
    
    print("✅ 所有依赖包已安装")
    return True

def setup_database():
    """设置数据库"""
    print("设置数据库...")
    try:
        subprocess.run([sys.executable, "manage.py", "migrate"], check=True)
        print("✅ 数据库迁移完成")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ 数据库迁移失败: {e}")
        return False

def start_server():
    """启动Django服务器"""
    print("启动Django服务器...")
    try:
        subprocess.run([
            sys.executable, "manage.py", "runserver", "127.0.0.1:8000"
        ])
    except KeyboardInterrupt:
        print("\n服务器已停止")
    except Exception as e:
        print(f"❌ 启动服务器失败: {e}")

def main():
    """主函数"""
    print("🚀 启动分块器API服务")
    print("="*50)
    
    # 检查依赖
    if not check_dependencies():
        return
    
    # 设置数据库
    if not setup_database():
        return
    
    print("\n✅ 服务准备就绪")
    print("API接口地址:")
    print("  - 健康检查: http://localhost:8000/api/health/")
    print("  - 分块器信息: http://localhost:8000/api/chunkers/")
    print("  - 文档分块: http://localhost:8000/api/chunk/")
    print("\n按 Ctrl+C 停止服务器")
    print("="*50)
    
    # 启动服务器
    start_server()

if __name__ == "__main__":
    main()
