# 成绩单拆分桌面界面：提供带序号的名单编辑、方案校验及逐人页数调整。
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from tkinterdnd2 import DND_FILES, TkinterDnD

from core import (OutputNaming, PersonPlan, SplitterError, build_plan, get_pdf_page_count,
                  page_difference, parse_names, planned_filenames, recalculate_ranges, split_pdf)

APP_TITLE = "成绩单 PDF 拆分工具"
BG, WHITE, STRIPE = "#f3f5f9", "#ffffff", "#f3f6fb"
INK, MUTED, BLUE = "#243247", "#64748b", "#2563eb"


def resource_path(filename: str) -> Path:
    """同时支持源码运行和单文件打包资源。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / filename


class TranscriptSplitterApp(TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.configure(background=BG)
        try:
            self.iconbitmap(str(resource_path("app.ico")))
        except tk.TclError:
            pass
        width = min(1100, self.winfo_screenwidth() - 80)
        height = min(760, self.winfo_screenheight() - 100)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(30, (self.winfo_screenheight() - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(880, width), min(520, height))
        self.pdf_path_var = tk.StringVar()
        self.pdf_display_var = tk.StringVar(value="选择或拖入一个 PDF")
        self.directory_pages_var = tk.IntVar(value=1)
        self.default_pages_var = tk.IntVar(value=2)
        self.fixed_number_var = tk.StringVar()
        self.start_number_var = tk.StringVar(value="1")
        self.sequence_digits_var = tk.StringVar(value="自动")
        self.export_directory_var = tk.BooleanVar(value=False)
        self.directory_number_var = tk.StringVar(value="0")
        self.filename_preview_var = tk.StringVar()
        self.summary_var = tk.StringVar(value="请选择 PDF · 粘贴姓名")
        self.result_var = tk.StringVar()
        self.count_var = tk.StringVar(value="0 人")
        self.plan_state_var = tk.StringVar()
        self.plan: list[PersonPlan] = []
        self.pdf_total_pages: int | None = None
        self.last_output_dir: Path | None = None
        self.plan_is_stale = True
        self.editor: tk.Entry | None = None
        self.edit_index: int | None = None
        self.page_labels: dict[int, tk.Label] = {}
        self._redraw_job: str | None = None
        self._style()
        self._build_ui()
        self.pdf_path_var.trace_add("write", self.update_pdf_display)
        self.update_names_appearance()
        self._enable_pdf_drop()
        for variable in (self.directory_pages_var, self.default_pages_var):
            variable.trace_add("write", lambda *_: self.mark_plan_stale())
        for variable in (self.fixed_number_var, self.start_number_var, self.sequence_digits_var,
                         self.export_directory_var, self.directory_number_var, self.directory_pages_var):
            variable.trace_add("write", self.update_naming_settings)
        self.update_naming_settings()
        self.names_text.bind("<<Modified>>", self.on_names_modified)
        self.names_text.bind("<Control-a>", self.select_all_names)
        self.names_text.bind("<Control-A>", self.select_all_names)
        self.names_text.edit_modified(False)
        self.after_idle(lambda: self.panes.sashpos(0, int(self.panes.winfo_width() * .30)))

    def _style(self) -> None:
        self.body_font = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.bold_font = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        self.row_height = self.body_font.metrics("linespace") + 12
        self.option_add("*Font", self.body_font)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", font=self.body_font, foreground=INK, background=BG)
        style.configure("Card.TFrame", background=WHITE)
        style.configure("Card.TLabel", background=WHITE)
        style.configure("Muted.TLabel", foreground=MUTED, background=WHITE)
        style.configure("Heading.TLabel", font=self.bold_font, background=WHITE)
        style.configure("TButton", padding=(12, 7), borderwidth=0, background="#e7edf5")
        style.map("TButton", background=[("active", "#dce5f2")], foreground=[("disabled", "#9aa6b5")])
        style.configure("Primary.TButton", background=BLUE, foreground=WHITE)
        style.map("Primary.TButton", background=[("disabled", "#dce3ed"), ("active", "#1d4ed8")],
                  foreground=[("disabled", "#8a98ab"), ("!disabled", WHITE)])
        style.configure("TEntry", padding=6, fieldbackground=WHITE)
        style.configure("TSpinbox", padding=5, arrowsize=14, fieldbackground=WHITE)
        style.configure("Treeview", rowheight=self.row_height, background=WHITE,
                        fieldbackground=WHITE, borderwidth=0)
        style.configure("Treeview.Heading", background="#eaf0f7", font=self.bold_font,
                        padding=(8, 8), relief="flat", borderwidth=0)
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#173d80")])

    def _build_ui(self) -> None:
        # 外层细边框在拖入文件时变蓝，提供明确且克制的接收反馈。
        self.drop_border = tk.Frame(
            self,
            background=BG,
            highlightthickness=2,
            highlightbackground=BG,
        )
        self.drop_border.pack(fill="both", expand=True)
        root = ttk.Frame(self.drop_border, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        settings = ttk.Frame(root, style="Card.TFrame", padding=8)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="PDF 文件", style="Card.TLabel").grid(row=0, column=0, padx=(0, 10))
        self.pdf_entry = ttk.Entry(settings, textvariable=self.pdf_display_var, state="readonly", foreground=MUTED, width=12)
        self.pdf_entry.grid(row=0, column=1, sticky="ew")
        file_actions = ttk.Frame(settings, style="Card.TFrame")
        file_actions.grid(row=0, column=2, padx=(10, 0))
        ttk.Button(file_actions, text="选择文件", command=self.choose_pdf).pack(side="left")
        ttk.Label(file_actions, text="支持拖入 PDF", style="Muted.TLabel").pack(side="left", padx=(10, 0))
        rules = ttk.Frame(settings, style="Card.TFrame")
        rules.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        rules.columnconfigure(5, weight=1)
        for column, title, variable, minimum in (
            (0, "目录页数", self.directory_pages_var, 0),
            (2, "默认每人页数", self.default_pages_var, 1),
        ):
            ttk.Label(rules, text=title, style="Card.TLabel").grid(row=0, column=column, padx=(0, 8))
            ttk.Spinbox(rules, from_=minimum, to=50, width=5, textvariable=variable).grid(row=0, column=column+1, padx=(0, 22))
        directory = ttk.Frame(rules, style="Card.TFrame")
        directory.grid(row=0, column=4, columnspan=2, sticky="w")
        ttk.Checkbutton(directory, text="导出目录", variable=self.export_directory_var).pack(side="left", padx=(0, 12))
        ttk.Label(directory, text="目录编号", style="Card.TLabel").pack(side="left", padx=(0, 8))
        self.directory_number_entry = ttk.Entry(directory, textvariable=self.directory_number_var, width=6)
        self.directory_number_entry.pack(side="left")

        naming = ttk.Frame(settings, style="Card.TFrame")
        naming.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        naming.columnconfigure(5, weight=1)
        for column, title, variable, width in (
            (0, "固定编号", self.fixed_number_var, 10),
            (2, "起始序号", self.start_number_var, 6),
        ):
            ttk.Label(naming, text=title, style="Card.TLabel").grid(row=0, column=column, padx=(0, 8))
            ttk.Entry(naming, textvariable=variable, width=width).grid(row=0, column=column + 1, padx=(0, 22))
        ttk.Label(naming, text="序号位数", style="Card.TLabel").grid(row=0, column=4, padx=(0, 8))
        self.sequence_digits_entry = ttk.Combobox(naming, textvariable=self.sequence_digits_var,
                                                 values=("自动", "2", "3", "4"), width=6)
        self.sequence_digits_entry.grid(row=0, column=5, sticky="w")
        self.filename_preview_label = ttk.Label(settings, textvariable=self.filename_preview_var, style="Muted.TLabel")
        self.filename_preview_label.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        settings.bind("<Configure>", lambda event: self.filename_preview_label.configure(wraplength=max(100, event.width - 24)))

        self.panes = ttk.Panedwindow(root, orient="horizontal")
        self.panes.grid(row=1, column=0, sticky="nsew")
        names_box = ttk.Frame(self.panes, style="Card.TFrame", padding=12)
        plan_box = ttk.Frame(self.panes, style="Card.TFrame", padding=12)
        self.panes.add(names_box, weight=3)
        self.panes.add(plan_box, weight=7)
        for box in (names_box, plan_box):
            box.columnconfigure(0, weight=1)
            box.rowconfigure(1, weight=1)
        header = ttk.Frame(names_box, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="输入姓名", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.count_var, style="Muted.TLabel").pack(side="right")
        self.names_border = names_area = tk.Frame(
            names_box, background=WHITE, highlightthickness=1,
            highlightbackground="#b8c5d6", highlightcolor=BLUE,
        )
        names_area.grid(row=1, column=0, sticky="nsew")
        names_area.columnconfigure(1, weight=1)
        names_area.rowconfigure(0, weight=1)
        self.gutter = tk.Canvas(names_area, width=42, highlightthickness=0, background=STRIPE)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.names_text = tk.Text(names_area, width=12, height=1, wrap="none", undo=True,
                                  font=self.body_font, borderwidth=0, highlightthickness=0,
                                  padx=8, pady=0, spacing1=6, spacing3=6,
                                  background=WHITE, foreground=INK, selectbackground="#bfdbfe", cursor="xterm")
        self.names_text.grid(row=0, column=1, sticky="nsew")
        # 提示层独立于姓名文本，复制、人数统计和撤销都不会读到提示内容。
        self.names_placeholder = tk.Label(
            self.names_text, text="在此输入或粘贴姓名\n每行一人，顺序与 PDF 一致",
            foreground=MUTED, background=WHITE, justify="left", anchor="nw",
            cursor="xterm", borderwidth=0, padx=0, pady=0,
        )
        self.names_placeholder.bind("<Button-1>", self.focus_names_input)
        self.names_text.bind("<FocusIn>", self.update_names_appearance)
        self.names_text.bind("<FocusOut>", self.update_names_appearance)
        names_scroll = ttk.Scrollbar(names_area, command=self.names_text.yview)
        names_scroll.grid(row=0, column=2, sticky="ns")
        def names_scrolled(first: str, last: str) -> None:
            names_scroll.set(first, last)
            self.redraw_gutter()
        self.names_text.configure(yscrollcommand=names_scrolled)
        self.names_text.bind("<Configure>", self.resize_names_input)
        self.names_text.tag_configure("stripe", background=STRIPE)
        self.names_horizontal = ttk.Scrollbar(names_area, orient="horizontal", command=self.names_text.xview)
        self.names_horizontal.grid(row=1, column=1, sticky="ew")
        self.names_text.configure(xscrollcommand=lambda first, last: self.update_horizontal(self.names_horizontal, first, last))
        ttk.Button(names_box, text="生成方案", command=self.generate_plan).grid(row=2, column=0, sticky="ew", pady=(12, 0))

        header = ttk.Frame(plan_box, style="Card.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="检查方案", style="Heading.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.plan_state_var, style="Muted.TLabel").pack(side="right")
        table = ttk.Frame(plan_box, style="Card.TFrame")
        table.grid(row=1, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(table, columns=("index", "name", "pages", "range"), show="headings", selectmode="browse", height=1)
        for key, label, width in (("index", "序号", 56), ("name", "姓名", 140), ("pages", "页数", 76), ("range", "PDF 页码", 112)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=width, anchor="w" if key == "name" else "center", stretch=key == "name")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.tag_configure("even", background=WHITE)
        self.tree.tag_configure("odd", background=STRIPE)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        def table_scrolled(first: str, last: str) -> None:
            scroll.set(first, last)
            self.schedule_cell_redraw()
        self.tree.configure(yscrollcommand=table_scrolled)
        self.table_horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.table_horizontal.grid(row=1, column=0, sticky="ew")
        def table_xscrolled(first: str, last: str) -> None:
            self.update_horizontal(self.table_horizontal, first, last)
            self.schedule_cell_redraw()
        self.tree.configure(xscrollcommand=table_xscrolled)
        self.tree.bind("<Double-1>", self.begin_page_edit)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.schedule_cell_redraw())
        self.tree.bind("<Configure>", lambda _: self.schedule_cell_redraw())
        actions = ttk.Frame(plan_box, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(actions, text="页数", style="Muted.TLabel").pack(side="left", padx=(0, 8))
        self.quick_buttons = []
        for pages in (2, 3, 4):
            button = ttk.Button(actions, text=f"{pages} 页", width=5, command=lambda p=pages: self.apply_selected_pages(p), state="disabled")
            button.pack(side="left", padx=(0, 6))
            self.quick_buttons.append(button)
        self.edit_error = ttk.Label(plan_box, text="", foreground="#b42318", style="Card.TLabel")
        self.edit_error.grid(row=3, column=0, sticky="w")
        self.edit_error.grid_remove()

        bottom = ttk.Frame(root)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        self.summary_label = ttk.Label(bottom, textvariable=self.summary_var)
        self.summary_label.grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, textvariable=self.result_var, foreground=MUTED).grid(row=1, column=0, sticky="w")
        self.open_button = ttk.Button(bottom, text="打开结果文件夹", command=self.open_result_folder, state="disabled")
        self.open_button.grid(row=0, column=1, rowspan=2, padx=10)
        self.split_button = ttk.Button(bottom, text="开始拆分", style="Primary.TButton", command=self.perform_split, state="disabled")
        self.split_button.grid(row=0, column=2, rowspan=2)

    @staticmethod
    def update_horizontal(scrollbar: ttk.Scrollbar, first: str, last: str) -> None:
        """只在内容横向溢出时显示滚动条，保留原有滚动能力。"""
        scrollbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            scrollbar.grid_remove()
        else:
            scrollbar.grid()

    def update_pdf_display(self, *_args: object) -> None:
        # 展示文本与真实路径分离，避免将占位提示当作文件路径使用。
        path = self.pdf_path_var.get()
        self.pdf_display_var.set(path or "选择或拖入一个 PDF")
        self.pdf_entry.configure(foreground=INK if path else MUTED)

    def read_naming(self) -> OutputNaming:
        def nonnegative_number(raw: str, title: str) -> int:
            value = raw.strip()
            if not value.isascii() or not value.isdecimal():
                raise SplitterError(f"{title}必须是大于或等于 0 的整数。")
            return int(value)

        digits = self.sequence_digits_var.get().strip()
        export_directory = self.export_directory_var.get() and self.directory_pages_var.get() > 0
        return OutputNaming(
            fixed_number=self.fixed_number_var.get().strip(),
            start_number=nonnegative_number(self.start_number_var.get(), "起始序号"),
            sequence_digits=None if digits == "自动" else nonnegative_number(digits, "序号位数"),
            export_directory=export_directory,
            directory_number=nonnegative_number(self.directory_number_var.get(), "目录编号") if export_directory else 0,
        )

    def update_naming_preview(self) -> str | None:
        try:
            directory_pages = self.directory_pages_var.get()
            naming = self.read_naming()
            sample_plan = self.plan if self.plan and not self.plan_is_stale else [PersonPlan("姓名")]
            filenames = planned_filenames(sample_plan, directory_pages, naming)
            examples = filenames if len(filenames) <= 2 else [filenames[0], filenames[1], "…", filenames[-1]]
            self.filename_preview_var.set("文件名预览：" + " · ".join(examples))
            return None
        except (ValueError, tk.TclError, SplitterError) as exc:
            error = str(exc) if isinstance(exc, SplitterError) else "请填写有效的目录页数和编号。"
            self.filename_preview_var.set(error)
            return error

    def update_naming_settings(self, *_args: object) -> None:
        try:
            enabled = self.export_directory_var.get() and self.directory_pages_var.get() > 0
        except tk.TclError:
            enabled = False
        self.directory_number_entry.configure(state="normal" if enabled else "disabled")
        self.result_var.set("")
        self.update_naming_preview()
        self.update_integrity_status()

    def focus_names_input(self, _event: tk.Event | None = None) -> str:
        self.names_placeholder.place_forget()
        self.names_text.focus_set()
        return "break"

    def resize_names_input(self, _event: tk.Event) -> None:
        self.names_placeholder.configure(wraplength=max(40, self.names_text.winfo_width() - 20))
        self.redraw_gutter()

    def update_names_appearance(self, _event: tk.Event | None = None) -> None:
        has_names = bool(self.names_text.get("1.0", "end-1c").strip())
        focused = self.focus_get() == self.names_text
        self.names_border.configure(highlightbackground=BLUE if focused else "#b8c5d6")
        if has_names:
            self.gutter.grid()
        else:
            self.gutter.grid_remove()
            self.names_text.tag_remove("stripe", "1.0", "end")
        # 点击时露出插入光标；清空内容或空白失焦时恢复提示。
        entering = _event is not None and _event.type == tk.EventType.FocusIn
        if not has_names and not entering:
            self.names_placeholder.place(x=8, y=8, relwidth=1, width=-16)
        else:
            self.names_placeholder.place_forget()

    def _enable_pdf_drop(self) -> None:
        """让整个窗口内的控件都能接收资源管理器中的 PDF。"""
        def register(widget: tk.Misc) -> None:
            widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            widget.dnd_bind("<<DropEnter>>", self.on_drop_enter)  # type: ignore[attr-defined]
            widget.dnd_bind("<<DropLeave>>", self.on_drop_leave)  # type: ignore[attr-defined]
            widget.dnd_bind("<<Drop>>", self.on_pdf_drop)  # type: ignore[attr-defined]
            for child in widget.winfo_children():
                register(child)

        register(self)

    def on_drop_enter(self, event: tk.Event) -> str:
        self.drop_border.configure(highlightbackground=BLUE, background=BLUE)
        return getattr(event, "action", "copy")

    def on_drop_leave(self, event: tk.Event | None = None) -> str:
        self.drop_border.configure(highlightbackground=BG, background=BG)
        return getattr(event, "action", "copy") if event else "copy"

    def on_pdf_drop(self, event: tk.Event) -> str:
        self.on_drop_leave(event)
        # splitlist 能正确拆开带空格、中文或花括号的 Windows 路径。
        paths = [Path(value) for value in self.tk.splitlist(event.data)]
        self.load_dropped_files(paths)
        return getattr(event, "action", "copy")

    def load_dropped_files(self, paths: list[Path]) -> bool:
        """校验拖入内容，只接收一个存在的 PDF 文件。"""
        if len(paths) != 1:
            messagebox.showwarning("无法载入", "请一次只拖入一个 PDF 文件。")
            return False
        path = paths[0]
        if path.suffix.lower() != ".pdf" or not path.is_file():
            messagebox.showwarning("无法载入", "请拖入一个有效的 PDF 文件。")
            return False
        return self.load_pdf(path)

    def select_all_names(self, _event: tk.Event) -> str:
        self.names_text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def on_names_modified(self, _event: tk.Event | None = None) -> None:
        if not self.names_text.edit_modified():
            return
        self.names_text.edit_modified(False)
        self.mark_plan_stale()
        self.names_text.tag_remove("stripe", "1.0", "end")
        lines = self.names_text.get("1.0", "end-1c").split("\n")
        for line in range(2, len(lines) + 1, 2):
            self.names_text.tag_add("stripe", f"{line}.0", f"{line + 1}.0")
        count = sum(bool(line.strip()) for line in lines)
        self.count_var.set(f"{count} 人")
        self.update_names_appearance()
        self.redraw_gutter()

    def redraw_gutter(self) -> None:
        # 序号单独绘制，不污染文本；空行跳过，编号与核心解析结果一致。
        self.gutter.delete("all")
        count = 0
        for line, name in enumerate(self.names_text.get("1.0", "end-1c").split("\n"), 1):
            if name.strip():
                count += 1
            info = self.names_text.dlineinfo(f"{line}.0")
            if info is None:
                continue
            _, y, _, height, _ = info
            self.gutter.create_rectangle(0, y, self.gutter.winfo_width(), y + height, fill=STRIPE if line % 2 == 0 else WHITE, outline="")
            if name.strip():
                self.gutter.create_text(self.gutter.winfo_width() - 10, y + height / 2, text=str(count), anchor="e", fill=MUTED, font=self.body_font)

    def set_editing_enabled(self, enabled: bool) -> None:
        for button in self.quick_buttons:
            button.configure(state="normal" if enabled else "disabled")

    def mark_plan_stale(self) -> None:
        self.cancel_page_edit()
        self.plan_is_stale = True
        self.split_button.configure(state="disabled")
        self.set_editing_enabled(False)
        self.result_var.set("")
        self.update_naming_preview()
        if self.plan:
            self.plan_state_var.set("待重新生成")
            self.summary_var.set("输入已修改 · 请重新生成方案")
            self.summary_label.configure(foreground="#a15c00")

    def choose_pdf(self) -> None:
        filename = filedialog.askopenfilename(title="选择成绩单 PDF", filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")])
        if not filename:
            return
        self.load_pdf(Path(filename))

    def load_pdf(self, path: Path) -> bool:
        """读取并载入 PDF；选择文件与拖放共用同一条状态更新路径。"""
        try:
            total_pages = get_pdf_page_count(path)
        except SplitterError as exc:
            messagebox.showerror("无法载入 PDF", str(exc))
            return False
        self.mark_plan_stale()
        self.pdf_path_var.set(str(path))
        self.plan = []
        self.pdf_total_pages = total_pages
        self.last_output_dir = None
        self.open_button.configure(state="disabled")
        self.clear_tree()
        self.plan_state_var.set("")
        self.summary_var.set(f"已载入 PDF · {total_pages} 页 · 请生成方案")
        self.summary_label.configure(foreground=MUTED)
        return True

    def generate_plan(self) -> None:
        self.mark_plan_stale()
        try:
            path = self.pdf_path_var.get().strip()
            if not path:
                raise SplitterError("请先选择 PDF 文件。")
            total = get_pdf_page_count(path)
            plan = build_plan(parse_names(self.names_text.get("1.0", "end")), int(self.directory_pages_var.get()), int(self.default_pages_var.get()), allow_duplicate_names=True)
            self.pdf_total_pages, self.plan = total, plan
            self.plan_is_stale = False
            self.plan_state_var.set("")
            self.refresh_tree()
            self.set_editing_enabled(True)
            self.update_integrity_status()
        except (ValueError, tk.TclError):
            messagebox.showerror("输入错误", "目录页数和默认页数必须是整数。")
        except SplitterError as exc:
            messagebox.showerror("无法生成方案", str(exc))

    def clear_tree(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.schedule_cell_redraw()

    def refresh_tree(self, selected_index: int | None = None) -> None:
        position = self.tree.yview()[0]
        if selected_index is None:
            self.clear_tree()
        for index, item in enumerate(self.plan):
            values = (index + 1, item.name, item.page_count, f"{item.start_page}-{item.end_page}")
            tags = ("odd" if index % 2 else "even",)
            if self.tree.exists(str(index)):
                self.tree.item(str(index), values=values, tags=tags)
            else:
                self.tree.insert("", "end", iid=str(index), values=values, tags=tags)
        if self.plan:
            selected = str(0 if selected_index is None else selected_index)
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.tree.yview_moveto(0 if selected_index is None else position)
        self.schedule_cell_redraw()

    def schedule_cell_redraw(self) -> None:
        if self._redraw_job is None:
            self._redraw_job = self.after_idle(self.redraw_page_cells)

    def redraw_page_cells(self) -> None:
        self._redraw_job = None
        visible = set()
        # ttk 只能整行加粗，因此仅在特殊页数单元格上覆盖同色文字。
        try:
            default = self.default_pages_var.get()
        except tk.TclError:
            default = None
        for index, item in enumerate(self.plan):
            box = self.tree.bbox(str(index), "pages")
            if not box or item.page_count == default:
                continue
            visible.add(index)
            x, y, width, height = box
            selected = str(index) in self.tree.selection()
            if index not in self.page_labels:
                label = tk.Label(self.tree, font=self.bold_font, borderwidth=0)
                label.bind("<Button-1>", lambda _, i=index: self.tree.selection_set(str(i)))
                label.bind("<Double-1>", lambda _, i=index: self.start_page_editor(i))
                label.bind("<MouseWheel>", lambda e: self.tree.yview_scroll(-int(e.delta / 120), "units"))
                self.page_labels[index] = label
            label = self.page_labels[index]
            label.configure(text=str(item.page_count),
                            background="#dbeafe" if selected else (STRIPE if index % 2 else WHITE),
                            foreground="#173d80" if selected else INK)
            label.place(x=x+1, y=y+1, width=width-2, height=height-2)
        for index in set(self.page_labels) - visible:
            self.page_labels.pop(index).destroy()
        if self.editor is not None and self.edit_index is not None:
            box = self.tree.bbox(str(self.edit_index), "pages")
            if box:
                self.editor.place(x=box[0], y=box[1], width=box[2], height=box[3])
                self.editor.lift()
            else:
                self.commit_page_edit()

    def begin_page_edit(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#3":
            self.start_page_editor(int(row))

    def start_page_editor(self, index: int) -> None:
        if self.plan_is_stale or not self.commit_page_edit():
            return
        box = self.tree.bbox(str(index), "pages")
        if not box:
            return
        self.tree.selection_set(str(index))
        self.edit_index = index
        self.editor = tk.Entry(self.tree, justify="center", font=self.body_font,
                               highlightthickness=2, highlightbackground=BLUE, highlightcolor=BLUE, borderwidth=0)
        self.editor.insert(0, str(self.plan[index].page_count))
        self.editor.place(x=box[0], y=box[1], width=box[2], height=box[3])
        self.editor.select_range(0, "end")
        self.editor.focus_set()
        self.editor.bind("<Return>", lambda _: self.commit_page_edit())
        self.editor.bind("<Escape>", lambda _: self.cancel_page_edit())
        self.editor.bind("<FocusOut>", lambda _: self.commit_page_edit())

    def cancel_page_edit(self) -> None:
        editor, self.editor = self.editor, None
        self.edit_index = None
        if editor is not None:
            editor.destroy()
        if hasattr(self, "edit_error"):
            self.edit_error.grid_remove()

    def commit_page_edit(self) -> bool:
        if self.editor is None:
            return True
        try:
            pages = int(self.editor.get())
            if pages < 1:
                raise ValueError
        except ValueError:
            self.editor.configure(highlightbackground="#b42318", highlightcolor="#b42318")
            self.edit_error.configure(text="页数须为大于 0 的整数")
            self.edit_error.grid()
            return False
        index = self.edit_index
        self.cancel_page_edit()
        if index is not None and not self.plan_is_stale:
            self.update_pages(index, pages)
        return True

    def apply_selected_pages(self, pages: int) -> None:
        if self.plan_is_stale or not self.tree.selection():
            return
        index = int(self.tree.selection()[0])
        self.cancel_page_edit()
        self.update_pages(index, pages)

    def update_pages(self, index: int, pages: int) -> None:
        self.plan[index].page_count = pages
        recalculate_ranges(self.plan, int(self.directory_pages_var.get()))
        self.result_var.set("")
        self.refresh_tree(selected_index=index)
        self.update_integrity_status()

    def update_integrity_status(self) -> None:
        naming_error = self.update_naming_preview()
        if not self.plan or self.pdf_total_pages is None or self.plan_is_stale:
            self.split_button.configure(state="disabled")
            return
        diff = page_difference(self.plan, int(self.directory_pages_var.get()), self.pdf_total_pages)
        status = "校验通过" if diff == 0 else (f"剩余 {diff} 页" if diff > 0 else f"超出 {-diff} 页")
        if diff == 0 and naming_error:
            status = "请修正命名设置"
        self.summary_var.set(f"{len(self.plan)} 人 · {self.pdf_total_pages} 页 · {status}")
        valid = diff == 0 and naming_error is None
        self.summary_label.configure(foreground="#16805d" if valid else "#a15c00")
        self.split_button.configure(state="normal" if valid else "disabled")

    def perform_split(self) -> None:
        if self.plan_is_stale or not self.commit_page_edit():
            return
        try:
            naming = self.read_naming()
            directory_pages = int(self.directory_pages_var.get())
            output = split_pdf(self.pdf_path_var.get().strip(), self.plan, directory_pages, naming=naming)
            self.last_output_dir = output
            self.result_var.set(f"已生成 {len(planned_filenames(self.plan, directory_pages, naming))} 个 PDF")
            self.open_button.configure(state="normal")
        except (ValueError, tk.TclError):
            messagebox.showerror("输入错误", "目录页数必须是整数。")
        except SplitterError as exc:
            messagebox.showerror("拆分失败", str(exc))

    def open_result_folder(self) -> None:
        if not self.last_output_dir or not self.last_output_dir.exists():
            messagebox.showinfo("提示", "结果文件夹不存在，请先完成拆分。")
            return
        try:
            path = str(self.last_output_dir)
            if sys.platform.startswith("win"):
                os.startfile(path)
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", path], check=False)
        except Exception as exc:
            messagebox.showerror("无法打开文件夹", str(exc))


def main() -> None:
    app = TranscriptSplitterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
