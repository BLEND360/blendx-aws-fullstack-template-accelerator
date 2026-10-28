"""Choose the image and SPA deploy steps by comparing HEAD with the running image's commit."""

import argparse
import os
import re
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "infra"))

import boto3  # noqa: E402

from awsutil import DeployError, check_account, cli, load_config, run  # noqa: E402
from deploy_app import current_image_tag  # noqa: E402

_TAG = re.compile(r"^([0-9a-f]{40})-\d+$")


def classify(paths: list[str]) -> tuple[bool, bool]:
    """Return (build image, publish SPA); any path outside app code runs both."""
    areas = set()
    for path in paths:
        if path.startswith("backend/"):
            areas.add("backend")
        elif path.startswith("frontend/"):
            areas.add("frontend")
        else:
            return True, True
    return "backend" in areas, "frontend" in areas


def plan(tag: str | None, head: str, paths: list[str] | None, *, commit_exists: bool = True) -> tuple[bool, bool]:
    if not tag or not (match := _TAG.fullmatch(tag)) or not commit_exists:
        return True, True
    if match.group(1) == head:
        return False, False
    if paths is None:
        return True, True
    return classify(paths)


def emit(image: bool, spa: bool) -> None:
    print(f"Image step: {'run' if image else 'skip'}; SPA step: {'run' if spa else 'skip'}.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"image={'true' if image else 'false'}\nspa={'true' if spa else 'false'}\n")


@cli
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", required=True)
    args = parser.parse_args()
    c = load_config()
    c.sizing(args.env)
    session = boto3.Session(region_name=c.aws_region)
    check_account(c, session)
    tag = current_image_tag(c, session)
    head = run("git", "rev-parse", "HEAD", cwd=ROOT, capture=True).strip()

    match = _TAG.fullmatch(tag or "")
    commit_exists = False
    paths = None
    if match:
        commit_exists = match.group(1) == head
    if match and match.group(1) != head:
        try:
            run("git", "cat-file", "-e", f"{match.group(1)}^{{commit}}", cwd=ROOT)
            commit_exists = True
            paths = run("git", "diff", "--name-only", match.group(1), head, cwd=ROOT, capture=True).splitlines()
        except (DeployError, subprocess.CalledProcessError):
            paths = None
            commit_exists = False
    image, spa = plan(tag, head, paths, commit_exists=commit_exists)
    emit(image, spa)
    return 0


if __name__ == "__main__":
    sys.exit(main())
