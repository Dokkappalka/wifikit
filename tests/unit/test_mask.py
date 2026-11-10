import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core import mask  # noqa: E402
from core.base import WilfiError  # noqa: E402


def P(kind, value=""):
    return {"kind": kind, "value": value}


class BuildTest(unittest.TestCase):
    def test_all_any_eight(self):
        spec = mask.build([P("any")] * 8, 8, 8)
        self.assertEqual(spec.mask, "?a?a?a?a?a?a?a?a")
        self.assertEqual(spec.keyspace, 95 ** 8)
        self.assertFalse(spec.incremental)

    def test_fixed_prefix_and_digit_tail(self):
        pos = [P("upper"), P("lower"), P("lower"), P("digit"), P("fixed", "-"),
               P("digit"), P("digit"), P("digit")]
        spec = mask.build(pos, 8, 8)
        self.assertEqual(spec.mask, "?u?l?l?d-?d?d?d")
        self.assertEqual(spec.keyspace, 26 ** 3 * 10 ** 4)

    def test_custom_sets_are_numbered_and_deduped(self):
        pos = [P("custom", "abc"), P("custom", "abc"), P("custom", "xy"), P("digit")]
        spec = mask.build(pos, 4, 4)
        self.assertEqual(spec.mask, "?1?1?2?d")
        self.assertEqual([c for c in spec.charsets], [(1, "abc"), (2, "xy")])
        self.assertEqual(spec.keyspace, 3 * 3 * 2 * 10)

    def test_more_than_four_sets_is_refused(self):
        pos = [P("custom", c) for c in ("ab", "cd", "ef", "gh", "ij")]
        with self.assertRaises(WilfiError) as ctx:
            mask.build(pos, 5, 5)
        self.assertEqual(ctx.exception.code, "too_many_sets")

    def test_range_pads_with_last_kind_and_sets_incremental(self):
        spec = mask.build([P("digit")] * 3, 3, 5)
        self.assertEqual(spec.mask, "?d?d?d?d?d")
        self.assertEqual((spec.length_min, spec.length_max), (3, 5))
        self.assertTrue(spec.incremental)
        frag = spec.argv_fragment()
        self.assertIn("-i", frag)
        self.assertIn("--increment-min=3", frag)
        self.assertIn("--increment-max=5", frag)

    def test_range_pads_with_any_when_last_is_fixed(self):
        spec = mask.build([P("digit"), P("fixed", "-")], 2, 4, pad="auto")
        self.assertEqual(spec.mask, "?d-?a?a")

    def test_explicit_pad_any(self):
        spec = mask.build([P("digit")] * 3, 3, 4, pad="any")
        self.assertEqual(spec.mask, "?d?d?d?a")

    def test_range_shorter_than_positions_is_clamped(self):
        spec = mask.build([P("digit")] * 6, 4, 6)
        self.assertEqual(spec.length_min, 6)
        self.assertTrue(any("меньше числа" in w for w in spec.warnings))

    def test_keyspace_sums_over_range(self):
        spec = mask.build([P("digit")] * 2, 2, 3)
        self.assertEqual(spec.keyspace, 10 ** 2 + 10 ** 3)

    def test_short_length_warns(self):
        spec = mask.build([P("digit")] * 4, 4, 4)
        self.assertTrue(any("8" in w for w in spec.warnings))

    def test_too_long_is_refused(self):
        with self.assertRaises(WilfiError):
            mask.build([P("any")] * 8, 8, 70)

    def test_fixed_question_mark_is_escaped(self):
        spec = mask.build([P("fixed", "?")], 1, 1)
        self.assertEqual(spec.mask, "??")

    def test_non_ascii_fixed_refused(self):
        with self.assertRaises(WilfiError):
            mask.build([P("fixed", "ы")], 1, 1)

    def test_empty_positions_refused(self):
        with self.assertRaises(WilfiError):
            mask.build([], 8, 8)

    def test_unknown_kind_refused(self):
        with self.assertRaises(WilfiError):
            mask.build([P("vowel")], 1, 1)

    def test_fixed_needs_single_char(self):
        with self.assertRaises(WilfiError):
            mask.build([P("fixed", "ab")], 1, 1)

    def test_summary_is_serialisable(self):
        spec = mask.build([P("custom", "ab"), P("upper")], 2, 2)
        data = spec.summary()
        self.assertEqual(data["mask"], "?1?u")
        self.assertEqual(data["charsets"], [{"slot": 1, "chars": "ab"}])
        self.assertIn("keyspace_human", data)


class HumanKeyspaceTest(unittest.TestCase):
    def test_scale(self):
        self.assertEqual(mask.human_keyspace(999), "999")
        self.assertIn("тыс", mask.human_keyspace(1500))
        self.assertIn("млн", mask.human_keyspace(2_500_000))
        self.assertIn("млрд", mask.human_keyspace(3_000_000_000))


class CrackArgvTest(unittest.TestCase):
    """Маска должна попасть в hashcat аргументом, а не строкой в shell."""

    def test_positions_fragment_in_argv(self):
        from core.base import which

        if not which("hashcat"):
            self.skipTest("hashcat не установлен — проверка аргументов только на Linux")
        from core.crack import Crack
        from core.jobs import JobRegistry
        import tempfile

        spec = mask.build([P("upper"), P("digit"), P("fixed", "x")], 3, 3)
        with tempfile.TemporaryDirectory() as tmp:
            crack = Crack(JobRegistry(), Path(tmp))
            hash_file = Path(tmp) / "h.hc22000"
            hash_file.write_text("WPA*01*a*b*c*64*00**\n")
            captured = {}

            class FakeJob:
                def __init__(self, kind, argv, title=""):
                    captured["argv"] = argv
                    self.state = "running"
                    self.id = "x"

                def start(self):
                    return self

            import core.crack as crack_mod

            original = crack_mod.Job
            crack_mod.Job = FakeJob  # type: ignore[assignment]
            try:
                crack.start(hash_file, "positions", mask_spec=spec)
            finally:
                crack_mod.Job = original  # type: ignore[assignment]
            argv = captured["argv"]
            self.assertIn("-a", argv)
            self.assertIn(spec.mask, argv)
            self.assertIn("-1", argv)
            self.assertNotIn("shell", argv)


if __name__ == "__main__":
    unittest.main()