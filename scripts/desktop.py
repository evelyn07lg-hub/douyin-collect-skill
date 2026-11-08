"""Independent desktop entrypoint; Python and Edge are the only initial prerequisites."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    message = 'Collect needs Python with Tkinter. Reinstall Python from python.org with Tcl/Tk enabled.'
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, 'Collect', 16)
    raise SystemExit(message)
from douyin_viral_collector.desktop_runner import DesktopRunner

STATUS = {'discovered': '等待识别', 'processing': '识别中', 'waiting_media': '需要原视频',
    'waiting_subtitles': '需要字幕画面', 'failed': '待重试', 'ready_to_archive': '可导出',
    'exported_local': '已导出 Word', 'archived': '已归档', 'already_present': '已收录',
    'duplicate_review': '疑似重复，待核对', 'uncertain': '需要核对'}


class App(tk.Tk):
    def __init__(self, root=ROOT):
        super().__init__()
        self.project = Path(root)
        self.title('Collect · 文稿工作台')
        width=min(1100,self.winfo_screenwidth()-80)
        height=min(820,self.winfo_screenheight()-110)
        self.geometry(f'{width}x{height}')
        self.minsize(900, 620)
        self.configure(bg='#f3f5fa')
        self.events = queue.Queue()
        self.runner = DesktopRunner(self.project, self.events.put)
        self.busy = False
        self.last_file = None
        self.items_by_row = {}
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background='#f3f5fa')
        style.configure('TFrame', background='#f3f5fa')
        style.configure('Card.TFrame', background='white')
        style.configure('TLabel', foreground='#334155')
        style.configure('Card.TLabel', background='white')
        style.configure('TButton', padding=(14, 9))
        style.configure('Primary.TButton', background='#4f46e5', foreground='white')
        style.map('Primary.TButton', background=[('active', '#4338ca'), ('disabled', '#a5b4fc')])
        style.configure('TNotebook', background='#f3f5fa', borderwidth=0)
        style.configure('TNotebook.Tab', padding=(20, 12), background='#e9edf5', foreground='#64748b', borderwidth=0)
        style.map('TNotebook.Tab', background=[('selected', 'white')], foreground=[('selected', '#4f46e5')])
        style.configure('TButton', background='white', foreground='#334155', bordercolor='#dce3ee', lightcolor='#dce3ee', darkcolor='#dce3ee')
        style.configure('TEntry', fieldbackground='white', bordercolor='#cbd5e1', lightcolor='#cbd5e1', darkcolor='#cbd5e1')
        style.configure('TProgressbar', background='#4f46e5', troughcolor='#e2e8f0', borderwidth=0)
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'))
        header = tk.Frame(self, bg='#111827', height=104)
        header.pack(fill='x')
        header.pack_propagate(False)
        tk.Label(header, text='Collect', font=('Segoe UI', 27, 'bold'), fg='white', bg='#111827').pack(side='left', padx=(28, 14))
        tk.Label(header, text='文稿工作台\n把分散的作品，整理成自己的文稿库', justify='left',
            font=('Microsoft YaHei UI', 11), fg='#cbd5e1', bg='#111827').pack(side='left')
        tk.Label(header, text='独立运行  /  本地 Word', font=('Microsoft YaHei UI', 10),
            fg='#c7d2fe', bg='#111827').pack(side='right', padx=28)
        main = ttk.Frame(self, padding=(24, 18))
        main.pack(fill='both', expand=True)
        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill='both', expand=True)
        setup_host = ttk.Frame(self.tabs, style='Card.TFrame')
        canvas = tk.Canvas(setup_host, bg='white', highlightthickness=0)
        scrolling = ttk.Scrollbar(setup_host, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrolling.set)
        scrolling.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        setup = ttk.Frame(canvas, padding=22, style='Card.TFrame')
        form_window = canvas.create_window((0,0), window=setup, anchor='nw')
        setup.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(form_window, width=event.width))
        works = ttk.Frame(self.tabs, padding=16)
        logs = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(setup_host, text='开始整理')
        self.tabs.add(works, text='作品与补充素材')
        self.tabs.add(logs, text='运行记录')
        setup.columnconfigure(0, weight=1)
        ttk.Label(setup, text='选择账号，设好条件，其余交给本地工作台。', style='Card.TLabel',
            font=('Microsoft YaHei UI', 15, 'bold')).grid(row=0, column=0, sticky='w', pady=(0, 14))
        ttk.Label(setup, text='账号主页 / 抖音分享文字 · 每条一行', style='Card.TLabel').grid(row=1, column=0, sticky='w')
        self.profiles = tk.Text(setup, height=4, font=('Consolas', 10), relief='flat', bd=0, highlightthickness=1, highlightbackground='#cbd5e1',
            bg='#f8fafc', fg='#1e293b', padx=10, pady=8, wrap='word')
        self.profiles.grid(row=2, column=0, sticky='ew', pady=(7, 6))
        ttk.Label(setup, text='可直接粘贴抖音复制的整段文字或短链接；作品链接会尝试识别作者账号。',
            style='Card.TLabel', foreground='#64748b').grid(row=3, column=0, sticky='w')
        options = ttk.Frame(setup, style='Card.TFrame')
        options.grid(row=4, column=0, sticky='ew', pady=(20, 14))
        ttk.Label(options, text='点赞门槛', style='Card.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 10))
        self.minimum = tk.StringVar(value='500')
        ttk.Spinbox(options, from_=0, to=100000000, textvariable=self.minimum, width=10).grid(row=0, column=1)
        self.comparison = tk.StringVar(value='不少于')
        ttk.Combobox(options, state='readonly', values=['不少于', '严格超过'], textvariable=self.comparison,
            width=10).grid(row=0, column=2, padx=(10, 28))
        ttk.Label(options, text='本地模型', style='Card.TLabel').grid(row=0, column=3, padx=(0, 10))
        self.model = tk.StringVar(value='标准 · 下载较小')
        ttk.Combobox(options, state='readonly', width=24, textvariable=self.model,
            values=['标准 · 下载较小', '精细 · large-v3-turbo']).grid(row=0, column=4)
        browser_row=ttk.Frame(setup,style='Card.TFrame')
        browser_row.grid(row=5,column=0,sticky='w',pady=(0,12))
        ttk.Label(browser_row,text='采集浏览器',style='Card.TLabel').pack(side='left',padx=(0,12))
        self.browser=tk.StringVar(value='Edge')
        ttk.Combobox(browser_row,state='readonly',values=['Edge','Chrome'],textvariable=self.browser,width=18).pack(side='left')
        output = ttk.Frame(setup, style='Card.TFrame')
        output.grid(row=6, column=0, sticky='ew')
        output.columnconfigure(1, weight=1)
        ttk.Label(output, text='文稿保存到', style='Card.TLabel').grid(row=0, column=0, padx=(0, 12))
        self.output = tk.StringVar(value=str(self.project / 'exports'))
        ttk.Entry(output, textvariable=self.output).grid(row=0, column=1, sticky='ew')
        ttk.Button(output, text='选择文件夹', command=self.choose_output).grid(row=0, column=2, padx=(10, 0))
        actions = ttk.Frame(setup, style='Card.TFrame')
        actions.grid(row=7, column=0, sticky='w', pady=(24, 14))
        self.start_button = ttk.Button(actions, text='开始整理并生成 Word', style='Primary.TButton', command=self.start)
        self.start_button.pack(side='left', padx=(0, 10))
        self.login_button = ttk.Button(actions, text='登录 / 重新登录', command=lambda: self.start(True))
        self.login_button.pack(side='left', padx=(0, 10))
        self.export_button = ttk.Button(actions, text='仅导出已有稿件', command=lambda: self.task(self.runner.export))
        self.export_button.pack(side='left')
        ttk.Label(setup, text='首次使用自动准备环境和模型。出现登录提示时，在所选浏览器中完成验证，再点击下方继续。',
            style='Card.TLabel', foreground='#64748b').grid(row=8, column=0, sticky='w', pady=(0, 9))
        ttk.Label(setup, text='默认生成本地自动识别稿；共享文档由博主自行创建和开启。复杂人名、专业词建议复核。',
            style='Card.TLabel', foreground='#64748b').grid(row=9, column=0, sticky='w')
        toolbar = ttk.Frame(works)
        toolbar.pack(fill='x', pady=(0, 12))
        ttk.Button(toolbar, text='刷新作品列表', command=self.refresh_items).pack(side='left')
        self.bind_button = ttk.Button(toolbar, text='为选中作品关联原视频', command=self.bind_media)
        self.bind_button.pack(side='left', padx=10)
        columns = ('account', 'date', 'title', 'likes', 'status')
        self.tree = ttk.Treeview(works, columns=columns, show='headings', selectmode='browse')
        for key, label, width in [('account', '账号', 140), ('date', '发布时间', 150), ('title', '作品', 350),
                                  ('likes', '点赞', 70), ('status', '处理状态', 145)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60, stretch=key == 'title')
        self.tree.pack(fill='both', expand=True)
        ttk.Label(works, text='有访问限制或缺少素材时会保留待处理状态；可关联你有权使用的原视频后继续，不会编造正文。',
            foreground='#64748b').pack(anchor='w', pady=(12, 0))
        self.log = tk.Text(logs, wrap='word', font=('Consolas', 10), bg='#0f172a', fg='#dbeafe',
            relief='flat', state='disabled', padx=12, pady=12)
        self.log.pack(fill='both', expand=True)
        bottom = ttk.Frame(main, padding=(0, 14, 0, 0))
        bottom.pack(fill='x')
        self.stage = tk.StringVar(value='就绪 · 无需启动 Codex')
        ttk.Label(bottom, textvariable=self.stage).pack(anchor='w')
        self.progress = ttk.Progressbar(bottom, mode='indeterminate')
        self.progress.pack(fill='x', pady=(8, 10))
        controls = ttk.Frame(bottom)
        controls.pack(fill='x')
        self.continue_button = ttk.Button(controls, text='登录完成，继续', state='disabled', command=self.continue_login)
        self.continue_button.pack(side='left')
        self.cancel_button = ttk.Button(controls, text='停止当前任务', state='disabled', command=self.runner.cancel)
        self.cancel_button.pack(side='left', padx=10)
        self.open_file_button = ttk.Button(controls, text='用 WPS 打开文稿', state='disabled', command=self.open_file)
        self.open_file_button.pack(side='right')
        ttk.Button(controls, text='打开输出文件夹', command=self.open_folder).pack(side='right', padx=10)
        self.load_config()
        self.refresh_items()
        self.after(100, self.drain)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def load_config(self):
        try:
            config = self.runner.config()
            self.browser.set('Chrome' if config.get('browser')=='chrome' else 'Edge')
            urls = [p.get('url') or 'https://www.douyin.com/user/' + p['sec_uid'] for p in config.get('public_profiles', [])]
            self.profiles.insert('1.0', '\n'.join(urls))
            self.minimum.set(str(config.get('minimum_likes', config.get('threshold', 500))))
            if 'threshold' in config and 'minimum_likes' not in config:
                self.comparison.set('严格超过')
            output = config.get('word_export', {}).get('output_dir')
            if output:
                path = Path(output)
                self.output.set(str(path if path.is_absolute() else self.project / path))
            if 'large-v3-turbo' in config.get('model', ''):
                self.model.set('精细 · large-v3-turbo')
        except (ValueError, OSError):
            self.stage.set('配置需要检查，请查看或备份 config.json 后重试。')

    def start(self, login_only=False):
        values = dict(profiles=self.profiles.get('1.0', 'end'), minimum=self.minimum.get(),
            strict=self.comparison.get() == '严格超过', output_dir=self.output.get() or 'exports',
            model='large-v3-turbo' if self.model.get().startswith('精细') else 'small', login_only=login_only, browser=self.browser.get().lower())
        try:
            self.runner.validate(values['profiles'], values['minimum'])
        except ValueError as exc:
            messagebox.showerror('请检查输入', str(exc), parent=self)
            return
        self.task(lambda: self.runner.start(**values))

    def task(self, action):
        if self.busy:
            return
        self.busy = True
        self.runner.cancelled.clear()
        self.progress.start(12)
        for button in (self.start_button, self.login_button, self.export_button, self.bind_button):
            button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.stage.set('正在准备')
        def work():
            try:
                action()
                self.events.put({'kind': 'finished'})
            except Exception as exc:
                self.events.put({'kind': 'error', 'text': str(exc)})
        threading.Thread(target=work, daemon=True).start()

    def drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                kind = event['kind']
                if kind in ('stage', 'error'):
                    self.stage.set(event['text'])
                if kind == 'login_required':
                    self.continue_button.configure(state='normal')
                    self.stage.set('请在所选浏览器中登录或完成验证，再点击“登录完成，继续”。')
                if kind == 'export':
                    self.last_file = event.get('path')
                    if self.last_file:
                        self.open_file_button.configure(state='normal')
                    self.stage.set(f"已生成 Word：{event.get('count', 0)}篇；待处理：{event.get('pending_count', 0)}篇。")
                if kind in ('log', 'error'):
                    self.log.configure(state='normal')
                    self.log.insert('end', event.get('text', '') + '\n')
                    if int(self.log.index('end-1c').split('.')[0]) > 1500:
                        self.log.delete('1.0', '300.0')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                if kind in ('finished', 'error'):
                    self.busy = False
                    self.progress.stop()
                    self.cancel_button.configure(state='disabled')
                    self.continue_button.configure(state='disabled')
                    for button in (self.start_button, self.login_button, self.export_button, self.bind_button):
                        button.configure(state='normal')
                    self.refresh_items()
        except queue.Empty:
            pass
        self.after(100, self.drain)

    def continue_login(self):
        if self.runner.continue_login():
            self.continue_button.configure(state='disabled')
            self.stage.set('正在核对账号，请稍候。')

    def choose_output(self):
        folder = filedialog.askdirectory(parent=self, title='选择 Word 保存文件夹')
        if folder:
            self.output.set(folder)

    def refresh_items(self):
        try:
            items = self.runner.items()
            self.tree.delete(*self.tree.get_children())
            self.items_by_row = {}
            for index, item in enumerate(items):
                key = str(index)
                self.items_by_row[key] = item
                self.tree.insert('', 'end', iid=key, values=(item['account'], item['date'], item['title'],
                    item['likes'], STATUS.get(item['status'], item['status'])))
        except (OSError, ValueError, __import__('sqlite3').Error) as exc:
            self.events.put({'kind': 'log', 'text': '作品列表暂不可读：' + str(exc)})

    def bind_media(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo('选择作品', '请先在列表中选中需要补充原视频的作品。', parent=self)
            return
        item = self.items_by_row[selected[0]]
        if item['status'] not in ('waiting_media', 'waiting_subtitles', 'failed', 'discovered'):
            messagebox.showinfo('保留现有稿件', '这篇作品不属于待补充素材状态，工作台不会覆盖已有校订。', parent=self)
            return
        file = filedialog.askopenfilename(parent=self, title='选择这篇作品对应的原视频',
            filetypes=[('视频文件', '*.mp4 *.mov *.mkv *.webm *.avi'), ('所有文件', '*.*')])
        if file:
            self.task(lambda: self.runner.bind_and_process(item['id'], file))

    def open_file(self):
        if self.last_file and Path(self.last_file).is_file():
            from douyin_viral_collector.wps_local import open_document
            try:open_document(self.last_file)
            except RuntimeError as exc:messagebox.showinfo('使用 WPS 打开',str(exc),parent=self)

    def open_folder(self):
        folder = Path(self.output.get())
        if not folder.is_absolute():
            folder = self.project / folder
        folder.mkdir(parents=True, exist_ok=True)
        self.open_path(folder)

    def open_path(self, path):
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])

    def close(self):
        if self.busy and not messagebox.askyesno('停止整理', '当前任务还在进行，确定停止并关闭吗？', parent=self):
            return
        self.runner.cancel()
        self.destroy()


if __name__ == '__main__':
    App().mainloop()
