from typing import Optional
import binaryninja as bn
from .structs.rtti.base_class_descriptor import BaseClassDescriptor, PMD
from .structs.rtti.class_hierarchy_descriptor import ClassHierarchyDescriptor
from .structs.virtual_function_table import VirtualFunctionTable

class VisualCxxBaseClass:
    where: PMD
    cls: 'VisualCxxClass'
    base_class_descriptor: BaseClassDescriptor

    def __init__(self, cls, base_class_descriptor):
        self.cls = cls
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
                (
                    "virtual "
                    if base.base_class_descriptor.virtual
                    else ""
                ) + str(base.cls.type_name.name)
                for base in base_classes
            )

        return str(self.type_name) + inheritance_info + ";"

    def __repr__(self):
        return f"<Visual C++ {self.type_name}>"

    @staticmethod
    def structure(classes: list['VisualCxxClass'], task: Optional[bn.BackgroundTask] = None):
        if task is not None:
            task.progress = 'Structuring classes'

        type_names = {
            cls.type_name: cls
            for cls in classes
        }
        bcd_to_classes = {
            bcd: type_names[bcd.type_name]
            for cls in classes
            for bcd in cls.class_hierarchy_descriptor.base_class_array
        }

        resolved = set()
        changed = False
        while True:
            for cls in classes:
                if cls in resolved:
                    continue

                class_bcds = list(
                    cls.class_hierarchy_descriptor.base_class_array
                )[1:]
                if not all(
                    bcd_to_classes[bcd] in resolved
                    for bcd in class_bcds
                ):
                    continue

                if task is not None:
                    print(f'Structuring {cls.type_name}')
                    task.progress = f'Structuring {cls.type_name}'

                base_classes = []
                resolved_indexes = [None] * len(class_bcds)
                while True:
                    parent_bca_index = next(
                        (
                            i
                            for i, resolved in enumerate(resolved_indexes)
                            if resolved is None
                        ),
                        None,
                    )
                    if parent_bca_index is None:
                        break

                    parent_bcd = class_bcds[parent_bca_index]
                    parent_class = bcd_to_classes[parent_bcd]
                    resolved_indexes[parent_bca_index] = parent_class

                    ancestor_bcds = list(
                        parent_class.class_hierarchy_descriptor.base_class_array
                    )[1:]

                    parent_bca_index += 1
                    for ancestor_bcd in ancestor_bcds:
                        ancestor_chd = ancestor_bcd.class_hierarchy_descriptor
                        ancestor_td = ancestor_bcd.type_descriptor
                        for next_parent_bca_offset in range(parent_bca_index, len(class_bcds)):
                            current = class_bcds[next_parent_bca_offset]
                            current_chd = current.class_hierarchy_descriptor
                            current_td = current.type_descriptor
                            if ancestor_chd is not None and current_chd is not None:
                                if ancestor_chd is not current_chd:
                                    continue
                            elif ancestor_td is not current_td:
                                continue

                            break

                        parent_bca_index = next_parent_bca_offset
                        resolved_indexes[parent_bca_index] = bcd_to_classes[ancestor_bcd]
                        parent_bca_index += 1

                    base_classes.append(VisualCxxBaseClass(parent_class, parent_bcd))

                if any(index is None for index in resolved_indexes):
                    print(class_bcds)
                    print(resolved_indexes)
                    raise ValueError()

                changed = True
                cls.base_classes = base_classes
                resolved.add(cls)

            if not changed:
                break
            changed = False

        return resolved
