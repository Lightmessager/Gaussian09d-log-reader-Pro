#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gaussian Log 热力学数据提取器 - 增强 GUI 版
====================================================================
基础功能（维持原版）：
  - 批量添加文件 / 文件夹，自动隐藏 .log 后缀
  - 取最终 SCF 能量（最后一次出现）
  - 提取 Gibbs 热校正、总自由能
  - 多线程提取、详细失败原因、导出 CSV

高级功能（点击「高级功能」展开）：
  - 选择能量类型：SCF / Gibbs热校正 / 总自由能
  - 设定能量零点（基准物种）
  - 自定义数学表达式计算相对能量（文件名作变量，如 TS1 - R + 0.5*P）
  - 自定义物种显示顺序（拖拽行 / 上下移动）
  - 单位切换：Hartree / kcal/mol
  - 实时预览结果表格
  - 反应坐标能量剖面图（Reaction Profile）
  - 导出相对能量结果 CSV、保存图表
====================================================================
依赖：Python 3.7+ 标准库 + matplotlib + numpy
"""

import os
import re
import ast
import csv
import threading
import operator

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from pathlib import Path

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import numpy as np
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ============================ 主题配色 ============================
COLORS = {
    "bg":        "#f4f6fb",
    "panel":     "#ffffff",
    "primary":   "#4361ee",
    "primary_d": "#3a0ca3",
    "accent":    "#7209b7",
    "teal":      "#06d6a0",
    "orange":    "#f4a261",
    "red":       "#ef476f",
    "yellow":    "#ffd166",
    "text":      "#2b2d42",
    "subtext":   "#6c757d",
    "border":    "#dfe3ee",
    "row_alt":   "#eef2fb",
    "success":   "#e6fff0",
    "warn":      "#fffbe6",
    "fail":      "#ffeaea",
}

ENERGY_OPTIONS = ("SCF 能量", "Gibbs 热校正", "总自由能")
HARTREE_TO_KCAL = 627.509474063  # 1 Hartree = 627.509... kcal/mol


# ==================================================================
#                         能量表达式解析器
# ==================================================================
class EnergyExpressionEvaluator:
    """
    安全解析形如 "TS1 - R + 0.5*P" 的能量表达式。
    仅允许：数字、变量名（文件名）、加减乘除、一元正负号、括号。
    通过 AST 白名单实现，禁止函数调用与任意代码执行。
    """

    _BIN = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
    }
    _UNA = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def __init__(self, variables):
        self.variables = {str(k).strip(): float(val)
                          for k, val in variables.items() if val is not None}

    def evaluate(self, expr):
        expr = (expr or "").strip()
        if not expr:
            raise ValueError("表达式为空")
        tree = ast.parse(expr, mode="eval")
        return self._eval_node(tree.body)

    def _eval_node(self, node):
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body)
        if isinstance(node, ast.Num):
            return node.n
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            name = node.id
            if name in self.variables:
                return self.variables[name]
            for k in self.variables:
                if k.startswith(name) or name.startswith(k):
                    return self.variables[k]
            raise ValueError(f"未找到物种「{name}」，请检查表达式与文件列表")
        if isinstance(node, ast.BinOp):
            op = self._BIN.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符 {type(node.op).__name__}")
            return op(self._eval_node(node.left), self._eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            op = self._UNA.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的一元运算符 {type(node.op).__name__}")
            return op(self._eval_node(node.operand))
        raise ValueError("表达式中存在不允许的语法元素")


# ==================================================================
#                             主程序
# ==================================================================
class LogExtractorApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Gaussian 热力学数据提取器 · 增强版")
        self.root.geometry("1120x780")
        self.root.minsize(1000, 660)
        self.root.configure(bg=COLORS["bg"])

        # 基础数据：每个元素 dict(path, name, scf, gibbs, free, status)
        self.file_data = []
        # 高级功能状态
        self.energy_type = tk.StringVar(value="总自由能")
        self.unit = tk.StringVar(value="Hartree")
        self.zero_point = tk.StringVar(value="(不设定，显示绝对值)")
        self.expression = tk.StringVar(value="")
        self.advanced_visible = tk.BooleanVar(value=False)

        self._drag_data = {"item": None, "idx": None}

        self.setup_styles()
        self.create_widgets()
        self._refresh_zero_options()
        self._refresh_order_tree()
        self._refresh_plot()

    # ------------------------------------------------------------------
    #                              样式
    # ------------------------------------------------------------------
    def setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=COLORS["bg"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"],
                        font=("微软雅黑", 10))
        style.configure("TButton", font=("微软雅黑", 10, "bold"), padding=(12, 6),
                        foreground="white", borderwidth=0)
        style.configure("Primary.TButton", background=COLORS["primary"], foreground="white")
        style.map("Primary.TButton", background=[("active", COLORS["primary_d"]),
                                                ("disabled", "#b8c0e0")])
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
        style.map("Accent.TButton", background=[("active", "#560bad"), ("disabled", "#d0b3e0")])
        style.configure("Teal.TButton", background=COLORS["teal"], foreground="#073b4c")
        style.map("Teal.TButton", background=[("active", "#04a97f"), ("disabled", "#bfe8dc")])
        style.configure("Orange.TButton", background=COLORS["orange"], foreground="#3d2b1f")
        style.map("Orange.TButton", background=[("active", "#e08a45"), ("disabled", "#f0dcc6")])
        style.configure("Ghost.TButton", background=COLORS["bg"], foreground=COLORS["primary_d"],
                        font=("微软雅黑", 10, "bold"))
        style.map("Ghost.TButton", background=[("active", "#e2e7fb")])
        style.configure("TProgressbar", thickness=14, background=COLORS["teal"],
                        troughcolor="#e2e7fb", borderwidth=0)
        style.configure("Treeview.Heading", font=("微软雅黑", 10, "bold"),
                        background=COLORS["primary"], foreground="white",
                        borderwidth=0, relief="flat")
        style.map("Treeview.Heading", background=[("active", COLORS["primary_d"])])
        style.configure("Treeview", font=("微软雅黑", 9), rowheight=26,
                        background=COLORS["panel"], foreground=COLORS["text"],
                        fieldbackground=COLORS["panel"], borderwidth=0)
        style.map("Treeview", background=[("selected", COLORS["primary"])])
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure("TLabelframe", background=COLORS["panel"], foreground=COLORS["primary_d"],
                        font=("微软雅黑", 10, "bold"))
        style.configure("TLabelframe.Label", background=COLORS["panel"],
                        foreground=COLORS["primary_d"], font=("微软雅黑", 10, "bold"))
        style.configure("TCombobox", font=("微软雅黑", 10), padding=4)
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", font=("微软雅黑", 10, "bold"), padding=(12, 5),
                        background=COLORS["panel"], foreground=COLORS["subtext"])
        style.map("TNotebook.Tab", background=[("selected", COLORS["primary"])],
                  foreground=[("selected", "white")])

    # ------------------------------------------------------------------
    #                           界面构建
    # ------------------------------------------------------------------
    def create_widgets(self):
        # 顶部标题栏
        top = tk.Frame(self.root, bg=COLORS["primary_d"], height=66)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="\u269b  Gaussian Log 热力学数据提取器",
                 bg=COLORS["primary_d"], fg="white",
                 font=("微软雅黑", 16, "bold")).pack(side=tk.LEFT, padx=20)
        tk.Label(top, text="增强版 · 支持相对能量计算与能量剖面图",
                 bg=COLORS["primary_d"], fg="#cdd7ff",
                 font=("微软雅黑", 9)).pack(side=tk.LEFT, padx=10)
        switch_frame = tk.Frame(top, bg=COLORS["primary_d"])
        switch_frame.pack(side=tk.RIGHT, padx=16)
        tk.Label(switch_frame, text="\u2699 高级功能", bg=COLORS["primary_d"], fg="white",
                 font=("微软雅黑", 10, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        self.adv_switch = ttk.Checkbutton(
            switch_frame, text="展开", style="TButton",
            variable=self.advanced_visible, command=self.toggle_advanced,
            onvalue=True, offvalue=False)
        self.adv_switch.pack(side=tk.LEFT)

        # 主体：左右分栏
        body = ttk.Frame(self.root, padding=10, style="TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1, minsize=560)
        body.columnconfigure(1, weight=1, minsize=400)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body, style="TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_basic_panel(left)

        self.adv_outer = ttk.Frame(body, style="TFrame")
        self.adv_outer.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self._build_advanced_panel(self.adv_outer)
        if not self.advanced_visible.get():
            self.adv_outer.grid_remove()

        self.statusbar = tk.Label(
            self.root, text="就绪", anchor=tk.W, bg=COLORS["primary"], fg="white",
            font=("微软雅黑", 9), padx=12, pady=4)
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    # -------------------- 基础面板 --------------------
    def _build_basic_panel(self, parent):
        parent.rowconfigure(2, weight=1)
        parent.columnconfigure(0, weight=1)

        btn_card = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"],
                            highlightthickness=1)
        btn_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        btns = [
            ("\U0001f4c2 添加文件", self.add_files, "Primary.TButton"),
            ("\U0001f4c1 添加文件夹", self.add_folder, "Primary.TButton"),
            ("\U0001f5d1 清空列表", self.clear_list, "Orange.TButton"),
            ("\u25b6 开始提取", self.start_extract, "Teal.TButton"),
            ("\U0001f4c4 导出 CSV", self.export_csv, "Accent.TButton"),
        ]
        for i, (txt, cmd, sty) in enumerate(btns):
            ttk.Button(btn_card, text=txt, command=cmd, style=sty).grid(
                row=0, column=i, padx=6, pady=10)

        self.progress = ttk.Progressbar(parent, mode="determinate", style="TProgressbar")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        table_card = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"],
                              highlightthickness=1)
        table_card.grid(row=2, column=0, sticky="nsew")
        table_card.rowconfigure(1, weight=1)
        table_card.columnconfigure(0, weight=1)
        tk.Label(table_card, text="\U0001f4cb 提取结果", bg=COLORS["panel"],
                 fg=COLORS["primary_d"], font=("微软雅黑", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=8)

        tree_frame = tk.Frame(table_card, bg=COLORS["panel"])
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        columns = ("文件名", "SCF 能量", "Gibbs 热校正", "总自由能", "状态")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)
        for col in columns:
            self.tree.heading(col, text=col)
            if col == "文件名":
                self.tree.column(col, width=170, anchor="w")
            elif col == "状态":
                self.tree.column(col, width=130, anchor="center")
            else:
                self.tree.column(col, width=120, anchor="center")
        self.tree.tag_configure("done", background=COLORS["success"])
        self.tree.tag_configure("fail", background=COLORS["fail"])
        self.tree.tag_configure("proc", background=COLORS["warn"])
        self.tree.grid(row=0, column=0, sticky="nsew")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

    # -------------------- 高级面板 --------------------
    def _build_advanced_panel(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)

        nb = ttk.Notebook(parent)
        nb.grid(row=0, column=0, sticky="nsew")
        self.adv_notebook = nb

        calc_frame = ttk.Frame(nb, style="TFrame", padding=8)
        nb.add(calc_frame, text="\u26a1 计算 & 能量剖面图")
        self._build_calc_tab(calc_frame)

        order_frame = ttk.Frame(nb, style="TFrame", padding=8)
        nb.add(order_frame, text="\U0001f500 自定义顺序")
        self._build_order_tab(order_frame)

    def _build_calc_tab(self, parent):
        parent.rowconfigure(5, weight=1)
        parent.columnconfigure(0, weight=1)

        settings = tk.LabelFrame(parent, text="能量设置", bg=COLORS["panel"],
                                 fg=COLORS["primary_d"], font=("微软雅黑", 10, "bold"),
                                 highlightbackground=COLORS["border"], highlightthickness=1)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for c in range(4):
            settings.columnconfigure(c, weight=1)

        tk.Label(settings, text="能量类型：", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("微软雅黑", 10)).grid(row=0, column=0, sticky="e", padx=6, pady=8)
        self.energy_combo = ttk.Combobox(settings, textvariable=self.energy_type,
                                         values=list(ENERGY_OPTIONS), state="readonly", width=14)
        self.energy_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.energy_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_all())

        tk.Label(settings, text="单位：", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("微软雅黑", 10)).grid(row=0, column=2, sticky="e", padx=6, pady=8)
        unit_frame = tk.Frame(settings, bg=COLORS["panel"])
        unit_frame.grid(row=0, column=3, sticky="ew", padx=6, pady=8)
        for txt, val in [("Hartree", "Hartree"), ("kcal/mol", "kcal/mol")]:
            ttk.Radiobutton(unit_frame, text=txt, value=val, variable=self.unit,
                            command=self._refresh_all).pack(side=tk.LEFT, padx=4)

        expr_card = tk.LabelFrame(parent, text="相对能量表达式", bg=COLORS["panel"],
                                  fg=COLORS["primary_d"], font=("微软雅黑", 10, "bold"),
                                  highlightbackground=COLORS["border"], highlightthickness=1)
        expr_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        expr_card.columnconfigure(1, weight=1)

        tk.Label(expr_card, text="零点：", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("微软雅黑", 10)).grid(row=0, column=0, sticky="e", padx=6, pady=8)
        self.zero_combo = ttk.Combobox(expr_card, textvariable=self.zero_point,
                                       values=["(不设定，显示绝对值)"], state="readonly", width=24)
        self.zero_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
        self.zero_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_all())
        ttk.Button(expr_card, text="设为表达式", style="Teal.TButton",
                   command=self._use_zero_in_expr).grid(row=0, column=2, padx=6, pady=8)

        tk.Label(expr_card, text="表达式：", bg=COLORS["panel"], fg=COLORS["text"],
                 font=("微软雅黑", 10)).grid(row=1, column=0, sticky="e", padx=6, pady=8)
        expr_entry = tk.Entry(expr_card, textvariable=self.expression,
                              font=("Consolas", 12, "bold"), fg=COLORS["accent"],
                              bg="#fbfaff", relief="solid", highlightthickness=1,
                              highlightbackground=COLORS["border"])
        expr_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=8)
        expr_entry.bind("<KeyRelease>", lambda e: self._refresh_all())
        tk.Label(expr_card, text="提示：用文件名作变量，如  TS1 - R  ；支持 + - * / 、括号与系数",
                 bg=COLORS["panel"], fg=COLORS["subtext"], font=("微软雅黑", 8),
                 anchor="w").grid(row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 6))
        self.expr_result = tk.Label(expr_card, text="", bg=COLORS["panel"],
                                    fg=COLORS["primary_d"], font=("微软雅黑", 10, "bold"),
                                    anchor="w")
        self.expr_result.grid(row=3, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 8))

        preview_card = tk.LabelFrame(parent, text="相对能量预览", bg=COLORS["panel"],
                                     fg=COLORS["primary_d"], font=("微软雅黑", 10, "bold"),
                                     highlightbackground=COLORS["border"], highlightthickness=1)
        preview_card.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        preview_card.rowconfigure(0, weight=1)
        preview_card.columnconfigure(0, weight=1)

        pcols = ("显示顺序", "物种", "原始能量(Hartree)", "相对能量", "单位")
        self.preview_tree = ttk.Treeview(preview_card, columns=pcols, show="headings", height=6)
        for col in pcols:
            self.preview_tree.heading(col, text=col)
            if col == "物种":
                self.preview_tree.column(col, width=150, anchor="w")
            elif col == "显示顺序":
                self.preview_tree.column(col, width=60, anchor="center")
            elif col == "单位":
                self.preview_tree.column(col, width=80, anchor="center")
            else:
                self.preview_tree.column(col, width=150, anchor="center")
        self.preview_tree.tag_configure("zero", background=COLORS["yellow"])
        self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)

        plot_card = tk.LabelFrame(parent, text="反应坐标能量剖面图 (Reaction Profile)",
                                  bg=COLORS["panel"], fg=COLORS["primary_d"],
                                  font=("微软雅黑", 10, "bold"),
                                  highlightbackground=COLORS["border"], highlightthickness=1)
        plot_card.grid(row=3, column=0, rowspan=3, sticky="nsew", pady=(0, 8))
        plot_card.rowconfigure(0, weight=1)
        plot_card.columnconfigure(0, weight=1)

        if HAS_MPL:
            self.fig = Figure(figsize=(5, 3.2), dpi=100, facecolor=COLORS["panel"])
            self.ax = self.fig.add_subplot(111)
            self.canvas = FigureCanvasTkAgg(self.fig, master=plot_card)
            self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        else:
            self.canvas = None
            tk.Label(plot_card, text="未检测到 matplotlib，无法显示图表。\n请安装：pip install matplotlib numpy",
                     bg=COLORS["panel"], fg=COLORS["red"], font=("微软雅黑", 10)).pack(expand=True)

        adv_btn = tk.Frame(parent, bg=COLORS["bg"])
        adv_btn.grid(row=6, column=0, sticky="ew", pady=(0, 4))
        ttk.Button(adv_btn, text="\U0001f504 刷新预览 & 图表", style="Primary.TButton",
                   command=self._refresh_all).pack(side=tk.LEFT, padx=3)
        ttk.Button(adv_btn, text="\U0001f4be 导出相对能量 CSV", style="Accent.TButton",
                   command=self.export_relative_csv).pack(side=tk.LEFT, padx=3)
        ttk.Button(adv_btn, text="\U0001f5bc 保存图表", style="Teal.TButton",
                   command=self.save_plot).pack(side=tk.LEFT, padx=3)
        ttk.Button(adv_btn, text="\u270d 应用表达式到全部", style="Ghost.TButton",
                   command=self._apply_expr_to_all).pack(side=tk.RIGHT, padx=3)

    def _build_order_tab(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        tk.Label(parent, text="拖拽行以调整物种在能量剖面图中的显示顺序（也决定反应坐标顺序）",
                 bg=COLORS["bg"], fg=COLORS["subtext"], font=("微软雅黑", 9)).grid(
            row=0, column=0, sticky="ew", pady=(0, 6))

        order_card = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"],
                              highlightthickness=1)
        order_card.grid(row=1, column=0, sticky="nsew")
        order_card.rowconfigure(0, weight=1)
        order_card.columnconfigure(0, weight=1)

        cols = ("顺序", "物种", "能量(Hartree)")
        self.order_tree = ttk.Treeview(order_card, columns=cols, show="headings", height=12)
        for col in cols:
            self.order_tree.heading(col, text=col)
            if col == "物种":
                self.order_tree.column(col, width=180, anchor="w")
            else:
                self.order_tree.column(col, width=80, anchor="center")
        self.order_tree.tag_configure("odd", background=COLORS["row_alt"])
        self.order_tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.order_tree.bind("<ButtonPress-1>", self._on_order_press)
        self.order_tree.bind("<B1-Motion>", self._on_order_drag)
        self.order_tree.bind("<ButtonRelease-1>", self._on_order_release)

        btn_row = tk.Frame(parent, bg=COLORS["bg"])
        btn_row.grid(row=2, column=0, sticky="ew", pady=6)
        ttk.Button(btn_row, text="\u2191 上移", style="Primary.TButton",
                   command=lambda: self._move_order(-1)).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="\u2193 下移", style="Primary.TButton",
                   command=lambda: self._move_order(1)).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="\u21e7 置顶", style="Ghost.TButton",
                   command=lambda: self._move_order_to("top")).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="\u21e9 置底", style="Ghost.TButton",
                   command=lambda: self._move_order_to("bottom")).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="\U0001f500 按名称排序", style="Teal.TButton",
                   command=self._order_by_name).pack(side=tk.LEFT, padx=3)
        ttk.Button(btn_row, text="\U0001f4be 确认顺序", style="Accent.TButton",
                   command=self._confirm_order).pack(side=tk.RIGHT, padx=3)

    # ------------------------------------------------------------------
    #                         高级面板开关
    # ------------------------------------------------------------------
    def toggle_advanced(self):
        if self.advanced_visible.get():
            self.adv_outer.grid()
            self.root.after(50, self._refresh_all)
            self.statusbar.config(text="高级功能已展开")
        else:
            self.adv_outer.grid_remove()
            self.statusbar.config(text="就绪")

    # ------------------------------------------------------------------
    #                        文件操作（维持原版）
    # ------------------------------------------------------------------
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 Gaussian Log 文件",
            filetypes=[("Log 文件", "*.log"), ("所有文件", "*.*")])
        if files:
            added = 0
            for f in files:
                if not any(item["path"] == f for item in self.file_data):
                    base = os.path.basename(f)
                    name, ext = os.path.splitext(base)
                    display_name = name if ext.lower() == ".log" else base
                    self.file_data.append(self._new_entry(f, display_name))
                    added += 1
            self.update_treeview()
            self._refresh_all()
            self.statusbar.config(text=f"已添加 {added} 个文件")

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择包含 Log 文件的文件夹")
        if folder:
            log_files = sorted(Path(folder).glob("*.log"))
            if not log_files:
                messagebox.showinfo("提示", "所选文件夹中没有 .log 文件")
                return
            count = 0
            for f in log_files:
                f_str = str(f)
                if not any(item["path"] == f_str for item in self.file_data):
                    name, ext = os.path.splitext(f.name)
                    display_name = name if ext.lower() == ".log" else f.name
                    self.file_data.append(self._new_entry(f_str, display_name))
                    count += 1
            self.update_treeview()
            self._refresh_all()
            self.statusbar.config(text=f"从文件夹添加了 {count} 个文件")

    def clear_list(self):
        if self.file_data and messagebox.askyesno("确认", "确定要清空所有文件吗？"):
            self.file_data.clear()
            self.update_treeview()
            self._refresh_all()
            self.statusbar.config(text="列表已清空")

    @staticmethod
    def _new_entry(path, name):
        return {"path": path, "name": name, "scf": None, "gibbs": None,
                "free": None, "status": "待处理"}

    # ------------------------------------------------------------------
    #                          表格更新
    # ------------------------------------------------------------------
    def update_treeview(self):
        self.tree.delete(*self.tree.get_children())
        for data in self.file_data:
            tag = {"已完成": "done", "失败": "fail", "处理中": "proc"}.get(data["status"], "")
            self.tree.insert("", "end", values=(
                data["name"],
                f"{data['scf']:.6f}" if data["scf"] is not None else "",
                f"{data['gibbs']:.6f}" if data["gibbs"] is not None else "",
                f"{data['free']:.6f}" if data["free"] is not None else "",
                data["status"]), tags=(tag,))

    # ------------------------------------------------------------------
    #                        解析核心（维持原版）
    # ------------------------------------------------------------------
    def parse_log(self, filepath):
        scf = gibbs = free = None
        scf_p = re.compile(r"SCF Done:\s+E\(\w+\)\s*=\s*([-\d.]+)")
        gibbs_p = re.compile(r"Thermal correction to Gibbs Free Energy=\s*([-\d.]+)")
        free_p = re.compile(r"Sum of electronic and thermal Free Energies\s*=\s*([-\d.]+)")
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    m = scf_p.search(line)
                    if m:
                        scf = float(m.group(1))
                    m = gibbs_p.search(line)
                    if m:
                        gibbs = float(m.group(1))
                    m = free_p.search(line)
                    if m:
                        free = float(m.group(1))
        except Exception as e:
            print(f"解析 {filepath} 出错: {e}")
        return scf, gibbs, free

    # ------------------------------------------------------------------
    #                        多线程提取（维持原版）
    # ------------------------------------------------------------------
    def start_extract(self):
        if not self.file_data:
            messagebox.showinfo("提示", "请先添加 Log 文件")
            return
        pending = [i for i, d in enumerate(self.file_data) if d["status"] in ("待处理", "失败")]
        if not pending:
            messagebox.showinfo("提示", "所有文件已处理完毕")
            return
        self._set_buttons_state("disabled")
        self.progress.config(maximum=len(pending), value=0)
        self.statusbar.config(text="正在提取...")

        def worker():
            total = len(pending)
            for i, idx in enumerate(pending):
                data = self.file_data[idx]
                data["status"] = "处理中"
                self.root.after(0, self.update_treeview)
                scf, gibbs, free = self.parse_log(data["path"])
                data["scf"], data["gibbs"], data["free"] = scf, gibbs, free
                if scf is None:
                    data["status"] = "失败：SCF未收敛"
                elif gibbs is None or free is None:
                    data["status"] = "失败：缺失频率计算"
                else:
                    data["status"] = "已完成"
                self.root.after(0, self._update_progress, i + 1, total)
            self.root.after(0, self._extract_finished)

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, value, total):
        self.progress.config(value=value)
        self.statusbar.config(text=f"正在处理... {value}/{total}")
        self.update_treeview()

    def _extract_finished(self):
        self.progress.config(value=self.progress.cget("maximum"))
        self.statusbar.config(text="提取完成")
        self.update_treeview()
        self._refresh_all()
        self._set_buttons_state("normal")
        messagebox.showinfo("完成", "所有文件提取完毕！")

    def _set_buttons_state(self, state):
        for w in self.root.winfo_children():
            if isinstance(w, tk.Frame) and w is not self.statusbar:
                for child in w.winfo_descendants():
                    if isinstance(child, ttk.Button):
                        child.config(state=state)

    # ------------------------------------------------------------------
    #                          导出 CSV
    # ------------------------------------------------------------------
    def export_csv(self):
        if not self.file_data:
            messagebox.showinfo("提示", "没有数据可导出")
            return
        pending = [d for d in self.file_data if d["status"] not in ("已完成", "失败")]
        if pending and not messagebox.askyesno("确认", "有文件尚未处理，确定要导出当前数据吗？"):
            return
        path = filedialog.asksaveasfilename(title="保存 CSV", defaultextension=".csv",
                                            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["文件名", "SCF 能量(Hartree)", "Gibbs热校正(Hartree)",
                            "总自由能(Hartree)", "状态"])
                for d in self.file_data:
                    w.writerow([d["name"],
                                f"{d['scf']:.6f}" if d["scf"] is not None else "",
                                f"{d['gibbs']:.6f}" if d['gibbs'] is not None else "",
                                f"{d['free']:.6f}" if d['free'] is not None else "",
                                d["status"]])
            messagebox.showinfo("成功", f"CSV 已保存至：{path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}")

    # ------------------------------------------------------------------
    #                      高级功能：核心逻辑
    # ------------------------------------------------------------------
    def _energy_key(self):
        return {"SCF 能量": "scf", "Gibbs 热校正": "gibbs", "总自由能": "free"}[self.energy_type.get()]

    def _current_energy_map(self):
        key = self._energy_key()
        return {d["name"]: d[key] for d in self.file_data}

    def _has_energy(self, d):
        return d[self._energy_key()] is not None

    def _custom_order(self):
        items = [self.order_tree.item(it)["values"] for it in self.order_tree.get_children()]
        if items:
            return [row[1] for row in items]
        return [d["name"] for d in self.file_data]

    def _relative_results(self):
        energy_map = self._current_energy_map()
        unit = self.unit.get()
        zero_sel = self.zero_point.get()
        expr = self.expression.get().strip()
        points = []
        zero_name = None

        if expr:
            evaluator = EnergyExpressionEvaluator(energy_map)
            val_hartree = evaluator.evaluate(expr)
            rel = val_hartree * (HARTREE_TO_KCAL if unit == "kcal/mol" else 1.0)
            label = f"{expr}  ="
            return {"zero_name": None, "unit": unit, "mode": "expr",
                    "points": [(label, 1, val_hartree, rel, False)], "value_hartree": val_hartree}

        order = self._custom_order()
        ordered = [n for n in order if n in energy_map and energy_map[n] is not None]
        zero_val = None
        if zero_sel != "(不设定，显示绝对值)" and zero_sel in energy_map:
            zero_name = zero_sel
            zero_val = energy_map[zero_sel]

        for i, name in enumerate(ordered, start=1):
            raw = energy_map[name]
            if zero_val is not None:
                rel = (raw - zero_val)
                is_zero = (name == zero_name)
            else:
                rel = raw
                is_zero = False
            disp = rel * (HARTREE_TO_KCAL if unit == "kcal/mol" else 1.0)
            points.append((name, i, raw, disp, is_zero))
        return {"zero_name": zero_name, "unit": unit, "mode": "list", "points": points}

    # -------------------- 刷新：全部 --------------------
    def _refresh_all(self):
        self._refresh_zero_options()
        self._refresh_order_tree()
        self._refresh_preview()
        self._refresh_plot()

    def _refresh_zero_options(self):
        names = [d["name"] for d in self.file_data if self._has_energy(d)]
        opts = ["(不设定，显示绝对值)"] + names
        current = self.zero_point.get()
        self.zero_combo.config(values=opts)
        if current not in opts:
            self.zero_point.set("(不设定，显示绝对值)")

    def _use_zero_in_expr(self):
        z = self.zero_point.get()
        if z == "(不设定，显示绝对值)":
            messagebox.showinfo("提示", "请先选择一个能量零点")
            return
        cur = self.expression.get().strip()
        self.expression.set(f"({cur}) - {z}" if cur else f"0 - {z}")
        self._refresh_all()

    def _apply_expr_to_all(self):
        z = self.zero_point.get()
        if z == "(不设定，显示绝对值)":
            messagebox.showinfo("提示", "请先在「零点」中选择基准物种")
            return
        names = [d["name"] for d in self.file_data if self._has_energy(d)]
        if not names:
            return
        self.expression.set(" + ".join(f"1*{n}" for n in names) + f" - {len(names)}*{z}")
        self._refresh_all()

    # -------------------- 预览表 --------------------
    def _refresh_preview(self):
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.expr_result.config(text="", fg=COLORS["primary_d"])
        if not self.file_data:
            return
        try:
            result = self._relative_results()
        except Exception as e:
            self.expr_result.config(text=f"\u26a0 表达式错误：{e}", fg=COLORS["red"])
            return

        unit = result["unit"]
        if result.get("mode") == "expr":
            v = result["points"][0][3]
            hartree = result.get("value_hartree", 0.0)
            sign = "+" if v >= 0 else "-"
            self.expr_result.config(
                text=f"\u2705 表达式结果：{result['points'][0][0]}  {sign} {abs(v):.4f} {unit}"
                     f"   (原始 {hartree:.6f} Hartree)",
                fg=COLORS["primary_d"])
            self.preview_tree.insert("", "end", values=(
                "\u2014", result["points"][0][0], f"{hartree:.6f}",
                f"{v:+.4f}", unit), tags=("zero",))
            return

        zero_name = result["zero_name"]
        if zero_name:
            self.expr_result.config(
                text=f"\U0001f4cc 零点 = {zero_name}（显示各物种相对 {zero_name} 的能量）",
                fg=COLORS["primary_d"])
        else:
            self.expr_result.config(
                text="\u2139 未设零点：显示各物种该能量类型的原始值（无相对意义）",
                fg=COLORS["subtext"])

        for name, order, raw, disp, is_zero in result["points"]:
            self.preview_tree.insert("", "end", values=(
                order, name, f"{raw:.6f}", f"{disp:+.4f}", unit),
                tags=("zero" if is_zero else ""))

    # ================== 科幻主题常量（图表专用） ==================
    S = {  # SciFi palette
        "bg":      "#070b19",   # 深空背景
        "bg2":     "#0c1226",   # 面板略亮
        "cyan":    "#00f0ff",   # 主霓虹青
        "magenta": "#ff2bd6",   # 品红
        "lime":    "#39ff14",   # 霓虹绿
        "amber":   "#ffb000",   # 琥珀
        "violet":  "#8b5cf6",   # 紫
        "blue":    "#2f80ff",   # 亮蓝
        "pink":    "#ff5e9c",   # 粉
        "grid":    "#1c2740",   # 网格
        "txt":     "#c9d8ff",   # 主文字
        "sub":     "#6f86c2",   # 次要文字
        "linecore":"#eafcff",   # 线芯高光
    }

    # -------------------- 能量剖面图（科幻风） --------------------
    def _refresh_plot(self):
        if not HAS_MPL:
            return
        import matplotlib.colors as mcolors
        from matplotlib.collections import PolyCollection

        self.ax.clear()
        ax = self.fig.add_axes([0.10, 0.16, 0.86, 0.68])
        self.ax = ax
        ax.set_facecolor(self.S["bg"])
        self.fig.patch.set_facecolor(self.S["bg"])

        try:
            result = self._relative_results()
        except Exception:
            result = None

        if not result or not result["points"]:
            ax.text(0.5, 0.5, "NO DATA\nEXTRACT OR ENTER AN EXPRESSION",
                    ha="center", va="center", fontsize=13, color=self.S["sub"],
                    fontweight="bold", transform=ax.transAxes, linespacing=1.6)
            ax.set_xticks([]); ax.set_yticks([])
            for sp in ax.spines.values(): sp.set_visible(False)
            self.canvas.draw_idle()
            return

        unit = result["unit"]
        points = result["points"]
        labels = [p[0] for p in points]
        values = [p[3] for p in points]

        neon = [self.S["lime"], self.S["magenta"], self.S["violet"], self.S["amber"],
                self.S["cyan"], self.S["pink"], self.S["blue"]]
        colors = [self.S["lime"] if p[4] else neon[i % len(neon)] for i, p in enumerate(points)]

        x = list(range(len(values)))
        n = len(x)

        # 背景径向渐变
        import numpy as _np
        grad = _np.linspace(0, 1, 256).reshape(1, -1)
        grad = _np.vstack([grad] * 16)
        cmap = mcolors.LinearSegmentedColormap.from_list("space", ["#050914", "#0a1024"])
        vmin, vmax = min(values + [0]), max(values + [0])
        pad = (vmax - vmin) * 0.25 + 1
        ax.imshow(grad, extent=[-0.55, n - 0.45, vmin - pad, vmax + pad],
                  aspect="auto", cmap=cmap, zorder=0)

        # 零点基准线（发光）
        if result.get("mode") == "list" and result.get("zero_name"):
            ax.axhline(0, color=self.S["lime"], lw=1.6, alpha=0.95, zorder=2)
            ax.axhline(0, color=self.S["lime"], lw=7, alpha=0.11, zorder=1)
            ax.text(n - 0.5, 0, "  ZERO POINT", color=self.S["lime"],
                    va="center", fontsize=8.5, fontweight="bold", alpha=0.9)

        # 分段渐变填充（每段取该段的主题色）
        for i in range(n - 1):
            xseg = _np.linspace(x[i], x[i + 1], 60)
            yseg = _np.interp(xseg, x, values)
            pts = [[(float(xx), float(yy)), (float(xx), 0.0)] for xx, yy in zip(xseg, yseg)]
            pc = PolyCollection(pts, facecolors=[colors[i]] * len(pts), alpha=0.11, zorder=2)
            ax.add_collection(pc)

        # 主线：三层叠加实现霓虹发光
        ax.plot(x, values, "-", color=self.S["cyan"], lw=8, alpha=0.13,
                solid_capstyle="round", zorder=3)
        ax.plot(x, values, "-", color=self.S["cyan"], lw=3.4, alpha=0.55,
                solid_capstyle="round", zorder=4)
        ax.plot(x, values, "-", color=self.S["linecore"], lw=1.2, alpha=0.95,
                solid_capstyle="round", zorder=5)

        # 数据点：外发光环 + 内核
        for xi, yi, c in zip(x, values, colors):
            ax.scatter([xi], [yi], s=560, color=c, alpha=0.13, edgecolors="none", zorder=6)
            ax.scatter([xi], [yi], s=250, color=c, alpha=0.27, edgecolors="none", zorder=7)
            ax.scatter([xi], [yi], s=72, color=self.S["bg"], edgecolors=c,
                       linewidths=2.5, zorder=8)

        # 数值标注（霓虹边框 HUD）
        for xi, yi, c in zip(x, values, colors):
            offset = 18 if yi >= 0 else -23
            ax.annotate(f"{yi:+.1f}", (xi, yi), textcoords="offset points",
                        xytext=(0, offset), ha="center", fontsize=10, fontweight="bold",
                        color=c, zorder=9,
                        bbox=dict(boxstyle="round,pad=0.28", fc=self.S["bg"],
                                  ec=c, lw=1.1, alpha=0.92))

        # 坐标轴
        ax.set_xticks(x)
        ax.set_xticklabels([f"[{i}] {l}" for i, l in enumerate(labels)],
                          fontsize=9.5, color=self.S["txt"])
        ax.set_ylabel("RELATIVE ENERGY  [kcal/mol]" if unit == "kcal/mol"
                      else "RELATIVE ENERGY  [Hartree]",
                      fontsize=10.5, fontweight="bold", color=self.S["cyan"], labelpad=10)
        ax.tick_params(colors=self.S["sub"], length=0)
        for sp in ["top", "right", "left"]:
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(self.S["grid"])
        for sp in ax.spines.values():
            sp.set_linewidth(1.2)

        # 网格（主 + 次）
        ax.grid(axis="y", which="major", color=self.S["grid"], lw=0.9, alpha=0.9, zorder=1)
        ax.grid(axis="y", which="minor", color=self.S["grid"], lw=0.4, alpha=0.45, zorder=1)
        ax.set_axisbelow(True)
        from matplotlib.ticker import AutoMinorLocator
        ax.yaxis.set_minor_locator(AutoMinorLocator())

        # 标题 HUD
        etype = self.energy_type.get()
        etag = {"SCF 能量": "SCF", "Gibbs 热校正": "ΔG_corr", "总自由能": "ΔG"}[etype]
        ax.set_title("REACTION PROFILE", color=self.S["cyan"], fontsize=15,
                     fontweight="bold", pad=22, loc="left")
        ax.text(0.0, 1.045, f"Σ {etag}  ·  {unit}", transform=ax.transAxes,
                color=self.S["sub"], fontsize=9, fontweight="bold")

        # 四角装饰线
        ax.plot([0.0, 0.18], [1.012, 1.012], transform=ax.transAxes,
                color=self.S["cyan"], lw=1.6)
        ax.plot([0.82, 1.0], [1.012, 1.012], transform=ax.transAxes,
                color=self.S["cyan"], lw=1.6)
        ax.annotate("", xy=(1.045, 1.045), xytext=(-0.045, 1.005),
                    xycoords=("axes fraction", "axes fraction"),
                    textcoords=("axes fraction", "axes fraction"),
                    arrowprops=dict(arrowstyle="-", color=self.S["cyan"], lw=1.6))
        ax.annotate("", xy=(1.045, 1.005), xytext=(-0.045, 1.055),
                    xycoords=("axes fraction", "axes fraction"),
                    textcoords=("axes fraction", "axes fraction"),
                    arrowprops=dict(arrowstyle="-", color=self.S["cyan"], lw=1.6))

        ax.set_ylim(vmin - pad, vmax + pad)
        ax.set_xlim(-0.55, n - 0.45)
        self.canvas.draw_idle()

    # -------------------- 顺序管理 --------------------
    def _refresh_order_tree(self):
        existing = list(self.order_tree.get_children())
        if existing:
            # 仅刷新能量列
            key = self._energy_key()
            for it in existing:
                vals = self.order_tree.item(it)["values"]
                d = next((x for x in self.file_data if x["name"] == vals[1]), None)
                e = d[key] if d else None
                self.order_tree.item(it, values=(vals[0], vals[1],
                                                f"{e:.6f}" if e is not None else "\u2014"),
                                    tags=("odd" if int(vals[0]) % 2 else ""))
            return
        # 首次：从 file_data 初始化
        for i, d in enumerate(self.file_data, start=1):
            key = self._energy_key()
            e = d[key]
            self.order_tree.insert("", "end", values=(
                i, d["name"], f"{e:.6f}" if e is not None else "\u2014"),
                tags=("odd" if i % 2 else ""))

    def _confirm_order(self):
        self._refresh_all()
        self.statusbar.config(text="自定义顺序已确认")

    def _order_by_name(self):
        items = [(self.order_tree.item(it)["values"][1], it)
                 for it in self.order_tree.get_children()]
        items.sort(key=lambda t: t[0])
        for _, it in items:
            self.order_tree.move(it, "", "end")
        self._renumber_order()

    def _move_order(self, delta):
        sel = self.order_tree.selection()
        if not sel:
            return
        for it in sel:
            idx = self.order_tree.index(it)
            new = idx + delta
            if 0 <= new < len(self.order_tree.get_children()):
                self.order_tree.move(it, "", new)
        self._renumber_order()

    def _move_order_to(self, where):
        sel = self.order_tree.selection()
        if not sel:
            return
        for it in sel:
            self.order_tree.move(it, "", 0 if where == "top" else "end")
        self._renumber_order()

    def _renumber_order(self):
        for i, it in enumerate(self.order_tree.get_children(), start=1):
            vals = self.order_tree.item(it)["values"]
            self.order_tree.item(it, values=(i, vals[1], vals[2]),
                                 tags=("odd" if i % 2 else ""))

    def _on_order_press(self, event):
        row = self.order_tree.identify_row(event.y)
        if row:
            self._drag_data["item"] = row
            self._drag_data["idx"] = self.order_tree.index(row)

    def _on_order_drag(self, event):
        row = self.order_tree.identify_row(event.y)
        if not row or row == self._drag_data["item"]:
            return
        self.order_tree.move(self._drag_data["item"], "", self.order_tree.index(row))

    def _on_order_release(self, event):
        self._drag_data["item"] = None
        self._drag_data["idx"] = None
        self._renumber_order()
        self._refresh_plot()

    # ------------------------------------------------------------------
    #                        导出相对能量
    # ------------------------------------------------------------------
    def export_relative_csv(self):
        if not self.file_data:
            messagebox.showinfo("提示", "没有数据可导出")
            return
        try:
            result = self._relative_results()
        except Exception as e:
            messagebox.showerror("表达式错误", str(e))
            return
        path = filedialog.asksaveasfilename(title="保存相对能量 CSV", defaultextension=".csv",
                                            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if result.get("mode") == "expr":
                    w.writerow(["表达式", "原始能量(Hartree)", f"相对能量({result['unit']})"])
                    p = result["points"][0]
                    w.writerow([self.expression.get(), p[2], f"{p[3]:.6f}"])
                else:
                    w.writerow(["显示顺序", "物种", "原始能量(Hartree)",
                                f"相对能量({result['unit']})", "是否零点"])
                    for name, order, raw, disp, is_zero in result["points"]:
                        w.writerow([order, name, f"{raw:.6f}", f"{disp:+.6f}",
                                    "是" if is_zero else ""])
            messagebox.showinfo("成功", f"相对能量 CSV 已保存至：{path}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败：{e}")

    def save_plot(self):
        if not HAS_MPL:
            messagebox.showerror("错误", "未安装 matplotlib")
            return
        path = filedialog.asksaveasfilename(title="保存能量剖面图",
                                            defaultextension=".png",
                                            filetypes=[("PNG 图片", "*.png"),
                                                       ("PDF 矢量图", "*.pdf"),
                                                       ("SVG 矢量图", "*.svg")])
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=200, bbox_inches="tight", facecolor=COLORS["panel"])
            messagebox.showinfo("成功", f"图表已保存至：{path}")
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{e}")


# ==================================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = LogExtractorApp(root)
    root.mainloop()
