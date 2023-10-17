import binaryninja as bn
from ...types import CheckedTypeDataVar, RTTIOffsetType, NamedCheckedTypeRef
from ..utils import resolve_rtti_offset
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

class BaseClassDescriptor(CheckedTypeDataVar,
    name='_RTTIBaseClassDescriptor',
    alt_name='_s_RTTIBaseClassDescriptor',
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
    type_descriptor: TypeDescriptor
    num_contained_bases: int
    where: PMD
    attributes: int
    class_hierarchy_descriptor: 'ClassHierarchyDescriptor'

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.type_descriptor = self['pTypeDescriptor']
        self.num_contained_bases = self['numContainedBases'].value
        self.where = self['where']
        self.attributes = self['attributes'].value
        self.class_hierarchy_descriptor = self['pClassDescriptor']

    @property
    def type_name(self):
        return self.type_descriptor.type_name_without_prefix

    @property
    def symbol_name(self):
        if self.type_name is None:
            return None

        location = f'({self.where.mdisp},{self.where.pdisp},{self.where.vdisp},{self.attributes})'
        return f"{self.type_name}::`RTTI Base Class Descriptor at {location}'"

class BaseClassArray(CheckedTypeDataVar,
    name='_RTTIBaseClassArray',
    alt_name='_s_RTTIBaseClassArray',
    members=[
        (RTTIOffsetType[BaseClassDescriptor], 'arrayOfBaseClassDescriptors'),
    ],
):
    length: int
    base_class_array: list[BaseClassDescriptor]

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int, length: int):
        super().__init__(view, source)
        self.length = length
        self.source = self.view.typed_data_accessor(
            self.address,
            self.type
        )

        if self.source[-1].value != 0:
            raise ValueError("Expected null terminator")

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
            len(self) + 1,
        )

    def __len__(self):
        return self.length

    def __iter__(self):
        return iter(self.base_class_descs)

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

        return f"{self.type_name}::`RTTI Base Class Array'"

    def mark_down_members(self):
        for i, bcd in enumerate(self.base_class_descs):
            bcd.mark_down()
            self.view.add_user_data_ref(
                self.address + (i * self.view.address_size),
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
        new_prefix = []
        type_token = None
        for token in prefix:
            if token.type in [
                bn.InstructionTextTokenType.BraceToken,
                bn.InstructionTextTokenType.ArrayIndexToken
            ]:
                continue

            if token.type == bn.InstructionTextTokenType.KeywordToken:
                type_token = token
                token = bn.InstructionTextToken(token.type, BaseClassArray.name)
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
            if offset == 0:
                value_token = bn.InstructionTextToken(
                    bn.InstructionTextTokenType.DataSymbolToken,
                    'nullptr',
                    offset,
                )
            else:
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
                type_token,
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

class BaseClassArrayListener(bn.BinaryDataNotification):
    def __init__(self):
        super().__init__(
            bn.NotificationType.NotificationBarrier |
            bn.NotificationType.DataVariableAdded |
            bn.NotificationType.DataVariableLifetime |
            bn.NotificationType.DataVariableRemoved |
            bn.NotificationType.DataVariableUpdated |
            bn.NotificationType.DataVariableUpdates
        )
        self.received_event = False

    def notification_barrier(self, view: bn.BinaryView) -> int:
        has_events = self.received_event
        self.received_event = False

        if has_events:
            return 250

        return 0

    def data_var_added(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if not var.name or not var.name.endswith("::`RTTI Base Class Array'"):
            return

        for accessor in view.typed_data_accessor(var.address, var.type):
            offset = accessor.value
            view.add_user_data_ref(
                accessor.address,
                resolve_rtti_offset(view, offset)
            )

    def data_var_updated(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if not var.name or not var.name.endswith("::`RTTI Base Class Array'"):
            return

        for accessor in view.typed_data_accessor(var.address, var.type):
            offset = accessor.value
            view.add_user_data_ref(
                accessor.address,
                resolve_rtti_offset(view, offset)
            )

    def data_var_removed(self, view: bn.BinaryView, var: bn.DataVariable) -> None:
        self.received_event = True
        if not var.name or not var.name.endswith("::`RTTI Base Class Array'"):
            return

        for accessor in view.typed_data_accessor(var.address, var.type):
            offset = accessor.value
            view.remove_user_data_ref(
                accessor.address,
                resolve_rtti_offset(view, offset)
            )
