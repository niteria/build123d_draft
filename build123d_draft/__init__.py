import math

from build123d import geometry as _gm
from build123d import topology as _tp
from build123d import build_enums as _be

from build123d_draft.utils import PPos

dpr = math.pi/180
sqr2 = math.sqrt(2)

def gen_pos(name, cls=_gm.Pos, default_zdir=None):
    def g(val):
        rv = cls(**{name: val})
        rv.default_zdir = default_zdir
        return rv
    return g

def gen_rot(name):
    def g(val):
        return _gm.Rot(**{name: val})
    return g

X = gen_pos('X', default_zdir=(1, 0, 0))
Y = gen_pos('Y', default_zdir=(0, 1, 0))
Z = gen_pos('Z', default_zdir=(0, 0, 1))
XX = gen_pos('X', PPos, default_zdir=(1, 0, 0))
YY = gen_pos('Y', PPos, default_zdir=(0, 1, 0))
ZZ = gen_pos('Z', PPos, default_zdir=(0, 0, 1))
O = _gm.Vector(0, 0, 0)

RX = gen_rot('X')
RY = gen_rot('Y')
RZ = gen_rot('Z')

_AMAP = {
    'w': (0, _be.Align.MIN),
    'e': (0, _be.Align.MAX),
    's': (1, _be.Align.MIN),
    'n': (1, _be.Align.MAX),
    'd': (2, _be.Align.MIN),
    'u': (2, _be.Align.MAX),
}


class R:
    X = RY(90)
    Y = RX(-90)


class _A:
    X = _gm.Axis.X
    Y = _gm.Axis.Y
    Z = _gm.Axis.Z

    default = [_be.Align.CENTER, _be.Align.CENTER, _be.Align.CENTER]

    def __getattr__(self, desc):
        result = self.default[:]
        for c in desc:
            p, a = _AMAP[c]
            result[p] = a
        return tuple(result)

A = _A()


def _axis_offset(self, X=0, Y=0, Z=0):
    if isinstance(X, (tuple, _gm.Vector)):
        v = X
    else:
        v = _gm.Vector(X, Y, Z)
    return _gm.Axis(self.position + v, self.direction)


_gm.Vector.perpendicular = lambda self, raxis=_gm.Axis.Z: self.rotate(raxis, 90)
_gm.Vector.rot = lambda self, angle, raxis=_gm.Axis.Z: self.rotate(raxis, angle)
_tp.Mixin1D.at = lambda self, param: self.position_at(param)
_tp.Mixin1D.tat = lambda self, param: self.tangent_at(param)
_tp.Mixin1D.nat = lambda self, param, raxis=_gm.Axis.Z: self.tangent_at(param).perpendicular(raxis)
_gm.Axis.offset = _axis_offset
_tp.Shape.arc_center = property(lambda self: self.edge().arc_center)
_tp.Mixin1D.s = property(lambda self: self.position_at(0))
_tp.Mixin1D.e = property(lambda self: self.position_at(1))

from build123d_draft.utils import *
from build123d_draft.tools import *
from build123d_draft.build_line import *
