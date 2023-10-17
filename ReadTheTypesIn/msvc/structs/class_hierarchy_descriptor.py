import binaryninja as bn
from ...types import CheckedTypeDataVar, RTTIOffsetType
from ..utils import resolve_rtti_offset
from .base_class_descriptor import BaseClassArray

class ClassHierarchyDescriptor(CheckedTypeDataVar,
    name='_RTTIClassHierarchyDescriptor',
    alt_name='_s_RTTIClassHierarchyDescriptor',
    members=[
        ('unsigned long', 'signature'),
        ('unsigned long', 'attributes'),
        ('unsigned long', 'numBaseClasses'),
        (RTTIOffsetType[BaseClassArray], 'pBaseClassArray'),
    ]
):
    attributes: int
    base_class_array: BaseClassArray

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        if self['signature'].value != 0:
            raise ValueError('Invalid signature')

        self.attributes = self['attributes'].value
        self.base_class_array = self['pBaseClassArray']

        # for bcd in self.base_class_array:
        #     if bcd.type_descriptor is not bcd.class_hierarchy_descriptor.base_class_array[0].type_descriptor:
        #         raise ValueError('Class hierarchy descriptors do not match')

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

        return f"{self.type_name}::`RTTI Class Hierarchy Descriptor'"
