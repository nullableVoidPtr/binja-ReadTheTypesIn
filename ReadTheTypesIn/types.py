from typing import (
    Optional,
    Mapping, Sequence,
    ClassVar, Self,
    TypeVar, Generic, get_origin, get_args
)
from functools import cache
from types import GenericAlias
import binaryninja as bn
from .name import TypeName
from .msvc.utils import uses_relative_rtti, resolve_rtti_offset

class CheckedTypeDataVar:
    name: ClassVar[str]
    alt_name: ClassVar[str]

    packed: ClassVar[bool]
    members: ClassVar[Sequence[tuple[bn.Type, str]]]
    relative_members: ClassVar[Mapping[str, bn.Type]]

    __instances__: ClassVar[Mapping]

    source: bn.TypedDataAccessor

    def __init_subclass__(
        cls,
        name=None, alt_name=None,
        alignment=None,
        members: list[tuple[bn.Type, str]] = None,
        packed=False,
        **kwargs
    ):
        cls.name = name or cls.__name__
        cls.alt_name = alt_name or f'_{cls.name}'

        assert members is not None, f"Members of {cls.name} must be specified"
        cls.packed = packed
        cls.members = members
        cls.relative_members = {
            name: target
            for mtype, name in cls.members
            if (target := RTTIOffsetType.get_target(mtype)) is not None
        }

        if getattr(cls, '__instances__', None) is None:
            cls.__instances__ = {}

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        if isinstance(source, bn.TypedDataAccessor):
            user_struct = self.get_user_struct(source.view)
            if source.type is not user_struct:
                raise TypeError(
                    f"Expected type of accessor to be {user_struct}, got {source.type}"
                )
        else:
            source = view.typed_data_accessor(
                source,
                self.get_user_struct(view),
            )

        self.source = source

    def __getitem__(self, key: str):
        member_source = self.source[key]

        target_type = next(
            (
                mtype
                for mtype, name in self.members
                if key == name
            )
        )

        if uses_relative_rtti(self.view) and key in self.relative_members:
            target_type = self.relative_members[key]
            if NamedCheckedTypeRef.get_target(target_type) is not None:
                if (resolved := NamedCheckedTypeRef.resolve(target_type)) is None:
                    raise TypeError(f'Cannot resolve {target_type}')

                target_type = resolved

            member_source = resolve_rtti_offset(
                self.view,
                member_source.value
            )

        if isinstance(target_type, type) and issubclass(target_type, CheckedTypeDataVar):
            if isinstance(member_source, bn.TypedDataAccessor) and member_source.type == target_type.get_typedef_ref(self.view):
                member_source = member_source.address

            return target_type.create(
                self.view,
                member_source,
            )

        if isinstance(member_source, int):
            member_source = self.view.typed_data_accessor(
                member_source,
                target_type,
            )

        return member_source

    def __repr__(self):
        suffix = '' if self.type_name is None else f': {self.type_name}'
        return f"<{self.__class__.__name__} 0x{self.address:x}{suffix}>"

    @property
    def view(self) -> bn.BinaryView:
        return self.source.view

    @property
    def type(self) -> bn.Type:
        return self.get_typedef_ref(self.view)

    @property
    def defined(self) -> bool:
        if (old_var := self.view.get_data_var_at(self.address)) is not None:
            if old_var.type != self.type:
                return False

            if self.symbol_name is not None and old_var.name != self.symbol_name:
                return False

            return True

        return False

    @property
    def type_name(self) -> Optional[str]:
        return None

    @property
    def symbol_name(self) -> Optional[str]:
        return None

    def mark_down(self):
        if not self.defined:
            try:
                self.view.define_user_data_var(
                    self.address,
                    self.type,
                    self.symbol_name,
                )
            except Exception as e:
                raise ValueError(
                    f"Failed to define {self.name} @ {self.address:x}"
                ) from e
        self.mark_down_members()

    def mark_down_members(self):
        for name in self.relative_members:
            member = self[name]
            if member.defined:
                continue

            try:
                member.mark_down()
            except Exception as e:
                raise ValueError(
                    f"Failed to define {self.name}.{name} @ {self[name].address:x}"
                ) from e

    @classmethod
    def create(cls, view: bn.BinaryView, source: bn.TypedDataAccessor | int, *args, **kwargs) -> Self:
        if isinstance(source, bn.TypedDataAccessor):
            address = source.address
        else:
            address = source

        if address in cls.__instances__:
            return cls.__instances__[address]

        obj = object.__new__(cls, view, source, *args, **kwargs)
        cls.__instances__[address] = obj
        try:
            obj.__init__(view, source, *args, **kwargs)
            cls.__instances__[address] = obj
            return obj
        except Exception as e:
            cls.__instances__.pop(address, None)
            raise ValueError(f"Failed to create {cls.__name__} @ {address:x}") from e

    @classmethod
    def define_user_type(cls, view: bn.BinaryView):
        with bn.StructureBuilder.builder(view, cls.alt_name) as builder:
            builder.packed = cls.packed
            for mtype, mname in cls.members:
                # pylint: disable-next=no-member
                builder.append(get_cached_type(view, mtype), mname)

        view.define_user_type(cls.name, bn.Type.named_type_from_registered_type(
            view, cls.alt_name
        ))

    @property
    def address(self) -> int:
        return self.source.address

    @classmethod
    @cache
    def get_user_struct(cls, view: bn.BinaryView) -> bn.Type:
        cls.define_user_type(view)
        return view.get_type_by_name(cls.alt_name)

    @classmethod
    @cache
    def get_struct_ref(cls, view: bn.BinaryView) -> bn.NamedTypeReferenceType:
        cls.define_user_type(view)
        return bn.Type.named_type_from_registered_type(view, cls.alt_name)

    @classmethod
    @cache
    def get_typedef_ref(cls, view: bn.BinaryView) -> bn.NamedTypeReferenceType:
        cls.define_user_type(view)
        return bn.Type.named_type_from_registered_type(view, cls.name)

    @classmethod
    @cache
    def get_alignment(cls, view: bn.BinaryView) -> int:
        return cls.get_user_struct(view).members[0].type.width

MemberTypeSpec = str | bn.Type | type[CheckedTypeDataVar] | type['RTTIOffsetType']

T = TypeVar('T')
class RTTIOffsetType(Generic[T]):
    @classmethod
    def get_target(cls, type_spec) -> Optional[MemberTypeSpec]:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return args[0]
 
    @classmethod
    def get_relative_type(cls, type_spec) -> Optional[MemberTypeSpec]:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return 'int' if len(args) < 2 else args[1]

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
    def resolve(cls, type_spec) -> Optional[type[CheckedTypeDataVar]]:
        if (target := cls.get_target(type_spec)) is None:
            return None

        for scls in CheckedTypeDataVar.__subclasses__():
            if scls.name == target:
                return scls

        return None

    @classmethod
    def __class_getitem__(cls, key: str):
        return GenericAlias(cls, (key,))

@cache
def get_cached_type(view: bn.BinaryView, type_spec: MemberTypeSpec) -> bn.Type:
    if isinstance(type_spec, bn.Type):
        return type_spec

    if isinstance(type_spec, type) and issubclass(type_spec, CheckedTypeDataVar):
        return type_spec.get_typedef_ref(view)

    if (ref := NamedCheckedTypeRef.get_ref(type_spec)) is not None:
        return ref

    if (offset_target := RTTIOffsetType.get_target(type_spec)) is not None:
        ptr_type = bn.Type.pointer(view.arch, get_cached_type(view, offset_target))
        return ptr_type if not uses_relative_rtti(view) else get_cached_type(
            view,
            RTTIOffsetType.get_relative_type(type_spec)
        )

    assert isinstance(type_spec, str), f'Incorrect type spec {type_spec} ({type(type_spec)})'
    return view.parse_type_string(type_spec)[0]

class RelativeOffsetRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if not uses_relative_rtti(view):
            return False

        if len(context) == 0 or (container_type := next(
            (
                scls
                for scls in CheckedTypeDataVar.__subclasses__()
                if bn.DataRenderer.is_type_of_struct_name(
                    context[-1].type,
                    scls.alt_name,
                    context[:-1],
                )
            )
        , None)) is None:
            return False

        member_offset = context[-1].offset
        user_struct = container_type.get_user_struct(view)
        if (member := user_struct.member_at_offset(member_offset)) is None:
            return False

        if member.name not in container_type.relative_members:
            return False

        if member.type != _type:
            return False

        return True

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        value = view.typed_data_accessor(address, _type).value
        target = resolve_rtti_offset(view, value)

        if (var := view.get_data_var_at(target)) is not None:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.DataSymbolToken,
                var.name or f"data_{target:x}",
                target,
            )
        else:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.IntegerToken,
                hex(value),
                target,
            )

        return [
            bn.DisassemblyTextLine([
                *prefix,
                token
            ], address)
        ]

class RelativeOffsetListener(bn.BinaryDataNotification):
    def __init__(self):
        super().__init__(
            bn.NotificationType.NotificationBarrier |
            bn.NotificationType.DataVariableAdded |
            bn.NotificationType.DataVariableLifetime |
            bn.NotificationType.DataVariableRemoved |
            bn.NotificationType.DataVariableUpdated |
            bn.NotificationType.DataVariableUpdates
        )
        self.received_event = False

    def notification_barrier(self, view: bn.BinaryView) -> int:
        has_events = self.received_event
        self.received_event = False

        if has_events:
            return 250

        return 0

    def find_checked_type(self, view: bn.BinaryView, _type: bn.Type) -> bool:
        if not uses_relative_rtti(view):
            return False

        return next(
            (
                scls
                for scls in CheckedTypeDataVar.__subclasses__()
                if scls.get_typedef_ref(view) == _type
            ),
            None,
        )

    def data_var_added(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for member in var_type.relative_members:
            offset = var_type.get_user_struct(view)[member].offset
            view.add_user_data_ref(
                var.address + offset,
                resolve_rtti_offset(view, var.value[member])
            )

    def data_var_updated(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for member in var_type.relative_members:
            offset = var_type.get_user_struct(view)[member].offset
            view.add_user_data_ref(
                var.address + offset,
                resolve_rtti_offset(view, var.value[member])
            )

    def data_var_removed(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if (var_type := self.find_checked_type(view, var.type)) is None:
            return

        for member in var_type.relative_members:
            offset = var_type.get_user_struct(view)[member].offset
            view.remove_user_data_ref(
                var.address + offset,
                resolve_rtti_offset(view, var.value[member])
            )
