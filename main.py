import os
import json
import webview
import threading
import platform
import subprocess
import base64
import tempfile
import io
from core.config_parser import ConfigManager
from core.batch_manager import BatchManager
from core.data_loader import DataLoader

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

    def open_folder(self, target_dir=None):
        """前端调用：唤起操作系统自带的文件管理器打开指定目录"""
        # 如果前端传了具体路径且存在，就打开它；否则打开默认的 ./output
        if target_dir and os.path.exists(target_dir):
            output_dir = os.path.abspath(target_dir)
        else:
            output_dir = os.path.abspath("./output")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            
        try:
            current_os = platform.system()
            if current_os == 'Windows':
                os.startfile(output_dir)
            elif current_os == 'Darwin':  
                subprocess.call(['open', output_dir])
            else:  
                subprocess.call(['xdg-open', output_dir])
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def preview_data(self, excel_path):
        """前端调用：极速读取 Excel 表头并进行模式诊断"""
        import pandas as pd
        try:
            # 仅读取表头，速度极快
            df = pd.read_excel(excel_path, engine='openpyxl', nrows=0)
            headers = df.columns.tolist()
            
            self._config_manager.load_config()
            self._config_manager._compile_regex()
            cfg = self._config_manager.config
            data_cfg = cfg.get("data", {})
            
            c_idx = data_cfg.get("class_col", 1) - 1
            s_idx = data_cfg.get("student_id_col", 2) - 1
            n_idx = data_cfg.get("name_col", 3) - 1
            f_idx = data_cfg.get("first_subject_col", 4) - 1
            
            # --- 1. 获取当前配置指向的真实基础列名 ---
            def get_col_name(idx):
                return str(headers[idx]) if 0 <= idx < len(headers) else "（索引越界）"
                
            current_basics = {
                "class_col": get_col_name(c_idx),
                "student_id_col": get_col_name(s_idx),
                "name_col": get_col_name(n_idx)
            }
            
            # --- 2. 硬编码推测基础列 ---
            predictions = {}
            found_class = [i for i, h in enumerate(headers) if "班级" in str(h)]
            found_id = [i for i, h in enumerate(headers) if "座号" in str(h) or "学号" in str(h)]
            found_name = [i for i, h in enumerate(headers) if "姓名" in str(h)]
            
            # 仅当三者都精准找到 1 个，且互不重叠（一一对应）时，才给出预测
            if len(found_class) == 1 and len(found_id) == 1 and len(found_name) == 1:
                if len(set([found_class[0], found_id[0], found_name[0]])) == 3:
                    # 检查是否与当前配置有差异，有差异才返回需要修正
                    if found_class[0] != c_idx or found_id[0] != s_idx or found_name[0] != n_idx:
                        predictions = {
                            "class_col": found_class[0] + 1,
                            "student_id_col": found_id[0] + 1,
                            "name_col": found_name[0] + 1
                        }
                    
            # --- 3. 检查解析模板命中率 ---
            parsed_subjects = set()
            sample_headers = []
            if 0 <= f_idx < len(headers):
                score_cols = headers[f_idx:]
                # 提取前 5 个成绩列供前端展示错误提示
                sample_headers = [str(x) for x in score_cols[:5]]
                for col in score_cols:
                    if self._config_manager.is_ignored_column(col):
                        continue
                    exam, subj = self._config_manager.parse_column_name(col)
                    if subj:
                        parsed_subjects.add(subj)
            
            return {
                "status": "success",
                "current_basics": current_basics,
                "predictions": predictions,
                "parsed_subject_count": len(parsed_subjects),
                "sample_headers": sample_headers
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}
        
    def preview_plot(self, excel_path):
        """前端调用：生成首位同学的图表并转为 Base64 返回"""
        try:
            # 1. 加载数据
            self._config_manager.load_config()
            self._config_manager._compile_regex() # 借用你修复的逻辑
            
            loader = DataLoader(self._config_manager)
            data = loader.load(excel_path)
            
            students = data.get("students", [])
            if not students:
                return {"status": "error", "message": "未在表格中解析到有效学生数据"}
                
            first_student = students[0]
            
            # 2. 创建临时目录来接收这张图
            with tempfile.TemporaryDirectory() as temp_dir:
                global_context = {
                    "subjects": data["subjects"],
                    "exam_orders": data["exam_orders"],
                    "all_exams": data["all_exams"],
                    "grade_averages": data["grade_averages"],
                    "class_averages": data["class_averages"],
                    "resolved_base_dir": temp_dir  # 强制输出到临时目录
                }
                
                from core.plotter import StudentPlotter
                plotter = StudentPlotter(self._config_manager)
                plotter.plot_student(first_student, global_context)
                
                # 3. 在临时目录中寻找生成的 .png 文件
                generated_file = None
                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith(".png"):
                            generated_file = os.path.join(root, file)
                            break
                    if generated_file: break
                    
                if not generated_file:
                    return {"status": "error", "message": "图表文件生成失败，未找到输出结果"}
                    
                # 4. 转为 Base64 字符串
                with open(generated_file, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                    
                return {
                    "status": "success", 
                    "image_base64": f"data:image/png;base64,{encoded_string}",
                    "student_name": first_student["name"]
                }
                
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def start_task(self, excel_path):
        """前端调用：启动批量生成任务"""
        def _run():
            try:
                manager = BatchManager("./config.toml")
                # 捕获内核返回的实际输出目录
                actual_output_dir = manager.run(excel_path)
                
                # Windows 路径的斜杠 \ 会破坏 JS 字符串，需替换为 /
                safe_dir = str(actual_output_dir).replace('\\', '/')
                
                # 将路径作为第二个参数传给前端
                self._window.evaluate_js(f"window.taskFinished('任务执行完毕！', '{safe_dir}')")
            except Exception as e:
                self._window.evaluate_js(f"window.taskError('核心报错: {str(e)}')")

        thread = threading.Thread(target=_run)
        thread.start()
        return {"status": "started"}

if __name__ == '__main__':
    api = Api()
    window = webview.create_window('Exam Graph', 'web/index.html', js_api=api, width=1000, height=750)
    api.set_window(window)
    webview.start(debug=True)