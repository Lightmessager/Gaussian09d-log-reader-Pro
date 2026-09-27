# Gaussian LogReader Pro

**A desktop tool for batch-extracting thermodynamic data from Gaussian `.log` files, with relative-energy calculation and reaction-profile plotting.**

![Python](https://img.shields.io/badge/Python-3.9%20--%203.13-blue) ![GUI](https://img.shields.io/badge/GUI-Tkinter-orange) ![Status](https://img.shields.io/badge/Status-Active%20Development-green)

---

## Declaration

> This program was designed by me, and the code was written by **Tencent Hy4preview**.
>
> A dedicated **English version, shipped as a standalone `.exe`**, is planned for the future. The project is still being improved, and more features will arrive together with that English release.
>
> For now you can use it as-is, provided your computer already has **Python installed with `numpy` and `matplotlib`**.
>
> **To get started:** download the two files (`app.py` and `launcher.py`), then run **`launcher.py`** — it will help you set up the environment and choose which Python interpreter to use.

<details>
<summary><b>声明（中文）</b></summary>

> 本程序由我本人设计，代码由 **腾讯 Hy4preview** 编写。
>
> 未来会发布**独立的英文 `.exe` 版本**。项目仍在持续改进，更多功能将随英文版一同推出。
>
> 现在即可使用，前提是电脑上已安装 **Python，并带有 `numpy` 和 `matplotlib`**。
>
> **使用方法：** 下载两个文件（`app.py` 与 `launcher.py`），然后运行 **`launcher.py`**，它会帮你搭建环境并选择使用哪个 Python 解释器。

</details>

---

## Overview

Gaussian `.log` files contain a lot of text, but the numbers you actually need — SCF energy, thermal correction to Gibbs free energy, and the total free energy — are buried in it. Copying them one by one by hand is slow and error-prone.

This tool scans a batch of `.log` files at once, pulls out those three values, and then lets you:

- compute **relative energies** against any reference species you pick,
- build **arithmetic expressions** between species (by typing, or by dragging blocks),
- plot a **reaction-coordinate energy profile** and export it,
- save everything to **CSV**.

Everything runs locally in a Tkinter window — no server, no account, no network.

---

## Features

### Extraction
- Add individual files or an entire folder (recursively picks up `.log` files).
- Batch extraction with a progress bar and per-file status.
- Extracts three values per file:
  - **SCF energy** (`SCF Done: E(...) = ...`)
  - **Thermal correction to Gibbs Free Energy**
  - **Sum of electronic and thermal Free Energies** (total free energy)
- Unit conversion: **Hartree ⇄ kcal/mol** (factor `627.509474063`).

### Relative energy
- Pick any species as the **zero point**; all others are shown relative to it.
- Or type an **expression** directly, e.g. `TS1 - R`, `A - 0.5*B + 2*C`.

### Drag-and-drop expression builder
- A separate window with a **species palette** on the left and a **build area** on the right.
- Drag species blocks across like building with Lego bricks.
- Each block has a **+/− toggle**, a **coefficient** control (`1 / 0.5 / 2 / 3 / 0.25`), and a delete button.
- Drag existing blocks to **reorder** them; drag one back to the left panel to remove it.
- The generated expression and its live result are shown at the bottom.

### Per-file expressions (each file keeps its own)
- Choose **which species you are editing** from the *Edit target* dropdown.
- Every file can store **its own expression**, so each one gets its own final relative energy.
- Reopening the builder **restores the saved expression back into blocks** so you can keep editing.
- Files without a custom expression fall back to the classic `energy − zero point` behaviour.

### Reaction profile plot
- Rendered in the main window, or opened in a **larger standalone window**.
- Dense x-axis labels are automatically **thinned** (long names truncated, extra ticks reduced to numbers) so a 40-species profile stays readable.

### Custom order
- Drag rows to reorder species; this also sets the reaction-coordinate order used by the plot.

### Export
- Export the extraction table to CSV.
- Export relative-energy results to CSV (includes a *custom expression* column).
- Save the profile chart as PNG / PDF / SVG.

---

## Requirements

| Item | Notes |
|---|---|
| Python | 3.9 – 3.13 recommended |
| `tkinter` | Usually bundled with Python on Windows; if missing, reinstall Python and tick *"tcl/tk and IDLE"* |
| `numpy` | Installed automatically by the launcher if missing |
| `matplotlib` | Installed automatically by the launcher if missing (≥ 3.5) |

> The **launcher detects all of this for you** and can install the missing packages with one click. You do not need to set anything up by hand.

---

## Getting Started

1. **Download** `app.py` and `launcher.py` into the **same folder**.
2. **Run the launcher:**
   ```bash
   python launcher.py
   ```
   (Or double-click `launcher.py` on Windows.)
3. The launcher scans every Python interpreter on your machine and reports each one's dependency status:
   - `Available · dependencies ready` → ready to use
   - `Available · needs: matplotlib, numpy` → click **Install missing dependencies**
   - `Unavailable: missing tkinter` → reinstall that Python with *tcl/tk and IDLE* enabled
4. Select an interpreter and click **Launch**.

If the dependencies are already complete, you can also run the program directly:

```bash
python app.py
```

---

## Usage

### Basic panel
1. **Add files** / **Add folder** — load your `.log` files.
2. **▶ Start extraction** — parse them and fill the result table.
3. **Export table** — save the raw extracted values as CSV.

Tick **Advanced features** in the top-right to reveal two extra tabs.

### Tab: Energy calculation & profile
- **Energy type**: SCF energy / Gibbs thermal correction / total free energy.
- **Unit**: Hartree or kcal/mol.
- **Zero point**: the reference species; leave unset to show absolute values.
- **Edit target**: pick *Global* (one single result) or a specific file (that file's own expression).
- **Expression**: type it by hand, or click **Drag-to-build** to open the block builder.
- Buttons: *Refresh*, *Export relative-energy CSV*, *Save chart*, **Open chart in new window**, *Apply to all*.

### Tab: Custom order
- Drag rows to reorder species, then confirm. This order drives the profile plot's x-axis.

---

## Tips

- **Species names come from file names.** Names containing spaces or hyphens (e.g. `TS 1`, `int-2`) are converted into valid identifiers (`TS_1`, `int_2`) automatically, and the mapping is stored alongside the expression — so you never have to rename your files.
- **Expressions support** `+ - * /`, parentheses, and coefficients. Only the flat `A ± coef*B ± ...` form can be restored into blocks; anything more complex (division, nested parentheses) is left for manual editing rather than guessed at.
- **Best interpreter choice:** Python 3.13 is the safest pick. Python 3.14 is not yet fully supported by matplotlib on all builds.
- **First run in the launcher:** the log panel prints your Tk version and the detected UI font. If text ever shows as boxes, that line tells you exactly why.

---

## Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `AttributeError: 'Frame' object has no attribute 'winfo_descendants'` | Your Python ships Tcl/Tk 8.5. Already handled — the code now walks widgets with `winfo_children()` instead. |
| Chinese text shows as **boxes / tofu** | The requested font is not actually installed. The launcher probes real fonts via `actual("family")` and falls back automatically. |
| Launcher **status column shows `???`** | Caused by a subprocess writing GBK while the parent decodes UTF-8. Fixed — the probe now returns ASCII status codes and translates them in the parent process. |
| Chinese species names show as boxes **in the chart** | matplotlib's default font has no CJK glyphs. `Microsoft YaHei` / `SimHei` are now placed first in the font list. |
| `Unavailable: missing tkinter` | Reinstall that Python and tick **"tcl/tk and IDLE"** during installation. |
| Launcher lists a Python that fails with `probe failed` | Usually the Windows Store stub under `WindowsApps`. Harmless — just pick another interpreter. |

---

## Files

| File | Purpose |
|---|---|
| `launcher.py` | Environment wizard. Scans Python interpreters, checks/installs dependencies, then launches the app. |
| `app.py` | The main program: extraction, relative-energy calculation, expression builder, profile plot, CSV export. |

Both files must sit in the **same directory**.

---

## Roadmap

- [ ] **English version**, packaged as a standalone `.exe` (no Python required)
- [ ] More features shipping alongside the English release
- [ ] Continued stability and usability improvements

---

*Designed by the author · Code by Tencent Hy4preview · Last updated 2026-09-27*
