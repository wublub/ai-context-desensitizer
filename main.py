# -*- coding: utf-8 -*-
from __future__ import annotations

import os
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


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1240x800")
        self.root.minsize(1040, 680)

        self.root.bind_all("<Key>", self._on_any_key_for_easter)

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
            "highlight_all": "<Control-h>",
        }
        self._bound_shortcuts: list[str] = []

        # 槽位：每个槽位 1 个名称（可改名） + 1 个关键词（通过快捷键绑定）
        self.slots: list[dict] = []
        self._selected_slot_index: int | None = None

        self._after_desensitize: str | None = None
        self._after_restore: str | None = None
        self._after_highlight: str | None = None
        self._programmatic = False

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

        # 编辑区（改名）
        edit = ttk.Frame(self.left, padding=(0, 10, 0, 0))
        edit.grid(row=2, column=0, columnspan=2, sticky="ew")
        edit.columnconfigure(1, weight=1)

        self.slot_name_var = tk.StringVar(value="")
        self.slot_keyword_var = tk.StringVar(value="")

        ttk.Label(edit, text="名称：").grid(row=0, column=0, sticky="w")
        self.slot_name_entry = ttk.Entry(edit, textvariable=self.slot_name_var)
        self.slot_name_entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Button(edit, text="改名", command=self.rename_selected_slot).grid(row=0, column=2, padx=(6, 0))

        ttk.Label(edit, text="关键词：").grid(row=1, column=0, sticky="w", pady=(6, 0))
        kw_preview = ttk.Entry(edit, textvariable=self.slot_keyword_var)
        kw_preview.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        kw_preview.configure(state="readonly")

        self.slot_name_entry.bind("<Return>", lambda e: self.rename_selected_slot())

        # 操作按钮
        btns = ttk.Frame(self.left, padding=(0, 8, 0, 0))
        btns.grid(row=3, column=0, columnspan=2, sticky="ew")
        btns.columnconfigure(0, weight=1)

        self.bind_btn = ttk.Button(btns, text="选中文字后按快捷键命名", command=self.bind_selection_to_slot)
        self.bind_btn.grid(row=0, column=0, sticky="ew")


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
        ttk.Label(top_bar, text="原文（粘贴你要发给AI的内容）").grid(row=0, column=0, sticky="w")
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

        bottom_bar = ttk.Frame(t)
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.columnconfigure(0, weight=1)
        ttk.Label(bottom_bar, text="脱敏后（发给AI）").grid(row=0, column=0, sticky="w")
        ttk.Button(bottom_bar, text="复制", command=lambda: self.copy_from(self.send_out_text)).grid(
            row=0, column=1, padx=(6, 0)
        )

        self.send_out_text, self.send_out_scroll = self._make_text_with_scroll(t, readonly=True)
        self.send_out_text.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.send_out_scroll.grid(row=3, column=1, sticky="ns", pady=(6, 0))
        self.send_out_text.tag_configure("kw", background="#FFF59D")

        self.send_status = ttk.Label(t, text="替换次数：0")
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
        ttk.Label(top_bar, text="AI返回（粘贴AI输出）").grid(row=0, column=0, sticky="w")
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

        bottom_bar = ttk.Frame(t)
        bottom_bar.grid(row=2, column=0, sticky="ew")
        bottom_bar.columnconfigure(0, weight=1)
        ttk.Label(bottom_bar, text="还原后").grid(row=0, column=0, sticky="w")
        ttk.Button(bottom_bar, text="复制", command=lambda: self.copy_from(self.restore_out_text)).grid(
            row=0, column=1, padx=(6, 0)
        )

        self.restore_out_text, self.restore_out_scroll = self._make_text_with_scroll(t, readonly=True)
        self.restore_out_text.grid(row=3, column=0, sticky="nsew", pady=(6, 0))
        self.restore_out_scroll.grid(row=3, column=1, sticky="ns", pady=(6, 0))
        self.restore_out_text.tag_configure("kw", background="#FFF59D")

        self.restore_status = ttk.Label(t, text="还原次数：0")
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
        if idx is None or not (0 <= idx < len(self.slots)):
            messagebox.showinfo(APP_NAME, "请先在左侧列表选中一个名称。")
            return

        raw = self.slot_name_var.get()
        name = _strip_token_brackets(raw)
        if not name:
            messagebox.showinfo(APP_NAME, "名称不能为空。")
            return

        # 名称唯一：避免 token 冲突（token = [名称]）
        for j, s in enumerate(self.slots):
            if j == idx:
                continue
            if str(s.get("name", "")).strip() == name:
                messagebox.showinfo(APP_NAME, "名称已存在，请换一个名称（名称必须唯一）。")
                return

        self.slots[idx]["name"] = name
        self._save_slots()
        self._refresh_slots_tree(select_index=idx)
        self._schedule_all_updates()

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

        default_name = ""
        cur_sel = self._get_selected_slot_index()
        if cur_sel is not None and 0 <= cur_sel < len(self.slots):
            default_name = str(self.slots[cur_sel].get("name", "")).strip()

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

        tip = ttk.Label(frm, text="输入示例：Ctrl+Alt+K / Ctrl+Alt+H", foreground="#666")
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
            "AI脱敏工具\n\n致谢：大模型 gpt5.2\n致谢：产品经理 wublub",
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

        self.set_readonly_text(self.send_out_text, res.output_text)
        self.send_status.configure(text=f"替换次数：{res.replacement_count} | 映射已保存到：{self.mapping_path}")

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
        self.set_readonly_text(self.restore_out_text, out)

        mapping_state = "已加载上次映射" if tok_to_kw else "未找到映射（请先在脱敏页替换一次）"
        self.restore_status.configure(text=f"还原次数：{count} | {mapping_state}")

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

    def copy_from(self, widget: tk.Text) -> None:
        text = widget.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

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
        self.copy_from(self.send_out_text)

    def restore_and_copy(self) -> None:
        self.update_restore()
        self.copy_from(self.restore_out_text)

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
