from typing import Optional, Generator, Self
import traceback
import binaryninja as bn
from ....types import CheckedTypeDataVar, CheckedTypedef, EHOffsetType
from ...utils import get_data_sections
from .handler_type import HandlerType

class UnwindMapEntry(CheckedTypeDataVar, members=[
    ('int', 'toState'),
    (EHOffsetType['void (__cdecl *)(void)'], 'action'),
]):
    name = "UnwindMapEntry"
    alt_name = "_s_UnwindMapEntry"

    to_state: int

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.to_state = self['toState'].value
        self.action = self['action']

class TryBlockMapEntry(CheckedTypeDataVar, members=[
    ('int', 'tryLow'),
    ('int', 'tryHigh'),
    ('int', 'catchHigh'),
    ('int', 'nCatches'),
    (EHOffsetType[HandlerType], 'pHandlerArray'),
]):
    name = "TryBlockMapEntry"
    alt_name = "_s_TryBlockMapEntry"

    try_low: int
    try_high: int
    catch_high: int
    handlers: list[HandlerType]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)

        self.try_low = self['tryLow'].value
        self.try_high = self['tryHigh'].value
        self.catch_high = self['catchHigh'].value

        handler_type_width = HandlerType.get_user_struct(self.view).width
        handler_array_address = self['pHandlerArray'].address
        self.handlers = [
            HandlerType.create(self.view, handler_array_address + (i * handler_type_width))
            for i in range(self['nCatches'].value)
        ]

    def mark_down_members(self):
        if len(self.handlers) > 0:
            self.view.define_user_data_var(
                self['pHandlerArray'].address,
                bn.Type.array(
                    HandlerType.get_typedef_ref(self.view),
                    len(self.handlers),
                ),
            )
            for entry in self.handlers:
                entry.mark_down_members()

class IpToStateMapEntry(CheckedTypeDataVar, members=[
    ('unsigned int', 'Ip'),
    ('int', 'State'),
]):
    name = "IpToStateMapEntry"
    alt_name = "_s_IpToStateMapEntry"

    ip: int
    state: int

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.ip = self['Ip'].value
        self.state = self['State'].value

class ESTypeList(CheckedTypeDataVar, members=[
    ('int', 'nCount'),
    (EHOffsetType[HandlerType], 'pTypeArray'),
]):
    name = "ESTypeList"
    alt_name = "_s_ESTypeList"

    types: list[HandlerType]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)

        handler_type_width = HandlerType.get_user_struct(self.view).width
        type_array_address = self['pTypeArray'].address
        self.types = [
            HandlerType.create(self.view, type_array_address + (i * handler_type_width))
            for i in range(self['nCount'].value)
        ]

    def mark_down_members(self):
        if len(self.types) > 0:
            self.view.define_user_data_var(
                self['pTypeArray'].address,
                bn.Type.array(
                    HandlerType.get_typedef_ref(self.view),
                    len(self.types),
                ),
            )
            for entry in self.types:
                entry.mark_down_members()

FUNC_INFO_MEMBERS = [
    ('unsigned int', 'magicNumberAndBBTFlag'),
    ('int', 'maxState'),
    (EHOffsetType[UnwindMapEntry], 'pUnwindMap'),
    ('unsigned int', 'nTryBlocks'),
    (EHOffsetType[TryBlockMapEntry], 'pTryBlockMap'),
    ('unsigned int', 'nIPMapEntries'),
    (EHOffsetType[IpToStateMapEntry], 'pIPtoStateMap'),
]

FUNC_INFO_MAGIC_NUMBERS = [
    b'\x20\x05\x93\x19',
    b'\x21\x05\x93\x19',
    b'\x22\x05\x93\x19',
    b'\x00\x40\x99\x01',
]

class _FuncInfoBase():
    view: bn.BinaryView

    bbt_flag: int
    max_state: int
    unwind_map: list[UnwindMapEntry]
    try_blocks: list[TryBlockMapEntry]
    ip_map_entries: list[IpToStateMapEntry]
    es_type_list: ESTypeList

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.bbt_flag = self['magicNumberAndBBTFlag'].value & 7
        self.max_state = self['maxState'].value

        if self['pUnwindMap'].to_state > self.max_state:
            raise ValueError('Invalid unwind map')

        unwind_entry_width = UnwindMapEntry.get_user_struct(self.view).width
        unwind_map_address = self['pUnwindMap'].address
        self.unwind_map = [
            UnwindMapEntry.create(
                self.view,
                unwind_map_address + (i * unwind_entry_width),
            )
            for i in range(self.max_state)
        ]

        try_block_map_length = self['nTryBlocks'].value
        if try_block_map_length == 0:
            self.try_blocks = []
        else:
            try_block_entry_width = TryBlockMapEntry.get_user_struct(self.view).width
            try_block_map_address = self['pTryBlockMap'].address
            self.try_blocks = [
                TryBlockMapEntry.create(
                    self.view,
                    try_block_map_address + (i * try_block_entry_width),
                )
                for i in range(try_block_map_length)
            ]

        ip_map_length = self['nIPMapEntries'].value
        if ip_map_length == 0:
            self.ip_map_entries = []
        else:
            ip_entry_width = IpToStateMapEntry.get_user_struct(self.view).width
            ip_map_address = self['pIPtoStateMap'].address
            self.ip_map_entries = [
                IpToStateMapEntry.create(
                    self.view,
                    ip_map_address + (i * ip_entry_width),
                )
                for i in range(ip_map_length)
            ]

    def mark_down_members(self):
        if self.max_state > 0:
            self.view.define_user_data_var(
                self['pUnwindMap'].address,
                bn.Type.array(
                    UnwindMapEntry.get_typedef_ref(self.view),
                    self.max_state,
                ),
            )
            for entry in self.unwind_map:
                entry.mark_down_members()

        if len(self.try_blocks) > 0:
            self.view.define_user_data_var(
                self['pTryBlockMap'].address,
                bn.Type.array(
                    TryBlockMapEntry.get_typedef_ref(self.view),
                    len(self.try_blocks),
                ),
            )
            for entry in self.try_blocks:
                entry.mark_down_members()

        if len(self.ip_map_entries) > 0:
            self.view.define_user_data_var(
                self['pIPtoStateMap'].address,
                bn.Type.array(
                    IpToStateMapEntry.get_typedef_ref(self.view),
                    len(self.ip_map_entries),
                ),
            )
            for entry in self.ip_map_entries:
                entry.mark_down_members()

class _FuncInfo(_FuncInfoBase, CheckedTypeDataVar,
    members=[
        *FUNC_INFO_MEMBERS,
        (EHOffsetType[ESTypeList], 'pESTypeList'),
        ('int', 'EHFlags'),
    ],
):
    name = '_s_FuncInfo'
    alt_name = '_s__FuncInfo'

class _FuncInfo2(_FuncInfoBase, CheckedTypeDataVar,
    members=[
        *FUNC_INFO_MEMBERS,
        ('int', 'pUnwindHelp'),
        (EHOffsetType[ESTypeList], 'pESTypeList'),
        ('int', 'EHFlags'),
    ],
):
    name = '_s_FuncInfo2'
    alt_name = '_s__FuncInfo2'

class FuncInfo(CheckedTypedef):
    name = '_FuncInfo'

    @classmethod
    def get_actual_type(cls, view: bn.BinaryView) -> type[_FuncInfoBase]:
        return _FuncInfo2 if EHOffsetType.is_relative(view) else _FuncInfo

    @classmethod
    def search(
        cls, view: bn.BinaryView,
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        user_struct = cls.get_user_struct(view)

        matches = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_func_info(accessor: bn.TypedDataAccessor) -> bool:
            if accessor.address % cls.get_alignment(view) != 0:
                return False

            if accessor['maxState'].value == 0:
                return False

            if accessor['maxState'].value >= 0xffff:
                return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            accessor = view.typed_data_accessor(address, user_struct)
            if is_potential_func_info(accessor):
                matches.append(accessor)

            return True

        for pattern in FUNC_INFO_MAGIC_NUMBERS:
            for section in get_data_sections(view):
                view.find_all_data(
                    section.start, section.end,
                    pattern,
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
                    f'Failed to define func info @ 0x{accessor.address:x}',
                    'FuncInfo::search',
                )
                bn.log.log_debug(
                    traceback.format_exc(),
                    'FuncInfo::search',
                )

                continue

            bn.log.log_debug(
                f'Defined complete func info @ 0x{accessor.address:x}',
                'FuncInfo::search',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'
