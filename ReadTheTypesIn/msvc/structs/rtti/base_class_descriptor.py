from typing import Optional
from enum import IntFlag
import binaryninja as bn
from ....types import CheckedTypeDataVar, RTTIOffsetType, NamedCheckedTypeRef
from ...utils import resolve_rtti_offset
from .type_descriptor import TypeDescriptor

class PMD(CheckedTypeDataVar, members=[
    ('int', 'mdisp'),
    ('int', 'pdisp'),
    ('int', 'vdisp'),
]):
    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.mdisp = self['mdisp'].value
        self.pdisp = self['pdisp'].value
        self.vdisp = self['vdisp'].value

class BCDAttributes(IntFlag):
    NOTVISIBLE          = 0x00000001
    AMBIGUOUS           = 0x00000002
    PRIVORPROTBASE      = 0x00000004
    PRIVORPROTINCOMPOBJ = 0x00000008
    VBOFCONTOBJ         = 0x00000010
    NONPOLYMORPHIC      = 0x00000020
    HASPCHD             = 0x00000040

class BaseClassDescriptor(CheckedTypeDataVar,
    members=[
        (RTTIOffsetType[TypeDescriptor], 'pTypeDescriptor'),
        ('unsigned long', 'numContainedBases'),
        (PMD, 'where'),
        ('unsigned long', 'attributes'),
        (RTTIOffsetType[
            NamedCheckedTypeRef['_RTTIClassHierarchyDescriptor']
        ], 'pClassDescriptor'),
    ],
):
    name = '_RTTIBaseClassDescriptor'
    alt_name = '_s_RTTIBaseClassDescriptor'

    type_descriptor: TypeDescriptor
    num_contained_bases: int
    where: PMD
    attributes: BCDAttributes
    class_hierarchy_descriptor: Optional['ClassHierarchyDescriptor']

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.type_descriptor = self['pTypeDescriptor']
        self.num_contained_bases = self['numContainedBases'].value
        self.where = self['where']
        self.attributes = BCDAttributes(self['attributes'].value)
        if BCDAttributes.HASPCHD in self.attributes:
            self.class_hierarchy_descriptor = self['pClassDescriptor']
        else:
            self.class_hierarchy_descriptor = None

    @property
    def type_name(self):
        return self.type_descriptor.type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        location = f'({self.where.mdisp},{self.where.pdisp},{self.where.vdisp},{self.attributes})'
        return f"{self.type_name.name}::`RTTI Base Class Descriptor at {location}'"

    @property
    def virtual(self) -> bool:
        return BCDAttributes.VBOFCONTOBJ in self.attributes

class BaseClassArray(CheckedTypeDataVar,
    members=[
        (RTTIOffsetType[BaseClassDescriptor], 'arrayOfBaseClassDescriptors'),
    ],
):
    name = '_RTTIBaseClassArray'
    alt_name = '_s_RTTIBaseClassArray'

    length: int
    base_class_array: list[BaseClassDescriptor]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int, length: int):
        super().__init__(view, source)
        self.length = length
        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

        self.base_class_descs = [
            BaseClassDescriptor.create(
                self.view,
                resolve_rtti_offset(self.view, self.source[i].value)
            )
            for i in range(len(self))
        ]

    @property
    def type(self):
        pointer_type = self.get_user_struct(self.view)['arrayOfBaseClassDescriptors'].type
        return bn.Type.array(
            pointer_type,
            len(self),
        )

    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.base_class_descs)

    def __contains__(self, value):
        return value in self.base_class_descs

    def __getitem__(self, key: str | int):
        if isinstance(key, int):
            return self.base_class_descs[key]

        if key == 'arrayOfBaseClassDescriptors':
            return self.base_class_descs

        return super().__getitem__(key)

    @property
    def type_name(self):
        return self[0].type_name

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        return f"{self.type_name.name}::`RTTI Base Class Array'"

    def mark_down_members(self):
        pointer_type = self.get_user_struct(self.view)['arrayOfBaseClassDescriptors'].type
        for i, bcd in enumerate(self.base_class_descs):
            bcd.mark_down()
            self.view.add_user_data_ref(
                self.address + (i * pointer_type.width),
                bcd.address,
            )

class BaseClassArrayRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, address, _type, context):
        if _type.type_class is not bn.TypeClass.ArrayTypeClass:
            return False

        if (sym := view.get_symbol_at(address)) is not None and \
            sym.name.endswith("::`RTTI Base Class Array'"):
            return True

        return False

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        offsets = view.typed_data_accessor(address, _type)

        type_tokens = [prefix[0]]
        if type_tokens[0].type == bn.InstructionTextTokenType.TypeNameToken:
            type_tokens.append(prefix[1])

        new_prefix = [
            bn.InstructionTextToken(
                bn.InstructionTextTokenType.TypeNameToken,
                BaseClassArray.name,
            )
        ]

        for token in prefix[len(type_tokens):]:
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

        array_lines = []
        for i, accessor in enumerate(offsets):
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


        return [
            bn.DisassemblyTextLine(
                new_prefix, address
            ),
            bn.DisassemblyTextLine([
                open_brace_token,
            ], address),
            bn.DisassemblyTextLine([
                indent_token,
                *type_tokens,
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.TextToken,
                    ' ',
                ),
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.FieldNameToken,
                    'arrayOfBaseClassDescriptors',
                    typeNames=[BaseClassArray.alt_name, 'arrayOfBaseClassDescriptors']
                ),
                open_bracket_token,
                close_bracket_token,
                assign_token,
            ], address),
            bn.DisassemblyTextLine([
                indent_token,
                open_brace_token,
            ], address),
            *array_lines,
            bn.DisassemblyTextLine([
                indent_token,
                close_brace_token,
            ], address + _type.width),
            bn.DisassemblyTextLine([
                close_brace_token,
            ], address + _type.width),
        ]
