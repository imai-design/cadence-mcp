import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import copy_guard


class TestCopyGuard(unittest.TestCase):
    def test_flags_diagnostic_language(self):
        self.assertFalse(copy_guard.is_safe_copy("あなたは躁状態です"))
        self.assertFalse(copy_guard.is_safe_copy("これを治します"))

    def test_flags_shaming_language(self):
        self.assertFalse(copy_guard.is_safe_copy("サボってますね"))
        self.assertFalse(copy_guard.is_safe_copy("記録が途切れました"))

    def test_flags_comparison(self):
        self.assertFalse(copy_guard.is_safe_copy("あなたは平均より下です"))
        self.assertFalse(copy_guard.is_safe_copy("ランキングは3位"))

    def test_allows_gentle_copy(self):
        for text in [
            "今日のチェックインを記録しました。",
            "終わらなくても大丈夫です。",
            "良し悪しは測りません。過去のあなたとだけ比べた足あとです。",
            "一人で抱えなくていいです。",
        ]:
            self.assertTrue(copy_guard.is_safe_copy(text), text)


if __name__ == "__main__":
    unittest.main()
