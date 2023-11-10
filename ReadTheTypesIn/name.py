from functools import cache
import re
import binaryninja as bn
from binaryninja.enums import StructureVariant

# pylint: disable=line-too-long
STD_TYPEDEFS = {
    "basic_string<char,struct std::char_traits<char>,class std::allocator<char> >": "string",
    "basic_string<wchar_t,struct std::char_traits<wchar_t>,class std::allocator<wchar_t> >": "wstring",

    "basic_ios<char,struct std::char_traits<char> >": "ios",
    "basic_streambuf<char,struct std::char_traits<char> >": "streambuf",
    "basic_istream<char,struct std::char_traits<char> >": "istream",
    "basic_iostream<char,struct std::char_traits<char> >": "iostream",
    "basic_ostream<char,struct std::char_traits<char> >": "ostream",
    "basic_filebuf<char,struct std::char_traits<char> >": "filebuf",
    "basic_ifstream<char,struct std::char_traits<char> >": "ifstream",
    "basic_ofstream<char,struct std::char_traits<char> >": "ofstream",
    "basic_fstream<char,struct std::char_traits<char> >": "fstream",
    "basic_stringbuf<char,struct std::char_traits<char>,class std::allocator<char> >": "stringbuf",
    "basic_istringstream<char,struct std::char_traits<char>,class std::allocator<char> >": "istringstream",
    "basic_ostringstream<char,struct std::char_traits<char>,class std::allocator<char> >": "ostringstream",
    "basic_stringstream<char,struct std::char_traits<char>,class std::allocator<char> >": "stringstream",

    "basic_ios<wchar_t,struct std::char_traits<wchar_t> >": "wios",
    "basic_streambuf<wchar_t,struct std::char_traits<wchar_t> >": "wstreambuf",
    "basic_istream<wchar_t,struct std::char_traits<wchar_t> >": "wistream",
    "basic_iostream<wchar_t,struct std::char_traits<wchar_t> >": "wiostream",
    "basic_ostream<wchar_t,struct std::char_traits<wchar_t> >": "wostream",
    "basic_filebuf<wchar_t,struct std::char_traits<wchar_t> >": "wfilebuf",
    "basic_ifstream<wchar_t,struct std::char_traits<wchar_t> >": "wifstream",
    "basic_ofstream<wchar_t,struct std::char_traits<wchar_t> >": "wofstream",
    "basic_fstream<wchar_t,struct std::char_traits<wchar_t> >": "wfstream",
    "basic_stringbuf<wchar_t,struct std::char_traits<wchar_t>,class std::allocator<wchar_t> >": "wstringbuf",
    "basic_istringstream<wchar_t,struct std::char_traits<wchar_t>,class std::allocator<wchar_t> >": "wistringstream",
    "basic_ostringstream<wchar_t,struct std::char_traits<wchar_t>,class std::allocator<wchar_t> >": "wostringstream",
    "basic_stringstream<wchar_t,struct std::char_traits<wchar_t>,class std::allocator<wchar_t> >": "wstringstream",
}
# pylint: enable=line-too-long

def simplify_name(name: str) -> str:
    old_name = name
    while True:
        new_name = old_name
        for std_type, typedef in STD_TYPEDEFS.items():
            new_name = new_name.replace("class std::" + std_type, "class std::" + typedef)

        new_name = re.sub(
            r'class std::map<(.+?),(.+?),struct std::less<\1 ?>,class std::allocator<struct std::pair<\1 const,\2 ?> >',
            r'class std::map<\1, \2 >',
            new_name,
        )
        new_name = re.sub(
            r'class std::vector<(.+?),class std::allocator<\1 ?> >',
            r'class std::vector<\1 >',
            new_name,
        )
        new_name = re.sub(
            r'(\w) >',
            r'\1>',
            new_name,
        )
        new_name = re.sub(
            r',struct std::_Nil>',
            r'>',
            new_name,
        )
        if old_name == new_name:
            break

        old_name = new_name

    return new_name

def simplify_std_name(name: str) -> str:
    if name in STD_TYPEDEFS:
        return STD_TYPEDEFS[name]

    new_name = name
    new_name = re.sub(
        r'map<(.+?),(.+?),struct std::less<\1 ?>,class std::allocator<struct std::pair<\1 const,\2> >',
        r'map<\1, \2>',
        new_name,
    )
    new_name = re.sub(
        r'vector<(.+?),class std::allocator<\1 ?> >',
        r'vector<\1>',
        new_name,
    )

    return new_name

@cache
def parse_from_msvc_type_descriptor_name(platform: str, decorated_name: str) -> bn.NamedTypeReferenceType:
    demangled_type, _ = bn.demangle_ms(platform, decorated_name)
    if not isinstance(demangled_type, bn.NamedTypeReferenceType):
        bn.log.log_warn(f"Could not demangle {decorated_name}")
        raise ValueError()

    filtered = []
    for i, name in enumerate(demangled_type.name):
        simplified_name = simplify_name(name)
        if i > 0 and demangled_type.name[0] == 'std':
            filtered.append(simplify_std_name(simplified_name))
        else:
            filtered.append(simplified_name)

    return bn.Type.named_type_reference(
        demangled_type.named_type_class,
        filtered,
    )
