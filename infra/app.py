import aws_cdk as cdk

import config
from definitions.app import app_specs
from definitions.auth import auth_specs
from definitions.network import network_specs
from definitions.roles import role_specs
from definitions.tables import table_specs
from deployment import DeployInputs
from stacks.app import AppStack
from stacks.auth import AuthStack
from stacks.data import DataStack
from stacks.network import NetworkStack
from stacks.roles import RolesStack


def build(app: cdk.App, c: config.Config) -> None:
    env = cdk.Environment(account=c.aws_account, region=c.aws_region)

    RolesStack(app, c.roles_stack, specs=role_specs(c), env=env)
    AuthStack(app, c.auth_stack, specs=auth_specs(c), env=env)
    DataStack(app, c.data_stack, specs=table_specs(c), env=env)

    # The network and the app are deployed by scripts/deploy_app.py, which passes `-c env=<name>` and
    # what only exists at deploy time. Without an environment they are left out, so deploying the
    # stacks above never needs any of it. With one, anything missing stops the synth, named.
    if app.node.try_get_context("env") is None:
        return
    inputs = DeployInputs.from_context(c, app.node.try_get_context)

    if c.existing_network:
        vpc = c.existing_network  # nothing is created: the app stack imports it
    else:
        network = NetworkStack(
            app, c.network_stack, specs=network_specs(), nat_gateways=c.sizing(inputs.env).nat_gateways, env=env
        )
        (vpc,) = network.vpcs.values()
    AppStack(app, c.app_stack, specs=app_specs(c, inputs), vpc=vpc, env=env)


if __name__ == "__main__":
    app = cdk.App()
    build(app, config.load())
    app.synth()
