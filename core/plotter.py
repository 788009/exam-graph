import os
import math

# 强制 Matplotlib 使用非交互式、线程安全的 Agg 后端
import matplotlib

from core.utils import get_exe_dir
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter
import seaborn as sns

from core.utils import *

class StudentPlotter:
    def __init__(self, config_manager, output_dir="./output"):
        self.config = config_manager.config
        self.plot_cfg = self.config.get("plot", {})
        self.styles_cfg = self.plot_cfg.get("styles", {})
        self.output_dir = get_exe_dir() + output_dir
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 初始化图表环境与字体
        self._setup_environment()

    def _setup_environment(self):
        """配置 seaborn 主题并加载独立打包的中文字体"""
        # 设置基础的纯洁白底带网格的主题
        sns.set_theme(style="whitegrid")
        
        font_path = self.config.get("system", {}).get("font_regular", "./fonts/Noto_Sans_SC/NotoSansSC-Regular.ttf")
        
        if os.path.exists(font_path):
            # 动态向 matplotlib 注册字体
            fm.fontManager.addfont(font_path)
            prop = fm.FontProperties(fname=font_path)
            # 强制覆盖当前的字体族
            plt.rcParams['font.sans-serif'] = [prop.get_name()] + plt.rcParams['font.sans-serif']
            # 解决负号显示为方块的问题
            plt.rcParams['axes.unicode_minus'] = False
        else:
            print(f"警告: 绘图时未找到字体文件 {font_path}，可能会出现中文乱码。")

    def plot_student(self, student_data, global_context):
        """为单个学生绘制综合成绩趋势大图"""
        subjects = global_context["subjects"]
        n_subjects = len(subjects)
        if n_subjects == 0:
            return
            
        # --- 新增：计算分组 Y 轴的最值范围 ---
        y_axis_cfg = self.plot_cfg.get("y_axis", {})
        unified_scale = y_axis_cfg.get("unified_scale", True)
        subj_to_group = {}
        group_limits = {}

        if unified_scale:
            groups_cfg = y_axis_cfg.get("groups", {})
            # 建立 反向映射: 科目 -> 分数分组
            for g_name, subjs in groups_cfg.items():
                for s in subjs:
                    subj_to_group[s] = g_name

            group_y_values = {g: [] for g in groups_cfg.keys()}
            align_x = self.plot_cfg.get("align_x_axis", True)
            class_name = student_data["class"]

            # 收集各个分组下的所有有效分数（用于求极值）
            for subject in subjects:
                g_name = subj_to_group.get(subject)
                if not g_name:
                    continue
                    
                x_labels = global_context["all_exams"] if align_x else global_context["exam_orders"].get(subject, [])
                for exam in x_labels:
                    v_stu = student_data["scores"][subject].get(exam)
                    if v_stu is not None: group_y_values[g_name].append(v_stu)

                    if self.plot_cfg.get("show_class_average"):
                        v_cls = global_context["class_averages"].get(class_name, {}).get(subject, {}).get(exam)
                        if v_cls is not None: group_y_values[g_name].append(v_cls)

                    if self.plot_cfg.get("show_grade_average"):
                        v_grd = global_context["grade_averages"].get(subject, {}).get(exam)
                        if v_grd is not None: group_y_values[g_name].append(v_grd)

            # 确定每个分组的 [最小值, 最大值]
            for g_name, vals in group_y_values.items():
                if vals:
                    group_limits[g_name] = (min(vals), max(vals))
        # ----------------------------------------

        n_cols = self.plot_cfg.get("columns", 3)
        n_rows = math.ceil(n_subjects / n_cols)
        align = self.plot_cfg.get("last_row_align", "center")
        
        fig = plt.figure(figsize=(n_cols * 5, n_rows * 4 + 1))
        gs_cols = n_cols * 2
        gs = GridSpec(n_rows, gs_cols, figure=fig)
        gs.update(wspace=0.3, hspace=0.4)
        
        student_name = student_data["name"]
        student_id = student_data["id"]
        class_name = student_data["class"]
        
        # ===== 1. 标题生成逻辑 =====
        title_template = self.plot_cfg.get("title_template", "{class_name} - {student_name} (座号: {student_id}) 排名趋势图")
        title_text = title_template.replace("{class_name}", str(class_name))\
                                   .replace("{student_name}", str(student_name))\
                                   .replace("{student_id}", str(student_id))
                                   
        fig.suptitle(title_text, fontsize=18, fontweight='bold', y=0.98)
        # ================================

        for i, subject in enumerate(subjects):
            row = i // n_cols
            col_in_row = i % n_cols
            
            if row == n_rows - 1:
                items_in_last_row = n_subjects - row * n_cols
                if align == "center":
                    start_offset = n_cols - items_in_last_row
                elif align == "right":
                    start_offset = (n_cols - items_in_last_row) * 2
                else:
                    start_offset = 0
            else:
                start_offset = 0
                
            start_col = start_offset + col_in_row * 2
            end_col = start_col + 2
            
            ax = fig.add_subplot(gs[row, start_col:end_col])
            
            # 将分组映射和范围传给子图绘制逻辑
            self._plot_single_subject(ax, subject, student_data, global_context, subj_to_group, group_limits)

        # ===== 2. 底部的保存图片逻辑 =====
        # 优先从 global_context 获取解析了 filename 和 time 的 base_dir
        base_dir = global_context.get("resolved_base_dir", self.config.get("output", {}).get("base_dir", "./output"))
        template = self.config.get("output", {}).get("file_template", "{class_name}/{student_id}-{student_name}.png")
        
        safe_class = str(class_name).replace("/", "_").replace("\\", "_")
        safe_id = str(student_id).replace("/", "_").replace("\\", "_")
        safe_name = str(student_name).replace("/", "_").replace("\\", "_")
        
        # 兼容了旧的 {class} 和 {name}，同时支持最新的占位符
        rel_path = template.replace("{class_name}", safe_class).replace("{class}", safe_class)\
                           .replace("{student_id}", safe_id).replace("{id}", safe_id)\
                           .replace("{student_name}", safe_name).replace("{name}", safe_name)
                           
        save_path = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        fig.savefig(save_path, bbox_inches='tight', dpi=120)
        plt.close(fig)
        # ================================

    def _plot_single_subject(self, ax, subject, student, context, subj_to_group=None, group_limits=None):
        """在指定的子图 (ax) 上绘制单科成绩"""
        align_x = self.plot_cfg.get("align_x_axis", True)
        
        if align_x:
            x_labels = context["all_exams"]
        else:
            x_labels = context["exam_orders"].get(subject, [])
            
        if not x_labels:
            ax.set_title(subject)
            return

        stu_scores = []
        cls_avgs = []
        grd_avgs = []
        class_name = student["class"]
        
        for exam in x_labels:
            stu_scores.append(student["scores"][subject].get(exam))
            if self.plot_cfg.get("show_class_average"):
                cls_avgs.append(context["class_averages"].get(class_name, {}).get(subject, {}).get(exam))
            if self.plot_cfg.get("show_grade_average"):
                grd_avgs.append(context["grade_averages"].get(subject, {}).get(exam))

        x_indices = list(range(len(x_labels)))
        line_width = self.styles_cfg.get("line_width", 2.0)
        marker_size = self.styles_cfg.get("marker_size", 6)
        
        if grd_avgs:
            self._draw_line(ax, x_indices, grd_avgs, color=self.styles_cfg.get("grade_avg_color", "#D3D3D3"), linestyle=self.styles_cfg.get("class_avg_linestyle", "--"), label="年级均分")
        if cls_avgs:
            self._draw_line(ax, x_indices, cls_avgs, color=self.styles_cfg.get("class_avg_color", "#808080"), linestyle=self.styles_cfg.get("class_avg_linestyle", "--"), label="班级均分")

        valid_stu_points = self._draw_line(ax, x_indices, stu_scores, color="#1f77b4", linestyle="-", marker="o", markersize=marker_size, linewidth=line_width, label="学生成绩")

        if self.plot_cfg.get("show_data_labels", True) and valid_stu_points:
            for vx, vy in valid_stu_points:
                ax.annotate(f"{vy:g}", xy=(vx, vy), xytext=(0, 7), textcoords="offset points", ha='center', va='bottom', fontsize=10, fontweight='bold', color="#1f77b4")

        # ==========================================
        # Y轴刻度与反转逻辑 (统一定义与应用)
        # ==========================================
        y_axis_cfg = self.plot_cfg.get("y_axis", {})
        is_inverted = y_axis_cfg.get("invert_y_axis", True)

        if subj_to_group and group_limits and subject in subj_to_group:
            g_name = subj_to_group[subject]
            if g_name in group_limits:
                min_y, max_y = group_limits[g_name]
                if min_y < max_y:
                    padding = (max_y - min_y) * 0.05
                    # 恢复留白：直接用 min_y - padding，允许坐标轴在数学上进入 0 或负数区域
                    top_limit = min_y - padding
                    ax.set_ylim(top_limit, max_y + padding)
                else:
                    ax.set_ylim(min_y - 5, max_y + 5)

        # 应用反转与刻度隐藏
        if is_inverted:
            ax.invert_yaxis()
            # 魔法在这里：拦截渲染，如果刻度值 <= 0，返回空字符串让其隐身；否则正常显示
            ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: "" if x <= 0 else f"{x:g}"))
        # ==========================================

        ax.set_title(subject, fontsize=14, pad=10)
        ax.set_xticks(x_indices)
        ax.set_xticklabels(x_labels, rotation=30, ha='right')
        
        if ax.get_subplotspec().colspan.start == 0 and ax.get_subplotspec().rowspan.start == 0:
            ax.legend(loc="best")

    def _draw_line(self, ax, x_indices, y_values, **kwargs):
        """
        通用画线辅助函数：自动剔除 y 中的 None，并匹配对应的 x_index
        实现“有缺考时空出 X 轴位置，但直接连接前后考试”的功能
        返回有效数据点的坐标列表 (用于后续标注文本)
        """
        valid_x = []
        valid_y = []
        for x, y in zip(x_indices, y_values):
            if y is not None:
                valid_x.append(x)
                valid_y.append(y)
                
        if valid_y:
            ax.plot(valid_x, valid_y, **kwargs)
            return list(zip(valid_x, valid_y))
        return []