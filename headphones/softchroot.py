import os
from headphones.exceptions import SoftChrootError


class SoftChroot(object):
    """ SoftChroot provides SOFT chrooting for UI

    IMPORTANT: call methods of this class just in modules, which generates data for client UI. Try to avoid unnecessary usage.
    """

    enabled = False
    chroot = None

    def __init__(self, path):
        if not path:
            #disabled
            return

        path = path.strip()
        if not path:
            #disabled
            return

        if (not os.path.exists(path) or
                not os.path.isdir(path)):
            raise SoftChrootError('No such directory: %s' % path)

        path = path.rstrip(os.path.sep) + os.path.sep

        self.enabled = True
        self.chroot = path

    def isEnabled(self):
        return self.enabled

    def getRoot(self):
        return self.chroot

    def apply(self, path):
        if not self.enabled:
            return path

        if not path:
            return path

        p = path.strip()
        if not p:
            return path

        unslashed_chroot = self.chroot[:-1]
        if path.startswith(self.chroot):
            p = os.path.sep + path[len(self.chroot):]
        elif path.startswith(unslashed_chroot):
            p = os.path.sep + path[len(unslashed_chroot):]
        else:
            p = os.path.join(self.chroot, os.path.sep, path)

        return p

    def revoke(self, path):
        if not self.enabled:
            return path

        if not path:
            return self.getRoot()

        p = path.strip()
        if not p:
            return self.getRoot()

        if os.path.sep == p[0]:
            p = p[1:]

        p = self.chroot + p
        return p
