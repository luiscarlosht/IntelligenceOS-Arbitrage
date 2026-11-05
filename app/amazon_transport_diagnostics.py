"""Message-free transport classification and zero-dispatch local socket checks."""
import errno
import socket
import ssl
from urllib.error import URLError


def classify_transport(error: BaseException, stage: str) -> dict:
    """Unwrap urllib's reason only; never stringify exceptions, URLs or arguments."""
    inner = error
    for _ in range(4):
        if isinstance(inner, URLError) and isinstance(inner.reason, BaseException):
            inner = inner.reason
        else:
            break
    number = getattr(inner, 'errno', None)
    number = number if type(number) is int and -65536 <= number <= 65536 else None
    if isinstance(inner, ssl.SSLCertVerificationError):
        category = 'tls_certificate_verification'
    elif isinstance(inner, ssl.SSLError):
        category = 'tls_error'
    elif isinstance(inner, socket.gaierror):
        category = 'dns_resolution'
    elif isinstance(inner, PermissionError) or number in (errno.EPERM, errno.EACCES):
        category = 'network_permission_denied'
    elif isinstance(inner, TimeoutError):
        category = 'timeout'
    elif number == errno.ECONNREFUSED:
        category = 'connection_refused'
    elif number in (errno.ENETUNREACH, errno.EHOSTUNREACH):
        category = 'network_unreachable'
    elif isinstance(inner, OSError):
        category = 'os_transport_error'
    else:
        category = 'unclassified_transport_error'
    allowed = {'PermissionError', 'TimeoutError', 'gaierror', 'SSLError', 'SSLCertVerificationError',
               'ConnectionRefusedError', 'ConnectionResetError', 'OSError', 'URLError'}
    return dict(category=category, stage=stage if stage in ('tls_context', 'opener', 'open', 'read') else 'other',
                exception=type(inner).__name__ if type(inner).__name__ in allowed else 'OTHER', errno=number)


def local_socket_readiness() -> dict:
    """Create and close unconnected sockets. No DNS, connect, send or HTTP calls."""
    results = {}
    for name, family in (('ipv4', socket.AF_INET), ('ipv6', socket.AF_INET6)):
        try:
            with socket.socket(family, socket.SOCK_STREAM):
                pass
            results[name] = dict(status='UNCONNECTED_SOCKET_CREATED', remote_connectivity='UNTESTED')
        except OSError as error:
            results[name] = dict(status='UNAVAILABLE', **classify_transport(error, 'open'))
    return dict(socket_checks=results, amazon_http_attempts=0,
                local_socket_ready=any(r['status'] == 'UNCONNECTED_SOCKET_CREATED' for r in results.values()),
                remote_connectivity='UNTESTED')
