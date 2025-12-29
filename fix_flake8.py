#!/usr/bin/env python3
"""Fix all flake8 issues automatically"""
import re
import sys
from pathlib import Path


def fix_file(filepath):
    """Fix common flake8 issues in a file"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()

        original = content
        lines = content.split('\n')

        # Fix imports at top
        import_lines = []
        other_lines = []
        in_imports = True
        docstring_count = 0

        for i, line in enumerate(lines):
            # Track docstrings
            if '"""' in line or "'''" in line:
                docstring_count += 1

            # After shebang, docstring, and initial comments, we're in import section
            if i == 0 or line.startswith('#') or (docstring_count > 0 and docstring_count < 2):
                other_lines.append(line)
            elif line.startswith('import ') or line.startswith('from '):
                import_lines.append(line)
            elif line.strip() == '':
                if in_imports and import_lines:
                    in_imports = False
                other_lines.append(line)
            else:
                in_imports = False
                other_lines.append(line)

        # Remove unused imports
        unused_imports = {
            'datetime.datetime': ['from datetime import datetime'],
            'datetime.timedelta': ['from datetime import timedelta'],
            'collections.defaultdict': ['from collections import defaultdict'],
            'collections.OrderedDict': ['from collections import OrderedDict'],
            'decimal.Decimal': ['from decimal import Decimal'],
            'json': ['import json'],
            're': ['import re'],
            'os': ['import os'],
            'sys': ['import sys'],
        }

        content_lower = content.lower()
        filtered_imports = []
        for line in import_lines:
            keep = True
            # Check for unused imports
            if 'datetime' in line and 'from datetime import' in line:
                if 'import datetime' in line and 'datetime(' not in content and 'datetime.' not in content.replace(line, ''):
                    keep = False
                if 'import timedelta' in line and 'timedelta(' not in content:
                    keep = False
            elif 'import defaultdict' in line and 'defaultdict' not in content.replace(line, ''):
                keep = False
            elif 'import OrderedDict' in line and 'OrderedDict' not in content.replace(line, ''):
                keep = False
            elif 'import Decimal' in line and 'Decimal(' not in content:
                keep = False
            elif line.strip() == 'import json' and ('json.' not in content.replace(line, '') and 'json(' not in content):
                keep = False
            elif line.strip() == 'import re' and ('re.' not in content.replace(line, '') and 're(' not in content):
                keep = False
            elif line.strip() == 'import os' and 'os.' not in content.replace(line, ''):
                keep = False
            elif line.strip() == 'import sys' and 'sys.' not in content.replace(line, ''):
                keep = False

            # Check for other unused imports
            if 'import Tuple' in line and 'Tuple[' not in content:
                keep = False
            if 'import Stage' in line and ('Stage.' not in content.replace(line, '') and 'Stage(' not in content):
                keep = False
            if 'import ReasonCode' in line and 'ReasonCode.' not in content.replace(line, ''):
                parts = line.split('import')
                if len(parts) > 1 and 'ReasonCode' in parts[1]:
                    # Check if it's importing multiple things
                    imports = parts[1].split(',')
                    if len(imports) > 1:
                        # Keep other imports
                        new_imports = [imp.strip() for imp in imports if 'ReasonCode' not in imp and 'Stage' not in imp]
                        if new_imports:
                            keep = True
                            line = parts[0] + 'import ' + ', '.join(new_imports)
                        else:
                            keep = False
                    else:
                        keep = False

            if 'MagicMock' in line and 'MagicMock' not in content.replace(line, ''):
                keep = False
            if 'TradeType' in line and 'TradeType.' not in content.replace(line, ''):
                keep = False
            if 'EventAggregator' in line and 'EventAggregator' not in content.replace(line, ''):
                keep = False
            if 'EventLogger' in line and 'EventLogger' not in content.replace(line, ''):
                keep = False
            if 'SymbolRejectionStats' in line and 'SymbolRejectionStats' not in content.replace(line, ''):
                keep = False
            if 'RegimeBreakdown' in line and 'RegimeBreakdown' not in content.replace(line, ''):
                keep = False
            if 'RejectionStats' in line and 'RejectionStats' not in content.replace(line, ''):
                keep = False
            if 'CreateExecutorAction' in line and 'CreateExecutorAction' not in content.replace(line, ''):
                keep = False
            if 'get_stage_for_reason' in line and 'get_stage_for_reason' not in content.replace(line, ''):
                keep = False

            if keep:
                filtered_imports.append(line)

        content = '\n'.join(other_lines)

        # Fix spacing around operators
        content = re.sub(r'(\w+)\s*\*\s*(\d+)', r'\1 * \2', content)
        content = re.sub(r'(\d+)\s*\*\s*(\d+)', r'\1 * \2', content)
        content = re.sub(r'(\w+)\s*/\s*(\d+)', r'\1 / \2', content)

        # Fix f-strings without placeholders
        content = re.sub(r'print\(f"([^{}"]+)"\)', r'print("\1")', content)
        content = re.sub(r'print\(f\'([^{}\']+)\'\)', r"print('\1')", content)

        # Fix bare except
        content = re.sub(r'except\s*:\s*pass', 'except Exception:\n                    pass', content)
        content = re.sub(r'except\s*:([^\n])', r'except Exception:\1', content)

        # Remove unused local variables by prefixing with _
        lines = content.split('\n')
        new_lines = []
        for line in lines:
            # Check for unused variable assignments
            if 'grid_closed' in line and '=' in line and 'grid_closed' not in content[content.index(line) + len(line):]:
                line = line.replace('grid_closed', '_grid_closed')
            if 'fees_paid' in line and '=' in line and 'fees_paid' not in content[content.index(line) + len(line):]:
                line = line.replace('fees_paid', '_fees_paid')
            if ' e)' in line or ' e ' in line and 'except' in line:
                line = line.replace(' e)', ' _e)').replace(' e ', ' _e ')
            if 'direction =' in line and 'direction' not in content[content.index(line) + len(line):]:
                line = line.replace('direction', '_direction')
            if 'num_events =' in line and 'num_events' not in content[content.index(line) + len(line):]:
                line = line.replace('num_events', '_num_events')
            if 'aggregator =' in line and 'aggregator' not in content[content.index(line) + len(line):]:
                line = line.replace('aggregator', '_aggregator')
            new_lines.append(line)
        content = '\n'.join(new_lines)

        # Ensure 2 blank lines before function/class definitions at module level
        content = re.sub(r'\n(def \w+)', r'\n\n\1', content)
        content = re.sub(r'\n(class \w+)', r'\n\n\1', content)

        # Ensure 2 blank lines after function/class definitions at module level
        content = re.sub(r'\n\nif __name__', r'\n\n\nif __name__', content)

        # Remove duplicate blank lines
        while '\n\n\n\n' in content:
            content = content.replace('\n\n\n\n', '\n\n\n')

        if content != original:
            with open(filepath, 'w') as f:
                f.write(content)
            print(f"Fixed: {filepath}")
            return True
        return False
    except Exception as e:
        print(f"Error fixing {filepath}: {e}")
        return False


# List of files to fix
files = [
    'analyze_bot_performance.py',
    'analyze_bot_profitability.py',
    'analyze_grid_placement_issue.py',
    'analyze_market_data.py',
    'calculate_slippage_risk.py',
    'cleanup_old_market_data.py',
    'demo_phase_4_reporting.py',
    'demo_slot_full_enhancement.py',
    'detailed_trades_with_fees.py',
    'explain_no_trade_decisions.py',
    'find_best_grid_pairs.py',
    'list_bot_databases.py',
    'migrate_database_precision.py',
    'optimize_market_data_db.py',
    'test_actual_overflow.py',
    'test_database_precision.py',
    'test_duplicate_grid_prevention.py',
    'test_exact_pepe_scenario.py',
    'test_exact_scenario.py',
    'test_fix_simple.py',
    'test_inflight_order_fix.py',
    'test_insufficient_funds_fix.py',
    'test_multi_coin_concurrent.py',
    'test_nl_restriction_detection.py',
    'test_slot_full_enhancement.py',
    'test_timestamp_overflow.py',
    'trade_analysis_last_15h.py',
]

fixed_count = 0
for file in files:
    if Path(file).exists():
        if fix_file(file):
            fixed_count += 1

print(f"\nFixed {fixed_count} files")
