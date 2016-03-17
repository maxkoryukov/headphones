def boolext(value):
    """ extended bool could read bool values from strings like '0', 'f', 'no' ano others.
    """
    if isinstance(value, basestring):
        v = value.lower()
        if v in ('', '0', 'false', 'f', 'no', 'n', 'off', '-'):
            return False
        if v in ('1', 'true', 't', 'yes', 'y', 'on', '+'):
            return True
    return bool(value)


class path(str):
    """ path-type for option value

    Describes the path on the file system.
    """

    @staticmethod
    def __call__(val):
        return path(val)

    def __new__(cls, *args, **kw):
        hstr = str.__new__(cls, *args, **kw)
        return hstr

    def __repr__(self):
        return 'headphones.config.types.path(%s)' % self
