"""Exercise the actual Actions shell steps against a local remote and synthetic readiness files."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


WORKFLOW = Path(os.environ.get('CONTRAST_WORKFLOW', '.github/workflows/update-temperature-contrast.yml')).resolve()
ROOT = Path('data/rekordlabor/contrast')


class Backfill(unittest.TestCase):
    def fixture(self, years, first='', last='', fail='', weekday='7', old_years=range(1961,1991), unavailable=(), ancient=range(1901,1961), stale=()):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        work = base / 'work'
        work.mkdir()
        tools = base / 'bin'
        tools.mkdir()
        def git(*args, cwd=work):
            return subprocess.check_output(['git', *args], cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()
        git('init', '--bare', str(base / 'remote.git'), cwd=base)
        git('init', '-b', 'main')
        git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        for mode in ('hourly', 'daily'):
            for year in sorted(set(years) | set(old_years) | {y for y in ancient if mode=='daily' or y>=1951}):
                name = 'unavailable.json' if mode == 'hourly' and year in unavailable else 'ready.json'
                p = work / ROOT / mode / str(year) / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps({'year': year, **({'time_reference':'utc-md-v2'} if mode=='hourly' and year not in stale else {})}))
        git('add', '.')
        git('commit', '--allow-empty', '-m', 'fixture')
        git('remote', 'add', 'origin', str(base / 'remote.git'))
        git('push', 'origin', 'main')
        date = tools / 'date'
        date.write_text('#!/bin/sh\ncase "$*" in *%Y*) echo 2026;; *) echo "$WEEKDAY";; esac\n')
        date.chmod(0o755)
        python = tools / 'python'
        python.write_text(f'#!{sys.executable}\n' + '''import os, sys, json
from pathlib import Path
if 'scripts/build_temperature_contrast.py' not in sys.argv:
    os.execv(sys.executable, [sys.executable] + sys.argv[1:])
def arg(name): return sys.argv[sys.argv.index(name)+1]
mode, first, last = arg('--mode'), int(arg('--first')), int(arg('--last'))
with open(os.environ['CALLS'], 'a') as f:
    f.write(f'{mode} {first} {last}\\n')
if os.environ.get('FAIL') == f'{mode} {first}': sys.exit(42)
for year in range(first,last+1):
    p=Path(arg('--out')) / mode / str(year) / 'ready.json'
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps({'year':year, 'fresh':True, 'time_reference':'utc-md-v2'}))
''')
        python.chmod(0o755)
        env = dict(os.environ, PATH=str(tools)+os.pathsep+os.environ['PATH'], INPUT_FIRST=first, INPUT_LAST=last, CALLS=str(base/'calls'), FAIL=fail, WEEKDAY=weekday)
        steps = yaml.safe_load(WORKFLOW.read_text())['jobs']['archive']['steps']
        result = None
        for step in steps:
            if step.get('name','').startswith(('Compute full station coverage', 'Commit complete annual batches')):
                result = subprocess.run(['bash','-c',step['run']], cwd=work, env=env, text=True, capture_output=True)
                if result.returncode: break
        self.assertIsNotNone(result)
        remote_head = git('rev-parse','origin/main')
        commits = git('rev-list','--count',remote_head)
        published = git('show',f'{remote_head}:{ROOT}/index.json') if int(commits)>1 else '{}'
        return result, (base/'calls').read_text().splitlines() if (base/'calls').exists() else [], int(commits)-1, json.loads(published)

    def test_all_missing_blocks_continue_and_skip_existing_years(self):
        result,calls,commits,index = self.fixture([*range(1991,1996), *range(2001,2025), 2025,2026])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 1996 2000','daily 1996 2000','hourly 2026 2026','daily 2026 2026'])
        self.assertEqual(commits,2)
        self.assertEqual([x['year'] for x in index['hourly']],list(range(1951,2027)))

    def test_multiple_blocks_and_checkpoint_on_failure(self):
        result,calls,commits,index = self.fixture([*range(1991,1996), *range(2006,2027)], fail='daily 2001')
        self.assertEqual(result.returncode,42,result.stderr)
        self.assertEqual(calls,['hourly 1996 2000','daily 1996 2000','hourly 2001 2005','daily 2001 2005'])
        self.assertEqual(commits,1)
        self.assertNotIn(2001,[x['year'] for x in index['hourly']])
        self.assertIn(2000,[x['year'] for x in index['daily']])

    def test_current_archive_fills_every_remaining_block(self):
        result,calls,commits,index = self.fixture([*range(1991,1996),2025,2026])
        self.assertEqual(result.returncode,0,result.stderr)
        expected = ['1996 2000','2001 2005','2006 2010','2011 2015','2016 2020','2021 2024','2026 2026']
        self.assertEqual(calls,[f'{mode} {years}' for years in expected for mode in ('hourly','daily')])
        self.assertEqual(commits,7)
        self.assertEqual([x['year'] for x in index['daily']],list(range(1901,2027)))

    def test_bootstrap_recent_years_only_once(self):
        result,calls,commits,_ = self.fixture(range(1991,2025))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 2025 2026','daily 2025 2026'])
        self.assertEqual(commits,1)

    def test_manual_range_is_preserved(self):
        result,calls,commits,_ = self.fixture([2025,2026],first='2003',last='2004')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 2003 2004','daily 2003 2004'])
        self.assertEqual(commits,1)

    def test_long_manual_range_is_checkpointed_in_five_year_blocks(self):
        result,calls,commits,_ = self.fixture([2025,2026],first='2000',last='2011')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 2000 2004','daily 2000 2004','hourly 2005 2009','daily 2005 2009','hourly 2010 2011','daily 2010 2011'])
        self.assertEqual(commits,3)

    def test_monday_current_refresh_survives_historical_error(self):
        result,calls,commits,_ = self.fixture([*range(1991,1996), *range(2001,2027)], fail='hourly 1996', weekday='1')
        self.assertEqual(result.returncode,42,result.stderr)
        self.assertEqual(calls,['hourly 2026 2026','daily 2026 2026','hourly 1996 2000'])
        self.assertEqual(commits,1)

    def test_complete_archive_refreshes_current_only(self):
        result,calls,commits,_ = self.fixture(range(1991,2027))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 2026 2026','daily 2026 2026'])
        self.assertEqual(commits,1)

    def test_add_historical_years_and_skip_documented_unavailable_hours(self):
        result,calls,commits,index = self.fixture(range(1991,2027),old_years=range(1961,1986),unavailable=(1961,))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 1986 1990','daily 1986 1990','hourly 2026 2026','daily 2026 2026'])
        self.assertEqual(commits,2)
        self.assertEqual([x['year'] for x in index['daily']],list(range(1901,2027)))
        self.assertEqual([x['year'] for x in index['hourly']],[*range(1951,1961),*range(1962,2027)])
        self.assertEqual([x['year'] for x in index['hourlyUnavailable']],[1961])

    def test_manual_old_range_is_accepted(self):
        result,calls,commits,_ = self.fixture([2025,2026],first='1981',last='1985')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(calls,['hourly 1981 1985','daily 1981 1985'])
        self.assertEqual(commits,1)

    def test_pre1951_daily_only_and_old_hourly_reprocessed(self):
        result,calls,commits,index = self.fixture(range(1991,2027),ancient=range(1906,1961),unavailable=(1961,),stale=(1961,))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('daily 1901 1905',calls)
        self.assertNotIn('hourly 1901 1905',calls)
        self.assertIn('hourly 1961 1961',calls)
        self.assertNotIn('daily 1961 1961',calls)
        self.assertEqual(index['daily'][0]['year'],1901)

    def test_stale_unavailable_marker_not_republished_between_batches(self):
        result,calls,commits,index=self.fixture(range(1991,2027),ancient=range(1906,1961),unavailable=(1961,),stale=(1961,),fail='hourly 1961')
        self.assertEqual(result.returncode,42)
        self.assertEqual(index['hourlyUnavailable'],[])


if __name__ == '__main__': unittest.main()
