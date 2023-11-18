from typing import Optional, Generator, Self, Annotated
import traceback
import binaryninja as bn
from ....types import CheckedTypeDataVar, CheckedTypedef
from ....types.annotation import Array, DisplacementOffset

class ScopeTableEntry(CheckedTypeDataVar, members=[
    (DisplacementOffset['void'], 'BeginAddress'),
    (DisplacementOffset['void'], 'EndAddress'),
    (DisplacementOffset['void'], 'HandlerAddress'),
    (DisplacementOffset['void'], 'JumpTarget'),
]):
    begin: Annotated[int, 'BeginAddress']
    end: Annotated[int, 'EndAddress']
    handler: Annotated[int, 'HandlerAddress']
    target: Annotated[int, 'JumpTarget']

class ScopeTable(CheckedTypeDataVar, members=[
    ('uint32_t', 'Count'),
    (Array[ScopeTableEntry, ...], 'ScopeRecord'),
]):
    name = 'SCOPE_TABLE'
    alt_name = '_SCOPE_TABLE'

    length: Annotated[int, 'Count']
    scopes: Annotated[list[ScopeTableEntry], 'ScopeRecord']

    def get_array_length(self, name: str):
        if name == 'ScopeRecord':
            return self['Count']

        return super().get_array_length(name)

    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.scopes)

    def __getitem__(self, key: str | int):
        if isinstance(key, int):
            return self.scopes[key]

        return super().__getitem__(key)

class ScopeHandlerRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if len(context) == 0:
            return False

        if _type.altname != "int __disp":
            return False

        if not bn.DataRenderer.is_type_of_struct_name(
            context[-1].type,
            ScopeTableEntry.alt_name,
            context[:-1],
        ):
            return False
        
        return context[-1].offset == ScopeTableEntry.get_structure(view)['HandlerAddress'].offset

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        for token in prefix:
            if token.text == 'int __disp':
                token.text = 'int'
                token.width = len(token.text)
                break

        value = view.typed_data_accessor(address, _type).value
        target = DisplacementOffset.resolve_offset(view, value)

        if value == 0:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.KeywordToken,
                "nullptr",
                value,
            )
        elif value == 1:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.EnumerationMemberToken,
                "EXCEPTION_EXECUTE_HANDLER",
                value,
            )
        elif (var := view.get_function_at(target)) is not None:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.CodeSymbolToken,
                var.name or f"sub_{target:x}",
                target,
            )
        elif (var := view.get_data_var_at(target)) is not None:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.DataSymbolToken,
                var.name or f"data_{target:x}",
                target,
            )
        else:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.IntegerToken,
                hex(value),
                target,
            )

        return [
            bn.DisassemblyTextLine([
                *prefix,
                token,
            ], address)
        ]
