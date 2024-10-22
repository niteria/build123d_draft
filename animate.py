import io
import textwrap
import ast

from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters.img import ImageFormatter
from PIL import Image

from tests.models import test_ttt_random
from build import clean_source

from build123d import Shape, Plane
from build123d_draft import build_line
from build123d_draft.render import ImageExporter

lex = PythonLexer()


def get_name(node):
    if hasattr(node, 'target'):
        return node.target.id
    elif hasattr(node, 'targets'):
        tt = node.targets
        if len(tt) == 1:
            return tt[0].id


def render_text(source, lines=None):
    fmt = ImageFormatter(style='friendly', font_size=22, image_pad=20,
                         font_name='Input Mono Condensed', line_numbers=False)
    fmt.hl_lines = lines
    return Image.open(io.BytesIO(highlight(source, lex, fmt)))


def animate(fname, fn, aspect=1.2):
    dclip = -Plane.XZ
    source = clean_source(fn)
    tree = ast.parse(source)

    init_img = render_text(source)
    rsize = int(init_img.size[1]*aspect), init_img.size[1]

    ctx = {}
    i_src = textwrap.dedent('''\n
        from build123d import *
        from build123d_draft import *
    ''')
    exec(i_src, ctx, ctx)

    ie = ImageExporter(rsize, bg=(1, 1, 1), transparent=False)
    exec(source, ctx, ctx)
    ie.show(ctx['part'])
    ie.setup_view(rotz=30)

    del ctx['part']

    slides = []
    def render():
        ie.clear(False)
        part = ctx.get('part')
        if part is not None and part is not obj:
            ie.show(part, clip=dclip, hscale=0.02, hatch=False, alpha=0.8, edges=False, clip_outline=False)

        ie.show(obj, clip=clip, hscale=0.02, line_width=line_width)

        r_img = ie.export()
        out = Image.new('RGBA', (rsize[0] + s_img.size[0], rsize[1]))
        out.paste(im=s_img, box=(0, 0))
        out.paste(im=r_img, box=(s_img.size[0], 0))
        slides.append(out)

    for s in tree.body:
        s_src = ast.get_source_segment(source, s, padded=True)

        fmt = ImageFormatter(style='friendly', font_size=22)
        s_img = render_text(source, range(s.lineno, s.end_lineno+1))

        exec(s_src, ctx, ctx)
        name = get_name(s)
        if name:
            obj = ctx[name]
            if isinstance(obj, build_line):
                obj = obj.wire()
                clip = None
                obj.color = (0.3, 0.3, 1)
                line_width = 5
            elif isinstance(obj, Shape):
                clip = dclip
                color = None
                line_width = None
            else:
                obj = None

            if obj is not None:
                render()

    if obj and clip:
        clip = None
        s_img = init_img
        render()

    if slides:
        slides[0].save(fname, save_all=True, append_images=slides[1:], duration=2000, loop=0)


if __name__ == '__main__':
    animate('resources/animation.gif', test_ttt_random.test_24WC_12_tube_plug)
