"""Unprivileged fixed-message encoder; no privileged imports or secret paths."""
import sys


def request() -> bytes:
    return b'{"operation":"M902_AUTH14_CATALOG15","version":1}'


def main():
    # Prints the protocol only. No installed privileged launcher in M90.2.
    sys.stdout.buffer.write(request() + b'\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
