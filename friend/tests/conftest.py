# pytest fixtures live next to tests; tmp_path is enough.
import pytest


@pytest.fixture(autouse=True)
def _no_cloud_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never touch real clouds, whatever is in the developer's env."""
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "FAL_KEY", "GIZMO_THINK_MODEL"):
        monkeypatch.delenv(var, raising=False)
    # No camera dwell in tests; they should stay instant.
    monkeypatch.setenv("GIZMO_SEE_DWELL_S", "0")
