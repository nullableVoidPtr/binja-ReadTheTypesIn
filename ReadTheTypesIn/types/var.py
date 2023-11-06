from typing import Optional, ClassVar, Mapping, Self, Annotated, get_origin
from weakref import WeakKeyDictionary
import binaryninja as bn
from .resolver import resolve_type_spec
from .annotation import OffsetType, Array, Enum, NamedCheckedTypeRef
from ..name import TypeName
from ..msvc.utils import get_function

class CheckedTypeDataVar:
    name: ClassVar[str]
    alt_name: ClassVar[str]

    packed: ClassVar[bool] = False
    members: ClassVar[list[tuple[bn.Type, str]]]
    member_map: ClassVar[dict[str, bn.Type]]

    _attr_map: ClassVar[dict[str, str]]

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
        cls.member_map = {
            name: mtype
            for mtype, name in cls.members
        }

        cls._attr_map = {}
        for c in reversed(cls.__mro__):
            if c is CheckedTypeDataVar:
                continue

            annotations = getattr(c, '__annotations__', None)
            if not isinstance(annotations, dict):
                continue

            for attr, annotation in annotations.items():
                if get_origin(annotation) is not Annotated:
                    continue

                member = annotation.__metadata__[0]
                if not isinstance(member, str):
                    continue

                cls._attr_map[attr] = member

        for i, (mtype, mname) in enumerate(cls.members):
            if not Array.is_flexible(mtype):
                continue

            if i != len(cls.members) - 1:
                raise TypeError(
                    f"Flexible array member {mname} is not the last member"
                )

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

        for attr, member in self._attr_map.items():
            setattr(self, attr, self[member])

    def __getitem__(self, key: str):
        from .typedef import CheckedTypedef

        member_source = self.source[key]

        target_type = self.member_map[key]

        if (enum_type := Enum.get_type(target_type)) is not None:
            return enum_type(member_source.value)

        if (array_type := Array.get_element_type(target_type)) is not None:
            target_type = array_type

        if (offset_type := OffsetType.get_origin(target_type)) is not None:
            target_type = OffsetType.get_target(target_type)
            if NamedCheckedTypeRef.get_target(target_type) is not None:
                if (resolved := NamedCheckedTypeRef.resolve(target_type)) is None:
                    raise TypeError(f'Cannot resolve {target_type}')

                target_type = resolved
            elif isinstance(target_type, str):
                target_type = resolve_type_spec(self.view, target_type)


            if isinstance(member_source.type, bn.ArrayType):
                member_source = [
                    offset_type.resolve_offset(
                        self.view,
                        offset.value
                    )
                    for offset in member_source
                ]
            else:
                member_source = offset_type.resolve_offset(
                    self.view,
                    member_source.value
                )

        if isinstance(target_type, bn.FunctionType):
            return get_function(self.view, member_source)

        if isinstance(target_type, type) and \
            issubclass(target_type, (CheckedTypeDataVar, CheckedTypedef)):
            if isinstance(member_source, bn.TypedDataAccessor):
                if member_source.type == target_type.get_typedef_ref(self.view):
                    member_source = member_source.address
                    return target_type.create(
                        self.view,
                        member_source,
                    )

                if isinstance(member_source.type, bn.ArrayType):
                    # TODO more checks
                    return [
                        target_type.create(
                            self.view,
                            value.address,
                        )
                        for value in member_source
                    ]

            if isinstance(member_source, int):
                return target_type.create(
                    self.view,
                    member_source,
                )

            if isinstance(member_source, list):
                return [
                    target_type.create(
                        self.view,
                        address,
                    )
                    for address in member_source
                ]

            raise ValueError()

        if isinstance(member_source, int):
            member_source = self.view.typed_data_accessor(
                member_source,
                target_type,
            )
        elif isinstance(member_source, list):
            member_source = [
                self.view.typed_data_accessor(
                    address,
                    target_type,
                )
                for address in member_source
            ]

        if isinstance(member_source.type, bn.IntegerType):
            return member_source.value

        if isinstance(member_source.type, bn.ArrayType):
            if all(
                isinstance(child, bn.IntegerType)
                for child in member_source.type.children
            ):
                return member_source.value

        return member_source

    def __repr__(self):
        suffix = '' if self.type_name is None else f': {self.type_name}'
        return f"<{self.__class__.__name__} 0x{self.address:x}{suffix}>"

    @property
    def view(self) -> bn.BinaryView:
        return self.source.view

    @property
    def type(self) -> bn.Type:
        last_type, last_name = self.members[-1]
        if not Array.is_flexible(last_type):
            return self.get_typedef_ref(self.view)

        element_type = Array.get_element_type(last_type)
        builder = bn.StructureBuilder.create()
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]
        builder.add_member_at_offset(
            last_name,
            bn.Type.array(
                resolve_type_spec(self.view, element_type),
                self.get_array_length(last_name),
            ),
            self.get_user_struct(self.view).width,
        )

        return builder.immutable_copy()

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

    def get_array_length(self, name: str) -> int:
        raise TypeError(f"len({name}) is not defined")

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
        for name, mtype in self.member_map.items():
            if OffsetType.get_target(mtype) is not None:
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
            elif OffsetType.get_target(Array.get_element_type(mtype)) is not None:
                array = self[name]
                for element in array:
                    if isinstance(element, CheckedTypeDataVar):
                        if element.defined:
                            continue

                        try:
                            element.mark_down()
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
        if view.session_data.get(session_data_key) and old_type is not None:
            return old_type

        builder = bn.StructureBuilder.create()
        builder.packed = cls.packed
        for mtype, mname in cls.members:
            if Array.is_flexible(mtype):
                builder.append(
                    bn.Type.array(
                        resolve_type_spec(
                            view,
                            Array.get_element_type(mtype),
                        ),
                        0
                    ),
                    mname
                )
                continue

            builder.append(resolve_type_spec(view, mtype), mname)

        structure = builder.immutable_copy()

        if old_type is not None:
            members = old_type.members
            if len(members) == len(structure.members):
                for (expected_type, expected_name), member in zip(members, structure.members):
                    if member.name != expected_name:
                        break

                    expected_type = resolve_type_spec(view, expected_type)
                    if member.type != expected_type:
                        print(f"{member.type=} {expected_type=}")
                        break
                else:
                    view.session_data[session_data_key] = True
                    return old_type

        view.define_user_type(cls.alt_name, structure)
        view.session_data[session_data_key] = True

        return view.types.get(cls.alt_name)

    @classmethod
    def define_typedef(cls, view: bn.BinaryView):
        session_data_key = f'ReadTheTypesIn.{cls.name}.defined'
        struct_ref = cls.get_struct_ref(view)
        if (old_typedef := view.types.get(cls.name)) is not None:
            if view.session_data.get(session_data_key):
                return

            if isinstance(old_typedef, bn.types.NamedReferenceType):
                target = old_typedef.target(view)
                if target == struct_ref:
                    view.session_data[session_data_key] = True
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
