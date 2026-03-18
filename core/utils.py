import sys
import shutil
import os

# ==========================================
# 区分“内部只读资源”和“外部可写目录”
# ==========================================

def get_resource_path(relative_path):
    """
    获取打包在程序内部的只读资源路径 (如 web/ 目录和 config_schema.json)
    兼容 PyInstaller 的 _MEIPASS 临时目录和 Nuitka/原生环境
    """
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller 单文件模式解压后的临时目录
        return os.path.join(sys._MEIPASS, relative_path)
    # Nuitka 独立目录或原生 Python 环境
    return os.path.join(os.getcwd(), relative_path)

def get_exe_dir():
    """
    获取 .exe 所在的外部真实目录 (用于生成 output/ 或读写 config.toml)
    """
    if getattr(sys, 'frozen', False):
        # 打包后的 .exe 所在目录
        return os.path.dirname(sys.executable)
    # 原生环境的 main.py 所在目录
    return os.getcwd()

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