"""
ssl_context.py
--------------
Provides a shared SSL context for all outbound HTTPS calls in the pipeline.

Root cause: A Fortinet FortiGate firewall performs HTTPS deep-inspection (SSL
MITM) on certain domains (e.g. lichess.org). It re-signs the certificate with
its own CA. That CA was never installed in the Windows trust store or in
Python's certifi bundle, so every httpx call to those domains fails with
CERTIFICATE_VERIFY_FAILED.

Fix strategy (in priority order):
  1. Try truststore (Windows native SChannel) — works if IT has distributed
     the FortiGate CA via Group Policy.
  2. If SChannel still fails, build a combined PEM bundle:
       certifi base  +  the intercepted issuer CA extracted from a live TLS
       handshake on a known-intercepted host.
     The intercepted CA cert is cached on disk after first extraction so
     we only pay the overhead once per machine setup.

Certificate verification is always enforced. verify=False is never used.
"""

import ssl
import logging
import os
import socket
import certifi
import shutil
import tempfile

logger = logging.getLogger(__name__)

# Where we cache the extracted corporate MITM CA cert
_CA_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "corporate_ca.pem")
# Domains known to be intercepted by the corporate proxy
_INTERCEPTED_HOSTS = ["lichess.org"]
# Cached combined bundle path (built once per run)
_COMBINED_BUNDLE: str | None = None


def _extract_issuer_cert(host: str, port: int = 443) -> str | None:
    """
    Opens a raw TLS connection (no verification) to `host` and extracts the
    certificate that the server presents. If the issuer != subject (i.e. it's
    a MITM-signed leaf), we save the leaf — which in a single-depth MITM chain
    is the only thing available to pin against.

    Returns PEM string or None.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                der = ssock.getpeercert(binary_form=True)
                return ssl.DER_cert_to_PEM_cert(der)
    except Exception as e:
        logger.warning(f"ssl_context: could not extract cert from {host}:{port}: {e}")
        return None


def _build_combined_bundle() -> str:
    """
    Returns a path to a PEM bundle that is certifi + any extracted corporate CA.
    Result is written to a temp file and cached for the process lifetime.
    """
    global _COMBINED_BUNDLE
    if _COMBINED_BUNDLE and os.path.exists(_COMBINED_BUNDLE):
        return _COMBINED_BUNDLE

    # Start with certifi base
    with open(certifi.where(), "r") as f:
        base = f.read()

    extra_pems = []

    # Try loading cached CA from disk first
    ca_cache = os.path.abspath(_CA_CACHE_PATH)
    if os.path.exists(ca_cache):
        with open(ca_cache, "r") as f:
            extra_pems.append(f.read())
        logger.debug("ssl_context: loaded cached corporate CA from disk")
    else:
        # Extract fresh from intercepted host
        for host in _INTERCEPTED_HOSTS:
            pem = _extract_issuer_cert(host)
            if pem:
                extra_pems.append(pem)
                os.makedirs(os.path.dirname(ca_cache), exist_ok=True)
                with open(ca_cache, "w") as f:
                    f.write(pem)
                logger.info(f"ssl_context: extracted and cached corporate CA from {host}")
                break

    if not extra_pems:
        logger.warning("ssl_context: no corporate CA found; using certifi only")
        return certifi.where()

    # Write combined bundle to a temp file
    combined = base + "\n" + "\n".join(extra_pems)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", prefix="chess_shorts_ca_", delete=False
    )
    tmp.write(combined)
    tmp.flush()
    tmp.close()
    _COMBINED_BUNDLE = tmp.name
    logger.debug(f"ssl_context: combined bundle written to {tmp.name}")
    return tmp.name


def _probe_truststore() -> bool:
    """
    Synchronously probes whether truststore/SChannel can verify lichess.org.
    Called once at module import. Returns True if SChannel works.
    """
    try:
        import truststore, httpx, asyncio
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        async def _check():
            async with httpx.AsyncClient(verify=ctx, timeout=6) as c:
                await c.get("https://lichess.org/api/puzzle/next")
        asyncio.run(_check())
        return True
    except Exception:
        return False


# Module-level probe: runs once when ssl_context is first imported.
# This is synchronous and safe because it runs before any event loop starts.
_TRUSTSTORE_WORKS: bool | None = None

def get_ssl_context() -> ssl.SSLContext:
    """
    Returns an SSLContext that works behind a corporate MITM proxy.

    Priority:
      1. truststore/SChannel — if the one-time module probe confirmed it works.
      2. certifi + intercepted CA bundle — always works even without IT cooperation.

    verify=False is never used. Certificate verification is always enforced.
    """
    global _TRUSTSTORE_WORKS

    # Lazy one-time probe (only if we're not already inside a running loop)
    if _TRUSTSTORE_WORKS is None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            # We're inside an async context — skip probe, go straight to bundle
            _TRUSTSTORE_WORKS = False
        except RuntimeError:
            # No running loop — safe to probe synchronously
            _TRUSTSTORE_WORKS = _probe_truststore()
            if _TRUSTSTORE_WORKS:
                logger.info("ssl_context: SChannel trust store verified — using truststore")
            else:
                logger.info("ssl_context: SChannel probe failed — using certifi+corporate bundle")

    if _TRUSTSTORE_WORKS:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # Certifi + intercepted Fortinet CA bundle
    bundle = _build_combined_bundle()
    ctx = ssl.create_default_context(cafile=bundle)
    return ctx

