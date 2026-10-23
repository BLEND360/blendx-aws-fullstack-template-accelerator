"""scripts/deploy_app.py with every AWS call, subprocess and cdk invocation replaced by a recorder."""

import base64
import hashlib
import importlib.util
import tomllib
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import config
from tests.test_config import VALID, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PREFIX = "arn:aws:bedrock-agentcore:eu-west-1:111122223333"
HARNESS, MEMORY = f"{PREFIX}:harness/assistant-AbC123", f"{PREFIX}:memory/assistant_mem-XyZ789"
IMAGE_ID = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
TAG = "0123456789ab"
CLOUDFRONT = "https://d111111abcdef8.cloudfront.net"
SUBNETS = '{ eu-west-1a = "subnet-0a1b2c3d", eu-west-1b = "subnet-4e5f6a7b" }'


def missing(code: str, message: str = "not found") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Op")


class World:
    """What AWS holds, and a record of everything the script did to it."""

    def __init__(self, c: config.Config, *, stacks=None, repo=True, tag_in_ecr=False, prefix_list="pl-4fa04526"):
        self.c = c
        self.account = c.aws_account
        self.stacks = {c.roles_stack, c.auth_stack, c.data_stack} if stacks is None else set(stacks)
        self.repo, self.tag_in_ecr, self.prefix_list = repo, tag_in_ecr, prefix_list
        self.objects: dict[str, str] = {}  # the SPA bucket: key -> MD5 etag
        self.object_headers: dict[str, dict] = {}
        self.live_callbacks: list[str] = []  # what Cognito itself accepts
        self.toml_path: Path | None = None
        self.invalidation_error: ClientError | None = None
        self.auth_deploy_error: Exception | None = None
        self.events: list[tuple] = []  # ("cdk", ...), ("run", ...), ("invalidate", ...), ("put", key), ("delete", key)

    # --- boto3 ---
    def client(self, name):
        return getattr(self, f"_{name.replace('-', '_')}")()

    def _sts(self):
        world = self

        class Sts:
            def get_caller_identity(self):
                return {"Account": world.account}

        return Sts()

    def _cloudformation(self):
        world, c = self, self.c

        class Cfn:
            def describe_stacks(self, StackName):
                if StackName not in world.stacks:
                    raise missing("ValidationError", f"Stack with id {StackName} does not exist")
                outputs = {
                    c.auth_stack: {"UserPoolId": "eu-west-1_AbCdEf", "AppClientId": "1example23456789", "Domain": "x.auth.eu-west-1.amazoncognito.com"},
                    c.app_stack: {"AppPublicUrl": CLOUDFRONT, "AppDistributionId": "E123ABC", "AppSpaBucket": c.web_bucket},
                }.get(StackName, {})
                return {"Stacks": [{"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in outputs.items()]}]}

        return Cfn()

    def _ec2(self):
        world = self

        class Ec2:
            def describe_managed_prefix_lists(self, Filters):
                assert Filters == [{"Name": "prefix-list-name", "Values": ["com.amazonaws.global.cloudfront.origin-facing"]}]
                return {"PrefixLists": [{"PrefixListId": world.prefix_list}] if world.prefix_list else []}

        return Ec2()

    def _ecr(self):
        world = self

        class Ecr:
            def describe_repositories(self, repositoryNames):
                if not world.repo:
                    raise missing("RepositoryNotFoundException")
                return {"repositories": [{}]}

            def describe_images(self, repositoryName, imageIds):
                if not world.tag_in_ecr:
                    raise missing("ImageNotFoundException")
                return {"imageDetails": [{}]}

            def get_authorization_token(self):
                token = base64.b64encode(b"AWS:s3cr3t-password").decode()
                return {"authorizationData": [{"authorizationToken": token}]}

        return Ecr()

    def _cloudfront(self):
        world = self

        class Cloudfront:
            def create_invalidation(self, DistributionId, InvalidationBatch):
                if world.invalidation_error:
                    raise world.invalidation_error
                world.events.append(("invalidate", DistributionId, tuple(InvalidationBatch["Paths"]["Items"])))

        return Cloudfront()

    def _s3(self):
        world = self

        class Paginator:
            def paginate(self, Bucket):
                return [{"Contents": [{"Key": k, "ETag": f'"{v}"'} for k, v in world.objects.items()]}]

        class S3:
            def get_paginator(self, name):
                assert name == "list_objects_v2"
                return Paginator()

            def put_object(self, Bucket, Key, Body, ContentType, CacheControl):
                world.events.append(("put", Key))
                world.objects[Key] = hashlib.md5(Body).hexdigest()
                world.object_headers[Key] = {"ContentType": ContentType, "CacheControl": CacheControl}

            def delete_object(self, Bucket, Key):
                world.events.append(("delete", Key))
                world.objects.pop(Key, None)

        return S3()

    def _cognito_idp(self):
        world = self

        class Cognito:
            def describe_user_pool_client(self, UserPoolId, ClientId):
                return {"UserPoolClient": {"CallbackURLs": list(world.live_callbacks)}}

        return Cognito()

    # --- scripts/deploy_app.py's seams ---
    def cdk(self, *args):
        self.events.append(("cdk", *args))
        if args[0] == "deploy" and self.c.auth_stack in args:
            if self.auth_deploy_error:
                raise self.auth_deploy_error
            self.live_callbacks = list(tomllib.loads(self.toml_path.read_text(encoding="utf-8")).get("auth", {}).get("callback_urls", []))
        if args[0] == "deploy" and self.c.app_stack in args:
            self.stacks |= {self.c.app_stack}
            self.repo = True  # the app stack creates the repository

    def run(self, *cmd, cwd=None, env=None, capture=False, input=None):
        self.events.append(("run", cmd, env, input))
        if cmd[:2] == ("docker", "build"):
            return IMAGE_ID + "\n"
        return ""

    # --- queries over the record ---
    def kinds(self):
        return [e[0] if e[0] in ("cdk", "network_check") else (e[0], e[1][:2]) for e in self.events]

    def cdk_calls(self):
        return [e[1:] for e in self.events if e[0] == "cdk"]

    def commands(self, *prefix):
        return [e[1] for e in self.events if e[0] == "run" and e[1][: len(prefix)] == prefix]


@pytest.fixture
def deploy_app(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("deploy_app", SCRIPTS / "deploy_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def arrange(deploy_app, monkeypatch, tmp_path, *, toml: str = VALID, **world_options):
    path = write(tmp_path, toml)
    c = config.load(path)
    world = World(c, **world_options)
    world.toml_path = path
    monkeypatch.setattr(deploy_app, "PROJECT_TOML", path)
    monkeypatch.setattr(deploy_app.shutil, "which", lambda tool: f"/usr/bin/{tool}")
    monkeypatch.setattr(deploy_app.boto3, "Session", lambda **_: type("S", (), {"client": lambda self, name: world.client(name)})())
    monkeypatch.setattr(deploy_app, "cdk", world.cdk)
    monkeypatch.setattr(deploy_app, "run", world.run)
    monkeypatch.setattr(deploy_app.harness_resolve, "resolve", lambda *_: (HARNESS, MEMORY))
    monkeypatch.setattr(deploy_app.network_check, "check", lambda *_: world.events.append(("network_check",)))
    monkeypatch.setattr(deploy_app, "WEB", tmp_path / "web")
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    # "zz/late.js" sorts after "index.html": only the explicit rule, not alphabetical order, puts the page last.
    build(tmp_path / "web", {"index.html": "<html>v1</html>", "assets/app-1a2b3c.js": "console.log(1)", "assets/app-1a2b3c.css": "body{}", "zz/late.js": "1"})
    return c, world, path


def build(web: Path, files: dict[str, str]) -> None:
    """What `npm run build` leaves in dist/ (the run is faked, so the test lays the output out)."""
    dist = web / "dist"
    if dist.exists():
        for old in sorted(dist.rglob("*"), reverse=True):
            old.unlink() if old.is_file() else old.rmdir()
    for name, text in files.items():
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_text(text, encoding="utf-8")


def go(deploy_app, *args):
    return deploy_app.main(["--env", "dev", *args])


# ------------------------------------------------------------------ 5.4: validations and inputs


def test_the_environment_is_a_required_argument(deploy_app):
    with pytest.raises(SystemExit) as stop:
        deploy_app.main([])
    assert stop.value.code == 2


def test_an_unknown_environment_stops_before_anything_is_created_and_lists_the_valid_ones(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    assert deploy_app.main(["--env", "qa"]) == 1
    error = capsys.readouterr().err
    assert "'qa'" in error and "valid: dev" in error
    assert world.events == []


def test_credentials_for_another_account_stop_the_script_with_the_usual_message(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    world.account = "999999999999"
    assert go(deploy_app) == 1
    error = capsys.readouterr().err
    assert "999999999999" in error and c.aws_account in error and "project.toml" in error
    assert world.cdk_calls() == []


@pytest.mark.parametrize("which,script", [("roles_stack", "bootstrap.py"), ("data_stack", "deploy_data.py"), ("auth_stack", "deploy_auth.py")])
def test_a_missing_prerequisite_stack_is_named_with_the_script_that_deploys_it(deploy_app, monkeypatch, tmp_path, capsys, which, script):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    world.stacks.discard(getattr(c, which))
    assert go(deploy_app) == 1
    error = capsys.readouterr().err
    assert getattr(c, which) in error and script in error
    assert world.cdk_calls() == []


def test_an_unresolvable_harness_stops_before_anything_is_created(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)

    def fail(*_):
        raise deploy_app.harness_resolve.HarnessResolveError("the harness has no memory")

    monkeypatch.setattr(deploy_app.harness_resolve, "resolve", fail)
    assert go(deploy_app) == 1
    assert "the harness has no memory" in capsys.readouterr().err
    assert world.cdk_calls() == []


def test_a_vpc_that_cannot_host_the_app_stops_before_anything_is_created(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, toml=VALID + f'\n[network]\nvpc_id = "vpc-0123abcd"\nprivate_subnets = {SUBNETS}\n')

    def fail(*_):
        raise deploy_app.network_check.NetworkCheckError("Subnet subnet-0a1b2c3d has no route to the Internet")

    monkeypatch.setattr(deploy_app.network_check, "check", fail)
    assert go(deploy_app) == 1
    assert "subnet-0a1b2c3d" in capsys.readouterr().err
    assert world.cdk_calls() == []


def test_the_vpc_is_checked_before_the_first_deployment(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    assert world.events[0] == ("network_check",)


@pytest.mark.parametrize("tool", ["docker", "npm"])
def test_a_missing_local_tool_stops_the_script_before_anything_is_created(deploy_app, monkeypatch, tmp_path, capsys, tool):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    monkeypatch.setattr(deploy_app.shutil, "which", lambda name: None if name == tool else f"/usr/bin/{name}")
    assert go(deploy_app) == 1
    assert tool in capsys.readouterr().err
    assert world.cdk_calls() == []


def test_a_missing_cloudfront_prefix_list_stops_the_script(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, prefix_list="")
    assert go(deploy_app) == 1
    assert "origin-facing" in capsys.readouterr().err
    assert world.cdk_calls() == []


# ------------------------------------------------------------------ 5.5: infrastructure and image


def context(call: tuple) -> dict:
    pairs = [call[i + 1] for i, a in enumerate(call) if a == "-c"]
    return dict(p.split("=", 1) for p in pairs)


def test_the_first_run_deploys_without_an_image_then_pushes_one_then_deploys_with_it(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, repo=False)
    assert go(deploy_app) == 0
    steps = [
        "deploy app" if e[0] == "cdk" else e[1][:2]
        for e in world.events
        if (e[0] == "cdk" and c.app_stack in e) or (e[0] == "run" and e[1][:2] in (("docker", "build"), ("docker", "push")))
    ]
    assert steps == ["deploy app", ("docker", "build"), ("docker", "push"), "deploy app"]
    first, second = [c_ for c_ in world.cdk_calls() if c_[0] == "deploy" and c.app_stack in c_]
    assert "image_tag" not in context(first) and context(second)["image_tag"] == TAG


def test_when_the_repository_exists_the_image_goes_first_and_there_is_one_deployment(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, repo=True)
    assert go(deploy_app) == 0
    deploys = [c_ for c_ in world.cdk_calls() if c.app_stack in c_]
    assert len(deploys) == 1 and context(deploys[0])["image_tag"] == TAG
    assert world.kinds().index(("run", ("docker", "push"))) < world.kinds().index("cdk")


def test_the_image_is_built_for_x86_and_tagged_with_the_start_of_its_id(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    (build,) = world.commands("docker", "build")
    assert "--platform" in build and build[build.index("--platform") + 1] == "linux/amd64"
    uri = f"{c.aws_account}.dkr.ecr.{c.aws_region}.amazonaws.com/{c.ecr_repository}"
    assert ("docker", "tag", IMAGE_ID, f"{uri}:{TAG}") in world.commands("docker", "tag")
    assert (f"{uri}:{TAG}") in world.commands("docker", "push")[0]


def test_a_tag_already_in_the_repository_is_not_pushed_again(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, tag_in_ecr=True)
    go(deploy_app)
    assert world.commands("docker", "push") == []
    assert context([c_ for c_ in world.cdk_calls() if c.app_stack in c_][0])["image_tag"] == TAG


def test_the_registry_password_goes_through_stdin_never_the_command_line(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    (login,) = [e for e in world.events if e[0] == "run" and e[1][:2] == ("docker", "login")]
    assert login[3] == "s3cr3t-password" and "s3cr3t-password" not in " ".join(login[1])


def test_the_deployment_carries_what_was_resolved_and_names_both_stacks(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    (call,) = [c_ for c_ in world.cdk_calls() if c.app_stack in c_]
    assert {c.network_stack, c.app_stack} <= set(call) and "--exclusively" in call
    assert context(call) == {
        "env": "dev", "harness_arn": HARNESS, "memory_arn": MEMORY, "user_pool_id": "eu-west-1_AbCdEf",
        "app_client_id": "1example23456789", "cloudfront_prefix_list": "pl-4fa04526", "image_tag": TAG,
    }


def test_with_an_existing_vpc_no_network_stack_is_deployed(deploy_app, monkeypatch, tmp_path):
    toml = VALID + f'\n[network]\nvpc_id = "vpc-0123abcd"\nprivate_subnets = {SUBNETS}\n'
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path, toml=toml)
    go(deploy_app)
    (call,) = [c_ for c_ in world.cdk_calls() if c.app_stack in c_]
    assert c.network_stack not in call


# ------------------------------------------------------------------ 5.6: SPA, return address and closing


def test_the_spa_is_built_with_the_sign_in_values_from_the_auth_stack(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    (build,) = [e for e in world.events if e[0] == "run" and e[1] == ("npm", "run", "build")]
    assert build[2] == {
        "VITE_COGNITO_REGION": c.aws_region,
        "VITE_COGNITO_USER_POOL_ID": "eu-west-1_AbCdEf",
        "VITE_COGNITO_APP_CLIENT_ID": "1example23456789",
        "VITE_COGNITO_DOMAIN": "x.auth.eu-west-1.amazoncognito.com",
    }


def test_dependencies_are_installed_only_when_missing(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    assert world.commands("npm", "ci") == []
    (tmp_path / "web" / "node_modules").rmdir()
    go(deploy_app)
    assert len(world.commands("npm", "ci")) == 1


def test_the_bucket_holds_the_built_site_with_the_right_type_and_cache_rules(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    assert set(world.objects) == {"index.html", "assets/app-1a2b3c.js", "assets/app-1a2b3c.css", "zz/late.js"}
    assert world.object_headers["index.html"] == {"ContentType": "text/html", "CacheControl": "no-cache"}
    bundle = world.object_headers["assets/app-1a2b3c.js"]
    assert "immutable" in bundle["CacheControl"] and "javascript" in bundle["ContentType"]


def test_the_entry_page_is_uploaded_after_every_bundle_it_points_at(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    uploads = [e[1] for e in world.events if e[0] == "put"]
    assert uploads[-1] == "index.html" and len(uploads) == 4


def test_a_file_that_is_no_longer_part_of_the_site_is_deleted(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    world.objects["assets/old-9z9z.js"] = "abc"
    go(deploy_app)
    assert "assets/old-9z9z.js" not in world.objects
    assert ("delete", "assets/old-9z9z.js") in world.events


def test_a_rebuild_with_identical_content_uploads_nothing_even_though_every_file_is_new(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    world.events.clear()
    web = tmp_path / "web"
    build(web, {"index.html": "<html>v1</html>", "assets/app-1a2b3c.js": "console.log(1)", "assets/app-1a2b3c.css": "body{}", "zz/late.js": "1"})
    assert go(deploy_app) == 0
    assert [e for e in world.events if e[0] in ("put", "delete", "invalidate")] == []


def test_a_changed_bundle_invalidates_the_cache_and_an_unchanged_one_does_not(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    assert [e for e in world.events if e[0] == "invalidate"] == [("invalidate", "E123ABC", ("/*",))]
    world.events.clear()
    build(tmp_path / "web", {"index.html": "<html>v2</html>", "assets/app-1a2b3c.js": "console.log(1)", "assets/app-1a2b3c.css": "body{}", "zz/late.js": "1"})
    go(deploy_app)
    assert [e[0] for e in world.events if e[0] in ("put", "invalidate")] == ["put", "invalidate"]  # only the page changed
    world.events.clear()
    go(deploy_app)
    assert [e for e in world.events if e[0] == "invalidate"] == []


def test_a_cache_that_could_not_be_cleared_is_cleared_by_running_again_with_the_flag(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    world.invalidation_error = missing("AccessDenied")
    assert go(deploy_app) == 1
    assert "--invalidate" in capsys.readouterr().err
    world.invalidation_error = None
    world.events.clear()
    assert go(deploy_app) == 0 and [e for e in world.events if e[0] == "invalidate"] == []  # nothing changed, so nothing is retried...
    assert go(deploy_app, "--invalidate") == 0  # ...which is why the flag exists
    assert [e for e in world.events if e[0] == "invalidate"] == [("invalidate", "E123ABC", ("/*",))]


def urls(path: Path) -> list[str]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("auth", {}).get("callback_urls", [])


def auth_deploys(world) -> list[tuple]:
    return [c_ for c_ in world.cdk_calls() if world.c.auth_stack in c_]


def test_the_public_url_becomes_a_return_address_and_auth_is_redeployed(deploy_app, monkeypatch, tmp_path):
    c, world, path = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    assert urls(path) == [f"{CLOUDFRONT}/"]
    assert len(auth_deploys(world)) == 1


def test_a_second_run_changes_neither_project_toml_nor_auth(deploy_app, monkeypatch, tmp_path):
    c, world, path = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    first = path.read_bytes()
    world.events.clear()
    assert go(deploy_app) == 0
    assert path.read_bytes() == first and auth_deploys(world) == []
    assert [e for e in world.events if e[0] in ("invalidate", "put", "delete")] == []


def test_if_auth_failed_after_project_toml_was_edited_the_next_run_still_redeploys_it(deploy_app, monkeypatch, tmp_path):
    c, world, path = arrange(deploy_app, monkeypatch, tmp_path)
    world.auth_deploy_error = deploy_app.subprocess.CalledProcessError(1, ["cdk", "deploy"])
    assert go(deploy_app) == 1
    assert urls(path) == [f"{CLOUDFRONT}/"] and world.live_callbacks == []  # the file is ahead of Cognito
    world.auth_deploy_error = None
    world.events.clear()
    assert go(deploy_app) == 0
    assert len(auth_deploys(world)) == 1 and world.live_callbacks == [f"{CLOUDFRONT}/"]


def test_a_project_toml_it_cannot_edit_stops_with_the_line_to_add_and_leaves_auth_alone(deploy_app, monkeypatch, tmp_path, capsys):
    toml = VALID + '\n[auth]\ncallback_urls = ["https://app.example.com/"]  # see [x]\n'
    c, world, path = arrange(deploy_app, monkeypatch, tmp_path, toml=toml)
    assert go(deploy_app) == 1
    assert "callback_urls = [" in capsys.readouterr().err
    assert auth_deploys(world) == []


def test_it_ends_with_the_url_and_how_to_create_a_user_and_prints_no_secret(deploy_app, monkeypatch, tmp_path, capsys):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    assert go(deploy_app) == 0
    out = capsys.readouterr()
    assert f"{CLOUDFRONT}" in out.out and "create_user.py" in out.out
    assert "s3cr3t-password" not in out.out + out.err and "AUTH_JWT_SECRET" not in out.out + out.err


def test_the_return_address_is_added_after_the_site_is_published(deploy_app, monkeypatch, tmp_path):
    c, world, _ = arrange(deploy_app, monkeypatch, tmp_path)
    go(deploy_app)
    last_upload = max(i for i, e in enumerate(world.events) if e[0] == "put")
    last_cdk = max(i for i, e in enumerate(world.events) if e[0] == "cdk")
    assert last_cdk > last_upload


@pytest.mark.parametrize("key,expected", [("a.js", "text/javascript"), ("a.mjs", "text/javascript"), ("a.css", "text/css"), ("f.woff2", "font/woff2"), ("a.js.map", "application/json"), ("i.html", "text/html"), ("x.unknown", "application/octet-stream")])
def test_content_types_do_not_depend_on_the_machines_registry(deploy_app, monkeypatch, key, expected):
    monkeypatch.setattr(deploy_app.mimetypes, "guess_type", lambda _: ("text/plain", None))  # a Windows registry gone wrong
    assert deploy_app.content_type(key) == (expected if key not in ("i.html", "x.unknown") else "text/plain")
