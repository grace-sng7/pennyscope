"""Deployment smoke checks without credentials, network, or repository imports."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DeploymentTests(unittest.TestCase):
    def test_exactly_two_services_and_existing_proxy_binding(self):
        config = json.loads((ROOT / 'vercel.json').read_text())
        self.assertEqual(set(config['services']), {'frontend', 'backend'})
        self.assertEqual(config['services']['backend']['entrypoint'], 'main:app')
        binding = config['services']['frontend']['bindings'][0]
        self.assertEqual((binding['service'], binding['env']), ('backend', 'BACKEND_URL'))
        self.assertEqual(config['rewrites'][0]['destination'], {'service': 'frontend'})

    def test_staged_backend_imports_without_repository_or_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = root / 'original_app/backend_reference'
            shutil.copytree(ROOT / 'original_app/backend_reference', service,
                            ignore=shutil.ignore_patterns('__pycache__', 'financial_tools.py'))
            shutil.copyfile(ROOT / 'financial_tools.py', root / 'financial_tools.py')
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith(('AWS_', 'PENNYSCOPE_', 'GEMINI_', 'PYTHONPATH'))}
            subprocess.run([sys.executable, 'prepare_deployment.py'], cwd=service,
                           env=environment, check=True, capture_output=True)
            self.assertEqual((service / 'financial_tools.py').read_bytes(),
                             (root / 'financial_tools.py').read_bytes())
            (root / 'financial_tools.py').unlink()
            subprocess.run([sys.executable, '-c',
                'import main, financial_tools, model_router, factor_registry; '
                'assert main.health() == {"ok": True}; '
                'assert len(factor_registry.REGISTRIES) == 4; '
                'assert {"/extract", "/correct", "/calculate", "/chat-fallback"} '
                '<= {r.path for r in main.app.routes}'],
                cwd=service, env=environment, check=True, capture_output=True)
