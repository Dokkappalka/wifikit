"""Фикстуры: реальные срезы вывода внешних утилит.

Оставляем как есть, включая мусор — парсеры должны держать грязный ввод.
"""

IW_SCAN = """BSS b4:fb:e4:11:22:33(on wlan0) -- associated
\tfreq: 2437
\tbeacon interval: 100 TUs
\tcapability: ESS Privacy ShortSlotTime (0x0411)
\tsignal: -54.00 dBm
\tlast seen: 120 ms ago
\tSSID: Keenetic-1234
\tSupported rates: 1.0* 2.0* 5.5* 11.0* 18.0 24.0 36.0 48.0 54.0
\tRSN:\t * Version: 1
\t\t * Group cipher: CCMP
\t\t * Pairwise ciphers: CCMP
\t\t * Authentication suites: PSK SAE
\t\t * Capabilities: MFP-capable MFP-required (0x00cc)
\tWPS:\t * Version: 1.0
BSS 00:11:22:33:44:55(on wlan0)
\tfreq: 5180
\tsignal: -71.00 dBm
\tSSID: Office-5G
\tRSN:\t * Version: 1
\t\t * Authentication suites: PSK
"""

AIRODUMP_CSV = """BSSID, First time seen, Last time seen, channel, Speed, Privacy, Cipher, Authentication, Power, # beacons, # IV, LAN IP, ID-length, ESSID, Key
B4:FB:E4:11:22:33, 2026-11-09 10:00:00, 2026-11-09 10:01:00, 6, 130, WPA2, CCMP, PSK, -54, 120, 12, 0.0.0.0, 13, Keenetic-1234,
00:11:22:33:44:55, 2026-11-09 10:00:00, 2026-11-09 10:01:00, 36, 800, OPN, , , -71, 40, 0, 0.0.0.0, 9, Office-5G,

Station MAC, First time seen, Last time seen, Power, # packets, BSSID, Probed ESSIDs
AA:BB:CC:DD:EE:FF, 2026-11-09 10:00:10, 2026-11-09 10:01:00, -60, 30, B4:FB:E4:11:22:33, Keenetic-1234
"""

HASHCAT_STATUS = (
    '{"status":2,"device_id":1,"speed":[12345.0],"progress":[42.5],"recovered_salts":0,'
    '"recovered_hashes":0,"restore_point":0}\n'
)

HCXHASHTOOL_INFO = """networkname.......: Keenetic-1234
mac_ap............: b4fbe4112233
mac_sta...........: aabbccddeeff
EAPOL pairs.......: 1
EAPOL M1M2........: 1
EAPOL M2M3........: 1
EAPOL M3M4........: 1
EAPOL pairs (best): 2
replaycount checked: 1
replaycount not checked: 0
"""

HC22000 = (
    "WPA*02*8f1e2d3c4b5a69788796a5b4c3d2e1f0*8f1e2d3c4b5a69788796a5b4c3d2e1f0"
    "*b4fbe4112233*aabbccddeeff*4b65656e657469632d31323334*01000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "*0000000000000000000000000000000000000000000000000000000000000000*02\n"
)
