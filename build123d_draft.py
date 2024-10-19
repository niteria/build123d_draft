import sys
import functools
from itertools import chain as it_chain
import math
from build123d import *
from build123d import topology
from build123d.build_common import WorkplaneList, Builder, LocationList
from build123d.topology import isclose_b

import OCP
from OCP.Standard import Standard_NoSuchObject
from OCP.BRep import BRep_Tool

b123_mirror = mirror

dpr = math.pi/180
sqr2 = math.sqrt(2)

def gen_pos(name, cls=Pos, default_zdir=None):
    def g(val):
        rv = cls(**{name: val})
        rv.default_zdir = default_zdir
        return rv
    return g

def gen_rot(name):
    def g(val):
        return Rot(**{name: val})
    return g

X = gen_pos('X', default_zdir=(1, 0, 0))
Y = gen_pos('Y', default_zdir=(0, 1, 0))
Z = gen_pos('Z', default_zdir=(0, 0, 1))
O = Vector(0, 0, 0)

RX = gen_rot('X')
RY = gen_rot('Y')
RZ = gen_rot('Z')

_AMAP = {
    'w': (0, Align.MIN),
    'e': (0, Align.MAX),
    's': (1, Align.MIN),
    'n': (1, Align.MAX),
    'd': (2, Align.MIN),
    'u': (2, Align.MAX),
}


class R:
    X = RY(90)
    Y = RX(-90)


class _A:
    X = Axis.X
    Y = Axis.Y
    Z = Axis.Z

    default = [Align.CENTER, Align.CENTER, Align.CENTER]

    def __getattr__(self, desc):
        result = self.default[:]
        for c in desc:
            p, a = _AMAP[c]
            result[p] = a
        return tuple(result)

A = _A()


def fillet_tool(r, length, align):
    return extrude(Rectangle(r*2, r*2) - Circle(r, align=align), length)


def ext_point_with_circle_intersection(p, c):
    Edge.make_circle()
    l = Line([c.center(), p])
    cc = Pos(l @ 0.5) * Circle(l.length / 2)
    return (c & cc).vertices()


def plane_along(axis, raxis=Axis.Z):
    return Axis(axis.position, axis.direction.rotate(raxis, 90)).to_plane()


def point_on_axis_with_dist(start, axis, dist, raxis=Axis.Z):
    vp = start.project_to_plane(plane_along(axis, raxis))
    d1 = abs(vp - start)
    d2 = (dist*dist - d1*d1)**0.5
    return vp + axis.direction * d2


def make_axis(start, end=None):
    if isinstance(start, Wire):
        start, end = start @ 0, start @ 1
    elif isinstance(start, Plane):
        return Axis(start.origin, start.z_dir)
    return Axis(start, end - start)


def overshoot_line(p1, p2, start=0, end=0):
    d = (p2 - p1).normalized()
    return Line(p1 - d * start, p2 + d * end)


def intersections(shape, other, tolerance=0):
    r = []
    for e in shape.edges():
        # print('### X', e.center(), other)
        r.extend(e.find_intersection_points(other, tolerance=tolerance))
    return ShapeList(r)


def intersection(*args, sort_by=Axis.Y, idx=-1, **kwargs):
    r = intersections(*args, **kwargs)
    return r.sort_by(sort_by)[idx]


def _axis_offset(self, X=0, Y=0, Z=0):
    if isinstance(X, (tuple, Vector)):
        v = X
    else:
        v = Vector(X, Y, Z)
    return Axis(self.position + v, self.direction)


Vector.perpendicular = lambda self, raxis=Axis.Z: self.rotate(raxis, 90)
Vector.rot = lambda self, angle, raxis=Axis.Z: self.rotate(raxis, angle)
topology.Mixin1D.at = lambda self, param: self.position_at(param)
topology.Mixin1D.tat = lambda self, param: self.tangent_at(param)
topology.Mixin1D.nat = lambda self, param, raxis=Axis.Z: self.tangent_at(param).perpendicular(raxis)
Axis.offset = _axis_offset
topology.Shape.arc_center = property(lambda self: self.edge().arc_center)
topology.Mixin1D.s = property(lambda self: self.position_at(0))
topology.Mixin1D.e = property(lambda self: self.position_at(1))


class PPos(Pos):
    def __init__(self, X=None, Y=None, Z=None):
        self._initial = (X, Y, Z)

    def combine_abs(self, v):
        if v is None:
            v = Vector(0, 0, 0)

        r = [0, 0, 0]
        for idx, (iv, vv) in enumerate(zip(self._initial, v.to_tuple())):
            r[idx] = iv if iv is not None else vv

        return Vector(*r)


XX = gen_pos('X', PPos, default_zdir=(1, 0, 0))
YY = gen_pos('Y', PPos, default_zdir=(0, 1, 0))
ZZ = gen_pos('Z', PPos, default_zdir=(0, 0, 1))


class build_line:
    def __init__(self, start=None, plane=Plane.XY, tangent=None):
        # TODO: use context to get current plane
        if isinstance(start, Plane):
            start, plane = None, start
        self.plane = plane
        self._shapes = []
        self._named = {}
        if start is None:
            self._start_point = plane.origin
        else:
            self._start_point = self.to_vector(start, plane.origin)

        if tangent is None:
            self._start_tangent = plane.x_dir
        else:
            self._start_tangent = self.to_direction(tangent)

        self._builder = FakeBuilder(plane)

    def to_vector(self, v, ref=None):
        if isinstance(v, Pos):
            if ref is None:
                ref = self.e
            ref = ref.transform(self.plane.forward_transform)
            if isinstance(v, PPos):
                rv = v.combine_abs(ref)
            else:
                rv = v.position + ref
            return rv.transform(self.plane.reverse_transform)
        if isinstance(v, Axis):
            return v.position.transform(self.plane.reverse_transform)
        elif isinstance(v, tuple):
            return Vector(*v).transform(self.plane.reverse_transform)

        return v

    def to_direction(self, v):
        if isinstance(v, Pos):
            v = v.position.to_tuple()

        if isinstance(v, Vector):
            return v
        elif isinstance(v, Axis):
            return v.located(self.plane.location).direction
        elif isinstance(v, tuple):
            origin = self.to_vector((0, 0, 0))
            return self.to_vector(v) - origin

        assert False, f'Unsupported type {type(v)}'

    def apply(self, op):
        if isinstance(op, (Vector, Pos, tuple)):
            v = self.to_vector(op)
            self._shapes.append(Line(self.e, v))
        elif isinstance(op, topology.Shape):
            self._shapes.append(op)
        else:
            s = op.fn(self, *op.args, **op.kwargs)
            if op.name:
                s._lb_name = op.name
                self._named[op.name] = s
            if op.reverse:
                chains = self.chains()
                for it in chains[-1]:
                    it.wrapped.Reverse()
                rv = list(it_chain.from_iterable(chains[:-1]))
                # rv.extend(reversed_wire(it) for it in reversed(chains[-1]))
                rv.extend(reversed(chains[-1]))
                self._shapes = rv
            if op.connect:
                chains = self.chains()
                if len(chains) > 1:
                    rv = list(it_chain.from_iterable(chains[:-1]))
                    rv.append(Line(rv[-1].e, chains[-1][0].s))
                    rv.extend(chains[-1])
                    self._shapes = rv

    def append(self, *ops):
        for op in ops:
            self.apply(op)
        return self

    @property
    def e(self):
        if self._shapes:
            return self._shapes[-1] @ 1
        else:
            return self._start_point

    @property
    def s(self):
        return self._shapes[0] @ 0

    @property
    def ss(self):
        return self._shapes[0] @ 1

    @property
    def ee(self):
        return self._shapes[-1] @ 0

    def wire(self):
        if len(self._shapes) == 1:
            return self._shapes[0]
        return self._shapes[0] + self._shapes[1:]

    def edges(self) -> topology.ShapeList[Edge]:
        return topology.ShapeList([
            e for shape in self._shapes for e in shape.edges()])

    def face(self):
        return make_face(self.wire())

    def tangent(self, shape_idx=-1, param=1):
        if self._shapes:
            return self._shapes[shape_idx].tangent_at(param)
        return self._start_tangent

    def normal(self, shape_idx=-1, param=1):
        if self._shapes:
            t = self._shapes[shape_idx].tangent_at(param)
        else:
            t = self._start_tangent
        return t.rotate(make_axis(self.plane), 90)

    def normal_loc(self, shape_idx=-1, param=1, tangent=1):
        p = self._shapes[shape_idx] @ param
        t = tangent * self.tangent(shape_idx, param)
        n = t.rotate(make_axis(self.plane), 90)
        return Location(Plane(p, x_dir=t, z_dir=n))

    def to_normal_plane(self, axis, start=None):
        if isinstance(axis, Pos):
            z_dir = getattr(axis, 'default_zdir', None)
            if z_dir is None:
                raise Exception('Position should have a default Z direction')
            return Plane(self.to_vector(axis, start), z_dir=self.to_direction(z_dir))
        else:
            gaxis = axis.located(self.plane.location)
            n = gaxis.direction.rotate(
                Axis(self.plane.origin, self.plane.z_dir), 90)
            return Plane(gaxis.position, z_dir=n)

    def add_shape(self, shape):
        self._shapes.append(shape)
        return shape

    def move(self, loc):
        if isinstance(loc, (tuple, Vector)):
            loc = Pos(loc)
        old = self._shapes
        self._shapes = [loc * it for it in self._shapes]

        for o, n in zip(old, self._shapes):
            if hasattr(o, '_lb_name'):
                self._named[o._lb_name] = n

    def __getitem__(self, idx):
        if idx in self._named:
            return self._named[idx]
        return self._shapes[idx]

    __getattr__ = __getitem__

    def revolvex(self):
        return revolve(self.face(), Axis.X)

    def revolvey(self):
        return revolve(self.face(), Axis.Y)

    def revolvez(self):
        return revolve(self.face(), Axis.Z)

    def sweep(self, face):
        return sweep(Plane(self.s, z_dir=self.tangent(0, 0)) * face, self.wire())

    def extrude(self, amount, both=False, z_dir=True):
        dir = self.plane.z_dir if z_dir else None
        return extrude(self.face(), amount, both=both, dir=dir)

    def chains(self):
        if not self._shapes:
            return []

        rv = [c := [self._shapes[0]]]
        for s in self._shapes[1:]:
            if c[-1].e != s.s:
                c = [s]
                rv.append(c)
            else:
                c.append(s)

        return rv


class op_data_holder:
    def __init__(self, fn, name, reverse, connect, args, kwargs):
        self.fn = fn
        self.name = name
        self.reverse = reverse
        self.connect = connect
        self.args = args
        self.kwargs = kwargs


def build_line_op(fn):
    def inner(*args, **kwargs):
        name = kwargs.pop('name', None)
        reverse = kwargs.pop('reverse', False)
        connect = kwargs.pop('connect', False)
        fn(None, *args, **kwargs)
        return op_data_holder(fn, name, reverse, connect, args, kwargs)
    return inner


def _defined(*args):
    return any(it is not None for it in args)


def _defined_all(*args):
    return all(it is not None for it in args)


@build_line_op
def op_line(lb, length=None, angle=None, dir=None, start=None, to=None,
            until=None, tangent=None):
    if lb is None:
        assert _defined(to, length, until)
        return

    reset_tangent = False
    if start is None:
        start = lb.e
    else:
        reset_tangent = True
        start = lb.to_vector(start)

    if to is not None:
        return lb.add_shape(Line(start, lb.to_vector(to, start)))

    if dir is None:
        if tangent is None:
            if reset_tangent:
                tangent = lb.plane.x_dir
            else:
                tangent = lb.tangent()
        else:
            tangent = lb.to_direction(tangent)
        dir = tangent.rot(angle or 0, make_axis(lb.plane))

    if length is not None:
        return lb.add_shape(Line(start, start + dir * length))

    return lb.add_shape(_until_helper(lb, start, dir, until))


def _until_helper(lb, start, dir, until):
    if isinstance(until, Pos):
        until = lb.to_normal_plane(until, start)

    if isinstance(until, (Axis, Plane)):
        to = Axis(start, dir).intersect(until)
        return Line(start, to)

    return IntersectingLine(start, dir, until)


@build_line_op
def op_extend(lb, start=None, end=None):
    if lb is None:
        return

    l = lb._shapes.pop()
    segments = [l]
    if start is not None:
        if isinstance(start, (int, float)):
            nl = Line(l @ 0 - l.tangent_at(0) * start, l @ 0)
        else:
            nl = _until_helper(lb, l @ 0, l.tangent_at(0), start)
            nl.wrapped.Reverse()
        segments = [nl, *segments]

    if end is not None:
        if isinstance(end, (int, float)):
            nl = Line(l @ 1, l @ 1 + l.tangent_at(1) * end)
        else:
            nl = _until_helper(lb, l @ 1, l.tangent_at(1), end)
        segments = [*segments, nl]

    lb._shapes.extend(segments)
    return l


@build_line_op
def op_arc(lb, radius=None, size=None, to=None, tangent=True,
           short=True, center=None, start_angle=None, start=None):
    if lb is None:
        return

    if start is None:
        e = lb.e
    else:
        e = lb.to_vector(start)

    if tangent is True:
        tangent = lb.tangent()
    elif tangent is not None and tangent is not False:
        tangent = lb.to_direction(tangent)

    with lb._builder:
        if _defined_all(radius, size) and center is None:
            ax = make_axis(lb.plane)
            n = tangent.rotate(ax, math.copysign(90, size))
            c = e + n.normalized() * radius
            ep = c + (e - c).rotate(ax, size)
            return lb.add_shape(BaseLineObject(Edge.make_tangent_arc(e, tangent, ep)))
        elif _defined(to) and tangent:
            return lb.add_shape(TangentArc(e, lb.to_vector(to), tangent=tangent))
        elif _defined_all(to, radius) and not tangent:
            return lb.add_shape(RadiusArc(e, lb.to_vector(to), radius, short_sagitta=short))
        elif _defined_all(center, radius):
            start_angle = start_angle or 0
            if center is True:
                center = lb.e
            else:
                center = lb.to_vector(center)
            return lb.add_shape(CenterArc(center, radius, start_angle, size))
    assert False


@build_line_op
def op_ellipse_arc(lb, r1, r2, start, end):
    if lb is None:
        return

    edge = Edge.make_ellipse(r1, r2, lb.plane, start, end)
    s = BaseLineObject(edge)
    return lb.add_shape(Pos(lb.e - s @ 0) * s)


@build_line_op
def op_drop(lb, idx=0):
    if not lb:
        return

    lb._shapes.pop(idx)


@build_line_op
def op_close(lb, both=None, end=None, start=None, mirror=None):
    if not lb:
        return

    if both:
        start = end = both

    if mirror is not None:
        start = end = mirror

    if isinstance(start, (Axis, Pos)):
        start = lb.to_normal_plane(start)

    if isinstance(end, (Axis, Pos)):
        end = lb.to_normal_plane(end)

    if end is not None:
        p = lb.e.project_to_plane(end)
        if p not in (lb.e, lb.s):
            lb.add_shape(Line(lb.e, p))

    if start is not None:
        p = lb.s.project_to_plane(start)
        if p not in (lb.e, lb.s):
            lb._shapes = [Line(p, lb.s), *lb._shapes]

    if mirror is not None:
        return lb.add_shape(b123_mirror(lb.wire(), start))

    return lb.add_shape(Line(lb.e, lb.s))


@build_line_op
def op_trim(lb, point, sort_by=Axis.Y, idx=-1, add=False):
    if not lb:
        return
    s = lb._shapes[-1]
    other = None
    if isinstance(point, by_tangent):
        rv, other = point.trim(lb)
    else:
        if isinstance(point, Axis):
            ax = point.located(lb.plane.location)
            point = intersection(s, ax, sort_by=sort_by, idx=idx)
            other = Line(point, ax.position)
        param = param_on_point(s, point)
        rv = lb._shapes[-1] = trim_wire(s, end=param)

    if other is not None and add:
        lb.add_shape(other)

    return rv


@build_line_op
def op_move(lb, start=None, end=None):
    if not lb:
        return

    targets = lb.chains()[-1]
    if start is not None:
        start = lb.to_vector(start)
        pos = Pos(start - targets[0].s)
    elif end is not None:
        end = lb.to_vector(end)
        pos = Pos(end - targets[-1].e)

    for it in targets:
        it.move(pos)


class by_tangent:
    def __init__(self, obj, sort_by=Axis.Y, idx=-1):
        self.obj = obj
        self.sort_by = sort_by
        self.idx = idx

    def trim(self, lb):
        s = lb._shapes[-1]
        cl = Line(s.edge().arc_center, self.point)
        cc = Pos(cl @ 0.5) * Edge.make_circle(cl.length/2)
        ip = intersection(s, cc, sort_by=self.sort_by, idx=self.idx)
        param = param_on_point(s, ip)
        rv = lb._shapes[-1] = trim_wire(s, end=param)
        return rv, Line(rv @ 1, lb.to_vector(self.obj))


@build_line_op
def op_fillet(lb, radius, count=1):
    if not lb:
        return
    fpoints = [lb._shapes[-i-1] @ 0 for i in range(count)]
    sidx = len(lb._shapes) - 1 - count
    spoint = lb._shapes[sidx] @ 0
    fused = lb._shapes[sidx].fuse(*lb._shapes[sidx+1:])
    w = Wire(fused.edges())
    fobj = fillet([v for v in w.vertices() if Vector(v) in fpoints], radius)
    if fobj @ 0 != spoint:
        fobj.wrapped.Reverse()
    lb._shapes[sidx:] = [fobj]
    return fobj


@build_line_op
def op_chamfer(lb, length, count=1, length2=None, angle=None):
    if not lb:
        return
    fpoints = [lb._shapes[-i-1] @ 0 for i in range(count)]
    sidx = len(lb._shapes) - 1 - count
    spoint = lb._shapes[sidx] @ 0
    fused = lb._shapes[sidx].fuse(*lb._shapes[sidx+1:])
    w = Wire(fused.edges())
    fobj = chamfer([v for v in w.vertices() if Vector(v) in fpoints], length=length, length2=length2, angle=angle)
    if fobj @ 0 != spoint:
        fobj.wrapped.Reverse()
    lb._shapes[sidx:] = [fobj]
    return fobj


def cbore(r1, depth1, r2, total_depth):
    return extrude(Circle(r1), -depth1) + Pos(Z=-depth1) * extrude(Circle(r2), depth1-total_depth)


def cbore_d(d1, depth1, d2, total_depth):
    return cbore(d1/2, depth1, d2/2, total_depth)


def mirror_add(obj, about=Plane.XZ):
    return obj + mirror(obj, about)


def aligned(obj, align):
    align = topology.tuplify(align, 2)
    return obj.moved(Location(Vector(*obj.bounding_box().to_align_offset(align))))


def new_edges_add(*parts):
    # c = parts[0].fuse(*parts[1:])
    # c.clean()
    c = parts[0] + parts[1:]
    # print(c.show_topology())
    return c, new_edges(*parts, combined=c)


class FakeBuilder(Builder):
    def _add_to_pending(self, *objects, face_plane = None):
        return NotImplementedError  # pragma: no cover

    @property
    def _obj(self):
        raise NotImplementedError  # pragma: no cover

    def validate_inputs(self, validating_class, objects = None):
        pass


class ShowList:
    def __init__(self):
        self.objects = []
        self.names = []
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


Cylinder_orig = Cylinder
Circle_orig = Circle


class Cylinder(Cylinder_orig):
    def __init__(
        self,
        radius: float,
        height: float | None = None,
        arc_size: float = 360,
        rotation: RotationLike = (0, 0, 0),
        align: Align | tuple[Align, Align, Align] = (
            Align.CENTER,
            Align.CENTER,
            Align.CENTER,
        ),
        mode: Mode = Mode.ADD,
        d: float | None = None,
        r: float | None = None,
    ):
        if d is not None:
            height = radius
            radius = d/2
        elif r is not None:
            height = radius
            radius = r
        super().__init__(radius, height, arc_size, rotation, align, mode)

    def new(self, radius=None, height=None, d=None, r=None):
        if d is not None:
            if radius is not None:
                height = radius
            radius = d/2
        elif r is not None:
            if radius is not None:
                height = radius
            radius = r
        if height is None:
            height = self.cylinder_height
        return self.location * Cylinder(radius, height, align=self.align)


class Circle(Circle_orig):
    def __init__(
        self,
        radius: float | None = None,
        align: Align | tuple[Align, Align] = (Align.CENTER, Align.CENTER),
        mode: Mode = Mode.ADD,
        d: float | None = None,
    ):
        if d is not None:
            radius = d/2
        super().__init__(radius, align, mode)

    def cylinder(self, height, d=None, r=None, align=Align.MIN):
        radius = self.radius
        if d is not None:
            radius = d/2
        elif r is not None:
            radius = r
        align = self.align[0], self.align[1], topology.tuplify(align, 3)[2]
        return self.location * Cylinder(radius, height, align=align)


def set_current(fn):
    set_current.fn = fn
    return fn


def force_fillet(part, edges, radius):
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    native_edges = [e.wrapped for e in edges]
    fillet_builder = BRepFilletAPI_MakeFillet(part.wrapped)
    for native_edge in native_edges:
        fillet_builder.Add(radius, native_edge)
    return Part(fillet_builder.Shape())


def make_slot(length=None, center=True, end=None, start=O, r=None, h=None,
              d=None, rotation=None, align=None, both=False, half=False):
    sw = None
    if r is not None:
        sw = r*2
    elif d is not None:
        sw = d
    assert sw, 'slot width required, use r or d arguments'

    if isinstance(length, tuple):
        if center:
            start, center = length
        else:
            start, end = length

    if isinstance(start, (int, float)):
        start = Vector(start, 0, 0)

    if center is None or center is False:
        assert _defined(length)
        center = start + Vector(length/2-sw/2)
    elif end is not None:
        if isinstance(end, (int, float)):
            end = Vector(end)
        center = start + end - Vector(sw/2)
    elif center is True:
        assert _defined(length)
        center = start + Vector(length/2)
    else:
        if isinstance(center, (int, float)):
            center = Vector(center, 0, 0)

    sk = SlotCenterPoint(start, center, sw, rotation=rotation)
    if align:
        sk = aligned(sk, align)

    if h is None:
        rv = sk
        center_locs = LocationList(
            [Pos(center), Pos(start - (center - start))])
    else:
        rv = extrude(sk, h, both=both)
        z = h/2 + abs(h/2)
        center_locs = LocationList(
            [Pos(center, Z=z), Pos(start - (center - start), Z=z)])

    if half:
        z_dir = (center - start).normalized()
        x_dir = z_dir.rot(90, Axis.Z)
        rv = split(rv, Plane(start, x_dir=x_dir, z_dir=z_dir))

    rv.center_locs = center_locs
    return rv


make_hslot = functools.partial(make_slot, half=True)


def reversed_wire(wire):
    elist = []
    for e in wire.edges():
        elist.append(e.reversed())
    return Wire(reversed(elist))


def edge_curve(edge):
    p1, p2 = BRep_Tool.Range_s(edge.wrapped)
    c = BRep_Tool.Curve_s(edge.wrapped, p1, p2)
    return c, (p1, p2)


def param_on_point(wire, point, normalized=True):
    is_reversed = wire.wrapped.Orientation() == OCP.TopAbs.TopAbs_Orientation.TopAbs_REVERSED
    edges = wire.edges()
    si = 0
    if is_reversed:
        edges = reversed(edges)
        si = 1

    U = 0
    candidates = []
    pt = Vector(point).to_pnt()
    for e in edges:
        c, pr = edge_curve(e)
        poc = OCP.GeomAPI.GeomAPI_ProjectPointOnCurve(pt, c)
        p = poc.LowerDistanceParameter()
        if pr[0] <= p <= pr[1]:
            candidates.append((poc.LowerDistance(), U + abs(pr[si] - p)))
        U += abs(pr[0] - pr[1])

    if not candidates:
        return None

    candidates.sort()
    u = candidates[0][1]
    if normalized:
        return u / U
    return u


def trim_wire(wire, start=0, end=1):
    is_reversed = wire.wrapped.Orientation() == OCP.TopAbs.TopAbs_Orientation.TopAbs_REVERSED

    edges = wire.edges()
    if is_reversed:
        edges.reverse()

    curves = [(it, edge_curve(it)) for it in edges]
    U = sum(abs(pr[0] - pr[1]) for _, (_, pr) in curves)
    start *= U
    end *= U

    nedges = []
    u2 = 0
    for e, (c, pr) in curves:
        u1 = u2
        u2 = (u1 + abs(pr[0] - pr[1]))
        if u2 < start or u1 > end:
            continue

        t1, t2 = pr
        if u1 <= start <= u2:
            d = start - u1
            if is_reversed:
                t2 -= d
            else:
                t1 += d

        if u1 <= end <= u2:
            d = u2 - end
            if is_reversed:
                t1 += d
            else:
                t2 -= d

        if isclose_b(t1, pr[0]) and isclose_b(t2, pr[1]):
            nedges.append(e.wrapped)
            continue

        if isclose_b(t1, t2):
            continue

        tc = OCP.Geom.Geom_TrimmedCurve(c, t1, t2)
        nedges.append(OCP.BRepBuilderAPI.BRepBuilderAPI_MakeEdge(tc).Edge())

    assert nedges

    if is_reversed:
        nedges.reverse()

    rv = Wire([Edge(it) for it in nedges])

    if is_reversed:
        rv.wrapped.Reverse()

    return rv


def ocp_color(r, g, b):
    return OCP.Quantity.Quantity_Color(r, g, b, OCP.Quantity.Quantity_TypeOfColor.Quantity_TOC_RGB)


@functools.lru_cache(1)
def render_context(size, bg):
    disp = OCP.Aspect.Aspect_DisplayConnection()
    gl = OCP.OpenGl.OpenGl_GraphicDriver(disp, True)
    gl.ChangeOptions().swapInterval = 0
    viewer = OCP.V3d.V3d_Viewer(gl)
    ctx = OCP.AIS.AIS_InteractiveContext(viewer)
    viewer.SetDefaultLights()
    viewer.SetLightOn()

    window = OCP.Xw.Xw_Window(disp, "some", 64, 64, *size)
    window.SetVirtual(True)
    view = OCP.V3d.V3d_View(viewer)
    view.SetWindow(window)
    # view.SetShadingModel(OCP.Graphic3d.Graphic3d_TypeOfShadingModel_Pbr)

    if bg:
        view.SetBackgroundColor(ocp_color(*bg))

    return view, ctx


def export_png(fname, part, size=(720, 480), bg=None, transparent=True, loc=None):
    # scale = 2.0
    # rparams = view.ChangeRenderingParams()
    # rparams.Resolution = int(96.0 * scale + 0.5)
    # rparams.NbMsaaSamples = 4 # MSAA
    # rparams.RenderResolutionScale = scale # SSAA as alternative to MSAA
    rsize = size[0]*2, size[1]*2
    view, ctx = render_context(rsize, bg)
    ctx.RemoveAll(False)
    view.Reset(False)

    # color = ocp_color(0.1, 0.7, 0.3)
    color = ocp_color(0.9, 0.8, 0.23)
    drawer = ctx.DefaultDrawer()
    mname = OCP.Graphic3d.Graphic3d_NameOfMaterial_Steel
    m = OCP.Graphic3d.Graphic3d_MaterialAspect(mname)
    # pbr = OCP.Graphic3d.Graphic3d_PBRMaterial()
    # pbr.SetColor(ocp_color(0.3, 0.3, 0.3))
    # pbr.SetMetallic(1)
    # pbr.SetRoughness(0.5)
    # pbr.SetAlpha(0.9)
    # m.SetPBRMaterial(pbr)
    drawer.ShadingAspect().SetMaterial(m);
    drawer.SetFaceBoundaryDraw(True)
    drawer.ShadingAspect().SetColor(color)

    if loc:
        part = RZ(loc[0]) * part

    prs = OCP.AIS.AIS_Shape(part.wrapped)
    ctx.Display(prs, OCP.AIS.AIS_Shaded, -1, False)

    view.SetProj(OCP.V3d.V3d_TypeOfOrientation_Zup_AxoRight)

    if loc:
        view.Turn(0, loc[1]*dpr, 0)
    view.FitAll(0.01, False)

    image = OCP.Image.Image_AlienPixMap()
    view.ToPixMap(image, *rsize)
    image.Save(OCP.TCollection.TCollection_AsciiString(fname))

    if transparent:
        from PIL import Image
        import numpy as np

        img = Image.open(fname).convert('RGBA')
        d = np.array(img)
        key_color = tuple(int(it*255) for it in bg) + (255,)
        d[(d == key_color).all(axis=-1)] = [0, 0, 0, 0]
        out = Image.fromarray(d, mode='RGBA')
        out = out.resize(size)
        out.save(fname)
