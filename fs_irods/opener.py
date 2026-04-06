import irods.test.helpers as helpers

import fs
from fs.opener import Opener
from fs.opener.registry import registry

from . import iRODSFS

@registry.install
class iRODSOpener(Opener):

    protocols = ['irods']

    # TODO - Flesh this out.  This is a stub just to get an initial fs.open_fs('irods://...') working.

    def open_fs(self, fs_url, parse_result, writeable, create, cwd):
        
        # TODO - We can use parse_result.resource to determine the root_path parameter value
        #        in the iRODSFS constructor, once an issue 16 fix is merged.

        return iRODSFS(helpers.make_session())
        
