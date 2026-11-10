"""`promhis-license` — generate a signing keypair, or issue a license file.

Not part of the running app; a standalone offline tool run by whoever owns
the Enterprise signing key (the vendor), not by self-hosters. See
docs/licensing.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _keygen(args: argparse.Namespace) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_b64 = base64.b64encode(
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
    ).decode()
    public_b64 = base64.b64encode(
        public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    ).decode()

    Path(args.private_out).write_text(private_b64 + "\n")
    print(f"Private key written to {args.private_out} — keep this secret, never commit it, never ship it.")
    print(f"Public key (paste into src/promhis/licensing.py's PUBLIC_KEY_B64):\n{public_b64}")


def _issue(args: argparse.Namespace) -> None:
    private_b64 = Path(args.private_key).read_text().strip()
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))

    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(days=args.expires_days) if args.expires_days else None
    payload = {
        "customer": args.customer,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "features": args.features or [],
        "max_users": args.max_users,
    }
    payload_bytes = json.dumps(payload).encode()
    signature_bytes = private_key.sign(payload_bytes)

    envelope = {
        "payload": base64.b64encode(payload_bytes).decode(),
        "signature": base64.b64encode(signature_bytes).decode(),
    }
    Path(args.out).write_text(json.dumps(envelope, indent=2))
    expiry_note = f"expires {expires_at.date().isoformat()}" if expires_at else "no expiry"
    features_note = ", ".join(payload["features"]) or "none"
    print(f"License for {args.customer!r} ({expiry_note}, features: {features_note}) written to {args.out}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="promhis-license")
    sub = parser.add_subparsers(dest="command", required=True)

    keygen_parser = sub.add_parser("keygen", help="generate a new signing keypair")
    keygen_parser.add_argument("--private-out", default="license-private-key.txt", help="where to write the private key")
    keygen_parser.set_defaults(func=_keygen)

    issue_parser = sub.add_parser("issue", help="issue a signed license file")
    issue_parser.add_argument("--customer", required=True, help="customer name, embedded in the license")
    issue_parser.add_argument("--private-key", required=True, help="path to the private key file from `keygen`")
    issue_parser.add_argument("--expires-days", type=int, default=None, help="days until expiry (omit for a perpetual license)")
    issue_parser.add_argument(
        "--features", nargs="*", default=[],
        help="licensed feature flags, e.g. --features sso rbac service_tokens (see docs/licensing.md)",
    )
    issue_parser.add_argument("--max-users", type=int, default=None, help="optional admin-user cap for this license")
    issue_parser.add_argument("--out", default="promhis-license.json", help="where to write the license file")
    issue_parser.set_defaults(func=_issue)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
