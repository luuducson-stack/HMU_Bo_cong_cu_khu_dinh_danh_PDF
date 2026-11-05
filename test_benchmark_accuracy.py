import unittest
from benchmarks.benchmark_accuracy import evaluate_regions

class AccuracyMetricTests(unittest.TestCase):
    def test_partial_name_is_miss_and_unselected_prediction_is_not_redacted(self):
        labels=[dict(entity_id='name',page=1,kind='PATIENT_NAME',action='must_redact',rects=[[10,10,40,20]])]
        partial=[dict(page=1,kind='PATIENT_NAME',selected=True,rects=[[20,10,40,20]])]
        self.assertEqual(evaluate_regions(labels,partial)['selection']['fn'],1)
        complete=partial+[dict(page=1,kind='PATIENT_NAME',selected=False,rects=[[10,10,20,20]])]
        result=evaluate_regions(labels,complete)
        self.assertEqual(result['proposal']['tp'],1);self.assertEqual(result['selection']['tp'],0)
        complete[1]['selected']=True
        self.assertEqual(evaluate_regions(labels,complete)['selection']['tp'],1)
    def test_wide_mask_touching_clinical_content_is_reported(self):
        labels=[dict(entity_id='clinical',page=1,kind='CLINICAL',action='must_preserve',rects=[[30,10,60,20]])]
        selected=[dict(page=1,kind='PATIENT_NAME',selected=True,rects=[[10,10,35,20]])]
        self.assertEqual(evaluate_regions(labels,selected)['preserve_overlaps'],1)

if __name__=='__main__':unittest.main()
