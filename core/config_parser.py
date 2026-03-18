import os
import re
try:
    import tomllib
except ImportError:
    import tomli as tomllib
from pathlib import Path
import py7zr

class ConfigManager:
    def __init__(self, config_path="config.toml"):
        self.config_path = Path(config_path)
        self.config = {}
        self.column_regex = None
        
        self.load_config()
        self._compile_regex()
        self._check_and_extract_fonts()

    def load_config(self):
        """加载并解析 TOML 配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"找不到配置文件: {self.config_path.resolve()}")
            
        with open(self.config_path, "rb") as f:
            self.config = tomllib.load(f)

    def _compile_regex(self):
        """将配置文件中的模板转换为正则表达式"""
        template = self.config.get("parser", {}).get("column_template", "{exam}-{subject}")
        
        # 将特殊符号转义，防止模板中出现正则元字符导致错误（比如 . 或 *）
        # 这里先不管 {exam} 和 {subject}，把它们当作普通文本保留
        escaped_template = re.escape(template)
        
        # 恢复占位符，并替换为命名捕获组
        # 注意：re.escape 会把 { 和 } 转义为 \{ 和 \}，所以我们需要匹配转义后的字符
        regex_str = escaped_template.replace(r"\{exam\}", r"(?P<exam>.+)")
        regex_str = regex_str.replace(r"\{subject\}", r"(?P<subject>.+)")
        
        # 添加首尾锚点，确保完全匹配列名
        regex_str = f"^{regex_str}$"
        self.column_regex = re.compile(regex_str)

    def _check_and_extract_fonts(self):
        """检查字体文件是否存在，若不存在则尝试解压"""
        sys_config = self.config.get("system", {})
        font_regular = Path(sys_config.get("font_regular", "./fonts/Noto_Sans_SC/NotoSansSC-Regular.ttf"))
        font_bold = Path(sys_config.get("font_bold", "./fonts/Noto_Sans_SC/NotoSansSC-Bold.ttf"))
        font_archive = Path(sys_config.get("font_archive", "./fonts/Noto_Sans_SC.7z"))

        # 如果常规字体或粗体缺失，则触发解压逻辑
        if not font_regular.exists() or not font_bold.exists():
            if not font_archive.exists():
                raise FileNotFoundError(f"字体文件和压缩包均丢失，请确保存在: {font_archive}")
            
            extract_dir = font_archive.parent  # 即 ./fonts/ 目录
            print(f"检测到字体缺失，正在从 {font_archive} 解压...")
            
            try:
                with py7zr.SevenZipFile(font_archive, mode='r') as z:
                    z.extractall(path=extract_dir)
                print("字体解压完成！")
            except Exception as e:
                raise RuntimeError(f"解压字体失败: {e}")

    def parse_column_name(self, col_name):
        """
        传入一个列名，返回解析出的考试名和科目名
        返回格式: (exam_name, subject_name)
        如果匹配失败（不符合模板），则返回 (None, None)
        """
        match = self.column_regex.match(col_name)
        if match:
            return match.group("exam"), match.group("subject")
        return None, None

    def is_ignored_column(self, col_name):
        """检查该列名是否包含需要忽略的关键字"""
        ignore_keywords = self.config.get("parser", {}).get("ignore_keywords", [])
        for keyword in ignore_keywords:
            if keyword in col_name:
                return True
        return False

# 简单的测试入口
if __name__ == "__main__":
    # 假设你的 config.toml 已经在同级目录
    config_mgr = ConfigManager()
    
    test_columns = ["高三上月考1-语文", "高三下期末-数学", "语文平均名次", "非法列名"]
    for col in test_columns:
        if config_mgr.is_ignored_column(col):
            print(f"[{col}] -> 被标记为忽略")
        else:
            exam, subject = config_mgr.parse_column_name(col)
            if exam and subject:
                print(f"[{col}] -> 考试: {exam}, 科目: {subject}")
            else:
                print(f"[{col}] -> 不符合解析模板")