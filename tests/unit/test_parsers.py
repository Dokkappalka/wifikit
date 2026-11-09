import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import convert, scan  # noqa: E402
from core.convert import replay_checked as _replay_checked  # noqa: E402
from tests.fixtures import samples  # noqa: E402


class IwScanTest(unittest.TestCase):
    def test_parses_two_aps(self):
        aps = scan.parse_iw_scan(samples.IW_SCAN)
        self.assertEqual(len(aps), 2)
        kh = aps[0]
        self.assertEqual(kh.bssid, "b4:fb:e4:11:22:33")
        self.assertEqual(kh.ssid, "Keenetic-1234")
        self.assertEqual(kh.channel, 6)
        self.assertEqual(kh.band, "2.4")
        self.assertTrue(kh.wpa2)
        self.assertTrue(kh.wpa3)
        self.assertEqual(kh.pmf, scan.PMF_REQUIRED)
        self.assertTrue(kh.wps)
        self.assertFalse(kh.deauth_ok)
        self.assertTrue(kh.crackable)

    def test_five_ghz_mapping(self):
        aps = scan.parse_iw_scan(samples.IW_SCAN)
        self.assertEqual(aps[1].channel, 36)
        self.assertEqual(aps[1].band, "5")
        self.assertEqual(aps[1].pmf, None)
        self.assertTrue(aps[1].deauth_ok)

    def test_hint_mentions_pmf(self):
        aps = scan.parse_iw_scan(samples.IW_SCAN)
        self.assertIn("PMF", aps[0].technique_hint())

    def test_garbage_is_ignored(self):
        self.assertEqual(scan.parse_iw_scan(""), [])
        self.assertEqual(scan.parse_iw_scan("BSS not-a-mac\n\tSSID: x\n"), [])


class AirodumpCsvTest(unittest.TestCase):
    def test_parses_ap_section_only(self):
        aps = scan.parse_airodump_csv(samples.AIRODUMP_CSV)
        self.assertEqual(len(aps), 2)
        self.assertTrue(aps[0].privacy)
        self.assertTrue(aps[0].wpa2)
        self.assertFalse(aps[1].privacy)
        self.assertTrue(aps[1].open)
        self.assertTrue(aps[1].crackable)


class OpenNetworkTest(unittest.TestCase):
    def test_open_network_hint(self):
        ap = scan.Ap(bssid="00:00:00:00:00:01")
        self.assertTrue(ap.open)
        self.assertIn("открытая", ap.technique_hint())


class ConvertTest(unittest.TestCase):
    def test_filter_by_bssid(self):
        lines = [samples.HC22000.strip(), "WPA*01*aa*deadbeef*998877665544*74657374***"]
        only = convert.filter_lines(lines, "b4:fb:e4:11:22:33")
        self.assertEqual(len(only), 1)
        self.assertTrue(only[0].startswith("WPA*02"))

    def test_best_pair_prefers_pmkid(self):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".hc22000", delete=False) as fh:
            fh.write(samples.HC22000)
            fh.write("WPA*01*aa*b4fbe4112233*aabbccddeeff*74657374***\n")
            path = Path(fh.name)
        self.assertTrue(convert.best_pair(path).startswith("WPA*01"))
        path.unlink()

    def test_count_after(self):
        self.assertEqual(convert._count_after(samples.HCXHASHTOOL_INFO, r"M2M3"), 1)
        self.assertEqual(convert._count_after("нет пар", r"M2M3"), 0)


class CookiesTest(unittest.TestCase):
    """Проверка, что replaycount не считается проверенным при наличии непроверенных."""

    def test_mixed_counts(self):
        text = "replaycount checked: 1\nreplaycount not checked: 3\n"
        self.assertFalse(_replay_checked(text))

    def test_all_checked(self):
        self.assertTrue(_replay_checked("replaycount checked: 2\nreplaycount not checked: 0\n"))

    def test_nothing_known(self):
        self.assertFalse(_replay_checked("replaycount checked: 0\nreplaycount not checked: 0\n"))


if __name__ == "__main__":
    unittest.main()
