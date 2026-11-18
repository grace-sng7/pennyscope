"""Stage the canonical calculator inside the independently bundled service.

Run by the backend's Vercel buildCommand, before Python function packaging.
No calculator code is generated or changed.
"""
from pathlib import Path
from shutil import copyfile


def prepare():
    service = Path(__file__).resolve().parent
    source = service.parents[1] / 'financial_tools.py'
    if not source.is_file():
        raise RuntimeError('Build from the repository root: financial_tools.py is missing')
    if not (service / 'routing_prompt.txt').is_file():
        raise RuntimeError('Backend routing_prompt.txt is missing')
    copyfile(source, service / 'financial_tools.py')


if __name__ == '__main__':
    prepare()
