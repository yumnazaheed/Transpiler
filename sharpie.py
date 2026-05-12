#!/usr/bin/env python3

import builtins
import keyword
import re
import sys


PYTHON_HEADER = "#!/usr/bin/python3 -u"
PYTHON_RESERVED_WORDS = keyword.kwlist + dir(builtins)

# these just keep track of what the generated Python will need
used_imports = []
needs_run_helper = False
needs_capture_helper = False
case_counter = 0
variable_names = {}


def add_import(import_name):
    # keeping imports in a normal list so it stays simple
    if import_name not in used_imports:
        used_imports.append(import_name)


def split_comment(line):
    # SUBSET 0: split one shell line into code and comment
    # but only if the # is really starting a comment
    quote_type = None
    bracket_depth = 0
    position = 0

    while position < len(line):
        character = line[position]

        if quote_type == "'":
            if character == "'":
                quote_type = None
        elif quote_type == '"':
            if character == '"':
                quote_type = None
        elif quote_type == "`":
            if character == "`":
                quote_type = None
        else:
            if line.startswith("$((", position):
                bracket_depth += 2
                position += 2
                continue
            if line.startswith("$(", position):
                bracket_depth += 1
                position += 2
                continue
            if character == "(" and bracket_depth:
                bracket_depth += 1
            elif character == ")" and bracket_depth:
                bracket_depth -= 1
            elif character in "'\"`":
                quote_type = character
            elif character == "#" and (position == 0 or line[position - 1].isspace()):
                return line[:position].rstrip(), line[position:]

        position += 1

    return line.rstrip(), ""


def skip_single_quotes(text, start_position):
    # move forward until it hits the matching single quote
    current_position = start_position + 1
    while current_position < len(text) and text[current_position] != "'":
        current_position += 1
    return current_position


def skip_double_quotes(text, start_position):
    # move forward until hit the matching double quote
    current_position = start_position + 1
    while current_position < len(text):
        if text[current_position] == '"':
            return current_position
        current_position += 1
    return current_position


def skip_backticks(text, start_position):
    #backticks
    current_position = start_position + 1
    while current_position < len(text) and text[current_position] != "`":
        current_position += 1
    return current_position


def find_matching_parentheses(text, start_position, arithmetic=False):
    # this finds the end of $(...) or $((..))
    bracket_depth = 1
    current_position = start_position

    while current_position < len(text):
        if text.startswith("$((", current_position):
            bracket_depth += 1
            current_position += 3
            continue
        if text.startswith("$(", current_position):
            bracket_depth += 1
            current_position += 2
            continue
        if arithmetic and text.startswith("))", current_position):
            bracket_depth -= 1
            current_position += 2
            if bracket_depth == 0:
                return current_position
            continue
        if text[current_position] == "(":
            bracket_depth += 1
        elif text[current_position] == ")":
            bracket_depth -= 1
            if bracket_depth == 0:
                return current_position + 1
        elif text[current_position] == "'":
            current_position = skip_single_quotes(text, current_position)
        elif text[current_position] == '"':
            current_position = skip_double_quotes(text, current_position)
        elif text[current_position] == "`":
            current_position = skip_backticks(text, current_position)
        current_position += 1

    return len(text)


def tokenize(shell_text):
    # split shell text into tokens
    # quoted strings and substitutions stay together as one token
    tokens = []
    current_token = []
    position = 0

    while position < len(shell_text):
        character = shell_text[position]

        if character.isspace():
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
            position += 1
            continue

        if shell_text.startswith("&&", position) or shell_text.startswith("||", position) or shell_text.startswith(">>", position):
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
            tokens.append(shell_text[position:position + 2])
            position += 2
            continue

        if character in "<>":
            if current_token:
                tokens.append("".join(current_token))
                current_token = []
            tokens.append(character)
            position += 1
            continue

        if character == "'":
            end_position = skip_single_quotes(shell_text, position)
            current_token.append(shell_text[position:end_position + 1])
            position = end_position + 1
            continue

        if character == '"':
            end_position = skip_double_quotes(shell_text, position)
            current_token.append(shell_text[position:end_position + 1])
            position = end_position + 1
            continue

        if character == "`":
            end_position = skip_backticks(shell_text, position)
            current_token.append(shell_text[position:end_position + 1])
            position = end_position + 1
            continue

        if shell_text.startswith("$((", position):
            end_position = find_matching_parentheses(shell_text, position + 3, arithmetic=True)
            current_token.append(shell_text[position:end_position])
            position = end_position
            continue

        if shell_text.startswith("$(", position):
            end_position = find_matching_parentheses(shell_text, position + 2)
            current_token.append(shell_text[position:end_position])
            position = end_position
            continue

        current_token.append(character)
        position += 1

    if current_token:
        tokens.append("".join(current_token))

    return tokens


def python_string(text):
    # making a safe python string
    escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped_text}"'


def safe_variable_name(name):
    # SUBSET 0: avoid bad Python variable names
    # for example if shell uses pass or print as a variable
    if name not in variable_names:
        new_name = name
        if not re.fullmatch(r"[A-Za-z_]\w*", new_name) or new_name in PYTHON_RESERVED_WORDS:
            new_name = f"{new_name}_value"
        variable_names[name] = new_name
    return variable_names[name]

def translate_arithmetic(expression):
    # SUBSET 4: turn $((...)) into python arithmetic
    expression = expression.strip()

    def replace_name(match):
        name = match.group(0)
        if name.isdigit():
            return name
        return f"int({safe_variable_name(name)})"

    return re.sub(r"\b[A-Za-z_]\w*\b|\b\d+\b", replace_name, expression)


def translate_command_substitution(command_text):
    # SUBSET 3/4: both backticks and $(...) use capture_command(...)
    global needs_capture_helper

    tokens = tokenize(command_text.strip())
    argument_expression, _ = translate_command_arguments(tokens)
    add_import("subprocess")
    needs_capture_helper = True
    return f"capture_command({argument_expression})"


def parse_double_quoted_parts(text):
    # SUBSET 3: inside double quotes
    # variables and command substitutions still work
    # but spaces and glob characters stay as normal text
    parts = []
    literal_text = []
    position = 0

    def flush_literal():
        if literal_text:
            parts.append(("literal", "".join(literal_text)))
            literal_text.clear()

    while position < len(text):
        if text[position] == "`":
            end_position = skip_backticks(text, position)
            flush_literal()
            parts.append(("expression", 
                translate_command_substitution(text[position + 1:end_position])))
            position = end_position + 1
            continue

        if text.startswith("$((", position):
            end_position = find_matching_parentheses(text, 
                position + 3, arithmetic=True)
            flush_literal()
            inner_expression = text[position + 3:end_position - 2]
            parts.append(("expression", 
                f"str({translate_arithmetic(inner_expression)})"))
            position = end_position
            continue

        if text.startswith("$(", position):
            end_position = find_matching_parentheses(text, position + 2)
            flush_literal()
            inner_command = text[position + 2:end_position - 1]
            parts.append(("expression", 
                translate_command_substitution(inner_command)))
            position = end_position
            continue

        if text.startswith("${", position):
            end_position = text.find("}", position + 2)
            flush_literal()
            parts.append(("expression", 
                safe_variable_name(text[position + 2:end_position])))
            position = end_position + 1
            continue

        if text.startswith("$#", position):
            flush_literal()
            add_import("sys")
            parts.append(("expression", "str(len(sys.argv) - 1)"))
            position += 2
            continue

        if text.startswith("$@", position):
            flush_literal()
            add_import("sys")
            parts.append(("expression", '" ".join(sys.argv[1:])'))
            position += 2
            continue

        if re.match(r"\$\d", text[position:]):
            flush_literal()
            add_import("sys")
            digit = text[position + 1]
            parts.append(("expression", f"sys.argv[{digit}]"))
            position += 2
            continue

        if text[position] == "$":
            match = re.match(r"\$([A-Za-z_]\w*)", text[position:])
            if match:
                flush_literal()
                parts.append(("expression", safe_variable_name(match.group(1))))
                position += len(match.group(0))
                continue

        literal_text.append(text[position])
        position += 1

    flush_literal()
    return parts


def parse_word_parts(text):
    # break one shell word into smaller pieces
    # for example literal text, variables, or command substitutions
    parts = []
    literal_text = []
    position = 0

    def flush_literal():
        if literal_text:
            parts.append(("literal", "".join(literal_text)))
            literal_text.clear()

    while position < len(text):
        if text[position] == "'":
            end_position = skip_single_quotes(text, position)
            literal_text.append(text[position + 1:end_position])
            position = end_position + 1
            continue

        if text[position] == '"':
            end_position = skip_double_quotes(text, position)
            flush_literal()
            parts.extend(parse_double_quoted_parts(text[position + 1:end_position]))
            position = end_position + 1
            continue

        if text[position] == "`":
            end_position = skip_backticks(text, position)
            flush_literal()
            parts.append(("expression", translate_command_substitution(text[position + 1:end_position])))
            position = end_position + 1
            continue

        if text.startswith("$((", position):
            end_position = find_matching_parentheses(text, position + 3, arithmetic=True)
            flush_literal()
            inner_expression = text[position + 3:end_position - 2]
            parts.append(("expression", f"str({translate_arithmetic(inner_expression)})"))
            position = end_position
            continue

        if text.startswith("$(", position):
            end_position = find_matching_parentheses(text, position + 2)
            flush_literal()
            inner_command = text[position + 2:end_position - 1]
            parts.append(("expression", translate_command_substitution(inner_command)))
            position = end_position
            continue

        if text.startswith("${", position):
            end_position = text.find("}", position + 2)
            flush_literal()
            parts.append(("expression", safe_variable_name(text[position + 2:end_position])))
            position = end_position + 1
            continue

        if text.startswith("$#", position):
            flush_literal()
            add_import("sys")
            parts.append(("expression", "str(len(sys.argv) - 1)"))
            position += 2
            continue

        if text.startswith("$@", position):
            flush_literal()
            parts.append(("argument_list", ""))
            position += 2
            continue

        if re.match(r"\$\d", text[position:]):
            flush_literal()
            add_import("sys")
            digit = text[position + 1]
            parts.append(("expression", f"sys.argv[{digit}]"))
            position += 2
            continue

        if text[position] == "$":
            match = re.match(r"\$([A-Za-z_]\w*)", text[position:])
            if match:
                flush_literal()
                parts.append(("expression", safe_variable_name(match.group(1))))
                position += len(match.group(0))
                continue

        literal_text.append(text[position])
        position += 1

    flush_literal()
    return parts


def word_to_string_expression(text):
    # turn one shell word into a Python string expression
    parts = parse_word_parts(text)

    if not parts:
        return '""'

    if len(parts) == 1:
        part_type, part_value = parts[0]
        if part_type == "literal":
            return python_string(part_value)
        if part_type == "argument_list":
            add_import("sys")
            return '" ".join(sys.argv[1:])'
        return part_value

    python_parts = []
    for part_type, part_value in parts:
        if part_type == "literal":
            python_parts.append(python_string(part_value))
        elif part_type == "argument_list":
            add_import("sys")
            python_parts.append('" ".join(sys.argv[1:])')
        else:
            python_parts.append(part_value)

    return " + ".join(python_parts)


def token_has_unquoted_glob(token):
    # SUBSET 1: only unquoted glob characters should actually glob
    quote_type = None
    position = 0

    while position < len(token):
        character = token[position]
        if quote_type == "'":
            if character == "'":
                quote_type = None
        elif quote_type == '"':
            if character == '"':
                quote_type = None
        else:
            if character in "'\"":
                quote_type = character
            elif character in "*?[]":
                return True
        position += 1

    return False

def word_as_argument(token, allow_glob, allow_quoted_all_arguments=False):
    # this turns one shell token into:
    # either one value, or a whole list of values
    # that matters for things like globs and $@
    expression = word_to_string_expression(token)

    if token == '"$@"' and allow_quoted_all_arguments:
        return "sys.argv[1:]", True
    if token == "$@":
        return "sys.argv[1:]", True
    if allow_glob and token_has_unquoted_glob(token):
        add_import("glob")
        return f"sorted(glob.glob({expression}))", True

    return expression, False


def translate_test_tokens(tokens):
    # SUBSET 2/4: translate test and [ .. ] into Python conditions
    if tokens[0] == "[" and tokens[-1] == "]":
        tokens = tokens[1:-1]
    elif tokens[0] == "test":
        tokens = tokens[1:]

    add_import("os")

    if len(tokens) == 1:
        return f"{word_to_string_expression(tokens[0])} != ''"

    if len(tokens) == 2:
        operation, expression = tokens
        value = word_to_string_expression(expression)
        unary_operations = {
            "-z": f"{value} == ''",
            "-n": f"{value} != ''",
            "-e": f"os.path.exists({value})",
            "-f": f"os.path.isfile({value})",
            "-d": f"os.path.isdir({value})",
            "-r": f"os.access({value}, os.R_OK)",
            "-w": f"os.access({value}, os.W_OK)",
            "-x": f"os.access({value}, os.X_OK)",
            "-s": f"os.path.getsize({value}) > 0",
        }
        return unary_operations.get(operation, "False")

    if len(tokens) == 3:
        left_expression, operation, right_expression = tokens
        left_value = word_to_string_expression(left_expression)
        right_value = word_to_string_expression(right_expression)
        binary_operations = {
            "=": f"{left_value} == {right_value}",
            "!=": f"{left_value} != {right_value}",
            "-eq": f"int({left_value}) == int({right_value})",
            "-ne": f"int({left_value}) != int({right_value})",
            "-lt": f"int({left_value}) < int({right_value})",
            "-le": f"int({left_value}) <= int({right_value})",
            "-gt": f"int({left_value}) > int({right_value})",
            "-ge": f"int({left_value}) >= int({right_value})",
        }
        return binary_operations.get(operation, "False")

    return "False"

def translate_condition_command(tokens):
    # in subset 4 a condition can be test/ i.e.[..] or an external command
    if not tokens:
        return "False"
    if tokens[0] == "test" or tokens[0] == "[":
        return translate_test_tokens(tokens)
    return translate_external_command(tokens, 0, use_returncode=True)


def translate_condition(text):
    # SUBSET 4: handle && and || in if / while
    tokens = tokenize(text)
    or_groups = []
    current_or_group = []

    for token in tokens:
        if token == "||":
            or_groups.append(current_or_group)
            current_or_group = []
        else:
            current_or_group.append(token)
    or_groups.append(current_or_group)

    translated_or_groups = []

    for or_group in or_groups:
        and_groups = []
        current_and_group = []

        for token in or_group:
            if token == "&&":
                and_groups.append(current_and_group)
                current_and_group = []
            else:
                current_and_group.append(token)
        and_groups.append(current_and_group)

        translated_and_groups = [translate_condition_command(group) for group in and_groups]
        translated_or_groups.append(" and ".join(translated_and_groups))

    return " or ".join(translated_or_groups)


def translate_command_arguments(tokens):
    # build the subprocess arguments
    # and also pull out any redirections like < > >>
    argument_parts = []
    redirections = {}
    position = 0

    while position < len(tokens):
        token = tokens[position]

        if token == "<" or token == ">" or token == ">>":
            file_expression = word_to_string_expression(tokens[position + 1])
            if token == "<":
                redirections["stdin"] = file_expression
            else:
                redirections["stdout"] = file_expression
                redirections["append"] = "True" if token == ">>" else "False"
            position += 2
            continue

        expression, is_multiple_arguments = word_as_argument(
            token,
            allow_glob=True,
            allow_quoted_all_arguments=True,
        )
        if is_multiple_arguments:
            argument_parts.append(expression)
        else:
            argument_parts.append(f"[{expression}]")
        position += 1

    if argument_parts:
        argument_expression = " + ".join(argument_parts)
    else:
        argument_expression = "[]"

    return argument_expression, redirections


def translate_external_command(tokens, indent_level, use_returncode):
    # SUBSET 1/4: external commands
    # normal lines run the command
    # conditions check if the return code was 0
    global needs_run_helper

    argument_expression, redirections = translate_command_arguments(tokens)
    add_import("subprocess")
    needs_run_helper = True

    input_file = redirections.get("stdin", "None")
    output_file = redirections.get("stdout", "None")
    append_mode = redirections.get("append", "False")

    call_expression = (
        f"run_command({argument_expression}, stdin_path={input_file}, "
        f"stdout_path={output_file}, append={append_mode})"
    )

    if use_returncode:
        return f"{call_expression} == 0"
    return f"{'    ' * indent_level}{call_expression}"


def translate_echo(tokens, indent_level):
    # SUBSET 0/3: echo
    # this also handles echo -n
    end_expression = "'\\n'"

    if tokens and tokens[0] == "-n":
        end_expression = "''"
        tokens = tokens[1:]

    if not tokens:
        return f"{'    ' * indent_level}print(end={end_expression})"

    argument_groups = []
    for token in tokens:
        expression, is_multiple_arguments = word_as_argument(
            token,
            allow_glob=True,
            allow_quoted_all_arguments=True,
        )
        if is_multiple_arguments:
            argument_groups.append(expression)
        else:
            argument_groups.append(f"[{expression}]")

    return (
        f"{'    ' * indent_level}print(' '.join({' + '.join(argument_groups)}), "
        f"end={end_expression})"
    )


def translate_assignment(stripped_line, indent_level):
    # SUBSET 0: variable assignment
    variable_name, value = stripped_line.split("=", 1)
    python_name = safe_variable_name(variable_name)
    expression = word_to_string_expression(value)
    return f"{'    ' * indent_level}{python_name} = {expression}"


def is_assignment(stripped_line):
    # detect simple shell assignments like x=hello
    if "=" not in stripped_line:
        return False
    first_token = tokenize(stripped_line)[0]
    return bool(re.fullmatch(r"[A-Za-z_]\w*=.*", first_token))


def translate_simple_line(stripped_line, indent_level, comment):
    # translate one normal line
    tokens = tokenize(stripped_line)

    if is_assignment(stripped_line):
        translated_line = translate_assignment(stripped_line, indent_level)
    elif tokens[0] == "echo":
        translated_line = translate_echo(tokens[1:], indent_level)
    elif tokens[0] == "exit":
        add_import("sys")
        if len(tokens) == 1:
            translated_line = f"{'    ' * indent_level}sys.exit()"
        else:
            exit_value = tokens[1]
            if re.fullmatch(r"\d+", exit_value):
                translated_line = f"{'    ' * indent_level}sys.exit({exit_value})"
            else:
                translated_line = f"{'    ' * indent_level}sys.exit({word_to_string_expression(exit_value)})"
    elif tokens[0] == "cd":
        add_import("os")
        if len(tokens) == 1:
            translated_line = f"{'    ' * indent_level}os.chdir(\"\")"
        else:
            translated_line = f"{'    ' * indent_level}os.chdir({word_to_string_expression(tokens[1])})"
    elif tokens[0] == "read":
        python_name = safe_variable_name(tokens[1])
        translated_line = f"{'    ' * indent_level}{python_name} = input()"
    elif tokens[0] == "test" or tokens[0] == "[":
        translated_line = f"{'    ' * indent_level}{translate_test_tokens(tokens)}"
    else:
        translated_line = translate_external_command(tokens, indent_level, use_returncode=False)

    if comment:
        translated_line += f" {comment}"

    return translated_line

def translate_for_header(stripped_line):
    # getting the variable name and the values for a for loop
    tokens = tokenize(stripped_line)
    loop_variable = safe_variable_name(tokens[1])
    loop_items = tokens[3:]

    single_items = []
    list_expressions = []

    for item in loop_items:
        expression, is_multiple_arguments = word_as_argument(item, 
            allow_glob=True)
        if is_multiple_arguments:
            list_expressions.append(expression)
        else:
            single_items.append(expression)

    if list_expressions:
        pieces = []
        if single_items:
            pieces.append(f"[{', '.join(single_items)}]")
        pieces.extend(list_expressions)
        iterable_expression = " + ".join(pieces)
    else:
        iterable_expression = f"[{', '.join(single_items)}]"

    return loop_variable, iterable_expression


def translate_case_patterns(case_value_name, pattern_text):
    # SUBSET 4: case patterns act like globs
    add_import("fnmatch")
    patterns = [pattern.strip() for pattern in pattern_text.split("|")]
    checks = [
        f"fnmatch.fnmatch({case_value_name}, {python_string(pattern)})"
        for pattern in patterns
    ]
    return " or ".join(checks)

def translate_block(lines, start_index, indent_level, stop_words):
    # this is the main loop
    # it keeps translating until it reaches a closing keyword
    output = []
    current_index = start_index

    while current_index < len(lines):
        raw_line = lines[current_index].rstrip("\n")

        if raw_line.startswith("#!"):
            current_index += 1
            continue

        code, comment = split_comment(raw_line)
        stripped_line = code.strip()

        if not stripped_line:
            if comment:
                output.append(f"{'    ' * indent_level}{comment}")
            else:
                output.append("")
            current_index += 1
            continue

        first_word = stripped_line.split()[0]
        if stripped_line in stop_words or first_word in stop_words:
            break

        if first_word == "for":
            translated_lines, current_index = translate_for_block(lines, 
                current_index, indent_level, comment)
            output.extend(translated_lines)
            continue

        if first_word == "while":
            translated_lines, current_index = translate_while_block(lines, 
                current_index, indent_level, comment)
            output.extend(translated_lines)
            continue

        if first_word == "if":
            translated_lines, current_index = translate_if_block(lines, 
                current_index, indent_level, comment)
            output.extend(translated_lines)
            continue

        if first_word == "case":
            translated_lines, current_index = translate_case_block(lines, 
                current_index, indent_level, comment)
            output.extend(translated_lines)
            continue

        output.append(translate_simple_line(stripped_line, indent_level, 
            comment))
        current_index += 1

    return output, current_index


def translate_for_block(lines, start_index, indent_level, comment):
    # SUBSET 1/3: for loop
    code, _ = split_comment(lines[start_index].rstrip("\n"))
    stripped_line = code.strip()
    loop_variable, iterable_expression = translate_for_header(stripped_line)

    first_line = f"{'    ' * indent_level}for {loop_variable} in {iterable_expression}:"
    if comment:
        first_line += f" {comment}"

    do_index = start_index + 1
    while do_index < len(lines):
        code, _ = split_comment(lines[do_index].rstrip("\n"))
        if code.strip():
            break
        do_index += 1

    if do_index < len(lines):
        do_code, _ = split_comment(lines[do_index].rstrip("\n"))
        if do_code.strip() == "do":
            body_start = do_index + 1
        else:
            body_start = do_index
    else:
        body_start = do_index

    body_lines, end_index = translate_block(lines, body_start, 
        indent_level + 1, ["done"])
    return [first_line] + body_lines + [""], end_index + 1


def translate_while_block(lines, start_index, indent_level, comment):
    # SUBSET 2,3,4: while loop
    code, _ = split_comment(lines[start_index].rstrip("\n"))
    stripped_line = code.strip()
    condition_text = stripped_line[6:].strip()
    condition = translate_condition(condition_text)

    first_line = f"{'    ' * indent_level}while {condition}:"
    if comment:
        first_line += f" {comment}"

    do_index = start_index + 1
    while do_index < len(lines):
        code, _ = split_comment(lines[do_index].rstrip("\n"))
        if code.strip():
            break
        do_index += 1

    if do_index < len(lines):
        do_code, _ = split_comment(lines[do_index].rstrip("\n"))
        if do_code.strip() == "do":
            body_start = do_index + 1
        else:
            body_start = do_index
    else:
        body_start = do_index

    body_lines, end_index = translate_block(lines, body_start, 
        indent_level + 1, ["done"])
    return [first_line] + body_lines + [""], end_index + 1


def translate_if_block(lines, start_index, indent_level, comment):
    # SUBSET 2,3,4: if statement
    output = []
    current_index = start_index
    current_comment = comment
    current_keyword = "if"

    while True:
        code, _ = split_comment(lines[current_index].rstrip("\n"))
        stripped_line = code.strip()
        first_word = stripped_line.split()[0]
        condition_text = stripped_line[len(first_word):].strip()
        condition = translate_condition(condition_text)

        line = f"{'    ' * indent_level}{current_keyword} {condition}:"
        if current_comment:
            line += f" {current_comment}"
        output.append(line)

        then_index = current_index + 1
        while then_index < len(lines):
            code, _ = split_comment(lines[then_index].rstrip("\n"))
            if code.strip():
                break
            then_index += 1

        if then_index < len(lines):
            then_code, _ = split_comment(lines[then_index].rstrip("\n"))
            if then_code.strip() == "then":
                body_start = then_index + 1
            else:
                body_start = then_index
        else:
            body_start = then_index

        body_lines, next_index = translate_block(lines, body_start, 
            indent_level + 1, ["elif", "else", "fi"])
        output.extend(body_lines)

        if next_index >= len(lines):
            return output, next_index

        next_code, next_comment = split_comment(lines[next_index].rstrip("\n"))
        next_line = next_code.strip()

        if next_line == "fi":
            output.append("")
            return output, next_index + 1

        if next_line == "else":
            else_line = f"{'    ' * indent_level}else:"
            if next_comment:
                else_line += f" {next_comment}"
            output.append(else_line)
            else_body, end_index = translate_block(lines, next_index + 1, 
                indent_level + 1, ["fi"])
            output.extend(else_body)
            output.append("")
            return output, end_index + 1

        current_index = next_index
        current_comment = next_comment
        current_keyword = "elif"


def translate_case_block(lines, start_index, indent_level, comment):
    # SUBSET 4: case statement
    global case_counter

    code, _ = split_comment(lines[start_index].rstrip("\n"))
    stripped_line = code.strip()
    expression = stripped_line[5:].strip()
    if expression.endswith(" in"):
        expression = expression[:-3].rstrip()

    case_value_name = f"case_value_{case_counter}"
    case_counter += 1

    first_line = f"{'    ' * indent_level}{case_value_name} = {word_to_string_expression(expression)}"
    if comment:
        first_line += f" {comment}"

    output = [first_line]
    current_index = start_index + 1
    first_branch = True

    while current_index < len(lines):
        raw_line = lines[current_index].rstrip("\n")
        code, branch_comment = split_comment(raw_line)
        stripped_line = code.strip()

        if not stripped_line:
            if branch_comment:
                output.append(f"{'    ' * indent_level}{branch_comment}")
            else:
                output.append("")
            current_index += 1
            continue

        if stripped_line == "esac":
            output.append("")
            return output, current_index + 1

        if not stripped_line.endswith(")"):
            output.append(f"{'    ' * indent_level}# untranslated case line: {stripped_line}")
            current_index += 1
            continue

        pattern_text = stripped_line[:-1].strip()
        condition = translate_case_patterns(case_value_name, pattern_text)
        keyword_name = "if" if first_branch else "elif"

        line = f"{'    ' * indent_level}{keyword_name} {condition}:"
        if branch_comment:
            line += f" {branch_comment}"
        output.append(line)

        branch_body, end_index = translate_block(lines, current_index + 1, 
            indent_level + 1, [";;", "esac"])
        output.extend(branch_body)

        if end_index < len(lines):
            end_code, _ = split_comment(lines[end_index].rstrip("\n"))
            if end_code.strip() == ";;":
                current_index = end_index + 1
            else:
                current_index = end_index
        else:
            current_index = end_index

        first_branch = False

    return output, current_index


def helper_lines():
    # only print helper functions if they are actually needed
    lines = []

    if needs_run_helper:
        lines.extend([
            "def run_command(arguments, stdin_path=None, stdout_path=None, append=False):",
            "    input_handle = open(stdin_path, encoding='utf-8') if stdin_path else None",
            "    mode = 'a' if append else 'w'",
            "    output_handle = open(stdout_path, mode, encoding='utf-8') if stdout_path else None",
            "    try:",
            "        return subprocess.run(",
            "            arguments,",
            "            text=True,",
            "            stdin=input_handle,",
            "            stdout=output_handle,",
            "        ).returncode",
            "    finally:",
            "        if input_handle is not None:",
            "            input_handle.close()",
            "        if output_handle is not None:",
            "            output_handle.close()",
            "",
        ])

    if needs_capture_helper:
        lines.extend([
            "def capture_command(arguments):",
            "    return subprocess.run(",
            "        arguments,",
            "        text=True,",
            "        stdout=subprocess.PIPE,",
            "    ).stdout.rstrip('\\n')",
            "",
        ])

    return lines


def translate_script(lines):
    # translate the whole shell script
    # imports and helper functions go at the top
    translated_body, _ = translate_block(lines, 0, 0, [])

    output_lines = [PYTHON_HEADER, ""]
    if used_imports:
        ordered_imports = []
        import_name_order = ["fnmatch", "glob", "os", "subprocess", "sys"]

        for import_name in import_name_order:
            if import_name in used_imports:
                ordered_imports.append(import_name)

        output_lines.append(f"import {', '.join(ordered_imports)}")
        output_lines.append("")

    output_lines.extend(helper_lines())
    output_lines.extend(translated_body)

    while output_lines and output_lines[-1] == "":
        output_lines.pop()

    return "\n".join(output_lines) + "\n"


def main():
    # takes one shell script pathname
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} shell-script", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as shell_file:
        lines = shell_file.readlines()

    sys.stdout.write(translate_script(lines))


if __name__ == "__main__":
    main()
