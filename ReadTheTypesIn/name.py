import binaryninja as bn
from binaryninja.enums import StructureVariant
import demurr

class TypeName:
    TAG_TO_VARIANT = {
        demurr.TagKind.Class: StructureVariant.ClassStructureType, 
        demurr.TagKind.Struct: StructureVariant.StructStructureType, 
        demurr.TagKind.Union: StructureVariant.UnionStructureType, 
    }

    variant: StructureVariant
    name: bn.QualifiedName

    def __init__(self, variant: StructureVariant, name: bn.QualifiedName):
        self.variant = variant
        self.name = name

    @staticmethod
    def parse_from_msvc_type_descriptor_name(name: str) -> TypeName:
        demangler = demurr.Demangler()
        symbol = demangler.parse(name)
        if symbol is None or demangler.error:
            raise ValueError()
        
        if not isinstance(symbol, demurr.VariableSymbolNode):
            raise ValueError()
        
        assert symbol.kind is demurr.NodeKind.VariableSymbol

        if not isinstance(tag_type := symbol.type, demurr.TagTypeNode):
            raise ValueError()

        assert tag_type.kind is demurr.NodeKind.TagType

        return TypeName(
            TypeName.TAG_TO_VARIANT[type_tag.tag],
            [
                str(component)
                for component in tag_type.qualified_name.components
            ],
        )