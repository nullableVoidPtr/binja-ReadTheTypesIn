from typing import Optional, Generator, Self
from functools import cache
import traceback
import binaryninja as bn
from ..utils import get_data_sections, uses_relative_rtti, encode_rtti_offset
from ...types import CheckedTypeDataVar, RTTIOffsetType, NamedCheckedTypeRef
from .type_descriptor import TypeDescriptor
from .class_hierarchy_descriptor import ClassHierarchyDescriptor

COL_SIG_REV0 = 0x00000000
COL_SIG_REV1 = 0x00000001

COMPLETE_OBJECT_LOCATOR_MEMBERS = [
    ('unsigned long', 'signature'),
    ('unsigned long', 'offset'),
    ('unsigned long', 'cdOffset'),
    (RTTIOffsetType[TypeDescriptor], 'pTypeDescriptor'),
    (RTTIOffsetType[ClassHierarchyDescriptor], 'pClassDescriptor'),
]

class _CompleteObjectLocatorBase():
    offset: int
    complete_displacement_offset: int
    type_descriptor: TypeDescriptor
    class_hierarchy_descriptor: ClassHierarchyDescriptor

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.offset = self['offset'].value
        self.complete_displacement_offset= self['cdOffset'].value
        self.type_descriptor = self['pTypeDescriptor']
        self.class_hierarchy_descriptor = self['pClassDescriptor']
        if self.type_descriptor is not self.class_hierarchy_descriptor.base_class_array[0].type_descriptor:
            raise ValueError('Type descriptors do not match')

    @property
    def type_name(self):
        if self.offset > 0:
            return None

        return self.type_descriptor.type_name_without_prefix

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name}::`RTTI Complete Object Locator'"

class _CompleteObjectLocator(_CompleteObjectLocatorBase, CheckedTypeDataVar,
    name='_s_RTTICompleteObjectLocator',
    alt_name='_s__RTTICompleteObjectLocator',
    members=COMPLETE_OBJECT_LOCATOR_MEMBERS,
):
    pass

class _CompleteObjectLocator2(_CompleteObjectLocatorBase, CheckedTypeDataVar,
    name='_s_RTTICompleteObjectLocator2',
    alt_name='_s__RTTICompleteObjectLocator2',
    members=[
        *COMPLETE_OBJECT_LOCATOR_MEMBERS,
        (RTTIOffsetType[NamedCheckedTypeRef['_s_RTTICompleteObjectLocator2']], 'pSelf'),
    ],
):
    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        if self.source['pSelf'].value != encode_rtti_offset(view, self.address):
            raise ValueError('Invalid pSelf')

    def mark_down_members(self):
        for name in self.relative_members:
            if name == 'pSelf':
                continue

            self[name].mark_down()

class CompleteObjectLocator:
    name = '_RTTICompleteObjectLocator'
    
    @classmethod
    def create(cls, view: bn.BinaryView, *args, **kwargs):
        return cls.get_actual_type(view).create(view, *args, **kwargs)

    @classmethod
    @cache
    def get_actual_type(cls, view: bn.BinaryView) -> type[_CompleteObjectLocatorBase]:
        return _CompleteObjectLocator2 if uses_relative_rtti(view) else _CompleteObjectLocator
    
    @classmethod
    def get_signature_rev(cls, view: bn.BinaryView) -> int:
        return COL_SIG_REV1 if uses_relative_rtti(view) else COL_SIG_REV0

    @classmethod
    def define_user_type(cls, view: bn.BinaryView) -> bn.Type:
        view.define_user_type(cls.name, cls.get_actual_type(view).get_typedef_ref(view))

    @classmethod
    @cache
    def get_user_struct(cls, view: bn.BinaryView) -> bn.Type:
        return cls.get_actual_type(view).get_user_struct(view)

    @classmethod
    @cache
    def get_typedef_ref(cls, view: bn.BinaryView) -> bn.Type:
        cls.define_user_type(view)
        return bn.Type.named_type_from_registered_type(view, cls.name)

    @classmethod
    @cache
    def get_alignment(cls, view: bn.BinaryView) -> int:
        return cls.get_user_struct(view).members[0].type.width

    @classmethod
    def search_with_type_descriptors(
        cls, view: bn.BinaryView,
        type_descriptors: list[TypeDescriptor],
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        type_desc_offsets = set(
            encode_rtti_offset(view, desc.address)
            for desc in type_descriptors
            if not desc.decorated_name.startswith(".?AV<lambda")
        )

        user_struct = cls.get_user_struct(view)

        matches = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_complete_object_locator(accessor: bn.TypedDataAccessor) -> bool:
            offset = accessor['pTypeDescriptor'].value
            if offset not in type_desc_offsets:
                return False

            if any(member.name == 'pSelf' for member in user_struct.members):
                if accessor['pSelf'].value != encode_rtti_offset(view, accessor.address):
                    return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            accessor = view.typed_data_accessor(address, user_struct)
            if is_potential_complete_object_locator(accessor):
                matches.append(accessor)

            return True

        signature = cls.get_signature_rev(view).to_bytes(
            user_struct['signature'].type.width,
            'little' if view.endianness is bn.Endianness.LittleEndian else 'big'
        )

        for section in get_data_sections(view):
            view.find_all_data(
                section.start, section.end,
                signature,
                progress_func=update_progress if task is not None else None,
                match_callback=process_match,
            )

        underlying_type = cls.get_actual_type(view)
        for accessor in matches:
            try:
                col = underlying_type.create(view, accessor)
                yield col
            except Exception:
                bn.log.log_warn(
                    f'Failed to define complete object locator @ 0x{accessor.address:x}',
                    'CompleteObjectLocator::search_with_type_descriptors',
                )
                traceback.print_exc()
                continue

            bn.log.log_debug(
                f'Defined complete object locator @ 0x{accessor.address:x}',
                'CompleteObjectLocator::search_with_type_descriptors',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'
