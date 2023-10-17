from .structs.type_descriptor import TypeDescriptor
from .structs.virtual_function_table import VirtualFunctionTable

class VisualCxxClass:
    type_descriptor: TypeDescriptor
    base_vftables: dict[(int, int), VirtualFunctionTable]

    def __init__(
        self,
        type_descriptor: TypeDescriptor,
		virtual_function_tables: list[VirtualFunctionTable]
    ):
        self.type_descriptor = type_descriptor
        self.base_vftables = {}

        if virtual_function_tables is not None:
            for vftable in virtual_function_tables:
                self.add_vftable(vftable)

    @property
    def type_name(self):
        return self.type_descriptor.type_name

    def add_vftable(self, virtual_function_table: VirtualFunctionTable):
        complete_object_locator = virtual_function_table.meta
        if complete_object_locator.type_descriptor is not self.type_descriptor:
            raise ValueError()

        key = (
            complete_object_locator.offset,
            complete_object_locator.complete_displacement_offset,
        )
        if key in self.base_vftables:
            raise ValueError()

        self.base_vftables[key] = virtual_function_table