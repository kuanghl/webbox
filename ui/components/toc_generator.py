"""翻译后处理：从原 PDF 提取目录（书签或目录页文字），翻译标题并写入输出 PDF。

背景
----
babeldoc 只迁移"原 PDF 已存在的书签"（``migrate_toc``）；原 PDF 没有书签时
（如 PCI 规范类文档，目录以目录页文字形式存在），输出 PDF 完全没有书签，
且目录页文字常因段落合并问题翻译乱序。

本模块作为 WebUI 层的普适后处理：
1. 优先读取原 PDF 书签（``get_toc``）；
2. 没有书签时，解析目录页文字（``标题 .... 页码`` 模式）；
3. 用主翻译引擎批量翻译标题；
4. 把书签写入 mono / dual 输出 PDF（交替页 dual 模式页码无法映射，跳过）。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 目录条目：编号 + 标题 + 点线引导符 + 页码
_TOC_LINE_RE = re.compile(
    r"^\s*([\dIVXivx]+(?:[.\-][\dIVXivx]+)*\.?)\s+"
    r"(.+?)\s*[.…·•]{2,}\s*(\d{1,3})\s*$"
)

# 纯编号行（目录条目编号与标题常被拆成两行，如 "1.1. " / "BASE CLASS 00H .... 10"）
_PURE_NUMBER_RE = re.compile(
    r"^\s*([\dIVXivx]+(?:[.\-][\dIVXivx]+)*\.?)\s*$"
)

# 目录条目编号行（要求以点结尾，排除页脚纯数字如 "5"；点后空格可选，
# 因为 babeldoc 翻译后编号行可能变成 "1.1." 无尾随空格）
_TOC_NUMBER_RE = re.compile(r"^\s*[\dIVXivx]+(?:[.\-][\dIVXivx]+)*\.\s?")

_TOC_TRANSLATE_PROMPT = """You are a professional translator. Translate the following
table-of-contents titles into {lang_out}.

Rules:
- Keep numbers, hex codes, version numbers, and proper nouns unchanged.
- Translate only the human-readable title part.
- Keep the same "id" for each item, output a JSON array:
  [{{"id": 0, "output": "..."}}, ...]
- No extra text, no ```json blocks.

Input:
{json_input}
"""


def _merge_split_toc_lines(lines: list[str]) -> list[str]:
    """合并被拆行的目录条目：'1.1. ' + 'BASE CLASS 00H .... 10' -> 单行。"""
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _PURE_NUMBER_RE.match(line)
        if m and i + 1 < len(lines):
            nxt = lines[i + 1]
            if "...." in nxt and re.search(r"\d\s*$", nxt):
                merged.append(f"{line} {nxt}")
                i += 2
                continue
        merged.append(line)
        i += 1
    return merged


def parse_toc_page_text(text: str) -> list[tuple[int, str, int]]:
    """从目录页文本解析 (level, title, page) 条目。

    ``level`` 由编号中小数点数量推导：``1.`` → 1，``1.1.`` → 2，``1.1.1`` → 3。
    无法推导编号的标题（如 "Tables"）按同级（1）处理。
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines = _merge_split_toc_lines(lines)
    entries: list[tuple[int, str, int]] = []
    for line in lines:
        m = _TOC_LINE_RE.match(line)
        if not m:
            continue
        number, title, page = m.group(1), m.group(2).strip(), m.group(3)
        try:
            page_num = int(page)
        except ValueError:
            continue
        level = max(1, len([x for x in number.split(".") if x]))
        title = f"{number} {title}" if number else title
        entries.append((level, title, page_num))
    return entries


def extract_toc_entries(pdf_path: str | Path) -> list[tuple[int, str, int]]:
    """提取目录条目：优先书签，其次解析目录页文字。"""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        toc = doc.get_toc()
        if toc:
            logger.info(f"Using {len(toc)} bookmarks from original PDF.")
            return toc
        # 无书签：扫描含点线引导符的页面
        for page in doc:
            entries = parse_toc_page_text(page.get_text())
            if entries:
                logger.info(
                    f"Parsed {len(entries)} TOC entries from page {page.number + 1}."
                )
                return entries
    finally:
        doc.close()
    logger.info("No TOC found in the original PDF.")
    return []


def _parse_translated_titles(llm_output: str, n_titles: int) -> dict[int, str]:
    """容错解析批量翻译结果：尽力抢救被说明文字/截断破坏的 JSON。"""
    if not llm_output:
        return {}
    text = str(llm_output).strip()
    for tag in ("<json>", "```json", "```"):
        if text.startswith(tag):
            text = text[len(tag):]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    start, end = text.find("["), text.rfind("]")
    results: dict[int, str] = {}
    if start != -1 and end > start:
        segment = text[start:end + 1]
        # 补齐被截断的右花括号 / 右方括号
        segment += "}" * max(0, segment.count("{") - segment.count("}"))
        segment += "]" * max(0, segment.count("[") - segment.count("]"))
        try:
            data = json.loads(segment, strict=False)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "id" in item and item.get("output"):
                        try:
                            results[int(item["id"])] = str(item["output"]).strip()
                        except (TypeError, ValueError):
                            continue
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    if not results:
        # 兜底：正则打捞 {"id": N, "output": "..."}（允许截断未闭合）
        for m in re.finditer(
            r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"output"\s*:\s*"((?:[^"\\]|\\.)*)"',
            text,
        ):
            results[int(m.group(1))] = m.group(2).replace('\\"', '"').strip()
    return results


def translate_toc_entries(
    entries: list[tuple[int, str, int]],
    translator,
    lang_out: str,
) -> list[tuple[int, str, int]]:
    """批量翻译目录标题，返回 (level, 翻译后标题, page)。失败时回退原标题。"""
    if not entries or not hasattr(translator, "llm_translate"):
        return entries

    # 去重标题（同一标题可能出现在多级/多次），按原始顺序翻译
    unique_titles: list[str] = []
    for _, title, _ in entries:
        if title not in unique_titles:
            unique_titles.append(title)

    json_input = json.dumps(
        [{"id": i, "title": t} for i, t in enumerate(unique_titles)],
        ensure_ascii=False,
    )
    prompt = _TOC_TRANSLATE_PROMPT.format(
        lang_out=lang_out,
        json_input=json_input,
    )
    try:
        output = translator.llm_translate(
            prompt,
            rate_limit_params={
                "paragraph_token_count": sum(len(t) for t in unique_titles),
                "request_json_mode": True,
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TOC title translation failed: {e}")
        return entries

    translated = _parse_translated_titles(output, len(unique_titles))
    title_map = {
        unique_titles[i]: translated.get(i, unique_titles[i])
        for i in range(len(unique_titles))
    }
    logger.info(
        f"TOC titles: translated {len(translated)}/{len(unique_titles)}, "
        f"fallback to original for the rest."
    )
    return [(level, title_map.get(title, title), page) for level, title, page in entries]


def apply_toc_to_pdf(pdf_path: str | Path, entries: list[tuple[int, str, int]]) -> bool:
    """把书签写入输出 PDF（增量保存，保留原有内容）。"""
    import fitz

    pdf_path = Path(pdf_path)
    if not pdf_path.exists() or not entries:
        return False
    try:
        doc = fitz.open(pdf_path)
        try:
            doc.set_toc(entries)
            doc.saveIncr()
        finally:
            doc.close()
        logger.info(f"TOC bookmarks written to {pdf_path.name}")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to write TOC to {pdf_path}: {e}")
        return False


_TOC_LEADER_RE = re.compile(r"\.{3,}")

# 目录页重建参数（与 PCI 类规范页面的常规排版近似；以页宽自适应）
_TOC_PAGE_X0 = 84.0  # 标题左对齐 x
_TOC_PAGE_RIGHT_MARGIN = 24.0  # 页码右边缘距页右的留白


def _find_toc_page_numbers(doc) -> list[int]:
    """定位输出 PDF 中的目录页。

    判定：页面含 "Contents"/"目录" 标题，且满足以下任一条件：
    - 至少 3 行带点线引导符的目录条目（排除 "TABLE"/"表" 开头的表格列表行）；
    - 至少 3 行以编号开头的短条目（如 "1. "、"1.1. "，翻译后点线可能被移除）。
    """
    page_numbers: list[int] = []
    for pno in range(min(doc.page_count, 8)):
        text = doc[pno].get_text()
        if not re.search(r"^\s*(Contents|目录)\s*$", text, re.MULTILINE):
            continue
        leader_lines = [
            l
            for l in text.splitlines()
            if _TOC_LEADER_RE.search(l)
            and not re.match(r"^\s*(TABLE|表)\b", l.strip(), re.IGNORECASE)
        ]
        numbered_lines = [
            l
            for l in text.splitlines()
            if _TOC_NUMBER_RE.match(l.strip())
            and not re.match(r"^\s*(TABLE|表)\b", l.strip(), re.IGNORECASE)
        ]
        if len(leader_lines) >= 3 or len(numbered_lines) >= 3:
            page_numbers.append(pno)
    return page_numbers


def rewrite_toc_page_in_pdf(
    pdf_path: str | Path,
    entries: list[tuple[int, str, int]],
    lang_out: str = "zh",
) -> bool:
    """重建输出 PDF 的目录页：删除原目录条目文字，按翻译后的条目重排"标题 … 页码"。

    仅删除"含点线引导符的文本行"区域（保留页眉/页脚/标题）；输出 PDF 无
    可识别目录页时跳过。失败不影响书签（幂等、可跳过）。
    """
    import fitz

    pdf_path = Path(pdf_path)
    if not pdf_path.exists() or not entries:
        return False
    try:
        doc = fitz.open(pdf_path)
        toc_pages = _find_toc_page_numbers(doc)
        if not toc_pages:
            logger.info(f"No TOC page found in {pdf_path.name}, skip page rewrite.")
            doc.close()
            return False

        fontname = "china-s"  # 内置 CJK 字体，覆盖中英文
        dot_width = fitz.get_text_length(".", fontname=fontname, fontsize=10)
        page_width = doc[0].rect.width
        page_x1 = page_width - _TOC_PAGE_RIGHT_MARGIN

        for pno in toc_pages:
            page = doc[pno]
            # 双语对照页（原文/译文同页，含未翻译的 "Contents" 标题）不做文本
            # 重建，避免删除原文部分；书签已在 apply_toc_to_pdf 写入。
            page_text = page.get_text()
            if re.search(r"^\s*Contents\s*$", page_text, re.MULTILINE):
                logger.info(
                    f"Bilingual TOC page (index {pno}) in {pdf_path.name}, "
                    f"skip page rewrite (bookmarks already written)."
                )
                continue
            # 1) 定位目录条目区域：优先点线行，其次编号条目行（翻译后点线可能被移除）
            d = page.get_text("dict")
            region_ys: list[float] = []
            for block in d["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    txt = "".join(s["text"] for s in line["spans"])
                    if _TOC_LEADER_RE.search(txt) or _TOC_NUMBER_RE.match(
                        txt.strip(),
                    ):
                        region_ys.append(fitz.Rect(line["bbox"]).y0)
            if not region_ys:
                continue
            region_top = min(region_ys) - 2.0
            region_bottom = max(region_ys) + 2.0
            lines_to_remove: list[fitz.Rect] = []
            for block in d["blocks"]:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    rect = fitz.Rect(line["bbox"])
                    if region_top <= rect.y0 <= region_bottom:
                        lines_to_remove.append(rect)
            for rect in lines_to_remove:
                page.add_redact_annot(rect)
            page.apply_redactions()

            # 2) 在原来第一条目的位置开始写入翻译后的条目
            y = region_top + 3.0
            for level, title, pg in entries:
                title = title.strip()
                title_text = f"{'  ' * (level - 1)}{title}"
                title_w = fitz.get_text_length(
                    title_text, fontname=fontname, fontsize=10
                )
                page_num_text = str(pg)
                num_w = fitz.get_text_length(
                    page_num_text, fontname=fontname, fontsize=10
                )
                dots_len = max(
                    3,
                    int(
                        (
                            page_x1
                            - _TOC_PAGE_X0
                            - title_w
                            - num_w
                            - 12
                        )
                        / dot_width
                    ),
                )
                dots = "." * dots_len
                line = f"{title_text} {dots} {page_num_text}"
                page.insert_text(
                    fitz.Point(_TOC_PAGE_X0, y),
                    line,
                    fontname=fontname,
                    fontsize=10,
                    color=(0, 0, 0),
                )
                y += 14.0
                if y > page.rect.height - 60:
                    break
        doc.saveIncr()
        doc.close()
        logger.info(
            f"TOC page rewritten in {pdf_path.name} ({len(toc_pages)} page(s), "
            f"{len(entries)} entries)."
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Failed to rewrite TOC page in {pdf_path}: {e}")
        return False


def add_toc_to_translation_results(
    original_pdf: str | Path,
    result_files: list[str | Path],
    translator,
    lang_out: str,
    skip_if_alternating_pages: bool = False,
) -> None:
    """一站式后处理：提取目录 → 翻译标题 → 写入书签并重建目录页。

    Args:
        original_pdf: 原始 PDF 路径。
        result_files: 输出 PDF 路径列表（mono/dual）。
        translator: 主翻译引擎（提供 ``llm_translate``）。
        lang_out: 目标语言代码。
        skip_if_alternating_pages: 交替页 dual 模式页码无法映射时跳过。
    """
    entries = extract_toc_entries(original_pdf)
    if not entries:
        return
    if skip_if_alternating_pages:
        logger.info("Skipping TOC generation for alternating-pages dual mode.")
        return
    entries = translate_toc_entries(entries, translator, lang_out)
    for f in result_files:
        apply_toc_to_pdf(f, entries)
        rewrite_toc_page_in_pdf(f, entries, lang_out=lang_out)
