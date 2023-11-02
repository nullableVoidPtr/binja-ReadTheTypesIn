from typing import Annotated
from enum import IntFlag
import binaryninja as bn
from ....types import CheckedTypeDataVar, Enum, RTTIOffsetType
from .base_class_descriptor import BaseClassArray

class CHDAttributes(IntFlag):
    CHD_MULTINH   = 0x00000001
    CHD_VIRTINH   = 0x00000002
    CHD_AMBIGUOUS = 0x00000004

class ClassHierarchyDescriptor(CheckedTypeDataVar,
    members=[
        ('unsigned long', 'signature'),
        (Enum[CHDAttributes, 'unsigned long'], 'attributes'),
        ('unsigned long', 'numBaseClasses'),
        (RTTIOffsetType[BaseClassArray], 'pBaseClassArray'),
    ]
):
    name = '_RTTIClassHierarchyDescriptor'
    alt_name = '_s_RTTIClassHierarchyDescriptor'

    attributes: Annotated[CHDAttributes, 'attributes']
    base_class_array: Annotated[BaseClassArray, 'pBaseClassArray']

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        if self['signature'] != 0:
            raise ValueError('Invalid signature')

    def __getitem__(self, key: str):
        if key == 'pBaseClassArray':
            return BaseClassArray.create(
                self.view,
                RTTIOffsetType.resolve_offset(
                    self.view,
                    self.source[key].value
                ),
                self['numBaseClasses'],
            )

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self.base_class_array[0].type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name.name}::`RTTI Class Hierarchy Descriptor'"
