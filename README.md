# Sharpie: Shell-to-Python Transpiler

A source-to-source compiler written in Python that translates POSIX Shell scripts into readable, human-modifiable Python. Built for COMP2041 Software Construction at UNSW.

## Overview

Shell scripts are powerful but limited — no GUIs, weaker libraries, and quirky semantics. Sharpie automates the tedious first pass of converting Shell to Python, producing clean, idiomatic output that a human can read and extend.

```bash
./sharpie.py script.sh
```

## Example

**Input (Shell):**
```sh
#!/bin/dash

for c_file in *.c
do
    gcc -c $c_file
done
```

**Output (Python):**
```python
#!/usr/bin/python3 -u

import glob, subprocess

for c_file in sorted(glob.glob("*.c")):
    subprocess.run(["gcc", "-c", c_file])
```

## Features

### Core Language Constructs
- Variable assignment and `$`/`${}` expansion
- `echo` → `print()`, including `echo -n` (no newline)
- `read` → `input()`
- `exit` → `sys.exit()`
- `cd` → `os.chdir()`
- Comments preserved in output

### Control Flow
- `if` / `elif` / `else` / `fi`
- `while` loops
- `for` loops (including over globs)
- `case` statements
- Full nesting support across all constructs

### String Handling
- Single-quoted strings (no expansion)
- Double-quoted strings (variable expansion, no globbing)
- Backtick command substitution → `subprocess`
- `$()` command substitution

### Globbing
- `*`, `?`, `[`, `]` patterns → `glob.glob()`
- Lazy expansion: glob patterns assigned to variables are expanded at use, not assignment

### External Commands
- Any unrecognised command → `subprocess.run([...])`

### Command-Line Arguments
- `$0`–`$9` → `sys.argv[0]`–`sys.argv[9]`
- `$#` → `len(sys.argv) - 1`
- `$@` → `sys.argv[1:]`

### Test Expressions
- `test` and `[` builtins fully supported
- File tests: `-f`, `-d`, `-r`, `-w`, `-x`, `-e`, `-s`, `-z`
- String comparisons: `=`, `!=`, `-z`, `-n`
- Numeric comparisons: `-eq`, `-ne`, `-lt`, `-le`, `-gt`, `-ge`
- Translated to idiomatic Python using `os.path` and `os.access`

## Usage

```bash
./sharpie.py <script.sh>
```

Output is written to stdout. Redirect to save:

```bash
./sharpie.py script.sh > script.py
chmod +x script.py
```

## Design Goals

- **Readable output** — preserves variable names, comments, and structure
- **Idiomatic Python** — uses `f-strings`, `glob`, `subprocess`, `sys`, `os` appropriately
- **Partial translation is useful** — constructs that can't be translated cleanly are flagged, not silently broken

## Limitations

- `test -ef` and `test -t` have no simple Python equivalent and are not supported
- Semantic edge cases (e.g. `$*` word splitting, empty glob behaviour) may differ from strict POSIX Shell — the goal is readable output, not exact semantic equivalence
- Nested backticks are not supported

## Requirements

- Python 3.6+
- No external dependencies
