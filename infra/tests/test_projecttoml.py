import importlib.util
import tomllib
from pathlib import Path

import pytest

import config
from definitions.auth import auth_specs
from tests.test_config import VALID

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_spec = importlib.util.spec_from_file_location("projecttoml", SCRIPTS / "projecttoml.py")
projecttoml = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(projecttoml)

URL = "https://d111111abcdef8.cloudfront.net/"
OTHER = "https://app.example.com/"
# The [auth] block the template ships with, as a copy: the repo's own project.toml changes as it gets deployed.
TEMPLATE_AUTH = """
[auth]
# Extra sign-in / sign-out return addresses besides http://localhost:5173/ (always allowed).
# Add the deployed app's public URL, with a trailing slash, once it exists.
# callback_urls = ["https://app.example.com/"]
"""
REPO_TOML = VALID + TEMPLATE_AUTH


def put(tmp_path, text: str, newline: str = "\n") -> Path:
    path = tmp_path / "project.toml"
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def urls(path: Path) -> list[str]:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("auth", {}).get("callback_urls", [])


def rest(path: Path) -> dict:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    data.get("auth", {}).pop("callback_urls", None)
    if data.get("auth") == {}:
        data.pop("auth")
    return data


FORMS = {
    "one line": VALID + f'\n[auth]\ncallback_urls = ["{OTHER}"]\n',
    "several lines": VALID + f'\n[auth]\ncallback_urls = [\n  "{OTHER}",  # the first\n]\n',
    "empty list": VALID + "\n[auth]\ncallback_urls = []\n",
    "key commented out": VALID + f'\n[auth]\n# Extra return addresses.\n# callback_urls = ["{OTHER}"]\n',
    "section without the key": VALID + "\n[auth]\n# nothing yet\n",
    "no section": VALID,
    "section between others": VALID.replace("[harness]", "[auth]\n# nothing yet\n\n[harness]"),
}


@pytest.mark.parametrize("form", FORMS)
def test_the_url_is_added_in_every_form(tmp_path, form):
    path = put(tmp_path, FORMS[form])
    before = rest(path)
    existing = urls(path)
    assert projecttoml.add_callback_url(path, URL) is True
    assert urls(path) == [*existing, URL]
    assert rest(path) == before  # nothing else in the file changed


@pytest.mark.parametrize("form", FORMS)
def test_adding_it_again_changes_nothing(tmp_path, form):
    path = put(tmp_path, FORMS[form])
    projecttoml.add_callback_url(path, URL)
    first = path.read_bytes()
    assert projecttoml.add_callback_url(path, URL) is False
    assert path.read_bytes() == first


def test_the_repo_project_toml_template_takes_the_url(tmp_path):
    path = put(tmp_path, REPO_TOML)
    assert projecttoml.add_callback_url(path, URL)
    assert urls(path) == [URL]
    assert "# callback_urls" in path.read_text(encoding="utf-8")  # the example stays


def test_comments_and_the_other_urls_survive(tmp_path):
    path = put(tmp_path, FORMS["several lines"])
    projecttoml.add_callback_url(path, URL)
    text = path.read_text(encoding="utf-8")
    assert "# the first" in text and OTHER in text


@pytest.mark.parametrize("form", FORMS)
def test_line_endings_are_preserved_in_every_form_including_the_ones_that_insert_a_line(tmp_path, form):
    path = put(tmp_path, FORMS[form], newline="\r\n")
    assert projecttoml.add_callback_url(path, URL)
    raw = path.read_bytes()
    assert raw.count(b"\n") == raw.count(b"\r\n")  # no bare line feed anywhere
    assert URL.encode() in raw


def test_the_last_item_without_a_comma_gets_one_and_keeps_its_comment(tmp_path):
    path = put(tmp_path, VALID + f'\n[auth]\ncallback_urls = [\n  "{OTHER}"  # the only one\n]\n')
    projecttoml.add_callback_url(path, URL)
    assert f'"{OTHER}",  # the only one' in path.read_text(encoding="utf-8")
    assert urls(path) == [OTHER, URL]


def test_a_form_it_does_not_recognise_is_left_alone_and_the_line_to_add_is_given(tmp_path):
    path = put(tmp_path, VALID + f'\n[auth]\ncallback_urls = {{ a = "{OTHER}" }}\n')
    before = path.read_bytes()
    with pytest.raises(projecttoml.ProjectTomlError, match=r'callback_urls = \["'):
        projecttoml.add_callback_url(path, URL)
    assert path.read_bytes() == before


def test_the_local_development_address_stays_allowed_after_the_edit(tmp_path):
    path = put(tmp_path, FORMS["one line"])
    projecttoml.add_callback_url(path, URL)
    specs = auth_specs(config.load(path))
    assert config.LOCAL_CALLBACK_URL in specs[0].callback_urls
    assert {URL, OTHER} <= set(specs[0].callback_urls)
    assert URL in specs[0].logout_urls


# Edits that would corrupt the file are caught by parsing the result back, before anything is written.
BREAKS_THE_FILE = {
    "a bracket in a trailing comment": '[auth]\ncallback_urls = ["https://app.example.com/"]  # see [x]\n',
    "a hash inside a url": '[auth]\ncallback_urls = [\n  "https://a.example/#/cb",\n]\n',
    "items already on the opening line": '[auth]\ncallback_urls = ["https://app.example.com/",\n  "https://b.example/"]\n',
    # "TOP:" puts it before the first table, where a top-level key belongs.
    "an inline auth table": 'TOP:auth = { callback_urls = ["https://app.example.com/"] }\n',
}


@pytest.mark.parametrize("case", BREAKS_THE_FILE)
def test_an_edit_that_would_corrupt_the_file_writes_nothing_and_gives_the_line_to_add(tmp_path, case):
    body = BREAKS_THE_FILE[case]
    path = put(tmp_path, body[4:] + VALID if body.startswith("TOP:") else VALID + "\n" + body)
    before = path.read_bytes()
    with pytest.raises(projecttoml.ProjectTomlError) as error:
        projecttoml.add_callback_url(path, URL)
    assert "callback_urls = [" in str(error.value) and URL in str(error.value)
    assert path.read_bytes() == before
