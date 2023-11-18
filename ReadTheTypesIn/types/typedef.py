from abc import abstractmethod
import binaryninja as bn
from .var import CheckedTypeDataVar

class CheckedTypedef:
    name: str

    @classmethod
    def create(cls, view: bn.BinaryView, *args, **kwargs):
        return cls.get_actual_type(view).create(view, *args, **kwargs)

    @classmethod
    @abstractmethod
    def get_actual_type(cls, view: bn.BinaryView) -> type[CheckedTypeDataVar]:
        ...

    @classmethod
    def define_type(cls, view: bn.BinaryView) -> bn.Type:
        session_data_key = f'ReadTheTypesIn.{cls.name}.defined'
        if view.session_data.get(session_data_key):
            return

        struct_ref = cls.get_actual_type(view).get_struct_ref(view)
        if (old_typedef := view.types.get(cls.name)) is not None:
            if isinstance(old_typedef, bn.types.NamedReferenceType):
                target = old_typedef.target(view)
                if target == struct_ref:
                    return

        view.define_type(cls.name, cls.name, struct_ref)
        view.session_data[session_data_key] = True

    @classmethod
    def get_structure(cls, view: bn.BinaryView) -> bn.Type:
        return cls.get_actual_type(view).get_structure(view)

    @classmethod
    def get_typedef_ref(cls, view: bn.BinaryView) -> bn.Type:
        cls.define_type(view)
        return bn.Type.named_type_from_registered_type(view, cls.name)

    @classmethod
    def get_alignment(cls, view: bn.BinaryView) -> int:
        return cls.get_actual_type(view).get_alignment(view)
