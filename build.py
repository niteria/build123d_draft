import inspect
import os
import pathlib
import runpy
import textwrap


def collect_model(parent, fn):
    img = parent + '_' + fn.__name__ + '.png'
    slines, _ = inspect.getsourcelines(fn)
    body = inspect.getdoc(fn)
    if body:
        start = [i for i, l in enumerate(slines) if l.strip().startswith('"""')][-1] + 1
    else:
        start = next(i for i, l in enumerate(slines) if l.startswith('def ')) + 1
    end = next(i for i, l in enumerate(slines) if l.strip().startswith('assert '))
    src = ''.join(slines[start:end])
    src = textwrap.dedent(src)
    return {'source': src, 'img': img, 'title': fn.__name__, 'body': body}


def collect_models(module_path):
    m = runpy.run_path(module_path)
    section = {'models': [], 'body': m.get('__doc__')}
    section['title'] = module_path.stem
    section['id'] = module_path.stem

    for k, v in m.items():
        if k.startswith('test_'):
            section['models'].append(collect_model(module_path.stem, v))

    return section


def main():
    sections = []
    for p in pathlib.Path('.').glob('tests/models/test_*.py'):
        sections.append(collect_models(p))

    content = [open('README.header.md').read() + '\n']
    toc = []
    for s in sections:
        if not s['models']:
            continue
        content.append(f'<a name="{s['id']}"></a>')
        if s['body']:
            content.append(s['body'] + '\n')
            title = s['body'].strip().splitlines()[0].lstrip('#').strip()
        else:
            title = s["title"]
            content.append(f'## {s["title"]}\n')
        toc.append(f'* [{title}](#{s['id']})')

        for m in s['models']:
            content.append(f'### {m["title"]}\n')
            if m['body']:
                content.append(m['body'] + '\n')
            content.append(f'![](./assets/{m["img"]})\n')
            # content.append(f'<img src="./assets/{m["img"]}" height="480px" />')
            content.append("```python")
            content.append(m['source'])
            content.append("```\n\n")

    content.insert(1, '\n'.join(toc) + '\n\n')

    with open('README.md', 'w') as f:
        f.write('\n'.join(content))


if __name__ == '__main__':
    main()
