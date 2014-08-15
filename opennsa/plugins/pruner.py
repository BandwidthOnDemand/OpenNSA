"""
Plugin to prune paths in order to help the probabilty that a path setup will succeed.

Mostly to work around limitations on certain network equipment, NRM,
and NSI agent implementations.

Author: Henrik Thostrup Jensen < htj at nordu dot net >

Copyright: NORDUnet A/S (2014)
"""

from zope.interface import implements

from twisted.internet import defer

from opennsa import nsa
from opennsa.interface import IPlugin
from opennsa.plugin import BasePlugin



def pruneLabels(path):
    """
    Some networks does not support underspecified STPs and VLAN rewrites so we help them out a bit.
    """
    NETWORKS = [ 'surfnet.nl' ]

    for idx, link in enumerate(path):

        #if 'surfnet.nl' in link.network:
        if any( [ n in link.network for n in NETWORKS ] ):
            liv = link.src_label.intersect(link.dst_label)
            lnv = nsa.Label(liv.type_, liv.labelValue())
            link.src_label = lnv
            link.dst_label = lnv

            if idx > 0:
                prev_link = path[idx-1]
                prev_link.dst_label = lnv

            if idx < len(path) - 1:
                next_link = path[idx+1]
                next_link.src_label = lnv

    return path



class PrunerPlugin(BasePlugin):
    implements(IPlugin)


    def prunePath(self, paths):
        pruned_paths = [ pruneLabels(paths[0]) ]
        return defer.succeed(pruned_paths)


plugin = PrunerPlugin()

