# CMakeLint

![PyPI](https://img.shields.io/pypi/v/cmake-lint-paddle.svg)
![PyPI - Downloads](https://img.shields.io/pypi/dd/cmake-lint-paddle.svg)
![PyPI - Downloads](https://img.shields.io/pypi/dm/cmake-lint-paddle.svg)

cmakelint parses CMake files and reports style issues.

cmakelint requires Python.

## Installation

To install cmakelint from PyPI, run:

```bash
pip install cmake-lint-paddle
```

## Usage

```
Syntax: cmakelint [--config=file] [--filter=-x,+y] <file> [file] ...
   filter=-x,+y,...
   Specify a comma separated list of filters to apply

config=file
   Use the given file for configuration. By default the file
   $PWD/.cmakelintrc, ~/.config/cmakelintrc, $XDG_CONFIG_DIR/cmakelintrc or
   ~/.cmakelintrc is used if it exists. Use the value "None" to use no
   configuration file (./None for a file called literally None) Only the
   option "filter=" is currently supported in this file.
```

Run the `--filter=` option with no filter to see available options. Currently
these are:

```
convention/filename
linelength
package/consistency
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
```

An example .cmakelintrc file would be as follows:

```
filter=-whitespace/indent
```

With this file in your home directory, running these commands would have the
same effect:

```bash
cmakelint.py CMakeLists.txt
cmakelint.py --filter=-whitespace/indent CMakeLists.txt
```

Filters can optionally be directly enabled/disabled from within a CMake file,
overriding the configuration from file or CLI argument:

```
# lint_cmake: <+ or -><filter name>
# e.g.:
# lint_cmake: -readability/wonkycase
# add multiple filters as list:
# lint_cmake: <+/-><filter1>, <+/-><filter2>
```

cmakelint can also be run with [pre-commit](https://pre-commit.com). Add the following configuration block to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/PFCCLab/cmake-lint-paddle
  rev: v1.5.0
  hooks:
     - id: cmakelint
```

# Output status codes

The program should exit with the following status codes:

-  0 if everything went fine
-  1 if an error message was issued
-  32 on usage error
