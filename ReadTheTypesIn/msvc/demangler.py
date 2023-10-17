from functools import cache
import subprocess

@cache
def run_demumbler(decorated_name: str) -> str:
    output = subprocess.check_output(
        ['/home/void/.binaryninja/plugins/ClassyPP/Common/demumble_linux', decorated_name])

    if output.startswith(b'The system cannot find the file specified'):
        raise ValueError()

    return output.decode()
