"""Prove a bijection from immutable parent DOCX objects to a formatted child.

No PDF position participates. Any changed object layout or paragraph text
withholds inheritance, including an apparently equal object ID.
"""
from __future__ import annotations
from .feedback_store import FeedbackError
from .preview import _sha256


def rebase_mapping(versions, indexes, task_id, source_version_id, target_version_id):
    source = versions.artifact_path(task_id, source_version_id, "docx")
    target = versions.artifact_path(task_id, target_version_id, "docx")
    source_hash = versions.get_version(task_id, source_version_id).docx_sha256
    target_hash = versions.get_version(task_id, target_version_id).docx_sha256
    old_semantic, new_semantic = indexes.semantic(source), indexes.semantic(target)
    old_text, new_text = indexes.docx(source), indexes.docx(target)
    if (old_semantic.sha256 != source_hash or old_text.sha256 != source_hash or
            new_semantic.sha256 != target_hash or new_text.sha256 != target_hash or
            _sha256(source) != source_hash or _sha256(target) != target_hash):
        raise FeedbackError("stale_base_version", "继承定位时原版本文件发生变化。")
    old = {(o.part, o.xml_path, o.kind): o for o in old_semantic.objects}
    new = {(o.part, o.xml_path, o.kind): o for o in new_semantic.objects}
    if len(old) != len(old_semantic.objects) or len(new) != len(new_semantic.objects) or old.keys() != new.keys():
        return None
    before = {p.object_id: p for p in old_text.paragraphs}
    after = {p.object_id: p for p in new_text.paragraphs}
    mapping = {}
    for key, obj in old.items():
        current = new[key]
        if obj.requires_manual_targeting != current.requires_manual_targeting:
            return None
        if obj.kind == "paragraph":
            a, b = before.get(obj.object_id), after.get(current.object_id)
            if a is None or b is None or (a.text, a.story_id, a.editable) != (b.text, b.story_id, b.editable):
                return None
        mapping[obj.object_id] = current.object_id
    return mapping
