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
