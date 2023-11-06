from typing import Optional
from collections import defaultdict
from dataclasses import dataclass
import binaryninja as bn
from ..types import RelativeOffsetRenderer, EnumRenderer, RelativeOffsetListener
from .structs.rtti.type_descriptor import TypeDescriptor
from .structs.rtti.base_class_descriptor import \
    BaseClassDescriptor, BaseClassArray
from .structs.rtti.class_hierarchy_descriptor import ClassHierarchyDescriptor
from .structs.rtti.complete_object_locator import CompleteObjectLocator
from .structs.virtual_function_table import VirtualFunctionTable
from .structs.eh.catchable_type import CatchableType, CatchableTypeArray
from .structs.eh.throw_info import ThrowInfo
from .structs.eh.func_info import FuncInfo
from .class_info import VisualCxxBaseClass, VisualCxxClass

def register_renderers():
    RelativeOffsetRenderer().register_type_specific()
    EnumRenderer().register_type_specific()

# TODO: refactor this to allow start from any phase (i.e. from saved file, or manually defined)
def search_rtti(view: bn.BinaryView, task: Optional[bn.BackgroundTask] = None):
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

    classes = {
        chd: VisualCxxClass(chd) for chd in ClassHierarchyDescriptor.get_instances(view)
    }

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
        bn.log.log_warn(f"{repr(col)} unreferenced")

    for vftable in virtual_function_tables:
        classes[vftable.meta.class_hierarchy_descriptor].add_vftable(vftable)

    return list(classes.values())

def search_eh(
    view: bn.BinaryView,
    task: Optional[bn.BackgroundTask] = None,
):
    catchable_types = list(CatchableType.search_with_type_descriptors(
        view,
        TypeDescriptor.get_instances(view),
        task,
    ))

    if task is not None:
        task.progress = 'Marking down catchable types'
    for ct in catchable_types:
        ct.mark_down()

    catchable_type_arrays = list(CatchableTypeArray.search(
        view,
        catchable_types,
        task
    ))

    if task is not None:
        task.progress = 'Marking down catchable type arrays'
    for cta in catchable_type_arrays:
        cta.mark_down()

    throw_infos = list(ThrowInfo.search_with_catchable_type_arrays(
        view,
        catchable_type_arrays,
        task
    ))

    if task is not None:
        task.progress = 'Marking down throw infos'
    for throw_info in throw_infos:
        throw_info.mark_down()

    func_infos = list(FuncInfo.search(
        view,
        task
    ))

    if task is not None:
        task.progress = 'Marking down func infos'
    for func_info in func_infos:
        func_info.mark_down()

    return (throw_infos, func_infos)

def search_new_and_delete(
    view: bn.BinaryView
):
    potential_operator_news = view.get_functions_by_name('operator new')
    potential_operator_deletes = view.get_functions_by_name('operator delete')
    if len(potential_operator_news) == 0:
        raise ValueError("Cannot find `operator new'")
    if len(potential_operator_deletes) == 0:
        raise ValueError("Cannot find `operator delete'")

    return potential_operator_news, potential_operator_deletes

def search_structors(
    view: bn.BinaryView,
    classes: list[VisualCxxClass],
    task: Optional[bn.BackgroundTask]
):
    if task is not None:
        task.progress = 'Identifying structors'

    vftable_refs_mapping = {
        ref: vft
        for cls in classes
        for vft in cls.base_vftables.values()
        for ref in view.get_code_refs(vft.address)
    }

    operator_news, operator_deletes = search_new_and_delete(view)

    virtual_method_mapping = {
        method: (cls, offsets)
        for cls in classes
        for offsets, vft in cls.base_vftables.items()
        for address in vft.method_addresses
        if (method := view.get_function_at(address)) is not None
    }

    functions_to_refs = defaultdict(list)
    for ref, vft in vftable_refs_mapping.items():
        functions_to_refs[ref.function].append(ref)

    # TODO(WPO) map, from functions_to_refs, potential_direct_structors to their this arg
    constructors = {}
    for function, refs in functions_to_refs.items():
        if function in virtual_method_mapping:
            continue

        potential_sizes = []
        for site in function.caller_sites:
            if not any(new in site.function.callees for new in operator_news):
                continue

            constructor_call = site.hlil
            if isinstance(constructor_call, bn.HighLevelILAssign):
                constructor_call = constructor_call.src

            if not isinstance(constructor_call, bn.HighLevelILCall):
                continue

            if len(constructor_call.params) == 0:
                continue

            # TODO(WPO) replace with this arg idx
            this_arg = constructor_call.params[0]
            if not isinstance(this_arg, bn.HighLevelILVar):
                continue

            defs = constructor_call.function.get_var_definitions(this_arg.var)
            if len(defs) != 1:
                continue

            init = defs[0]
            call = None
            if isinstance(init, bn.HighLevelILVarInit):
                call = init.src

            if not isinstance(call, bn.Call):
                continue

            callee = call.dest
            if not isinstance(callee, bn.HighLevelILConstPtr):
                continue

            callee_ptr = callee.constant
            if view.get_function_at(callee_ptr) not in operator_news:
                continue

            size = call.params[0]
            if not isinstance(size, bn.HighLevelILConst):
                continue

            potential_sizes.append(size.constant)

        if len(potential_sizes) == 0:
            continue

        if not all(
            size == potential_sizes[0]
            for size in potential_sizes
        ):
            continue

        # TODO identify target class via last assignment to `this` ptr

        constructors[function] = True

    for func in constructors:
        # TODO attribute vftable
        func.add_tag("Potential constructors (RTTI)", "unk")

    return constructors

def search(view: bn.BinaryView, task: Optional[bn.BackgroundTask] = None):
    view.register_notification(RelativeOffsetListener())

    with view.undoable_transaction():
        view.create_tag_type("Potential constructors (RTTI)", "🏗️")
        view.create_tag_type("Potential destructors (RTTI)", "💥")

        classes = search_rtti(view, task)
        print(f"{len(classes)} classes identified")
        throw_infos, func_infos = search_eh(view, task)
        print(f"{len(throw_infos)} exceptions identified")
        print(f"{len(func_infos)} FuncInfos identified")

    resolved_classes = VisualCxxClass.structure(classes, task)
    with view.undoable_transaction():
        # TODO TEMPORARY
        for cls in classes:
            for vft in cls.base_vftables.values():
                if task is not None:
                    task.progress = f"Marking down {vft.address} for {cls}"
                address = vft.address - view.address_size
                view.define_user_data_var(address, vft.type, vft.name())

        constructors = search_structors(view, classes, task)
        print(f"{len(constructors)} constructors identified")

__all__ = [
    'TypeDescriptor',
    'BaseClassDescriptor',
    'BaseClassArray',
    'ClassHierarchyDescriptor',
    'CompleteObjectLocator',
    'search',
]
