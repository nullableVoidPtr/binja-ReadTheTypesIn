from typing import Optional, Generator, Self
from enum import IntFlag
import traceback
import binaryninja as bn
from ....types import CheckedTypeDataVar, RTTIOffsetType
from ...utils import get_data_sections, encode_rtti_offset, resolve_rtti_offset, get_function
from ..rtti.type_descriptor import TypeDescriptor
from ..rtti.base_class_descriptor import PMD

PATTERN_SHIFT_SIZE = 2

class CTProperties(IntFlag):
    CT_IsSimpleType    = 0x00000001
    CT_ByReferenceOnly = 0x00000002
    CT_HasVirtualBase  = 0x00000004
    CT_IsWinRTHandle   = 0x00000008
    CT_IsStdBadAlloc   = 0x00000010

class CatchableType(CheckedTypeDataVar,
    members=[
        ('unsigned int', 'properties'),
        (RTTIOffsetType[TypeDescriptor], 'pType'),
        (PMD, 'thisDisplacement'),
        ('int', 'sizeOrOffset'),
        (RTTIOffsetType[
            'void __cdecl (void *)'
        ], 'copyFunction'),
    ],
):
    name = '_CatchableType'
    alt_name = '_s_CatchableType'

    properties: CTProperties
    type_descriptor: TypeDescriptor
    this_displacement: PMD
    size_or_offset: int
    copy_function: bn.Function

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.properties = CTProperties(self['properties'].value)
        self.type_descriptor = self['pType']
        self.this_displacement = self['thisDisplacement']
        self.size_or_offset = self['sizeOrOffset'].value
        self.copy_function = self['copyFunction']

    @property
    def type_name(self):
        return self.type_descriptor.type_name

    @property
    def symbol_name(self):
        return f"{self.type_name.name} `EH Catchable Type'"

    @classmethod
    def search_with_type_descriptors(
        cls, view: bn.BinaryView,
        type_descriptors: list[TypeDescriptor],
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        type_desc_offsets = set(
            encode_rtti_offset(
                view,
                type_desc.address
            )
            for type_desc in type_descriptors
        )

        user_struct = cls.get_user_struct(view)
        ptype_offset = user_struct['pType'].offset

        matches = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_catchable_type(accessor: bn.TypedDataAccessor) -> bool:
            if accessor.address % cls.get_alignment(view) != 0:
                return False

            offset = accessor['pType'].value
            if offset not in type_desc_offsets:
                return False

            if get_function(
                view,
                resolve_rtti_offset(
                    view,
                    accessor['copyFunction'].value,
                )
            ) is None:
                return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            address -= PATTERN_SHIFT_SIZE
            accessor = view.typed_data_accessor(address - ptype_offset, user_struct)
            if is_potential_catchable_type(accessor):
                matches.append(accessor)

            return True

        patterns = set(
            (address >> (8 * PATTERN_SHIFT_SIZE)).to_bytes(
                view.address_size - PATTERN_SHIFT_SIZE,
                'little' if view.endianness is bn.Endianness.LittleEndian else 'big')
            for address in type_desc_offsets
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
                    'CatchableType::search_with_base_class_descriptors',
                )
                bn.log.log_debug(
                    traceback.format_exc(),
                    'CatchableType::search_with_base_class_descriptors',
                )

                continue

            bn.log.log_debug(
                f'Defined catchable type @ 0x{accessor.address:x}',
                'CatchableType::search_with_base_class_descriptors',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'

class CatchableTypeArray(CheckedTypeDataVar,
    members=[
        ('int', 'nCatchableTypes'),
        (RTTIOffsetType[CatchableType], 'arrayOfCatchableTypes'),
    ],
):
    name='_CatchableTypeArray'
    alt_name='_s_CatchableTypeArray'

    length: int
    catchable_type_array: list[CatchableType]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.length = self['nCatchableTypes'].value
        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

        self.catchable_type_array = [
            CatchableType.create(
                self.view,
                resolve_rtti_offset(
                    self.view,
                    self.source['arrayOfCatchableTypes'][i].value
                )
            )
            for i in range(len(self))
        ]

    @property
    def type(self):
        struct = self.get_user_struct(self.view).mutable_copy()
        struct.replace(
            1,
            bn.Type.array(
                self.get_user_struct(self.view)['arrayOfCatchableTypes'].type,
                len(self),
            ),
            'arrayOfCatchableTypes',
        )
        return struct.immutable_copy()


    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.catchable_type_array)

    def __getitem__(self, key: str | int):
        if isinstance(key, int):
            return self.catchable_type_array[key]

        if key == 'arrayOfCatchableTypes':
            return self.catchable_type_array

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self[0].type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name.name} `EH Catchable Type Array'"

    def mark_down_members(self):
        user_struct = self.get_user_struct(self.view)
        count_type = user_struct['nCatchableTypes'].type
        pointer_type = user_struct['arrayOfCatchableTypes'].type
        for i, ct in enumerate(self.catchable_type_array):
            ct.mark_down()
            self.view.add_user_data_ref(
                self.address + count_type.width + (i * pointer_type.width),
                ct.address,
            )

    @classmethod
    def search(
        cls,
        view: bn.BinaryView,
        catchable_types: list[CatchableType],
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        ct_offsets = set(
            encode_rtti_offset(
                view,
                ct.address
            )
            for ct in catchable_types
        )

        user_struct = cls.get_user_struct(view)
        count_type = user_struct['nCatchableTypes'].type
        pointer_type = user_struct['arrayOfCatchableTypes'].type

        elements = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            address -= PATTERN_SHIFT_SIZE
            accessor = view.typed_data_accessor(
                address,
                pointer_type,
            )
            if accessor.value in ct_offsets:
                elements.append(address)

            return True

        patterns = set(
            (offset >> (8 * PATTERN_SHIFT_SIZE)).to_bytes(
                pointer_type.width - PATTERN_SHIFT_SIZE,
                'little' if view.endianness is bn.Endianness.LittleEndian else 'big')
            for offset in ct_offsets
        )

        for pattern in patterns:
            for section in get_data_sections(view):
                view.find_all_data(
                    section.start, section.end,
                    pattern,
                    progress_func=update_progress if task is not None else None,
                    match_callback=process_match,
                )

        starts = set()
        for element in sorted(elements, reverse=True):
            starts.add(element)

            after = element + pointer_type.width
            if after in starts:
                starts.remove(after)

        arrays = []
        for start in starts:
            try:
                struct_address = start - count_type.width
                count = view.typed_data_accessor(
                    struct_address,
                    count_type
                ).value
                if count <= 0:
                    continue

                for address in range(
                    start,
                    start + (pointer_type.width * count),
                    pointer_type.width
                ):
                    offset = view.typed_data_accessor(
                        address,
                        pointer_type,
                    ).value
                    if offset not in ct_offsets:
                        try:
                            CatchableType.create(
                                view,
                                resolve_rtti_offset(view, offset)
                            )
                        except ValueError:
                            break
                else:
                    arrays.append(struct_address)

            except ValueError:
                continue

        for address in arrays:
            try:
                col = cls.create(view, address)
                yield col
            except Exception:
                bn.log.log_warn(
                    f'Failed to define catchable type @ 0x{address:x}',
                    'CatchableTypeArray::search',
                )
                bn.log.log_debug(
                    traceback.format_exc(),
                    'CatchableTypeArray::search',
                )

                continue

            bn.log.log_debug(
                f'Defined catchable type @ 0x{address:x}',
                'CatchableTypeArray::search',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'


class CatchableTypeArrayRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, address, _type, context):
        if (sym := view.get_symbol_at(address)) is not None and \
            sym.name.endswith(" `EH Catchable Type Array'"):
            return True

        return False

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        struct = view.typed_data_accessor(address, _type)

        new_prefix = [
            bn.InstructionTextToken(
                bn.InstructionTextTokenType.TypeNameToken,
                CatchableTypeArray.name,
            )
        ]

        for token in prefix[1:]:
            if token.type in [
                bn.InstructionTextTokenType.BraceToken,
                bn.InstructionTextTokenType.ArrayIndexToken
            ]:
                continue

            new_prefix.append(token)

        indent_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.TextToken,
            '    ',
        )
        open_brace_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.BraceToken,
            '{'
        )
        close_brace_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.BraceToken,
            '}'
        )
        open_bracket_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.BraceToken,
            '['
        )
        close_bracket_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.BraceToken,
            ']'
        )
        assign_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.TextToken,
            ' = ',
        )

        count_lines = [
            bn.DisassemblyTextLine([
                indent_token,
                *struct['nCatchableTypes'].type.get_tokens_before_name(),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    ' ',
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.FieldNameToken,
                    'nCatchableTypes',
                    typeNames=[CatchableTypeArray.alt_name, 'nCatchableTypes']
                ),
                assign_token,
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.IntegerToken,
                    hex(struct['nCatchableTypes'].value),
                    struct['nCatchableTypes'].value,
                ),
            ], address),
        ]

        array_lines = [
            bn.DisassemblyTextLine([
                indent_token,
                *struct['arrayOfCatchableTypes'].type.get_tokens_before_name(),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    ' ',
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.FieldNameToken,
                    'arrayOfCatchableTypes',
                    typeNames=[CatchableTypeArray.alt_name, 'arrayOfCatchableTypes']
                ),
                open_bracket_token,
                close_bracket_token,
                assign_token,
            ], address),
            bn.DisassemblyTextLine([
                indent_token,
                open_brace_token,
            ], address),
        ]
        for i, accessor in enumerate(struct['arrayOfCatchableTypes']):
            offset = accessor.value
            target = resolve_rtti_offset(view, offset)

            if (var := view.get_data_var_at(target)) is not None:
                value_token = bn.InstructionTextToken(
                    bn.InstructionTextTokenType.DataSymbolToken,
                    var.name or f"data_{target:x}",
                    target,
                )
            else:
                value_token = bn.InstructionTextToken(
                    bn.InstructionTextTokenType.IntegerToken,
                    hex(offset),
                    target,
                )

            array_lines.append(
                bn.DisassemblyTextLine([
                    indent_token,
                    indent_token,
                    open_bracket_token,
                    bn.InstructionTextToken(
                        bn.InstructionTextTokenType.IntegerToken,
                        hex(i)
                    ),
                    close_bracket_token,
                    assign_token,
                    value_token,
                ], accessor.address)
            )
        array_lines.append(
            bn.DisassemblyTextLine([
                indent_token,
                close_brace_token,
            ], address + _type.width),
        )


        return [
            bn.DisassemblyTextLine(
                new_prefix, address
            ),
            bn.DisassemblyTextLine([
                open_brace_token,
            ], address),
            *count_lines,
            *array_lines,
            bn.DisassemblyTextLine([
                close_brace_token,
            ], address + _type.width),
        ]