from dataclasses import dataclass
from enum import IntFlag
from typing import Optional
import binaryninja as bn
from ....utils import get_function

UNWIND_REGISTERS = [
    'rax',
    'rcx',
    'rdx',
    'rbx',
    'rsp',
    'rbp',
    'rsi',
    'rdi',
    'r8',
    'r9',
    'r10',
    'r11',
    'r12',
    'r13',
    'r14',
    'r15',
]

@dataclass(frozen=True)
class UnwindCode:
    offset: int

@dataclass(frozen=True)
class UnwindPushNonVol(UnwindCode):
    register: str

@dataclass(frozen=True)
class UnwindAllocLarge(UnwindCode):
    size: int

@dataclass(frozen=True)
class UnwindAllocSmall(UnwindCode):
    size: int

@dataclass(frozen=True)
class UnwindSetFPRegister(UnwindCode):
    pass

@dataclass(frozen=True)
class UnwindSaveNonVol(UnwindCode):
    register: str
    stack_offset: int

@dataclass(frozen=True)
class UnwindSaveNonVolFar(UnwindCode):
    register: str
    stack_offset: int

@dataclass(frozen=True)
class UnwindSaveXMM128(UnwindCode):
    register: str
    stack_offset: int

@dataclass(frozen=True)
class UnwindSaveXMM128Far(UnwindCode):
    register: str
    stack_offset: int

@dataclass(frozen=True)
class UnwindPushMachFrame(UnwindCode):
    has_error_code: bool

class UnwindFlag(IntFlag):
    UNW_FLAG_EHANDLER = 1
    UNW_FLAG_UHANDLER = 2
    UNW_FLAG_CHAININFO = 4

class UnwindInfo:
    source: bn.TypedDataAccessor
    address: int

    version: int
    flags: int
    prolog_size: int
    frame_register: str
    register_offset: int
    unwind_codes: list[int]
    exception_handler: Optional[bn.Function]
    exception_handler_data: Optional[int]
    image_runtime_function: Optional['ImageRuntimeFunction']

    def __init__(self, view: bn.BinaryView, addr: int):
        self.address = addr

        unwind_info_struct = view.types['UNWIND_INFO']
        self.source = view.typed_data_accessor(addr, unwind_info_struct)
        version_and_flags = self.source['VersionAndFlag'].value
        self.version = version_and_flags & 0b111
        self.flags = UnwindFlag(version_and_flags >> 3)
        self.prolog_size = self.source['SizeOfProlog'].value
        code_count = self.source['CountOfUnwindCodes'].value
        frame_register_and_offset = self.source['FrameRegisterAndFrameRegisterOffset'].value
        self.frame_register = UNWIND_REGISTERS[frame_register_and_offset >> 4]
        self.register_offset = (frame_register_and_offset & 0b1111) * 16

        unwind_code_start = addr + unwind_info_struct.width
        raw_codes = view.typed_data_accessor(
            unwind_code_start,
            bn.Type.array(
                bn.Type.int(2, False),
                code_count,
            ),
        ).value

        self.unwind_codes = []
        i = 0
        while i < len(raw_codes):
            raw_code = raw_codes[i]
            i += 1
            offset = raw_code & 0xFF
            op = (raw_code >> 8) & 0b1111
            info = (raw_code >> 12) & 0b1111

            if op == 0:
                code = UnwindPushNonVol(offset, UNWIND_REGISTERS[info])
            elif op == 1:
                if info == 0:
                    size = raw_codes[i] * 8
                    i += 1
                elif info == 1:
                    encoded_size = raw_codes[i].to_bytes(2, 'little')
                    i += 1
                    encoded_size = encoded_size + raw_codes[i].to_bytes(2, 'little')
                    i += 1
                    size = int.from_bytes(encoded_size, 'little')
                else:
                    raise ValueError()

                code = UnwindAllocLarge(offset, size)
            elif op == 2:
                size = info * 8 + 8
                code = UnwindAllocSmall(offset, size)
            elif op == 3:
                code = UnwindSetFPRegister(offset)
            elif op == 4:
                register_offset = raw_codes[i] * 8 + 8
                i += 1
                code = UnwindSaveNonVol(offset, UNWIND_REGISTERS[info], register_offset)
            elif op == 5:
                encoded_offset = raw_codes[i].to_bytes(2, 'little')
                i += 1
                encoded_offset = encoded_offset + raw_codes[i].to_bytes(2, 'little')
                i += 1
                register_offset = int.from_bytes(encoded_offset, 'little')
                code = UnwindSaveNonVolFar(offset, UNWIND_REGISTERS[info], register_offset)
            elif op == 8:
                register_offset = raw_codes[i] * 16
                i += 1
                code = UnwindSaveNonVol(offset, f"xmm{info}", register_offset)
            elif op == 9:
                encoded_offset = raw_codes[i].to_bytes(2, 'little')
                i += 1
                encoded_offset = encoded_offset + raw_codes[i].to_bytes(2, 'little')
                i += 1
                register_offset = int.from_bytes(encoded_offset, 'little')
                code = UnwindSaveNonVol(offset, f"xmm{info}", register_offset)
            elif op == 10:
                code = UnwindPushMachFrame(offset, bool(info))
            else:
                raise ValueError(f"Invalid opcode {op}")

            self.unwind_codes.append(code)

        current = unwind_code_start + 2 * code_count
        if current % 4 != 0:
            current += 4 - (current % 4)

        self.image_runtime_function = None
        self.exception_handler = None
        self.exception_handler_data_start = None
        if UnwindFlag.UNW_FLAG_CHAININFO in self.flags:
            self.image_runtime_function = ImageRuntimeFunction(view, current)
        elif UnwindFlag.UNW_FLAG_EHANDLER in self.flags or UnwindFlag.UNW_FLAG_UHANDLER in self.flags:
            self.exception_handler = get_function(view, view.start + view.read_int(current, 4, False))
            self.exception_handler_data_start = current + 4


class ImageRuntimeFunction:
    source: bn.TypedDataAccessor
    address: int

    start: int
    end: int
    unwind_info: UnwindInfo

    def __init__(self, view: bn.BinaryView, addr: int):
        self.address = addr

        struct = view.types['Exception_Directory_Entry']
        self.source = view.typed_data_accessor(addr, struct)
        self.start = view.start + self.source['beginAddress'].value
        self.end = view.start + self.source['endAddress'].value
        self.unwind_info = UnwindInfo(view, view.start + self.source['unwindInformation'].value)

    @staticmethod
    def search(
        view: bn.BinaryView,
        task: Optional[bn.BackgroundTask] = None,
    ):
        if task is not None:
            task.progress = 'Parsing exception directory'

        pe64_header = view.get_data_var_at(
            view.symbols['__pe64_optional_header'][0].address
        )

        entries = []
        except_dir = pe64_header['exceptionTableEntry'].value
        start = view.start + except_dir['virtualAddress']
        end = start + except_dir['size']
        img_rt_func_struct = view.types['Exception_Directory_Entry']
        for address in range(start, end, img_rt_func_struct.width):
            try:
                irf = ImageRuntimeFunction(view, address)
                unwind_info = irf.unwind_info
                view.add_user_data_ref(
                    irf.source['unwindInformation'].address,
                    unwind_info.address,
                )
                yield irf
            except Exception as e:
                import traceback
                bn.log.log_warn(
                    f"Failed to parse ImageRuntimeFunction @ {address:x}",
                    "ImageRuntimeFunction::search"
                )
                bn.log.log_debug(
                    traceback.format_exc(e),
                    "ImageRuntimeFunction::search"
                )
                continue
