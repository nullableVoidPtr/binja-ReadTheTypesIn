from typing import Optional, Generator, Self
from weakref import WeakKeyDictionary
import traceback
import binaryninja as bn
from ..utils import get_data_sections, get_function
from ...name import TypeName
from .rtti.complete_object_locator import CompleteObjectLocator

PATTERN_SHIFT_SIZE = 3

class VirtualFunctionTable:
    __instances__ = WeakKeyDictionary()

    meta: CompleteObjectLocator
    method_addresses: list[int]

    def __init__(self, view: bn.BinaryView, address: int):
        self.view = view
        self.address = address
        self.for_base_class = None

        try:
            self.meta = CompleteObjectLocator.create(
                view,
                view.read_pointer(self.address - self.view.address_size),
            )
        except ValueError:
            self.meta = None

        self.method_addresses = []
        offset = 0
        while get_function(
            self.view,
            method_address := self.view.read_pointer(
                self.address + offset
            )
        ) is not None:
            self.method_addresses.append(method_address)
            offset += self.view.address_size

    def name(self, for_base: Optional[TypeName] = None):
        suffix = ''
        if self.type_name is None:
            if for_base is None:
                return None

            suffix = f"{{for `{self.for_base_class.name}'}}"

        return f"{self.type_name.name}::`vftable'{suffix}"

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
            "meta",
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
        view_instances = cls.__instances__.setdefault(view, {})
        if address in view_instances:
            return view_instances[address]

        obj = object.__new__(cls, view, address, *args, **kwargs)
        view_instances[address] = obj
        try:
            # pylint:disable-next=unnecessary-dunder-call
            obj.__init__(view, address, *args, **kwargs)
            return obj
        except Exception as e:
            view_instances.pop(address, None)
            raise ValueError(f"Failed to create {cls.__name__} @ {address:x}") from e

    @property
    def type_name(self):
        return self.meta.type_name

    @property
    def symbol_name(self):
        return f"{self.type_name.name}::`vftable'"

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
            if address % view.address_size != 0:
                return False

            meta_address = address - view.address_size
            if meta_address % view.address_size != 0:
                return False

            try:
                if view.read_pointer(
                    meta_address
                ) not in pointers:
                    return False
            except ValueError:
                return False

            if get_function(
                view,
                view.read_pointer(
                    address
                )
            ) is None:
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
                bn.log.log_debug(
                    traceback.format_exc(),
                    'VirtualFunctionTable::search',
                )

                continue

            bn.log.log_debug(
                f'Defined virtual function table @ 0x{address:x}',
                'VirtualFunctionTable::search',
            )

        if task is not None:
            task.progress = f'{cls.__name__} search finished'
