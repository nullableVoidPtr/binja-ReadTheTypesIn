from typing import Optional, Annotated
from enum import IntFlag
import binaryninja as bn
from ....types import CheckedTypeDataVar, Array, Enum, RTTIOffsetType, NamedCheckedTypeRef
from .type_descriptor import TypeDescriptor

class PMD(CheckedTypeDataVar, members=[
    ('int', 'mdisp'),
    ('int', 'pdisp'),
    ('int', 'vdisp'),
]):
    mdisp: Annotated[int, 'mdisp']
    pdisp: Annotated[int, 'pdisp']
    vdisp: Annotated[int, 'vdisp']

class BCDAttributes(IntFlag):
    BCD_NOTVISIBLE          = 0x00000001
    BCD_AMBIGUOUS           = 0x00000002
    BCD_PRIVORPROTBASE      = 0x00000004
    BCD_PRIVORPROTINCOMPOBJ = 0x00000008
    BCD_VBOFCONTOBJ         = 0x00000010
    BCD_NONPOLYMORPHIC      = 0x00000020
    BCD_HASPCHD             = 0x00000040

class BaseClassDescriptor(CheckedTypeDataVar,
    members=[
        (RTTIOffsetType[TypeDescriptor], 'pTypeDescriptor'),
        ('unsigned long', 'numContainedBases'),
        (PMD, 'where'),
        (Enum[BCDAttributes, 'unsigned long'], 'attributes'),
        (RTTIOffsetType[
            NamedCheckedTypeRef['_RTTIClassHierarchyDescriptor']
        ], 'pClassDescriptor'),
    ],
):
    name = '_RTTIBaseClassDescriptor'
    alt_name = '_s_RTTIBaseClassDescriptor'

    type_descriptor: Annotated[TypeDescriptor, 'pTypeDescriptor']
    num_contained_bases: Annotated[int, 'numContainedBases']
    where: Annotated[PMD, 'where']
    attributes: Annotated[BCDAttributes, 'attributes']
    class_hierarchy_descriptor: Annotated[
        Optional['ClassHierarchyDescriptor'],
        'pClassDescriptor'
    ]

    def __getitem__(self, key: str):
        if key == 'pClassDescriptor':
            if BCDAttributes.BCD_HASPCHD not in self['attributes']:
                return None

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self.type_descriptor.type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        where = f'{self.where.mdisp},{self.where.pdisp},{self.where.vdisp}'
        location = f'({where},{int(self.attributes)})'
        return f"{self.type_name.name}::`RTTI Base Class Descriptor at {location}'"

    @property
    def virtual(self) -> bool:
        return BCDAttributes.BCD_VBOFCONTOBJ in self.attributes

class BaseClassArray(CheckedTypeDataVar,
    members=[
        (Array[RTTIOffsetType[BaseClassDescriptor], ...], 'arrayOfBaseClassDescriptors'),
    ],
):
    name = '_RTTIBaseClassArray'
    alt_name = '_s_RTTIBaseClassArray'

    length: int
    base_class_descs: list[BaseClassDescriptor]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int, length: int):
        super().__init__(view, source)
        self.length = length
        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

        self.base_class_descs = self['arrayOfBaseClassDescriptors']

    def get_array_length(self, name: str):
        if name == 'arrayOfBaseClassDescriptors':
            return self.length

        return super().get_array_length(name)

    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.base_class_descs)

    def __contains__(self, value):
        return value in self.base_class_descs

    def __getitem__(self, key: str | int):
        if isinstance(key, int):
            return self.base_class_descs[key]

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self[0].type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name.name}::`RTTI Base Class Array'"

    def mark_down_members(self):
        for bcd in self.base_class_descs:
            bcd.mark_down()
