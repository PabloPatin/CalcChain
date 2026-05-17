from __future__ import annotations

from calcchain_core.plugin_api import PluginContext
from calcchain_core.sources import SvnSourceAdapter
from calcchain_core.targets import SvnTargetAdapter


class SvnPlugin:
    plugin_id = 'calcchain.svn'
    plugin_version = '0.1.0'

    def register(self, context: PluginContext) -> None:
        context.sources.register('svn', SvnSourceAdapter(), owner=self.plugin_id)
        context.targets.register('svn', SvnTargetAdapter(), owner=self.plugin_id)
