import sys
import functools

from build123d import Sphere

from .build_line import build_line


def set_current(fn):
    import pytest
    set_current.fn = fn
    return pytest.mark.current(fn)
set_current.fn = None


class ShowList:
    def __init__(self):
        self.objects = []
        self.names = []
        self.cnt = 0

    def reset(self):
        self.objects.clear()
        self.names.clear()
        self.cnt = 0

    def __call__(self, fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            self.append(part=fn(*args, **kwargs))
        return inner

    def origin_radius(self):
        if not self.objects:
            return 1
        o = self.objects[-1]
        if hasattr(o, 'bounding_box'):
            bbox = o.bounding_box()
            if bbox.diagonal > 20:
                return 1
            else:
                return 0.1
        else:
            return 1

    def append(self, *items, **kwargs):
        olist = []
        if items:
            fl = sys._getframe(1).f_locals
            fmap = {id(v): k for k, v in fl.items()}
            for o in items:
                k = id(o)
                if k in fmap:
                    n = fmap[k]
                else:
                    self.cnt += 1
                    n = f'unknown_var_{self.cnt}'
                olist.append((n, o))

        olist.extend(kwargs.items())

        for n, o in olist:
            if o is None:
                continue
            if isinstance(o, build_line):
                o = o.wire()
            self.objects.append(o)
            self.names.append(n)

slist = ShowList()
sadd = slist.append

def main_yacv():
    from yacv_server import show

    set_current.fn and slist.reset()
    sadd(origin=Sphere(1))
    set_current.fn and set_current.fn()
    show(*slist.objects, names=slist.names)


def main_ocp_vscode(**options):
    from ocp_vscode import show, set_port, set_defaults
    from ocp_vscode.config import Camera
    set_port(options.pop('port', 3939))
    # if options:
    #     set_defaults(**options)

    if set_current.fn:
        slist.reset()
        set_current.fn()
    show(*slist.objects, names=slist.names, progress='', reset_camera=Camera.KEEP)


__all__ = ['slist', 'sadd', 'main_yacv', 'set_current', 'main_ocp_vscode']
