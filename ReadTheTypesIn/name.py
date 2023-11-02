from typing import Self
from dataclasses import dataclass
from functools import cache
import binaryninja as bn
from binaryninja.enums import StructureVariant
import demurr

TAG_TO_VARIANT = {
    demurr.TagKind.Class: StructureVariant.ClassStructureType,
    demurr.TagKind.Struct: StructureVariant.StructStructureType,
    demurr.TagKind.Union: StructureVariant.UnionStructureType,
}
VARIANT_TO_STR = {
    StructureVariant.ClassStructureType: "class",
    StructureVariant.StructStructureType: "struct",
    StructureVariant.UnionStructureType: "union",
}

@dataclass(frozen=True)
class TypeName:
    variant: StructureVariant
    name: bn.QualifiedName

    @staticmethod
    @cache
    def create_component(view: bn.BinaryView, name: tuple):
        if len(name) == 1:
            parent = view.root_component
        else:
            parent = TypeName.create_component(view, name[:-1])

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

    def get_component(self, view: bn.BinaryView):
        return TypeName.create_component(view, tuple(self.name.name))

    def __str__(self):
        return VARIANT_TO_STR[self.variant] + " " + str(self.name)

    @staticmethod
    @cache
    def parse_from_msvc_type_descriptor_name(name: str) -> Self:
        demangler = demurr.Demangler()
        symbol = demangler.parse(name)
        if symbol is None or demangler.error:
            raise ValueError()

        if not isinstance(symbol, demurr.VariableSymbolNode):
            raise ValueError()

        assert symbol.kind == demurr.NodeKind.VariableSymbol

        if not isinstance(tag_type := symbol.type, demurr.TagTypeNode):
            raise ValueError()

        assert tag_type.kind == demurr.NodeKind.TagType

        return TypeName(
            TAG_TO_VARIANT[tag_type.tag],
            bn.QualifiedName([
                str(component)
                for component in tag_type.qualified_name.components
            ]),
        )
