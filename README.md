# ReadTheTypesIn
Author: nullableVoidPtr

_Find RTTI and define structs accordingly._

## Description:
Currently works for MSVC 32/64-bit binaries.

### Unimplemented features
* Restoring from previous analysis
* Attributing base vftables to derived types
* Structor hueristics
  * via `atexit` for global instances
  * `` `scalar deleting destructor' ``, etc.
* Virtual inheritance
  * `vbptr` and relevant structs
* UI inheritance graph
* Class structure definition w/ automatic width and detected members
* Pseudo C++ Linear View
  * `__try`/`__except` using EH data
    * Parsing `UNWIND_INFO` instances
    * EH4
  * Converting `__CxxThrowException` to `throw` statements
* Itanium

## License

This plugin is released under an [MIT license](./license).
