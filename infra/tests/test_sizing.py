import pytest

import config
from tests.test_config import VALID, write


def with_env(tmp_path, body: str) -> config.Config:
    return config.load(write(tmp_path, VALID.split("[environments.dev]")[0] + body))


def test_nat_gateways_default_to_one(tmp_path):
    c = with_env(tmp_path, "[environments.dev]\ndesired_count = 1\ncpu = 256\nmemory = 512\n")
    assert c.sizing("dev").nat_gateways == 1


def test_environment_sets_its_own_nat_gateways(tmp_path):
    c = with_env(
        tmp_path,
        "[environments.prod]\ndesired_count = 2\ncpu = 512\nmemory = 1024\nnat_gateways = 2\n",
    )
    assert c.sizing("prod") == config.Sizing(2, 512, 1024, 2)


@pytest.mark.parametrize("nat", [0, 3])
def test_nat_gateways_outside_the_two_zones_are_rejected(tmp_path, nat):
    with pytest.raises(ValueError, match=r"environments\.dev.*nat_gateways"):
        with_env(tmp_path, f"[environments.dev]\ndesired_count = 1\ncpu = 256\nmemory = 512\nnat_gateways = {nat}\n")


@pytest.mark.parametrize(
    "cpu,memory",
    [(256, 512), (256, 2048), (512, 1024), (512, 4096), (1024, 2048), (2048, 16384), (4096, 8192), (4096, 30720)],
)
def test_valid_fargate_combinations_load(tmp_path, cpu, memory):
    c = with_env(tmp_path, f"[environments.dev]\ndesired_count = 1\ncpu = {cpu}\nmemory = {memory}\n")
    assert (c.sizing("dev").cpu, c.sizing("dev").memory) == (cpu, memory)


@pytest.mark.parametrize("cpu,memory", [(256, 4096), (512, 512), (1024, 1536), (300, 512), (4096, 4096)])
def test_invalid_fargate_combination_names_environment_and_values(tmp_path, cpu, memory):
    with pytest.raises(ValueError, match=rf"environments\.dev.*cpu={cpu}.*memory={memory}"):
        with_env(tmp_path, f"[environments.dev]\ndesired_count = 1\ncpu = {cpu}\nmemory = {memory}\n")


def test_unknown_environment_lists_the_defined_ones(tmp_path):
    c = config.load(write(tmp_path, VALID))
    with pytest.raises(ValueError, match=r"'qa'.*valid: dev"):
        c.sizing("qa")


def test_new_names_derive_from_the_project_name(tmp_path):
    c = config.load(write(tmp_path, VALID))
    assert c.network_stack == "acme-portal-network"
    assert c.load_balancer == "acme-portal-alb"
    assert c.log_group == "/acme-portal/api"
    assert c.auth_jwt_secret_name == "acme-portal/auth-jwt-secret"


def test_repo_project_toml_defines_nat_gateways_per_environment():
    c = config.load()
    assert c.sizing("dev").nat_gateways == 1
    assert c.sizing("prod").nat_gateways == 2
