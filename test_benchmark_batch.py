import unittest
from benchmarks.benchmark_batch import summarize

class BatchMetricTests(unittest.TestCase):
    def test_throughput_counts_unique_verified_files_not_attempts_or_warnings(self):
        rows=[dict(source_sha256='a',state='NEEDS_REVIEW',result={'machine_seconds':30,'verification':{'status':'PASS'}}),
              dict(source_sha256='a',state='DUPLICATE',result={}),
              dict(source_sha256='b',state='NEEDS_REVIEW',result={'machine_seconds':50,'verification':{'status':'NEEDS_REVIEW'}}),
              dict(source_sha256='c',state='FAILED',result={})]
        report=summarize(rows,120)
        self.assertEqual(report['machine_clear_files'],1)
        self.assertEqual(report['machine_clear_files_per_hour'],30)
        self.assertEqual(report['exported_files'],2)
        self.assertEqual(report['ready_files'],0)
        self.assertEqual(report['worst_seconds'],50)

if __name__=='__main__':unittest.main()
