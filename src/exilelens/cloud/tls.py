"""TLS context for the optional ExileLens cloud client.

On Windows, ``ssl.create_default_context()`` loads both the ``ROOT`` *and* the ``CA`` (intermediate)
certificate stores as trust anchors. A machine whose CA store still holds an expired cross-signed root
(for example ISRG Root X1 cross-signed by the expired DST Root CA X3) then rejects perfectly valid
Let's Encrypt chains with "certificate has expired" — browsers and curl do not have this flaw. Found
during activation against a ``workers.dev`` hostname.

The cloud client therefore trusts only the Windows ``ROOT`` store (certificates explicitly trusted for
server authentication). That is a strict subset of the default trust, so it is never weaker; the server
still sends its own intermediates. Verification, hostname checking and TLS >= 1.2 stay mandatory.
If the store cannot be read, the standard default context is used (never an unverified one).
"""

from __future__ import annotations

import logging
import ssl
import sys
import urllib.request
from typing import Callable

logger = logging.getLogger(__name__)

SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"
MIN_EXPECTED_ROOTS = 10  # a Windows ROOT store with fewer anchors is not trustworthy as a sole source


def windows_root_store_context() -> ssl.SSLContext | None:
    if sys.platform != "win32":
        return None
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        loaded = 0
        for cert, encoding, trust in ssl.enum_certificates("ROOT"):
            if encoding != "x509_asn" or not (trust is True or SERVER_AUTH_OID in trust):
                continue
            try:
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
                loaded += 1
            except ssl.SSLError:
                continue  # an unparsable store entry is skipped, never fatal
        return context if loaded >= MIN_EXPECTED_ROOTS else None
    except Exception:  # noqa: BLE001 - fall back to the default context below
        logger.debug("cloud_tls_root_store_unavailable")
        return None


def client_context() -> ssl.SSLContext:
    return windows_root_store_context() or ssl.create_default_context()


_opener: urllib.request.OpenerDirector | None = None


def default_opener() -> Callable:
    """``urlopen``-compatible callable that verifies certificates with :func:`client_context`.

    Built lazily and cached; honours system proxy settings like ``urllib`` does.
    """
    global _opener
    if _opener is None:
        _opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=client_context()))
    return _opener.open
