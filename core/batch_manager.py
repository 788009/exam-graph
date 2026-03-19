import os
import time
import json
from concurrent.futures import ProcessPoolExecutor, as_completed

from core.config_parser import ConfigManager
from core.data_loader import DataLoader
from core.plotter import StudentPlotter

# 定义子进程的全局变量
global_plotter = None

def init_worker(config_manager):
    """
    子进程初始化函数。
    由 ProcessPoolExecutor 的 initializer 参数调用。
    每个子进程在刚诞生时，仅执行一次此函数。
    在这里实例化 StudentPlotter，后续该子进程的所有任务都复用它。
    """
    global global_plotter
    global_plotter = StudentPlotter(config_manager)

def _worker_task(student_data, global_context):
    """
    独立进程的工作函数。
    直接复用进程启动时创建好的 global_plotter，告别冗余初始化。
    """
    try:
        global_plotter.plot_student(student_data, global_context)
        return True, student_data['name'], "成功"
    except Exception as e:
        return False, student_data['name'], str(e)


class BatchManager:
    def __init__(self, config_path="config.toml"):
        """初始化全局配置"""
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.config
        self.is_cancelled = False
        
    def cancel(self):
        self.is_cancelled = True

    def run(self, excel_path, progress_callback=None):
        """执行批量生成的总指挥方法"""
        start_time = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] 开始任务，读取数据...")
        
        # 1. 加载并清洗数据
        try:
            loader = DataLoader(self.config_manager)
            data = loader.load(excel_path)
        except Exception as e:
            print(f"[致命错误] 数据加载失败: {e}")
            return
            
        students = data["students"]
        if not students:
            print("未解析到任何有效学生数据，任务终止。")
            return
        total_students = len(students)
            
        # 动态解析 base_dir 所需的变量
        excel_filename = os.path.splitext(os.path.basename(excel_path))[0]
        # 时间格式如 20260318-111740
        current_time = time.strftime("%Y%m%d-%H%M%S") 
        
        output_cfg = self.config.get("output", {})
        dir_mode = output_cfg.get("dir_mode", "dynamic")
        
        if dir_mode == "static":
            resolved_base_dir = output_cfg.get("static_base_dir", "./output/static")
            resume_enabled = output_cfg.get("resume_enabled", True)
        else:
            raw_base_dir = output_cfg.get("base_dir", "./output/{filename}-{time}")
            resolved_base_dir = raw_base_dir.replace("{filename}", excel_filename).replace("{time}", current_time)
            resume_enabled = False # 动态目录默认不支持续传

        # 提取全局画图上下文 (将解析好的 base_dir 塞进去传给 Plotter)
        global_context = {
            "subjects": data["subjects"],
            "exam_orders": data["exam_orders"],
            "all_exams": data["all_exams"],
            "grade_averages": data["grade_averages"],
            "class_averages": data["class_averages"],
            "resolved_base_dir": resolved_base_dir,
            "resume_enabled": resume_enabled
        }

        # 确保根目录存在，并在静态模式下写入元数据
        os.makedirs(resolved_base_dir, exist_ok=True)
        
        if dir_mode == "static":
            meta_path = os.path.join(resolved_base_dir, "metadata.json")
            meta_data = {
                "exams": data.get("all_exams", []),
                "subjects": data.get("subjects", [])
            }
            try:
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[警告] 元数据 metadata.json 写入失败: {e}")

        # 2. 准备并发环境
        system_cfg = self.config.get("system", {})
        use_mp = system_cfg.get("use_multiprocessing", True)
        max_workers = system_cfg.get("max_workers", 0)
        
        if max_workers <= 0:
            max_workers = os.cpu_count() or 4

        print(f"[{time.strftime('%H:%M:%S')}] 数据就绪，准备生成 {len(students)} 张图表...")
        
        success_count = 0
        fail_count = 0

        # 3. 开始批量绘图
        if use_mp and max_workers > 1:
            print(f"启用多进程加速，分配核心数: {max_workers}")
            
            # ===== 修改：使用 initializer 传递子进程初始化逻辑 =====
            with ProcessPoolExecutor(
                max_workers=max_workers,
                initializer=init_worker,
                initargs=(self.config_manager,)
            ) as executor:
                
                # 提交所有学生的画图任务 (不再传递 config_manager)
                futures = [
                    executor.submit(_worker_task, stu, global_context) 
                    for stu in students
                ]
                
                # 收集进度 (此处 enumerate 从 1 开始，所以直接传 i)
                for i, future in enumerate(as_completed(futures), 1):
                    if self.is_cancelled:
                        # 尝试取消还没开始分配的子任务
                        for f in futures: f.cancel()
                        print("\n[中断] 用户终止了批量生成任务。")
                        break

                    success, name, msg = future.result()
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                        print(f"\n[错误] 学生 {name} 图表生成失败: {msg}")

                    if progress_callback:
                        # 传出：当前第几个、总数、当前同学姓名 (修复了之前的 i+1 溢出逻辑)
                        progress_callback(i, total_students, name)
                    
                    # 简单的终端进度条打印
                    if i % 10 == 0 or i == len(students):
                        print(f"\r进度: {i}/{len(students)} (成功: {success_count}, 失败: {fail_count})", end="", flush=True)
            print() # 换行收尾
        else:
            print("单进程模式运行中...")
            # 单进程下，为了性能复用同一个 plotter 实例
            plotter = StudentPlotter(self.config_manager)
            for i, stu in enumerate(students, 1):
                try:
                    plotter.plot_student(stu, global_context)
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    print(f"\n[错误] 学生 {stu['name']} 图表生成失败: {e}")
                
                if progress_callback:
                    progress_callback(i, total_students, stu['name'])
                    
                if i % 10 == 0 or i == len(students):
                    print(f"\r进度: {i}/{len(students)}", end="", flush=True)
            print()

        # 4. 统计与结束
        cost_time = time.time() - start_time
        print(f"\n[{time.strftime('%H:%M:%S')}] 批量任务完成！")
        print(f"总计: {len(students)} | 成功: {success_count} | 失败: {fail_count}")
        print(f"总耗时: {cost_time:.2f} 秒 (平均 {cost_time/len(students):.2f} 秒/张)")

        # 返回本次任务的专属输出目录
        return global_context.get("resolved_base_dir")