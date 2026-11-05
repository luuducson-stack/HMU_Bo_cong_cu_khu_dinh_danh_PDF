import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import fitz
import app,engine
from benchmarks import benchmark_real_workflow as bench

class RealBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'Đầu vào.pdf'
        with fitz.open() as doc:
            p=doc.new_page();p.insert_text((30,50),'Ho ten: NGUYEN VAN AN');doc.save(self.source)

    def test_real_benchmark_preserves_source_and_uses_new_jobs(self):
        before=self.source.read_bytes()
        with patch.object(engine,'approve_all_pages',side_effect=AssertionError('no auto-approval')):
            a=bench.run(self.source,self.root/'a');b=bench.run(self.source,self.root/'b')
        self.assertEqual(self.source.read_bytes(),before)
        self.assertNotEqual(a['output'],b['output'])
        self.assertEqual(a['status'],'DRAFT_NEEDS_QC')
        self.assertEqual(a['machine_seconds'],a['ingest_prepare_seconds']+a['export_download_seconds'])

    def test_reference_policy_checked_before_server(self):
        job=self.root/'reference';job.mkdir()
        (job/'review.json').write_text(json.dumps({'source_sha256':engine.sha(self.source),'policy':'old-policy','dpi':200}))
        with patch.object(app,'create_server',side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(ValueError,'policy'):bench.run(self.source,self.root/'run',job)

    def test_reference_dpi_checked_before_server(self):
        job=self.root/'reference';job.mkdir()
        (job/'review.json').write_text(json.dumps({'source_sha256':engine.sha(self.source),'policy':engine.POLICY,'dpi':600}))
        with patch.object(app,'create_server',side_effect=AssertionError('must validate first')):
            with self.assertRaisesRegex(ValueError,'DPI'):bench.run(self.source,self.root/'run',job)

    def test_mask_hash_ignores_identity_but_tracks_manual_masks(self):
        a={'dpi':200,'pages':[{'page':1,'width':300,'height':200,'proposals':[],'manual_rects':[]}],'revision':0,'job_id':'a'}
        b=copy.deepcopy(a);b.update(revision=99,job_id='b')
        self.assertEqual(bench.mask_sha(a),bench.mask_sha(b))
        b['pages'][0]['manual_rects']=[[1,2,3,4]]
        self.assertNotEqual(bench.mask_sha(a),bench.mask_sha(b))
