import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(os.name=='nt','Windows process ownership')
class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('batch_runtime'),'Bounded Windows worker runtime is missing')
        import batch_runtime
        self.runtime=batch_runtime
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_cancel_reaps_worker_descendants(self):
        script=self.root/'child.py'
        script.write_text("import sys,subprocess,time\nfrom pathlib import Path\nassert sys.stdin.readline().strip()=='START'\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(60)\n",encoding='utf8')
        pidfile=self.root/'pid.txt'
        managed=self.runtime.ManagedProcess([sys.executable,str(script),str(pidfile)],self.root/'log.txt')
        self.addCleanup(managed.close)
        deadline=time.monotonic()+10
        while not pidfile.exists() and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(pidfile.exists())
        child=int(pidfile.read_text())
        self.assertTrue(self.runtime.process_alive(child))
        managed.close()
        deadline=time.monotonic()+5
        while self.runtime.process_alive(child) and time.monotonic()<deadline:time.sleep(.05)
        self.assertFalse(self.runtime.process_alive(child),'OCR-like child must not remain orphaned')
        self.assertIsNotNone(managed.process.poll())

    def test_resource_snapshot_reports_physical_ram_and_current_tree_rss(self):
        result=self.runtime.resources(self.root)
        self.assertGreater(result['total_ram'],0)
        self.assertGreater(result['available_ram'],0)
        self.assertGreater(result['batch_rss'],0)
        self.assertGreater(result['free_disk'],0)


if __name__=='__main__':unittest.main()
