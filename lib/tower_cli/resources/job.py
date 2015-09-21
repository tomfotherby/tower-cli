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

from __future__ import absolute_import, unicode_literals
from copy import copy
from datetime import datetime
from getpass import getpass
import sys
import time

import click

from sdict import adict

from tower_cli import models, get_resource, resources
from tower_cli.api import client
from tower_cli.conf import settings
from tower_cli.utils import debug, exceptions as exc, types


class Resource(models.MonitorableResource):
    """A resource for jobs.

    As a base resource, this resource does *not* have the normal create, list,
    etc. methods.
    """
    cli_help = 'Launch or monitor jobs.'
    endpoint = '/jobs/'

    @resources.command
    @click.option('--job-template', type=types.Related('job_template'))
    @click.option('--monitor', is_flag=True, default=False,
                  help='If sent, immediately calls `job monitor` on the newly '
                       'launched job rather than exiting with a success.')
    @click.option('--timeout', required=False, type=int,
                  help='If provided with --monitor, this command (not the job)'
                       ' will time out after the given number of seconds. '
                       'Does nothing if --monitor is not sent.')
    @click.option('--no-input', is_flag=True, default=False,
                                help='Suppress any requests for input.')
    @click.option('--extra-vars', type=types.File('r'), required=False)
    @click.option('--tags', required=False)
    def launch(self, job_template, tags=None, monitor=False, timeout=None,
                     no_input=True, extra_vars=None):
        """Launch a new job based on a job template.

        Creates a new job in Ansible Tower, immediately stats it, and
        returns back an ID in order for its status to be monitored.
        """
        # Get the job template from Ansible Tower.
        # This is used as the baseline for starting the job.
        jt_resource = get_resource('job_template')
        jt = jt_resource.get(job_template)

        # Update the job data by adding an automatically-generated job name,
        # and removing the ID.
        data = copy(jt)
        data['job_template'] = data.pop('id')
        data['name'] = '%s [invoked via. Tower CLI]' % data['name']
        if tags:
            data['job_tags'] = tags

        # If the job template requires prompting for extra variables,
        # do so (unless --no-input is set).
        if extra_vars:
            if hasattr(extra_vars, 'read'):
                extra_vars = extra_vars.read()
            data['extra_vars'] = data['extra_vars']+extra_vars
        elif data.pop('ask_variables_on_launch', False) and not no_input:
            initial = data['extra_vars']
            initial = '\n'.join((
                '# Specify extra variables (if any) here.',
                '# Lines beginning with "#" are ignored.',
                initial,
            ))
            extra_vars = click.edit(initial) or ''
            extra_vars = '\n'.join([i for i in extra_vars.split('\n')
                                            if not i.startswith('#')])
            data['extra_vars'] = extra_vars

        # In Tower 2.1 and later, we create the new job with
        # /job_templates/N/launch/; in Tower 2.0 and before, there is a two
        # step process of posting to /jobs/ and then /jobs/N/start/.
        supports_job_template_launch = False
        if 'launch' in jt['related']:
            supports_job_template_launch = True

        # Create the new job in Ansible Tower.
        start_data = {}
        if supports_job_template_launch:
            endpoint = '/job_templates/%d/launch/' % jt['id']
            if 'extra_vars' in data:
                start_data['extra_vars'] = data['extra_vars']
            if tags:
                start_data['job_tags'] = data['job_tags']
        else:
            debug.log('Creating the job.', header='details')
            job = client.post('/jobs/', data=data).json()
            job_id = job['id']
            endpoint = '/jobs/%d/start/' % job_id

        # There's a non-trivial chance that we are going to need some
        # additional information to start the job; in particular, many jobs
        # rely on passwords entered at run-time.
        #
        # If there are any such passwords on this job, ask for them now.

        debug.log('Asking for information necessary to start the job.',
                  header='details')
        job_start_info = client.get(endpoint).json()
        for password in job_start_info.get('passwords_needed_to_start', []):
            start_data[password] = getpass('Password for %s: ' % password)

        # Actually start the job.
        debug.log('Launching the job.', header='details')
        result = client.post(endpoint, start_data)

        # If this used the /job_template/N/launch/ route, get the job
        # ID from the result.
        if supports_job_template_launch:
            job_id = result.json()['job']

        # If we were told to monitor the job once it started, then call
        # monitor from here.
        if monitor:
            return self.monitor(job_id, timeout=timeout)

        # Return the job ID.
        return {
            'changed': True,
            'id': job_id,
        }

    @resources.command
    @click.option('--detail', is_flag=True, default=False,
                              help='Print more detail.')
    def status(self, pk, detail=False):
        """Print the current job status."""
        # Get the job from Ansible Tower.
        debug.log('Asking for job status.', header='details')
        job = client.get('/jobs/%d/' % pk).json()

        # In most cases, we probably only want to know the status of the job
        # and the amount of time elapsed. However, if we were asked for
        # verbose information, provide it.
        if detail:
            return job

        # Print just the information we need.
        return adict({
            'elapsed': job['elapsed'],
            'failed': job['failed'],
            'status': job['status'],
        })

    @resources.command
    @click.option('--fail-if-not-running', is_flag=True, default=False,
                  help='Fail loudly if the job is not currently running.')
    def cancel(self, pk, fail_if_not_running=False):
        """Cancel a currently running job.

        Fails with a non-zero exit status if the job cannot be canceled.
        """
        # Attempt to cancel the job.
        try:
            client.post('/jobs/%d/cancel/' % pk)
            changed = True
        except exc.MethodNotAllowed:
            changed = False
            if fail_if_not_running:
                raise exc.TowerCLIError('Job not running.')

        # Return a success.
        return adict({'status': 'canceled', 'changed': changed})
