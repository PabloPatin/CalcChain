# Third-Party Notices for Bundled SVN CLI

This directory contains a reduced Windows command-line SVN runtime bundled for
the CalcChain SVN plugin demo.

Included executable:

- `svn.exe` - Apache Subversion command-line client
  - Version: `1.14.5 (r1922182)`
  - Build date reported by the binary: `Nov 30 2024`
  - Copyright reported by the binary: The Apache Software Foundation

Included runtime libraries:

- `libsvn_tsvn.dll`
- `libapr_tsvn.dll`
- `libaprutil_tsvn.dll`
- `intl3_tsvn.dll`
- `libsasl.dll`
- `sasl*.dll`

Source of bundled files:

- Copied from a TortoiseSVN Windows installation directory.
- These files are bundled only to allow the demo plugin to run without a
  separately installed system SVN command-line client.
- The bundled binaries have not been modified by CalcChain.

Project and source links:

- Apache Subversion: https://subversion.apache.org/
- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0
- TortoiseSVN: https://tortoisesvn.net/
- TortoiseSVN source access: https://tortoisesvn.net/docs/release/TortoiseSVN_en/tsvn-preface-source.html
- TortoiseSVN SourceForge source browser: https://sourceforge.net/p/tortoisesvn/code/HEAD/tree/

Before a public CalcChain release, replace this notice with a complete
third-party notice bundle copied from the exact TortoiseSVN/Subversion
distribution used for the bundled binaries, including all required license
texts and copyright notices.
