from headphones import logger

""" List of types, which ConfigOpt could handle internally, without conversions """
_primitives = (int, str, bool, list, float)


class OptionModel(object):
    """ Stores value of option, and know, how to write this value to the config file"""

    def __init__(self, appkey, section, default, typeconv):

        self._config_callback = None

        self._appkey = appkey
        self._inikey = appkey.lower()
        self._section = section
        self._default = default
        self._typeconv = typeconv

    @property
    def appkey(self):
        return self._appkey

    @property
    def inikey(self):
        return self._inikey

    @property
    def section(self):
        return self._section

    @section.setter
    def section(self, value):
        """ The value of 'section' is immutable. But it is possible to change CASE of this value """
        ov = self._section.lower() if self._section else None
        nv = value.lower() if value else None

        # is immutable. Could change case of chars, or change value from None to not None
        if (ov is None) or (ov == nv):
            self._section = value
        else:
            raise ValueError('section already set')
        return self._section

    def bindToConfig(self, config_callback):
        self._config_callback = config_callback

    def get(self):
        # abbreviation. I am too lazy to write 'self._inikey', will use 'k'
        s = self._section   # section
        k = self._inikey    # key
        t = self._typeconv   # type
        d = self._default

        if self._config_callback is None:
            msg = 'Option [{0}][{1}] was not binded/registered with config'.format(s, k)
            logger.error(msg)
            raise Exception(msg)

        config = self._config_callback()

        v = None
        if s not in config:
            # take default, there is no appropriate section in config
            v = d
        elif k not in config[s]:
            # take default, there is no appropriate option in config
            v = d
        else:
            v = config[s][k]

        # cast to target type:
        try:
            v = t(v)
        except TypeError as exc:
            logger.error('The value of option [{0}[{1}] is not well-typed. Will try to use default value.'.format(s, k))
            v = t(d)

        return v

    def set(self, value):
        # abbreviation. I am too lazy to write 'self._inikey', will use 'k'
        s = self._section   # section
        k = self._inikey    # key
        d = self._default
        t = self._typeconv   # type

        if self._config_callback is None:
            msg = 'Option [{0}][{1}] was not binded/registered with config'.format(s, k)
            logger.error(msg)
            raise Exception(msg)

        config = self._config_callback()

        if s not in config:
            # create section:
            config[s] = {}

        # convert value to storable types:
        if not isinstance(value, _primitives):
            logger.debug('Value of option [{0}][{1}] is not primitive (but {2}), will stringify it'.format(s, k, type(value)))
            value = str(value)
        else:
            value = t(value)

        config[s][k] = value
