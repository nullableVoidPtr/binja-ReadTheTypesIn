from typing import Optional, Generator, Self
import traceback
import binaryninja as bn
from ..utils import get_data_sections
from .complete_object_locator import CompleteObjectLocator

PATTERN_SHIFT_SIZE = 3

class VirtualFunctionTable:
    __instances__ = {}
    meta: CompleteObjectLocator

    def __init__(self, view: bn.BinaryView, address: int):
        self.view = view
        self.address = address

        try:
            self.meta = CompleteObjectLocator.create(
                view,
                view.read_pointer(self.address - self.view.address_size),
            )
        except:
            self.meta = None

        self.method_addresses = []
        offset = 0
        while self.try_define_function(
            self.view,
            method_address := self.view.read_pointer(
                self.address + offset
            )
        ) is not None:
            self.method_addresses.append(method_address)
            offset += self.view.address_size

    @property
    def type(self):
        builder = bn.StructureBuilder.create()
        builder.pointer_offset = self.view.address_size
        builder.propagate_data_var_refs = True

        builder.append(
            bn.Type.pointer(
                self.view.arch,
                CompleteObjectLocator.get_typedef_ref(self.view),
            ),
            "meta"
        )

        for address in self.method_addresses:
            method = self.view.get_function_at(address)
            builder.append(
                bn.Type.pointer(
                    self.view.arch,
                    method.type,
                ),
                method.name
            )

        return builder.immutable_copy()

    @classmethod
    def create(cls, view: bn.BinaryView, address: int, *args, **kwargs):
        if address in cls.__instances__:
            return cls.__instances__[address]

        obj = object.__new__(cls, view, address, *args, **kwargs)
        cls.__instances__[address] = obj
        try:
            obj.__init__(view, address, *args, **kwargs)
            cls.__instances__[address] = obj
            return obj
        except Exception as e:
            cls.__instances__.pop(address, None)
            raise ValueError(f"Failed to create {cls.__name__} @ {address:x}") from e


    @property
    def type_name(self):
        return self.meta.type_name

    @property
    def symbol_name(self):
        return f"{self.type_name}::`vftable'"

    @staticmethod
    def try_define_function(view: bn.BinaryView, address: int):
        if not any(
            section.semantics == bn.SectionSemantics.ReadOnlyCodeSectionSemantics
            for section in view.get_sections_at(address)
        ):
            return None

        if view.get_data_var_at(address) is not None:
            return None

        if (func := view.get_function_at(address)) is not None:
            return func

        return view.create_user_function(address)

    @classmethod
    def search_with_complete_object_locators(
        cls,
        view: bn.BinaryView,
        complete_object_locators: list[CompleteObjectLocator],
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        pointers = {
            col.address: col
            for col in complete_object_locators
        }
        matches = []

        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.__name__} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_vftable(address: int):
            meta_address = address - view.address_size
            if meta_address % view.address_size != 0:
                return False

            if view.read_pointer(
                meta_address
            ) not in pointers:
                return False
            
            if view.get_function_at(
                func_addr := view.read_pointer(
                    address
                )
            ) is None:
                if cls.try_define_function(view, func_addr) is None:
                    return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            address -= PATTERN_SHIFT_SIZE
            if is_potential_vftable(
                address
            ):
                matches.append(address)

            return True
        
        patterns = set(
            (address >> (8 * PATTERN_SHIFT_SIZE)).to_bytes(
                view.address_size - PATTERN_SHIFT_SIZE,
                'little' if view.endianness is bn.Endianness.LittleEndian else 'big')
            for address in pointers
        )

        for pattern in patterns:
            for section in get_data_sections(view):
                view.find_all_data(
                    section.start, section.end,
                    pattern,
                    progress_func=update_progress if task is not None else None,
                    match_callback=process_match,
                )

        for address in matches:
            try:
                virtual_function_table = cls.create(view, address)
                yield virtual_function_table
            except Exception:
                bn.log.log_warn(
                    f'Failed to define virtual function table @ 0x{address:x}',
                    'VirtualFunctionTable::search',
                )
                traceback.print_exc()
                continue

            bn.log.log_debug(
                f'Defined virtual function table @ 0x{address:x}',
                'VirtualFunctionTable::search',
            )

        if task is not None:
            task.progress = f'{cls.__name__} search finished'