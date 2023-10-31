from enum import Flag
import binaryninja as bn
from .var import CheckedTypeDataVar
from .annotation import OffsetType, RTTIOffsetType, EHOffsetType, Array, Enum

class RelativeOffsetRenderer(bn.DataRenderer):
    def get_relative_offset_member(self, view, _type, context):
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
            return None

        member_offset = context[-1].offset
        user_struct = container_type.get_user_struct(view)
        if (member := user_struct.member_at_offset(member_offset)) is None:
            return None

        if member.type != _type:
            return None

        return OffsetType.get_origin(container_type.member_map.get(member.name))

    def get_relative_offset_element(self, view, _type, context):
        if len(context) < 2:
            return None

        array = context[-1]
        if not isinstance(array.type, bn.ArrayType):
            return None

        struct = context[-2]
        if isinstance(struct.type, bn.NamedTypeReferenceType):
            # TODO CheckedTypedef
            if (container_type := next(
                (
                    scls
                    for scls in CheckedTypeDataVar.__subclasses__()
                    if bn.DataRenderer.is_type_of_struct_name(
                        struct.type,
                        scls.alt_name,
                        struct[:-2],
                    )
                )
            , None)) is None:
                return None

            member_offset = struct.offset
            user_struct = container_type.get_user_struct(view)
            if (member := user_struct.member_at_offset(member_offset)) is None:
                return None

            return OffsetType.get_origin(container_type.member_map.get(member.name))

        if isinstance(struct.type, bn.StructureType):
            if len(struct.type.base_structures) != 1:
                return None

            base = struct.type.base_structures[0].type
            if (container_type := next(
                (
                    scls
                    for scls in CheckedTypeDataVar.__subclasses__()
                    # FIXME
                    if scls.alt_name == base.name
                ),
                None,
            )) is None:
                return None

            last_member_type = container_type.members[-1][0]
            if not Array.is_flexible(last_member_type):
                return None

            return OffsetType.get_origin(Array.get_element_type(last_member_type))

        return None

    def perform_is_valid_for_data(self, ctxt, view, _, _type, context):
        if not RTTIOffsetType.is_relative(view) and not EHOffsetType.is_relative(view):
            return False

        if len(context) == 0:
            return False

        return self.get_relative_offset_member(view, _type, context) is not None or \
			self.get_relative_offset_element(view, _type, context) is not None

    def perform_get_lines_for_data(self, ctxt, view, address, _type, prefix, width, context):
        value = view.typed_data_accessor(address, _type).value
        offset_type = self.get_relative_offset_member(view, _type, context)
        if offset_type is None:
            offset_type = self.get_relative_offset_element(view, _type, context)
        assert offset_type is not None

        target = offset_type.resolve_offset(view, value)

        if value == 0:
            token = bn.InstructionTextToken(
                bn.InstructionTextTokenType.KeywordToken,
                "nullptr",
                target,
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
            return None

        member_offset = context[-1].offset
        user_struct = container_type.get_user_struct(view)
        if (member := user_struct.member_at_offset(member_offset)) is None:
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
