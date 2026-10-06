"""File transfers in and out of the local workspace jail.

The previous implementation branched on ``is_dir()`` and created an *empty*
destination for a directory, so a caller copying a directory out of a sandbox got
a success and silently lost the contents. It also read whole files into memory
with no size bound, which made ``max_filesystem_bytes`` decorative.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.ports.agent_runtime import (
    RuntimePolicyRejectedError,
    SandboxHandle,
    TransferRequest,
)
from app.domain.value_objects.runtime_provider import RuntimeProvider
from app.infrastructure.agent_runtime.adapters.local_sandbox_runtime import (
    LocalSandboxRuntime,
)


@pytest.fixture
def workspace(tmp_path) -> Path:
    root = tmp_path / "workspace"
    (root / "nested").mkdir(parents=True)
    (root / "top.txt").write_text("top", encoding="utf-8")
    (root / "nested" / "deep.txt").write_text("deep", encoding="utf-8")
    return root


def handle_for(workspace: Path) -> SandboxHandle:
    return SandboxHandle(
        sandbox_id="sbx-1",
        provider=RuntimeProvider.LOCAL,
        name="run-1",
        workspace_path=str(workspace),
    )


class TestDownloadFiles:
    async def test_a_file_is_copied_out(self, workspace: Path, tmp_path: Path) -> None:
        destination = tmp_path / "out" / "top.txt"
        runtime = LocalSandboxRuntime()

        await runtime.download(
            handle_for(workspace),
            TransferRequest(
                sandbox_id="sbx-1", local_path=str(destination), remote_path="top.txt"
            ),
        )

        assert destination.read_text(encoding="utf-8") == "top"

    async def test_a_nested_file_is_copied_out(self, workspace: Path, tmp_path: Path) -> None:
        destination = tmp_path / "deep.txt"
        runtime = LocalSandboxRuntime()

        await runtime.download(
            handle_for(workspace),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=str(destination),
                remote_path="nested/deep.txt",
            ),
        )

        assert destination.read_text(encoding="utf-8") == "deep"

    async def test_a_source_outside_the_workspace_is_refused(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        runtime = LocalSandboxRuntime()

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(tmp_path / "out.txt"),
                    remote_path=str(outside),
                ),
            )
        assert not (tmp_path / "out.txt").exists()

    async def test_traversal_out_of_the_workspace_is_refused(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        runtime = LocalSandboxRuntime()

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(tmp_path / "out.txt"),
                    remote_path="../../etc/passwd",
                ),
            )


class TestDownloadDirectories:
    async def test_a_directory_transfer_carries_its_contents(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        # This is the case that used to produce an empty directory and report
        # success.
        destination = tmp_path / "copy"
        runtime = LocalSandboxRuntime()

        await runtime.download(
            handle_for(workspace),
            TransferRequest(sandbox_id="sbx-1", local_path=str(destination)),
        )

        assert (destination / "top.txt").read_text(encoding="utf-8") == "top"
        assert (destination / "nested" / "deep.txt").read_text(encoding="utf-8") == "deep"

    async def test_an_empty_directory_does_not_fail(self, tmp_path: Path) -> None:
        workspace = tmp_path / "empty"
        workspace.mkdir()
        runtime = LocalSandboxRuntime()

        await runtime.download(
            handle_for(workspace),
            TransferRequest(
                sandbox_id="sbx-1", local_path=str(tmp_path / "copy"), remote_path="."
            ),
        )

        assert (tmp_path / "copy").is_dir()


class TestTransferSizeLimit:
    async def test_an_oversized_file_is_refused(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "big.bin").write_bytes(b"x" * 4096)
        runtime = LocalSandboxRuntime(max_transfer_bytes=1024)

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(tmp_path / "big.bin"),
                    remote_path="big.bin",
                ),
            )
        assert not (tmp_path / "big.bin").exists()

    async def test_an_oversized_tree_is_refused(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        (workspace / "sub").mkdir(parents=True)
        (workspace / "sub" / "a.bin").write_bytes(b"x" * 2048)
        (workspace / "sub" / "b.bin").write_bytes(b"x" * 2048)
        runtime = LocalSandboxRuntime(max_transfer_bytes=3000)

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(sandbox_id="sbx-1", local_path=str(tmp_path / "copy")),
            )

    async def test_a_file_exactly_at_the_limit_is_allowed(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "exact.bin").write_bytes(b"x" * 1024)
        runtime = LocalSandboxRuntime(max_transfer_bytes=1024)

        await runtime.download(
            handle_for(workspace),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=str(tmp_path / "exact.bin"),
                remote_path="exact.bin",
            ),
        )

        assert (tmp_path / "exact.bin").stat().st_size == 1024


class TestSymlinksAreNotFollowed:
    async def test_a_symlinked_source_is_refused(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        link = workspace / "link.txt"
        try:
            link.symlink_to(secret)
        except OSError:
            pytest.skip("symlinks are not available on this filesystem")

        runtime = LocalSandboxRuntime()

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(tmp_path / "out.txt"),
                    remote_path="link.txt",
                ),
            )

    async def test_a_symlink_inside_a_tree_is_refused(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        (workspace / "tree").mkdir(parents=True)
        secret = tmp_path / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        try:
            (workspace / "tree" / "link.txt").symlink_to(secret)
        except OSError:
            pytest.skip("symlinks are not available on this filesystem")

        runtime = LocalSandboxRuntime()

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.download(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(tmp_path / "copy"),
                    remote_path="tree",
                ),
            )


class TestUpload:
    async def test_a_file_is_copied_in(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        source = tmp_path / "in.txt"
        source.write_text("payload", encoding="utf-8")
        runtime = LocalSandboxRuntime()

        await runtime.upload(
            handle_for(workspace),
            TransferRequest(
                sandbox_id="sbx-1",
                local_path=str(source),
                remote_path="in.txt",
            ),
        )

        assert (workspace / "in.txt").read_text(encoding="utf-8") == "payload"

    async def test_a_destination_outside_the_workspace_is_refused(
        self, tmp_path: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        source = tmp_path / "in.txt"
        source.write_text("payload", encoding="utf-8")
        runtime = LocalSandboxRuntime()

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.upload(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(source),
                    remote_path=str(tmp_path / "escaped.txt"),
                ),
            )
        assert not (tmp_path / "escaped.txt").exists()

    async def test_an_oversized_upload_is_refused(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        source = tmp_path / "big.bin"
        source.write_bytes(b"x" * 4096)
        runtime = LocalSandboxRuntime(max_transfer_bytes=1024)

        with pytest.raises(RuntimePolicyRejectedError):
            await runtime.upload(
                handle_for(workspace),
                TransferRequest(
                    sandbox_id="sbx-1",
                    local_path=str(source),
                    remote_path="big.bin",
                ),
            )
        assert not (workspace / "big.bin").exists()