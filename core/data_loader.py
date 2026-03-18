import pandas as pd

class DataLoader:
    def __init__(self, config_manager):
        self.config = config_manager.config
        self.parser = config_manager
        
        # 核心元数据（自动从表格推导）
        self.subjects = []           # 记录解析出的科目列表（严格按照表格列出现的顺序）
        self.exam_orders = {}        # {subject: [exam1, exam2, ...]} 记录各科具体的考试顺序
        self.all_exams = []          # [exam1, exam2, ...] 所有出现过的考试并集（按顺序，用于对齐 x 轴）
        self.col_mapping = {}        # {原始列名: (subject, exam)} 路由映射，加速数据提取
        
        # 平均分缓存
        self.grade_averages = {}     # {subject: {exam: score}}
        self.class_averages = {}     # {class_name: {subject: {exam: score}}}

    def load(self, file_path):
        """主入口：加载并处理 Excel 数据"""
        print(f"正在读取数据文件: {file_path} ...")
        # 建议引擎使用 openpyxl 读取 xlsx
        df = pd.read_excel(file_path, engine='openpyxl')
        
        # 1. 扫描表头，建立科目、考试和列名的映射关系
        self._parse_headers(df)
        
        # 2. 如果配置开启，计算班级和年级均分
        self._calculate_averages(df)
        
        # 3. 提取每位学生的具体成绩
        students = self._extract_students(df)
        
        print(f"数据加载完成！共解析 {len(self.subjects)} 个科目, {len(students)} 名学生。")
        
        return {
            "subjects": self.subjects,
            "exam_orders": self.exam_orders,
            "all_exams": self.all_exams,
            "grade_averages": self.grade_averages,
            "class_averages": self.class_averages,
            "students": students
        }

    def _parse_headers(self, df):
        """解析表头，提取科目与考试顺序"""
        data_cfg = self.config.get("data", {})
        # 配置中是 1-based，转为 pandas 的 0-based 索引
        first_subj_idx = data_cfg.get("first_subject_col", 4) - 1
        
        if first_subj_idx >= len(df.columns):
            raise ValueError(f"配置的第一科起始列({first_subj_idx + 1})超出了表格总列数！")

        score_cols = df.columns[first_subj_idx:]
        
        for col_name in score_cols:
            # 跳过类似“名次”、“均分”这种被标记为忽略的列
            if self.parser.is_ignored_column(col_name):
                continue
            
            # 尝试通过正则模板匹配
            exam, subject = self.parser.parse_column_name(col_name)
            
            if exam and subject:
                # 建立列名到 (科目, 考试) 的映射
                self.col_mapping[col_name] = (subject, exam)
                
                # 动态维护科目列表（保证按表格里的顺序从左到右）
                if subject not in self.subjects:
                    self.subjects.append(subject)
                    self.exam_orders[subject] = []
                
                # 动态维护该科目的考试顺序
                if exam not in self.exam_orders[subject]:
                    self.exam_orders[subject].append(exam)
                    
                # 维护全局所有考试的并集（用于应对某科缺考，横轴需要空出位置的情况）
                if exam not in self.all_exams:
                    self.all_exams.append(exam)

    def _calculate_averages(self, df):
        """计算年级与班级均分"""
        plot_cfg = self.config.get("plot", {})
        calc_grade = plot_cfg.get("show_grade_average", True)
        calc_class = plot_cfg.get("show_class_average", True)
        
        if not calc_grade and not calc_class:
            return

        data_cfg = self.config.get("data", {})
        class_col_name = df.columns[data_cfg.get("class_col", 1) - 1]
        
        # 初始化结构
        for subject in self.subjects:
            self.grade_averages[subject] = {}
        
        # 计算年级均分
        if calc_grade:
            for col_name, (subject, exam) in self.col_mapping.items():
                # pandas 的 mean() 会自动忽略 NaN（缺考）
                mean_val = df[col_name].mean()
                if pd.notna(mean_val):
                    self.grade_averages[subject][exam] = round(mean_val, 2)
        
        # 计算班级均分
        if calc_class:
            grouped = df.groupby(class_col_name)
            for class_name, group in grouped:
                # 强制转为字符串，防止班级名是纯数字(如 1, 2)导致后续字典取值类型混乱
                class_name_str = str(class_name)
                self.class_averages[class_name_str] = {subj: {} for subj in self.subjects}
                
                for col_name, (subject, exam) in self.col_mapping.items():
                    mean_val = group[col_name].mean()
                    if pd.notna(mean_val):
                        self.class_averages[class_name_str][subject][exam] = round(mean_val, 2)

    def _extract_students(self, df):
        """提取每个学生的独立数据"""
        data_cfg = self.config.get("data", {})
        class_col = df.columns[data_cfg.get("class_col", 1) - 1]
        id_col = df.columns[data_cfg.get("student_id_col", 2) - 1]
        name_col = df.columns[data_cfg.get("name_col", 3) - 1]
        
        students = []
        
        for _, row in df.iterrows():
            cls_name = str(row[class_col]) if pd.notna(row[class_col]) else "未知班级"
            stu_id = str(row[id_col]) if pd.notna(row[id_col]) else "未知座号"
            stu_name = str(row[name_col]) if pd.notna(row[name_col]) else "未知姓名"
            
            # 防御性过滤：如果表格底下有全空的脏数据行，直接跳过
            if cls_name == "未知班级" and stu_name == "未知姓名":
                continue
            
            scores = {subj: {} for subj in self.subjects}
            
            for col_name, (subject, exam) in self.col_mapping.items():
                val = row[col_name]
                # 将缺考的 NaN 转为 Python 原生的 None，seaborn/matplotlib 会自动处理断点连线
                if pd.notna(val):
                    scores[subject][exam] = float(val)
                else:
                    scores[subject][exam] = None
                    
            students.append({
                "class": cls_name,
                "id": stu_id,
                "name": stu_name,
                "scores": scores
            })
            
        return students