import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from core.config_parser import ConfigManager
from core.data_loader import DataLoader
from core.plotter import StudentPlotter

def _worker_task(student_data, global_context, config_manager):
    """
    独立进程的工作函数
    注意：Matplotlib 在多进程环境下，最好在每个进程内部独立实例化 Plotter，
    避免跨进程共享 GUI 资源导致死锁或崩溃。
    """
    try:
        plotter = StudentPlotter(config_manager)
        plotter.plot_student(student_data, global_context)
        return True, student_data['name'], "成功"
    except Exception as e:
        return False, student_data['name'], str(e)


class BatchManager:
    def __init__(self, config_path="config.toml"):
        """初始化全局配置"""
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.config

    def run(self, excel_path):
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
            
        # 动态解析 base_dir 所需的变量
        excel_filename = os.path.splitext(os.path.basename(excel_path))[0]
        # 时间格式如 20260318-111740
        current_time = time.strftime("%Y%m%d-%H%M%S") 
        
        output_cfg = self.config.get("output", {})
        raw_base_dir = output_cfg.get("base_dir", "./output/{filename}-{time}")
        resolved_base_dir = raw_base_dir.replace("{filename}", excel_filename).replace("{time}", current_time)

        # 提取全局画图上下文 (将解析好的 base_dir 塞进去传给 Plotter)
        global_context = {
            "subjects": data["subjects"],
            "exam_orders": data["exam_orders"],
            "all_exams": data["all_exams"],
            "grade_averages": data["grade_averages"],
            "class_averages": data["class_averages"],
            "resolved_base_dir": resolved_base_dir  # 新增这一行
        }

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
            # 使用进程池分配任务
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有学生的画图任务
                futures = [
                    executor.submit(_worker_task, stu, global_context, self.config_manager) 
                    for stu in students
                ]
                
                # 收集进度
                for i, future in enumerate(as_completed(futures), 1):
                    success, name, msg = future.result()
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
                        print(f"\n[错误] 学生 {name} 图表生成失败: {msg}")
                    
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
                
                if i % 10 == 0 or i == len(students):
                    print(f"\r进度: {i}/{len(students)}", end="", flush=True)
            print()

        # 4. 统计与结束
        cost_time = time.time() - start_time
        print(f"\n[{time.strftime('%H:%M:%S')}] 批量任务完成！")
        print(f"总计: {len(students)} | 成功: {success_count} | 失败: {fail_count}")
        print(f"总耗时: {cost_time:.2f} 秒 (平均 {cost_time/len(students):.2f} 秒/张)")