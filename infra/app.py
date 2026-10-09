import aws_cdk as cdk

import config
from definitions.roles import role_specs
from definitions.tables import table_specs
from stacks.data import DataStack
from stacks.roles import RolesStack

c = config.load()
app = cdk.App()
env = cdk.Environment(account=c.aws_account, region=c.aws_region)

RolesStack(app, c.roles_stack, specs=role_specs(c), env=env)
DataStack(app, c.data_stack, specs=table_specs(c), env=env)

app.synth()
