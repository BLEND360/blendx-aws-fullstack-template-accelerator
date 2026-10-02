import aws_cdk as cdk

import config
from definitions.roles import role_specs
from stacks.roles import RolesStack

c = config.load()
app = cdk.App()
env = cdk.Environment(account=c.aws_account, region=c.aws_region)

RolesStack(app, c.roles_stack, specs=role_specs(c), env=env)

app.synth()
