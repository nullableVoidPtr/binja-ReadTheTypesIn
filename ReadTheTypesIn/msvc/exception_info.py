from typing import Optional
import binaryninja as bn
from .structs.rtti.type_descriptor import TypeDescriptor

class TryBlockHandler:
    adjectives: int
    exception_type: Optional[TypeDescriptor]
    catch_object_displacement: int
    handler: int

class ExceptionInfo:
    function: bn.Function

    ip_to_states: dict[int, int]
    try_blocks: dict[int, TryBlockHandler]
    unwind_info: dict[int, bn.Function]
