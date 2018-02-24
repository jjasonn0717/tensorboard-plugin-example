import os
import re
import six
from six.moves.urllib import parse as urlparse
import tensorflow as tf
from werkzeug import wrappers
from werkzeug.serving import run_simple

from tensorboard.backend.event_processing.event_multiplexer import EventMultiplexer
from tensorboard.backend import http_util
from tensorboard.plugins.core import core_plugin

import argparse
from greeter_plugin import GreeterPlugin

DATA_PREFIX = '/data'
PLUGIN_PREFIX = '/plugin'
PLUGINS_LISTING_ROUTE = '/plugins_listing'

# Slashes in a plugin name could throw the router for a loop. An empty
# name would be confusing, too. To be safe, let's restrict the valid
# names as follows.
_VALID_PLUGIN_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def _clean_path(path):
    """Removes trailing slash if present, unless it's the root path."""
    if len(path) > 1 and path.endswith('/'):
        return path[:-1]
    return path


class WSGI_APP(object):
    """The TensorBoard WSGI app that delegates to a set of TBPlugin."""
    """Copy from https://github.com/tensorflow/tensorboard/blob/c82300f188e4d2f4e1e2e029ce4019fd9e89a1e9/tensorboard/backend/application.py """
    def __init__(self, plugins):
        """Constructs TensorBoardWSGI instance.
        Args:
          plugins: A list of base_plugin.TBPlugin subclass instances.
        Returns:
          A WSGI application for the set of all TBPlugin instances.
        Raises:
          ValueError: If some plugin has no plugin_name
          ValueError: If some plugin has an invalid plugin_name (plugin
              names must only contain [A-Za-z0-9_.-])
          ValueError: If two plugins have the same plugin_name
          ValueError: If some plugin handles a route that does not start
              with a slash
        """
        self._plugins = plugins

        self.data_applications = {
            # TODO(@chihuahua): Delete this RPC once we have skylark rules that
            # obviate the need for the frontend to determine which plugins are
            # active.
            DATA_PREFIX + PLUGINS_LISTING_ROUTE: self._serve_plugins_listing,
            '/': self._index_route
        }

        # Serve the routes from the registered plugins using their name as the route
        # prefix. For example if plugin z has two routes /a and /b, they will be
        # served as /data/plugin/z/a and /data/plugin/z/b.
        plugin_names_encountered = set()
        for plugin in self._plugins:
            if plugin.plugin_name is None:
                raise ValueError('Plugin %s has no plugin_name' % plugin)
            if not _VALID_PLUGIN_RE.match(plugin.plugin_name):
                raise ValueError('Plugin %s has invalid name %r' % (plugin, plugin.plugin_name))
            if plugin.plugin_name in plugin_names_encountered:
                raise ValueError('Duplicate plugins for name %s' % plugin.plugin_name)
            plugin_names_encountered.add(plugin.plugin_name)

            try:
                plugin_apps = plugin.get_plugin_apps()
            except Exception as e:  # pylint: disable=broad-except
                if type(plugin) is core_plugin.CorePlugin:  # pylint: disable=unidiomatic-typecheck
                    raise tf.logging.warning('Plugin %s failed. Exception: %s', plugin.plugin_name, str(e))
                continue
            for route, app in plugin_apps.items():
                if not route.startswith('/'):
                    raise ValueError('Plugin named %r handles invalid route %r: '
                                     'route does not start with a slash' % (plugin.plugin_name, route))
                if type(plugin) is core_plugin.CorePlugin:  # pylint: disable=unidiomatic-typecheck
                    path = route
                else:
                    path = DATA_PREFIX + PLUGIN_PREFIX + '/' + plugin.plugin_name + route
                self.data_applications[path] = app

    @wrappers.Request.application
    def _serve_plugins_listing(self, request):
        """Serves an object mapping plugin name to whether it is enabled.
        Args:
          request: The werkzeug.Request object.
        Returns:
          A werkzeug.Response object.
        """
        return http_util.Respond(
            request,
            {plugin.plugin_name: plugin.is_active() for plugin in self._plugins},
            'application/json')

    @wrappers.Request.application
    def _index_route(self, request):
        """serve index.html.
        Args:
          request: The werkzeug.Request object.
        Returns:
          A werkzeug.Response object.
        """
        with open('./test.html', 'r') as f:
            html_body = f.read()
        return http_util.Respond(request, html_body, 'text/html')

    def __call__(self, environ, start_response):  # pylint: disable=invalid-name
        """Central entry point for the TensorBoard application.
        This method handles routing to sub-applications. It does simple routing
        using regular expression matching.
        This __call__ method conforms to the WSGI spec, so that instances of this
        class are WSGI applications.
        Args:
          environ: See WSGI spec.
          start_response: See WSGI spec.
        Returns:
          A werkzeug Response.
        """
        request = wrappers.Request(environ)
        parsed_url = urlparse.urlparse(request.path)
        clean_path = _clean_path(parsed_url.path)
        # pylint: disable=too-many-function-args
        if clean_path in self.data_applications:
            return self.data_applications[clean_path](environ, start_response)
        else:
            tf.logging.warning('path %s not found, sending 404', clean_path)
            return http_util.Respond(request, 'Not found', 'text/plain', code=404)(environ, start_response)
            #return http_util.Respond(request, 'Not found', 'text/plain', code=404)
        # pylint: enable=too-many-function-args


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--logdir', default='/tmp/greeter_demo')
    parser.add_argument('--port', default=6008, type=int)
    args = parser.parse_args()

    multiplexer = EventMultiplexer().AddRunsFromDirectory(args.logdir)
    multiplexer.Reload()
    plugins = [GreeterPlugin(multiplexer)]

    app = WSGI_APP(plugins)
    run_simple('0.0.0.0', args.port, app, use_debugger=True, use_reloader=True)
