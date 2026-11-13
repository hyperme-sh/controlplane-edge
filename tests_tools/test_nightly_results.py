"""Exercise only shell cleanup, without installing or running owner suites."""
import os
from pathlib import Path
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('status', [0,1,5])
def test_cleanup_preserves_available_native_xml_and_original_status(tmp_path,status):
    script=(ROOT/'scripts/check-package.sh').read_text()
    cleanup=script.split('cleanup() {',1)[1].split('trap cleanup EXIT',1)[0]
    scratch=tmp_path/'private';scratch.mkdir()
    output=tmp_path/'results'
    (scratch/'source.xml').write_text('<testsuite failures="1"/>')
    (scratch/'private.txt').write_text('must not be copied')
    body='cleanup() {'+cleanup+'\ntrap cleanup EXIT\nexit '+str(status)
    result=subprocess.run(['bash','-c',body],env={**os.environ,'scratch':str(scratch),'TEST_EVIDENCE_DIR':str(output)})
    assert result.returncode==status
    assert (output/'source.xml').read_text()=='<testsuite failures="1"/>'
    assert sorted(p.name for p in output.iterdir())==['source.xml']
    assert not scratch.exists()


def test_container_smoke_opt_out_is_not_a_runtime_image_default():
    assert '-e EDGE_SECRETS_REQUIRED=false' in (ROOT/'scripts/check-container.sh').read_text()
    assert 'EDGE_SECRETS_REQUIRED=false' not in (ROOT/'deploy/Dockerfile.runtime').read_text()
