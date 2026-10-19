# Public font notice evidence

These are unchanged public third-party license texts, independently downloaded
from the Google Fonts repository at the full commits below. They were not copied
from private ejm-ui source. They provide the external byte evidence for the
existing `UI_FONT_HASHES` allowlist in `scripts/standards.py`.

| Fixture | Public upstream source | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| [Manrope-OFL.txt](Manrope-OFL.txt) | [google/fonts, `ofl/manrope/OFL.txt` at `16c2976c68c3137c09c69c8e9d3deada699d157e`](https://github.com/google/fonts/blob/16c2976c68c3137c09c69c8e9d3deada699d157e/ofl/manrope/OFL.txt) | 4,387 | `58172e0c0fac2cda8a37b348164bb55e44b0e69051e557e92b1d3f6910141f7b` |
| [IBMPlexMono-OFL.txt](IBMPlexMono-OFL.txt) | [google/fonts, `ofl/ibmplexmono/OFL.txt` at `465b90c97b4de569e0b546bb2536900194cf7187`](https://github.com/google/fonts/blob/465b90c97b4de569e0b546bb2536900194cf7187/ofl/ibmplexmono/OFL.txt) | 4,456 | `7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da` |

The Manrope text retains its project authors' copyright. IBM Plex Mono retains
IBM's copyright and reserved font name. Both retain the full SIL Open Font
License 1.1. Preserve their original bytes, including trailing spaces and IBM's
CRLF line endings. The local attributes disable text conversion and whitespace
warnings only for these original notices; the unpatched validator test protects
their exact bytes.

To review or replace a fixture, fetch its path from the stated public commit,
compare its raw SHA-256 with the allowlist, and review the complete license text
and copyright notice. A changed upstream license does not authorize changing
the allowlist or an owner's bundled notices without review.

These fixtures establish public notice provenance and validator behavior. They
do not establish that any private UI checkout has matching manifests, fonts,
notices or gate implementations.
