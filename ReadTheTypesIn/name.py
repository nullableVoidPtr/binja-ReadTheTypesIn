from typing import Self
from dataclasses import dataclass
from functools import cache
import re
import binaryninja as bn
from binaryninja.enums import StructureVariant

TYPE_DESCRIPTOR_NAME_PREFIX = '.?A'
CLASS_TYPE_ID_PREFIX = TYPE_DESCRIPTOR_NAME_PREFIX + 'V'
STRUCT_TYPE_ID_PREFIX = TYPE_DESCRIPTOR_NAME_PREFIX + 'U'

VARIANT_TO_STR = {
    StructureVariant.ClassStructureType: "class",
    StructureVariant.StructStructureType: "struct",
}

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

@dataclass(frozen=True)
class TypeName:
    variant: StructureVariant
    name: bn.QualifiedName

    @staticmethod
    @cache
    def create_component(view: bn.BinaryView, name: tuple):
        if len(name) == 1:
            parent = view.root_component
            if name[0].startswith("<lambda_"):
                parent = TypeName.create_component(view, ("Anonymous Lambdas",))
        else:
            parent = TypeName.create_component(view, name[:-1])

        component = next(
            (
                component
                for component in parent.components
                if component.display_name == name[-1]
            ),
            None,
        ) or view.create_component("::".join(name), parent)
        component.name = name[-1]

        return component

    def get_component(self, view: bn.BinaryView):
        return TypeName.create_component(view, tuple(self.name.name))

    def __str__(self):
        return VARIANT_TO_STR[self.variant] + " " + str(self.name)

    @staticmethod
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

    @staticmethod
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

    @staticmethod
    @cache
    def parse_from_msvc_type_descriptor_name(platform: str, name: str) -> Self:
        demangled_type, demangled_name = bn.demangle_ms(platform, name)
        if not isinstance(demangled_type, bn.VoidType):
            bn.log.log_warn(f"Could not demangle {name}")
            raise ValueError()

        if name.startswith(CLASS_TYPE_ID_PREFIX):
            variant = StructureVariant.ClassStructureType
        elif name.startswith(STRUCT_TYPE_ID_PREFIX):
            variant = StructureVariant.StructStructureType
        else:
            raise ValueError()

        filtered = []
        for i, name in enumerate(demangled_name):
            simplified_name = TypeName.simplify_name(name)
            if i > 0 and demangled_name[0] == 'std':
                filtered.append(TypeName.simplify_std_name(simplified_name))
            else:
                filtered.append(simplified_name)

        return TypeName(
            variant,
            bn.QualifiedName(filtered),
        )
