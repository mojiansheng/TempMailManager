"""极简 xlsx 写出器（仅标准库），用于生成导入模板。

只写一个工作表、纯文本单元格，采用 inlineStr 形式，因此不需要
sharedStrings 与 styles，文件结构最小：

    [Content_Types].xml
    _rels/.rels
    xl/workbook.xml
    xl/_rels/workbook.xml.rels
    xl/worksheets/sheet1.xml

生成的模板能被 Excel / WPS / 本项目的 xlsx_reader 正常打开。
"""

import io
import zipfile
from typing import Iterable, List, Sequence
from xml.sax.saxutils import escape

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""


def _col_letter(index: int) -> str:
    """0 → A, 1 → B, 26 → AA"""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _workbook_xml(sheet_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""


def _sheet_xml(rows: Sequence[Sequence[str]], widths: Sequence[int]) -> str:
    cols = ""
    if widths:
        parts = "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths)
        )
        cols = f"<cols>{parts}</cols>"

    body: List[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row):
            text = "" if value is None else str(value)
            if text == "":
                continue
            ref = f"{_col_letter(col_index)}{row_index}"
            cells.append(
                f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">'
                f"{escape(text)}</t></is></c>"
            )
        body.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{cols}<sheetData>{''.join(body)}</sheetData></worksheet>"
    )


def build_xlsx(rows: Iterable[Sequence[str]], sheet_name: str = "Sheet1",
               widths: Sequence[int] = ()) -> bytes:
    """把二维文本数组写成 xlsx 字节流。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("xl/workbook.xml", _workbook_xml(sheet_name))
        zf.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        zf.writestr("xl/worksheets/sheet1.xml", _sheet_xml(list(rows), widths))
    return buffer.getvalue()


# 模板内容：表头 + 3 个示例账户，与文本导入格式保持一致。
# 注意：示例 uuid 必须是不存在的假值，避免用户照抄模板把真实邮箱导进来。
TEMPLATE_ROWS = [
    ["UUID", "助记词"],
    ["6f1b9d24-3a7e-4c58-9b02-8e4d17ac5f63",
     "over bulk slice alert dove uncle sketch weekend orphan online balcony fly"],
    ["2d8c40f7-91b6-4a3e-8c75-5f0e62b9d418",
     "degree hurry alert access faint assault adjust october marine figure flat luggage"],
    ["b4e72a58-06d3-4f19-a8c6-31d95e7f20ab",
     "success awful alcohol gossip recipe give fetch bracket brand calm trend ethics"],
]


def template_bytes() -> bytes:
    return build_xlsx(TEMPLATE_ROWS, sheet_name="账户导入模板", widths=(40, 80))
