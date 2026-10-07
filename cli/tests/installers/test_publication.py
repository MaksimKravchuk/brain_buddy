"""Publication stays bound to owner authority and independent exact-source gates."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

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

    def test_existing_release_tag_must_resolve_to_approved_commit_024_fr_009_024_fr_011(self):
        sha='a'*40;tag='bb-v0.1.0';ref=f'refs/tags/{tag}'
        for kind,target in [('commit','b'*40),('tree',sha),('tag','c'*40)]:
            def response(path):
                return [{'ref':ref,'object':{'type':kind,'sha':target}}] if 'matching-refs' in path else {'object':{'type':'commit','sha':'b'*40}}
            with self.subTest(kind=kind),patch.object(self.module,'api',side_effect=response),self.assertRaises(ValueError):
                self.module.validate_tag(tag,sha,required=True)
        replies=[[{'ref':ref,'object':{'type':'tag','sha':'c'*40}}],{'object':{'type':'tag','sha':'d'*40}},{'object':{'type':'commit','sha':sha}}]
        with patch.object(self.module,'api',side_effect=replies):
            self.assertTrue(self.module.validate_tag(tag,sha,required=True))
        with patch.object(self.module,'api',return_value=[]):
            self.assertFalse(self.module.validate_tag(tag,sha))
            with self.assertRaises(ValueError):self.module.validate_tag(tag,sha,required=True)

    def test_tag_is_rechecked_before_draft_is_published_024_fr_009_024_fr_011(self):
        sha='a'*40
        with patch.object(self.module,'validate_tag',side_effect=[True,True,ValueError('Tag moved')]) as validate,patch.object(self.module,'api',return_value={'object':{'sha':sha}}),patch.object(self.module,'gh') as gh:
            with self.assertRaises(ValueError):self.module.publish('bb-v0.1.0',sha,'0.1.0',Path('/fixture'),['SHA256SUMS'])
        self.assertEqual(validate.call_count,3)
        self.assertEqual(gh.call_count,1)
        self.assertIn('--draft',gh.call_args.args)
        self.assertIn('--verify-tag',gh.call_args.args)

    def test_missing_tag_is_created_at_exact_sha_without_moving_existing_refs_024_fr_011(self):
        sha='a'*40
        with patch.object(self.module,'validate_tag',side_effect=[False,True,True]),patch.object(self.module,'api',return_value={'object':{'sha':sha}}),patch.object(self.module,'gh') as gh:
            self.module.publish('bb-v0.1.0',sha,'0.1.0',Path('/fixture'),['SHA256SUMS'])
        self.assertEqual(gh.call_count,3)
        creation=gh.call_args_list[0].args
        self.assertIn('POST',creation);self.assertIn('ref=refs/tags/bb-v0.1.0',creation);self.assertIn(f'sha={sha}',creation)
        self.assertEqual(gh.call_args.args[:3],('release','edit','bb-v0.1.0'))

if __name__=='__main__':unittest.main()
