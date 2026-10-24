from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ('backend', 'db', 'firmware', 'webui', 'ops')
FORBIDDEN = 'device' + '_id'

class ForbiddenLegacyIdentifierTests(unittest.TestCase):
    def test_runtime_files_do_not_reference_legacy_identifier(self):
        violations = []
        extensions = {'.py', '.sql', '.ino', '.h', '.hpp', '.cpp', '.js', '.jsx', '.ts', '.tsx', '.html', '.css', '.json', '.yml', '.yaml', '.toml', '.sh'}
        for relative_dir in RUNTIME_DIRS:
            directory = ROOT / relative_dir
            if not directory.exists():
                continue
            for path in directory.rglob('*'):
                if not path.is_file() or path.suffix.lower() not in extensions:
                    continue
                try:
                    content = path.read_text(encoding='utf-8')
                except UnicodeDecodeError:
                    continue
                for line_number, line in enumerate(content.splitlines(), start=1):
                    if FORBIDDEN in line:
                        violations.append(f'{path.relative_to(ROOT)}:{line_number}: {line.strip()}')
        self.assertEqual(violations, [], 'Forbidden legacy identifier found in v2 runtime files:\n' + '\n'.join(violations))

if __name__ == '__main__':
    unittest.main()
