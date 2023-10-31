from typing import Optional, Generator, Self
import traceback
from collections import Counter
import binaryninja as bn
from ....types import CheckedTypeDataVar, Array
from ....name import TypeName
from ...utils import get_data_sections

TYPE_DESCRIPTOR_NAME_PREFIX = '.?A'
CLASS_TYPE_ID_PREFIX = TYPE_DESCRIPTOR_NAME_PREFIX + 'V'
STRUCT_TYPE_ID_PREFIX = TYPE_DESCRIPTOR_NAME_PREFIX + 'U'

# https://learn.microsoft.com/en-us/cpp/build/reference/h-restrict-length-of-external-names?view=msvc-170#remarks
MAX_NAME_LEN = 2047

class TypeDescriptor(CheckedTypeDataVar, members=[
    ('void*', 'pVFTable'),
    ('void*', 'spare'),
    (Array['char', ...], 'name'),
]):
    packed = True

    decorated_name: str

    def __init__(self, view: bn.BinaryView, source: bn.TypedDataAccessor | int):
        super().__init__(view, source)

        if self['spare'].value != 0:
            raise ValueError("Invalid TypeDescriptor (non-null spare)")

        self.decorated_name = self['name'].value

    def get_array_length(self, name: str):
        if name == 'name':
            return len(self.decorated_name) + 1

        return super().get_array_length(name)

    @property
    def type_name(self):
        try:
            return TypeName.parse_from_msvc_type_descriptor_name(self.decorated_name)
        except Exception:
            return None

    @property
    def is_class(self) -> bool:
        return self.decorated_name.startswith(CLASS_TYPE_ID_PREFIX)

    @property
    def is_struct(self) -> bool:
        return self.decorated_name.startswith(STRUCT_TYPE_ID_PREFIX)

    def __getitem__(self, key: str):
        if key == 'name':
            if (name := self.view.get_ascii_string_at(
                self.source['name'].address,
                max_length=MAX_NAME_LEN,
            )) is None:
                raise ValueError("Invalid TypeDescriptor (incorrect name)")

            return name

        return super().__getitem__(key)

    @property
    def symbol_name(self):
        return f"{self.type_name.name} `RTTI Type Descriptor'"

    @classmethod
    def search(
        cls,
        view: bn.BinaryView,
        task: Optional[bn.BackgroundTask] = None
    ) -> Generator[Self, None, None]:
        user_struct = cls.get_user_struct(view)
        name_offset = user_struct['name'].offset

        matches = []
        def update_progress(processed: int, total: int) -> bool:
            task.progress = f'{cls.name} search {processed:x}/{total:x}'
            return not task.cancelled

        def is_potential_type_descriptor(accessor: bn.TypedDataAccessor):
            if accessor.address % cls.get_alignment(view) != 0:
                return False

            if (name := view.get_ascii_string_at(
                accessor.address + name_offset,
                max_length=MAX_NAME_LEN,
            )) is None:
                return False

            name = name.value
            if not name.startswith((CLASS_TYPE_ID_PREFIX, STRUCT_TYPE_ID_PREFIX)) or \
                not name.endswith('@@'):
                return False

            return True

        def process_match(address: int, _: bn.databuffer.DataBuffer) -> bool:
            accessor = view.typed_data_accessor(address - name_offset, user_struct)
            if is_potential_type_descriptor(accessor):
                matches.append(accessor)
            return True

        for section in get_data_sections(view):
            view.find_all_data(
                section.start, section.end,
                TYPE_DESCRIPTOR_NAME_PREFIX.encode(),
                progress_func=update_progress if task is not None else None,
                match_callback=process_match,
            )

        vftable_counter = Counter([
            accessor['pVFTable'].value
            for accessor in matches
        ])

        type_info_vftable = vftable_counter.most_common(1)[0][0]

        for accessor in matches:
            if accessor['pVFTable'].value != type_info_vftable:
                continue

            try:
                type_descriptor = cls.create(view, accessor)
                yield type_descriptor
            except Exception:
                bn.log.log_warn(
                    f'Failed to define type descriptor @ 0x{accessor.address:x}',
                    'TypeDescriptor::search',
                )
                bn.log.log_debug(
                    traceback.format_exc(),
                    'TypeDescriptor::search_with_type_descriptors',
                )

                continue

            bn.log.log_debug(
                f'Defined type descriptor @ 0x{accessor.address:x}',
                'TypeDescriptor::search',
            )

        if task is not None:
            task.progress = f'{cls.name} search finished'
