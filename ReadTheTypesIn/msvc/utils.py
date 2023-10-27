from typing import Generator
import binaryninja as bn

def uses_relative_rtti(view: bn.BinaryView):
    if view.arch.name == 'x86_64':
        return True

    return False

def get_data_sections(view: bn.BinaryView) -> Generator[bn.Section, None, None]:
    for section in view.sections.values():
        if section.semantics not in [
            bn.SectionSemantics.ReadOnlyDataSectionSemantics,
            bn.SectionSemantics.ReadWriteDataSectionSemantics,
        ]:
            continue

        yield section

def encode_rtti_offset(view: bn.BinaryView, address: int) -> int:
    if uses_relative_rtti(view):
        return address - view.start

    return address

def resolve_rtti_offset(view: bn.BinaryView, offset: int) -> int:
    if uses_relative_rtti(view):
        return view.start + offset

    return offset

def get_function(view: bn.BinaryView, address: int):
    if not any(
        section.semantics == bn.SectionSemantics.ReadOnlyCodeSectionSemantics
        for section in view.get_sections_at(address)
    ):
        return None

    if (func := view.get_function_at(address)) is not None:
        return func

    if view.get_data_var_at(address) is not None:
        return None

    return view.create_user_function(address)
