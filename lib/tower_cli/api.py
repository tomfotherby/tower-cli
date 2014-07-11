# Copyright 2014, Ansible, Inc.
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

import contextlib
import copy
import functools
import json

from requests.sessions import Session
from requests.models import Response

from fauxquests.adapter import FauxAdapter

from tower_cli.conf import settings
from tower_cli.utils import data_structures, exceptions as exc


class Client(Session):
    """A class for making HTTP requests to the Ansible Tower API and
    returning the responses.

    This functions as a wrapper around [requests][1], and returns its
    responses; therefore, interact with response objects to this class the
    same way you would with objects you get back from `requests.get` or
    similar.

      [1]: http://docs.python-requests.org/en/latest/
    """
    @property
    def prefix(self):
        """Return the appropriate URL prefix to prepend to requests,
        based on the host provided in settings.
        """
        host = settings.host
        if '://' not in host:
            host = 'https://%s' % host.strip('/')
        return '%s/api/v1/' % host.rstrip('/')

    @functools.wraps(Session.request)
    def request(self, method, url, *args, **kwargs):
        """Make a request to the Ansible Tower API, and return the
        response.
        """
        # Piece together the full URL.
        url = '%s%s' % (self.prefix, url.lstrip('/'))

        # Ansible Tower expects authenticated requests; add the authentication
        # from settings if it's provided.
        kwargs.setdefault('auth', (settings.username, settings.password))

        # POST and PUT requests will send JSON by default; make this
        # the content_type by default.  This makes it such that we don't have
        # to constantly write that in our code, which gets repetitive.
        headers = kwargs.get('headers', {})
        if method.upper() in ('PATCH', 'POST', 'PUT'):
            headers.setdefault('Content-Type', 'application/json')
            kwargs['headers'] = headers

        # If this is a JSON request, encode the data value.
        if headers.get('Content-Type', '') == 'application/json':
            kwargs['data'] = json.dumps(kwargs.get('data', {}))

        # Call the superclass method.
        r = super(Client, self).request(method, url, *args, **kwargs)

        # Sanity check: Did the server send back some kind of internal error?
        # If so, bubble this up.
        if r.status_code >= 500:
            raise exc.ServerError('The Tower server sent back a server error. '
                                  'Please try again later.')

        # Sanity check: Did we fail to authenticate properly?
        # If so, fail out now; this is always a failure.
        if r.status_code == 401:
            raise exc.AuthError('Invalid Tower authentication credentials.')

        # Sanity check: Did we get a forbidden response, which means that
        # the user isn't allowed to do this? Report that.
        if r.status_code == 403:
            raise exc.Forbidden("You don't have permission to do that.")

        # Sanity check: Did we get a 404 response?
        # Requests with primary keys will return a 404 if there is no response,
        # and we want to consistently trap these.
        if r.status_code == 404:
            raise exc.NotFound('The requested object could not be found.')

        # Sanity check: Did we get a 405 response?
        # A 405 means we used a method that isn't allowed. Usually this
        # is a bad request, but it requires special treatment because the
        # API sends it as a logic error in a few situations (e.g. trying to
        # cancel a job that isn't running).
        if r.status_code == 405:
            raise exc.MethodNotAllowed(
                "The Tower server says you can't make a request with the "
                "%s method to that URL (%s)." % (method, url),
            )

        # Sanity check: Did we get some other kind of error?
        # If so, write an appropriate error message.
        if r.status_code >= 400:
            raise exc.BadRequest(
                'The Tower server claims it was sent a bad request.\n\n'
                '%s %s\nParams: %s\nData: %s\n\nResponse: %s' %
                (method, url, kwargs.get('params', None),
                 kwargs.get('data', None), r.content.decode('utf8'))
            )

        # Django REST Framework intelligently prints API keys in the
        # order that they are defined in the models and serializer.
        #
        # We want to preserve this behavior when it is possible to do so
        # with minimal effort, because while the order has no explicit meaning,
        # we make some effort to order keys in a convenient manner.
        #
        # To this end, make this response into an APIResponse subclass
        # (defined below), which has a `json` method that doesn't lose key
        # order.
        r.__class__ = APIResponse

        # Return the response object.
        return r

    @property
    @contextlib.contextmanager
    def test_mode(self):
        """Replace the HTTP adapters with a fauxquests.FauxAdapter, which
        will make the client into a faux client.
        """
        with settings.runtime_values(host='20.12.4.21', username='meagan',
                                     password='This is the best wine.',
                                     verbose=False, format='json'):
            adapters = copy.copy(self.adapters)
            faux_adapter = FauxAdapter(
                url_pattern=self.prefix.rstrip('/') + '%s',
            )
            
            try:
                self.adapters.clear()
                self.mount('https://', faux_adapter)
                self.mount('http://', faux_adapter)
                yield faux_adapter
            finally:
                self.adapters = adapters
            

class APIResponse(Response):
    """A Response subclass which preseves JSON key order (but makes no other
    changes).
    """
    def json(self, **kwargs):
        kwargs.setdefault('object_pairs_hook', data_structures.OrderedDict)
        return super(APIResponse, self).json(**kwargs)


client = Client()
