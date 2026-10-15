"""Versioned spelling aliases. They normalize text, never supply missing values."""

from __future__ import annotations

import re


ROLE_ALIASES = (
    (r"\btable\s+(?:body|text)\b", "表内文字"),
    (r"\b(?:main|body)\s+text\b|\bbody\b", "正文"),
    (r"\bChinese\s+abstract\b", "中文摘要"),
    (r"\bEnglish\s+abstract\b", "英文摘要"),
    (r"\babstract\s+heading\b", "摘要标题"),
    (r"\babstract\b", "摘要"),
    (r"\bkeywords?\b", "关键词"),
    (r"\btable\s+of\s+contents\b|\bTOC\b", "目录"),
    (r"\b(?:bibliography|references)\s+heading\b", "参考文献标题"),
    (r"\b(?:bibliography|references)\b", "参考文献"),
    (r"\bfootnotes?\b", "脚注"), (r"\bendnotes?\b", "尾注"),
    (r"\btable\s+captions?\b", "表题"), (r"\bfigure\s+captions?\b", "图题"),
    (r"\btable\s+headers?\b", "表头文字"), (r"\btable\s+(?:body|text)\b", "表内文字"),
    (r"\btables?\b", "表格"), (r"\bpage\s+numbers?\b", "页码"),
    (r"\bheaders?\b", "页眉"), (r"\bfooters?\b", "页脚"),
    (r"\bpages?\b|\bpaper\b", "页面"),
    (r"\bwhole\s+document\b|\ball\s+text\b", "全文"),
    (r"\b(?:all|every)\s+headings?\b", "所有标题"),
    (r"\backnowledgements?\b", "致谢"), (r"\bappendi(?:x|ces)\b", "附录"),
)
VALUE_ALIASES = (
    (r"\b(?:do\s+not|must\s+not|shall\s+not)\b", "不得"),
    (r"\bfont\s+(?:family|name)\b|\btypeface\b", "字体"),
    (r"\bfont\s+size\b", "字号"), (r"\bfont\b", "字体"),
    (r"\b(?:not\s+bold|non[ -]bold|unbold)\b", "不加粗"), (r"\bbold\b", "加粗"),
    (r"\b(?:not\s+italic|non[ -]italic)\b", "不使用斜体"), (r"\bitalic\b", "斜体"),
    (r"\b(?:fully\s+)?justified\b|\bjustify\b", "两端对齐"),
    (r"\bcent(?:er|re)(?:ed)?(?:[ -]aligned)?\b", "居中"),
    (r"\bleft[ -]aligned\b|\balign\s+left\b", "左对齐"),
    (r"\bright[ -]aligned\b|\balign\s+right\b", "右对齐"),
    (r"\balignment\b", "对齐"),
    (r"\b(?:single[ -]spaced|single\s+spacing)\b", "1倍行距"),
    (r"\b(?:double[ -]spaced|double\s+spacing)\b", "2倍行距"),
    (r"\b(?:one[ -]and[ -]a[ -]half\s+spacing|1\.5[ -]spaced)\b", "1.5倍行距"),
    (r"\bline\s+spacing\b", "行距"),
    (r"\bfirst[ -]line\s+indent(?:ation)?\b", "首行缩进"),
    (r"\bhanging\s+indent(?:ation)?\b", "悬挂缩进"),
    (r"\bleft\s+indent(?:ation)?\b", "左缩进"), (r"\bright\s+indent(?:ation)?\b", "右缩进"),
    (r"\b(?:space|spacing)\s+before\b", "段前"), (r"\b(?:space|spacing)\s+after\b", "段后"),
    (r"\btop\s+margin\b", "上页边距"), (r"\bbottom\s+margin\b", "下页边距"),
    (r"\bleft\s+margin\b", "左页边距"), (r"\bright\s+margin\b", "右页边距"),
    (r"\b(?:page\s+)?margins?\b", "页边距"),
    (r"\b(?:paper\s+)?size\b", "纸张尺寸"), (r"\blandscape\b", "横向"), (r"\bportrait\b", "纵向"),
    (r"\bthree[ -]line\s+table\b", "三线表"), (r"\ball\s+borders\b", "全框线"), (r"\bno\s+borders\b", "无边框"),
    (r"\blower[ -]case\s+Roman(?:\s+numerals)?\b", "小写罗马数字"),
    (r"\bupper[ -]case\s+Roman(?:\s+numerals)?\b", "大写罗马数字"),
    (r"\bArabic(?:\s+numerals)?\b", "阿拉伯数字"),
    (r"\bpoints?\b", "pt"), (r"\bcharacters?\b", "字符"), (r"\blines?\b", "行"),
    (r"\b(?:must|shall)\b", "必须"), (r"\b(?:use|uses|using)\b", "使用"),
    (r"\b(?:set\s+to|is|are|equals?)\b|=", "为"),
    (r"\bor\b", "或"), (r"\b(?:recommended|preferably|may|should)\b", "建议"),
    (r"\b(?:if|when|unless)\b", "如果"),
    (r"\bat\s+least\b", "不小于"), (r"\bat\s+most\b|\bno\s+more\s+than\b", "不超过"),
    (r"\b(?:greater|more)\s+than\b", "大于"), (r"\bless\s+than\b", "小于"),
)


def normalize_expression(text: str) -> str:
    # A quoted font name is opaque: words such as "Body" in its name must
    # never become object labels or translated value tokens.
    quoted = []
    def protect(match):
        quoted.append(match.group())
        return f"\uE000{len(quoted) - 1}\uE001"
    text = re.sub(r'["“][^"”\r\n]+["”]|\x27[^\x27\r\n]+\x27', protect, text)
    text = re.sub(r"\bchapter\s+([1-9][0-9]*)\b", r"第\1章", text, flags=re.I)
    def level(match):
        number = int(match.group(1))
        return "一二三四五六七八九"[number - 1] + "级标题"
    for pattern in (r"\blevel\s*([1-9])\s+headings?\b", r"\bheadings?\s*([1-9])\b",
                    r"第?([1-9])级标题", r"标题\s*([1-9])(?=\s|[：:,，]|$)"):
        text = re.sub(pattern, level, text, flags=re.I)
    text = re.sub(r"第([一二三四五六七八九])级标题", r"\1级标题", text)
    for pattern, value in ROLE_ALIASES + VALUE_ALIASES:
        text = re.sub(pattern, value, text, flags=re.I)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"设置成|设定为|设置为|字体选用|选用", "使用", text)
    for index, quote in enumerate(quoted):
        text = text.replace(f"\uE000{index}\uE001", quote)
    return text


def canonical_font(value: str) -> str:
    aliases = {"times new roman": "Times New Roman", "arial": "Arial", "calibri": "Calibri",
               "cambria": "Cambria", "microsoft yahei": "Microsoft YaHei", "simsun": "宋体",
               "simhei": "黑体", "kaiti": "楷体", "fangsong": "仿宋"}
    return aliases.get(" ".join(value.split()).casefold(), value.strip())
