"""极简 xlsx 读取器（仅标准库）。

xlsx 就是一个 zip 包：
  xl/workbook.xml          工作表清单（r:id 指向具体文件）
  xl/_rels/workbook.xml.rels   r:id → 路径
  xl/sharedStrings.xml     共享字符串表（t="s" 的单元格存的是下标）
  xl/worksheets/sheetN.xml 实际单元格

我们只需要「把每个单元格的文本读出来」，不关心样式、公式、合并单元格，
所以用 zipfile + ElementTree 几十行就够，避免引入 openpyxl 让打包变慢。
"""

import io
import re
import zipfile
from typing import Dict, List
from xml.etree import ElementTree as ET

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CELL_REF = re.compile(r"([A-Z]+)")


class XlsxError(Exception):
    pass


def _col_index(ref: str) -> int:
    """A1 → 0, B7 → 1, AA1 → 26"""
    match = _CELL_REF.match(ref or "")
    if not match:
        return 0
    index = 0
    for ch in match.group(1):
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _text_of(node) -> str:
    """拼接一个 <si>/<is> 下所有 <t> 的文本。"""
    return "".join(t.text or "" for t in node.iter(f"{_NS_MAIN}t"))


def _shared_strings(zf: zipfile.ZipFile) -> List[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise XlsxError(f"sharedStrings 解析失败：{exc}") from exc
    return [_text_of(si) for si in root.findall(f"{_NS_MAIN}si")]


def _first_sheet_path(zf: zipfile.ZipFile) -> str:
    """解析 workbook + rels，拿到第一个工作表在包内的路径。"""
    try:
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        # 没有标准结构就退化成扫描
        for name in zf.namelist():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                return name
        raise XlsxError("文件里没有工作表。")
    except ET.ParseError as exc:
        raise XlsxError(f"workbook.xml 解析失败：{exc}") from exc

    rel_map: Dict[str, str] = {}
    for rel in rels.findall(f"{_NS_PKG_REL}Relationship"):
        rel_map[rel.get("Id", "")] = rel.get("Target", "")

    sheets = workbook.find(f"{_NS_MAIN}sheets")
    sheet = None
    if sheets is not None:
        sheet = sheets.find(f"{_NS_MAIN}sheet")
    if sheet is None:
        raise XlsxError("文件里没有工作表。")

    target = rel_map.get(sheet.get(f"{_NS_REL}id", ""), "")
    if not target:
        raise XlsxError("无法定位工作表文件。")
    target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = "xl/" + target.lstrip("./")
    if target not in zf.namelist():
        raise XlsxError("工作表文件缺失。")
    return target


def read_rows(data: bytes) -> List[List[str]]:
    """读取第一个工作表的全部行，返回 [[单元格文本, ...], ...]。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("不是有效的 xlsx 文件（可能是老的 .xls，请另存为 xlsx）。") from exc

    with zf:
        shared = _shared_strings(zf)
        path = _first_sheet_path(zf)
        try:
            raw = zf.read(path)
        except KeyError as exc:
            raise XlsxError("读取工作表失败。") from exc

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise XlsxError(f"工作表解析失败：{exc}") from exc

    rows: List[List[str]] = []
    for row_node in root.iter(f"{_NS_MAIN}row"):
        cells: Dict[int, str] = {}
        for cell in row_node.findall(f"{_NS_MAIN}c"):
            idx = _col_index(cell.get("r", ""))
            kind = cell.get("t", "n")
            if kind == "inlineStr":
                node = cell.find(f"{_NS_MAIN}is")
                value = _text_of(node) if node is not None else ""
            else:
                node = cell.find(f"{_NS_MAIN}v")
                value = node.text if node is not None and node.text else ""
                if kind == "s" and value.isdigit():
                    pos = int(value)
                    value = shared[pos] if pos < len(shared) else ""
            value = (value or "").strip()
            if value:
                cells[idx] = value
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
    return rows
