from functools import cache
import binaryninja as bn
from .annotation import OffsetType, Enum, NamedCheckedTypeRef

MemberTypeSpec = str | bn.Type | type['CheckedTypeDataVar'] | type['RTTIOffsetType'] | type['Enum']

@cache
def resolve_type_spec(view: bn.BinaryView, type_spec: MemberTypeSpec) -> bn.Type:
    from .var import CheckedTypeDataVar
    from .typedef import CheckedTypedef

    if isinstance(type_spec, bn.Type):
        return type_spec

    if isinstance(type_spec, type) and issubclass(type_spec, (CheckedTypeDataVar, CheckedTypedef)):
        return type_spec.get_typedef_ref(view)

    if (ref := NamedCheckedTypeRef.get_ref(type_spec)) is not None:
        return ref

    if (offset_type := OffsetType.get_origin(type_spec)) is not None:    
        if (offset_target := offset_type.get_target(type_spec)) is not None:
            ptr_type = bn.Type.pointer(view.arch, resolve_type_spec(view, offset_target))
            return ptr_type if not offset_type.is_relative(view) else resolve_type_spec(
                view,
                offset_type.get_relative_type(type_spec)
            )

    if (enum_type := Enum.get_raw_type(type_spec)) is not None:
        return resolve_type_spec(view, enum_type)

    assert isinstance(type_spec, str), f'Incorrect type spec {type_spec} ({type(type_spec)})'
    return view.parse_type_string(type_spec)[0]
