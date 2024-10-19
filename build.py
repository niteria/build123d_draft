import inspect
import os
import pathlib
import runpy


def collect_model(parent, fn):
    img = parent + '_' + fn.__name__ + '.png'
    return {'source': inspect.getsource(fn), 'img': img, 'title': fn.__name__}


def collect_models(module_path):
    m = runpy.run_path(module_path)
    section = {'models': []}
    section['title'] = module_path.stem

    for k, v in m.items():
        if k.startswith('test_'):
            section['models'].append(collect_model(module_path.stem, v))
    return section


def main():
    sections = []
    for p in pathlib.Path('.').glob('tests/models/test_*.py'):
        sections.append(collect_models(p))

    content = []
    for s in sections:
        if not s['models']:
            continue
        content.append(f'## {s["title"]}\n')
        for m in s['models']:
            content.append(f'### {m["title"]}\n')
            content.append(f'![](./assets/{m["img"]})\n')
            # content.append(f'<img src="./assets/{m["img"]}" height="480px" />')
            content.append("```python")
            content.append(m['source'])
            content.append("```\n\n")

    with open('README.md', 'w') as f:
        f.write('\n'.join(content))


if __name__ == '__main__':
    main()
