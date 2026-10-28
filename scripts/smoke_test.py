"""Check the public API health route, or a supplied URL, without credentials in URL mode."""

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

from awsutil import DeployError, check_account, cli, load_config, outputs  # noqa: E402
from definitions.app import APP_ID  # noqa: E402

DEFAULT_TIMEOUT = 300
DEFAULT_INTERVAL = 15
REQUEST_TIMEOUT = 10
BODY_LIMIT = 200


def is_healthy(status: int, content_type: str, body: bytes) -> bool:
    if status != 200 or "application/json" not in content_type.lower():
        return False
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("status") == "ok"


def request(url: str) -> tuple[int, str, bytes]:
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(BODY_LIMIT + 1)
    except HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read(BODY_LIMIT + 1)
    except (URLError, TimeoutError, OSError) as error:
        return 0, "", str(error).encode()[: BODY_LIMIT + 1]


def wait_for_health(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    interval: int = DEFAULT_INTERVAL,
) -> None:
    if timeout <= 0 or interval <= 0:
        raise ValueError("timeout and interval must be positive")

    deadline = time.monotonic() + timeout
    while True:
        status, content_type, body = request(url)
        if is_healthy(status, content_type, body):
            print(f"Smoke test passed: {url}")
            return

        remaining = deadline - time.monotonic()
        if status < 500 and status != 0:
            remaining = 0
        if remaining <= 0:
            excerpt = body[:BODY_LIMIT].decode("utf-8", errors="replace")
            shown_status = status if status else "network error"
            raise DeployError(f"Smoke test failed for {url}: HTTP {shown_status}; body: {excerpt}")
        time.sleep(min(interval, remaining))


def public_url(env: str) -> str:
    c = load_config()
    c.sizing(env)
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)
    app = outputs(session, c.app_stack)
    url = app.get(f"{APP_ID}PublicUrl")
    if not url:
        raise DeployError(f"The {c.app_stack} stack has no {APP_ID}PublicUrl output.")
    return url


@cli
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--env", help="read the public URL from the app stack in this environment")
    source.add_argument("--url", help="public app URL; useful for checks without AWS credentials")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"maximum wait in seconds (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help=f"retry interval in seconds (default {DEFAULT_INTERVAL})")
    args = parser.parse_args()

    base_url = args.url.rstrip("/") if args.url else public_url(args.env).rstrip("/")
    wait_for_health(f"{base_url}/api/health", timeout=args.timeout, interval=args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
