import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cadence import safety


class TestCrisisDetection(unittest.TestCase):
    def test_detects_suicidal_language(self):
        for text in ["もう死にたい", "消えたい気分", "いなくなりたい", "生きる意味がわからない"]:
            self.assertTrue(safety.detect_crisis(text), text)

    def test_detects_expanded_crisis_phrasing(self):
        # 否定形・略語・助詞抜き・複合語まで安全側に広く拾えること（取りこぼし防止）
        for text in [
            "もう死ぬしかない", "死ぬ以外に道がない",
            "もう生きたくない", "正直、生きていたくない",
            "消えてなくなりたい",
            "電車に飛び込みたい",
            "また自傷してしまった",
            "ODしそう", "薬を過剰摂取した", "オーバードーズ",
            "首吊りたい",
            "存在価値がない", "生きてる意味が無い",
        ]:
            self.assertTrue(safety.detect_crisis(text), text)

    def test_ignores_neutral_language(self):
        for text in ["今日は調子がいい", "散歩した", "ごはんを食べた", ""]:
            self.assertFalse(safety.detect_crisis(text), text)

    def test_avoids_false_positives_near_expanded_patterns(self):
        # 拡張パターンが良性・紛らわしい語を誤検出しないこと（誤爆ガード）
        for text in [
            "ODA（政府開発援助）について調べた",  # OD の直後が英字 → 除外
            "GOODな一日だった",                    # OD の直前が英字 → 除外
            "method を実装した",                   # 小文字 od は対象外
            "長生きしたい",                        # 生きたい（前進）
            "今日も生きてるだけで偉い",            # 自己肯定
            "首都圏に住んでいる",                  # 首都（吊/つ ではない）
        ]:
            self.assertFalse(safety.detect_crisis(text), text)

    def test_crisis_message_lists_real_hotlines(self):
        msg = safety.crisis_message()
        self.assertIn("よりそいホットライン", msg)
        self.assertIn("0120-279-338", msg)
        self.assertIn("いのちの電話", msg)
        self.assertIn("一人で抱えなくていい", msg)


class TestMedicationGuards(unittest.TestCase):
    def test_detects_discontinuation_intent(self):
        for text in ["薬やめたい", "もう薬を飲むのをやめる", "断薬しようと思う", "自分で減らす"]:
            self.assertTrue(safety.detect_med_discontinuation(text), text)

    def test_detects_medical_advice_request(self):
        for text in ["何mg飲めばいい？", "200mgに増やしても大丈夫？", "この薬の飲み合わせは？", "これは躁ですか"]:
            self.assertTrue(safety.detect_medical_advice_request(text), text)

    def test_nudge_does_not_prescribe(self):
        msg = safety.med_nudge_message()
        self.assertIn("主治医", msg)
        # 用量や具体的なやめ方を指示しない
        self.assertNotIn("mg", msg)


if __name__ == "__main__":
    unittest.main()
