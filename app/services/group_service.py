"""分组业务：多级树、防环、级联删除。"""

from typing import Any, Dict, List, Optional

from .. import store


class GroupError(Exception):
    pass


def list_groups() -> List[Dict[str, Any]]:
    return store.list_groups()


def create_group(name: str, parent_id: Optional[int] = None) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise GroupError("分组名称不能为空。")
    if len(name) > 50:
        raise GroupError("分组名称不能超过 50 个字符。")
    if parent_id is not None and not store.get_group(parent_id):
        raise GroupError("上级分组不存在。")
    return store.create_group(name, parent_id)


def update_group(group_id: int, name: Any = None, parent_id: Any = None,
                 has_parent: bool = False) -> Dict[str, Any]:
    group = store.get_group(group_id)
    if not group:
        raise GroupError("分组不存在。")

    clean_name = None
    if name is not None:
        clean_name = str(name).strip()
        if not clean_name:
            raise GroupError("分组名称不能为空。")
        if len(clean_name) > 50:
            raise GroupError("分组名称不能超过 50 个字符。")

    new_parent = None
    if has_parent:
        new_parent = None if parent_id in (None, "", 0) else int(parent_id)
        if new_parent is not None:
            if not store.get_group(new_parent):
                raise GroupError("上级分组不存在。")
            if new_parent in store.descendant_group_ids(group_id):
                raise GroupError("不能把分组移动到它自己或它的子分组下。")

    return store.update_group(group_id, name=clean_name, parent_id=new_parent,
                              set_parent=has_parent)


def delete_group(group_id: int) -> Dict[str, Any]:
    if not store.get_group(group_id):
        raise GroupError("分组不存在。")
    removed = store.delete_group(group_id)
    return {"removed_groups": len(removed), "ids": removed}
