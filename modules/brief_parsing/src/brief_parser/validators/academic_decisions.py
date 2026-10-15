"""Validate explicit formatting answers; never interpret raw user text as code."""

from brief_parser.domain.academic_format import finite_value


ROLES = {"body", "abstract", "abstract_heading", "keywords", "toc", "toc_heading", "heading", "bibliography",
         "bibliography_heading", "acknowledgements", "appendix", "footnote", "endnote", "header", "footer",
         "page", "page_number", "table", "table_header", "table_body", "table_caption", "figure_text",
         "figure_caption", "citation", "latin_text", "latin_digits", "document_text"}
ROLES.update(f"{prefix}{level}" for prefix in ("heading_", "toc_heading_") for level in range(1, 10))
ENUMS = {"paragraph.alignment": {"left", "center", "right", "both"},
         "page.orientation": {"portrait", "landscape"}, "page.paper_size": {"A4", "A3", "A5", "Letter"},
         "page_number.number_format": {"arabic", "lower_roman", "upper_roman"},
         "section.text_direction": {"horizontal", "vertical"},
         "table.border_style": {"three_line", "all_borders", "none"},
         "caption.position": {"above", "below"}, "document.position": {"after_body", "before_body", "document_end"}}
BOOLEANS = {"font.bold", "font.italic", "paragraph.keep_with_next", "paragraph.keep_together", "paragraph.page_break_before", "paragraph.snap_to_grid"}
LENGTHS = {"paragraph.spacing_before", "paragraph.spacing_after", "paragraph.first_line_indent", "paragraph.hanging_indent",
           "paragraph.left_indent", "paragraph.right_indent", "page.margin.all", "page.margin.top", "page.margin.bottom",
           "page.margin.left", "page.margin.right", "page.margin.header_distance", "page.margin.footer_distance", "page.margin.gutter"}
INTEGERS = {"toc.max_depth", "section.column_count", "page_number.start"}


def typed_property(prop):
    return prop in ENUMS or prop in BOOLEANS or prop in LENGTHS or prop in INTEGERS or prop in {"font.family", "font.size", "paragraph.line_spacing", "page.dimensions"}


def validate_answer_scope(scope):
    """Only registered, explicit applicability axes can be supplied by a user."""
    choices = {"roles": ROLES | {"table_cell"}, "characters": {"chinese", "latin", "digits", "complex_script", "other"},
               "object_language": {"chinese", "english"}, "region_zone": {"front_matter", "body"},
               "regions": {"front_matter", "body", "abstract", "toc", "bibliography", "appendix", "acknowledgements"},
               "property_component": {"top", "bottom", "left", "right"}}
    for name, axis in scope.axes.items():
        values = (axis.include or []) + axis.exclude
        if name in {"chapter", "object_ordinal"}:
            valid = all(value.isascii() and value.isdigit() and int(value) > 0 for value in values)
        else:
            valid = name in choices and set(values) <= choices.get(name, set())
        if not valid:
            raise ValueError("用户提供的范围包含未注册的轴或取值。")


def validate_format_value(prop, value, unit):
    if not finite_value(value):
        raise ValueError("格式值必须是有限数值。")
    numeric = isinstance(value, (float, int)) and not isinstance(value, bool)
    if prop in ENUMS:
        valid = isinstance(value, str) and value in ENUMS[prop] and unit is None
    elif prop in BOOLEANS:
        valid = isinstance(value, bool) and unit is None
    elif prop == "font.family":
        valid = isinstance(value, str) and 0 < len(value.strip()) <= 100 and not any(char in value for char in "\r\n\x00") and unit is None
    elif prop == "font.size":
        valid = numeric and value > 0 and unit == "pt"
    elif prop in LENGTHS:
        valid = numeric and value >= 0 and unit in {"pt", "cm", "mm"}
        if prop in {"paragraph.spacing_before", "paragraph.spacing_after"}:
            valid = valid or numeric and value >= 0 and unit in {"lines", "characters"}
        if "indent" in prop:
            valid = valid or numeric and value >= 0 and unit == "characters"
    elif prop in INTEGERS:
        valid = isinstance(value, int) and not isinstance(value, bool) and value >= (0 if prop == "page_number.start" else 1) and unit is None
    elif prop == "paragraph.line_spacing":
        valid = numeric and value > 0 and unit == "multiple"
        valid = valid or (isinstance(value, dict) and set(value) == {"mode", "amount"} and value["mode"] in {"exact", "atLeast"}
                         and isinstance(value["amount"], (int, float)) and not isinstance(value["amount"], bool) and value["amount"] > 0 and unit == "pt")
    elif prop == "page.dimensions":
        valid = (isinstance(value, dict) and set(value) == {"width_cm", "height_cm"} and unit == "cm"
                 and all(isinstance(item, (int, float)) and not isinstance(item, bool) and item > 0 for item in value.values()))
    else:
        raise ValueError("该属性没有已注册的格式回答校验器；不能生成可执行规则。")
    if not valid:
        raise ValueError("格式值或单位不符合该属性的类型。")
