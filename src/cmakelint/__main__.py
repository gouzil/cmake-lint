"""
Copyright 2009 Richard Quirk
Copyright 2023 Nyakku Shigure, PaddlePaddle Authors

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

import cmakelint.__version__

_RE_COMMAND = re.compile(r"^\s*(\w+)(\s*)\(", re.VERBOSE)
_RE_COMMAND_START_SPACES = re.compile(r"^\s*\w+\s*\((\s*)", re.VERBOSE)
_RE_COMMAND_END_SPACES = re.compile(r"(\s*)\)", re.VERBOSE)
_RE_LOGIC_CHECK = re.compile(r"(\w+)\s*\(\s*\S+[^)]+\)", re.VERBOSE)
_RE_COMMAND_ARG = re.compile(r"(\w+)", re.VERBOSE)
_logic_commands = """
else
endforeach
endfunction
endif
endmacro
endwhile
""".split()

_ERROR_CATEGORIES = """\
        convention/filename
        linelength
        package/consistency
        package/stdargs
        readability/logic
        readability/mixedcase
        readability/wonkycase
        syntax
        whitespace/eol
        whitespace/extra
        whitespace/indent
        whitespace/mismatch
        whitespace/newline
        whitespace/tabs
"""
_DEFAULT_FILENAME = "CMakeLists.txt"
_ERROR_CODE_FOUND_ISSUE = 1
_ERROR_CODE_WRONG_USAGE = 32


def default_rc():
    """
    Check current working directory and XDG_CONFIG_DIR before ~/.cmakelintrc
    """
    cwdfile = os.path.join(os.getcwd(), ".cmakelintrc")
    if os.path.exists(cwdfile):
        return cwdfile
    xdg = os.path.join(os.path.expanduser("~"), ".config")
    if "XDG_CONFIG_DIR" in os.environ:
        xdg = os.environ["XDG_CONFIG_DIR"]
    xdgfile = os.path.join(xdg, "cmakelintrc")
    if os.path.exists(xdgfile):
        return xdgfile
    return os.path.join(os.path.expanduser("~"), ".cmakelintrc")


_DEFAULT_CMAKELINTRC = default_rc()


class _CMakeLintState:
    def __init__(self):
        self.filters = []
        self.config: str | None = _DEFAULT_CMAKELINTRC
        self.errors = 0
        self.spaces = 2
        self.linelength = 80
        self.allowed_categories = _ERROR_CATEGORIES.split()
        self.quiet = False

    def set_filters(self, filters):
        if not filters:
            return
        assert isinstance(self.filters, list)
        if isinstance(filters, list):
            self.filters.extend(filters)
        elif isinstance(filters, str):
            self.filters.extend([f.strip() for f in filters.split(",") if f])
        else:
            raise ValueError("Filters should be a list or a comma separated string")
        for f in self.filters:
            if f.startswith("-") or f.startswith("+"):
                allowed = False
                for c in self.allowed_categories:
                    if c.startswith(f[1:]):
                        allowed = True
                if not allowed:
                    raise ValueError("Filter not allowed: %s" % f)
            else:
                raise ValueError("Filter should start with - or +")

    def set_spaces(self, spaces: int):
        self.spaces = spaces

    def set_quiet(self, quiet: bool):
        self.quiet = quiet

    def set_line_length(self, linelength):
        self.linelength = int(linelength)

    def reset(self):
        self.filters = []
        self.config = _DEFAULT_CMAKELINTRC
        self.errors = 0
        self.spaces = 2
        self.linelength = 80
        self.allowed_categories = _ERROR_CATEGORIES.split()
        self.quiet = False


class _CMakePackageState:
    def __init__(self):
        self.sets = []
        self.have_included_stdargs = False
        self.have_used_stdargs = False

    def check(self, filename, linenumber, clean_lines, errors):
        pass

    def _get_expected(self, filename):
        package = os.path.basename(filename)
        package = re.sub(r"^Find(.*)\.cmake", lambda m: m.group(1), package)
        return package.upper()

    def done(self, filename, errors):
        try:
            if not is_find_package(filename):
                return
            if self.have_included_stdargs and self.have_used_stdargs:
                return
            if not self.have_included_stdargs:
                errors(filename, 0, "package/consistency", "Package should include FindPackageHandleStandardArgs")
            if not self.have_used_stdargs:
                errors(filename, 0, "package/consistency", "Package should use FIND_PACKAGE_HANDLE_STANDARD_ARGS")
        finally:
            self.have_used_stdargs = False
            self.have_included_stdargs = False

    def have_used_standard_args(self, filename, linenumber, var, errors):
        expected = self._get_expected(filename)
        self.have_used_stdargs = True
        if expected != var:
            errors(
                filename,
                linenumber,
                "package/stdargs",
                "Weird variable passed to std args, should be " + expected + " not " + var,
            )

    def have_included(self, var):
        if var == "FindPackageHandleStandardArgs":
            self.have_included_stdargs = True

    def set(self, var):
        self.sets.append(var)


_lint_state = _CMakeLintState()
_package_state = _CMakePackageState()


def clean_comments(line, quote=False):
    """
    quote means 'was in a quote starting this line' so that
    quoted lines can be eaten/removed.
    """
    if line.find("#") == -1 and line.find('"') == -1:
        if quote:
            return "", quote
        else:
            return line, quote
    # else have to check for comment
    prior = []
    prev = ""
    for char in line:
        try:
            if char == '"':
                if prev != "\\":
                    quote = not quote
                    prior.append(char)
                continue
            elif char == "#" and not quote:
                break
            if not quote:
                prior.append(char)
        finally:
            prev = char

    # rstrip removes trailing space between end of command and the comment # start

    return "".join(prior).rstrip(), quote


class CleansedLines:
    def __init__(self, lines):
        self.have_seen_uppercase = None
        self.raw_lines = lines
        self.lines = []
        quote = False
        for line in lines:
            cleaned, quote = clean_comments(line, quote)
            self.lines.append(cleaned)

    def line_numbers(self):
        return range(0, len(self.lines))


def should_print_error(category):
    should_print = True
    for f in _lint_state.filters:
        if f.startswith("-") and category.startswith(f[1:]):
            should_print = False
        elif f.startswith("+") and category.startswith(f[1:]):
            should_print = True
    return should_print


def error(filename, linenumber, category, message):
    if should_print_error(category):
        _lint_state.errors += 1
        print(f"{filename}:{linenumber}: {message} [{category}]")


def check_line_length(filename, linenumber, clean_lines, errors):
    """
    Check for lines longer than the recommended length
    """
    line = clean_lines.raw_lines[linenumber]
    if len(line) > _lint_state.linelength:
        return errors(
            filename, linenumber, "linelength", "Lines should be <= %d characters long" % (_lint_state.linelength)
        )


def contains_command(line):
    return _RE_COMMAND.match(line)


def get_command(line):
    match = _RE_COMMAND.match(line)
    if match:
        return match.group(1)
    return ""


def is_command_mixed_case(command):
    lower = command.lower()
    upper = command.upper()
    return not (command == lower or command == upper)


def is_command_upper_case(command):
    upper = command.upper()
    return command == upper


def check_upper_lower_case(filename, linenumber, clean_lines, errors):
    """
    Check that commands are either lower case or upper case, but not both
    """
    line = clean_lines.lines[linenumber]
    if contains_command(line):
        command = get_command(line)
        if is_command_mixed_case(command):
            return errors(filename, linenumber, "readability/wonkycase", "Do not use mixed case commands")
        if clean_lines.have_seen_uppercase is None:
            clean_lines.have_seen_uppercase = is_command_upper_case(command)
        else:
            is_upper = is_command_upper_case(command)
            if is_upper != clean_lines.have_seen_uppercase:
                return errors(filename, linenumber, "readability/mixedcase", "Do not mix upper and lower case commands")


def get_initial_spaces(line):
    initial_spaces = 0
    while initial_spaces < len(line) and line[initial_spaces] == " ":
        initial_spaces += 1
    return initial_spaces


def check_command_spaces(filename, linenumber, clean_lines, errors):
    """
    No extra spaces between command and parenthesis
    """
    line = clean_lines.lines[linenumber]
    match = contains_command(line)
    if match and len(match.group(2)):
        errors(filename, linenumber, "whitespace/extra", "Extra spaces between '%s' and its ()" % (match.group(1)))
    if match:
        spaces_after_open = len(_RE_COMMAND_START_SPACES.match(line).group(1))
        initial_spaces = get_initial_spaces(line)
        initial_linenumber = linenumber
        end = None
        while True:
            line = clean_lines.lines[linenumber]
            end = _RE_COMMAND_END_SPACES.search(line)
            if end:
                break
            linenumber += 1
            if linenumber >= len(clean_lines.lines):
                break
        if linenumber == len(clean_lines.lines) and not end:
            errors(filename, initial_linenumber, "syntax", "Unable to find the end of this command")
        if end:
            spaces_before_end = len(end.group(1))
            initial_spaces = get_initial_spaces(line)
            if initial_linenumber != linenumber and spaces_before_end >= initial_spaces:
                spaces_before_end -= initial_spaces

            if spaces_after_open != spaces_before_end:
                errors(
                    filename, initial_linenumber, "whitespace/mismatch", "Mismatching spaces inside () after command"
                )


def check_repeat_logic(filename, linenumber, clean_lines, errors):
    """
    Check for logic inside else, endif etc
    """
    line = clean_lines.lines[linenumber]
    for cmd in _logic_commands:
        if re.search(r"\b%s\b" % cmd, line.lower()):
            m = _RE_LOGIC_CHECK.search(line)
            if m:
                errors(
                    filename,
                    linenumber,
                    "readability/logic",
                    f"Expression repeated inside {cmd}; " + f"better to use only {m.group(1)}()",
                )
            break


def check_indent(filename, linenumber, clean_lines, errors):
    line = clean_lines.raw_lines[linenumber]
    initial_spaces = get_initial_spaces(line)
    remainder = initial_spaces % _lint_state.spaces
    if remainder != 0:
        errors(filename, linenumber, "whitespace/indent", "Weird indentation; use %d spaces" % (_lint_state.spaces))


def check_style(filename, linenumber, clean_lines, errors):
    """
    Check style issues. These are:
    No extra spaces between command and parenthesis
    Matching spaces between parenthesis and arguments
    No repeated logic in else(), endif(), endmacro()
    """
    check_indent(filename, linenumber, clean_lines, errors)
    check_command_spaces(filename, linenumber, clean_lines, errors)
    line = clean_lines.raw_lines[linenumber]
    if line.find("\t") != -1:
        errors(filename, linenumber, "whitespace/tabs", "Tab found; please use spaces")

    if line and line[-1].isspace():
        errors(filename, linenumber, "whitespace/eol", "Line ends in whitespace")

    check_repeat_logic(filename, linenumber, clean_lines, errors)


def check_file_name(filename, errors):
    name_match = re.match(r"Find(.*)\.cmake", os.path.basename(filename))
    if name_match:
        package = name_match.group(1)
        if not package.isupper():
            errors(
                filename,
                0,
                "convention/filename",
                "Find modules should use uppercase names; " "consider using Find" + package.upper() + ".cmake",
            )
    else:
        if filename.lower() == "cmakelists.txt" and filename != "CMakeLists.txt":
            errors(filename, 0, "convention/filename", "File should be called CMakeLists.txt")


def is_find_package(filename):
    return os.path.basename(filename).startswith("Find") and filename.endswith(".cmake")


def get_command_argument(linenumber, clean_lines):
    line = clean_lines.lines[linenumber]
    skip = get_command(line)
    while True:
        line = clean_lines.lines[linenumber]
        m = _RE_COMMAND_ARG.finditer(line)
        for i in m:
            if i.group(1) == skip:
                continue
            return i.group(1)
        linenumber += 1
    return ""


def check_find_package(filename, linenumber, clean_lines, errors):
    cmd = get_command(clean_lines.lines[linenumber])
    if cmd:
        if cmd.lower() == "include":
            var_name = get_command_argument(linenumber, clean_lines)
            _package_state.have_included(var_name)
        elif cmd.lower() == "find_package_handle_standard_args":
            var_name = get_command_argument(linenumber, clean_lines)
            _package_state.have_used_standard_args(filename, linenumber, var_name, errors)


def process_line(filename, linenumber, clean_lines, errors):
    """
    Arguments:
        filename    the name of the file
        linenumber  the line number index
        clean_lines CleansedLines instance
        errors      the error handling function
    """
    check_lint_pragma(filename, linenumber, clean_lines.raw_lines[linenumber], errors)
    check_line_length(filename, linenumber, clean_lines, errors)
    check_upper_lower_case(filename, linenumber, clean_lines, errors)
    check_style(filename, linenumber, clean_lines, errors)
    if is_find_package(filename):
        check_find_package(filename, linenumber, clean_lines, errors)


def is_valid_file(filename):
    return filename.endswith(".cmake") or os.path.basename(filename).lower() == "cmakelists.txt"


def process_file(filename):
    # Store and then restore the filters to prevent pragmas in the file from persisting.
    original_filters = list(_lint_state.filters)
    try:
        return _process_file(filename)
    finally:
        _lint_state.filters = original_filters


def check_lint_pragma(filename, linenumber, line, errors=None):
    # Check this line to see if it is a lint_cmake pragma
    linter_pragma_start = "# lint_cmake: "
    if line.startswith(linter_pragma_start):
        try:
            _lint_state.set_filters(line[len(linter_pragma_start) :])
        except ValueError as ex:
            if errors:
                errors(filename, linenumber, "syntax", str(ex))
        except:  # noqa: E722
            print(f"Exception occurred while processing '{filename}:{linenumber}':")


def _process_file(filename):
    lines = ["# Lines start at 1"]
    have_cr = False
    if not is_valid_file(filename):
        print("Ignoring file: " + filename)
        return
    global _package_state
    _package_state = _CMakePackageState()
    for line in open(filename).readlines():
        line = line.rstrip("\n")
        if line.endswith("\r"):
            have_cr = True
            line = line.rstrip("\r")
        lines.append(line)
        check_lint_pragma(filename, len(lines) - 1, line)
    lines.append("# Lines end here")
    # Check file name after reading lines incase of a # lint_cmake: pragma
    check_file_name(filename, error)
    if have_cr and os.linesep != "\r\n":
        error(filename, 0, "whitespace/newline", "Unexpected carriage return found; " "better to use only \\n")
    clean_lines = CleansedLines(lines)
    for line in clean_lines.line_numbers():
        process_line(filename, line, clean_lines, error)
    _package_state.done(filename, error)


def print_version():
    sys.stderr.write("cmakelint %s\n" % cmakelint.__version__.VERSION)
    sys.exit(0)


def print_categories():
    sys.stderr.write(_ERROR_CATEGORIES)
    sys.exit(0)


def parse_option_file(contents, ignore_space):
    filters = None
    spaces = None
    linelength = None
    for line in contents:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("filter="):
            filters = line.replace("filter=", "")
        if line.startswith("spaces="):
            spaces = line.replace("spaces=", "")
        if line == "quiet":
            _lint_state.set_quiet(True)
        if line.startswith("linelength="):
            linelength = line.replace("linelength=", "")
    _lint_state.set_filters(filters)
    if spaces and not ignore_space:
        _lint_state.set_spaces(int(spaces.strip()))
    if linelength is not None:
        _lint_state.set_line_length(linelength)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(_ERROR_CODE_WRONG_USAGE, f"{self.prog}: error: {message}\n")


def parse_args(argv):
    parser = ArgumentParser("cmakelint", description="cmakelint")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {cmakelint.__version__.VERSION}")
    parser.add_argument("files", nargs="*", help="files to lint")
    parser.add_argument(
        "--filter", default=None, metavar="-X,+Y", help="Specify a comma separated list of filters to apply"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="""
        Use the given file for configuration. By default the file
        $PWD/.cmakelintrc, ~/.config/cmakelintrc, $XDG_CONFIG_DIR/cmakelintrc or
        ~/.cmakelintrc is used if it exists. Use the value "None" to use no
        configuration file (./None for a file called literally None) Only the
        option "filter=" is currently supported in this file.
        """,
    )
    parser.add_argument("--spaces", type=int, default=None, help="Indentation should be a multiple of N spaces")
    parser.add_argument(
        "--linelength",
        type=int,
        default=None,
        help="This is the allowed line length for the project. The default value is 80 characters.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="""
        makes output quiet unless errors occurs
        Mainly used by automation tools when parsing huge amount of files.
        In those cases actual error might get lost in the pile of other stats
        prints.

        This argument is also handy for build system integration, so it's
        possible to add automated lint target to a project and invoke it
        via build system and have no pollution of terminals or IDE.
        """,
    )

    args = parser.parse_args(argv)
    ignore_space = args.spaces is not None
    if args.config is not None:
        if args.config == "None":
            _lint_state.config = None
        elif args.config is not None:
            _lint_state.config = args.config
    if args.linelength is not None:
        _lint_state.set_line_length(args.linelength)
    if args.spaces is not None:
        _lint_state.set_spaces(args.spaces)
    if args.filter is not None:
        if args.filter == "":
            print_categories()
    _lint_state.set_quiet(args.quiet)

    try:
        if _lint_state.config and os.path.isfile(_lint_state.config):
            with open(_lint_state.config) as f:
                parse_option_file(f.readlines(), ignore_space)
        _lint_state.set_filters(args.filter)
    except ValueError as e:
        parser.error(str(e))

    filenames = args.files
    if not filenames:
        if os.path.isfile(_DEFAULT_FILENAME):
            filenames = [_DEFAULT_FILENAME]
        else:
            parser.error("No files were specified!")
    return filenames


def main():
    files = parse_args(sys.argv[1:])

    for filename in files:
        process_file(filename)
    if _lint_state.errors > 0 or not _lint_state.quiet:
        sys.stderr.write("Total Errors: %d\n" % _lint_state.errors)
    if _lint_state.errors > 0:
        return _ERROR_CODE_FOUND_ISSUE
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
