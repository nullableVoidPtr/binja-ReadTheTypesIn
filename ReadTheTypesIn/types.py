from typing import (
    Optional,
    Mapping,
    ClassVar, Self,
    TypeVar, Generic, get_origin, get_args
)
from functools import cache
from weakref import WeakKeyDictionary
from types import GenericAlias
import binaryninja as bn
from .name import TypeName
from .msvc.utils import uses_relative_rtti, resolve_rtti_offset, get_function

class CheckedTypeDataVar:
    name: ClassVar[str]
    alt_name: ClassVar[str]

    packed: ClassVar[bool] = False
    members: ClassVar[list[tuple[bn.Type, str]]]
    relative_members: ClassVar[Mapping[str, bn.Type]]

    __instances__: ClassVar[Mapping[bn.BinaryView, Mapping[int, Self]]]

    source: bn.TypedDataAccessor

    def __init_subclass__(
        cls,
        alignment=None,
        members: list[tuple[bn.Type, str]] = None,
        **kwargs
    ):
        if not hasattr(cls, 'name'):
            cls.name = cls.__name__
        if not hasattr(cls, 'alt_name'):
            cls.alt_name = f'_{cls.name}'

        assert members is not None, f"Members of {cls.name} must be specified"
        cls.members = members
        cls.relative_members = {
            name: target
            for mtype, name in cls.members
            if (target := RTTIOffsetType.get_target(mtype)) is not None
        }

        if getattr(cls, '__instances__', None) is None:
            cls.__instances__ = WeakKeyDictionary()

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        if isinstance(source, bn.TypedDataAccessor):
            user_struct = self.get_user_struct(source.view)
            if source.type != user_struct:
                raise TypeError(
                    f"Expected type of accessor to be {repr(user_struct)}, got {repr(source.type)}"
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

        if key in self.relative_members:
            target_type = self.relative_members[key]
            if NamedCheckedTypeRef.get_target(target_type) is not None:
                if (resolved := NamedCheckedTypeRef.resolve(target_type)) is None:
                    raise TypeError(f'Cannot resolve {target_type}')

                target_type = resolved
            elif isinstance(target_type, str):
                target_type = get_cached_type(self.view, target_type)


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

        if isinstance(target_type, bn.FunctionType):
            return get_function(self.view, member_source)

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
        if (old_var := self.view.get_data_var_at(self.address)) is None:
            return False

        if old_var.type != self.type:
            return False

        expected_symbol_name = self.symbol_name
        if expected_symbol_name is None:
            return True

        if isinstance(expected_symbol_name, str):
            return old_var.name == expected_symbol_name

        if tuple(old_var.symbol.namespace.name) != tuple(expected_symbol_name.namespace.name):
            return False

        return old_var.symbol.short_name == expected_symbol_name.short_name

    @property
    def type_name(self) -> Optional[TypeName]:
        return None

    @property
    def symbol_name(self) -> Optional[str | bn.Symbol]:
        return None

    def mark_down(self):
        if not self.defined:
            try:
                self.view.define_user_data_var(
                    self.address,
                    self.type,
                    self.symbol_name,
                )
                if self.type_name is not None:
                    component = self.type_name.get_component(self.view)
                    component.add_data_variable(
                        self.view.get_data_var_at(self.address)
                    )
            except Exception as e:
                raise ValueError(
                    f"Failed to define {self.name} @ {self.address:x}"
                ) from e
        self.mark_down_members()

    def mark_down_members(self):
        for name in self.relative_members:
            member = self[name]
            if isinstance(member, CheckedTypeDataVar):
                if member.defined:
                    continue

                try:
                    member.mark_down()
                except Exception as e:
                    raise ValueError(
                        f"Failed to define {self.name}.{name} @ {self[name].address:x}"
                    ) from e

    @classmethod
    def create(
        cls,
        view: bn.BinaryView,
        source: bn.TypedDataAccessor | int,
        *args, **kwargs) -> Self:
        if isinstance(source, bn.TypedDataAccessor):
            address = source.address
        else:
            address = source

        view_instances = cls.__instances__.setdefault(view, {})
        if address in view_instances:
            return view_instances[address]

        obj = object.__new__(cls, view, source, *args, **kwargs)
        view_instances[address] = obj
        try:
            # pylint: disable-next=unnecessary-dunder-call
            obj.__init__(view, source, *args, **kwargs)
            return obj
        except Exception as e:
            view_instances.pop(address, None)
            raise ValueError(f"Failed to create {cls.__name__} @ {address:x}") from e

    @classmethod
    def define_structure(cls, view: bn.BinaryView) -> bn.StructureType:
        session_data_key = f'ReadTheTypesIn.{cls.alt_name}.defined'
        old_type = view.types.get(cls.alt_name)
        if view.session_data.get(session_data_key):
            return old_type

        builder = bn.StructureBuilder.create()
        builder.packed = cls.packed
        for mtype, mname in cls.members:
            # pylint: disable-next=no-member
            builder.append(get_cached_type(view, mtype), mname)

        # pylint: disable-next=no-member
        structure = builder.immutable_copy()

        if old_type is not None:
            members = old_type.members
            if len(members) == len(structure.members):
                for member, (expected_type, expected_name) in zip(members, structure.members):
                    if member.name != expected_name:
                        break

                    expected_type = get_cached_type(view, expected_type)
                    if member.type != expected_type:
                        print(f"{member.type=} {expected_type=}")
                        break
                else:
                    return old_type

        view.define_user_type(cls.alt_name, structure)
        view.session_data[session_data_key] = True

        return view.types.get(cls.alt_name)

    @classmethod
    def define_typedef(cls, view: bn.BinaryView):
        session_data_key = f'ReadTheTypesIn.{cls.name}.defined'
        if view.session_data.get(session_data_key):
            return

        struct_ref = cls.get_struct_ref(view)
        if (old_typedef := view.types.get(cls.name)) is not None:
            if isinstance(old_typedef, bn.types.NamedReferenceType):
                target = old_typedef.target(view)
                if target == struct_ref:
                    return

        view.define_user_type(cls.name, struct_ref)
        view.session_data[session_data_key] = True

    @classmethod
    def define_user_type(cls, view: bn.BinaryView):
        cls.define_structure(view)
        cls.define_typedef(view)

    @property
    def address(self) -> int:
        return self.source.address

    @classmethod
    def get_user_struct(cls, view: bn.BinaryView) -> bn.Type:
        cls.define_structure(view)
        return view.get_type_by_name(cls.alt_name)

    @classmethod
    def get_struct_ref(cls, view: bn.BinaryView) -> bn.NamedTypeReferenceType:
        cls.define_structure(view)
        return bn.Type.named_type_from_registered_type(view, cls.alt_name)

    @classmethod
    def get_typedef_ref(cls, view: bn.BinaryView) -> bn.NamedTypeReferenceType:
        cls.define_typedef(view)
        return bn.Type.named_type_from_registered_type(view, cls.name)

    @classmethod
    def get_alignment(cls, view: bn.BinaryView) -> int:
        return cls.get_user_struct(view).alignment

    @classmethod
    def get_instances(cls, view: bn.BinaryView) -> list[Self]:
        if (view_instances := cls.__instances__.get(view)) is None:
            return []

        return list(view_instances.values())

MemberTypeSpec = str | bn.Type | type[CheckedTypeDataVar] | type['RTTIOffsetType']

T = TypeVar('T')
class Array(Generic[T]):
    @classmethod
    def get_element_type(cls, type_spec) -> Optional[MemberTypeSpec]:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        return args[0]

    @classmethod
    def get_size(cls, type_spec) -> Optional[MemberTypeSpec]:
        if get_origin(type_spec) is not cls:
            return None

        args = get_args(type_spec)
        assert args is not None
        if len(args) < 2 or args[1] is Ellipsis:
            return None

        return args[1]

    @classmethod
    def __class_getitem__(cls, key: str):
        return GenericAlias(cls, (key,))

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

    @classmethod
    def __class_getitem__(cls, key: str):
        return GenericAlias(cls, (key,))

class EHOffsetType(Generic[T]):
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

    @classmethod
    def __class_getitem__(cls, key: str):
        return GenericAlias(cls, (key,))

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

        if value == 0:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.KeywordToken,
                "nullptr",
                target,
            )
        elif (var := view.get_function_at(target)) is not None:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.CodeSymbolToken,
                var.name or f"sub_{target:x}",
                target,
            )
        elif (var := view.get_data_var_at(target)) is not None:
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

    def find_checked_type(self, view: bn.BinaryView, _type: bn.Type) \
        -> Optional[type[CheckedTypeDataVar]]:
        if not uses_relative_rtti(view):
            return None

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
