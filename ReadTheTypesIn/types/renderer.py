from enum import Flag
import binaryninja as bn
from .var import CheckedTypeDataVar
from .annotation import DisplacementOffset, Array, Enum

class RelativeOffsetRenderer(bn.DataRenderer):
    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if not isinstance(_type, bn.IntegerType):
            return False

        # TODO unique fake attributes for each subclass
        return _type.altname == "int __disp"

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
                token
            ], address)
        ]

class EnumRenderer(bn.DataRenderer):
    def find_enum_type(self, view, _type, context):
        if (container_type := next(
            (
                scls
                for scls in CheckedTypeDataVar.__subclasses__()
                if bn.DataRenderer.is_type_of_struct_name(
                    context[-1].type,
                    scls.alt_name,
                    context[:-1],
                )
            )
        , None)) is None:
            if isinstance(context[-1].type, bn.StructureType):
                if len(context[-1].type.base_structures) != 1:
                    return None

                base = context[-1].type.base_structures[0].type
                if (container_type := next(
                    (
                        scls
                        for scls in CheckedTypeDataVar.__subclasses__()
                        if scls.alt_name == base.name
                    ),
                    None,
                )) is None:
                    return None
            else:
                return None

        member_offset = context[-1].offset
        user_struct = container_type.get_user_struct(view)
        try:
            if (member := user_struct.member_at_offset(member_offset)) is None:
                return None
        except ValueError:
            return None

        return Enum.get_type(container_type.member_map.get(member.name))

    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if len(context) == 0:
            return False

        return self.find_enum_type(view, _type, context) is not None

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        enum_type = self.find_enum_type(view, _type, context)
        value = enum_type(view.typed_data_accessor(address, _type).value)

        tokens = []
        if value.name is None:
            if int(value) == 0:
                tokens.append(
                    bn.InstructionTextToken(
                        bn.InstructionTextTokenType.IntegerToken,
                        "0",
                        0,
                    )
                )
            else:
                tokens.append(
                    bn.InstructionTextToken(
                        bn.InstructionTextTokenType.IntegerToken,
                        hex(value),
                        int(value),
                    )
                )
        elif isinstance(value, Flag):
            for i, flag in enumerate(value):
                if i != 0:
                    tokens.append(
                        bn.InstructionTextToken(
                            bn.InstructionTextTokenType.TextToken,
                            ' | ',
                        )
                    )

                tokens.append(
                    bn.InstructionTextToken(
                        bn.InstructionTextTokenType.EnumerationMemberToken,
                        flag.name,
                        int(flag),
                    )
                )
        else:
            tokens.append(
                bn.InstructionTextToken(
                    bn.InstructionTextTokenType.EnumerationMemberToken,
                    value.name,
                    int(value),
                )
            )

        return [
            bn.DisassemblyTextLine([
                *prefix,
                *tokens,
            ], address)
        ]
