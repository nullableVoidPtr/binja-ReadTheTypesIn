from enum import IntFlag
import binaryninja as bn
from ....types import CheckedTypeDataVar, RTTIOffsetType
from ...utils import resolve_rtti_offset
from .base_class_descriptor import BaseClassArray

class CHDAttributes(IntFlag):
    MULTINH   = 0x00000001
    VIRTINH   = 0x00000002
    AMBIGUOUS = 0x00000004

class ClassHierarchyDescriptor(CheckedTypeDataVar,
    members=[
        ('unsigned long', 'signature'),
        ('unsigned long', 'attributes'),
        ('unsigned long', 'numBaseClasses'),
        (RTTIOffsetType[BaseClassArray], 'pBaseClassArray'),
    ]
):
    name = '_RTTIClassHierarchyDescriptor'
    alt_name = '_s_RTTIClassHierarchyDescriptor'

    attributes: CHDAttributes
    base_class_array: BaseClassArray

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        if self['signature'].value != 0:
            raise ValueError('Invalid signature')

        self.attributes = CHDAttributes(self['attributes'].value)
        self.base_class_array = self['pBaseClassArray']

    def __getitem__(self, key: str):
        if key == 'pBaseClassArray':
            return BaseClassArray.create(
                self.view,
                resolve_rtti_offset(
                    self.view,
                    self.source[key].value
                ),
                self['numBaseClasses'].value,
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