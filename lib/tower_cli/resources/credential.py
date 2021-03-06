# Copyright 2015, Ansible, Inc.
# Luke Sneeringer <lsneeringer@ansible.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import click

from tower_cli import models
from tower_cli.utils import exceptions as exc
from tower_cli.utils import types


class Resource(models.Resource):
    cli_help = 'Manage credentials within Ansible Tower.'
    endpoint = '/credentials/'
    identity = ('user', 'team', 'kind', 'name')

    name = models.Field(unique=True)
    description = models.Field(required=False, display=False)

    # Who owns this credential?
    user = models.Field(
        display=False,
        type=types.Related('user'),
        required=False,
    )
    team = models.Field(
        display=False,
        type=types.Related('team'),
        required=False,
    )

    # What type of credential is this (machine, SCM, etc.)?
    kind = models.Field(
        help_text='The type of credential being added. '
                  'Valid options are: ssh, scm, aws, rax, vmware,'
                  ' gce, azure, openstack.',
        type=click.Choice(['ssh', 'scm', 'aws', 'rax', 'vmware',
                           'gce', 'azure', 'openstack']),
    )

    # need host in order to use VMware
    host = models.Field(
        help_text='The hostname or IP address to use.',
        required=False,
    )
    # need project to use openstack
    project = models.Field(
        help_text='The identifier for the project.',
        required=False
    )

    # SSH and SCM fields.
    username = models.Field(
        help_text='The username. For AWS credentials, the access key.',
        required=False,
    )
    password = models.Field(
        help_text='The password. For AWS credentials, the secret key. '
                  'For Rackspace credentials, the API key.',
        password=True,
        required=False,
    )
    ssh_key_data = models.Field(
        'ssh_key_data',
        display=False,
        help_text="The full path to the SSH private key to store. "
                  "(Don't worry; it's encrypted.)",
        required=False,
        type=models.File('r'),
    )
    ssh_key_unlock = models.Field('ssh_key_unlock', password=True,
                                  required=False)

    # Method with which to esclate
    become_method = models.Field(
        help_text='Privledge escalation method. ',
        type=types.MappedChoice([
            ('', 'None'),
            ('sudo', 'sudo'),
            ('su', 'su'),
            ('pbrun', 'pbrun'),
            ('pfexec', 'pfexec'),
        ]),
        required=False,
    )

    # SSH specific fields.
    become_username = models.Field(required=False, display=False)
    become_password = models.Field(password=True, required=False)
    vault_password = models.Field(password=True, required=False)
