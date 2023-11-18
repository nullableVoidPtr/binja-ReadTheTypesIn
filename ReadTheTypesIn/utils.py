from functools import cache
from typing import Generator
import binaryninja as bn

def get_data_sections(view: bn.BinaryView) -> Generator[bn.Section, None, None]:
    for section in view.sections.values():
        if section.semantics not in [
            bn.SectionSemantics.ReadOnlyDataSectionSemantics,
            bn.SectionSemantics.ReadWriteDataSectionSemantics,
        ]:
            continue

        yield section

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

    view.add_function(address, auto_discovered=True)
    return view.get_recent_function_at(address)

@cache
def get_component(view: bn.BinaryView, name: tuple[str]):
    if len(name) == 1:
        parent = view.root_component
        if name[0].startswith("<lambda_"):
            parent = get_component(view, ("Anonymous Lambdas",))
    else:
        parent = get_component(view, name[:-1])

    component = next(
        (
            component
            for component in parent.components
            if component.display_name == name[-1]
        ),
        None,
    ) or view.create_component("::".join(name), parent)
    component.name = name[-1]

    return component
