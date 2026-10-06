"""Publication stays bound to owner authority and independent exact-source gates."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]

class PublicationTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('publish_cli_release',ROOT/'scripts/publish_cli_release.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)

    def test_approval_and_review_cannot_be_reused_for_other_source_024_fr_011(self):
        sha='a'*40
        approval={'source_sha':sha,'version':'0.1.0','approved_by':'MaksimKravchuk','approved_actor':'MaksimKravchuk','approved_actions':['publish-cli-release'],'approval_evidence':'Owner explicitly approved this exact SHA/version/assets','assets':{'SHA256SUMS':'b'*64}}
        gates=[{'source_sha':sha,'verdict':'approved','reviewer':'independent-code-review','evidence':'recorded exact-SHA review'},{'source_sha':sha,'verdict':'approved','reviewer':'independent-qa','evidence':'recorded exact-SHA QA'}]
        self.module.validate_authority(approval,gates,sha,'0.1.0',{'SHA256SUMS':'b'*64},'MaksimKravchuk')
        for field,value in (('source_sha','c'*40),('approved_actor','other-user'),('approved_actions',[])):
            with self.subTest(field=field),self.assertRaises(ValueError):self.module.validate_authority({**approval,field:value},gates,sha,'0.1.0',{'SHA256SUMS':'b'*64},'MaksimKravchuk')
        gates[1]['source_sha']='c'*40
        with self.assertRaises(ValueError):self.module.validate_authority(approval,gates,sha,'0.1.0',{'SHA256SUMS':'b'*64},'MaksimKravchuk')

if __name__=='__main__':unittest.main()
