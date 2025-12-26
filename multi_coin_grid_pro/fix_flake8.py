#!/usr/bin/env python3
"""
Script to automatically fix remaining flake8 errors
"""
import re
import subprocess


def fix_fstring_placeholders(file_path: str, line_num: int):
    """Fix f-strings without placeholders by converting them to regular strings"""
    with open(file_path, 'r') as f:
        lines = f.readlines()

    line_idx = line_num - 1
    line = lines[line_idx]

    # Replace f"..." with "..." and f'...' with '...'
    fixed_line = re.sub(r'f"([^"]*)"', r'"\1"', line)
    fixed_line = re.sub(r"f'([^']*)'", r"'\1'", fixed_line)

    if fixed_line != line:
        lines[line_idx] = fixed_line
        with open(file_path, 'w') as f:
            f.writelines(lines)
        return True
    return False


def fix_line_too_long(file_path: str, line_num: int):
    """Try to fix lines that are too long by smart line breaking"""
    with open(file_path, 'r') as f:
        lines = f.readlines()

    line_idx = line_num - 1
    line = lines[line_idx]

    # Skip if already a continuation
    if line_idx > 0 and lines[line_idx - 1].rstrip().endswith('\\'):
        return False

    indent = len(line) - len(line.lstrip())
    indent_str = ' ' * indent

    # Try to break at logical points
    if ', ' in line and len(line) > 120:
        # Break at commas
        parts = line.split(', ')
        if len(parts) > 1:
            new_lines = []
            current = parts[0]
            for part in parts[1:]:
                if len(current + ', ' + part) <= 120:
                    current += ', ' + part
                else:
                    new_lines.append(current + ',\n')
                    current = indent_str + '    ' + part
            new_lines.append(current)

            lines[line_idx] = ''.join(new_lines)
            with open(file_path, 'w') as f:
                f.writelines(lines)
            return True

    # Try to break long strings
    if 'prompt=' in line or 'prompt_on_new=' in line:
        match = re.search(r'prompt=lambda mi: "(.+)"', line)
        if match and len(line) > 120:
            prompt_text = match.group(1)
            # Break into multiple lines
            new_line = line.replace(
                f'lambda mi: "{prompt_text}"',
                f'lambda mi: (\n{indent_str}        "{prompt_text}"\n{indent_str}    )'
            )
            lines[line_idx] = new_line
            with open(file_path, 'w') as f:
                f.writelines(lines)
            return True

    return False


def main():
    # Get all flake8 errors
    result = subprocess.run(
        ['bash', 'lint_all.sh'],
        cwd='/home/mo/repos/hummingbot/multi_coin_grid_pro',
        capture_output=True,
        text=True
    )

    errors = []
    for line in result.stdout.split('\n'):
        match = re.match(r'^([^:]+):(\d+):\d+: (F541|E501) (.+)$', line)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(2))
            error_code = match.group(3)
            errors.append((file_path, line_num, error_code))

    print(f"Found {len(errors)} errors to fix")

    fixed_count = 0
    for file_path, line_num, error_code in errors:
        full_path = f'/home/mo/repos/hummingbot/multi_coin_grid_pro/{file_path}'

        if error_code == 'F541':
            if fix_fstring_placeholders(full_path, line_num):
                fixed_count += 1
                print(f"Fixed F541 in {file_path}:{line_num}")
        elif error_code == 'E501':
            if fix_line_too_long(full_path, line_num):
                fixed_count += 1
                print(f"Fixed E501 in {file_path}:{line_num}")

    print(f"\nFixed {fixed_count} errors automatically")

    # Run autopep8 again to clean up
    subprocess.run([
        'autopep8', '--in-place', '--aggressive', '--aggressive',
        '--max-line-length', '120', '--recursive',
        '--exclude', 'venv,data,logs', '.'
    ], cwd='/home/mo/repos/hummingbot/multi_coin_grid_pro')


if __name__ == '__main__':
    main()
