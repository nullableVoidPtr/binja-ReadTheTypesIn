from typing import Optional
import binaryninja as bn
from .structs.rtti.base_class_descriptor import BaseClassDescriptor, PMD
from .structs.rtti.class_hierarchy_descriptor import ClassHierarchyDescriptor
from .structs.virtual_function_table import VirtualFunctionTable

class VisualCxxBaseClass:
    where: PMD
    class_info: 'VisualCxxClass'
    base_class_descriptor: BaseClassDescriptor

    def __init__(self, class_info, base_class_descriptor):
        self.class_info = class_info
        self.base_class_descriptor = base_class_descriptor

class VisualCxxClass:
    class_hierarchy_descriptor: ClassHierarchyDescriptor
    base_vftables: dict[(int, int), VirtualFunctionTable]

    _base_classes: Optional[list[VisualCxxBaseClass]]
    constructors: set[bn.Function]
    destructor: Optional[bn.Function]

    width: Optional[int]

    def __init__(
        self,
        class_hierarchy_descriptor: ClassHierarchyDescriptor,
		virtual_function_tables: Optional[list[VirtualFunctionTable]] = None
    ):
        self.class_hierarchy_descriptor = class_hierarchy_descriptor
        self.base_vftables = {}
        self._base_classes = None
        self.constructors = set()
        self.destructor = None
        self.width = None

        if virtual_function_tables is not None:
            for vftable in virtual_function_tables:
                self.add_vftable(vftable)

    @property
    def type_name(self):
        try:
            return self.class_hierarchy_descriptor.type_name
        except Exception as e:
            print(self.base_vftables)
            raise e

    def add_vftable(self, virtual_function_table: VirtualFunctionTable):
        meta = virtual_function_table.meta
        if meta.class_hierarchy_descriptor is not self.class_hierarchy_descriptor:
            raise ValueError()

        key = (
            meta.offset,
            meta.complete_displacement_offset,
        )
        # TODO define for_base_class here by matching base class array
        if key in self.base_vftables:
            raise ValueError()

        self.base_vftables[key] = virtual_function_table

    @property
    def base_classes(self) -> list[VisualCxxBaseClass]:
        return self._base_classes

    @base_classes.setter
    def base_classes(self, base_classes: Optional[list[VisualCxxBaseClass]]):
        # TODO sanity checks here
        self._base_classes = base_classes

    def mark_down(self):
        pass

    def __str__(self):
        inheritance_info = ""
        base_classes = self.base_classes
        if base_classes is None:
            inheritance_info = " : unknown"
        elif len(base_classes) > 0:
            inheritance_info = " : " + ", ".join(
                ("virtual " if base.base_class_descriptor.virtual else "") + str(base.class_info.type_name.name)
                for base in base_classes
            )

        return str(self.type_name) + inheritance_info + ";"

    def __repr__(self):
        return f"<Visual C++ {self.type_name}>"
