# Copyright 2017 Google Inc. All Rights Reserved.
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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf
import numpy as np
import argparse
import six
from werkzeug import wrappers
from werkzeug.serving import run_simple

from tensorboard.backend import http_util
from tensorboard.plugins import base_plugin
from tensorboard.backend.event_processing.event_multiplexer import EventMultiplexer

class GreeterPlugin(base_plugin.TBPlugin):
  """A plugin that serves greetings recorded during model runs."""

  # This static property will also be included within routes (URL paths)
  # offered by this plugin. This property must uniquely identify this plugin
  # from all other plugins.
  plugin_name = 'greeter'

  def __init__(self, multiplexer):
    """Instantiates a GreeterPlugin.
    """
    self._multiplexer = multiplexer

  @wrappers.Request.application
  def tags_route(self, request):
    """A route (HTTP handler) that returns a response with tags.

    Returns:
      A response that contains a JSON object. The keys of the object
      are all the runs. Each run is mapped to a (potentially empty)
      list of all tags that are relevant to this plugin.
    """
    # This is a dictionary mapping from run to (tag to string content).
    # To be clear, the values of the dictionary are dictionaries.
    all_runs = self._multiplexer.PluginRunToTagToContent(
        GreeterPlugin.plugin_name)
    tf.logging.warning(request)

    # tagToContent is itself a dictionary mapping tag name to string
    # content. We retrieve the keys of that dictionary to obtain a
    # list of tags associated with each run.
    response = {
        run: list(tagToContent.keys())
        for (run, tagToContent) in all_runs.items()
    }
    return http_util.Respond(request, response, 'application/json')

  def get_plugin_apps(self):
    """Gets all routes offered by the plugin.

    This method is called by TensorBoard when retrieving all the
    routes offered by the plugin.

    Returns:
      A dictionary mapping URL path to route that handles it.
    """
    # Note that the methods handling routes are decorated with
    # @wrappers.Request.application.
    return {
        '/tags': self.tags_route,
        '/greetings': self.greetings_route,
    }

  def is_active(self):
    """Determines whether this plugin is active.

    This plugin is only active if TensorBoard sampled any summaries
    relevant to the greeter plugin.

    Returns:
      Whether this plugin is active.
    """
    all_runs = self._multiplexer.PluginRunToTagToContent(
        GreeterPlugin.plugin_name)

    # The plugin is active if any of the runs has a tag relevant
    # to the plugin.
    return bool(self._multiplexer and any(six.itervalues(all_runs)))

  def _process_string_tensor_event(self, event):
    """Convert a TensorEvent into a JSON-compatible response."""
    string_arr = tf.make_ndarray(event.tensor_proto)
    text = string_arr.astype(np.dtype(str)).tostring()
    return {
        'wall_time': event.wall_time,
        'step': event.step,
        'text': text,
    }

  @wrappers.Request.application
  def greetings_route(self, request):
    """A route that returns the greetings associated with a tag.

    Returns:
      A JSON list of greetings associated with the run and tag
      combination.
    """
    tf.logging.warning(request)
    run = request.args.get('run')
    tag = request.args.get('tag')
    if run == None or tag == None:
        response = "404 NOT FOUND\n" + \
                   "Please provide run and tag in url as \n" + \
                   "ADDRESS:PORT/data/plugin/greeter/greetings?run=steven_universe&tag=greetings"
        return http_util.Respond(request, response, 'text/plain', code=404)

    # We fetch all the tensor events that contain greetings.
    try:
        tensor_events = self._multiplexer.Tensors(run, tag)
    except:
        response = "Incorrect run or tag\n" + \
                   "Please check ADDRESS:PORT/data/plugin/greeter/tags first"
        return http_util.Respond(request, response, 'text/plain', code=404)

    # We convert the tensor data to text.
    response = [self._process_string_tensor_event(ev) for
                ev in tensor_events]
    return http_util.Respond(request, response, 'application/json')



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--logdir', default='/tmp/greeter_demo')
    parser.add_argument('--port', default=6008, type=int)
    args = parser.parse_args()

    multiplexer = EventMultiplexer().AddRunsFromDirectory(args.logdir)
    multiplexer.Reload()
    plugin = GreeterPlugin(multiplexer)
    run_simple('0.0.0.0', args.port, plugin.tags_route, use_debugger=True, use_reloader=True)
