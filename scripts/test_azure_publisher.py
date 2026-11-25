"""Exercise the publisher's registry exchange and protection with local command fixtures."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from textwrap import dedent
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/publish-azure-runtime.yml"
MOCK = r'''
import json
import os
from pathlib import Path
import sys

command = Path(sys.argv[0]).name
args = sys.argv[1:]
server = "acrfybercg47.azurecr.io"
endpoint = f"https://{server}"
repository = "controlplane-edge"
digest = os.environ["DIGEST"]

if command == "az":
    assert args == ["account", "get-access-token", "--resource", "https://containerregistry.azure.net",
                    "--query", "accessToken", "-o", "tsv"], args
    print("test-azure-token")
elif command == "docker":
    if args[:1] == ["login"]:
        assert args[1] in {"ghcr.io", server}, args
        assert args[-1] == "--password-stdin", args
        expected = "test-gh-token" if args[1] == "ghcr.io" else "test-refresh"
        assert sys.stdin.read() == expected
    elif args[:2] == ["manifest", "inspect"]:
        assert args[2] == f"{server}/{repository}:v1.2.3"
    else:
        assert args[:3] == ["buildx", "imagetools", "inspect"], args
        reference = args[3]
        assert reference in {f"ghcr.io/hyperme-sh/{repository}/runtime:v1.2.3", f"{server}/{repository}:v1.2.3"}, args
        actual = "sha256:" + "b" * 64 if os.environ["UNPROTECTED"] == "digest" else digest
        print(json.dumps({"digest": actual}))
else:
    assert command == "curl" and args[:4] == ["--disable", "-fsS", "--max-time", "30"], args
    body = sys.stdin.read()
    request = args[4:]
    if request[0] == endpoint + "/oauth2/exchange":
        assert body == "test-azure-token"
        assert request[1:] == [
            "--data", "grant_type=access_token", "--data-urlencode", "tenant=test-tenant",
            "--data-urlencode", f"service={server}", "--data-urlencode", "access_token@-",
        ]
        print(json.dumps({"refresh_token": "test-refresh"}))
    elif request[0] == endpoint + "/oauth2/token":
        assert body == "test-refresh"
        assert request[1:] == [
            "--data", "grant_type=refresh_token", "--data-urlencode", f"service={server}",
            "--data-urlencode", f"scope=repository:{repository}:metadata_read,metadata_write",
            "--data-urlencode", "refresh_token@-",
        ]
        print(json.dumps({"access_token": "test-metadata"}))
    else:
        assert request[:2] == ["--config", "-"]
        assert body == 'header = "Authorization: Bearer test-metadata"\n'
        tag_url = f"{endpoint}/acr/v1/{repository}/_tags/v1.2.3?api-version=2021-07-01"
        manifest_url = f"{endpoint}/acr/v1/{repository}/_manifests/{digest}?api-version=2021-07-01"
        url, *options = request[2:]
        assert url in {tag_url, manifest_url}, url
        kind = "tag" if url == tag_url else "manifest"
        with open(os.environ["REQUESTS"], "a") as log:
            print(f"{'PATCH' if options else 'GET'} {kind}", file=log)
        if options:
            assert options[:5] == ["--request", "PATCH", "--header", "Content-Type: application/json",
                                   "--data"], options
            fields = {"deleteEnabled": False}
            if kind == "tag":
                fields["writeEnabled"] = False
            assert json.loads(options[5]) == fields
        else:
            print(json.dumps({kind: {"digest": digest, "changeableAttributes": {
                "readEnabled": True, "deleteEnabled": os.environ["UNPROTECTED"] == kind,
                "writeEnabled": False,
            }}}))
'''


class PublisherContract(unittest.TestCase):
    def test_publisher_requires_verified_registry_protection(self):
        workflow = WORKFLOW.read_text()
        self.assertIn("    environment: edge-azure-release", workflow)
        for failure in ("", "tag", "manifest", "digest"):
            with self.subTest(failure=failure), TemporaryDirectory() as directory:
                run_case(Path(directory), failure)


def run_case(tmp_path, unprotected):
    step = WORKFLOW.read_text().split(
        "- name: Copy the qualified image without rebuilding and protect the tag", 1
    )[1]
    script = dedent(step.split("run: |\n", 1)[1].split("\n      - name:", 1)[0])
    for command in ("az", "docker", "curl"):
        fixture = tmp_path / command
        fixture.write_text(f"#!{sys.executable}\n{MOCK}")
        fixture.chmod(0o700)
    requests = tmp_path / "requests"
    summary = tmp_path / "summary"
    env = {
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "REQUESTS": str(requests),
        "GITHUB_STEP_SUMMARY": str(summary),
        "DIGEST": "sha256:" + "a" * 64,
        "VERSION_TAG": "v1.2.3",
        "ACR_TENANT": "test-tenant",
        "GH_TOKEN": "test-gh-token",
        "GITHUB_ACTOR": "test-actor",
        "UNPROTECTED": unprotected,
    }

    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=10)

    expected = ["PATCH tag", "PATCH manifest", "GET tag"]
    if unprotected != "tag":
        expected.append("GET manifest")
    actual = requests.read_text().splitlines() if requests.exists() else []
    assert actual == ([] if unprotected == "digest" else expected), result.stderr
    assert result.returncode == (1 if unprotected else 0), result.stderr
    if unprotected:
        assert not summary.exists()
    else:
        assert "Protected acrfybercg47.azurecr.io/controlplane-edge:v1.2.3" in summary.read_text()


PUBLISH_RUN_MOCK = r'''
import json
import os
import sys

args = sys.argv[1:]
repository = "hyperme-sh/controlplane-edge"
source = "a" * 40
if args == ["api", f"repos/{repository}/commits/v0.2.1", "--jq", ".sha"]:
    print(source)
elif args == ["api", f"repos/{repository}/actions/runs/100"]:
    print(json.dumps({"path": ".github/workflows/publish-stable-runtime.yml" if os.environ["FAILURE"] != "workflow" else "other.yml",
                      "event": "workflow_dispatch", "head_branch": "main", "conclusion": "success",
                      "head_repository": {"full_name": repository}, "repository": {"full_name": repository},
                      "run_attempt": 1}))
elif args == ["api", "--paginate", f"repos/{repository}/actions/runs/100/attempts/1/jobs?per_page=100"]:
    print(json.dumps({"jobs": [{"name": "publish", "conclusion": "success", "id": 101}]}))
else:
    assert args == ["run", "view", "100", "--repo", repository, "--attempt", "1", "--job", "101", "--log"], args
    print("publish\tPromote\t2026-11-25T16:00:00Z " + json.dumps({"schema_version": 1, "version": "v0.2.1",
          "revision": "b" * 40 if os.environ["FAILURE"] == "revision" else source,
          "repository": f"ghcr.io/{repository}/runtime", "digest": "sha256:" + "c" * 64}, separators=(",", ":")))
'''


class StableOCIInputContract(unittest.TestCase):
    def test_exact_stable_job_can_supply_azure_runtime_metadata(self):
        step = WORKFLOW.read_text().split("- name: Bind the stable release to its original image and source", 1)[1]
        script = dedent(step.split("run: |\n", 1)[1].split("\n      - name:", 1)[0])
        for failure in ("", "workflow", "revision"):
            with self.subTest(failure=failure), TemporaryDirectory() as directory:
                root = Path(directory)
                cli = root / "gh"
                cli.write_text(f"#!{sys.executable}\n{PUBLISH_RUN_MOCK}")
                cli.chmod(0o700)
                output = root / "output"
                env = {"PATH": f"{root}{os.pathsep}{os.environ['PATH']}", "RUNNER_TEMP": directory,
                       "GITHUB_REPOSITORY": "hyperme-sh/controlplane-edge", "GITHUB_OUTPUT": str(output),
                       "VERSION_TAG": "v0.2.1", "STABLE_RUN": "100", "FAILURE": failure}
                result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=10)
                if failure:
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(output.read_text(), "digest=sha256:" + "c" * 64 + "\n")
