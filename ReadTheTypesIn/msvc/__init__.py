from typing import Optional
from collections import defaultdict
import binaryninja as bn
from ..types import RelativeOffsetRenderer, RelativeOffsetListener
from .structs.type_descriptor import TypeDescriptor, TypeDescriptorRenderer
from .structs.base_class_descriptor import BaseClassDescriptor, BaseClassArray, BaseClassArrayRenderer, BaseClassArrayListener
from .structs.class_hierarchy_descriptor import ClassHierarchyDescriptor
from .structs.complete_object_locator import CompleteObjectLocator
from .structs.virtual_function_table import VirtualFunctionTable
from .class_info import VisualCxxClass

def register_renderers():
    TypeDescriptorRenderer().register_type_specific()
    BaseClassArrayRenderer().register_type_specific()
    RelativeOffsetRenderer().register_type_specific()

def search(view: bn.BinaryView, task: Optional[bn.BackgroundTask] = None):
    view.register_notification(RelativeOffsetListener())
    # ???
    # view.register_notification(msvc.BaseClassArrayListener())
    type_descs = list(TypeDescriptor.search(view, task=task))
    complete_object_locators = list(
        CompleteObjectLocator.search_with_type_descriptors(
            view,
            type_descs,
            task=task,
        )
    )

    if task is not None:
        task.progress = 'Marking down complete object locators'
    for col in complete_object_locators:
        col.mark_down()

    undefined_type_descs = set(
        type_desc
        for type_desc in type_descs
        if not type_desc.defined
    ) - set(
        col.type_descriptor
        for col in complete_object_locators
    )

    if task is not None:
        task.progress = 'Marking down remaining type descriptors'
    for type_desc in undefined_type_descs:
        type_desc.mark_down()

    virtual_function_tables = list(VirtualFunctionTable.search_with_complete_object_locators(
        view,
        complete_object_locators,
        task=task
    ))

    referenced_cols = set(
        vft.meta
        for vft in virtual_function_tables
    )
    ureferenced_cols = set(complete_object_locators) - referenced_cols
    for col in ureferenced_cols:
        bn.log.log_warn(f"{repr(col)} left undefined")

    base_vftables: defaultdict[TypeDescriptor, list] = defaultdict(list)
    for vftable in virtual_function_tables:
        base_vftables[vftable.meta.type_descriptor].append(vftable)

    classes: list[VisualCxxClass] = [
        VisualCxxClass(type_desc, vftables)
        for type_desc, vftables in base_vftables.items()
    ]

    print(classes)
    return classes


__all__ = [
    'TypeDescriptor',
    'TypeDescriptorRenderer',
    'BaseClassDescriptor',
    'BaseClassArray',
    'BaseClassArrayRenderer',
    'BaseClassArrayListener',
    'ClassHierarchyDescriptor',
    'CompleteObjectLocator',
]
