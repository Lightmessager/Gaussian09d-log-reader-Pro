#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gaussian Log 热力学数据提取器 ---- 业务程序（app.py）
====================================================================
由 launcher.py 在依赖齐备后调用，也可独立运行：
  独立运行：  python app.py
  配合启动器：和 launcher.py 放同一目录，双击 launcher.py
====================================================================
"""

import os
import re
import ast
import csv
import operator
import threading

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from pathlib import Path


# 表达式编辑目标为"全局"时的显示名（全局模式：一个表达式算出一个值）
GLOBAL_EXPR = "(全局：单一结果)"
# 零点下拉里"不设定"的固定文案
NO_ZERO = "(不设定，显示绝对值)"


def sanitize_name(name):
    """把物种名（文件名）转成合法的 Python 标识符，供表达式使用。

    文件名常带空格、点、连字符等（如 "TS 1"、"int-2"），直接拼进表达式
    会被 ast.parse 判为语法错误。这里把非法字符统一替换为下划线，并保证
    不以数字开头。原名与新名的对应关系由调用方记入别名表。
    """
    s = re.sub(r"[^0-9A-Za-z_]", "_", str(name))
    if not s:
        s = "_"
    if s[0].isdigit():
        s = "_" + s
    return s


def format_coef(coef):
    """系数格式化：避免 0.30000000000000004 这类浮点尾数进入表达式。"""
    try:
        v = float(coef)
    except (TypeError, ValueError):
        return "1"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%g" % v)


def expression_from_terms(terms):
    """由构建器的项列表生成表达式字符串（纯逻辑，可独立测试）。

    terms: [{"name": 表达式变量名, "coef": 系数, "op": 该项前的运算符}, ...]
    首项的 op 若为 "-" 则写成一元负号；其余项按 "op 项" 拼接。
    例: [A(+), B(-, 0.5)] -> "A - 0.5*B"
    """
    parts = []
    for i, t in enumerate(terms):
        name = str(t.get("name", "")).strip()
        if not name:
            continue
        coef = format_coef(t.get("coef", 1.0))
        piece = name if coef == "1" else "%s*%s" % (coef, name)
        op = t.get("op") or "+"
        if i == 0 or not parts:
            parts.append(("-" + piece) if op == "-" else piece)
        else:
            parts.append("%s %s" % (op, piece))
    return " ".join(parts).strip()


def terms_from_expression(expr, alias=None):
    """把表达式字符串反解析成构建器的项列表，便于再次编辑已保存的表达式。

    只支持构建器自己能产出的扁平形式：若干项相加减，每项形如 变量 或
    系数*变量（如 "TS1 - R"、"A - 0.5*B + 2*C"）。遇到括号、除法、纯常数
    等无法用方块表示的结构则返回 None，调用方据此决定不预填，绝不猜。

    alias: {变量名: 真实物种名}，用于把变量还原成方块上显示的名字。
    """
    import ast as _ast
    alias = alias or {}
    # 查表方向是「表达式里的变量名 -> 真实物种名」，这正是 alias 本身的方向
    # {变量: 真实名}。之前写成反转 {真实名: 变量}，会导致变量名被当成物种名
    # 显示，再次保存时又生成新变量（R_1 -> R_1_1），每开一次漂移一次。
    inv = dict(alias)

    def _const_val(n, sign=1.0):
        """取数值常量，允许被一元 +/- 包裹；不是数字则返回 None。"""
        if isinstance(n, _ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value) * sign
        if isinstance(n, _ast.UnaryOp):
            if isinstance(n.op, _ast.USub):
                return _const_val(n.operand, -sign)
            if isinstance(n.op, _ast.UAdd):
                return _const_val(n.operand, sign)
        return None
    try:
        node = _ast.parse(str(expr), mode="eval").body
    except Exception:
        return None
    terms = []

    def walk(n, sign):
        if isinstance(n, _ast.UnaryOp):
            if isinstance(n.op, _ast.USub):
                return walk(n.operand, -sign)
            if isinstance(n.op, _ast.UAdd):
                return walk(n.operand, sign)
            return False
        if isinstance(n, _ast.BinOp):
            if isinstance(n.op, _ast.Add):
                return walk(n.left, sign) and walk(n.right, sign)
            if isinstance(n.op, _ast.Sub):
                return walk(n.left, sign) and walk(n.right, -sign)
            if isinstance(n.op, _ast.Mult):
                # 系数可能是被一元负号包起来的常量：'-3*TS1' 解析成
                # Mult(UnaryOp(USub, Const 3), Name)，只认 Constant 会漏掉。
                c = _const_val(n.left)
                var_node = n.right
                if c is None:
                    c = _const_val(n.right)
                    var_node = n.left
                if c is None or not isinstance(var_node, _ast.Name):
                    return False
                c = c * sign
                terms.append({"name": inv.get(var_node.id, var_node.id),
                              "var": var_node.id, "coef": abs(c),
                              "op": "-" if c < 0 else "+"})
                return True
            return False
        if isinstance(n, _ast.Name):
            terms.append({"name": inv.get(n.id, n.id), "var": n.id,
                          "coef": 1.0, "op": "-" if sign < 0 else "+"})
            return True
        return False

    if not walk(node, 1) or not terms:
        return None
    return terms


def run_application():
    import matplotlib
    matplotlib.use("TkAgg")
    # matplotlib 默认字体不含中文 glyph，物种名若是中文文件名会显示成方块。
    # 这里把中文字体排在最前，找不到时自动回退到 DejaVu Sans，不影响英文。
    try:
        matplotlib.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "SimSun", "DejaVu Sans"]
        # 用 ASCII 负号，避免某些中文字体下负号变方块
        matplotlib.rcParams["axes.unicode_minus"] = False
    except Exception:
        pass
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import numpy as np

    HAS_MPL = True

    COLORS = {
        "bg": "#f4f6fb", "panel": "#ffffff", "primary": "#4361ee",
        "primary_d": "#3a0ca3", "accent": "#7209b7", "teal": "#06d6a0",
        "orange": "#f4a261", "red": "#ef476f", "yellow": "#ffd166",
        "text": "#2b2d42", "subtext": "#6c757d", "border": "#dfe3ee",
        "row_alt": "#eef2fb", "success": "#e6fff0", "warn": "#fffbe6",
        "fail": "#ffeaea",
    }
    ENERGY_OPTIONS = ("SCF 能量", "Gibbs 热校正", "总自由能")
    HARTREE_TO_KCAL = 627.509474063

    class EnergyExpressionEvaluator:
        """安全解析形如 "TS1 - R + 0.5*P" 的能量表达式（AST 白名单）。"""
        _BIN = {ast.Add: operator.add, ast.Sub: operator.sub,
                ast.Mult: operator.mul, ast.Div: operator.truediv}
        _UNA = {ast.UAdd: operator.pos, ast.USub: operator.neg}

        def __init__(self, variables):
            self.variables = {str(k).strip(): float(v)
                             for k, v in variables.items() if v is not None}

        def evaluate(self, expr):
            expr = (expr or "").strip()
            if not expr:
                raise ValueError("表达式为空")
            return self._eval_node(ast.parse(expr, mode="eval").body)

        def _eval_node(self, node):
            if isinstance(node, ast.Expression):
                return self._eval_node(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.Name):
                # 精确匹配优先。原实现取"第一个"前缀匹配项，当物种名存在
                # 前缀关系（如 TS1 与 TS1b）时会张冠李戴，取最长匹配更稳。
                if node.id in self.variables:
                    return self.variables[node.id]
                cands = [k for k in self.variables
                         if k.startswith(node.id) or node.id.startswith(k)]
                if cands:
                    return self.variables[max(cands, key=len)]
                raise ValueError(f"未找到物种「{node.id}」，请检查表达式与文件列表")
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

    class LogExtractorApp:
        def __init__(self, root):
            self.root = root
            self.root.title("Gaussian 热力学数据提取器 · 增强版")
            self.root.geometry("1120x780")
            self.root.minsize(1000, 660)
            self.root.configure(bg=COLORS["bg"])

            self.file_data = []
            self.energy_type = tk.StringVar(value="总自由能")
            self.unit = tk.StringVar(value="Hartree")
            self.zero_point = tk.StringVar(value="(不设定，显示绝对值)")
            # expression 是"编辑缓冲区"（绑在输入框上），真正存储分两处：
            #   · 全局：self.global_expr / self.global_alias（一个表达式算一个值）
            #   · 每个文件：file_data[i]["expr"] / ["expr_alias"]
            # 切换编辑目标时先 flush 缓冲区到旧目标，再从新目标 load 回来。
            self.expression = tk.StringVar(value="")
            self.expr_target = tk.StringVar(value=GLOBAL_EXPR)
            self.global_expr = ""
            self.global_alias = {}
            self._expr_alias = {}
            self.advanced_visible = tk.BooleanVar(value=False)
            self._drag_data = {"item": None, "idx": None}
            # 绘图用深色配色表。原代码把它写成 _refresh_preview 内的局部变量 S，
            # 而 _refresh_plot 访问的是 self.S —— 该属性从未被赋值，会在
            # 启动时（__init__ 末尾调用 _refresh_plot）抛 AttributeError。
            self.S = {"bg": "#070b19", "cyan": "#00f0ff", "lime": "#39ff14",
                      "grid": "#1c2740", "txt": "#c9d8ff", "sub": "#6f86c2",
                      "linecore": "#eafcff", "magenta": "#ff2bd6",
                      "violet": "#8b5cf6"}

            self.setup_styles()
            self.create_widgets()
            self._refresh_zero_options()
            self._refresh_order_tree()
            self._refresh_plot()

        def _detect_font(self):
            """
            探测系统中真实存在的中文字体。
            中文 Windows 一般有微软雅黑；精简/英文系统可能没有，此时回退到
            系统默认字体，避免 tkinter 因找不到字体而回退到方块字形。
            """
            try:
                import tkinter.font as tkfont
                avail = set(tkfont.families())
                for cand in ("微软雅黑", "Microsoft YaHei", "SimHei", "DengXian",
                             "Segoe UI", "TkDefaultFont", "TkTextFont"):
                    if cand in avail:
                        return cand
            except Exception:
                pass
            return "TkDefaultFont"

        def setup_styles(self):
            self.FONT = self._detect_font()
            self.MONO = self.FONT
            try:
                import tkinter.font as _tkfont
                if "Consolas" in set(_tkfont.families()):
                    self.MONO = "Consolas"
            except Exception:
                pass
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("TFrame", background=COLORS["bg"])
            style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"],
                            font=(self.FONT,10))
            for name, fg in (("Primary.TButton", "white"), ("Accent.TButton", "white"),
                             ("Teal.TButton", "#073b4c"), ("Orange.TButton", "#3d2b1f"),
                             ("Ghost.TButton", COLORS["primary_d"])):
                style.configure(name, font=(self.FONT,10, "bold"), padding=(12, 6),
                                foreground=fg, borderwidth=0)
            style.map("Primary.TButton", background=[("active", COLORS["primary_d"]),
                                                    ("disabled", "#b8c0e0")],
                      foreground=[("!active", "white")])
            style.map("Accent.TButton", background=[("active", "#560bad"),
                                                   ("disabled", "#d0b3e0")],
                      foreground=[("!active", "white")])
            style.map("Teal.TButton", background=[("active", "#04a97f"),
                                                 ("disabled", "#bfe8dc")],
                      foreground=[("!active", "#073b4c")])
            style.map("Orange.TButton", background=[("active", "#e08a45"),
                                                   ("disabled", "#f0dcc6")],
                      foreground=[("!active", "#3d2b1f")])
            style.map("Ghost.TButton", background=[("active", "#e2e7fb")],
                      foreground=[("!active", COLORS["primary_d"])])
            style.configure("TProgressbar", thickness=14, background=COLORS["teal"],
                            troughcolor="#e2e7fb", borderwidth=0)
            style.configure("Treeview.Heading", font=(self.FONT,10, "bold"),
                            background=COLORS["primary"], foreground="white",
                            borderwidth=0, relief="flat")
            style.map("Treeview.Heading", background=[("active", COLORS["primary_d"])])
            style.configure("Treeview", font=(self.FONT,9), rowheight=26,
                            background=COLORS["panel"], foreground=COLORS["text"],
                            fieldbackground=COLORS["panel"], borderwidth=0)
            style.map("Treeview", background=[("selected", COLORS["primary"])])
            style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            style.configure("TLabelframe", background=COLORS["panel"],
                            foreground=COLORS["primary_d"],
                            font=(self.FONT,10, "bold"))
            style.configure("TLabelframe.Label", background=COLORS["panel"],
                            foreground=COLORS["primary_d"],
                            font=(self.FONT,10, "bold"))
            style.configure("TCombobox", font=(self.FONT,10), padding=4)
            style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", font=(self.FONT,10, "bold"), padding=(12, 5),
                            background=COLORS["panel"], foreground=COLORS["subtext"])
            style.map("TNotebook.Tab", background=[("selected", COLORS["primary"])],
                      foreground=[("selected", "white")])

        def create_widgets(self):
            top = tk.Frame(self.root, bg=COLORS["primary_d"], height=66)
            top.pack(fill=tk.X)
            top.pack_propagate(False)
            tk.Label(top, text="Gaussian Log 热力学数据提取器", bg=COLORS["primary_d"],
                     fg="white", font=(self.FONT,16, "bold")).pack(side=tk.LEFT, padx=20)
            tk.Label(top, text="增强版 · 支持相对能量计算与能量剖面图", bg=COLORS["primary_d"],
                     fg="#cdd7ff", font=(self.FONT,9)).pack(side=tk.LEFT, padx=10)
            switch_frame = tk.Frame(top, bg=COLORS["primary_d"])
            switch_frame.pack(side=tk.RIGHT, padx=16)
            tk.Label(switch_frame, text="高级功能", bg=COLORS["primary_d"], fg="white",
                     font=(self.FONT,10, "bold")).pack(side=tk.LEFT, padx=(0, 8))
            self.adv_switch = ttk.Checkbutton(
                switch_frame, text="展开", style="TButton",
                variable=self.advanced_visible, command=self.toggle_advanced,
                onvalue=True, offvalue=False)
            self.adv_switch.pack(side=tk.LEFT)

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

            self.statusbar = tk.Label(self.root, text="就绪（双击 launcher.py 启动）", anchor=tk.W, bg=COLORS["primary"],
                                      fg="white", font=(self.FONT,9), padx=12, pady=4)
            self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

        def _build_basic_panel(self, parent):
            parent.rowconfigure(2, weight=1)
            parent.columnconfigure(0, weight=1)
            btn_card = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"],
                                highlightthickness=1)
            btn_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            btns = [("添加文件", self.add_files, "Primary.TButton"),
                    ("添加文件夹", self.add_folder, "Primary.TButton"),
                    ("清空列表", self.clear_list, "Orange.TButton"),
                    ("\u25b6 开始提取", self.start_extract, "Teal.TButton"),
                    ("导出表格", self.export_csv, "Accent.TButton")]
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
            tk.Label(table_card, text="提取结果", bg=COLORS["panel"],
                     fg=COLORS["primary_d"], font=(self.FONT,11, "bold")).grid(
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

        def _build_advanced_panel(self, parent):
            parent.rowconfigure(0, weight=1)
            parent.columnconfigure(0, weight=1)
            nb = ttk.Notebook(parent)
            nb.grid(row=0, column=0, sticky="nsew")
            self.adv_notebook = nb
            calc_frame = ttk.Frame(nb, style="TFrame", padding=8)
            nb.add(calc_frame, text="能量计算与剖面图")
            self._build_calc_tab(calc_frame)
            order_frame = ttk.Frame(nb, style="TFrame", padding=8)
            nb.add(order_frame, text="自定义顺序")
            self._build_order_tab(order_frame)

        def _build_calc_tab(self, parent):
            parent.rowconfigure(5, weight=1)
            parent.columnconfigure(0, weight=1)
            settings = tk.LabelFrame(parent, text="能量设置", bg=COLORS["panel"],
                                     fg=COLORS["primary_d"], font=(self.FONT,10, "bold"),
                                     highlightbackground=COLORS["border"], highlightthickness=1)
            settings.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            for c in range(4):
                settings.columnconfigure(c, weight=1)
            tk.Label(settings, text="能量类型：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.FONT,10)).grid(row=0, column=0, sticky="e", padx=6, pady=8)
            self.energy_combo = ttk.Combobox(settings, textvariable=self.energy_type,
                                             values=list(ENERGY_OPTIONS), state="readonly",
                                             width=14)
            self.energy_combo.grid(row=0, column=1, sticky="ew", padx=6, pady=8)
            self.energy_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_all())
            tk.Label(settings, text="单位：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.FONT,10)).grid(row=0, column=2, sticky="e", padx=6, pady=8)
            unit_frame = tk.Frame(settings, bg=COLORS["panel"])
            unit_frame.grid(row=0, column=3, sticky="ew", padx=6, pady=8)
            for txt, val in [("Hartree", "Hartree"), ("kcal/mol", "kcal/mol")]:
                ttk.Radiobutton(unit_frame, text=txt, value=val, variable=self.unit,
                                command=self._refresh_all).pack(side=tk.LEFT, padx=4)
            expr_card = tk.LabelFrame(parent, text="相对能量表达式", bg=COLORS["panel"],
                                      fg=COLORS["primary_d"], font=(self.FONT,10, "bold"),
                                      highlightbackground=COLORS["border"], highlightthickness=1)
            expr_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
            expr_card.columnconfigure(1, weight=1)
            # --- 第 0 行：选择"给谁搭表达式" ---
            tk.Label(expr_card, text="编辑对象：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.FONT,10)).grid(row=0, column=0, sticky="e", padx=6, pady=(8, 4))
            tgt_row = tk.Frame(expr_card, bg=COLORS["panel"])
            tgt_row.grid(row=0, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 4))
            self.expr_target_combo = ttk.Combobox(tgt_row, textvariable=self.expr_target,
                                                  values=[GLOBAL_EXPR], state="readonly",
                                                  width=22)
            self.expr_target_combo.pack(side=tk.LEFT)
            self.expr_target_combo.bind("<<ComboboxSelected>>",
                                        lambda e: self._on_expr_target_changed())
            ttk.Button(tgt_row, text="拖放构建", style="Accent.TButton",
                       command=self._open_expr_builder).pack(side=tk.LEFT, padx=6)
            ttk.Button(tgt_row, text="清除该表达式", style="Orange.TButton",
                       command=self._clear_expr_for_target).pack(side=tk.LEFT)
            # --- 第 1 行：零点（无自定义表达式时的回退基准） ---
            tk.Label(expr_card, text="零点：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.FONT,10)).grid(row=1, column=0, sticky="e", padx=6, pady=4)
            self.zero_combo = ttk.Combobox(expr_card, textvariable=self.zero_point,
                                           values=[NO_ZERO], state="readonly",
                                           width=24)
            self.zero_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
            self.zero_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_all())
            ttk.Button(expr_card, text="设为表达式", style="Teal.TButton",
                       command=self._use_zero_in_expr).grid(row=1, column=2, padx=6, pady=4)
            # --- 第 2 行：表达式（可直接手写，也可由构建器写入） ---
            tk.Label(expr_card, text="表达式：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.FONT,10)).grid(row=2, column=0, sticky="e", padx=6, pady=4)
            expr_entry = tk.Entry(expr_card, textvariable=self.expression,
                                  font=(self.MONO,12, "bold"), fg=COLORS["accent"],
                                  bg="#fbfaff", relief="solid", highlightthickness=1,
                                  highlightbackground=COLORS["border"])
            expr_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=4)
            expr_entry.bind("<KeyRelease>", lambda e: self._refresh_all())
            self.expr_target_hint = tk.Label(expr_card, text="", bg=COLORS["panel"],
                                             fg=COLORS["subtext"], font=(self.FONT,9))
            self.expr_target_hint.grid(row=2, column=2, sticky="w", padx=6, pady=4)
            tk.Label(expr_card,
                     text="提示：选「某个文件」= 给该文件单独搭表达式（最终结果就是它的相对能量）；"
                          "选「全局」= 只算一个值。可手写，也可点「拖放构建」用鼠标拖。",
                     bg=COLORS["panel"], fg=COLORS["subtext"], font=(self.FONT,8),
                     anchor="w", wraplength=760, justify="left"
                     ).grid(row=3, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 6))
            self.expr_result = tk.Label(expr_card, text="", bg=COLORS["panel"],
                                        fg=COLORS["primary_d"], font=(self.FONT,10, "bold"),
                                        anchor="w")
            self.expr_result.grid(row=4, column=0, columnspan=3, sticky="ew", padx=6, pady=(0, 8))
            preview_card = tk.LabelFrame(parent, text="相对能量预览", bg=COLORS["panel"],
                                         fg=COLORS["primary_d"], font=(self.FONT,10, "bold"),
                                         highlightbackground=COLORS["border"], highlightthickness=1)
            preview_card.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
            preview_card.rowconfigure(0, weight=1)
            preview_card.columnconfigure(0, weight=1)
            pcols = ("显示顺序", "物种", "原始能量(Hartree)", "相对能量", "单位",
                     "自定义表达式")
            self.preview_tree = ttk.Treeview(preview_card, columns=pcols, show="headings",
                                            height=6)
            for col in pcols:
                self.preview_tree.heading(col, text=col)
                if col == "物种":
                    self.preview_tree.column(col, width=130, anchor="w")
                elif col == "显示顺序":
                    self.preview_tree.column(col, width=60, anchor="center")
                elif col == "单位":
                    self.preview_tree.column(col, width=80, anchor="center")
                elif col == "自定义表达式":
                    self.preview_tree.column(col, width=190, anchor="w")
                else:
                    self.preview_tree.column(col, width=130, anchor="center")
            self.preview_tree.tag_configure("zero", background=COLORS["yellow"])
            # 自己搭了表达式的行用另一种底色标出，一眼看出哪些是定制的
            self.preview_tree.tag_configure("custom", background=COLORS["row_alt"])
            self.preview_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
            plot_card = tk.LabelFrame(parent, text="反应坐标能量剖面图 (Reaction Profile)",
                                      bg=COLORS["panel"], fg=COLORS["primary_d"],
                                      font=(self.FONT,10, "bold"),
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
                tk.Label(plot_card, text="未检测到 matplotlib，无法显示图表。",
                         bg=COLORS["panel"], fg=COLORS["red"],
                         font=(self.FONT,10)).pack(expand=True)
            adv_btn = tk.Frame(parent, bg=COLORS["bg"])
            adv_btn.grid(row=6, column=0, sticky="ew", pady=(0, 4))
            ttk.Button(adv_btn, text="刷新预览与图表", style="Primary.TButton",
                       command=self._refresh_all).pack(side=tk.LEFT, padx=3)
            ttk.Button(adv_btn, text="导出相对能量 CSV", style="Accent.TButton",
                       command=self.export_relative_csv).pack(side=tk.LEFT, padx=3)
            ttk.Button(adv_btn, text="保存图表", style="Teal.TButton",
                       command=self.save_plot).pack(side=tk.LEFT, padx=3)
            ttk.Button(adv_btn, text="在新窗口打开图表", style="Orange.TButton",
                       command=self._open_plot_window).pack(side=tk.LEFT, padx=3)
            ttk.Button(adv_btn, text="应用到全部", style="Ghost.TButton",
                       command=self._apply_expr_to_all).pack(side=tk.RIGHT, padx=3)

        def _build_order_tab(self, parent):
            parent.rowconfigure(1, weight=1)
            parent.columnconfigure(0, weight=1)
            tk.Label(parent, text="拖拽行以调整物种在能量剖面图中的显示顺序（也决定反应坐标顺序）",
                     bg=COLORS["bg"], fg=COLORS["subtext"], font=(self.FONT,9)).grid(
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
            ttk.Button(btn_row, text="上移", style="Primary.TButton",
                       command=lambda: self._move_order(-1)).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_row, text="下移", style="Primary.TButton",
                       command=lambda: self._move_order(1)).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_row, text="置顶", style="Ghost.TButton",
                       command=lambda: self._move_order_to("top")).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_row, text="置底", style="Ghost.TButton",
                       command=lambda: self._move_order_to("bottom")).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_row, text="按名称排序", style="Teal.TButton",
                       command=self._order_by_name).pack(side=tk.LEFT, padx=3)
            ttk.Button(btn_row, text="确认顺序", style="Accent.TButton",
                       command=self._confirm_order).pack(side=tk.RIGHT, padx=3)

        def toggle_advanced(self):
            if self.advanced_visible.get():
                self.adv_outer.grid()
                self.root.after(50, self._refresh_all)
                self.statusbar.config(text="高级功能已展开")
            else:
                self.adv_outer.grid_remove()
                self.statusbar.config(text="就绪（双击 launcher.py 启动）")

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
        @staticmethod
        def _new_entry(path, name):
            # expr / expr_alias：该文件专属的表达式与变量别名表。
            # 每个文件都能自己搭一套表达式来算自己的相对能量，
            # 没搭的则回退到"原始能量 - 零点"的老逻辑。
            return {"path": path, "name": name, "scf": None, "gibbs": None,
                    "free": None, "status": "待处理",
                    "expr": "", "expr_alias": {}}

        def update_treeview(self):
            self.tree.delete(*self.tree.get_children())
            for data in self.file_data:
                tag = {"已完成": "done", "失败": "fail", "处理中": "proc"}.get(data["status"], "")
                self.tree.insert("", "end", values=(
                    data["name"],
                    f"{data['scf']:.6f}" if data['scf'] is not None else "",
                    f"{data['gibbs']:.6f}" if data['gibbs'] is not None else "",
                    f"{data['free']:.6f}" if data['free'] is not None else "",
                    data["status"]), tags=(tag,))

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

        def _iter_descendants(self, widget):
            """递归遍历 widget 的所有子孙（含 widget 自身）。

            winfo_descendants() 是 Tk 8.6 才引入的方法，8.5 及更早版本
            只有 winfo_children()。Windows 上部分 Python 自带的 Tcl/Tk
            是 8.5，直接调用 winfo_descendants() 会抛 AttributeError。
            这里用 winfo_children() 手动递归，兼容所有版本。
            """
            yield widget
            try:
                children = widget.winfo_children()
            except Exception:
                return
            for ch in children:
                yield from self._iter_descendants(ch)

        def _disable_buttons(self):
            """禁用控制按钮，但绝不禁用状态栏；用 state() 方法而非 config()。"""
            for w in self._iter_descendants(self.root):
                if isinstance(w, ttk.Button):
                    try:
                        w.state(["disabled"])
                    except Exception:
                        try:
                            w.config(state="disabled")
                        except Exception:
                            pass

        def _enable_buttons(self):
            for w in self._iter_descendants(self.root):
                if isinstance(w, ttk.Button):
                    try:
                        w.state(["!disabled"])
                    except Exception:
                        try:
                            w.config(state="normal")
                        except Exception:
                            pass

        def start_extract(self):
            if not self.file_data:
                self.statusbar.config(text="提示：请先添加 Log 文件")
                messagebox.showinfo("提示", "请先添加 Log 文件")
                return
            # 关键：用索引快照，避免提取过程中用户增删导致错位
            pending = [i for i, d in enumerate(self.file_data)
                       if d["status"] in ("待处理", "失败")]
            if not pending:
                self.statusbar.config(text="提示：所有文件已处理完毕")
                messagebox.showinfo("提示", "所有文件已处理完毕")
                return
            self._disable_buttons()
            total = len(pending)
            self.progress.config(maximum=total, value=0)
            self.statusbar.config(text=f"正在提取... 0/{total}")
            self.update_treeview()

            def process_next(queue):
                """逐个文件处理，用 after 串行化，避免线程内操作 UI。"""
                if not queue:
                    self._extract_finished()
                    return
                idx = queue[0]
                rest = queue[1:]
                if idx >= len(self.file_data):
                    # 数据已被改动，重新计算剩余项
                    self.root.after(0, lambda: process_next(rest))
                    return
                data = self.file_data[idx]
                data["status"] = "处理中"
                self.update_treeview()
                self.root.update_idletasks()
                try:
                    scf, gibbs, free = self.parse_log(data["path"])
                    data["scf"], data["gibbs"], data["free"] = scf, gibbs, free
                    if scf is None:
                        data["status"] = "失败：SCF未收敛"
                    elif gibbs is None or free is None:
                        data["status"] = "失败：缺失频率计算"
                    else:
                        data["status"] = "已完成"
                except Exception as e:
                    data["status"] = f"失败：{e}"
                done = total - len(rest)
                self.progress.config(value=done)
                self.statusbar.config(text=f"正在处理... {done}/{total}")
                self.update_treeview()
                # 下一个文件，让 UI 有机会刷新
                self.root.after(20, lambda q=rest: process_next(q))

            process_next(pending)

        def _extract_finished(self):
            self.progress.config(value=self.progress.cget("maximum"))
            self.statusbar.config(text="提取完成")
            self.update_treeview()
            self._refresh_all()
            self._enable_buttons()
            messagebox.showinfo("完成", "所有文件提取完毕！")

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
                                    f"{d['scf']:.6f}" if d['scf'] is not None else "",
                                    f"{d['gibbs']:.6f}" if d['gibbs'] is not None else "",
                                    f"{d['free']:.6f}" if d['free'] is not None else "",
                                    d["status"]])
                messagebox.showinfo("成功", f"CSV 已保存至：{path}")
            except Exception as e:
                messagebox.showerror("错误", f"导出失败：{e}")

        def _energy_key(self):
            return {"SCF 能量": "scf", "Gibbs 热校正": "gibbs", "总自由能": "free"}[self.energy_type.get()]

        def _current_energy_map(self):
            key = self._energy_key()
            return {d["name"]: d[key] for d in self.file_data}

        def _has_energy(self, d):
            return d[self._energy_key()] is not None

        def _custom_order(self):
            items = [self.order_tree.item(it)["values"]
                     for it in self.order_tree.get_children()]
            if items:
                return [row[1] for row in items]
            return [d["name"] for d in self.file_data]

        def _relative_results(self):
            """计算各物种最终显示的相对能量。

            优先级：
              1. 该文件自己搭了表达式 -> 用表达式结果作为它的相对能量
                 （表达式里已经写明减谁，所以不再重复减零点）
              2. 没搭 -> 回退到"原始能量 - 零点"的老逻辑
              3. 若所有文件都没搭，且填了全局表达式 -> 只算一个值（旧行为）
            """
            energy_map = self._current_energy_map()
            unit = self.unit.get()
            zero_sel = self.zero_point.get()
            fac = HARTREE_TO_KCAL if unit == "kcal/mol" else 1.0
            zero_name, zero_val = None, None
            if zero_sel != NO_ZERO and zero_sel in energy_map:
                zero_name, zero_val = zero_sel, energy_map[zero_sel]

            # ---- 只有全部文件都没自定义表达式时，才走全局单一结果模式 ----
            if not self._has_custom_expr():
                expr = (self.global_expr or "").strip()
                if expr:
                    emap = dict(energy_map)
                    for v, real in (self.global_alias or {}).items():
                        if real in emap and v not in emap:
                            emap[v] = emap[real]
                    val_hartree = EnergyExpressionEvaluator(emap).evaluate(expr)
                    rel = val_hartree * fac
                    return {"zero_name": None, "unit": unit, "mode": "expr",
                            "points": [(f"{expr} =", 1, val_hartree, rel, False, expr)],
                            "value_hartree": val_hartree}

            # ---- 列表模式：逐个物种算 ----
            order = self._custom_order()
            ordered = [n for n in order if n in energy_map and energy_map[n] is not None]
            points = []
            for i, name in enumerate(ordered, start=1):
                raw = energy_map[name]
                d = self._find_by_name(name)
                ex = ((d.get("expr") or "").strip() if d else "")
                if ex:
                    emap = dict(energy_map)
                    for v, real in (d.get("expr_alias") or {}).items():
                        if real in emap and v not in emap:
                            emap[v] = emap[real]
                    # 表达式自身就是"相对谁"，结果直接作为相对能量
                    rel = EnergyExpressionEvaluator(emap).evaluate(ex) * fac
                    is_zero = False
                else:
                    base = (raw - zero_val) if zero_val is not None else raw
                    rel = base * fac
                    is_zero = (name == zero_name)
                points.append((name, i, raw, rel, is_zero, ex))
            return {"zero_name": zero_name, "unit": unit, "mode": "list",
                    "points": points}

        def _refresh_all(self):
            # 输入框里的内容先落到当前编辑对象上，后续计算才读得到
            self._save_expr_to_target()
            self._refresh_expr_target_options()
            self._refresh_zero_options()
            self._refresh_order_tree()
            self._refresh_preview()
            self._refresh_plot()
            self._sync_plot_window()

        def _refresh_zero_options(self):
            names = [d["name"] for d in self.file_data if self._has_energy(d)]
            opts = ["(不设定，显示绝对值)"] + names
            current = self.zero_point.get()
            self.zero_combo.config(values=opts)
            if current not in opts:
                self.zero_point.set("(不设定，显示绝对值)")

        # ---------- 表达式的分文件存储 ----------
        def _find_by_name(self, name):
            return next((d for d in self.file_data if d["name"] == name), None)

        def _expr_target_file(self):
            """当前编辑目标对应的文件条目；全局模式返回 None。"""
            t = self.expr_target.get()
            if t == GLOBAL_EXPR or not t:
                return None
            return self._find_by_name(t)

        def _save_expr_to_target(self):
            """把输入框里的表达式与别名保存到当前目标（切换目标/刷新前调用）。"""
            d = self._expr_target_file()
            val = self.expression.get().strip()
            alias = dict(getattr(self, "_expr_alias", {}) or {})
            if d is None:
                self.global_expr = val
                self.global_alias = alias
            else:
                d["expr"] = val
                d["expr_alias"] = alias

        def _load_expr_from_target(self):
            """从当前目标读出已保存的表达式，填进输入框（不触发刷新）。"""
            d = self._expr_target_file()
            if d is None:
                self.expression.set(self.global_expr)
                self._expr_alias = dict(self.global_alias or {})
            else:
                self.expression.set(d.get("expr", "") or "")
                self._expr_alias = dict(d.get("expr_alias") or {})

        def _on_expr_target_changed(self):
            """切换编辑对象：先存旧的，再载入新的。"""
            self._save_expr_to_target()
            self._load_expr_from_target()
            self._refresh_all()

        def _refresh_expr_target_options(self):
            names = [d["name"] for d in self.file_data]
            opts = [GLOBAL_EXPR] + names
            cur = self.expr_target.get()
            self.expr_target_combo.config(values=opts)
            if cur not in opts:
                # 目标文件被删掉了，退回全局并重新载入
                self.expr_target.set(GLOBAL_EXPR)
                self._load_expr_from_target()
            hint = "整体算一个值" if self.expr_target.get() == GLOBAL_EXPR else "该文件的最终相对能量"
            self.expr_target_hint.config(text=hint)

        def _has_custom_expr(self):
            return any((d.get("expr") or "").strip() for d in self.file_data)

        def _clear_expr_for_target(self):
            """清除当前编辑对象已保存的表达式。"""
            d = self._expr_target_file()
            who = self.expr_target.get()
            if d is None:
                self.global_expr = ""
                self.global_alias = {}
            else:
                d["expr"] = ""
                d["expr_alias"] = {}
            self._expr_alias = {}
            self.expression.set("")
            self._refresh_all()
            self.statusbar.config(text=f"已清除 {who} 的表达式")

        def _open_expr_builder(self):
            """打开可视化表达式构建器（拖放即可，无需输入）。

            构建结果保存到"当前编辑对象"：选了某个文件就存到该文件上，
            选全局就存到全局。这样每个文件都能有自己的一套表达式。
            """
            names = [d["name"] for d in self.file_data if self._has_energy(d)]
            if not names:
                messagebox.showinfo("提示", "还没有可参与计算的物种，请先添加并完成提取。")
                return
            self._save_expr_to_target()
            d = self._expr_target_file()
            try:
                ExpressionBuilder(self, None if d is None else d["name"])
            except Exception as e:
                # 构建失败时明确告知，而不是丢一个空白窗口让人无从判断
                import traceback
                traceback.print_exc()
                messagebox.showerror("构建器打开失败",
                                     f"{type(e).__name__}: {e}\n\n"
                                     f"详细堆栈已打印到控制台。")

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
                    "-", result["points"][0][0], f"{hartree:.6f}",
                    f"{v:+.4f}", unit, self.global_expr), tags=("zero",))
                return
            zero_name = result["zero_name"]
            if zero_name:
                self.expr_result.config(
                    text=f"参考零点 = {zero_name}（显示各物种相对 {zero_name} 的能量）",
                    fg=COLORS["primary_d"])
            else:
                self.expr_result.config(
                    text="未设零点：显示各物种该能量类型的原始值（无相对意义）",
                    fg=COLORS["subtext"])
            for row in result["points"]:
                name, order, raw, disp, is_zero = row[0], row[1], row[2], row[3], row[4]
                ex = row[5] if len(row) > 5 else ""
                tags = []
                if is_zero:
                    tags.append("zero")
                elif ex:
                    tags.append("custom")
                self.preview_tree.insert("", "end", values=(
                    order, name, f"{raw:.6f}", f"{disp:+.4f}", unit, ex or "—"),
                    tags=tuple(tags))

        S = {"bg": "#070b19", "cyan": "#00f0ff", "lime": "#39ff14",
             "grid": "#1c2740", "txt": "#c9d8ff", "sub": "#6f86c2",
             "linecore": "#eafcff", "magenta": "#ff2bd6", "violet": "#8b5cf6"}

        def _xtick_labels(self, labels, max_labels=None):
            """生成 x 轴标签。

            物种一多，每个点都标全名会挤成一团完全看不清。这里做两级降级：
              1. 过长的名字先截断，避免单个标签占太宽；
              2. 超过 max_labels 时均匀抽稀 —— 抽中的位显示「[序号] 名字」，
                 被跳过的位只显示序号，既省宽度又能和上方预览表对上。
            """
            def short(t):
                t = str(t)
                return t if len(t) <= 14 else t[:13] + "…"

            n = len(labels)
            if max_labels and n > max_labels:
                step = (n + max_labels - 1) // max_labels   # 向上取整
                out = []
                for i, l in enumerate(labels):
                    if i % step == 0 or i == n - 1:
                        out.append(f"[{i}] {short(l)}")
                    else:
                        out.append(str(i))
                return out
            return [f"[{i}] {short(l)}" for i, l in enumerate(labels)]

        def _draw_profile(self, ax, max_labels=None, rotation=0):
            """把能量剖面图画到指定 axes 上。

            主窗口小图与独立大窗口共用同一套绘图逻辑，只通过 max_labels /
            rotation 控制标签密度，避免两处各写一遍导致显示不一致。

            max_labels: x 轴最多显示几个完整标签，超出则抽稀
            rotation:   x 轴标签旋转角度，标签长或点多时倾斜可显著减少重叠
            """
            import matplotlib.colors as mcolors
            from matplotlib.collections import PolyCollection
            import numpy as _np

            ax.set_facecolor(self.S["bg"])
            ax.figure.patch.set_facecolor(self.S["bg"])
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
                return   # 画布刷新交给调用方，绘图核心不碰具体 canvas
            unit = result["unit"]
            points = result["points"]
            labels = [p[0] for p in points]
            values = [p[3] for p in points]
            neon = [self.S["lime"], self.S["magenta"], self.S["violet"],
                    "#ffb000", self.S["cyan"], "#ff5e9c", "#2f80ff"]
            colors = [self.S["lime"] if p[4] else neon[i % len(neon)]
                      for i, p in enumerate(points)]
            x = list(range(len(values)))
            n = len(x)
            grad = _np.linspace(0, 1, 256).reshape(1, -1)
            grad = _np.vstack([grad] * 16)
            cmap = mcolors.LinearSegmentedColormap.from_list("space", ["#050914", "#0a1024"])
            vmin, vmax = min(values + [0]), max(values + [0])
            pad = (vmax - vmin) * 0.25 + 1
            ax.imshow(grad, extent=[-0.55, n - 0.45, vmin - pad, vmax + pad],
                      aspect="auto", cmap=cmap, zorder=0)
            if result.get("mode") == "list" and result.get("zero_name"):
                ax.axhline(0, color=self.S["lime"], lw=1.6, alpha=0.95, zorder=2)
                ax.axhline(0, color=self.S["lime"], lw=7, alpha=0.11, zorder=1)
                ax.text(n - 0.5, 0, "  ZERO POINT", color=self.S["lime"],
                        va="center", fontsize=8.5, fontweight="bold", alpha=0.9)
            for i in range(n - 1):
                xseg = _np.linspace(x[i], x[i + 1], 60)
                yseg = _np.interp(xseg, x, values)
                pts = [[(float(xx), float(yy)), (float(xx), 0.0)] for xx, yy in zip(xseg, yseg)]
                pc = PolyCollection(pts, facecolors=[colors[i]] * len(pts), alpha=0.11, zorder=2)
                ax.add_collection(pc)
            ax.plot(x, values, "-", color=self.S["cyan"], lw=8, alpha=0.13,
                    solid_capstyle="round", zorder=3)
            ax.plot(x, values, "-", color=self.S["cyan"], lw=3.4, alpha=0.55,
                    solid_capstyle="round", zorder=4)
            ax.plot(x, values, "-", color=self.S["linecore"], lw=1.2, alpha=0.95,
                    solid_capstyle="round", zorder=5)
            for xi, yi, c in zip(x, values, colors):
                ax.scatter([xi], [yi], s=560, color=c, alpha=0.13, edgecolors="none", zorder=6)
                ax.scatter([xi], [yi], s=250, color=c, alpha=0.27, edgecolors="none", zorder=7)
                ax.scatter([xi], [yi], s=72, color=self.S["bg"], edgecolors=c,
                           linewidths=2.5, zorder=8)
            for xi, yi, c in zip(x, values, colors):
                offset = 18 if yi >= 0 else -23
                ax.annotate(f"{yi:+.1f}", (xi, yi), textcoords="offset points",
                            xytext=(0, offset), ha="center", fontsize=10, fontweight="bold",
                            color=c, zorder=9,
                            bbox=dict(boxstyle="round,pad=0.28", fc=self.S["bg"],
                                      ec=c, lw=1.1, alpha=0.92))
            ax.set_xticks(x)
            ax.set_xticklabels(self._xtick_labels(labels, max_labels),
                               fontsize=9.5, color=self.S["txt"],
                               rotation=rotation,
                               ha=("right" if rotation else "center"))
            # 注意：set_ylabel 没有 pad 参数（那是 set_title 的），正确名是 labelpad。
            # 传 pad 会让 matplotlib 抛 AttributeError: 'Text' object has no property 'pad'
            ax.set_ylabel("RELATIVE ENERGY  [kcal/mol]" if unit == "kcal/mol"
                          else "RELATIVE ENERGY  [Hartree]",
                          fontsize=10.5, fontweight="bold", color=self.S["cyan"],
                          labelpad=10)
            ax.tick_params(colors=self.S["sub"], length=0)
            for sp in ("top", "right", "left"):
                ax.spines[sp].set_visible(False)
            ax.spines["bottom"].set_color(self.S["grid"])
            for sp in ax.spines.values():
                sp.set_linewidth(1.2)
            ax.grid(axis="y", which="major", color=self.S["grid"], lw=0.9, alpha=0.9, zorder=1)
            ax.grid(axis="y", which="minor", color=self.S["grid"], lw=0.4, alpha=0.45, zorder=1)
            ax.set_axisbelow(True)
            from matplotlib.ticker import AutoMinorLocator
            ax.yaxis.set_minor_locator(AutoMinorLocator())
            etype = self.energy_type.get()
            etag = {"SCF 能量": "SCF", "Gibbs 热校正": "ΔG_corr", "总自由能": "ΔG"}[etype]
            ax.set_title("REACTION PROFILE", color=self.S["cyan"], fontsize=15,
                         fontweight="bold", pad=22, loc="left")
            ax.text(0.0, 1.045, f"Σ {etag}  ·  {unit}", transform=ax.transAxes,
                    color=self.S["sub"], fontsize=9, fontweight="bold")
            ax.plot([0.0, 0.18], [1.012, 1.012], transform=ax.transAxes, color=self.S["cyan"], lw=1.6)
            ax.plot([0.82, 1.0], [1.012, 1.012], transform=ax.transAxes, color=self.S["cyan"], lw=1.6)
            

        def _refresh_plot(self):
            if not HAS_MPL:
                return
            # 必须清 fig 而不是只清 ax：原代码每次刷新都 add_axes 一次，
            # 会不断叠加新的坐标系图层，越刷越糊。
            self.fig.clear()
            ax = self.fig.add_axes([0.10, 0.16, 0.86, 0.68])
            self.ax = ax
            # 主窗口图表区窄，最多显示 6 个完整标签，其余只显示序号
            self._draw_profile(ax, max_labels=6)
            self.canvas.draw_idle()
            self._sync_plot_window()

        # ---------- 独立大窗口 ----------
        def _sync_plot_window(self):
            """主窗口数据变化时，同步刷新已打开的独立图表窗口。"""
            win = getattr(self, "_plot_win", None)
            if not win:
                return
            try:
                if win.winfo_exists():
                    self.root.after_idle(self._redraw_plot_window)
            except Exception:
                pass

        def _open_plot_window(self):
            """在独立窗口中打开能量剖面图。

            主窗口的高级面板只有约一半屏宽，物种一多横坐标就挤得看不清。
            这里开一个大窗口重绘一张大图，并按窗口实际宽度决定标签密度。
            """
            if not HAS_MPL:
                messagebox.showinfo("提示", "未检测到 matplotlib，无法绘制图表。")
                return
            # 已打开则直接置前并重绘，避免开出多个窗口
            win = getattr(self, "_plot_win", None)
            if win:
                try:
                    if win.winfo_exists():
                        win.lift()
                        win.focus_force()
                        self._redraw_plot_window()
                        return
                except Exception:
                    pass

            win = tk.Toplevel(self.root)
            win.title("能量剖面图 · 独立窗口")
            win.geometry("1180x720")
            win.minsize(760, 480)
            win.configure(bg=COLORS["bg"])
            self._plot_win = win
            self._plot_fig = None
            self._plot_holder_w = 0

            bar = tk.Frame(win, bg=COLORS["primary_d"], height=48)
            bar.pack(fill=tk.X)
            bar.pack_propagate(False)
            tk.Label(bar, text="反应坐标能量剖面图", bg=COLORS["primary_d"], fg="white",
                     font=(self.FONT, 12, "bold")).pack(side=tk.LEFT, padx=14)
            ttk.Button(bar, text="刷新", style="Primary.TButton",
                       command=self._redraw_plot_window).pack(side=tk.RIGHT, padx=6)
            ttk.Button(bar, text="保存图片", style="Teal.TButton",
                       command=self._save_plot_window).pack(side=tk.RIGHT, padx=6)

            holder = tk.Frame(win, bg=COLORS["panel"])
            holder.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            holder.rowconfigure(0, weight=1)
            holder.columnconfigure(0, weight=1)
            self._plot_holder = holder
            # 窗口尺寸变化超过阈值才重绘，避免拖动时疯狂重建画布
            holder.bind("<Configure>", self._on_plot_holder_resize)
            win.protocol("WM_DELETE_WINDOW", self._close_plot_window)
            # holder 首帧宽高还是 1，等布局完成后再画
            win.after(60, self._redraw_plot_window)

        def _on_plot_holder_resize(self, event):
            prev = getattr(self, "_plot_holder_w", 0)
            if abs(event.width - prev) < 60 or event.width < 100:
                return
            self._plot_holder_w = event.width
            job = getattr(self, "_resize_job", None)
            if job:
                try:
                    self.root.after_cancel(job)
                except Exception:
                    pass
            self._resize_job = self.root.after(220, self._redraw_plot_window)

        def _redraw_plot_window(self):
            """按 holder 当前尺寸重建大图：尺寸越大，能完整显示的标签越多。"""
            holder = getattr(self, "_plot_holder", None)
            if not holder or not HAS_MPL:
                return
            try:
                if self._plot_win and not self._plot_win.winfo_exists():
                    return
            except Exception:
                return
            for child in holder.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            w = max(holder.winfo_width() or 0, 900)
            h = max(holder.winfo_height() or 0, 560)
            fig = Figure(figsize=(w / 100.0, h / 100.0), dpi=100,
                         facecolor=COLORS["panel"])
            ax = fig.add_axes([0.07, 0.14, 0.90, 0.74])
            # 约每 95px 放得下一个完整标签，据此决定显示几个
            max_labels = max(4, min(28, int(w // 95)))
            try:
                self._draw_profile(ax, max_labels=max_labels, rotation=30)
            except Exception as e:
                ax.text(0.5, 0.5, f"绘图失败：{e}", ha="center", va="center",
                        color=self.S["sub"], transform=ax.transAxes)
            canvas = FigureCanvasTkAgg(fig, master=holder)
            canvas.draw()
            canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
            self._plot_fig = fig

        def _save_plot_window(self):
            fig = getattr(self, "_plot_fig", None)
            if fig is None:
                messagebox.showinfo("提示", "图表尚未绘制，无法保存。")
                return
            path = filedialog.asksaveasfilename(
                title="保存能量剖面图", defaultextension=".png",
                filetypes=[("PNG 图片", "*.png"), ("PDF 矢量图", "*.pdf"),
                           ("SVG 矢量图", "*.svg")])
            if not path:
                return
            try:
                fig.savefig(path, dpi=180, bbox_inches="tight",
                            facecolor=COLORS["panel"])
                messagebox.showinfo("成功", f"图表已保存至：{path}")
            except Exception as e:
                messagebox.showerror("错误", f"保存失败：{e}")

        def _close_plot_window(self):
            try:
                self._plot_win.destroy()
            except Exception:
                pass
            self._plot_win = None
            self._plot_fig = None
            self._plot_holder = None


        def _refresh_order_tree(self):
            existing = list(self.order_tree.get_children())
            if existing:
                key = self._energy_key()
                for it in existing:
                    vals = self.order_tree.item(it)["values"]
                    d = next((x for x in self.file_data if x["name"] == vals[1]), None)
                    e = d[key] if d else None
                    self.order_tree.item(it, values=(vals[0], vals[1],
                                                    f"{e:.6f}" if e is not None else "-"),
                                        tags=("odd" if int(vals[0]) % 2 else ""))
                return
            for i, d in enumerate(self.file_data, start=1):
                key = self._energy_key()
                e = d[key]
                self.order_tree.insert("", "end", values=(
                    i, d["name"], f"{e:.6f}" if e is not None else "-"),
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
                        w.writerow(["表达式", "原始能量(Hartree)",
                                    f"相对能量({result['unit']})"])
                        p = result["points"][0]
                        w.writerow([self.global_expr, p[2], f"{p[3]:.6f}"])
                    else:
                        w.writerow(["显示顺序", "物种", "原始能量(Hartree)",
                                    f"相对能量({result['unit']})", "是否零点",
                                    "自定义表达式"])
                        for row in result["points"]:
                            name, order, raw, disp, is_zero = (
                                row[0], row[1], row[2], row[3], row[4])
                            ex = row[5] if len(row) > 5 else ""
                            w.writerow([order, name, f"{raw:.6f}", f"{disp:+.6f}",
                                        "是" if is_zero else "", ex])
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

    class ExpressionBuilder:
        """可视化表达式构建器：像搭积木一样用鼠标拼出表达式。

        左栏 = 物种模块（每个已提取的文件一个小方块）
        右栏 = 构建区，拖进来的方块按顺序拼成表达式
          · 按住左栏方块拖到右栏松手 = 插入一块（可插到任意位置）
          · 方块左侧的 +/- 点击切换加减，×系数 点击循环改倍数
          · 拖动已有方块可重排；拖回左栏 = 删除
          · 方块右上角 X 直接删除

        关键实现：Tk 的事件只派发给鼠标下方的控件。若把 <B1-Motion> /
        <ButtonRelease-1> 绑在源控件上，鼠标一移出就收不到事件了（上一版
        "拖不动、只能有一个" 正是这个原因）。所以拖拽期间改用窗口级
        bind_all 监听，松手后立刻 unbind_all。
        """

        COEF_CYCLE = (1.0, 0.5, 2.0, 3.0, 0.25)
        CHIP_W = 182

        def __init__(self, app, target_name=None):
            self.app = app
            # target_name=None 表示编辑"全局"；否则是这个文件的专属表达式
            self.target_name = target_name
            self.terms = []            # [{name, var, coef, op}, ...]
            self.alias = {}            # 该表达式自己的 {变量名: 真实物种名}
            self.pool_names = []
            self.pool_chips = []
            self.build_chips = []
            self._cols_pool = None
            self._cols_build = None
            self.drag = {"active": False, "source": None, "payload": None,
                         "tip": None, "name": ""}
            self.expr = ""
            self.expr_text = tk.StringVar(value="")
            self.result_text = tk.StringVar(value="—")
            self.win = tk.Toplevel(app.root)
            who = "全局" if target_name is None else target_name
            self.win.title(f"表达式构建器 · 编辑对象：{who}")
            self.win.geometry("1000x680")
            self.win.minsize(860, 560)
            self.win.configure(bg=COLORS["bg"])
            self.win.transient(app.root)
            self.win.protocol("WM_DELETE_WINDOW", self._close)
            self._build()
            self._refresh_pool()
            self._preload()
            self._render()

        # ---------------- 界面骨架 ----------------
        def _build(self):
            top = tk.Frame(self.win, bg=COLORS["primary_d"], height=54)
            top.pack(fill=tk.X)
            top.pack_propagate(False)
            tk.Label(top, text="表达式构建器", bg=COLORS["primary_d"], fg="white",
                     font=(self.app.FONT, 14, "bold")).pack(side=tk.LEFT, padx=16)
            tk.Label(top, text="按住左边的小方块拖到右边，像搭积木一样拼出表达式",
                     bg=COLORS["primary_d"], fg="#cdd7ff",
                     font=(self.app.FONT, 9)).pack(side=tk.LEFT, padx=8)
            # 注意：这里必须用 self.target_name。之前误写成裸名 target_name，
            # 而它只是 __init__ 的参数、不在 _build 作用域内，会抛 NameError
            # 并中断整个 _build —— 表现就是只剩顶部横幅、下面一片空白。
            tk.Label(top, text=("编辑对象：全局" if self.target_name is None
                                else f"编辑对象：{self.target_name}"),
                     bg=COLORS["primary_d"], fg="#ffd166",
                     font=(self.app.FONT, 10, "bold")).pack(side=tk.RIGHT, padx=16)

            body = tk.Frame(self.win, bg=COLORS["bg"])
            body.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

            # ---- 左：物种模块池 ----
            lf = tk.LabelFrame(body, text="物种模块（按住拖到右边）", bg=COLORS["panel"],
                               fg=COLORS["primary_d"], font=(self.app.FONT, 10, "bold"),
                               highlightbackground=COLORS["border"], highlightthickness=1)
            lf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
            self.pool_canvas = tk.Canvas(lf, bg=COLORS["panel"], highlightthickness=0)
            pvs = ttk.Scrollbar(lf, orient="vertical", command=self.pool_canvas.yview)
            pvs.pack(side=tk.RIGHT, fill=tk.Y, pady=6)
            self.pool_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
            self.pool_canvas.configure(yscrollcommand=pvs.set)
            self.pool_box = tk.Frame(self.pool_canvas, bg=COLORS["panel"])
            self._pw = self.pool_canvas.create_window((0, 0), window=self.pool_box,
                                                      anchor="nw")
            self.pool_box.bind("<Configure>", lambda e: self.pool_canvas.configure(
                scrollregion=self.pool_canvas.bbox("all")))
            self.pool_canvas.bind("<Configure>", self._on_canvas_resize)

            # ---- 右：构建区 ----
            rf = tk.LabelFrame(body, text="构建区（拖到这里拼起来）", bg=COLORS["panel"],
                               fg=COLORS["primary_d"], font=(self.app.FONT, 10, "bold"),
                               highlightbackground=COLORS["border"], highlightthickness=1)
            rf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0))
            self.build_canvas = tk.Canvas(rf, bg=COLORS["panel"], highlightthickness=0)
            bvs = ttk.Scrollbar(rf, orient="vertical", command=self.build_canvas.yview)
            bvs.pack(side=tk.RIGHT, fill=tk.Y, pady=6)
            self.build_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
            self.build_canvas.configure(yscrollcommand=bvs.set)
            self.build_box = tk.Frame(self.build_canvas, bg=COLORS["panel"])
            self._bw = self.build_canvas.create_window((0, 0), window=self.build_box,
                                                       anchor="nw")
            self.build_box.bind("<Configure>", lambda e: self.build_canvas.configure(
                scrollregion=self.build_canvas.bbox("all")))
            self.build_canvas.bind("<Configure>", self._on_canvas_resize)

            # ---- 底部：表达式 / 结果 / 按钮 ----
            bottom = tk.Frame(self.win, bg=COLORS["panel"],
                              highlightbackground=COLORS["border"], highlightthickness=1)
            bottom.pack(fill=tk.X, padx=8, pady=(0, 8))
            bottom.columnconfigure(1, weight=1)
            tk.Label(bottom, text="表达式：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.app.FONT, 10)).grid(row=0, column=0, sticky="e",
                                                    padx=8, pady=6)
            tk.Label(bottom, textvariable=self.expr_text, bg=COLORS["panel"],
                     fg=COLORS["accent"], font=(self.app.MONO, 12, "bold"),
                     anchor="w").grid(row=0, column=1, sticky="ew", pady=6)
            tk.Label(bottom, text="结果：", bg=COLORS["panel"], fg=COLORS["text"],
                     font=(self.app.FONT, 10)).grid(row=1, column=0, sticky="e",
                                                    padx=8, pady=(0, 6))
            tk.Label(bottom, textvariable=self.result_text, bg=COLORS["panel"],
                     fg=COLORS["primary_d"], font=(self.app.MONO, 12, "bold"),
                     anchor="w").grid(row=1, column=1, sticky="ew", pady=(0, 6))
            bf = tk.Frame(bottom, bg=COLORS["panel"])
            bf.grid(row=0, column=2, rowspan=2, padx=8)
            ttk.Button(bf, text="清空", style="Orange.TButton",
                       command=self._clear).pack(side=tk.LEFT, padx=3)
            ttk.Button(bf, text="应用", style="Primary.TButton",
                       command=self._apply).pack(side=tk.LEFT, padx=3)
            ttk.Button(bf, text="关闭", style="Ghost.TButton",
                       command=self._close).pack(side=tk.LEFT, padx=3)

        def _on_canvas_resize(self, event):
            try:
                if event.widget is self.pool_canvas:
                    self.pool_canvas.itemconfigure(self._pw, width=event.width)
                else:
                    self.build_canvas.itemconfigure(self._bw, width=event.width)
            except Exception:
                pass
            self._relayout_if_needed()

        def _relayout_if_needed(self):
            """列数变化时才重排，避免拖动窗口时疯狂重建。"""
            cp = max(1, (self.pool_canvas.winfo_width() or 320) // self.CHIP_W)
            cb = max(1, (self.build_canvas.winfo_width() or 420) // self.CHIP_W)
            if cp != self._cols_pool:
                self._cols_pool = cp
                self._render_pool()
            if cb != self._cols_build:
                self._cols_build = cb
                self._render()

        # ---------------- 数据 ----------------
        def _refresh_pool(self):
            self.pool_names = [d["name"] for d in self.app.file_data
                               if self.app._has_energy(d)]
            self._render_pool()

        def _var_for(self, real):
            base = sanitize_name(real)
            used = {t["var"] for t in self.terms}
            v, k = base, 1
            while v in used:
                v = "%s_%d" % (base, k)
                k += 1
            if v != real:
                self.alias[v] = real
            return v

        def _insert_term(self, name, idx=None):
            op = "-" if self.terms else "+"
            t = {"name": name, "var": self._var_for(name), "coef": 1.0, "op": op}
            if idx is None:
                idx = len(self.terms)
            self.terms.insert(max(0, min(len(self.terms), idx)), t)
            self._render()

        def _move_term(self, src, tgt):
            if not (0 <= src < len(self.terms)) or tgt is None:
                return
            item = self.terms.pop(src)
            if tgt > src:
                tgt -= 1
            self.terms.insert(max(0, min(len(self.terms), tgt)), item)
            self._render()

        def _remove(self, i):
            if 0 <= i < len(self.terms):
                self.terms.pop(i)
                self._render()

        def _toggle_op(self, i):
            if 0 <= i < len(self.terms):
                self.terms[i]["op"] = "-" if self.terms[i]["op"] == "+" else "+"
                self._render()

        def _cycle_coef(self, i):
            if not (0 <= i < len(self.terms)):
                return
            cur = self.terms[i]["coef"]
            try:
                k = list(self.COEF_CYCLE).index(cur)
            except ValueError:
                k = -1
            self.terms[i]["coef"] = self.COEF_CYCLE[(k + 1) % len(self.COEF_CYCLE)]
            self._render()

        def _clear(self):
            self.terms = []
            self.alias = {}
            self._render()

        def _preload(self):
            """把该对象已保存的表达式反解析回方块，方便接着改。

            只还原构建器自己能表示的形式（加减 + 系数）；遇到括号、除法等
            复杂结构就放弃预填，绝不猜出一个错的来。
            """
            if self.target_name is None:
                saved = (getattr(self.app, "global_expr", "") or "").strip()
                saved_alias = dict(getattr(self.app, "global_alias", {}) or {})
            else:
                d = self.app._find_by_name(self.target_name)
                if d is None:
                    return
                saved = (d.get("expr") or "").strip()
                saved_alias = dict(d.get("expr_alias") or {})
            if not saved:
                return
            self.alias = dict(saved_alias)
            parsed = terms_from_expression(saved, saved_alias)
            if not parsed:
                return
            self.terms = []
            for t in parsed:
                self.terms.append({"name": t["name"], "var": self._var_for(t["name"]),
                                   "coef": t["coef"], "op": t["op"]})

        def _apply(self):
            """把搭好的表达式保存到编辑对象上（每个文件各存一份）。"""
            if not self.terms:
                messagebox.showinfo("提示", "构建区还是空的，请先从左边拖入方块。",
                                    parent=self.win)
                return
            if self.target_name is None:
                self.app.global_expr = self.expr
                self.app.global_alias = dict(self.alias)
                msg = "已保存全局表达式：" + self.expr
            else:
                d = self.app._find_by_name(self.target_name)
                if d is None:
                    messagebox.showerror("错误", "目标物种已不存在，无法保存。",
                                         parent=self.win)
                    return
                d["expr"] = self.expr
                d["expr_alias"] = dict(self.alias)
                msg = f"已保存 {self.target_name} 的表达式：{self.expr}"
            # 主窗口若正编辑同一对象，把输入框同步成新表达式
            cur = self.app.expr_target.get()
            if cur == (self.target_name or GLOBAL_EXPR):
                self.app._load_expr_from_target()
            self.app._refresh_all()
            self.app.statusbar.config(text=msg)

        def _close(self):
            self._unbind_drag()
            self._kill_tip()
            try:
                self.win.destroy()
            except Exception:
                pass

        # ---------------- 渲染 ----------------
        def _render_pool(self):
            for c in self.pool_box.winfo_children():
                try:
                    c.destroy()
                except Exception:
                    pass
            self.pool_chips = []
            if not self.pool_names:
                tk.Label(self.pool_box, bg=COLORS["panel"], fg=COLORS["subtext"],
                         font=(self.app.FONT, 10), anchor="w", justify="left",
                         text="（暂无可用物种）\n请先添加 Log 文件并完成提取。"
                         ).grid(row=0, column=0, sticky="w", padx=12, pady=16)
                return
            cols = self._cols_pool or 1
            for i, n in enumerate(self.pool_names):
                chip = self._make_chip(self.pool_box, n, 1.0, "+", False, i)
                chip.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky="w")
                self.pool_chips.append(chip)

        def _render(self):
            for c in self.build_box.winfo_children():
                try:
                    c.destroy()
                except Exception:
                    pass
            self.build_chips = []
            if not self.terms:
                tk.Label(self.build_box, bg=COLORS["panel"], fg=COLORS["subtext"],
                         font=(self.app.FONT, 10), anchor="w", justify="left",
                         text="把左边的方块拖到这里\n\n"
                              "· 方块左侧 +/- 切换加减\n"
                              "· ×1 点击循环改系数（1 / 0.5 / 2 / 3 / 0.25）\n"
                              "· 拖动方块重排，拖回左边删除"
                         ).grid(row=0, column=0, sticky="w", padx=14, pady=18)
                self._update()
                return
            cols = self._cols_build or 1
            for i, t in enumerate(self.terms):
                chip = self._make_chip(self.build_box, t["name"], t["coef"],
                                       t["op"], True, i)
                chip.grid(row=i // cols, column=i % cols, padx=5, pady=5, sticky="w")
                self.build_chips.append(chip)
            self._update()

        def _make_chip(self, parent, name, coef, op, is_build, idx):
            """生成一个可拖动的小方块。"""
            bg = "#ffffff" if is_build else "#fbfaff"
            edge = COLORS["primary"] if is_build else COLORS["border"]
            f = tk.Frame(parent, bg=bg, highlightbackground=edge,
                         highlightthickness=2, cursor="fleur")
            inner = tk.Frame(f, bg=bg)
            inner.pack(padx=2, pady=2)
            skip = []
            if is_build:
                opb = tk.Label(inner, text=op, bg=COLORS["primary"], fg="white",
                               font=(self.app.MONO, 11, "bold"), padx=7, pady=3,
                               cursor="hand2")
                opb.bind("<Button-1>", lambda e, i=idx: self._toggle_op(i))
                opb.pack(side=tk.LEFT, padx=(2, 4))
                skip.append(opb)
                cb = tk.Label(inner, text="×%s" % format_coef(coef), bg="#eef2fb",
                              fg=COLORS["primary_d"], font=(self.app.FONT, 9, "bold"),
                              padx=5, pady=2, cursor="hand2")
                cb.bind("<Button-1>", lambda e, i=idx: self._cycle_coef(i))
                cb.pack(side=tk.LEFT, padx=2)
                skip.append(cb)
            nm = tk.Label(inner, text=name, bg=bg, fg=COLORS["text"],
                          font=(self.app.FONT, 10, "bold"), padx=5, pady=3)
            nm.pack(side=tk.LEFT, padx=2)
            if is_build:
                xb = tk.Label(inner, text="X", bg=COLORS["red"], fg="white",
                              font=(self.app.FONT, 8, "bold"), padx=6, pady=1,
                              cursor="hand2")
                xb.bind("<Button-1>", lambda e, i=idx: self._remove(i))
                xb.pack(side=tk.LEFT, padx=(6, 2))
                skip.append(xb)
            src = "build" if is_build else "pool"
            payload = idx if is_build else name
            self._bind_drag_all(inner, tuple(skip), src, payload, name)
            return f

        def _bind_drag_all(self, widget, skip, source, payload, label):
            """给方块本体及其子控件都绑上"按下即拖"。

            Tk 事件不会从子控件冒泡到父控件：点在方块里的文字标签上时，
            只有那个标签收到事件。所以必须逐个绑定，否则会出现"点方块
            空白处能拖、点到名字就拖不动"的怪现象。
            """
            def press(e, s=source, p=payload, l=label):
                self._start_drag(e, s, p, l)
            widget.bind("<ButtonPress-1>", press)
            for ch in widget.winfo_children():
                if ch in skip:
                    continue
                self._bind_drag_all(ch, skip, source, payload, label)

        # ---------------- 拖拽（窗口级监听） ----------------
        def _start_drag(self, event, source, payload, label):
            self.drag.update(active=True, source=source, payload=payload, name=label)
            self.drag["tip"] = self._make_tip(label)
            self._move_tip(event.x_root, event.y_root)
            self.win.bind_all("<B1-Motion>", self._on_motion)
            self.win.bind_all("<ButtonRelease-1>", self._on_release)

        def _on_motion(self, event):
            self._move_tip(event.x_root, event.y_root)

        def _on_release(self, event):
            self._unbind_drag()
            self._kill_tip()
            d = self.drag
            active, src, payload = d.get("active"), d.get("source"), d.get("payload")
            d.update(active=False, source=None, payload=None, tip=None, name="")
            if not active:
                return
            in_build = self._in_widget(self.build_canvas, event.x_root, event.y_root)
            in_pool = self._in_widget(self.pool_canvas, event.x_root, event.y_root)
            if src == "pool" and in_build:
                self._insert_term(payload, self._build_target_index(
                    event.x_root, event.y_root))
            elif src == "build":
                if in_pool:
                    self._remove(payload)
                elif in_build:
                    self._move_term(payload, self._build_target_index(
                        event.x_root, event.y_root))

        def _unbind_drag(self):
            try:
                self.win.unbind_all("<B1-Motion>")
                self.win.unbind_all("<ButtonRelease-1>")
            except Exception:
                pass

        def _make_tip(self, text):
            try:
                t = tk.Toplevel(self.win)
                t.overrideredirect(True)
                try:
                    t.attributes("-alpha", 0.92)
                except Exception:
                    pass
                tk.Label(t, text=text, bg=COLORS["primary_d"], fg="white",
                         font=(self.app.FONT, 10, "bold"), padx=10, pady=4).pack()
                t.update_idletasks()
                return t
            except Exception:
                return None

        def _move_tip(self, x, y):
            tip = self.drag.get("tip")
            if tip:
                try:
                    tip.geometry("+%d+%d" % (x + 14, y + 10))
                except Exception:
                    pass

        def _kill_tip(self):
            tip = self.drag.get("tip")
            if tip:
                try:
                    tip.destroy()
                except Exception:
                    pass
            self.drag["tip"] = None

        def _in_widget(self, w, x, y):
            try:
                rx, ry = w.winfo_rootx(), w.winfo_rooty()
                return (rx <= x <= rx + w.winfo_width()
                        and ry <= y <= ry + w.winfo_height())
            except Exception:
                return False

        def _build_target_index(self, x, y):
            """算出松手位置对应的插入下标。"""
            chips = self.build_chips
            if not chips:
                return 0
            for i, fr in enumerate(chips):
                try:
                    rx, ry = fr.winfo_rootx(), fr.winfo_rooty()
                    w = fr.winfo_width() or self.CHIP_W
                    h = fr.winfo_height() or 34
                except Exception:
                    continue
                if rx <= x <= rx + w and ry <= y <= ry + h:
                    return i + 1 if x > rx + w / 2.0 else i
            # 不在任何方块上：取中心距离最近的那个，按左右半边决定前后
            best, bd = len(chips), None
            for i, fr in enumerate(chips):
                try:
                    cx = fr.winfo_rootx() + (fr.winfo_width() or self.CHIP_W) / 2.0
                    cy = fr.winfo_rooty() + (fr.winfo_height() or 34) / 2.0
                except Exception:
                    continue
                d = (cx - x) ** 2 + (cy - y) ** 2
                if bd is None or d < bd:
                    bd, best = d, (i + 1 if x > cx else i)
            return best

        # ---------------- 结果 ----------------
        def _update(self):
            expr = expression_from_terms(
                [{"name": t["var"], "coef": t["coef"], "op": t["op"]}
                 for t in self.terms])
            self.expr = expr
            self.expr_text.set(expr or "（还没有拖入方块）")
            if not expr:
                self.result_text.set("—")
                return
            emap = dict(self.app._current_energy_map())
            for v, real in self.alias.items():
                if real in emap and v not in emap:
                    emap[v] = emap[real]
            try:
                val = EnergyExpressionEvaluator(emap).evaluate(expr)
                unit = self.app.unit.get()
                disp = val * (HARTREE_TO_KCAL if unit == "kcal/mol" else 1.0)
                self.result_text.set("%.4f %s" % (disp, unit))
            except Exception as e:
                self.result_text.set("无法计算：%s" % e)


    root = tk.Tk()
    app = LogExtractorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_application()
