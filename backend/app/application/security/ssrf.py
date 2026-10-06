"""SSRF guard for any component that will fetch a caller- or model-supplied URL.

NEXUS has no HTTP-fetching tool today -- the only outbound HTTP client is the
Nebius LLM provider, whose base URL comes from deployment configuration and not
from a request. So this module guards nothing that currently runs.

It exists anyway, for two reasons. First, "web research" is the obvious next tool
for a personal assistant and SSRF is the vulnerability it ships with by default.
Second, a guard written *after* the first fetch tool exists is a guard written
under time pressure. Having it here, tested, means the tool that lands wires to a
control rather than inventing one.

The design point that matters: **validating the URL string is not enough.** The
classic bypass is a hostname that resolves to a private address
(``localtest.me``, a rebinding domain, ``127.0.0.1.nip.io``), or a redirect
chain that starts public and ends at ``169.254.169.254``. So this guard does two
things a string check cannot:

* it resolves the hostname and checks *every* returned address, and
* it requires the caller to re-validate after redirects, because only the
  final hop matters.

``validate_url`` is safe to call against a string. ``validate_resolution`` needs
an async resolver and is what an actual fetcher must use, per redirect.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

#: Schemes a fetcher may use. Anything else -- ``file:``, ``gopher:``, ``dict:``,
#: ``ftp:`` -- is refused rather than normalised.
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

#: Ports commonly used to reach a service from inside a network. Refused because
#: a model-supplied URL has no legitimate reason to name them, and each maps to a
#: concrete exfiltration or control surface.
BLOCKED_PORTS: frozenset[int] = frozenset(
    {
        22,    # ssh
        23,    # telnet
        25,    # smtp
        445,   # smb
        1433,  # mssql
        2375,  # docker api (unencrypted)
        2376,  # docker api (tls, still the same socket)
        3306,  # mysql
        3389,  # rdp
        5432,  # postgres
        5672,  # amqp
        6379,  # redis
        8080,  # common local admin ui
        8443,  # common local admin ui (tls)
        9200,  # elasticsearch
        11211, # memcached
        27017, # mongodb
    }
)

#: Exact hostnames that resolve to something local regardless of DNS.
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

#: Suffixes that resolve inside a cloud provider's control plane.
BLOCKED_SUFFIXES: tuple[str, ...] = (
    ".internal",
    ".local",
    ".localdomain",
    ".cluster.local",
)


class SsrfBlocked(ValueError):
    """Raised when a URL may not be fetched. The reason is safe to log."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ValidatedTarget:
    """A URL that passed every check, with the addresses it resolved to."""

    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]

    @property
    def is_loopback(self) -> bool:  # pragma: no cover - convenience
        return any(ipaddress.ip_address(a).is_loopback for a in self.addresses)


def validate_url(url: str, *, allow_private: bool = False) -> ValidatedTarget:
    """Structural checks only. Cheap, and it catches most bad input.

    ``allow_private`` exists so the function is testable against a local server.
    It has no production caller and must not gain one: the whole point is that
    the default refuses private space.
    """
    if not url or not isinstance(url, str):
        raise SsrfBlocked("url must be a non-empty string")
    if len(url) > 2_048:
        raise SsrfBlocked("url exceeds the maximum length")

    parts = urlsplit(url.strip())

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        # Refused rather than rewritten. "Fixing" an unknown scheme by mapping it
        # to http is how ``file:///etc/passwd`` becomes an HTTP request for the
        # wrong thing instead of an error.
        raise SsrfBlocked(f"scheme not allowed: {parts.scheme or 'none'}")

    host = (parts.hostname or "").strip().lower()
    if not host:
        raise SsrfBlocked("url has no host")
    if host in BLOCKED_HOSTNAMES:
        raise SsrfBlocked(f"host is not fetchable: {host}")
    if any(host.endswith(suffix) for suffix in BLOCKED_SUFFIXES):
        raise SsrfBlocked(f"host resolves inside the local network: {host}")

    try:
        port = parts.port
    except ValueError as error:
        raise SsrfBlocked("url has an invalid port") from error
    port = port or (443 if parts.scheme.lower() == "https" else 80)
    if port in BLOCKED_PORTS:
        raise SsrfBlocked(f"port is not fetchable: {port}")
    if not 1 <= port <= 65535:
        raise SsrfBlocked("port is out of range")

    # A credential in a URL is either a mistake or an attempt to make the request
    # look authenticated. Either way the fetcher should not carry it.
    if parts.username or parts.password:
        raise SsrfBlocked("url must not embed credentials")

    if not allow_private:
        # A literal IP can be judged now, with no DNS involved. Still not
        # sufficient on its own -- see validate_resolution.
        literal = _as_ip(host)
        if literal is not None and not _is_public(literal):
            raise SsrfBlocked(f"address is not publicly routable: {host}")

    return ValidatedTarget(
        url=url.strip(),
        scheme=parts.scheme.lower(),
        host=host,
        port=port,
        addresses=(),
    )


async def validate_resolution(url: str, *, resolver=None) -> ValidatedTarget:
    """Structural checks, then resolve and check every returned address.

    This is the check that actually prevents SSRF. ``resolver`` defaults to
    ``getaddrinfo`` and exists so tests can pin resolution without a live DNS.

    Call this again on every redirect hop. A 302 to ``http://169.254.169.254/``
    passes any check performed on the original URL.
    """
    target = validate_url(url)
    resolve = resolver or _default_resolver
    try:
        addresses = await resolve(target.host, target.port)
    except SsrfBlocked:
        raise
    except OSError as error:
        raise SsrfBlocked("host could not be resolved") from error

    if not addresses:
        raise SsrfBlocked("host resolved to no addresses")

    for address in addresses:
        parsed = _as_ip(address)
        if parsed is None:
            # A resolver that returns something unparseable has told us nothing
            # we can judge. Refusing is the only safe reading.
            raise SsrfBlocked(f"host resolved to an unparseable address: {address}")
        if not _is_public(parsed):
            raise SsrfBlocked(
                f"host resolves to a non-public address: {parsed}"
            )

    return ValidatedTarget(
        url=target.url,
        scheme=target.scheme,
        host=target.host,
        port=target.port,
        addresses=tuple(addresses),
    )


def is_blocked_address(address: str) -> bool:
    """True when a bare address is outside public space."""
    parsed = _as_ip(address)
    return parsed is None or not _is_public(parsed)


def _is_public(address) -> bool:  # noqa: ANN001 - ipaddress.IPv4Address | IPv6Address
    """Public means routable on the public internet, and nothing else.

    ``is_private`` on the stdlib objects covers loopback, link-local, private
    ranges and reserved space, but it treats some documentation and benchmark
    ranges inconsistently across versions. The explicit list is what this guard
    means by "public", and it includes the cloud metadata address explicitly so
    that a future stdlib change cannot quietly widen reach.
    """
    if address.is_loopback:
        return False
    if address.is_link_local:
        return False
    if address.is_private:
        return False
    if address.is_multicast:
        return False
    if address.is_reserved:
        return False
    if address.is_unspecified:
        return False
    if address.version == 4:
        octets = address.packed
        # 100.64.0.0/10 carrier-grade NAT: not private per the stdlib, not
        # reachable from the internet either.
        if octets[0] == 100 and 64 <= octets[1] <= 127:
            return False
        # 169.254.0.0/16 is link-local and already covered, but the cloud
        # metadata address is called out because reaching it is the single most
        # valuable SSRF outcome.
        if octets[0] == 169 and octets[1] == 254:
            return False
        # 0.0.0.0/8 "this network", 240.0.0.0/4 reserved.
        if octets[0] == 0 or octets[0] >= 240:
            return False
    else:
        # IPv6 unique-local fc00::/7. The stdlib flags these, but an explicit
        # check keeps the intent readable and survives a stdlib change.
        if address.packed[0] & 0xFE == 0xFC:
            return False
        # IPv4-mapped IPv6 (::ffff:127.0.0.1) must not slip through by looking
        # like IPv6. Unwrap and re-judge as IPv4.
        if address.version == 6 and address.ipv4_mapped is not None:
            return _is_public(address.ipv4_mapped)
        if address.packed[0] == 0xFE and address.packed[1] & 0xC0 == 0x80:
            return False  # link-local fe80::/10
    return True


def _as_ip(value: str):
    """Parse a bare IP, tolerating the IPv6 bracket form urlsplit leaves behind."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


async def _default_resolver(host: str, port: int) -> tuple[str, ...]:
    loop = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return tuple({info[4][0] for info in loop})


__all__ = (
    "ALLOWED_SCHEMES",
    "BLOCKED_HOSTNAMES",
    "BLOCKED_PORTS",
    "SsrfBlocked",
    "ValidatedTarget",
    "is_blocked_address",
    "validate_resolution",
    "validate_url",
)