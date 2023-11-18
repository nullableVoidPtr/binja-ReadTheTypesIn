from enum import IntEnum, IntFlag
from typing import Annotated, Optional
import binaryninja as bn
from ....types import CheckedTypeDataVar, Array, Enum
from ....types.annotation import DisplacementOffset
from ....utils import get_data_sections, get_function
from ..rtti.type_descriptor import TypeDescriptor
from ..rtti.base_class_descriptor import PMD

COMPRESSED_INT_LENGTH = [
    1, # 0
    2, # 1
    1, # 2
    3, # 3

    1, # 4
    2, # 5
    1, # 6
    4, # 7

    1, # 8
    2, # 9
    1, # 10
    3, # 11

    1, # 12
    2, # 13
    1, # 14
    5, # 15
]

def read_compressed_int(view: bn.BinaryView, address: int):
    length_bits = view.read_int(address, 1, False) & 0xF
    length = COMPRESSED_INT_LENGTH[length_bits]
    shift = 0 if length_bits == 15 else 32 - 7 * length
    return view.read_int(address + length - 4, 4, False) >> shift

class CompressedIntRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if not isinstance(_type, bn.IntegerType):
            return False

        return _type.altname == "COMPRESSED_INT"

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        for token in prefix:
            if token.text == 'COMPRESSED_INT':
                token.text = 'uint32_t'
                token.width = len(token.text)
                break

        value = read_compressed_int(view, address)
        token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.IntegerToken,
            hex(value),
            value,
        )

        return [
            bn.DisassemblyTextLine([
                *prefix,
                token
            ], address)
        ]

class UnwindMapEntryType(IntEnum):
    NO_UNWIND            = 0b00
    DTOR_WITH_OBJ        = 0b01
    DTOR_WITH_PTR_TO_OBJ = 0b10
    RVA                  = 0b11

class UnwindMapEntry4(CheckedTypeDataVar, members=[
    ('uint8_t', 'nextOffsetAndType'),
]):
    value_dependent = True
    virtual_relative_members = {
        'action': DisplacementOffset['void __cdecl (void)'],
    }

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0
        disp_type = bn.Type.int(4, False, "int __disp")

        entry_type = UnwindMapEntryType(
            read_compressed_int(self.view, self.address + offset) & 0b11
        )

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "nextOffsetAndType",
        )
        offset += length

        if entry_type != UnwindMapEntryType.NO_UNWIND:
            builder.insert(
                offset,
                disp_type,
                "action",
            )
            offset += 4

        if entry_type in [
            UnwindMapEntryType.DTOR_WITH_OBJ,
            UnwindMapEntryType.DTOR_WITH_PTR_TO_OBJ
        ]:
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                "object",
            )
            offset += length

        return builder.immutable_copy()

class UnwindMapRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if len(context) == 0:
            return False

        if not isinstance(_type, bn.IntegerType):
            return False

        if _type.altname != "COMPRESSED_INT":
            return False

        if context[-1].offset != 0:
            return False

        if not isinstance(context[-1].type, bn.StructureType):
            return False

        if len(context[-1].type.base_structures) == 0:
            return False

        return context[-1].type.base_structures[0].type.name == UnwindMapEntry4.alt_name

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        for token in prefix:
            if token.text == 'COMPRESSED_INT':
                token.text = 'uint32_t'
                token.width = len(token.text)
            elif token.text == 'nextOffsetAndType':
                token.text = 'nextOffset'
                token.width = len(token.text)

        value = read_compressed_int(view, address)
        next_offset = value >> 2
        entry_type = UnwindMapEntryType(value & 0b11)
        offset_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.IntegerToken,
            hex(value),
            value,
        )

        enum_token = bn.InstructionTextToken(
            bn.InstructionTextTokenType.EnumerationMemberToken,
            entry_type.name,
            int(entry_type),
        )

        return [
            bn.DisassemblyTextLine([
                *prefix,
                offset_token,
            ], address),
            bn.DisassemblyTextLine([
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TypeNameToken,
                    "uint8_t",
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    " ",
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    "Type",
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    " = ",
                ),
                enum_token,
            ], address),
        ]

class UwMap4(CheckedTypeDataVar, members=[
    ('uint8_t', 'numEntries'),
]):
    entries: list

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        num_entries = read_compressed_int(self.view, self.address)
        length_bits = self.view.read_int(self.address, 1, False) & 0xF
        offset = COMPRESSED_INT_LENGTH[length_bits]

        self.entries = []
        for i in range(num_entries):
            entry = UnwindMapEntry4.create(self.view, self.address + offset)
            self.entries.append(entry)
            offset += entry.type.width

        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "numEntries",
        )
        offset += length

        for i, entry in enumerate(self.entries):
            entry_type = entry.source.type
            builder.insert(
                offset,
                entry_type,
                f"entry{i}",
            )
            offset += entry_type.width

        return builder.immutable_copy()

class HandlerTypeHeader(IntFlag):
    HAS_ADJECTIVES = 0x01
    HAS_TYPE = 0x02
    HAS_CATCH_OBJ = 0x04
    CONT_IS_RVA= 0x08

class HandlerType4(CheckedTypeDataVar, members=[
    (Enum[HandlerTypeHeader, 'uint8_t'], 'header'),
]):
    value_dependent = True
    virtual_relative_members = {
        'pType': DisplacementOffset[TypeDescriptor],
        'pOfHandler': DisplacementOffset['void'],
    }

    header: Annotated[HandlerTypeHeader, 'header']

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 1
        disp_type = bn.Type.int(4, False, "int __disp")

        if HandlerTypeHeader.HAS_ADJECTIVES in self.header:
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                "adjectives",
            )
            offset += length

        if HandlerTypeHeader.HAS_TYPE in self.header:
            builder.insert(
                offset,
                disp_type,
                "pType",
            )
            offset += 4

        if HandlerTypeHeader.HAS_CATCH_OBJ in self.header:
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                "dispCatchObj",
            )
            offset += length

        builder.insert(
            offset,
            disp_type,
            "pOfHandler",
        )
        offset += 4

        cont_addr_count = (self['header'].value >> 4) & 0b11
        for i in range(cont_addr_count):
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                f"continuationAddress{i}",
            )
            offset += length

        return builder.immutable_copy()

class HandlerMap4(CheckedTypeDataVar, members=[
    ('uint8_t', 'numEntries'),
]):
    entries: list

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        num_entries = read_compressed_int(self.view, self.address)
        length_bits = self.view.read_int(self.address, 1, False) & 0xF
        offset = COMPRESSED_INT_LENGTH[length_bits]

        self.entries = []
        for i in range(num_entries):
            entry = HandlerType4.create(self.view, self.address + offset)
            self.entries.append(entry)
            offset += entry.type.width

        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "numEntries",
        )
        offset += length

        for i, entry in enumerate(self.entries):
            entry_type = entry.source.type
            builder.insert(
                offset,
                entry_type,
                f"entry{i}",
            )
            offset += entry_type.width

        return builder.immutable_copy()

class TryBlockMapEntry4(CheckedTypeDataVar, members=[
    ('uint8_t', 'tryLow'),
]):
    value_dependent = True
    virtual_relative_members = {
        'pHandlerArray': DisplacementOffset[HandlerMap4],
    }

    handler_array: HandlerMap4

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.handler_array = HandlerMap4.create(
            self.view,
            self.view.start + self.source['pHandlerArray'].value,
        )

    def mark_down_members(self):
        self.handler_array.mark_down()

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0
        disp_type = bn.Type.int(4, False, "int __disp")

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "tryLow",
        )
        offset += length

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "tryHigh",
        )
        offset += length

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "catchHigh",
        )
        offset += length

        builder.insert(
            offset,
            disp_type,
            "pHandlerArray",
        )
        offset += 4

        return builder.immutable_copy()

class TryBlockMap4(CheckedTypeDataVar, members=[
    ('uint8_t', 'numEntries'),
]):
    entries: list

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        num_entries = read_compressed_int(self.view, self.address)
        length_bits = self.view.read_int(self.address, 1, False) & 0xF
        offset = COMPRESSED_INT_LENGTH[length_bits]

        self.entries = []
        for i in range(num_entries):
            entry = TryBlockMapEntry4.create(self.view, self.address + offset)
            self.entries.append(entry)
            offset += entry.type.width

        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

    def mark_down_members(self):
        for entry in self.entries:
            entry.mark_down_members()

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "numEntries",
        )
        offset += length

        for i, entry in enumerate(self.entries):
            entry_type = entry.source.type
            builder.insert(
                offset,
                entry_type,
                f"entry{i}",
            )
            offset += entry_type.width

        return builder.immutable_copy()

class IPtoStateMapEntry4(CheckedTypeDataVar, members=[
    ('uint8_t', 'Ip'),
]):
    value_dependent = True

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "Ip",
        )
        offset += length

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "State",
        )
        offset += length

        return builder.immutable_copy()

class IPtoStateMap4(CheckedTypeDataVar, members=[
    ('uint8_t', 'numEntries'),
]):
    entries: list

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        num_entries = read_compressed_int(self.view, self.address)
        length_bits = self.view.read_int(self.address, 1, False) & 0xF
        offset = COMPRESSED_INT_LENGTH[length_bits]

        self.entries = []
        for i in range(num_entries):
            entry = IPtoStateMapEntry4.create(self.view, self.address + offset)
            self.entries.append(entry)
            offset += entry.type.width

        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = 0

        length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
        length = COMPRESSED_INT_LENGTH[length_bits]
        builder.insert(
            offset,
            bn.Type.int(length, False, "COMPRESSED_INT"),
            "numEntries",
        )
        offset += length

        for i, entry in enumerate(self.entries):
            entry_type = entry.source.type
            builder.insert(
                offset,
                entry_type,
                f"entry{i}",
            )
            offset += entry_type.width

        return builder.immutable_copy()

class FuncInfoHeader(IntFlag):
    IS_CATCH          = 0x01
    IS_SEPARATED      = 0x02
    BBT               = 0x04
    HAS_UNWIND_MAP    = 0x08
    HAS_TRY_BLOCK_MAP = 0x10
    EH                = 0x20
    NOEXCEPT          = 0x40

class FuncInfo4(CheckedTypeDataVar,
    members=[
        (Enum[FuncInfoHeader, 'uint8_t'], 'header'),
    ],
):
    value_dependent = True
    virtual_relative_members = {
        'pUnwindMap': DisplacementOffset[UnwindMapEntry4],
        'pTryBlockMap': DisplacementOffset[TryBlockMap4],
        'pIPtoStateMap': DisplacementOffset[IPtoStateMap4]
    }

    packed = True

    header: Annotated[FuncInfoHeader, 'header']
    BBTFlags: int
    unwind_map: Optional[UwMap4]
    try_block_map: Optional[TryBlockMap4]
    ip_to_state_map: Optional[IPtoStateMap4]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)

        self.unwind_map = None
        self.try_block_map = None
        self.ip_to_state_map = None

        value = self.source.value
        if 'pUnwindMap' in value:
            self.unwind_map = UwMap4.create(
                self.view,
                self.view.start + value['pUnwindMap'],
            )

        if 'pTryBlockMap' in value:
            self.try_block_map = TryBlockMap4.create(
                self.view,
                self.view.start + value['pTryBlockMap'],
            )

        if 'pIPtoStateMap' in value:
            self.ip_to_state_map = IPtoStateMap4.create(
                self.view,
                self.view.start + value['pIPtoStateMap'],
            )

    def mark_down_members(self):
        if self.unwind_map is not None:
            self.unwind_map.mark_down()

        if self.try_block_map is not None:
            self.try_block_map.mark_down()

        if self.ip_to_state_map is not None:
            self.ip_to_state_map.mark_down()

    @property
    def type(self) -> bn.Type:
        builder = bn.StructureBuilder.create()
        builder.packed = True
        builder.base_structures = [
            bn.BaseStructure(self.get_struct_ref(self.view), 0)
        ]

        offset = self.get_structure(self.view).width
        disp_type = bn.Type.int(4, False, "int __disp")
        if FuncInfoHeader.BBT in self.header:
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                "bbtFlags",
            )
            offset += length

        if FuncInfoHeader.HAS_UNWIND_MAP in self.header:
            builder.insert(
                offset,
                disp_type,
                "pUnwindMap",
            )
            offset += 4

        if FuncInfoHeader.HAS_TRY_BLOCK_MAP in self.header:
            builder.insert(
                offset,
                disp_type,
                "pTryBlockMap",
            )
            offset += 4

        builder.insert(
            offset,
            disp_type,
            "pIPtoStateMap",
        )
        offset += 4

        if FuncInfoHeader.IS_CATCH in self.header:
            length_bits = self.view.read_int(self.address + offset, 1, False) & 0xF
            length = COMPRESSED_INT_LENGTH[length_bits]
            builder.insert(
                offset,
                bn.Type.int(length, False, "COMPRESSED_INT"),
                "dispFrame",
            )
            offset += length

        return builder.immutable_copy()
