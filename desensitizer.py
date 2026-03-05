# -*- coding: utf-8 -*-
"""脱敏/还原核心逻辑（离线本地）"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


TOKEN_PREFIX = "<<SENS_"
TOKEN_SUFFIX = ">>"


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def normalize_keywords(keywords: List[str]) -> List[str]:
    """清理关键词：去空白、去空、保持顺序去重。"""
    cleaned = [k.strip() for k in keywords]
    cleaned = [k for k in cleaned if k]
    return _dedupe_keep_order(cleaned)


def build_keyword_regex(keywords: List[str], *, ignore_case: bool = False) -> re.Pattern | None:
    """构建用于“匹配任意关键词”的正则。按长度降序，减少子串抢先匹配。"""
    kws = normalize_keywords(keywords)
    if not kws:
        return None

    # 长的优先，避免例如：abc 与 abcd 同时存在时先匹配到 abc
    kws_sorted = sorted(kws, key=len, reverse=True)
    escaped = [re.escape(k) for k in kws_sorted]
    pattern = "|".join(escaped)
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    return re.compile(pattern, flags)


def keyword_to_token(keyword: str) -> str:
    """为单个关键词生成稳定 token（尽量不受顺序影响）。"""
    # 用 hash 保持稳定，同时尽量短。
    h = hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:10].upper()
    return f"{TOKEN_PREFIX}{h}{TOKEN_SUFFIX}"


@dataclass
class DesensitizeResult:
    output_text: str
    token_to_keyword: Dict[str, str]
    keyword_to_token: Dict[str, str]
    replacement_count: int


def desensitize(
    text: str,
    keywords: List[str],
    *,
    ignore_case: bool = False,
    keyword_to_token_override: Dict[str, str] | None = None,
) -> DesensitizeResult:
    kws = normalize_keywords(keywords)
    if not kws or not text:
        return DesensitizeResult(
            output_text=text,
            token_to_keyword={},
            keyword_to_token={},
            replacement_count=0,
        )

    override = keyword_to_token_override or {}

    # 建立映射：优先使用 override（用于“公司1/药物名1”等命名占位符），否则退回到 hash token
    used_tokens: set[str] = set()
    kw_to_tok: Dict[str, str] = {}
    for k in kws:
        tok: str | None = None

        cand = override.get(k)
        if isinstance(cand, str):
            cand = cand.strip()
        if cand and cand not in used_tokens:
            tok = cand

        if tok is None:
            tok = keyword_to_token(k)
            # 理论上不会冲突，但仍做一次防御
            while tok in used_tokens:
                tok = f"{tok}_{hashlib.sha1((k + tok).encode('utf-8')).hexdigest()[:4].upper()}"

        kw_to_tok[k] = tok
        used_tokens.add(tok)

    tok_to_kw: Dict[str, str] = {v: k for k, v in kw_to_tok.items()}

    rx = build_keyword_regex(kws, ignore_case=ignore_case)
    if rx is None:
        return DesensitizeResult(
            output_text=text,
            token_to_keyword={},
            keyword_to_token={},
            replacement_count=0,
        )

    replacement_count = 0

    if not ignore_case:
        def repl(m: re.Match) -> str:
            nonlocal replacement_count
            replacement_count += 1
            return kw_to_tok[m.group(0)]

        out = rx.sub(repl, text)
        return DesensitizeResult(
            output_text=out,
            token_to_keyword=tok_to_kw,
            keyword_to_token=kw_to_tok,
            replacement_count=replacement_count,
        )

    # ignore_case 情况下，match 可能与原关键词大小写不一致：用 lower 映射
    kw_lower_to_kw = {k.lower(): k for k in kws}

    def repl_ic(m: re.Match) -> str:
        nonlocal replacement_count
        replacement_count += 1
        original = kw_lower_to_kw[m.group(0).lower()]
        return kw_to_tok[original]

    out = rx.sub(repl_ic, text)
    return DesensitizeResult(
        output_text=out,
        token_to_keyword=tok_to_kw,
        keyword_to_token=kw_to_tok,
        replacement_count=replacement_count,
    )


def restore(text: str, token_to_keyword: Dict[str, str]) -> Tuple[str, int]:
    """把 token 还原成关键词。返回（还原后文本，替换次数）。"""
    if not text or not token_to_keyword:
        return text, 0

    # token 不应该互为子串，但仍按长度降序更稳。
    tokens = sorted(token_to_keyword.keys(), key=len, reverse=True)
    pattern = "|".join(re.escape(t) for t in tokens)
    rx = re.compile(pattern)

    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        count += 1
        return token_to_keyword[m.group(0)]

    return rx.sub(repl, text), count


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:
        return default


def make_mapping_payload(
    token_to_keyword: Dict[str, str],
    keyword_to_token: Dict[str, str],
    *,
    keyword_to_label: Dict[str, str] | None = None,
) -> dict:
    payload = {
        "version": 2,
        "created_at": int(time.time()),
        "token_to_keyword": token_to_keyword,
        "keyword_to_token": keyword_to_token,
    }
    if keyword_to_label:
        payload["keyword_to_label"] = keyword_to_label
    return payload
