# repl-client
import sys
sys.modules.pop('build123d_draft', None)

from build123d import *
from build123d_draft import *
from pytest import approx


LBF = 25.4**3 / 1000 / 0.45359237
densa = 1020e-6
densb = 2700e-6
densc = 7800e-6

slist = ShowList()
sadd = slist.append


@set_current
@slist
def _test_model1():
    l = build_line(Plane.XZ).append(
        YY(55), X(20), YY(9), XX(155), Y(-9),
        op_arc(560, to=(0, 0), tangent=False)
    )

    base = l.extrude(-60)
    base -= Pos(20, 30, 55-20) * R.X * cbore_d(34, 6, 26, 20)
    base -= Pos(155-40, 20, 9) * cbore(10, 5, 15, 20)
    base -= Pos(155-40-60, 20, 9) * cbore(10, 5, 15, 20)

    l = build_line(Plane.XZ.offset(-60)).append(
        YY(55-10), X(20+15), Y(10), (155, 9), op_close()
    )

    part = base + l.extrude(7)
    return part


if __name__ == '__main__':
    from yacv_server import show

    set_current.fn()
    sadd(origin=Sphere(slist.origin_radius()))
    show(*slist.objects, names=slist.names)
    # export_gltf(slist.objects[-1], '/tmp/output.glb', binary=True)
