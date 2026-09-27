#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gaussian Log 热力学数据提取器 —— 智能启动器（launcher.py）
====================================================================
让 .py 文件在任何电脑上双击即可运行，无需预先配置环境。

运行流程（全程图形化，只依赖 Python 标准库）：
  1. 扫描本机所有 Python 解释器（py.exe 启动器、常见安装路径、PATH）。
  2. 逐个探测其 tkinter / matplotlib / numpy 状态。
  3. 弹出「环境选择器」窗口，用户点选一个解释器。
     - 依赖已齐 → 直接启动业务程序
     - 依赖缺失 → 点「安装缺失依赖」自动 pip 补齐，再启动
  4. 用 os.execv 把当前进程整体替换成选中的 Python，
     从而保证从一开始就是用户选定的解释器。
  5. 依赖齐备后加载 app.py 中的 LogExtractorApp 并启动。

配合 app.py 使用：把两个文件放在同一目录，双击 launcher.py 即可。
====================================================================
"""

import os
import sys
import json
import subprocess
from pathlib import Path


# ==================================================================
#                        解释器扫描与探测
# ==================================================================
def _which(name):
    """跨平台 which，返回可执行文件路径。"""
    try:
        from shutil import which as _w
        r = _w(name)
        if r:
            return r
    except ImportError:
        pass
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for ext in ("", ".exe", ".cmd", ".bat"):
            cand = os.path.join(p, name + ext)
            if os.path.isfile(cand):
                return cand
    return None


_PROBE_NAMES = {"tk": "tkinter", "mpl": "matplotlib", "np": "numpy"}

# 子进程只回传 ASCII 状态码，界面上的中文全部由父进程拼装。
#
# 这就是状态列乱码的真正原因（和字体无关）：探针脚本是在「子进程」里执行的，
# 它 print 出来的中文通过管道传回父进程。简体中文 Windows 上，Python 往管道
# 写东西用的是系统本地编码 GBK/cp936，而父进程按 UTF-8 解码，GBK 的中文字节
# 几乎都不是合法 UTF-8，于是被 errors="replace" 整段替换成 '?'。
# 表现就是：版本数字（纯 ASCII）正常，中文全变成问号。
#
# 让中文根本不经过子进程，是最彻底的解法：子进程只回 "no_tk"/"need_install"/
# "ready" 这类 ASCII 码，中文由父进程翻译。换字体解决不了这个问题。
_PROBE_SCRIPT = r'''
import json, sys
def chk(name):
    try:
        m = __import__(name)
        return getattr(m, "__version__", "?")
    except Exception:
        return None
mpl_ver = chk("matplotlib")
np_ver = chk("numpy")
info = {
    "exe": sys.executable,
    "version": sys.version.split()[0],
    "display": "Python " + sys.version.split()[0] + "  (" + sys.executable + ")",
    "tk": chk("tkinter"),
    "mpl": mpl_ver,
    "np": np_ver,
    "pip": chk("pip"),
    "error": None,
}
mpl_ok = True
if mpl_ver and mpl_ver != "?":
    try:
        from pkg_resources import parse_version
        if parse_version(mpl_ver) < parse_version("3.5"):
            mpl_ok = False
    except Exception:
        pass
info["mpl_ok"] = mpl_ok
missing = [n for n in ("tk", "mpl", "np") if not info.get(n)]
info["missing"] = missing
if not info.get("tk"):
    info["code"] = "no_tk"
    info["can_install"] = False
elif missing:
    info["code"] = "need_install"
    info["can_install"] = True
else:
    info["code"] = "ready"
    info["can_install"] = True
print(json.dumps(info, ensure_ascii=True))
'''


def _status_text(code, missing):
    """把子进程回传的状态码翻译成中文（在父进程里拼，编码完全可控）。"""
    if code == "no_tk":
        return "不可用：缺少 tkinter（请重装 Python 并勾选 tcl/tk and IDLE）"
    if code == "need_install":
        names = [_PROBE_NAMES.get(m, m) for m in (missing or [])]
        if names:
            return "可用 · 需安装：" + "、".join(names)
        return "可用 · 需安装依赖"
    if code == "ready":
        return "可用 · 依赖已就绪"
    return "状态未知"


def _child_env():
    """子进程环境：强制 stdout/stderr 用 UTF-8。

    状态码已是纯 ASCII，但 display 里的解释器路径仍可能含中文，
    这里再加一道保险，双保险确保管道里流的始终是 UTF-8。
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONUTF8", "1")
    return env


def _probe_python(python_exe):
    """探测某个解释器的能力与依赖状态。"""
    try:
        res = subprocess.run([python_exe, "-c", _PROBE_SCRIPT], capture_output=True,
                             text=True, timeout=60, encoding="utf-8",
                             errors="replace", env=_child_env())
    except (OSError, subprocess.SubprocessError) as e:
        return {"exe": python_exe, "version": "?", "display": python_exe,
                "status": f"无法启动：{e}", "can_install": False, "missing": [],
                "error": str(e)}
    out = (res.stdout or "").strip()
    if not out or res.returncode != 0:
        err = (res.stderr or "").strip().splitlines()
        return {"exe": python_exe, "version": "?", "display": python_exe,
                "status": "探测失败：" + (err[-1] if err else "执行失败"),
                "can_install": False, "missing": [], "error": err[-1] if err else "exec fail"}
    try:
        info = json.loads(out.splitlines()[-1])
    except Exception:
        return {"exe": python_exe, "version": "?", "display": python_exe,
                "status": "探测输出解析失败", "can_install": False, "missing": [],
                "error": "parse fail"}
    # 中文在这里拼装，不经过子进程，因此不受子进程编码影响
    if not info.get("status"):
        info["status"] = _status_text(info.get("code"), info.get("missing"))
    return info


def _scan_pythons():
    """扫描本机所有 Python 解释器，返回路径列表。"""
    found = {}

    # 方法1：py.exe 启动器（Windows 官方安装器会装）
    try:
        res = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace", env=_child_env())
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            parts = line.split(None, 1)
            if not parts:
                continue
            exe = parts[-1].strip()
            if exe and os.path.exists(exe) and exe.lower() not in found:
                found[exe.lower()] = exe
    except (OSError, subprocess.SubprocessError):
        pass

    # 方法2：常见安装路径
    candidates = set()
    env = os.environ
    search_bases = [env.get("LOCALAPPDATA"), env.get("APPDATA"), env.get("USERPROFILE"),
                    env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)")]
    search_subs = ("Programs\\Python", "Python")
    for base in search_bases:
        if not base:
            continue
        for sub in search_subs:
            candidates.add(os.path.join(base, sub))
    for var in ("ANACONDA", "CONDA_ROOT", "CONDA_PREFIX", "USERPROFILE"):
        v = env.get(var)
        if v:
            for name in ("anaconda3", "miniconda3", "Miniconda3", "miniforge3"):
                candidates.add(os.path.join(v, name))
    if env.get("LOCALAPPDATA"):
        candidates.add(os.path.join(env["LOCALAPPDATA"], "Microsoft", "WindowsApps"))

    for base in candidates:
        if not base or not os.path.isdir(base):
            continue
        try:
            for root, dirs, files in os.walk(base):
                depth = root[len(base):].count(os.sep)
                if depth > 2:
                    dirs[:] = []
                    continue
                for fn in files:
                    if fn.lower() in ("python.exe", "python3.exe", "pythonw.exe"):
                        full = os.path.join(root, fn)
                        if full.lower() not in found:
                            found[full.lower()] = full
                dirs[:] = [d for d in dirs if not d.startswith(".")]
        except OSError:
            continue

    # 方法3：PATH
    for name in ("python", "python3", "py"):
        exe = _which(name)
        if exe and os.path.exists(exe) and exe.lower() not in found:
            found[exe.lower()] = exe

    return list(found.values())


def _version_of(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace", env=_child_env())
        parts = (r.stdout + r.stderr).strip().split()
        return parts[-1] if parts else "0"
    except Exception:
        return "0"


def _dedupe(exes):
    """按版本号去重，同版本保留路径最短者。"""
    by_ver = {}
    for exe in exes:
        by_ver.setdefault(_version_of(exe), []).append(exe)
    out = [group[0] for group in by_ver.values()]
    out.sort(key=lambda p: [int(x) for x in _version_of(p).split(".") if x.isdigit()] or [0])
    return out


# ==================================================================
#                        环境选择 / 安装窗口
# ==================================================================
class EnvironmentChooser:
    def _detect_font(self):
        """探测系统里真实可用的中文字体（三级回退）。

        只查 tkfont.families() 并不可靠：Tk 遇到不存在的字体会静默回退到
        别的字体，名字在列表里 != 实际生效。这里对候选真正建一个 Font 对象，
        用 actual("family") 回读"实际生效字体"，只有一致才算命中 —— 这正是
        界面出现方块（tofu）的典型成因。

        三级回退：
          1. 严格匹配（请求名 == 实际生效名）
          2. 在字体表里模糊找中文字体（YaHei / Hei / Song / 黑 / 宋 ...）
          3. Tk 默认字体
        """
        try:
            import tkinter.font as tkfont
            avail = list(tkfont.families())
            aset = set(avail)
            cands = ("微软雅黑", "Microsoft YaHei", "Microsoft YaHei UI",
                     "SimHei", "SimSun", "NSimSun", "DengXian",
                     "FangSong", "KaiTi", "Segoe UI")
            # 第 1 级：严格匹配（请求名必须与实际生效名一致）
            for cand in cands:
                if cand not in aset:
                    continue
                try:
                    f = tkfont.Font(family=cand, size=10)
                    actual = (f.actual("family") or "").strip()
                except Exception:
                    actual = ""
                if actual and actual.replace(" ", "").lower() == cand.replace(" ", "").lower():
                    return cand
            # 第 2 级：字体表中模糊找中文字体
            keys = ("yahei", "simhei", "simsun", "nsimsun", "dengxian",
                    "fangsong", "kaiti", "黑", "宋", "楷", "仿")
            for name in avail:
                low = name.lower()
                if any((k in low) or (k in name) for k in keys):
                    return name
        except Exception:
            pass
        return "TkDefaultFont"

    def _detect_mono(self):
        """探测等宽字体，用于安装日志框。"""
        try:
            import tkinter.font as tkfont
            avail = set(tkfont.families())
            for cand in ("Consolas", "Lucida Console", "DejaVu Sans Mono",
                         "Courier New", "TkFixedFont"):
                if cand in avail:
                    return cand
        except Exception:
            pass
        return "TkFixedFont"

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk, messagebox, filedialog
        self.tk = tk
        self.ttk = ttk
        self.messagebox = messagebox
        self.filedialog = filedialog

        self.root = tk.Tk()
        # 字体探测必须在 Tk() 之后（tkfont.families() 需要 root 已创建），
        # 且必须在 _build_ui() 之前（build 时就要用到 self.FONT / self.MONO）
        self.FONT = self._detect_font()
        self.MONO = self._detect_mono()
        self.root.title("Gaussian 提取器 · 环境选择（首次运行向导）")
        self.root.geometry("780x580")
        self.root.minsize(680, 520)
        self.root.configure(bg="#f4f6fb")

        self._build_ui()
        # 诊断信息：若仍有方块，请把这两行内容告知，可据此精确定位
        try:
            self._log(f"Tk 版本 {self.tk.TkVersion} / Tcl {self.tk.TclVersion}\n")
            self._log(f"界面字体: {self.FONT}   日志字体: {self.MONO}\n")
            if self.FONT in ("TkDefaultFont", "TkTextFont"):
                self._log("警告: 未探测到中文字体，界面可能出现方块字形。\n")
        except Exception:
            pass
        self.root.after(100, self._start_scan)

    def _setup_styles(self):
        """给 ttk 控件套用探测到的中文字体。

        这是状态列乱码的真正原因：tk.Label 可以直接指定 font，但 ttk 的
        Treeview / Treeview.Heading / Button 走的是样式表里的默认字体，
        系统缺对应字形时「可用 · 依赖已就绪」这类中文就会被画成方块。
        不配置样式的话，只改 tk.Label 的字体是没用的。
        """
        try:
            st = self.ttk.Style()
            try:
                st.theme_use("clam")
            except Exception:
                pass
            f = self.FONT
            st.configure("TLabel", font=(f, 10))
            st.configure("TButton", font=(f, 10))
            st.configure("TEntry", font=(f, 10))
            st.configure("TCombobox", font=(f, 10))
            st.configure("Treeview", font=(f, 9), rowheight=26)
            st.configure("Treeview.Heading", font=(f, 10, "bold"))
            st.configure("TLabelframe.Label", font=(f, 10, "bold"))
            st.configure("TNotebook.Tab", font=(f, 10, "bold"))
            st.configure("Vertical.TScrollbar", background="#dfe3ee")
        except Exception:
            pass

    def _build_ui(self):
        tk = self.tk
        ttk = self.ttk
        self._setup_styles()

        top = tk.Frame(self.root, bg="#3a0ca3", height=78)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="选择运行环境", bg="#3a0ca3", fg="white",
                 font=(self.FONT, 16, "bold")).pack(anchor="w", padx=20, pady=14)
        tk.Label(top, text="程序需要 Python + tkinter + matplotlib + numpy，选一个环境，缺什么它会自动装",
                 bg="#3a0ca3", fg="#cdd7ff", font=(self.FONT, 9)).place(x=20, y=46)

        body = tk.Frame(self.root, bg="#f4f6fb")
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        bar = tk.Frame(body, bg="#f4f6fb")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.status = tk.Label(bar, text="正在扫描本机 Python 环境…",
                               bg="#f4f6fb", fg="#6c757d", font=(self.FONT, 9))
        self.status.pack(side=tk.LEFT)
        ttk.Button(bar, text="重新扫描", command=self._start_scan,
                   style="Ghost.TButton").pack(side=tk.RIGHT)

        list_card = tk.Frame(body, bg="white", highlightbackground="#dfe3ee",
                            highlightthickness=1)
        list_card.grid(row=1, column=0, sticky="nsew")
        list_card.rowconfigure(0, weight=1)
        list_card.columnconfigure(0, weight=1)

        cols = ("版本", "状态", "解释器路径")
        self.tree = ttk.Treeview(list_card, columns=cols, show="headings", height=10,
                                selectmode="browse")
        widths = {"版本": 110, "状态": 250, "解释器路径": 440}
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.tag_configure("ok", background="#e6fff0")
        self.tree.tag_configure("need", background="#fffbe6")
        self.tree.tag_configure("bad", background="#ffeaea")
        self.tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._on_launch(only_if_ready=True))

        vsb = ttk.Scrollbar(list_card, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)

        btn = tk.Frame(body, bg="#f4f6fb")
        btn.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.launch_btn = tk.Button(btn, text="启动程序", font=(self.FONT, 11, "bold"),
                                    bg="#4361ee", fg="white", padx=22, pady=6, relief="flat",
                                    state="disabled", command=self._on_launch)
        self.launch_btn.pack(side=tk.LEFT, padx=3)
        self.install_btn = tk.Button(btn, text="为选中环境安装缺失依赖",
                                     font=(self.FONT, 10, "bold"), bg="#06d6a0", fg="#073b4c",
                                     padx=16, pady=6, relief="flat", state="disabled",
                                     command=self._on_install)
        self.install_btn.pack(side=tk.LEFT, padx=3)
        self.custom_btn = tk.Button(btn, text="手动指定 python.exe",
                                    font=(self.FONT, 9), bg="#f4f6fb", fg="#6c757d",
                                    padx=10, pady=6, relief="flat", command=self._on_custom_path)
        self.custom_btn.pack(side=tk.RIGHT, padx=3)

        log_card = tk.Frame(body, bg="white", highlightbackground="#dfe3ee",
                           highlightthickness=1)
        log_card.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        log_card.rowconfigure(1, weight=1)
        log_card.columnconfigure(0, weight=1)
        tk.Label(log_card, text="安装日志", bg="white", fg="#2b2d42",
                 font=(self.FONT, 10, "bold")).grid(row=0, column=0, sticky="w",
                                                     padx=10, pady=6)
        self.log = tk.Text(log_card, height=8, font=(self.MONO, 9), bg="#0c1226",
                           fg="#39ff14", relief="flat", state="disabled")
        self.log.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.infos = {}
        self.selected = None

    # ---------------- 扫描 ----------------
    def _start_scan(self):
        self.status.config(text="正在扫描本机 Python 环境…（可能需要几秒）")
        self.install_btn.config(state="disabled")
        self.launch_btn.config(state="disabled")
        self.tree.delete(*self.tree.get_children())
        self._log("扫描本机 Python 解释器…\n")
        import threading
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        exes = _dedupe(_scan_pythons())
        if not exes:
            self.root.after(0, lambda: self._scan_done([]))
            return
        self.root.after(0, lambda: self._log(f"找到 {len(exes)} 个解释器，逐个探测依赖…\n"))
        infos = []
        for exe in exes:
            info = _probe_python(exe)
            infos.append(info)
            icon = "[OK]" if (info.get("tk") and info.get("mpl") and info.get("np")) else \
                   ("[X]" if info.get("error") else "[!]")
            self.root.after(0, lambda i=info, ic=icon: self._log(
                f"  {ic} Python {i.get('version','?')}  {i.get('status','')}\n"))
        self.root.after(0, lambda: self._scan_done(infos))

    def _scan_done(self, infos):
        self.infos.clear()
        for info in infos:
            if info.get("error"):
                tag = "bad"
            elif info.get("missing"):
                tag = "need"
            else:
                tag = "ok"
            iid = self.tree.insert("", "end", values=(
                "Python " + info.get("version", "?"),
                info.get("status", ""), info.get("exe", "")), tags=(tag,))
            self.infos[iid] = info
        if not infos:
            self._log("\n未找到任何 Python 解释器。\n"
                      "请先到 https://www.python.org/downloads/ 下载安装 Python 3.9~3.13，\n"
                      "安装时务必勾选「Add Python to PATH」和「tcl/tk and IDLE」。\n")
            self.status.config(text="未找到 Python —— 请先安装 Python 3.9~3.13")
            return
        for iid in self.tree.get_children():
            if self.infos[iid].get("tk"):
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                break
        self.status.config(text=f"扫描完成，共 {len(infos)} 个 Python 解释器")

    # ---------------- 选择 ----------------
    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            self.selected = None
            self.launch_btn.config(state="disabled")
            self.install_btn.config(state="disabled")
            return
        info = self.infos[sel[0]]
        self.selected = info.get("exe")
        if info.get("error"):
            self.launch_btn.config(state="disabled")
            self.install_btn.config(state="disabled")
        else:
            self.launch_btn.config(state="normal")
            self.install_btn.config(state="normal")

    # ---------------- 启动 ----------------
    def _on_launch(self, only_if_ready=False):
        sel = self.tree.selection()
        if not sel:
            return
        info = self.infos[sel[0]]
        if info.get("missing") and only_if_ready:
            self._log(f"\n{info['exe']} 还缺依赖，请先点「安装缺失依赖」。\n")
            return
        if info.get("error"):
            self.messagebox.showerror("无法启动", info["error"])
            return
        self._launch_with(info["exe"])

    def _launch_with(self, python_exe):
        """用选中的 Python 重启本脚本，进程整体替换。"""
        script = os.path.abspath(__file__)
        env = os.environ.copy()
        env["GAUSSIAN_LAUNCHER_PYTHON"] = python_exe
        env["GAUSSIAN_LAUNCHER_MODE"] = "run"
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("PYTHONUTF8", "1")
        self._log(f"\n正在以 {python_exe} 重启程序…\n")
        try:
            os.execve(python_exe, [python_exe, script], env)
        except OSError as e:
            self.messagebox.showerror(
                "启动失败", f"无法用以下解释器启动：\n{python_exe}\n\n错误：{e}")
            self._log(f"启动失败：{e}\n")

    # ---------------- 安装依赖 ----------------
    def _on_install(self):
        sel = self.tree.selection()
        if not sel:
            return
        info = self.infos[sel[0]]
        exe = info["exe"]

        if not info.get("tk"):
            self.messagebox.showerror(
                "无法修复：缺少 tkinter",
                "该 Python 没有 tkinter，pip 装不了。\n\n修复方法（二选一）：\n"
                "1. 换用列表里其他 Python 3.9~3.13 的环境；\n"
                "2. 对当前 Python 执行「修改 / Modify」安装，\n"
                "   勾选 tcl/tk and IDLE 组件后重试。")
            return

        pkgs = []
        if not info.get("pip"):
            pkgs.append("pip")
        if not info.get("mpl"):
            pkgs.append("matplotlib")
        if not info.get("np"):
            pkgs.append("numpy")
        if not pkgs:
            self._log("\n依赖已齐全，无需安装。\n")
            return

        self._log(f"\n准备为 {exe} 安装：{', '.join(pkgs)}\n")
        self.install_btn.config(state="disabled")
        self.launch_btn.config(state="disabled")
        import threading
        threading.Thread(target=self._do_install, args=(exe, pkgs), daemon=True).start()

    def _do_install(self, exe, pkgs):
        self._pip_run(exe, ["install", "--upgrade", "pip"], "升级 pip")
        candidates = [
            ("已配置源", None),
            ("清华镜像", "https://pypi.tuna.tsinghua.edu.cn/simple"),
            ("官方 PyPI", "https://pypi.org/simple"),
        ]
        for label, url in candidates:
            self._log(f"  尝试 {label} …\n")
            ok, _ = self._pip_run(exe, self._pip_cmd(pkgs, url), f"安装依赖({label})")
            if ok:
                self._log(f"  [OK] {label} 安装成功\n")
                break
            self._log("  [X] 失败，查看末尾报错\n")
        else:
            self._log("\n[X] 全部源都安装失败。常见原因：\n"
                      "  1. 没联网（可浏览器打开 pypi.org 验证）\n"
                      "  2. 公司/校园内网需要代理或自定义镜像源\n"
                      "  3. 当前用户无写入权限（可尝试管理员身份运行）\n请手动执行：\n"
                      f"  \"{exe}\" -m pip install matplotlib numpy\n")
            self.root.after(0, lambda: self.install_btn.config(state="normal"))
            return

        self._log("\n重新探测该环境…\n")
        new_info = _probe_python(exe)
        self.root.after(0, lambda: self._refresh_after_install(exe, new_info))

    def _refresh_after_install(self, exe, new_info):
        sel = self.tree.selection()
        old_iid = sel[0] if sel else None
        idx = self.tree.index(old_iid) if old_iid else "end"
        if old_iid:
            self.tree.delete(old_iid)
        tag = "ok" if (new_info.get("tk") and new_info.get("mpl") and new_info.get("np")) else \
              ("need" if new_info.get("missing") else "bad")
        iid = self.tree.insert("", idx, values=(
            "Python " + new_info.get("version", "?"),
            new_info.get("status", ""), new_info.get("exe", "")), tags=(tag,))
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self._on_select()
        self.install_btn.config(state="normal")
        if new_info.get("missing"):
            self._log(f"仍有缺失：{', '.join(new_info['missing'])}，可重试或换源。\n")
        else:
            self._log("[OK] 所有依赖已就绪！点击「启动程序」即可运行。\n")

    def _pip_cmd(self, pkgs, index_url=None):
        cmd = ["install", "--upgrade"]
        if index_url:
            cmd += ["--index-url", index_url]
        cmd += ["--disable-pip-version-check", "--no-input"] + pkgs
        return cmd

    def _pip_run(self, exe, args, label):
        full = [exe, "-m", "pip"] + args
        try:
            proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", bufsize=1, env=_child_env())
        except OSError as e:
            # Python 3 在 except 块结束时会 del e，lambda 延迟执行时 e 已不存在
            # 会抛 NameError。用默认参数把值"固化"进闭包。
            msg = str(e)
            self.root.after(0, lambda msg=msg: self._log(f"[{label}] 启动失败：{msg}\n"))
            return False, msg
        buf = []
        assert proc.stdout is not None
        for line in proc.stdout:
            buf.append(line)
            self.root.after(0, lambda l=line: self._log(l if l.endswith("\n") else l + "\n"))
        proc.wait()
        ok = proc.returncode == 0
        if not ok:
            self.root.after(0, lambda: self._log(f"[{label}] 返回码 {proc.returncode}\n"))
        return ok, "".join(buf)

    # ---------------- 手动指定 ----------------
    def _on_custom_path(self):
        path = self.filedialog.askopenfilename(
            title="选择 python.exe", filetypes=[("Python 解释器", "python.exe"),
                                               ("所有文件", "*.*")])
        if not path or not os.path.exists(path):
            return
        self._log(f"\n探测 {path} …\n")
        info = _probe_python(path)
        iid = self.tree.insert("", "end", values=(
            "Python " + info.get("version", "?"),
            info.get("status", "手动指定"), path),
            tags=("ok" if not info.get("missing") else "need",))
        self.infos[iid] = info
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self._on_select()
        self._log(f"已添加：{path}\n")

    # ---------------- 日志 ----------------
    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self):
        self.root.mainloop()


# ==================================================================
#                              主入口
# ==================================================================
def _ensure_tkinter():
    """tkinter 缺失时给出可操作的修复提示，而不是一闪崩溃。"""
    try:
        import tkinter  # noqa: F401
        return True
    except Exception as e:
        msg = ("当前 Python 没有 tkinter 组件，无法运行本程序。\n\n"
               "这是 Windows 版 Python 安装时未勾选「tcl/tk and IDLE」导致的。\n\n"
               "修复方法：\n"
               "  1. 打开「设置 -> 应用 -> 已安装的应用」\n"
               "  2. 找到当前 Python，选择「修改 / Modify」\n"
               "  3. 勾选「tcl/tk and IDLE」，点下一步完成\n"
               "  4. 重新双击本程序\n\n"
               "错误详情：" + str(e))
        try:
            import ctypes
            if sys.platform.startswith("win"):
                ctypes.windll.user32.MessageBoxW(
                    0, msg, "Gaussian 提取器 · 启动失败", 0x10)
            else:
                print("tkinter 缺失：" + str(e))
        except Exception:
            print("tkinter 缺失：" + str(e))
        return False


if __name__ == "__main__":
    if not _ensure_tkinter():
        sys.exit(1)

    if os.environ.get("GAUSSIAN_LAUNCHER_MODE") == "run":
        # 依赖齐备，交给 app.py 启动业务程序
        app_path = Path(__file__).parent / "app.py"
        if not app_path.exists():
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("文件缺失", f"未找到业务程序文件：\n{app_path}\n\n"
                                 "请确保 launcher.py 与 app.py 放在同一目录。")
            sys.exit(1)
        # 用 importlib 加载，避免路径问题
        import importlib.util
        spec = importlib.util.spec_from_file_location("gauss_app", str(app_path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run_application()
    else:
        chooser = EnvironmentChooser()
        chooser.run()
