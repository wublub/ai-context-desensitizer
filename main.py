# -*- coding: utf-8 -*-
from __future__ import annotations

import ctypes
from ctypes import wintypes
import html
import os
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import ttk

from desensitizer import (
    build_keyword_regex,
    desensitize,
    load_json,
    make_mapping_payload,
    normalize_keywords,
    restore,
    save_json,
)


APP_NAME = "AI脱敏工具"
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
CF_HTML_NAME = "HTML Format"


def get_app_data_dir() -> Path:

    # PyInstaller 等打包场景下，sys.executable 指向 exe 路径
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).resolve().parent
    else:
        base_dir = Path(__file__).resolve().parent

    return base_dir


def _strip_token_brackets(name_or_token: str) -> str:
    """如果用户输入了 [名称]，则提取内部名称；否则返回去两端空白后的文本。"""
    s = (name_or_token or "").strip()
    if s.startswith("[") and s.endswith("]") and len(s) >= 4:
        return s[2:-2].strip()
    return s


def markdown_to_word_html(text: str) -> str:
    """把常见 Markdown 转成适合粘贴到 Word 的 HTML 片段（不含 <html>/<body> 外壳）。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts: list[str] = []
    list_tag: str | None = None

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            parts.append(f"</{list_tag}>")
            list_tag = None

    def open_list(tag: str) -> None:
        nonlocal list_tag
        if list_tag == tag:
            return
        close_list()
        parts.append(f"<{tag}>")
        list_tag = tag

    def render_inline(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"__(.+?)__", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
        escaped = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<em>\1</em>", escaped)
        escaped = re.sub(
            r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
            r'<a href="\2">\1</a>',
            escaped,
        )
        return escaped

    def split_table_row(value: str) -> list[str]:
        s = (value or "").strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]

        cells: list[str] = []
        cur: list[str] = []
        escape = False
        for ch in s:
            if escape:
                cur.append(ch)
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == "|":
                cells.append("".join(cur).strip())
                cur = []
                continue
            cur.append(ch)
        cells.append("".join(cur).strip())
        return cells

    def parse_table_sep(value: str) -> list[str] | None:
        s = (value or "").strip()
        if not s:
            return None
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c.strip() for c in s.split("|")]
        if len(cells) < 2:
            return None
        aligns: list[str] = []
        for c in cells:
            if not re.match(r"^:?-{3,}:?$", c):
                return None
            if c.startswith(":") and c.endswith(":"):
                aligns.append("center")
            elif c.endswith(":"):
                aligns.append("right")
            else:
                aligns.append("left")
        return aligns

    def build_table(header_cells: list[str], aligns: list[str], body_rows: list[list[str]]) -> None:
        col_count = max(len(header_cells), len(aligns))
        if col_count < 2:
            return

        def style_cell(*, is_header: bool, align: str) -> str:
            base = "border:1px solid #999;padding:4px;vertical-align:top;"
            bg = "background:#f3f3f3;" if is_header else ""
            return base + bg + f"text-align:{align};"

        parts.append('<table border="1" cellspacing="0" cellpadding="4" style="border-collapse:collapse;">')
        parts.append("<thead><tr>")
        for i in range(col_count):
            cell = header_cells[i] if i < len(header_cells) else ""
            align = aligns[i] if i < len(aligns) else "left"
            parts.append(f'<th style="{style_cell(is_header=True, align=align)}">{render_inline(cell)}</th>')
        parts.append("</tr></thead>")

        parts.append("<tbody>")
        for row in body_rows:
            parts.append("<tr>")
            for i in range(col_count):
                cell = row[i] if i < len(row) else ""
                align = aligns[i] if i < len(aligns) else "left"
                parts.append(f'<td style="{style_cell(is_header=False, align=align)}">{render_inline(cell)}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table>")

    i = 0
    while i < len(lines):
        line = (lines[i] or "").rstrip()
        stripped = line.strip()

        # 表格（GFM）：
        # | A | B |
        # |---|---|
        # | 1 | 2 |
        if stripped and i + 1 < len(lines) and "|" in stripped:
            aligns = parse_table_sep(lines[i + 1])
            if aligns is not None:
                header_cells = split_table_row(stripped)
                if len(header_cells) >= 2:
                    close_list()
                    rows: list[list[str]] = []
                    j = i + 2
                    while j < len(lines):
                        row_line = (lines[j] or "").rstrip()
                        row_stripped = row_line.strip()
                        if not row_stripped:
                            break
                        if "|" not in row_stripped:
                            break
                        if parse_table_sep(row_stripped) is not None:
                            break
                        rows.append(split_table_row(row_stripped))
                        j += 1

                    build_table(header_cells, aligns, rows)
                    i = j
                    continue

        if not stripped:
            close_list()
            i += 1
            continue

        # 水平分隔线：---、***、___ （至少 3 个连续字符）
        if re.match(r"^[-*_]{3,}$", stripped):
            close_list()
            parts.append('<hr style="border:none;border-top:1px solid #999;margin:12px 0;">')
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{render_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        # 引用块 blockquote（支持多行连续 >）
        if stripped.startswith(">"):
            close_list()
            bq_lines: list[str] = []
            while i < len(lines):
                cur = (lines[i] or "").strip()
                if cur.startswith(">"):
                    content = cur[1:].lstrip()
                    bq_lines.append(render_inline(content) if content else "<br>")
                    i += 1
                else:
                    break
            parts.append(
                '<blockquote style="border-left:3px solid #ccc;margin:8px 0;padding:4px 12px;color:#555;">'
                + "<br>".join(bq_lines)
                + "</blockquote>"
            )
            continue

        # checkbox 列表：- [ ] 或 - [x]
        checkbox = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", stripped)
        if checkbox:
            open_list("ul")
            checked = checkbox.group(1).lower() == "x"
            symbol = "&#9745;" if checked else "&#9744;"
            parts.append(f"<li style=\"list-style:none;\">{symbol} {render_inline(checkbox.group(2).strip())}</li>")
            i += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            open_list("ul")
            parts.append(f"<li>{render_inline(bullet.group(1).strip())}</li>")
            i += 1
            continue

        numbered = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if numbered:
            open_list("ol")
            parts.append(f"<li>{render_inline(numbered.group(1).strip())}</li>")
            i += 1
            continue

        close_list()
        parts.append(f"<p>{render_inline(stripped)}</p>")
        i += 1

    close_list()

    if not parts:
        return ""

    return "\n".join(parts)


def html_to_preview_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []

    def is_table_sep_line(value: str) -> bool:
        aligns = re.sub(r"\s+", "", value or "")
        if not aligns or "|" not in aligns:
            return False
        s = aligns.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        cells = [c for c in s.split("|")]
        if len(cells) < 2:
            return False
        return all(re.match(r"^:?-{3,}:?$", c) for c in cells)

    def split_row(value: str) -> list[str]:
        s = (value or "").strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    i = 0
    while i < len(lines):
        raw = lines[i] or ""
        stripped = raw.strip()

        # 表格：转成制表符分隔，便于 Word 直接粘贴为表格
        if stripped and "|" in stripped and i + 1 < len(lines) and is_table_sep_line(lines[i + 1]):
            header = split_row(stripped)
            if len(header) >= 2:
                out.append("\t".join(header))
                j = i + 2
                while j < len(lines):
                    row_line = (lines[j] or "").strip()
                    if not row_line:
                        break
                    if "|" not in row_line:
                        break
                    if is_table_sep_line(row_line):
                        break
                    row = split_row(row_line)
                    out.append("\t".join(row))
                    j += 1
                out.append("")
                i = j
                continue

        if not stripped:
            out.append("")
            i += 1
            continue

        # 水平分隔线
        if re.match(r"^[-*_]{3,}$", stripped):
            out.append("————————————————")
            out.append("")
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            out.append(heading.group(2).strip())
            out.append("")
            i += 1
            continue

        # 引用块
        if stripped.startswith(">"):
            while i < len(lines):
                cur = (lines[i] or "").strip()
                if cur.startswith(">"):
                    content = cur[1:].lstrip()
                    plain_bq = re.sub(r"\*\*(.+?)\*\*", r"\1", content)
                    plain_bq = re.sub(r"__(.+?)__", r"\1", plain_bq)
                    plain_bq = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", plain_bq)
                    plain_bq = re.sub(r"`([^`]+)`", r"\1", plain_bq)
                    out.append(f"  {plain_bq}" if plain_bq else "")
                    i += 1
                else:
                    break
            continue

        # checkbox 列表
        checkbox = re.match(r"^[-*+]\s+\[([ xX])\]\s+(.*)$", stripped)
        if checkbox:
            checked = checkbox.group(1).lower() == "x"
            symbol = "☑" if checked else "☐"
            out.append(f"{symbol} {checkbox.group(2).strip()}")
            i += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        if bullet:
            out.append(f"• {bullet.group(1).strip()}")
            i += 1
            continue

        numbered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if numbered:
            out.append(f"{numbered.group(1)}. {numbered.group(2).strip()}")
            i += 1
            continue

        plain = stripped
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", plain)
        plain = re.sub(r"__(.+?)__", r"\1", plain)
        plain = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", plain)
        plain = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", plain)
        plain = re.sub(r"`([^`]+)`", r"\1", plain)
        plain = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1（\2）", plain)
        out.append(plain)
        i += 1

    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def build_cf_html(html_fragment: str) -> bytes:
    fragment = html_fragment.replace("\r\n", "\n").replace("\r", "\n")
    style = "font-family:Calibri,'Microsoft YaHei',sans-serif;font-size:11pt;line-height:1.6;"
    prefix = f"<html><body style=\"{style}\"><!--StartFragment-->"
    suffix = "<!--EndFragment--></body></html>"
    full_html = prefix + fragment + suffix
    template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    dummy = template.format(start_html=0, end_html=0, start_fragment=0, end_fragment=0)
    start_html = len(dummy.encode("utf-8"))
    start_fragment = start_html + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    end_html = start_html + len(full_html.encode("utf-8"))
    header = template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    )
    return (header + full_html).encode("utf-8")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1240x800")
        self.root.minsize(1040, 680)

        self.root.bind_all("<Key>", self._on_any_key_for_easter)
        self.root.bind_all("<Control-f>", self._on_find_slot_shortcut, add=True)

        self.app_dir = get_app_data_dir()

        # json 文件保存在当前文件夹（脚本/EXE 所在目录）
        self.mapping_path = self.app_dir / "latest_mapping.json"

        # 新版槽位（名称/关键词绑定）
        self.slots_path = self.app_dir / "slots.json"

        # 兼容：旧版规则文件（用于迁移）
        self.legacy_rules_path = self.app_dir / "rules.json"

        self.shortcuts_path = self.app_dir / "shortcuts.json"

        self.ignore_case_var = tk.BooleanVar(value=False)
        # “标黄全部关键词位置（原文+脱敏后）”
        self.highlight_all_var = tk.BooleanVar(value=False)

        self.shortcut_cfg: dict = {
            "pick": "<Control-c>",
            "highlight_all": "<Control-Alt-h>",
        }
        self._bound_shortcuts: list[str] = []

        # 槽位：每个槽位 1 个名称（可改名） + 1 个关键词（通过快捷键绑定）
        self.slots: list[dict] = []
        self._selected_slot_index: int | None = None

        self._after_desensitize: str | None = None
        self._after_restore: str | None = None
        self._after_highlight: str | None = None
        self._programmatic = False

        self._send_out_plain_text = ""
        self._send_out_html = markdown_to_word_html("")
        self._restore_out_plain_text = ""
        self._restore_out_html = markdown_to_word_html("")
        self._tree_edit_entry: ttk.Entry | None = None
        self._tree_edit_index: int | None = None

        self._easter_buffer = ""

        self.latest_mapping: dict = {"token_to_keyword": {}, "keyword_to_token": {}, "keyword_to_label": {}}

        self._build_ui()
        self._load_startup_state()
        self._bind_shortcuts()
        self._refresh_shortcut_ui()
        self._refresh_slots_tree(select_index=0 if self.slots else None)
        self._schedule_all_updates()

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.left = ttk.Frame(self.root, padding=10)
        self.left.grid(row=0, column=0, sticky="nsw")
        self.left.columnconfigure(0, weight=1)
        self.left.rowconfigure(1, weight=1)

        self._j_label = ttk.Label(self.left, text="")
        self._j_label.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

        header = ttk.Frame(self.left)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="名称/关键词（点选=联动标黄）").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="设置", command=self.open_settings).grid(row=0, column=1, padx=(0, 6))
        ttk.Button(header, text="关于", command=self.show_about).grid(row=0, column=2)

        # 槽位表
        cols = ("name", "token", "keyword")
        self.slot_tree = ttk.Treeview(self.left, columns=cols, show="headings", selectmode="browse", height=18)
        self.slot_tree.heading("name", text="名称")
        self.slot_tree.heading("token", text="占位符")
        self.slot_tree.heading("keyword", text="关键词")
        self.slot_tree.column("name", width=110, anchor="w")
        self.slot_tree.column("token", width=120, anchor="w")
        self.slot_tree.column("keyword", width=260, anchor="w")

        slot_vs = ttk.Scrollbar(self.left, orient="vertical", command=self.slot_tree.yview)
        self.slot_tree.configure(yscrollcommand=slot_vs.set)

        self.slot_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        slot_vs.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        self.slot_tree.bind("<<TreeviewSelect>>", self._on_slot_tree_select)
        self.slot_tree.bind("<Delete>", self._on_slot_tree_delete_key)
        self.slot_tree.bind("<Double-1>", self._on_slot_tree_double_click)

        # 编辑区（关键词预览）
        edit = ttk.Frame(self.left, padding=(0, 10, 0, 0))
        edit.grid(row=2, column=0, columnspan=2, sticky="ew")
        edit.columnconfigure(1, weight=1)

        self.slot_name_var = tk.StringVar(value="")
        self.slot_keyword_var = tk.StringVar(value="")

        ttk.Label(edit, text="名称：双击左侧关键词改名").grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(edit, text="关键词：").grid(row=1, column=0, sticky="w", pady=(6, 0))
        kw_preview = ttk.Entry(edit, textvariable=self.slot_keyword_var)
        kw_preview.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        kw_preview.configure(state="readonly")

        # 操作按钮
        btns = ttk.Frame(self.left, padding=(0, 8, 0, 0))
        btns.grid(row=3, column=0, columnspan=2, sticky="ew")
        btns.columnconfigure(0, weight=1)

        self.bind_btn = ttk.Button(btns, text="选中文字后按快捷键命名", command=self.bind_selection_to_slot)
        self.bind_btn.grid(row=0, column=0, sticky="ew")

        self.find_btn = ttk.Button(btns, text="定位名称并修改/删除（Ctrl+F）", command=self._locate_slot_for_edit_or_delete)
        self.find_btn.grid(row=1, column=0, sticky="ew", pady=(8, 0))


        # 选项/高亮
        opts = ttk.Frame(self.left, padding=(0, 10, 0, 0))
        opts.grid(row=4, column=0, columnspan=2, sticky="ew")
        opts.columnconfigure(0, weight=1)

        ttk.Checkbutton(
            opts,
            text="忽略大小写",
            variable=self.ignore_case_var,
            command=self._schedule_all_updates,
        ).grid(row=0, column=0, sticky="w")

        self.highlight_btn = ttk.Button(
            opts,
            text="切换标黄全部",
            command=self.toggle_highlight_all,
        )
        self.highlight_btn.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self.highlight_state_label = ttk.Label(opts, text="当前标黄：只标黄选中")
        self.highlight_state_label.grid(row=2, column=0, sticky="w", pady=(6, 0))

        self.hint = ttk.Label(
            self.left,
            text="未来的AI们你们好！",
            wraplength=520,
            justify="left",
        )
        self.hint.grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 0))

        # 右侧主区
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        self.nb = ttk.Notebook(main)
        self.nb.grid(row=0, column=0, sticky="nsew")

        self.tab_send = ttk.Frame(self.nb, padding=10)
        self.tab_restore = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_send, text="发送前（脱敏）")
        self.nb.add(self.tab_restore, text="收到后（还原）")

        self._build_send_tab()
        self._build_restore_tab()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _make_text_with_scroll(self, parent, *, readonly: bool = False) -> tuple[tk.Text, ttk.Scrollbar]:
        txt = tk.Text(parent, wrap="word", undo=True)
        scroll = ttk.Scrollbar(parent, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        if readonly:
            txt.configure(state="disabled")
        return txt, scroll

    def _build_send_tab(self) -> None:
        t = self.tab_send
        t.rowconfigure(1, weight=1)
        t.rowconfigure(3, weight=1)
        t.columnconfigure(0, weight=1)

        top_bar = ttk.Frame(t)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.columnconfigure(0, weight=1)
        ttk.Label(top_bar, text="原文（支持粘贴 Markdown）").grid(row=0, column=0, sticky="w")
        ttk.Button(top_bar, text="粘贴", command=lambda: self.paste_into(self.send_in_text)).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(top_bar, text="清空", command=lambda: self.set_text(self.send_in_text, "")).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(top_bar, text="脱敏并复制", command=self.desensitize_and_copy).grid(
            row=0, column=3, padx=(12, 0)
        )

        self.send_in_text, self.send_in_scroll = self._make_text_with_scroll(t)
        self.send_in_text.grid(row=1, column=0, sticky="nsew", pady=(6, 10))
        self.send_in_scroll.grid(row=1, column=1, sticky="ns", pady=(6, 10))
        self.send_in_text.tag_configure("kw", background="#FFF59D")
        self.send_in_text.bind("<<Copy>>", self._on_send_in_ctrl_c)
        self.send_in_text.bind("<Control-c>", self._on_send_in_ctrl_c)

        bottom_bar = ttk.Frame(t)
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.columnconfigure(0, weight=1)
        ttk.Label(bottom_bar, text="脱敏后（自动转为便于粘贴 Word 的格式）").grid(row=0, column=0, sticky="w")
        ttk.Button(bottom_bar, text="复制", command=lambda: self.copy_result("send")).grid(
            row=0, column=1, padx=(6, 0)
        )

        self.send_out_text, self.send_out_scroll = self._make_text_with_scroll(t, readonly=True)
        self.send_out_text.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.send_out_scroll.grid(row=3, column=1, sticky="ns", pady=(6, 0))
        self.send_out_text.tag_configure("kw", background="#FFF59D")
        self.send_out_text.bind("<<Copy>>", self._on_send_out_ctrl_c)
        self.send_out_text.bind("<Control-c>", self._on_send_out_ctrl_c)

        self.send_status = ttk.Label(t, text="替换次数：0 | 已自动转换为 Word 友好格式")
        self.send_status.grid(row=4, column=0, sticky="w", pady=(8, 0))

        self.send_in_text.bind("<<Modified>>", self._on_send_in_modified)

    def _build_restore_tab(self) -> None:
        t = self.tab_restore
        t.rowconfigure(1, weight=1)
        t.rowconfigure(3, weight=1)
        t.columnconfigure(0, weight=1)

        top_bar = ttk.Frame(t)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.columnconfigure(0, weight=1)
        ttk.Label(top_bar, text="AI返回（支持粘贴 Markdown）").grid(row=0, column=0, sticky="w")
        ttk.Button(top_bar, text="粘贴", command=lambda: self.paste_into(self.restore_in_text)).grid(
            row=0, column=1, padx=(6, 0)
        )
        ttk.Button(top_bar, text="清空", command=lambda: self.set_text(self.restore_in_text, "")).grid(
            row=0, column=2, padx=(6, 0)
        )
        ttk.Button(top_bar, text="还原并复制", command=self.restore_and_copy).grid(
            row=0, column=3, padx=(12, 0)
        )

        self.restore_in_text, self.restore_in_scroll = self._make_text_with_scroll(t)
        self.restore_in_text.grid(row=1, column=0, sticky="nsew", pady=(6, 10))
        self.restore_in_scroll.grid(row=1, column=1, sticky="ns", pady=(6, 10))
        self.restore_in_text.tag_configure("kw", background="#FFF59D")
        self.restore_in_text.bind("<<Copy>>", self._on_restore_in_ctrl_c)
        self.restore_in_text.bind("<Control-c>", self._on_restore_in_ctrl_c)

        bottom_bar = ttk.Frame(t)
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.columnconfigure(0, weight=1)
        ttk.Label(bottom_bar, text="还原后（自动转为便于粘贴 Word 的格式）").grid(row=0, column=0, sticky="w")
        ttk.Button(bottom_bar, text="复制", command=lambda: self.copy_result("restore")).grid(
            row=0, column=1, padx=(6, 0)
        )

        self.restore_out_text, self.restore_out_scroll = self._make_text_with_scroll(t, readonly=True)
        self.restore_out_text.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.restore_out_scroll.grid(row=3, column=1, sticky="ns", pady=(6, 0))
        self.restore_out_text.tag_configure("kw", background="#FFF59D")
        self.restore_out_text.bind("<<Copy>>", self._on_restore_out_ctrl_c)
        self.restore_out_text.bind("<Control-c>", self._on_restore_out_ctrl_c)

        self.restore_status = ttk.Label(t, text="还原次数：0 | 已自动转换为 Word 友好格式")
        self.restore_status.grid(row=4, column=0, sticky="w", pady=(8, 0))

        self.restore_in_text.bind("<<Modified>>", self._on_restore_in_modified)

    # ---------------- 槽位：增删改/绑定 ----------------

    def _token_for_name(self, name: str) -> str:
        n = (name or "").strip()
        return f"[{n}]" if n else ""

    def _next_default_name(self) -> str:
        used = set(str(s.get("name", "")).strip() for s in self.slots)
        n = 1
        while True:
            cand = f"名称{n}"
            if cand not in used:
                return cand
            n += 1

    def _ensure_default_slots_if_empty(self) -> None:
        if self.slots:
            return
        self.slots = [
        ]

    def _refresh_slots_tree(self, *, select_index: int | None) -> None:
        # 记录当前选择
        for iid in self.slot_tree.get_children():
            self.slot_tree.delete(iid)

        for i, s in enumerate(self.slots):
            name = str(s.get("name", "")).strip()
            kw = str(s.get("keyword", "")).strip()
            tok = self._token_for_name(name)
            self.slot_tree.insert("", "end", iid=str(i), values=(name, tok, kw))

        if select_index is not None and 0 <= select_index < len(self.slots):
            try:
                self.slot_tree.selection_set(str(select_index))
                self.slot_tree.focus(str(select_index))
                self.slot_tree.see(str(select_index))
            except Exception:
                pass
            self._selected_slot_index = select_index
        else:
            self._selected_slot_index = None

        self._sync_slot_editor_from_selection()

    def _get_selected_slot_index(self) -> int | None:
        sel = self.slot_tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _sync_slot_editor_from_selection(self) -> None:
        idx = self._get_selected_slot_index()
        if idx is None or not (0 <= idx < len(self.slots)):
            self.slot_name_var.set("")
            self.slot_keyword_var.set("")
            return
        s = self.slots[idx]
        self.slot_name_var.set(str(s.get("name", "")).strip())
        self.slot_keyword_var.set(str(s.get("keyword", "")).strip())

    def _set_slot_name(self, idx: int, raw_name: str, *, show_message: bool = True) -> bool:
        if idx is None or not (0 <= idx < len(self.slots)):
            if show_message:
                messagebox.showinfo(APP_NAME, "请先在左侧列表选中一个名称。")
            return False

        name = _strip_token_brackets(raw_name)
        if not name:
            if show_message:
                messagebox.showinfo(APP_NAME, "名称不能为空。")
            return False

        for j, s in enumerate(self.slots):
            if j == idx:
                continue
            if str(s.get("name", "")).strip() == name:
                if show_message:
                    messagebox.showinfo(APP_NAME, "名称已存在，请换一个名称（名称必须唯一）。")
                return False

        self.slots[idx]["name"] = name
        self._save_slots()
        self._refresh_slots_tree(select_index=idx)
        self._schedule_all_updates()
        return True

    def _destroy_tree_editor(self) -> None:
        if self._tree_edit_entry is not None:
            try:
                self._tree_edit_entry.destroy()
            except Exception:
                pass
        self._tree_edit_entry = None
        self._tree_edit_index = None

    def _commit_tree_editor(self, *, show_message: bool = False) -> None:
        if self._tree_edit_entry is None or self._tree_edit_index is None:
            return
        value = self._tree_edit_entry.get()
        idx = self._tree_edit_index
        if self._set_slot_name(idx, value, show_message=show_message):
            self._destroy_tree_editor()
            return
        try:
            self._tree_edit_entry.focus_set()
            self._tree_edit_entry.selection_range(0, "end")
        except Exception:
            pass

    def _begin_tree_rename(self, idx: int) -> None:
        if not (0 <= idx < len(self.slots)):
            return
        self._destroy_tree_editor()
        bbox = self.slot_tree.bbox(str(idx), "#1")
        if not bbox:
            return
        x, y, width, height = bbox
        entry = ttk.Entry(self.slot_tree)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, str(self.slots[idx].get("name", "")).strip())
        entry.select_range(0, "end")
        entry.focus_set()
        entry.bind("<Return>", lambda _e: self._commit_tree_editor(show_message=True))
        entry.bind("<Escape>", lambda _e: self._destroy_tree_editor())
        entry.bind("<FocusOut>", lambda _e: self._commit_tree_editor(show_message=False))
        self._tree_edit_entry = entry
        self._tree_edit_index = idx

    def _on_slot_tree_double_click(self, event) -> str:
        row_id = self.slot_tree.identify_row(event.y)
        if not row_id:
            return "break"
        try:
            idx = int(row_id)
        except Exception:
            return "break"
        self._refresh_slots_tree(select_index=idx)
        self._begin_tree_rename(idx)
        return "break"

    def _on_slot_tree_select(self, _evt=None) -> None:
        idx = self._get_selected_slot_index()
        self._selected_slot_index = idx
        # 点击某条关键词：默认切回“只标黄选中”，保证点击有可见效果
        if idx is not None:
            self.highlight_all_var.set(False)
        self._sync_slot_editor_from_selection()
        self.schedule_highlight_update()

    def add_slot(self) -> None:
        name = self._next_default_name()
        self.slots.append({"name": name, "keyword": ""})
        self._save_slots()
        self._refresh_slots_tree(select_index=len(self.slots) - 1)
        self._schedule_all_updates()

    def delete_selected_slot(self) -> None:
        idx = self._get_selected_slot_index()
        if idx is None or not (0 <= idx < len(self.slots)):
            return

        self.slots.pop(idx)
        self._save_slots()

        new_idx = None
        if self.slots:
            new_idx = min(idx, len(self.slots) - 1)
        self._refresh_slots_tree(select_index=new_idx)
        self._schedule_all_updates()

    def _on_slot_tree_delete_key(self, _evt=None):
        idx = self._get_selected_slot_index()
        if idx is None or not (0 <= idx < len(self.slots)):
            return "break"

        s = self.slots[idx]
        name = str(s.get("name", "")).strip()
        kw = str(s.get("keyword", "")).strip()
        if not messagebox.askyesno(APP_NAME, f"确定删除该项吗？\n\n名称：{name}\n关键词：{kw}"):
            return "break"

        self.delete_selected_slot()
        return "break"

    def rename_selected_slot(self) -> None:
        idx = self._get_selected_slot_index()
        raw = self.slot_name_var.get()
        self._set_slot_name(idx, raw, show_message=True)

    def _first_empty_slot_index(self) -> int | None:
        for i, s in enumerate(self.slots):
            if not str(s.get("keyword", "")).strip():
                return i
        return None

    def _find_slot_index_by_keyword(self, keyword: str) -> int | None:
        kw = (keyword or "").strip()
        if not kw:
            return None
        for i, s in enumerate(self.slots):
            if str(s.get("keyword", "")).strip() == kw:
                return i
        return None

    def _find_slot_index_by_name(self, name: str) -> int | None:
        target = (name or "").strip()
        if not target:
            return None
        for i, s in enumerate(self.slots):
            if str(s.get("name", "")).strip() == target:
                return i
        return None

    def _focus_slot_by_index(self, idx: int, *, begin_rename: bool = False) -> None:
        if not (0 <= idx < len(self.slots)):
            return
        self._refresh_slots_tree(select_index=idx)
        self.highlight_all_var.set(False)
        self.schedule_highlight_update()
        try:
            self.slot_tree.focus_set()
        except Exception:
            pass
        if begin_rename:
            self._begin_tree_rename(idx)

    def _prompt_find_slot_name(self) -> str | None:
        initial = self.slot_name_var.get().strip()
        return simpledialog.askstring(
            APP_NAME,
            "请输入要定位的名称：",
            initialvalue=initial,
            parent=self.root,
        )

    def _locate_slot_for_edit_or_delete(self) -> bool:
        raw_name = self._prompt_find_slot_name()
        if raw_name is None:
            return True
        name = _strip_token_brackets(raw_name)
        if not name:
            messagebox.showinfo(APP_NAME, "请输入要定位的名称。")
            return True
        idx = self._find_slot_index_by_name(name)
        if idx is None:
            messagebox.showinfo(APP_NAME, f"未找到名称：{name}")
            return True
        self._focus_slot_by_index(idx, begin_rename=True)
        return True

    def _on_find_slot_shortcut(self, _evt=None):
        w = self.root.focus_get()
        if w in (self.send_in_text, self.restore_in_text):
            return None
        self._locate_slot_for_edit_or_delete()
        return "break"

    def _get_selected_text(self) -> str:
        try:
            return self.send_in_text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def bind_selection_to_slot(self, _evt=None) -> None:
        kw = self._get_selected_text().strip()
        if not kw:
            messagebox.showinfo(APP_NAME, "请先在【发送前（脱敏）】原文里用鼠标选中要脱敏的文本。")
            return

        # 不允许把占位符本身当关键词
        if kw.startswith("[") and kw.endswith("]"):
            messagebox.showinfo(APP_NAME, "选中的内容看起来像占位符，请选中原始敏感内容。")
            return

        # 关键词已存在：定位到对应行（避免重复关键词导致映射混乱）
        exists = self._find_slot_index_by_keyword(kw)
        if exists is not None:
            self._refresh_slots_tree(select_index=exists)
            self.highlight_all_var.set(False)
            self.schedule_highlight_update()
            return

        default_name = kw

        raw_name = simpledialog.askstring(
            APP_NAME,
            "请输入名称（用于占位符 [名称]，例如：公司1/药物名1）：",
            initialvalue=default_name,
            parent=self.root,
        )
        if raw_name is None:
            return

        name = _strip_token_brackets(raw_name)
        if not name:
            messagebox.showinfo(APP_NAME, "名称不能为空。")
            return

        # 用名称定位槽位；没有则优先复用空槽，否则新增一行
        idx: int | None = None
        for i, s in enumerate(self.slots):
            if str(s.get("name", "")).strip() == name:
                idx = i
                break

        if idx is None:
            empty = self._first_empty_slot_index()
            if empty is None:
                self.slots.append({"name": name, "keyword": ""})
                idx = len(self.slots) - 1
            else:
                self.slots[empty]["name"] = name
                idx = empty

        # 若目标槽已有关键词，提示是否覆盖
        cur_kw = str(self.slots[idx].get("keyword", "")).strip()
        if cur_kw and cur_kw != kw:
            if not messagebox.askyesno(
                APP_NAME,
                f"该名称已绑定过关键词，是否覆盖？\n\n名称：{name}\n原关键词：{cur_kw}\n新关键词：{kw}",
            ):
                return

        self.slots[idx]["keyword"] = kw
        self._save_slots()
        self._refresh_slots_tree(select_index=idx)
        self.highlight_all_var.set(False)
        self._schedule_all_updates()

    # ---------------- 快捷键：加载/保存/绑定 ----------------

    def _format_shortcut_for_button(self, seq: str) -> str:
        if not isinstance(seq, str) or not seq:
            return ""
        s = seq
        s = s.replace("<Control-", "Ctrl+")
        s = s.replace("<Alt-", "Alt+")
        s = s.replace("<Shift-", "Shift+")
        s = s.replace(">", "")
        if len(s) >= 1 and s[-1].isalpha():
            s = s[:-1] + s[-1].upper()
        return s

    def _refresh_shortcut_ui(self) -> None:
        try:
            pick = self._format_shortcut_for_button(self.shortcut_cfg.get("pick", ""))
            hl = self._format_shortcut_for_button(self.shortcut_cfg.get("highlight_all", ""))
            self.bind_btn.configure(text=f"选中文字后按快捷键命名（{pick or '未设置'}）")
            self.find_btn.configure(text="定位名称并修改/删除（Ctrl+F）")
            self.highlight_btn.configure(text=f"切换标黄全部（{hl or '未设置'}）")
        except Exception:
            pass

    def _load_shortcuts(self) -> None:
        payload = load_json(self.shortcuts_path, default={})
        if not isinstance(payload, dict) or not isinstance(payload.get("shortcuts"), dict):
            return
        sc = payload.get("shortcuts")

        v = sc.get("pick") or sc.get("company") or sc.get("drug") or sc.get("patent")
        if isinstance(v, str) and v.strip():
            self.shortcut_cfg["pick"] = v.strip()

        v2 = sc.get("highlight_all") or sc.get("highlight")
        if isinstance(v2, str) and v2.strip():
            self.shortcut_cfg["highlight_all"] = v2.strip()

    def _save_shortcuts(self) -> None:
        save_json(self.shortcuts_path, {"version": 1, "shortcuts": self.shortcut_cfg})

    def _bind_shortcuts(self) -> None:
        # 先加载配置
        self._load_shortcuts()

        # 解绑旧的（避免重复绑定）
        for seq in list(self._bound_shortcuts):
            try:
                self.root.unbind_all(seq)
            except tk.TclError:
                pass
        self._bound_shortcuts = []

        def bind_if_valid(seq: str, func):
            if not isinstance(seq, str) or not seq.strip():
                return
            try:
                self.root.bind_all(seq, func)
                self._bound_shortcuts.append(seq)
            except tk.TclError:
                pass

        bind_if_valid(self.shortcut_cfg.get("pick", ""), lambda e: self.bind_selection_to_slot(e))
        bind_if_valid(self.shortcut_cfg.get("highlight_all", ""), lambda e: self.toggle_highlight_all(e))

        self._save_shortcuts()

    def _parse_shortcut(self, user_input: str) -> str:
        s = (user_input or "").strip()
        if not s:
            return ""

        # 兼容用户输入：Ctrl+c / ctrl c / <Control-c>
        if s.startswith("<") and s.endswith(">"):
            return s

        u = s.upper().replace(" ", "")
        # 允许用 - 或 + 分隔
        u = u.replace("-", "+")

        parts = [p for p in u.split("+") if p]
        key = parts[-1] if parts else ""
        mods = parts[:-1]

        mod_map = {
            "CTRL": "Control",
            "CONTROL": "Control",
            "ALT": "Alt",
            "SHIFT": "Shift",
        }

        out = "<"
        for m in mods:
            mm = mod_map.get(m)
            if mm:
                out += f"{mm}-"
        if not key:
            return ""
        out += key.lower() + ">"
        return out

    def open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="命名快捷键：").grid(row=0, column=0, sticky="w")
        pick_var = tk.StringVar(value=self._format_shortcut_for_button(self.shortcut_cfg.get("pick", "")))
        pick_entry = ttk.Entry(frm, textvariable=pick_var, width=28)
        pick_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        ttk.Label(frm, text="标黄全部快捷键：").grid(row=1, column=0, sticky="w", pady=(10, 0))
        hl_var = tk.StringVar(
            value=self._format_shortcut_for_button(self.shortcut_cfg.get("highlight_all", ""))
        )
        hl_entry = ttk.Entry(frm, textvariable=hl_var, width=28)
        hl_entry.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(10, 0))

        tip = ttk.Label(frm, text="输入示例：Ctrl+C / Ctrl+Alt+H", foreground="#666")
        tip.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))

        def on_save():
            pick_seq = self._parse_shortcut(pick_var.get())
            hl_seq = self._parse_shortcut(hl_var.get())
            if not pick_seq or not hl_seq:
                messagebox.showinfo(APP_NAME, "快捷键格式不正确，请按示例输入。")
                return
            self.shortcut_cfg["pick"] = pick_seq
            self.shortcut_cfg["highlight_all"] = hl_seq
            # 先落盘，再重新绑定（避免 _bind_shortcuts() 读取旧配置覆盖内存值）
            self._save_shortcuts()
            self._bind_shortcuts()
            self._refresh_shortcut_ui()
            win.destroy()

        ttk.Button(btns, text="保存", command=on_save).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="取消", command=win.destroy).grid(row=0, column=1)

        try:
            pick_entry.focus_set()
        except Exception:
            pass

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于",
            "AI脱敏工具\n\n致谢：大模型 gpt5.2、gpt5.4\n致谢：产品经理 wublub",
        )

    def _on_any_key_for_easter(self, event):
        ch = getattr(event, "char", "") or ""
        if not ch:
            return
        if not ch.isprintable():
            return

        self._easter_buffer = (self._easter_buffer + ch)[-16:]
        if "KLCB" in self._easter_buffer.upper():
            try:
                self._j_label.configure(text="J")
            except Exception:
                pass


    def toggle_highlight_all(self, _evt=None) -> None:
        self.highlight_all_var.set(not bool(self.highlight_all_var.get()))
        state = "标黄全部" if self.highlight_all_var.get() else "只标黄选中"
        self.highlight_state_label.configure(text=f"当前标黄：{state}")
        self.schedule_highlight_update()

    # ---------------- 文件持久化：slots/mapping ----------------

    def _save_slots(self) -> None:
        save_json(self.slots_path, {"version": 1, "slots": self.slots})

    def _load_slots(self) -> None:
        payload = load_json(self.slots_path, default={})
        if isinstance(payload, dict) and isinstance(payload.get("slots"), list):
            cleaned = []
            for x in payload.get("slots"):
                if not isinstance(x, dict):
                    continue
                name = str(x.get("name", "")).strip()
                kw = str(x.get("keyword", "")).strip()
                if not name:
                    continue
                cleaned.append({"name": _strip_token_brackets(name), "keyword": kw})
            self.slots = cleaned
            self._ensure_default_slots_if_empty()
            return

        # 尝试从旧版 rules.json 迁移
        legacy = load_json(self.legacy_rules_path, default={})
        if isinstance(legacy, dict) and isinstance(legacy.get("rules"), list):
            used_names: set[str] = set()
            slots: list[dict] = []
            for r in legacy.get("rules"):
                if not isinstance(r, dict):
                    continue
                kw = str(r.get("keyword", "")).strip()
                tok = str(r.get("token", "")).strip()
                if not kw or not tok:
                    continue
                name = _strip_token_brackets(tok) or self._next_default_name()
                base = name
                suffix = 2
                while name in used_names:
                    name = f"{base}_{suffix}"
                    suffix += 1
                used_names.add(name)
                slots.append({"name": name, "keyword": kw})

            if slots:
                self.slots = slots
                self._save_slots()
                self._ensure_default_slots_if_empty()
                return

        self._ensure_default_slots_if_empty()
        self._save_slots()

    def _load_latest_mapping(self) -> None:
        mapping_payload = load_json(self.mapping_path, default={})
        if isinstance(mapping_payload, dict) and mapping_payload.get("token_to_keyword"):
            self.latest_mapping = mapping_payload

    def _load_startup_state(self) -> None:
        self._load_slots()
        self._load_latest_mapping()
        state = "标黄全部" if self.highlight_all_var.get() else "只标黄选中"
        self.highlight_state_label.configure(text=f"当前标黄：{state}")

    # ---------------- 事件/调度 ----------------

    def _copy_text_selection_or_all(self, widget: tk.Text) -> None:
        self.root.clipboard_clear()
        try:
            data = widget.get("sel.first", "sel.last")
        except tk.TclError:
            data = widget.get("1.0", "end-1c")
        self.root.clipboard_append(data)
        self.root.update()

    def _on_send_in_ctrl_c(self, _evt=None):
        self.bind_selection_to_slot(_evt)
        return "break"

    def _on_restore_in_ctrl_c(self, _evt=None):
        self._copy_text_selection_or_all(self.restore_in_text)
        return "break"

    def _on_send_out_ctrl_c(self, _evt=None):
        self.copy_result("send")
        return "break"

    def _on_restore_out_ctrl_c(self, _evt=None):
        self.copy_result("restore")
        return "break"

    def _on_any_ctrl_c_copy(self, _evt=None):
        w = self.root.focus_get()
        if w is self.send_out_text:
            return self._on_send_out_ctrl_c(_evt)
        if w is self.restore_out_text:
            return self._on_restore_out_ctrl_c(_evt)
        if w is self.send_in_text:
            return self._on_send_in_ctrl_c(_evt)
        if w is self.restore_in_text:
            return self._on_restore_in_ctrl_c(_evt)
        return None

    def _on_send_in_modified(self, _event) -> None:
        if self._programmatic:
            self.send_in_text.edit_modified(False)
            return
        if not self.send_in_text.edit_modified():
            return
        self.send_in_text.edit_modified(False)
        self.schedule_desensitize_update()
        self.schedule_highlight_update()

    def _on_restore_in_modified(self, _event) -> None:
        if self._programmatic:
            self.restore_in_text.edit_modified(False)
            return
        if not self.restore_in_text.edit_modified():
            return
        self.restore_in_text.edit_modified(False)
        self.schedule_restore_update()

    def schedule_desensitize_update(self) -> None:
        if self._after_desensitize is not None:
            self.root.after_cancel(self._after_desensitize)
        self._after_desensitize = self.root.after(220, self.update_desensitize)

    def schedule_restore_update(self) -> None:
        if self._after_restore is not None:
            self.root.after_cancel(self._after_restore)
        self._after_restore = self.root.after(220, self.update_restore)

    def schedule_highlight_update(self) -> None:
        if self._after_highlight is not None:
            self.root.after_cancel(self._after_highlight)
        self._after_highlight = self.root.after(80, self.update_highlights)

    def _schedule_all_updates(self) -> None:
        self.schedule_desensitize_update()
        self.schedule_restore_update()
        self.schedule_highlight_update()

    # ---------------- 核心功能：脱敏/还原 ----------------

    def _collect_keywords_and_overrides(self) -> tuple[list[str], dict[str, str]]:
        kws: list[str] = []
        override: dict[str, str] = {}
        for s in self.slots:
            name = str(s.get("name", "")).strip()
            kw = str(s.get("keyword", "")).strip()
            if not name or not kw:
                continue
            tok = self._token_for_name(name)
            kws.append(kw)
            override[kw] = tok

        kws = normalize_keywords(kws)
        return kws, override

    def _get_text_preview(self, text: str) -> str:
        preview = html_to_preview_text(text)
        return preview if preview else text

    def _to_word_html(self, text: str) -> str:
        fragment = markdown_to_word_html(text)
        if fragment:
            return fragment
        return f"<p>{html.escape(text or '')}</p>" if text else ""

    def _set_output_content(self, widget: tk.Text, plain_text: str, html_content: str) -> None:
        preview = self._get_text_preview(plain_text)
        self.set_readonly_text(widget, preview)
        if widget is self.send_out_text:
            self._send_out_plain_text = plain_text
            self._send_out_html = html_content
        elif widget is self.restore_out_text:
            self._restore_out_plain_text = plain_text
            self._restore_out_html = html_content

    def update_desensitize(self) -> None:
        self._after_desensitize = None

        text = self.send_in_text.get("1.0", "end-1c")
        ignore_case = bool(self.ignore_case_var.get())

        kws, kw_to_tok_override = self._collect_keywords_and_overrides()

        res = desensitize(
            text,
            kws,
            ignore_case=ignore_case,
            keyword_to_token_override=kw_to_tok_override,
        )

        self.latest_mapping = make_mapping_payload(res.token_to_keyword, res.keyword_to_token)
        save_json(self.mapping_path, self.latest_mapping)

        html_output = self._to_word_html(res.output_text)
        self._set_output_content(self.send_out_text, res.output_text, html_output)
        self.send_status.configure(text=f"替换次数：{res.replacement_count} | 映射已保存到：{self.mapping_path} | 已转 Word 格式")

        self.update_highlights()

    def _get_token_mapping_for_restore(self) -> dict[str, str]:
        if isinstance(self.latest_mapping, dict) and self.latest_mapping.get("token_to_keyword"):
            tok_to_kw = self.latest_mapping.get("token_to_keyword")
            if isinstance(tok_to_kw, dict):
                return tok_to_kw

        payload = load_json(self.mapping_path, default={})
        if isinstance(payload, dict) and isinstance(payload.get("token_to_keyword"), dict):
            self.latest_mapping = payload
            return payload.get("token_to_keyword")

        return {}

    def update_restore(self) -> None:
        self._after_restore = None

        text = self.restore_in_text.get("1.0", "end-1c")
        tok_to_kw = self._get_token_mapping_for_restore()

        out, count = restore(text, tok_to_kw)
        html_output = self._to_word_html(out)
        self._set_output_content(self.restore_out_text, out, html_output)

        mapping_state = "已加载上次映射" if tok_to_kw else "未找到映射（请先在脱敏页替换一次）"
        self.restore_status.configure(text=f"还原次数：{count} | {mapping_state} | 已转 Word 格式")

        # 还原页也跟随“标黄全部/只标黄选中”刷新高亮
        self.schedule_highlight_update()

    # ---------------- 高亮 ----------------

    def highlight_keywords(self, widget: tk.Text, kws: list[str], *, ignore_case: bool) -> None:
        """在指定 Text 里把 kws（关键词或 token 列表）标黄。"""
        widget.tag_remove("kw", "1.0", "end")
        if not kws:
            return
        content = widget.get("1.0", "end-1c")
        if not content:
            return

        # 防卡顿保护：文本或关键词特别大时，跳过高亮
        if len(content) > 300_000 or len(kws) > 2_000:
            return

        rx = build_keyword_regex(kws, ignore_case=ignore_case)
        if rx is None:
            return

        for m in rx.finditer(content):
            start = f"1.0+{m.start()}c"
            end = f"1.0+{m.end()}c"
            widget.tag_add("kw", start, end)

    def update_highlights(self) -> None:
        """根据“标黄全部/选中行”刷新两侧高亮。"""
        self._after_highlight = None

        ignore_case = bool(self.ignore_case_var.get())

        # 先清空
        self.send_in_text.tag_remove("kw", "1.0", "end")
        self.send_out_text.tag_remove("kw", "1.0", "end")
        self.restore_in_text.tag_remove("kw", "1.0", "end")
        self.restore_out_text.tag_remove("kw", "1.0", "end")

        kws, override = self._collect_keywords_and_overrides()

        if self.highlight_all_var.get():
            # 发送前（原文/脱敏后）
            self.highlight_keywords(self.send_in_text, kws, ignore_case=ignore_case)
            tokens = [override.get(k, "") for k in kws]
            tokens = [t for t in tokens if t]
            self.highlight_keywords(self.send_out_text, tokens, ignore_case=False)

            # 收到后（AI返回/还原后）：
            # - AI返回：标黄 token
            # - 还原后：标黄 keyword
            tok_to_kw = self._get_token_mapping_for_restore()
            if tok_to_kw:
                self.highlight_keywords(self.restore_in_text, list(tok_to_kw.keys()), ignore_case=False)
                self.highlight_keywords(self.restore_out_text, list(tok_to_kw.values()), ignore_case=False)
            return

        idx = self._get_selected_slot_index()
        if idx is None or not (0 <= idx < len(self.slots)):
            return
        s = self.slots[idx]
        kw = str(s.get("keyword", "")).strip()
        name = str(s.get("name", "")).strip()

        # 发送前：选中行
        if kw:
            self.highlight_keywords(self.send_in_text, [kw], ignore_case=ignore_case)
        if name:
            self.highlight_keywords(self.send_out_text, [self._token_for_name(name)], ignore_case=False)

        # 收到后：选中行
        tok_to_kw = self._get_token_mapping_for_restore()
        if tok_to_kw and name:
            token = self._token_for_name(name)
            keyword = tok_to_kw.get(token, "")
            if token:
                self.highlight_keywords(self.restore_in_text, [token], ignore_case=False)
            if keyword:
                self.highlight_keywords(self.restore_out_text, [keyword], ignore_case=False)

    # ---------------- 按钮：剪贴板 ----------------

    def _copy_html_to_clipboard(self, plain_text: str, html_content: str) -> None:
        text = plain_text or ""
        if html_content:
            fragment = html_content
        else:
            fragment = self._to_word_html(text)
        html_bytes = build_cf_html(fragment)
        if os.name != "nt":
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            return

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        html_format = user32.RegisterClipboardFormatW(CF_HTML_NAME)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.argtypes = []
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL

        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        if not user32.OpenClipboard(None):
            raise OSError("无法打开剪贴板。")
        try:
            if not user32.EmptyClipboard():
                raise OSError("清空剪贴板失败。")

            def put_clipboard_data(fmt: int, payload: bytes) -> None:
                size = len(payload)
                handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
                if not handle:
                    raise MemoryError("分配剪贴板内存失败。")
                locked = kernel32.GlobalLock(handle)
                if not locked:
                    kernel32.GlobalFree(handle)
                    raise MemoryError("锁定剪贴板内存失败。")
                ctypes.memmove(locked, payload, size)
                kernel32.GlobalUnlock(handle)
                if not user32.SetClipboardData(fmt, handle):
                    kernel32.GlobalFree(handle)
                    raise OSError("写入剪贴板失败。")

            put_clipboard_data(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
            put_clipboard_data(html_format, html_bytes + b"\0")
        finally:
            user32.CloseClipboard()
        self.root.update()

    def copy_result(self, kind: str) -> None:
        try:
            if kind == "send":
                self._copy_html_to_clipboard(self._get_text_preview(self._send_out_plain_text), self._send_out_html)
                return
            if kind == "restore":
                self._copy_html_to_clipboard(self._get_text_preview(self._restore_out_plain_text), self._restore_out_html)
                return
            raise ValueError(f"未知复制类型：{kind}")
        except Exception as e:
            # 兜底：至少能复制纯文本
            try:
                if kind == "send":
                    self.root.clipboard_clear()
                    self.root.clipboard_append(self._get_text_preview(self._send_out_plain_text))
                    self.root.update()
                    return
                if kind == "restore":
                    self.root.clipboard_clear()
                    self.root.clipboard_append(self._get_text_preview(self._restore_out_plain_text))
                    self.root.update()
                    return
            except Exception:
                pass
            messagebox.showinfo(APP_NAME, f"复制失败：{e}")

    def paste_into(self, widget: tk.Text) -> None:
        try:
            data = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(APP_NAME, "剪贴板为空或无法读取。")
            return

        self._programmatic = True
        widget.insert("insert", data)
        self._programmatic = False
        widget.edit_modified(False)

        if widget is self.send_in_text:
            self.schedule_desensitize_update()
            self.schedule_highlight_update()
        if widget is self.restore_in_text:
            self.schedule_restore_update()

    def set_text(self, widget: tk.Text, content: str) -> None:
        self._programmatic = True
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        if widget in (self.send_out_text, self.restore_out_text):
            widget.configure(state="disabled")
        self._programmatic = False
        widget.edit_modified(False)
        if widget is self.send_in_text:
            self.schedule_desensitize_update()
            self.schedule_highlight_update()
        if widget is self.restore_in_text:
            self.schedule_restore_update()

    def set_readonly_text(self, widget: tk.Text, content: str) -> None:
        self._programmatic = True
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")
        self._programmatic = False
        widget.edit_modified(False)

    def desensitize_and_copy(self) -> None:
        self.update_desensitize()
        self.copy_result("send")

    def restore_and_copy(self) -> None:
        self.update_restore()
        self.copy_result("restore")

    def on_close(self) -> None:
        try:
            self._save_slots()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
