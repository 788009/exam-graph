import sys
import shutil
import os

# ==========================================
# 区分“内部只读资源”和“外部可写目录”
# ==========================================

import os
import sys

def get_resource_path(relative_path):
    """
    获取程序内部资源的路径（兼容 PyInstaller _MEIPASS 和 Nuitka）
    用于：web/ 目录、config_schema.json 等只读资源
    """
    # 1. 处理 PyInstaller 的单文件模式 (解压到临时目录)
    if hasattr(sys, '_MEIPASS'):
        base_path = sys._MEIPASS
    # 2. 处理 Nuitka 或 PyInstaller 的普通模式
    # 使用 sys.argv[0] 获取程序本体位置，比 getcwd() 更稳定
    else:
        # 寻找入口文件所在目录
        import __main__
        if hasattr(__main__, "__file__"):
            base_path = os.path.dirname(os.path.abspath(__main__.__file__))
        else:
            base_path = os.path.dirname(os.path.abspath(sys.argv[0]))

    return os.path.normpath(os.path.join(base_path, relative_path))

def get_exe_dir():
    """
    获取 .exe 所在的外部真实目录
    用于：读写 config.toml、存放 output/ 日志等用户可见文件
    """
    # 如果是打包环境 (Nuitka 或 PyInstaller)
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        # sys.executable 是生成的 .exe 的绝对路径
        return os.path.dirname(os.path.abspath(sys.executable))
    
    # 如果是开发环境，返回入口脚本 main.py 所在的目录
    import __main__
    if hasattr(__main__, "__file__"):
        return os.path.dirname(os.path.abspath(__main__.__file__))
    
    return os.path.dirname(os.path.abspath(sys.argv[0]))

# ==========================================
# 初始化外部的可写配置文件
# ==========================================

def init_external_config():
    """
    确保 .exe 旁边有一个可读写的 config.toml。
    如果没有，就把程序内部打包的默认模板拷贝出去。
    """
    exe_dir = get_exe_dir()
    external_config_path = os.path.join(exe_dir, "config.toml")
    
    # 如果外部没有配置文件，则从内部释放一个默认的
    if not os.path.exists(external_config_path):
        internal_config_path = get_resource_path("config.toml")
        if os.path.exists(internal_config_path):
            shutil.copy2(internal_config_path, external_config_path)
            
    return external_config_path

# ==========================================