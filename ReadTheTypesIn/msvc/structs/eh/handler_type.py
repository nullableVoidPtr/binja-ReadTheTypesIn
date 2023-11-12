from typing import Optional, Annotated
import binaryninja as bn
from ....types import CheckedTypeDataVar, CheckedTypedef, EHRelative
from ..rtti.type_descriptor import TypeDescriptor

HANDLER_TYPE_MEMBERS = [
    ('unsigned int', 'adjectives'),
    (EHRelative[TypeDescriptor], 'pType'),
    ('int', 'dispCatchObj'),
    (EHRelative['void'], 'pHandler'),
]

class _HandlerTypeBase():
    source: bn.TypedDataAccessor

    adjectives: Annotated[int, 'adjectives']
    type_descriptor: Annotated[Optional[TypeDescriptor], 'pType']
    disp_catch_obj: Annotated[int, 'dispCatchObj']
    handler: int

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)
        self.handler = self['pHandler'].value

    def __getitem__(self, key: str):
        if key == 'pType':
            if self.source[key].value == 0:
                return None

        # pylint:disable-next=no-member
        return super().__getitem__(key)

class _HandlerType(_HandlerTypeBase, CheckedTypeDataVar,
    members=HANDLER_TYPE_MEMBERS,
):
    name = '_s_HandlerType'
    alt_name = '_s__HandlerType'

class _HandlerType2(_HandlerTypeBase, CheckedTypeDataVar,
    members=[
        *HANDLER_TYPE_MEMBERS,
        ('int', 'pFrame'),
    ],
):
    name = '_s_HandlerType2'
    alt_name = '_s__HandlerType2'

class HandlerType(CheckedTypedef):
    name = '_HandlerType'

    @classmethod
    def get_actual_type(cls, view: bn.BinaryView) -> type[_HandlerTypeBase]:
        return _HandlerType2 if EHRelative.is_relative(view) else _HandlerType
