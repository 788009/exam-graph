import os
import json
import webview
import threading
from core.config_parser import ConfigManager
from core.batch_manager import BatchManager

class Api:
    def __init__(self):
        # 核心修复：加上单下划线，让 pywebview 知道这是内部变量，不要去碰它们！
        self._window = None
        self._schema_path = "./config_schema.json"
        self._config_manager = ConfigManager("./config.toml")

    def set_window(self, window):
        self._window = window

    def get_schema(self):
        """前端调用：获取配置表单的 JSON 结构"""
        try:
            with open(self._schema_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # 明确返回 error 字段
            return {"error": f"无法读取 Schema: {str(e)}"}

    def get_config(self):
        """前端调用：读取当前实际的 TOML 配置"""
        self._config_manager.load_config()
        return self._config_manager.config

    def save_config(self, new_config):
        """前端调用：保存用户在界面上修改后的配置到 TOML"""
        import tomli_w
        try:
            with open(self._config_manager.config_path, "wb") as f:
                tomli_w.dump(new_config, f)
            self._config_manager.load_config()
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def choose_excel_file(self):
        """前端调用：唤起系统文件选择框"""
        if not self._window:
            return None
        file_types = ('Excel 文件 (*.xlsx)', '所有文件 (*.*)')
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=file_types)
        if result and len(result) > 0:
            return result[0]
        return None

    def start_task(self, excel_path):
        """前端调用：启动批量生成任务"""
        def _run():
            try:
                manager = BatchManager("./config.toml")
                manager.run(excel_path)
                self._window.evaluate_js(f"window.taskFinished('任务执行完毕！')")
            except Exception as e:
                print(os.getcwd())
                self._window.evaluate_js(f"window.taskError('核心报错: {str(e)}')")

        thread = threading.Thread(target=_run)
        thread.start()
        return {"status": "started"}

if __name__ == '__main__':
    api = Api()
    window = webview.create_window('批量成绩可视化软件', 'web/index.html', js_api=api, width=1000, height=750)
    api.set_window(window)
    webview.start(debug=True)