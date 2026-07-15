"""Tests for local OSA instance management (osa/cli/instance.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import json

import pytest
import yaml

from osa.cli.instance import (
    InstanceError,
    _build_compose_command,
    _compose_template_path,
    _mint_dev_token,
    _read_project_name,
    _write_dev_override,
    fetch_latest_osa_version,
    init_project,
    instance_logs,
    instance_status,
    start_instance,
    stop_instance,
)


def _write_osa_yaml(path: Path, name: str = "test-archive") -> None:
    (path / "osa.yaml").write_text(f'name: "{name}"\ndomain: "localhost"\n')
    (path / ".env").write_text("POSTGRES_PASSWORD=test\nJWT_SECRET=test\n")


class TestMintDevToken:
    def test_returns_three_part_jwt(self) -> None:
        token = _mint_dev_token()
        parts = token.split(".")
        assert len(parts) == 3

    def test_token_has_correct_claims(self) -> None:
        import base64

        token = _mint_dev_token()
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert payload["sub"] == "00000000-0000-7000-8000-0000000000a1"
        assert payload["aud"] == "authenticated"
        assert payload["provider"] == "local"
        assert payload["external_id"] == "admin@osa.local"

    def test_tokens_have_unique_jti(self) -> None:
        t1 = _mint_dev_token()
        t2 = _mint_dev_token()
        assert t1 != t2

    def test_signs_with_given_secret(self) -> None:
        import base64
        import hashlib
        import hmac

        token = _mint_dev_token("my-custom-secret")
        header_b64, payload_b64, sig_b64 = token.split(".")
        message = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(b"my-custom-secret", message, hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        assert got == expected


class TestEffectiveJwtSecret:
    """`osa start` must mint with the secret the local server actually uses."""

    def test_falls_back_to_dev_secret_when_no_env(self, tmp_path: Path) -> None:
        from osa.cli.instance import DEV_JWT_SECRET, _effective_jwt_secret

        assert _effective_jwt_secret(tmp_path) == DEV_JWT_SECRET

    def test_reads_jwt_secret_from_env(self, tmp_path: Path) -> None:
        from osa.cli.instance import _effective_jwt_secret

        (tmp_path / ".env").write_text(
            "POSTGRES_PASSWORD=pw\nJWT_SECRET=custom-cloud-secret\n"
        )
        assert _effective_jwt_secret(tmp_path) == "custom-cloud-secret"

    def test_osa_auth_var_takes_precedence(self, tmp_path: Path) -> None:
        from osa.cli.instance import _effective_jwt_secret

        (tmp_path / ".env").write_text(
            "JWT_SECRET=mapped\nOSA_AUTH__JWT__SECRET=direct\n"
        )
        assert _effective_jwt_secret(tmp_path) == "direct"

    def test_strips_quotes(self, tmp_path: Path) -> None:
        from osa.cli.instance import _effective_jwt_secret

        (tmp_path / ".env").write_text('JWT_SECRET="quoted-secret"\n')
        assert _effective_jwt_secret(tmp_path) == "quoted-secret"

    def test_minted_token_verifies_against_env_secret(self, tmp_path: Path) -> None:
        # End-to-end: a token minted from the effective secret validates with
        # that same secret — the exact coupling the server enforces.
        import base64
        import hashlib
        import hmac

        from osa.cli.instance import _effective_jwt_secret, _mint_dev_token

        (tmp_path / ".env").write_text("JWT_SECRET=the-real-secret\n")
        secret = _effective_jwt_secret(tmp_path)
        token = _mint_dev_token(secret)
        header_b64, payload_b64, sig_b64 = token.split(".")
        message = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        got = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        assert got == expected


class TestHelpers:
    def test_compose_template_path_exists(self) -> None:
        path = _compose_template_path()
        assert path.exists()
        assert path.name == "docker-compose.yml"


class TestReadProjectName:
    def test_reads_name_from_osa_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text('name: "my-archive"\n')
        assert _read_project_name(tmp_path) == "my-archive"

    def test_sanitizes_name(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text('name: "My Cool Project"\n')
        assert _read_project_name(tmp_path) == "my-cool-project"

    def test_strips_leading_trailing_hyphens(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text('name: "---test---"\n')
        assert _read_project_name(tmp_path) == "test"

    def test_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        project = tmp_path / "myarchive"
        project.mkdir()
        (project / "osa.yaml").write_text("domain: localhost\n")
        assert _read_project_name(project) == "myarchive"

    def test_raises_when_no_osa_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(InstanceError, match="osa.yaml not found"):
            _read_project_name(tmp_path)


class TestInitProject:
    def test_creates_osa_yaml(self, tmp_path: Path) -> None:
        project = tmp_path / "my-archive"
        init_project(project_dir=project)
        config = yaml.safe_load((project / "osa.yaml").read_text())
        assert config["name"] == "my-archive"
        assert config["domain"] == "localhost"

    def test_creates_env_file(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        env = (project / ".env").read_text()
        assert "POSTGRES_PASSWORD=" in env
        assert "JWT_SECRET=" in env

    def test_env_has_well_known_dev_secrets(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        env = (project / ".env").read_text()
        assert "POSTGRES_PASSWORD=osa-local-dev-password-CHANGE-IN-PRODUCTION" in env
        assert "JWT_SECRET=osa-local-dev-jwt-secret-CHANGE-IN-PRODUCTION" in env

    def test_creates_data_directory(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        assert (project / ".data").is_dir()

    def test_creates_osa_directory(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        assert (project / ".osa").is_dir()

    def test_creates_gitignore(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        gitignore = (project / ".gitignore").read_text()
        assert ".data/" in gitignore
        assert ".env" in gitignore
        assert ".osa/" in gitignore

    def test_appends_to_existing_gitignore(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        project.mkdir()
        (project / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        init_project(project_dir=project, force=True)
        gitignore = (project / ".gitignore").read_text()
        assert "*.pyc" in gitignore
        assert ".data/" in gitignore

    def test_does_not_duplicate_gitignore_entries(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        project.mkdir()
        (project / ".gitignore").write_text(".data/\n.env\n.osa/\n")
        init_project(project_dir=project, force=True)
        gitignore = (project / ".gitignore").read_text()
        assert gitignore.count(".data/") == 1

    def test_custom_name(self, tmp_path: Path) -> None:
        project = tmp_path / "dir"
        init_project(project_dir=project, name="custom-name")
        config = yaml.safe_load((project / "osa.yaml").read_text())
        assert config["name"] == "custom-name"

    def test_uses_dir_name_as_default(self, tmp_path: Path) -> None:
        project = tmp_path / "my-cool-archive"
        init_project(project_dir=project)
        config = yaml.safe_load((project / "osa.yaml").read_text())
        assert config["name"] == "my-cool-archive"

    def test_creates_target_directory(self, tmp_path: Path) -> None:
        project = tmp_path / "nested" / "deep" / "archive"
        init_project(project_dir=project)
        assert project.is_dir()
        assert (project / "osa.yaml").exists()

    def test_refuses_existing_config(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        with pytest.raises(InstanceError, match="already initialized"):
            init_project(project_dir=project)

    def test_force_overwrites(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        init_project(project_dir=project, force=True)
        assert (project / "osa.yaml").exists()

    def test_force_preserves_data_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        init_project(project_dir=project)
        (project / ".data" / "important.db").write_text("data")
        init_project(project_dir=project, force=True)
        assert (project / ".data" / "important.db").exists()

    def test_returns_project_dir(self, tmp_path: Path) -> None:
        project = tmp_path / "archive"
        result = init_project(project_dir=project)
        assert result.project_dir == project

    def test_lists_created_files(self, tmp_path: Path) -> None:
        result = init_project(project_dir=tmp_path / "archive")
        created_paths = [path for path, _ in result.created]
        assert created_paths == ["osa.yaml", ".env", ".data/", ".osa/", ".gitignore"]

    def test_init_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        init_project(project_dir=tmp_path)
        assert (tmp_path / "osa.yaml").exists()
        assert (tmp_path / ".env").exists()
        assert (tmp_path / ".data").is_dir()

    def test_init_current_dir_skips_cd_hint(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        result = init_project(project_dir=tmp_path)
        assert result.show_cd is False

    def test_init_other_dir_shows_cd_hint(self, tmp_path: Path) -> None:
        result = init_project(project_dir=tmp_path / "my-archive")
        assert result.show_cd is True


class TestBuildComposeCommand:
    def test_base_command_includes_template(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        cmd = _build_compose_command(project_dir=tmp_path, project_name="test")
        template = str(_compose_template_path())
        assert "-f" in cmd
        assert template in cmd

    def test_sets_project_name(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        cmd = _build_compose_command(project_dir=tmp_path, project_name="my-project")
        idx = cmd.index("--project-name")
        assert cmd[idx + 1] == "my-project"

    def test_includes_env_file(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        cmd = _build_compose_command(project_dir=tmp_path, project_name="test")
        idx = cmd.index("--env-file")
        assert cmd[idx + 1] == str(tmp_path / ".env")

    def test_with_override_file(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        (tmp_path / "docker-compose.override.yml").write_text("services: {}\n")
        cmd = _build_compose_command(project_dir=tmp_path, project_name="test")
        assert str(tmp_path / "docker-compose.override.yml") in cmd

    def test_without_override_file(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        cmd = _build_compose_command(project_dir=tmp_path, project_name="test")
        assert "docker-compose.override.yml" not in " ".join(cmd)

    def test_with_profiles(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        cmd = _build_compose_command(
            project_dir=tmp_path, project_name="test", profiles=["ui"]
        )
        idx = cmd.index("--profile")
        assert cmd[idx + 1] == "ui"

    def test_source_adds_dev_override(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        (tmp_path / ".osa").mkdir()
        source = tmp_path / "server-src"
        source.mkdir()
        cmd = _build_compose_command(
            project_dir=tmp_path, project_name="test", source=source
        )
        dev_path = str(tmp_path / ".osa" / "docker-compose.dev.yml")
        assert dev_path in cmd


class TestWriteDevOverride:
    def test_writes_valid_yaml(self, tmp_path: Path) -> None:
        source = tmp_path / "server"
        source.mkdir()
        (tmp_path / ".osa").mkdir()
        path = _write_dev_override(source=source, project_dir=tmp_path)
        data = yaml.safe_load(path.read_text())
        assert "services" in data

    def test_includes_source_path(self, tmp_path: Path) -> None:
        source = tmp_path / "server"
        source.mkdir()
        (tmp_path / ".osa").mkdir()
        path = _write_dev_override(source=source, project_dir=tmp_path)
        data = yaml.safe_load(path.read_text())
        context = data["services"]["server"]["build"]["context"]
        assert context == str(source.resolve())

    def test_sets_dev_mode(self, tmp_path: Path) -> None:
        source = tmp_path / "server"
        source.mkdir()
        (tmp_path / ".osa").mkdir()
        path = _write_dev_override(source=source, project_dir=tmp_path)
        data = yaml.safe_load(path.read_text())
        assert data["services"]["server"]["environment"]["OSA_DEV_MODE"] == "true"

    def test_written_to_osa_dir(self, tmp_path: Path) -> None:
        source = tmp_path / "server"
        source.mkdir()
        path = _write_dev_override(source=source, project_dir=tmp_path)
        assert path == tmp_path / ".osa" / "docker-compose.dev.yml"


def _mock_streamed(returncode: int = 0, output: str = ""):
    from osa.cli.proc import ProcResult

    return patch(
        "osa.cli.instance.run_streamed",
        return_value=ProcResult(returncode=returncode, output=output),
    )


class TestStartInstance:
    @pytest.fixture(autouse=True)
    def _mock_credentials(self):
        with patch("osa.cli.credentials.write_credentials"):
            yield

    def test_calls_docker_compose_up(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed() as mock_run:
            start_instance(project_dir=tmp_path, osa_version="v0.0.0")
        args = mock_run.call_args[0][0]
        assert "up" in args
        assert "-d" in args

    def test_no_detach_inherits_stdio(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            start_instance(project_dir=tmp_path, detach=False, osa_version="v0.0.0")
        args = mock_run.call_args[0][0]
        assert "up" in args
        assert "-d" not in args

    def test_with_source_adds_build(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        source = tmp_path / "server-src"
        source.mkdir()
        with _mock_streamed() as mock_run:
            start_instance(project_dir=tmp_path, source=source, osa_version="v0.0.0")
        args = mock_run.call_args[0][0]
        assert "--build" in args

    def test_with_ui_adds_profile(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed() as mock_run:
            start_instance(project_dir=tmp_path, with_ui=True, osa_version="v0.0.0")
        args = mock_run.call_args[0][0]
        assert "--profile" in args
        idx = args.index("--profile")
        assert args[idx + 1] == "ui"

    def test_raises_when_no_osa_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(InstanceError, match="osa.yaml not found"):
            start_instance(project_dir=tmp_path, osa_version="v0.0.0")

    def test_raises_on_compose_failure(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed(returncode=1):
            with pytest.raises(InstanceError, match="Failed to start"):
                start_instance(project_dir=tmp_path, osa_version="v0.0.0")

    def test_runs_in_project_dir(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed() as mock_run:
            start_instance(project_dir=tmp_path, osa_version="v0.0.0")
        assert mock_run.call_args[1]["cwd"] == tmp_path

    def test_links_to_local_server(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed():
            start_instance(project_dir=tmp_path, osa_version="v0.0.0")
        config = json.loads((tmp_path / ".osa" / "config.json").read_text())
        assert config["server"] == "http://127.0.0.1:8000"

    def test_stores_dev_credentials(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with (
            _mock_streamed(),
            patch("osa.cli.credentials.write_credentials") as mock_creds,
        ):
            start_instance(project_dir=tmp_path, osa_version="v0.0.0")
        mock_creds.assert_called_once()
        call_kwargs = mock_creds.call_args
        assert call_kwargs[0][0] == "http://127.0.0.1:8000"
        assert call_kwargs[1]["access_token"]
        assert call_kwargs[1]["refresh_token"] == "dev-no-refresh"


class TestStopInstance:
    def test_calls_docker_compose_down(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed() as mock_run:
            stop_instance(project_dir=tmp_path)
        args = mock_run.call_args[0][0]
        assert "down" in args

    def test_raises_when_no_osa_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(InstanceError, match="osa.yaml not found"):
            stop_instance(project_dir=tmp_path)

    def test_raises_on_compose_failure(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with _mock_streamed(returncode=1):
            with pytest.raises(InstanceError, match="Failed to stop"):
                stop_instance(project_dir=tmp_path)


class TestInstanceLogs:
    def test_calls_docker_compose_logs(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            instance_logs(project_dir=tmp_path)
        args = mock_run.call_args[0][0]
        assert "logs" in args

    def test_follow_flag(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            instance_logs(project_dir=tmp_path, follow=True)
        args = mock_run.call_args[0][0]
        assert "--follow" in args

    def test_tail_option(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            instance_logs(project_dir=tmp_path, tail=50)
        args = mock_run.call_args[0][0]
        assert "--tail" in args
        idx = args.index("--tail")
        assert args[idx + 1] == "50"

    def test_service_filter(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            instance_logs(project_dir=tmp_path, service="server")
        args = mock_run.call_args[0][0]
        assert "server" in args


class TestInstanceStatus:
    def test_calls_docker_compose_ps(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            instance_status(project_dir=tmp_path)
        args = mock_run.call_args[0][0]
        assert "ps" in args
        assert "--format" in args

    def test_parses_services_from_json_lines(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        line = json.dumps(
            {
                "Service": "server",
                "State": "running",
                "Health": "healthy",
                "Publishers": [{"PublishedPort": 8000, "TargetPort": 8000}],
            }
        )
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = line + "\n"
            services = instance_status(project_dir=tmp_path)
        assert len(services) == 1
        assert services[0].name == "server"
        assert services[0].state == "running"
        assert services[0].health == "healthy"
        assert services[0].ports == "8000->8000"

    def test_returns_empty_list_when_nothing_running(self, tmp_path: Path) -> None:
        _write_osa_yaml(tmp_path)
        with patch("osa.cli.instance.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            assert instance_status(project_dir=tmp_path) == []

    def test_raises_when_no_osa_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(InstanceError, match="osa.yaml not found"):
            instance_status(project_dir=tmp_path)


def _ghcr_resp(json_data: dict, link: str | None = None):
    from unittest.mock import MagicMock

    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    resp.headers = {"Link": link} if link else {}
    return resp


class TestFetchLatestOsaVersion:
    def test_picks_highest_semver_single_page(self) -> None:
        responses = [
            _ghcr_resp({"token": "t"}),
            _ghcr_resp({"tags": ["sha-abc", "v0.0.1", "v0.0.5", "v0.0.4", "latest"]}),
        ]
        with patch("httpx.get", side_effect=responses) as mock_get:
            assert fetch_latest_osa_version() == "v0.0.5"

        # Requests a large page so everything usually arrives in one response.
        tags_call = mock_get.call_args_list[1]
        assert "n=1000" in tags_call.args[0]

    def test_follows_pagination_to_find_newer_tag(self) -> None:
        # v0.0.5 only appears on the second page (the real GHCR bug).
        next_link = (
            f'</v2/{"opensciencearchive/osa"}/tags/list?last=sha-z&n=1000>; rel="next"'
        )
        responses = [
            _ghcr_resp({"token": "t"}),
            _ghcr_resp({"tags": ["v0.0.4", "sha-a"]}, link=next_link),
            _ghcr_resp({"tags": ["v0.0.5", "sha-b"]}),
        ]
        with patch("httpx.get", side_effect=responses) as mock_get:
            assert fetch_latest_osa_version() == "v0.0.5"

        # token + two tag pages
        assert mock_get.call_count == 3

    def test_tolerates_null_tags_page(self) -> None:
        responses = [
            _ghcr_resp({"token": "t"}),
            _ghcr_resp({"tags": None}),
        ]
        with patch("httpx.get", side_effect=responses):
            with pytest.raises(InstanceError, match="No release tags found"):
                fetch_latest_osa_version()

    def test_raises_when_registry_unreachable(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("boom")):
            with pytest.raises(
                InstanceError, match="Could not fetch latest OSA version"
            ):
                fetch_latest_osa_version()
