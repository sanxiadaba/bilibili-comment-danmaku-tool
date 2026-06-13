import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_encoding  # noqa: E402


class EncodingGuardTests(unittest.TestCase):
    def test_encoding_guard_rejects_bom_and_mojibake(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bom_file = root / "bom.ts"
            mojibake_file = root / "bad.tsx"
            bom_file.write_bytes(b"\xef\xbb\xbfconst value = 1;\n")
            mojibake_file.write_text('const label = "' + "\u747e\u55db\ue575" + '";\n', encoding="utf-8")

            with mock.patch.object(check_encoding, "ROOT", root), redirect_stdout(StringIO()):
                code = check_encoding.main()

        self.assertEqual(code, 1)

    def test_encoding_guard_accepts_utf8_chinese(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "ok.tsx"
            source.write_text('const label = "视频列表";\n', encoding="utf-8")

            with mock.patch.object(check_encoding, "ROOT", root), redirect_stdout(StringIO()):
                code = check_encoding.main()

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
