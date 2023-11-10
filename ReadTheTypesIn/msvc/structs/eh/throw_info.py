from typing import Optional, Generator, Self, Annotated
import traceback
import binaryninja as bn
from ....types import CheckedTypeDataVar, RTTIOffsetType
from ....utils import get_data_sections, get_function
from .catchable_type import CatchableTypeArray

PATTERN_SHIFT_SIZE = 2

class ThrowInfo(CheckedTypeDataVar,
    members=[
        ('unsigned long', 'attributes'),
        (RTTIOffsetType[
            'void __cdecl (void *)'
        ], 'pmfnUnwind'),
        (RTTIOffsetType[
            'int __cdecl (...)'
        ], 'pForwardCompat'),
        (RTTIOffsetType[CatchableTypeArray], 'pCatchableTypeArray'),
    ]
):
    name = '_ThrowInfo'
    alt_name = '_s_ThrowInfo'

    attributes: Annotated[int, 'attributes']
    member_unwind: Annotated[bn.Function, 'pmfnUnwind']
    forward_compat: Annotated[bn.Function, 'pForwardCompat']
    catchable_type_array: Annotated[CatchableTypeArray, 'pCatchableTypeArray']

    def __getitem__(self, key: str):
        if key == 'pCatchableTypeArray':
            return CatchableTypeArray.create(
                self.view,
                RTTIOffsetType.resolve_offset(
                    self.view,
                    self.source[key].value
                ),
            )

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self.catchable_type_array[0].type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name.name} `EH Throw Info'"

    @classmethod
    def search_with_catchable_type_arrays(
        cls, view: bn.BinaryView,
        catchable_type_arrays: list[CatchableTypeArray],
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        cta_offsets = set(
            RTTIOffsetType.encode_offset(
                view,
                cta.address
            )
            for cta in catchable_type_arrays
        )

        user_struct = cls.get_user_struct(view)
        array_offset = user_struct['pCatchableTypeArray'].offset

        matches = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_throw_info(accessor: bn.TypedDataAccessor) -> bool:
            if accessor.address % cls.get_alignment(view) != 0:
                return False

            offset = accessor['pCatchableTypeArray'].value
            if offset not in cta_offsets:
                return False

            if get_function(
                view,
                RTTIOffsetType.resolve_offset(
                    view,
                    accessor['pmfnUnwind'].value,
                )
            ) is None:
                return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            address -= PATTERN_SHIFT_SIZE
            accessor = view.typed_data_accessor(address - array_offset, user_struct)
            if is_potential_throw_info(accessor):
                matches.append(accessor)

            return True

        patterns = set(
            (address >> (8 * PATTERN_SHIFT_SIZE)).to_bytes(
                view.address_size - PATTERN_SHIFT_SIZE,
                'little' if view.endianness is bn.Endianness.LittleEndian else 'big')
            for address in cta_offsets
        )

        for pattern in patterns:
            for section in get_data_sections(view):
                view.find_all_data(
                    section.start, section.end,
                    pattern,
                    progress_func=update_progress if task is not None else None,
                    match_callback=process_match,
                )

        for accessor in matches:
            try:
                col = cls.create(view, accessor)
                yield col
            except Exception:
                bn.log.log_warn(
                    f'Failed to define catchable type @ 0x{accessor.address:x}',
                    'ThrowInfo::search_with_catchable_type_arrays',
                )
                bn.log.log_debug(
                    traceback.format_exc(),
                    'ThrowInfo::search_with_catchable_type_arrays',
                )

                continue

            bn.log.log_debug(
                f'Defined catchable type @ 0x{accessor.address:x}',
                'ThrowInfo::search_with_catchable_type_arrays',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'
