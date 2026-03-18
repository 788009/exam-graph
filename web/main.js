// 确保只在 pywebview 注入完成后再初始化 Vue
window.addEventListener('pywebviewready', function() {
    
    const app = Vue.createApp({
        data() {
            return {
                schema: [],           // 存储配置项的 JSON 骨架
                config: {},           // 存储真实的 TOML 配置数据
                currentTab: 'data',   // 当前选中的左侧菜单 key
                selectedFile: '',     // 选中的 Excel 文件路径
                isProcessing: false,  // 是否正在生成图表
                loading: true,        // 是否正在加载配置
                logs: ['[系统] 成绩可视化配置台初始化完成...'],
                isLogVisible: false,  // 控制日志面板显示状态，默认隐藏
                taskCompleted: false, // 标记任务是否已完成
                currentOutputDir: '', // 存储本次生成的专属文件夹路径
                diagnostics: null,    // 存储数据诊断结果
                parserRuleClicked: false, // 记录是否点击了“前往修改”
                // 预览相关状态
                showPreviewModal: false,
                previewImageSrc: '',
                isPreviewing: false,
                previewStudentName: ''
            };
        },
        computed: {
            // 获取当前选中模块的名称
            currentTabName() {
                const tab = this.schema.find(s => s.section_key === this.currentTab);
                return tab ? tab.section_name : '';
            },
            // 获取当前选中模块下的所有配置项
            currentFields() {
                const tab = this.schema.find(s => s.section_key === this.currentTab);
                return tab ? tab.items : [];
            }
        },
        mounted() {
            this.initData();
            // 将内部方法挂载到 window 上，供 Python 后端通过 evaluate_js 回调
            window.taskFinished = this.onTaskFinished;
            window.taskError = this.onTaskError;
            window.appendLog = this.appendLog;
        },
        methods: {
            // ===== 根据点号路径安全获取嵌套对象的辅助函数 =====
            getSectionData(path) {
                if (!this.config || !path) return undefined;
                let obj = this.config;
                const keys = path.split('.'); // 将 "plot.styles" 拆分成 ["plot", "styles"]
                for (let key of keys) {
                    if (obj[key] === undefined) return undefined;
                    obj = obj[key]; // 逐层深入
                }
                return obj;
            },

            async initData() {
                try {
                    // 1. 获取 JSON Schema
                    const schemaRes = await window.pywebview.api.get_schema();
                    
                    // 防御性判断：如果 Python 返回了错误对象
                    if (schemaRes && schemaRes.error) {
                        throw new Error(schemaRes.error);
                    }
                    // 防御性判断：如果不是数组
                    if (!Array.isArray(schemaRes)) {
                        throw new Error("Schema 格式不正确，应为数组");
                    }
                    
                    this.schema = schemaRes;
                    
                    // 2. 获取真实的 TOML 配置
                    const configRes = await window.pywebview.api.get_config();
                    if (configRes && configRes.error) {
                        throw new Error(configRes.error);
                    }
                    this.config = configRes;
                    
                    // 默认选中第一个 Tab
                    if (this.schema.length > 0) {
                        this.currentTab = this.schema[0].section_key;
                    }
                } catch (error) {
                    this.appendLog('[致命错误] 加载配置失败: ' + error.message);
                    alert("界面初始化失败：\n" + error.message + "\n\n请检查 web/config_schema.json 是否存在且格式正确。");
                } finally {
                    this.loading = false;
                }
            },

            async selectFile() {
                const filepath = await window.pywebview.api.choose_excel_file();
                if (filepath) {
                    this.selectedFile = filepath;
                    this.parserRuleClicked = false; // 换新文件时，重置按钮状态
                    this.appendLog(`[就绪] 已选择数据文件: ${filepath}`);
                    // 选中文件后立刻执行数据诊断
                    await this.runDiagnostics(filepath);
                }
            },

            // ===== 执行数据自检 =====
            async runDiagnostics(filepath) {
                try {
                    const res = await window.pywebview.api.preview_data(filepath);
                    if (res.status === 'success') {
                        this.diagnostics = res;
                    } else {
                        this.appendLog(`[自检失败] ${res.message}`);
                        this.diagnostics = null;
                    }
                } catch (error) {
                    console.error("自检请求出错:", error);
                }
            },

            // ===== 一键应用预测的列索引 =====
            async applyPredictions() {
                if (!this.diagnostics || Object.keys(this.diagnostics.predictions).length === 0) return;
                
                const preds = this.diagnostics.predictions;
                this.config.data.class_col = preds.class_col;
                this.config.data.student_id_col = preds.student_id_col;
                this.config.data.name_col = preds.name_col;
                
                this.appendLog('[系统] 已自动应用列索引修复。');
                await this.saveConfig(); // 自动保存
                await this.runDiagnostics(this.selectedFile); // 重新诊断以刷新 UI
            },

            // 专门处理点击修改解析规则的逻辑
            goToParserTab() {
                this.currentTab = 'parser';
                this.parserRuleClicked = true; // 触发按钮文字变身
            },

            // ===== 跳转到指定的配置标签页 =====
            jumpToTab(tabKey) {
                this.currentTab = tabKey;
            },

            async saveConfig() {
                this.isProcessing = true;
                this.appendLog('[系统] 正在保存配置...');
                
                try {
                    // 将前端绑定的 config 对象直接扔给 Python
                    const res = await window.pywebview.api.save_config(Vue.toRaw(this.config));
                    if (res.status === 'success') {
                        this.appendLog('[成功] 配置已成功保存到 config.toml！');
                        alert('配置保存成功！');

                        // 保存配置后，如果已经选了文件，用最新配置重新自检
                        if (this.selectedFile) {
                            await this.runDiagnostics(this.selectedFile);
                        }
                    } else {
                        this.appendLog(`[错误] 保存失败: ${res.message}`);
                        alert('保存失败，请查看底层日志。');
                    }
                } catch (error) {
                    this.appendLog(`[异常] 保存出错: ${error}`);
                } finally {
                    this.isProcessing = false;
                }
            },

            // 执行预览生成
            async previewPlot() {
                if (!this.selectedFile) return;
                
                this.isPreviewing = true;
                this.appendLog('====================================');
                this.appendLog('[预览] 正在生成首位同学的图表，请稍候...');
                
                try {
                    // 核心细节：预览前，先静默把前端的最新配置保存进 TOML！
                    // 否则 Python 读到的还是旧配置，预览就没意义了
                    await window.pywebview.api.save_config(Vue.toRaw(this.config));

                    const res = await window.pywebview.api.preview_plot(this.selectedFile);
                    
                    if (res.status === 'success') {
                        this.previewImageSrc = res.image_base64;
                        this.previewStudentName = res.student_name;
                        this.showPreviewModal = true; // 弹出遮罩层
                        this.appendLog(`[预览成功] 成功生成学生 [${res.student_name}] 的图表。`);
                    } else {
                        this.appendLog(`[预览失败] ${res.message}`);
                        alert(`预览生成失败:\n${res.message}`);
                    }
                } catch (error) {
                    this.appendLog(`[调用异常] 预览功能出错: ${error}`);
                } finally {
                    this.isPreviewing = false;
                }
            },

            async startTask() {
                if (!this.selectedFile) {
                    alert('请先选择一个 Excel 表格文件！');
                    return;
                }
                
                this.isProcessing = true;
                this.isLogVisible = true;
                this.taskCompleted = false;

                this.appendLog('====================================');
                this.appendLog(`[任务开始] 正在处理: ${this.selectedFile}`);
                
                try {
                    // 调用 Python 启动多进程任务
                    await window.pywebview.api.start_task(this.selectedFile);
                    // 注意：这里不设 isProcessing = false，因为后端是异步的，
                    // 状态恢复交给 window.taskFinished 和 window.taskError 处理
                } catch (error) {
                    this.appendLog(`[调用失败] 无法启动任务: ${error}`);
                    this.isProcessing = false;
                }
            },

            // 辅助功能：点击占位符标签时，自动将其插入到对应的输入框中，支持嵌套路径的占位符插入
            insertPlaceholder(sectionKey, itemKey, placeholder) {
                const targetObj = this.getSectionData(sectionKey);
                if (!targetObj) return;
                
                let currentValue = targetObj[itemKey] || '';
                targetObj[itemKey] = currentValue + placeholder;
            },

            // ===== 供 Python 调用的全局回调方法 =====
            
            appendLog(msg) {
                this.logs.push(msg);
                // 自动滚动到最底部
                this.$nextTick(() => {
                    const logContent = document.querySelector('.log-content');
                    if (logContent) {
                        logContent.scrollTop = logContent.scrollHeight;
                    }
                });
            },

            onTaskFinished(msg, outputDir) {
                this.appendLog(`[完成] ${msg}`);
                if (outputDir) {
                    this.appendLog(`[路径] 图表已保存至: ${outputDir}`);
                    this.currentOutputDir = outputDir; // 保存具体路径
                }
                this.isProcessing = false;
                this.taskCompleted = true; 
                
                // 加个小延时，确保 DOM 状态更新后再弹窗，体验更好
                setTimeout(() => alert('所有图表生成完毕！请前往 output 目录查看。'), 100);
            },

            onTaskError(msg) {
                this.appendLog(`[严重错误] ${msg}`);
                this.isProcessing = false;
                alert('任务执行过程中出错，请查看底层日志。');
            },

            async openFolder() {
                try {
                    // 将存储的路径传给 Python
                    const res = await window.pywebview.api.open_folder(this.currentOutputDir);
                    if (res.status === 'error') {
                        this.appendLog(`[错误] 无法打开文件夹: ${res.message}`);
                        alert('打开文件夹失败，请查看底层日志。');
                    } else {
                        this.appendLog('[系统] 已唤起系统资源管理器打开专属输出目录。');
                    }
                } catch (error) {
                    this.appendLog(`[调用失败] ${error}`);
                }
            },
        }
    });

    // 挂载 Vue 实例到 id="app" 的 div 上
    app.mount('#app');
});