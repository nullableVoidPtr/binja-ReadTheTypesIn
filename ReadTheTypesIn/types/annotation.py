from typing import Optional, Any, Union, get_origin, get_args
from types import GenericAlias
import binaryninja as bn

class Array():
    @classmethod
    def get_element_type(cls, type_spec) -> Optional['MemberTypeSpec']:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return args[0]

    @classmethod
    def get_size(cls, type_spec) -> Optional['MemberTypeSpec']:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        if len(args) < 2 or args[1] is Ellipsis:
            return None

        return args[1]

    @classmethod
    def is_flexible(cls, type_spec) -> bool:
        if cls.get_element_type(type_spec) is None:
            return False

        return cls.get_size(type_spec) is None

    @classmethod
    def __class_getitem__(cls, key: Union['MemberTypeSpec', tuple['MemberTypeSpec', Any]]):
        if not isinstance(key, tuple):
            key = (key,)
        return GenericAlias(cls, key)

class Enum():
    @classmethod
    def get_type(cls, type_spec) -> Optional['MemberTypeSpec']:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return args[0]

    @classmethod
    def get_raw_type(cls, type_spec) -> Optional['MemberTypeSpec']:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return 'unsigned int' if len(args) < 2 else args[1]

    @classmethod
    def __class_getitem__(cls, key: Union['MemberTypeSpec', tuple['MemberTypeSpec', Any]]):
        if not isinstance(key, tuple):
            key = (key,)
        return GenericAlias(cls, key)

class OffsetType():
    @staticmethod
    def get_origin(type_spec) -> type:
        origin = get_origin(type_spec)
        if not isinstance(origin, type) or not issubclass(origin, OffsetType):
            return None

        return origin

    @classmethod
    def get_target(cls, type_spec) -> Optional['MemberTypeSpec']:
        origin = cls.get_origin(type_spec)
        if origin is None:
            return None

        args = get_args(type_spec)
        assert args is not None
        return args[0]

    @classmethod
    def get_typedef_ref(view: bn.BinaryView):
        pass

    @classmethod
    def get_relative_type(cls, type_spec) -> Optional['MemberTypeSpec']:
        origin = cls.get_origin(type_spec)
        if origin is None:
            return None

        args = get_args(type_spec)
        assert args is not None
        return 'int' if len(args) < 2 else args[1]

    @classmethod
    def __class_getitem__(cls, key: Any):
        return GenericAlias(cls, (key,))

    @staticmethod
    def is_relative(view: bn.BinaryView):
        return True

    @classmethod
    def encode_offset(cls, view: bn.BinaryView, address: int) -> int:
        if cls.is_relative(view):
            return address - view.start

        return address

    @classmethod
    def resolve_offset(cls, view: bn.BinaryView, offset: int) -> int:
        if cls.is_relative(view):
            return view.start + offset

        return offset

class RTTIOffsetType(OffsetType):
    @staticmethod
    def is_relative(view: bn.BinaryView):
        if view.arch.name == 'x86_64':
            return True

        return False

class EHOffsetType(OffsetType):
    @staticmethod
    def is_relative(view: bn.BinaryView):
        if view.arch.name == 'x86_64':
            return True

        return False

class NamedCheckedTypeRef():
    @classmethod
    def get_target(cls, type_spec) -> Optional[str]:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        target = args[0]
        assert isinstance(target, str)
        return target

    @classmethod
    def get_ref(cls, type_spec) -> bn.NamedTypeReferenceType:
        if (target := cls.get_target(type_spec)) is None:
            return None

        return bn.Type.named_type_reference(
            bn.NamedTypeReferenceClass.TypedefNamedTypeClass,
            target
        )

    @classmethod
    def resolve(cls, type_spec) -> Optional[type['CheckedTypeDataVar']]:
        from .var import CheckedTypeDataVar

        if (target := cls.get_target(type_spec)) is None:
            return None

        for scls in CheckedTypeDataVar.__subclasses__():
            if scls.name == target:
                return scls

        return None

    @classmethod
    def __class_getitem__(cls, key: str):
        return GenericAlias(cls, (key,))
