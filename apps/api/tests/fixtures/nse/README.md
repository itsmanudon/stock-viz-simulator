# Synthetic NSE end-of-day files (A1.1)

These files use NSE's real headers (checked against real files on 25 Nov 2026)
with **invented rows and numbers**. A few real symbols and ISINs (RELIANCE
`INE002A01018`, TCS `INE467B01029`) appear so matching can be tested; every
price, volume, turnover and count is made up. Never commit real NSE data here.

- `BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv`: CM bhavcopy, UDiFF format.
  Zipped copies are built in the tests.
- `cm05JUL2024bhav.csv`: CM bhavcopy, legacy format, with the trailing empty
  column NSE often adds.
- `sec_bhavdata_full_01012025.csv`: delivery file, spaces after commas and
  `-` for no delivery.
