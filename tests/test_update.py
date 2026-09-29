"""Repos Git desechables; sudo, systemd y red simulados, sin tocar servicios reales."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'linux/actualizar.sh'
GIT = shutil.which('git')


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.repo=self.root/'repo'; self.remote=self.root/'remote'
        self.bin=self.root/'bin'; self.bin.mkdir()
        self.env=os.environ.copy()
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='Test',GIT_AUTHOR_EMAIL='test@example.com',
                        GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.com',
                        TEST_LOG=str(self.root/'calls'))
        self.run_git('init','--bare',str(self.remote),cwd=self.root)
        self.run_git('init','-b','azure-telegram',str(self.repo),cwd=self.root)
        (self.repo/'app.py').write_text('x = 1\n')
        (self.repo/'requirements.txt').write_text('')
        (self.repo/'docs').mkdir(); (self.repo/'docs/page').write_text('old')
        self.run_git('add','.'); self.run_git('commit','-m','initial')
        self.run_git('remote','add','origin',str(self.remote)); self.run_git('push','origin','azure-telegram')
        self.before=self.run_git('rev-parse','HEAD').stdout.strip()
        (self.repo/'linux').mkdir()
        # Solo la copia de prueba usa comandos simulados; no hay escape en producción.
        text=SCRIPT.read_text().replace('PATH=/usr/local/bin:/usr/bin:/bin',f'PATH={self.bin}:/usr/bin:/bin')
        text=text.replace('/usr/bin/systemctl',str(self.bin/'systemctl'))
        (self.repo/'linux/actualizar.sh').write_text(text)
        self.exe('id','#!/bin/sh\necho 1000\n')
        self.exe('flock','#!/bin/sh\nexit 0\n')
        self.exe('sleep','#!/bin/sh\nexit 0\n')
        self.exe('systemctl','#!/bin/sh\nexit "${TEST_ACTIVE:-0}"\n')
        self.exe('git',f'''#!/bin/sh
if [ "$1 $2" = "remote get-url" ]; then echo https://github.com/jduquetr/SismoAlert.git; exit 0; fi
if [ "$1" = fetch ] && [ "${{TEST_FETCH_FAIL:-0}}" = 1 ]; then exit 1; fi
exec {GIT} "$@"
''')
        self.exe('sudo','''#!/bin/sh
if [ "$2" = -l ]; then exit "${TEST_SUDO_FAIL:-0}"; fi
echo restart >> "$TEST_LOG"
exit 0
''')
        venv=self.repo/'.venv/bin'; venv.mkdir(parents=True)
        python=venv/'python'; python.write_text(f'''#!/bin/sh
if [ "$#" = 1 ]; then cat >/dev/null; exit "${{TEST_HEALTH_FAIL:-0}}"; fi
exec {sys.executable} "$@"
'''); python.chmod(0o755)

    def exe(self,name,text):
        file=self.bin/name; file.write_text(text); file.chmod(0o755)

    def run_git(self,*args,cwd=None):
        return subprocess.run([GIT,*args],cwd=cwd or self.repo,env=self.env,text=True,capture_output=True,check=True)

    def candidate(self,path='app.py',content='x = 2\n'):
        (self.repo/path).write_text(content)
        self.run_git('add',path); self.run_git('commit','-m','candidate')
        self.target=self.run_git('rev-parse','HEAD').stdout.strip()
        self.run_git('push','origin','azure-telegram')
        self.run_git('reset','--hard',self.before)  # solo el repositorio desechable

    def update(self):
        return subprocess.run(['/bin/sh','linux/actualizar.sh'],cwd=self.repo,env=self.env,text=True,capture_output=True)

    def head(self): return self.run_git('rev-parse','HEAD').stdout.strip()

    def test_fetch_failure_is_nonzero(self):
        self.env['TEST_FETCH_FAIL']='1'
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),self.before)

    def test_wrong_branch_is_refused(self):
        self.run_git('switch','-c','main')
        self.assertNotEqual(self.update().returncode,0)

    def test_dirty_docs_preserved(self):
        self.candidate(); (self.repo/'docs/page').write_text('local')
        self.assertNotEqual(self.update().returncode,0)
        self.assertEqual((self.repo/'docs/page').read_text(),'local'); self.assertEqual(self.head(),self.before)

    def test_dependency_change_requires_operator(self):
        self.candidate('requirements.txt','new-package\n')
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),self.before)

    def test_divergent_history_refused(self):
        self.candidate(); (self.repo/'local').write_text('local')
        self.run_git('add','local'); self.run_git('commit','-m','local'); local=self.head()
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),local)

    def test_invalid_python_refused_before_checkout(self):
        self.candidate(content='invalid syntax !')
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),self.before)

    def test_missing_sudo_refused_before_checkout(self):
        self.candidate(); self.env['TEST_SUDO_FAIL']='1'
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),self.before)

    def test_successful_update(self):
        self.candidate(); result=self.update()
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(self.head(),self.target)
        self.assertEqual((self.root/'calls').read_text().splitlines(),['restart'])

    def test_failed_health_rolls_back(self):
        self.candidate(); self.env['TEST_HEALTH_FAIL']='1'
        self.assertNotEqual(self.update().returncode,0); self.assertEqual(self.head(),self.before)
        self.assertEqual(len((self.root/'calls').read_text().splitlines()),2)

    def test_docs_only_does_not_restart(self):
        self.candidate('docs/page','new')
        self.assertEqual(self.update().returncode,0); self.assertEqual(self.head(),self.target)
        self.assertFalse((self.root/'calls').exists())

    def test_installer_renders_restricted_unit_and_narrow_sudoers(self):
        installer = SCRIPT.with_name('instalar_servicio.sh').read_text()
        installer = installer.replace('PATH=/usr/local/bin:/usr/bin:/bin', f'PATH={self.bin}:/usr/bin:/bin')
        (self.repo/'linux/instalar_servicio.sh').write_text(installer)
        self.exe('id', '#!/bin/sh\nif [ "$1" = -un ]; then echo alice; else echo 1000; fi\n')
        self.env['TEST_ARTIFACTS'] = str(self.root/'artifacts')
        (self.root/'artifacts').mkdir()
        self.exe('sudo', f'''#!/bin/sh
if [ "$1" = test ]; then exit 1; fi
if [ "$1" = install ]; then
  for arg in "$@"; do previous="${{last:-}}"; last="$arg"; done
  cp "$previous" "$TEST_ARTIFACTS/$(basename "$previous")"
fi
exit 0
''')
        result = subprocess.run(['/bin/sh','linux/instalar_servicio.sh'], cwd=self.repo,
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        unit = (self.root/'artifacts/unit').read_text()
        self.assertIn('User=alice', unit)
        self.assertIn('ProtectSystem=strict', unit)
        self.assertIn(f'ReadWritePaths={self.repo.resolve()}/datos', unit)
        sudoers = (self.root/'artifacts/sudoers').read_text()
        self.assertEqual(sudoers.strip(), 'alice ALL=(root) NOPASSWD: /usr/bin/systemctl restart sismoalert.service')
        cron = (self.root/'artifacts/cron').read_text()
        self.assertIn(f'alice /bin/sh {self.repo.resolve()}/linux/actualizar.sh', cron)

    def test_installer_refuses_root_before_sudo(self):
        installer = SCRIPT.with_name('instalar_servicio.sh').read_text()
        installer = installer.replace('PATH=/usr/local/bin:/usr/bin:/bin', f'PATH={self.bin}:/usr/bin:/bin')
        (self.repo/'linux/instalar_servicio.sh').write_text(installer)
        self.exe('id', '#!/bin/sh\necho 0\n')
        result = subprocess.run(['/bin/sh','linux/instalar_servicio.sh'], cwd=self.repo,
                                env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no root', result.stderr)
        self.assertFalse((self.root/'calls').exists())
