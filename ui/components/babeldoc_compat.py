"""babeldoc 翻译质量增强补丁层（monkeypatch，不修改 site-packages）。

设计原则
--------
本模块针对 babeldoc 0.6.x 翻译管线的**通用薄弱点**做进程内补丁，而非针对
某个具体 PDF：

1. 段落被错误合并成单行（坐标异常/分行算法退化）→ 文本顺序错乱、翻译乱码
   （典型症状：目录/TOC 页 "H.10 12 01 . ." 乱序）。
   - 补丁：``ParagraphFinder.process_page`` 后按 y 坐标聚类重新分行。

2. 自动术语提取质量差（提取大量通用词/纯数字/未翻译条目，污染术语表）。
   - 补丁：``SharedContextCrossSplitPart.finalize_auto_extracted_glossary``
     增加过滤；``AutomaticTermExtractor.extract_terms_from_paragraphs``
     改用容错 JSON 解析（LLM 输出带说明文字/截断时仍能抢救术语）。

3. 批量翻译时 LLM 输出缺 id（length mismatch）→ 整批丢弃、整批 fallback，
   已翻译正确的段落也被浪费；短段落翻译后被长度比例误判为异常。
   - 补丁：``ILTranslatorLLMOnly.translate_paragraph`` 部分匹配时保留
     已返回段落、仅对缺失段落补翻；短输入放宽长度比例检查。

4. 富文本占位符超过硬编码阈值（40）→ 段落富文本翻译被禁用、格式丢失。
   - 补丁：``ILTranslator.get_translate_input`` 阈值上调，保留保护机制。

补丁在 WebUI 进程内生效，不写入 site-packages；babeldoc 升级后重启 WebUI
即重新应用（补丁与 0.6.4 源码逐行对齐，若上游 API 变更会打印告警并跳过）。
"""

from __future__ import annotations

import importlib
import json
import logging
import re

import Levenshtein
from babeldoc.format.pdf.document_il.midend import il_translator
from babeldoc.format.pdf.document_il.utils.paragraph_helper import (
    is_pure_numeric_paragraph,
    is_placeholder_only_paragraph,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import (
    get_char_unicode_string,
    is_same_style,
    is_same_style_except_font,
    is_same_style_except_size,
)

logger = logging.getLogger(__name__)

_PATCH_APPLIED = False

# ---------------------------------------------------------------------------
# P2：自动术语提取 —— 过滤规则
# ---------------------------------------------------------------------------

# 常见英语功能词 / 通用名词：不应作为术语强制替换
_COMMON_EN_WORDS: set[str] = {
    "a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "with",
    "by", "from", "at", "as", "is", "are", "be", "this", "that", "these",
    "those", "it", "its", "all", "any", "each", "one", "other", "others",
    "class", "base", "date", "dates", "notes", "note", "section", "sections",
    "history", "host", "controller", "controllers", "device", "devices",
    "function", "functions", "interface", "interfaces", "value", "values",
    "type", "types", "name", "names", "field", "fields", "byte", "bytes",
    "bit", "bits", "register", "registers", "specification", "document",
    "documents", "revision", "version", "chapter", "page", "pages", "table",
    "tables", "figure", "figures", "list", "description", "meaning",
    "code", "codes", "number", "numbers", "status", "state", "index",
    "content", "contents", "reference", "references", "objective",
    "standard", "standards", "mode", "modes", "operation", "operations",
    "supported", "support", "used", "use", "new", "general", "generic",
    "public", "vendor", "specific", "example", "examples", "capability",
    "capabilities", "capabilities", "programming", "reserved", "defined",
    "following", "follows", "below", "above", "see", "shown", "shows",
    "please", "contact", "via", "using", "used", "between", "within",
    "after", "before", "both", "same", "such", "than", "then", "there",
    "they", "two", "three", "etc", "e.g", "i.e", "approx", "approximately",
    "about", "also", "may", "must", "can", "could", "should", "will",
}

# 句子性标点：术语不应包含（"PCI-SIG" 等专名例外，允许 - 和 _）
_SENTENCE_PUNCT_RE = re.compile(r"[.,;:!?。，；：！？、…]")


def _is_reasonable_term(src: str, tgt: str) -> bool:
    """判断自动提取的 (src, tgt) 是否值得保留为术语。"""
    s = (src or "").strip()
    t = (tgt or "").strip()
    if not s or not t:
        return False
    if s == t:
        # 等值术语：≥3 字符的缩写/专名（NVMe、PCI-SIG）保留以锁定不译；
        # 纯数值/过短符号（00h、1.12、a）无意义，丢弃。
        if len(s) < 3:
            return False
        if re.fullmatch(r"[\d\sA-Fa-fhHxXbB.,/\\\-]+", s):
            return False
        return True
    if len(s) < 2:
        return False
    if s.lower() in _COMMON_EN_WORDS:
        return False
    # 纯数字 / 纯十六进制数值 / 纯标点 / 空壳
    if re.fullmatch(r"[\d\sA-Fa-fhHxXbB.,;:!?()\[\]{}<>\"'\-_/\\]+", s):
        # 纯数值（如 "00h"、"1.12"）不应作为术语
        if not re.search(r"[A-Za-z]", s):
            return False
    # 含句子标点（"." 只允许出现在版本号/缩写内部，如 "e.g."、"rev. 1.2"）
    if _SENTENCE_PUNCT_RE.search(s):
        # 允许 "PCI-SIG"、带连字符/下划线的标识符
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\- ]*", s):
            return False
    # 全小写单/双字母缩写无意义（如 "st"、"of"）
    if len(s) <= 2 and s.islower():
        return False
    return True


def _finalize_auto_extracted_glossary_patched(self) -> None:
    """过滤后的术语表生成（替代 SharedContextCrossSplitPart.finalize_auto_extracted_glossary）。"""
    from collections import Counter

    from babeldoc.glossary import Glossary, GlossaryEntry

    with self._lock:
        self.auto_extracted_glossary = None
        if not self.raw_extracted_terms:
            self.raw_extracted_terms = []
            return

        raw_count = len(self.raw_extracted_terms)
        filtered = [
            (s, t)
            for s, t in self.raw_extracted_terms
            if _is_reasonable_term(s, t)
        ]
        dropped = raw_count - len(filtered)
        if dropped:
            logger.info(
                f"Term extraction filter: dropped {dropped}/{raw_count} "
                f"generic/empty term pairs.",
            )

        term_translations: dict[str, list[str]] = {}
        for src, tgt in filtered:
            term_translations.setdefault(src, []).append(tgt)

        final_entries: list[GlossaryEntry] = []
        for src, tgts in term_translations.items():
            if not tgts:
                continue
            most_common_tgt = Counter(tgts).most_common(1)[0][0]
            final_entries.append(GlossaryEntry(src, most_common_tgt))

        if final_entries:
            self.auto_extracted_glossary = Glossary(
                name=self.unique_name, entries=final_entries
            )


# ---------------------------------------------------------------------------
# P2：自动术语提取 —— 容错 JSON 解析（LLM 输出带说明/截断时仍能抢救）
# ---------------------------------------------------------------------------

_SRC_TGT_RE = re.compile(
    r'\{\s*"src"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"tgt"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
)
_TGT_SRC_RE = re.compile(
    r'\{\s*"tgt"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"src"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
)


def _pairs_from_list(data) -> list[tuple[str, str]]:
    """把 json.loads 的结果归一化为 (src, tgt) 对列表。"""
    pairs: list[tuple[str, str]] = []
    if not isinstance(data, list):
        data = [data]
    for item in data:
        if not isinstance(item, dict):
            continue
        if item.get("src") is None or item.get("tgt") is None:
            continue
        src = str(item["src"]).strip()
        tgt = str(item["tgt"]).strip()
        if src and tgt:
            pairs.append((src, tgt))
    return pairs


def parse_term_pairs(text) -> list[tuple[str, str]]:
    """容错解析模型返回的术语数组。

    None/空内容 → ``[]``。层层降级解析，尽量抢救被说明文字/截断破坏的 JSON。
    """
    if not text:
        return []
    if not isinstance(text, str):
        return []

    text = text.strip()
    if text.startswith("<json>"):
        text = text[6:]
    if text.endswith("</json>"):
        text = text[:-7]
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    candidates: list[str] = []
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        segment = text[start : end + 1]
        unbalanced = segment.count("[") - segment.count("]")
        if unbalanced > 0:
            segment += "]" * unbalanced
        candidates.append(segment)

    for cand in candidates:
        try:
            pairs = _pairs_from_list(json.loads(cand, strict=False))
            if pairs:
                return pairs
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    # 最后兜底：正则逐个打捞 {"src":..., "tgt":...} 对象
    pairs: list[tuple[str, str]] = []
    for pattern in (_SRC_TGT_RE, _TGT_SRC_RE):
        for m in pattern.finditer(text):
            src = m.group(1).replace('\\"', '"').strip()
            tgt = m.group(2).replace('\\"', '"').strip()
            if src and tgt:
                pairs.append((src, tgt))
    return pairs


def _extract_terms_from_paragraphs_robust(
    self,
    paragraphs,
    pbar=None,
    paragraph_token_count: int = 0,
):
    """替代 AutomaticTermExtractor.extract_terms_from_paragraphs 的容错版本。"""
    self.translation_config.raise_if_cancelled()
    try:
        inputs = [p.unicode for p in paragraphs.paragraphs if p.unicode]
        tracker = paragraphs.tracker
        for u in inputs:
            tracker.append_paragraph_unicode(u)
        if not inputs:
            pbar.advance(len(paragraphs.paragraphs))
            return

        # Build reference glossary section
        reference_glossary_section = ""
        user_glossaries = self.shared_context.user_glossaries
        if user_glossaries:
            text_for_glossary = "\n\n".join(inputs)
            glossary_entries = {}
            for glossary in user_glossaries:
                active_entries = glossary.get_active_entries_for_text(
                    text_for_glossary
                )
                if active_entries:
                    glossary_entries[glossary.name] = active_entries
            if glossary_entries:
                reference_glossary_section = (
                    "Reference Glossaries (for consistency and quality):\n"
                )
                for glossary_name, entries in glossary_entries.items():
                    reference_glossary_section += f"\n{glossary_name}:\n"
                    for src, tgt in sorted(set(entries)):
                        reference_glossary_section += f"- {src} → {tgt}\n"
                reference_glossary_section += (
                    "\nPlease consider these existing translations for consistency "
                    "when extracting new terms. IMPORTANT: You should also extract "
                    "terms that appear in the reference glossaries above if they are "
                    "found in the input text - don't skip them just because they "
                    "already exist in the reference."
                )

        prompt = LLM_PROMPT_TEMPLATE.format(
            target_language=self.translation_config.lang_out,
            text_to_process="\n\n".join(inputs),
            reference_glossary_section=reference_glossary_section,
            example_output="""[
  {"src": "LLM", "tgt": "大语言模型"},
  {"src": "GPT", "tgt": "GPT"}
]""",
        )
        tracker.set_input(prompt)
        output = self.translate_engine.llm_translate(
            prompt,
            rate_limit_params={
                "paragraph_token_count": paragraph_token_count,
                "request_json_mode": True,
            },
        )
        tracker.set_output(output)

        for src_term, tgt_term in parse_term_pairs(output):
            if src_term == tgt_term and len(src_term) < 3:
                continue
            if src_term and tgt_term and len(src_term) < 100:
                self.shared_context.add_raw_extracted_term_pair(
                    src_term, tgt_term
                )
    except Exception as e:
        logger.debug("Error during automatic terms extract: %s", e)
        return
    finally:
        pbar.advance(len(paragraphs.paragraphs))


# ---------------------------------------------------------------------------
# P1：段落重分行（修复多行被错误合并为单行导致的乱序）
# ---------------------------------------------------------------------------

_MERGE_GAP = 5.0  # y 坐标差小于该值视为同一行
_MIN_CHARS_TO_CHECK = 20  # 少于该字符数的段落不处理（避免误伤短段落）


def _fix_merged_paragraph_lines(paragraph_finder, page) -> int:
    """把被错误合并为单行的多行段落按 y 聚类重新分行，行内按 x 排序。

    仅在段落"只有一个 LINE 但字符 y 跨度明显大于行高"时触发（正常单行段落
    的 y 跨度 < 2 倍行高），返回修复的段落数。
    """
    from babeldoc.format.pdf.document_il import PdfLine, PdfParagraphComposition

    fixed = 0
    for para in page.pdf_paragraph:
        comps = para.pdf_paragraph_composition
        if len(comps) != 1 or comps[0].pdf_line is None:
            continue
        chars = comps[0].pdf_line.pdf_character
        if not chars or len(chars) < _MIN_CHARS_TO_CHECK:
            continue

        ys = [c.visual_bbox.box.y for c in chars]
        y_min, y_max = min(ys), max(ys)
        if y_max - y_min < 2 * _MERGE_GAP:
            # 正常单行（或本就该是一行）
            continue

        # 按 y 聚类
        ordered = sorted(zip(chars, ys), key=lambda t: t[1], reverse=True)
        groups: list[list] = []  # (avg_y, [chars])
        for char, y in ordered:
            placed = False
            for g in groups:
                if abs(g[0] - y) < _MERGE_GAP:
                    n = len(g[1])
                    g[0] = (g[0] * n + y) / (n + 1)
                    g[1].append(char)
                    placed = True
                    break
            if not placed:
                groups.append([y, [char]])

        if len(groups) < 2:
            continue

        new_comps = []
        for g in sorted(groups, key=lambda g: -g[0]):
            g[1].sort(key=lambda c: c.visual_bbox.box.x)
            line = PdfLine(pdf_character=g[1])
            paragraph_finder.update_line_data(line)
            new_comps.append(PdfParagraphComposition(pdf_line=line))

        para.pdf_paragraph_composition = new_comps
        paragraph_finder.update_paragraph_data(para, update_unicode=True)
        fixed += 1
    return fixed


def _process_page_with_line_fix(self, page) -> None:
    """包装 ParagraphFinder.process_page：原逻辑之后修复误合并的单行段落。"""
    _orig_process_page(self, page)
    try:
        n = _fix_merged_paragraph_lines(self, page)
        if n:
            logger.info(f"ParagraphFinder: re-split {n} mis-merged paragraph(s).")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ParagraphFinder re-split failed: {e}")


# ---------------------------------------------------------------------------
# 补丁应用入口
# ---------------------------------------------------------------------------


def apply_babeldoc_compat_patches() -> bool:
    """在进程内应用全部补丁。幂等，可重复调用；失败仅告警不中断翻译。"""
    global _PATCH_APPLIED, _orig_process_page, LLM_PROMPT_TEMPLATE

    if _PATCH_APPLIED:
        return True

    try:
        import babeldoc.format.pdf.document_il.midend.paragraph_finder as pf_mod
        import babeldoc.format.pdf.document_il.midend.automatic_term_extractor as ate_mod
        import babeldoc.format.pdf.translation_config as tc_mod
        from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import (
            ILTranslatorLLMOnly,
        )
        from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

        # P1: 段落重分行
        global _orig_process_page
        _orig_process_page = pf_mod.ParagraphFinder.process_page
        pf_mod.ParagraphFinder.process_page = _process_page_with_line_fix

        # P2a: 术语过滤
        tc_mod.SharedContextCrossSplitPart.finalize_auto_extracted_glossary = (
            _finalize_auto_extracted_glossary_patched
        )

        # P2b: 术语提取容错 JSON 解析
        LLM_PROMPT_TEMPLATE = ate_mod.LLM_PROMPT_TEMPLATE
        ate_mod.AutomaticTermExtractor.extract_terms_from_paragraphs = (
            _extract_terms_from_paragraphs_robust
        )

        # P3: 批量翻译部分恢复
        ILTranslatorLLMOnly.translate_paragraph = _translate_paragraph_patched

        # P4: 富文本占位符阈值
        ILTranslator.get_translate_input = _get_translate_input_patched

        _PATCH_APPLIED = True
        logger.info("babeldoc 翻译质量补丁已应用 (P1 重分行 / P2 术语 / P3 批量恢复 / P4 富文本阈值)")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"应用 babeldoc 补丁失败（babeldoc 版本可能不兼容）: {e}")
        return False



# ---------------------------------------------------------------------------
# P3：批量翻译部分恢复（复制自 babeldoc 0.6.4 ILTranslatorLLMOnly.translate_paragraph，
# 仅修改：mismatch 部分匹配、短段落长度比例放宽、缺失段落单独补翻）
# ---------------------------------------------------------------------------

def _translate_paragraph_patched(
        self,
        batch_paragraph: BatchParagraph,
        pbar: tqdm | None = None,
        page_font_map: dict[str, PdfFont] = None,
        xobj_font_map: dict[int, dict[str, PdfFont]] = None,
        title_paragraph: TitleContextSnapshot | None = None,
        local_title_paragraph: TitleContextSnapshot | None = None,
        executor: PriorityThreadPoolExecutor | None = None,
        paragraph_token_count: int = 0,
        mp_id: int = 0,
    ):
        """Translate a paragraph using pre and post processing functions."""
        self.translation_config.raise_if_cancelled()
        should_translate_paragraph = []
        try:
            inputs = []
            llm_translate_trackers = []
            paragraph_unicodes = []
            for i in range(len(batch_paragraph.paragraphs)):
                paragraph = batch_paragraph.paragraphs[i]
                tracker = batch_paragraph.trackers[i]
                text, translate_input = self.il_translator.pre_translate_paragraph(
                    paragraph, tracker, page_font_map, xobj_font_map
                )
                if text is None:
                    pbar.advance(1)
                    continue

                tracker.record_multi_paragraph_id(mp_id)

                llm_translate_tracker = tracker.new_llm_translate_tracker()
                should_translate_paragraph.append(i)
                llm_translate_trackers.append(llm_translate_tracker)
                inputs.append(
                    (
                        text,
                        translate_input,
                        paragraph,
                        tracker,
                        llm_translate_tracker,
                        paragraph_unicodes,
                    )
                )
                paragraph_unicodes.append(paragraph.unicode)
            if not inputs:
                return
            json_format_input = []

            for id_, input_text in enumerate(inputs):
                ti: il_translator.ILTranslator.TranslateInput = input_text[1]
                tracker: ParagraphTranslateTracker = input_text[3]
                tracker.record_multi_paragraph_index(id_)
                placeholders_hint = ti.get_placeholders_hint()
                obj = {
                    "id": id_,
                    "input": input_text[0],
                    "layout_label": input_text[2].layout_label,
                }
                if (
                    placeholders_hint
                    and self.translation_config.add_formula_placehold_hint
                ):
                    obj["formula_placeholders_hint"] = placeholders_hint
                json_format_input.append(obj)

            json_format_input_str = json.dumps(
                json_format_input, ensure_ascii=False, indent=2
            )

            batch_text_for_glossary_matching = "\n".join(
                item.get("input", "") for item in json_format_input
            )

            final_input = self._build_llm_prompt(
                json_input_str=json_format_input_str,
                title_paragraph=title_paragraph,
                local_title_paragraph=local_title_paragraph,
                batch_text_for_glossary_matching=batch_text_for_glossary_matching,
            )

            for llm_translate_tracker in llm_translate_trackers:
                llm_translate_tracker.set_input(final_input)
            llm_output = self.translate_engine.llm_translate(
                final_input,
                rate_limit_params={
                    "paragraph_token_count": paragraph_token_count,
                    "request_json_mode": True,
                },
            )
            for llm_translate_tracker in llm_translate_trackers:
                llm_translate_tracker.set_output(llm_output)
            llm_output = llm_output.strip()

            llm_output = self._clean_json_output(llm_output)

            parsed_output = json.loads(llm_output)

            if isinstance(parsed_output, dict) and parsed_output.get(
                "output", parsed_output.get("input", False)
            ):
                parsed_output = [parsed_output]

            translation_results = {
                item["id"]: item.get("output", item.get("input"))
                for item in parsed_output
            }

            # [P3] 部分匹配修复：LLM 输出缺 id 时不再整批丢弃，
            # 已返回的段落照常应用，缺失的段落稍后单独补翻。
            # 注意 id 可能是 int 或 str，统一转 str 比较。
            missing_ids: list[int] = []
            if len(translation_results) != len(inputs):
                present = {str(k) for k in translation_results}
                missing_ids = [
                    i for i in range(len(inputs)) if str(i) not in present
                ]
                if len(translation_results) == 0:
                    raise Exception(
                        f"Translation results length mismatch. Expected: {len(inputs)}, Got: {len(translation_results)}"
                    )
                logger.warning(
                    f"Partial translation results. Expected: {len(inputs)}, Got: {len(translation_results)}. "
                    f"Missing ids: {missing_ids}. Will retry missing paragraphs individually."
                )

            for id_, output in translation_results.items():
                should_fallback = True
                try:
                    if not isinstance(output, str):
                        logger.warning(
                            f"Translation result is not a string. Output: {output}"
                        )
                        continue

                    id_ = int(id_)  # Ensure id is an integer
                    if id_ >= len(inputs):
                        logger.warning(f"Invalid id {id_}, skipping")
                        continue

                    # Clean up any excessive punctuation in the translated text
                    translated_text = re.sub(r"[. 。…，]{20,}", ".", output)

                    # Get the original input for this translation
                    translate_input = inputs[id_][1]
                    llm_translate_tracker = inputs[id_][4]

                    input_unicode = inputs[id_][0]
                    output_unicode = translated_text

                    trimed_input = re.sub(r"[. 。…，]{20,}", ".", input_unicode)

                    input_token_count = self.calc_token_count(trimed_input)
                    output_token_count = self.calc_token_count(output_unicode)

                    same_as_input = trimed_input == output_unicode
                    if (
                        same_as_input
                        and input_token_count > 10
                        and not self.translation_config.disable_same_text_fallback
                    ):
                        llm_translate_tracker.set_error_message(
                            "Translation result is the same as input, fallback."
                        )
                        llm_translate_tracker.set_placeholder_full_match()
                        logger.warning(
                            "Translation result is the same as input, fallback."
                        )
                        continue

                    # [P3] 短段落（<=12 token）翻译后比例波动大（如 "ISA RTC controller"
                    # → 中文 2-3 词），放宽边界，避免误判 fallback。
                    if input_token_count <= 12:
                        ratio_ok = 0.15 < output_token_count / max(input_token_count, 1) < 8
                    else:
                        ratio_ok = 0.3 < output_token_count / input_token_count < 3
                    if not ratio_ok:
                        llm_translate_tracker.set_error_message(
                            f"Translation result is too long or too short. Input: {input_token_count}, Output: {output_token_count}"
                        )
                        logger.warning(
                            f"Translation result is too long or too short. Input: {input_token_count}, Output: {output_token_count}"
                        )
                        llm_translate_tracker.set_placeholder_full_match()
                        continue

                    if not self.translation_config.disable_same_text_fallback:
                        edit_distance = Levenshtein.distance(
                            input_unicode, output_unicode
                        )
                        if edit_distance < 5 and input_token_count > 20:
                            llm_translate_tracker.set_error_message(
                                f"Translation result edit distance is too small. distance: {edit_distance}, input: {input_unicode}, output: {output_unicode}"
                            )
                            logger.warning(
                                f"Translation result edit distance is too small. distance: {edit_distance}, input: {input_unicode}, output: {output_unicode}"
                            )
                            llm_translate_tracker.set_placeholder_full_match()
                            continue
                    # Apply the translation to the paragraph
                    self.il_translator.post_translate_paragraph(
                        inputs[id_][2],
                        inputs[id_][3],
                        translate_input,
                        translated_text,
                    )
                    should_fallback = False
                    if pbar:
                        pbar.advance(1)
                except Exception as e:
                    error_message = f"Error translating paragraph. Error: {e}."
                    logger.exception(error_message)
                    # Ignore error and continue
                    for llm_translate_tracker in llm_translate_trackers:
                        llm_translate_tracker.set_error_message(error_message)
                    continue
                finally:
                    self.total_count += 1
                    if should_fallback:
                        self.fallback_count += 1
                        inputs[id_][4].set_fallback_to_translate()
                        logger.warning(
                            f"Fallback to simple translation. paragraph id: {inputs[id_][2].debug_id}"
                        )
                        paragraph_token_count = self.calc_token_count(
                            inputs[id_][2].unicode
                        )
                        paragraph_unicodes = inputs[id_][5]
                        inputs[id_][2].unicode = paragraph_unicodes[id_]
                        executor.submit(
                            self.il_translator.translate_paragraph,
                            inputs[id_][2],
                            batch_paragraph.pages[id_],
                            pbar,
                            inputs[id_][3],
                            page_font_map,
                            xobj_font_map,
                            priority=1048576 - paragraph_token_count,
                            paragraph_token_count=paragraph_token_count,
                            title_paragraph=title_paragraph,
                            local_title_paragraph=local_title_paragraph,
                        )
                    else:
                        self.ok_count += 1

            # [P3] 对缺失 id 的段落单独补翻（复用简单翻译路径）
            for i in missing_ids:
                if i >= len(inputs):
                    continue
                paragraph = inputs[i][2]
                tracker = inputs[i][3]
                if paragraph.debug_id is None:
                    continue
                paragraph.unicode = paragraph_unicodes[i]
                inputs[i][4].set_fallback_to_translate()
                self.total_count += 1
                self.fallback_count += 1
                logger.warning(
                    f"Fallback missing paragraph. paragraph id: {paragraph.debug_id}"
                )
                ptc = self.calc_token_count(paragraph.unicode)
                executor.submit(
                    self.il_translator.translate_paragraph,
                    paragraph,
                    batch_paragraph.pages[i],
                    pbar,
                    tracker,
                    page_font_map,
                    xobj_font_map,
                    priority=1048576 - ptc,
                    paragraph_token_count=ptc,
                    title_paragraph=title_paragraph,
                    local_title_paragraph=local_title_paragraph,
                )

        except Exception as e:
            error_message = f"Error {e} during translation. try fallback"
            logger.warning(error_message)
            for llm_translate_tracker in llm_translate_trackers:
                llm_translate_tracker.set_error_message(error_message)
                llm_translate_tracker.set_fallback_to_translate()
            self.total_count += len(llm_translate_trackers)
            self.fallback_count += len(llm_translate_trackers)
            for input_ in inputs:
                input_[2].unicode = input_[5]
            if not should_translate_paragraph:
                should_translate_paragraph = list(
                    range(len(batch_paragraph.paragraphs))
                )
            for i in should_translate_paragraph:
                paragraph = batch_paragraph.paragraphs[i]
                tracker = batch_paragraph.trackers[i]
                if paragraph.debug_id is None:
                    continue
                paragraph_token_count = self.calc_token_count(paragraph.unicode)
                executor.submit(
                    self.il_translator.translate_paragraph,
                    paragraph,
                    batch_paragraph.pages[i],
                    pbar,
                    tracker,
                    page_font_map,
                    xobj_font_map,
                    priority=1048576 - paragraph_token_count,
                    paragraph_token_count=paragraph_token_count,
                    title_paragraph=title_paragraph,
                    local_title_paragraph=local_title_paragraph,
                )


# ---------------------------------------------------------------------------
# P4：富文本占位符阈值（复制自 babeldoc 0.6.4 ILTranslator.get_translate_input，
# 仅修改：占位符阈值 40 -> 120）
# ---------------------------------------------------------------------------

def _get_translate_input_patched(
        self,
        paragraph: PdfParagraph,
        page_font_map: dict[str, PdfFont] = None,
        disable_rich_text_translate: bool | None = None,
    ):
        if not paragraph.pdf_paragraph_composition:
            return

        # Skip pure numeric paragraphs
        if is_pure_numeric_paragraph(paragraph):
            return None

        # Skip paragraphs with only placeholders
        if is_placeholder_only_paragraph(paragraph):
            return None

        # Extract original placeholder-like tokens from the raw paragraph text
        original_placeholder_tokens: dict[str, int] = {}

        def scan_placeholder_tokens(text: str, tokens: dict[str, int]):
            for pattern in (
                self._formula_placeholder_pattern,
                self._style_left_placeholder_pattern,
                self._style_right_placeholder_pattern,
            ):
                for match in pattern.finditer(text):
                    token = match.group(0)
                    tokens[token] = tokens.get(token, 0) + 1

        if paragraph.unicode:
            scan_placeholder_tokens(paragraph.unicode, original_placeholder_tokens)
        if len(paragraph.pdf_paragraph_composition) == 1:
            # 如果整个段落只有一个组成部分，那么直接返回，不需要套占位符等
            composition = paragraph.pdf_paragraph_composition[0]
            if (
                composition.pdf_line
                or composition.pdf_same_style_characters
                or composition.pdf_character
            ):
                translate_input = self.TranslateInput(
                    paragraph.unicode,
                    [],
                    paragraph.pdf_style,
                )
                translate_input.set_original_placeholder_tokens(
                    original_placeholder_tokens,
                )
                return translate_input
            elif composition.pdf_formula:
                # 不需要翻译纯公式
                return None
            elif composition.pdf_same_style_unicode_characters:
                # DEBUG INSERT CHAR, NOT TRANSLATE
                return None
            else:
                logger.error(
                    f"Unknown composition type. "
                    f"Composition: {composition}. "
                    f"Paragraph: {paragraph}. ",
                )
                return None

        # 如果没有指定 disable_rich_text_translate，使用配置中的值
        if disable_rich_text_translate is None:
            disable_rich_text_translate = (
                self.translation_config.disable_rich_text_translate
            )

        placeholder_id = 1
        placeholders = []
        chars = []
        for composition in paragraph.pdf_paragraph_composition:
            if composition.pdf_line:
                chars.extend(composition.pdf_line.pdf_character)
            elif composition.pdf_formula:
                formula_placeholder = self.create_formula_placeholder(
                    composition.pdf_formula,
                    placeholder_id,
                    paragraph,
                )
                placeholders.append(formula_placeholder)
                # 公式只需要一个占位符，所以 id+1
                placeholder_id = formula_placeholder.id + 1
                chars.extend(formula_placeholder.placeholder)
            elif composition.pdf_character:
                chars.append(composition.pdf_character)
            elif composition.pdf_same_style_characters:
                if disable_rich_text_translate:
                    # 如果禁用富文本翻译，直接添加字符
                    chars.extend(composition.pdf_same_style_characters.pdf_character)
                    continue

                fonta = self.font_mapper.map(
                    page_font_map[
                        composition.pdf_same_style_characters.pdf_style.font_id
                    ],
                    "1",
                )
                fontb = self.font_mapper.map(
                    page_font_map[paragraph.pdf_style.font_id],
                    "1",
                )
                if (
                    # 样式和段落基准样式一致，无需占位符
                    is_same_style(
                        composition.pdf_same_style_characters.pdf_style,
                        paragraph.pdf_style,
                    )
                    # 字号差异在 0.7-1.3 之间，可能是首字母变大效果，无需占位符
                    or is_same_style_except_size(
                        composition.pdf_same_style_characters.pdf_style,
                        paragraph.pdf_style,
                    )
                    or (
                        # 除了字体以外样式都和基准一样，并且字体都映射到同一个字体。无需占位符
                        is_same_style_except_font(
                            composition.pdf_same_style_characters.pdf_style,
                            paragraph.pdf_style,
                        )
                        and fonta
                        and fontb
                        and fonta.font_id == fontb.font_id
                    )
                    # or len(composition.pdf_same_style_characters.pdf_character) == 1
                ):
                    chars.extend(composition.pdf_same_style_characters.pdf_character)
                    continue
                placeholder = self.create_rich_text_placeholder(
                    composition.pdf_same_style_characters,
                    placeholder_id,
                    paragraph,
                )
                placeholders.append(placeholder)
                # 样式需要一左一右两个占位符，所以 id+2
                placeholder_id = placeholder.id + 2
                chars.append(placeholder.left_placeholder)
                chars.extend(composition.pdf_same_style_characters.pdf_character)
                chars.append(placeholder.right_placeholder)
            else:
                logger.error(
                    "Unexpected PdfParagraphComposition type "
                    "in PdfParagraph during translation. "
                    f"Composition: {composition}. "
                    f"Paragraph: {paragraph}. ",
                )
                return None

            # 如果占位符数量超过阈值，且未禁用富文本翻译，则递归调用并禁用富文本翻译
            if len(placeholders) > 120 and not disable_rich_text_translate:
                logger.warning(
                    f"Too many placeholders ({len(placeholders)}) in paragraph[{paragraph.debug_id}], "
                    "disabling rich text translation for this paragraph",
                )
                return self.get_translate_input(paragraph, page_font_map, True)

        text = get_char_unicode_string(chars)
        translate_input = self.TranslateInput(text, placeholders, paragraph.pdf_style)
        translate_input.set_original_placeholder_tokens(original_placeholder_tokens)
        return translate_input

