import json
import subprocess

from content_archiver_telegram.config import Settings
from content_archiver_telegram.kiro_runner import KiroRunner


def test_kiro_runner_does_not_pass_github_token_to_kiro(monkeypatch, tmp_path) -> None:
    workflow = tmp_path / ".kiro" / "workflows" / "capture-text.md"
    request = tmp_path / ".content-archiver" / "incoming" / "request.yml"
    workflow.parent.mkdir(parents=True)
    request.parent.mkdir(parents=True)
    workflow.write_text("workflow", encoding="utf-8")
    request.write_text("id: test\n", encoding="utf-8")
    captured_env = {}

    def fake_run(args, **kwargs):
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"ok": True, "message": "done"}),
            stderr="",
        )

    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_secret")
    monkeypatch.setattr("content_archiver_telegram.kiro_runner.subprocess.run", fake_run)
    settings = Settings(
        content_repo_path=tmp_path,
        kiro_cli="kiro-cli",
        kiro_api_key="kiro-secret",
        github_token="github_pat_secret",
    )

    result = KiroRunner(settings).run_workflow(workflow_path=workflow, request_path=request)

    assert result["message"] == "done"
    assert captured_env["KIRO_API_KEY"] == "kiro-secret"
    assert "GITHUB_TOKEN" not in captured_env
