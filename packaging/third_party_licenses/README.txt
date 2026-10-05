License texts for bundled components
====================================

These files are copied byte-for-byte from the upstream source or package
named below. THIRD_PARTY_NOTICES.txt (one folder up) names each component
and its license; QT_LGPL_COMPLIANCE.txt (also one folder up) covers Qt.

    qt\             LGPL-3.0.txt, GPL-3.0.txt
                    Qt 6.11.2, PySide6 6.11.2, shiboken6 6.11.2
                    (LGPL-3.0 incorporates the GPL-3.0 terms)
    python\         LICENSE.txt, LICENSES-incorporated-software.rst
                    CPython 3.12.10 (PSF terms; incorporated software,
                    including the OpenSSL used by Python's ssl/hashlib)
    openssl\        LICENSE.txt
                    OpenSSL 4.0.1, statically linked into the cryptography
                    Windows wheel (Apache-2.0)
    cryptography\   LICENSE, LICENSE.APACHE, LICENSE.BSD,
                    SBOM-openssl.json, SBOM-rust-crates.cyclonedx.json
                    cryptography 50.0.0 (Apache-2.0 OR BSD-3-Clause). The
                    two SBOM files are the wheel's own, listing the OpenSSL
                    version and the Rust crates (with licenses) built in.
    cffi\           LICENSE        cffi 2.1.1 (MIT-0)
    pycparser\      LICENSE        pycparser 3.0 (BSD-3-Clause)
    pyinstaller\    COPYING.txt    PyInstaller 6.22.2 (GPL-2.0-or-later with
                                   the bootloader exception)

Where each file came from
-------------------------

qt\LGPL-3.0.txt, qt\GPL-3.0.txt
    LICENSES\LGPL-3.0-only.txt and LICENSES\GPL-3.0-only.txt of the official
    Qt 6.11.2 source (qtbase-everywhere-src-6.11.2.tar.xz); identical to the
    same files in the official Qt for Python source
    (pyside-setup-everywhere-src-6.11.2.tar.xz).
python\LICENSE.txt, python\LICENSES-incorporated-software.rst
    LICENSE and Doc\license.rst of the official CPython 3.12.10 source
    (https://www.python.org/ftp/python/3.12.10/Python-3.12.10.tgz).
openssl\LICENSE.txt
    LICENSE.txt of the official openssl-4.0.1 source
    (https://github.com/openssl/openssl/releases/download/openssl-4.0.1/).
cryptography\*, cffi\LICENSE, pycparser\LICENSE, pyinstaller\COPYING.txt
    dist-info\licenses (and, for cryptography, dist-info\sboms) of the exact
    wheels pinned by the release lock (packaging\requirements-release.lock):
    cryptography-50.0.0-cp311-abi3-win_amd64, cffi-2.1.1-cp312-cp312-win_amd64,
    pycparser-3.0-py3-none-any, pyinstaller-6.22.2-py3-none-win_amd64.

Source archive hashes and the checks made are recorded in
docs/1.0-HARDENING-PLAN.md in the project repository.

The Spectral font license (SIL Open Font License 1.1) is inside the
application folder at assets\fonts\OFL.txt.
