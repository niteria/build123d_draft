import os
import pytest

from build123d_draft import export_png


@pytest.fixture(autouse=True)
def render(request):
    yield
    if os.environ.get('RENDER_MODELS', '0') != '0':
        fname = 'assets/' + os.path.basename(request.node.path).rpartition('.')[0] + '_' + request.node.name + '.png'
        os.makedirs(os.path.dirname(fname), exist_ok=True)

        r = request.node.get_closest_marker('rotate')
        loc = None
        if r:
            loc = r.args[0]

        export_png(fname, request.module.slist.objects[-1], bg=(1, 0, 1), transparent=True, loc=loc)
