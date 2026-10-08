import subprocess
import sys
import venv
from pathlib import Path
import tempfile
import pytest
import logging

logger = logging.getLogger(__name__)


def test_package_metadata_exists():
    """Test that package metadata is accessible after import."""
    import importlib.metadata

    # This should not raise PackageNotFoundError
    version = importlib.metadata.version("mg-ravens")
    assert version is not None
    assert len(version) > 0

    # Verify it matches our __version__
    import ravens
    assert ravens.__version__ == version


def test_import_without_metadata():
    """Test that import works even if metadata is missing (dev mode)."""
    # This simulates the case where package isn't installed
    # We can't easily test this in the same process, but we can verify
    # the fallback logic exists
    from ravens import extract_version
    version = extract_version()
    assert version is not None
    assert isinstance(version, str)


def test_import_basic_modules():
    """Test that basic modules can be imported."""
    # Should not raise ImportError
    from ravens.xml import DssExport, RavensImport
    from ravens.base import RavensData

    assert DssExport is not None
    assert RavensImport is not None
    assert RavensData is not None


def test_version_format():
    """Test that version string has expected format."""
    import ravens

    version = ravens.__version__
    assert isinstance(version, str)
    assert len(version) > 0

    # Should be semver-like or have -dev suffix
    assert any([
        version.count('.') >= 2,  # e.g., 0.3.0
        version.endswith('-dev'),  # e.g., 0.3.0-dev
    ]), f"Version format unexpected: {version}"


@pytest.mark.slow
def test_package_installs_in_clean_venv():
    """Test that package can be installed and imported in a clean virtual environment.

    This test is marked as slow because it creates a venv and installs all dependencies.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "test_venv"
        logger.info(f"Creating test venv at: {venv_path}")

        # Create virtual environment
        venv.create(venv_path, with_pip=True)

        # Get python and pip executables
        if sys.platform == "win32":
            python_exe = venv_path / "Scripts" / "python.exe"
            pip_exe = venv_path / "Scripts" / "pip.exe"
        else:
            python_exe = venv_path / "bin" / "python"
            pip_exe = venv_path / "bin" / "pip"

        # Upgrade pip first (helps with speed)
        logger.info("Upgrading pip...")
        subprocess.run(
            [str(pip_exe), "install", "--upgrade", "pip"],
            capture_output=True,
            timeout=60
        )

        # Install the package from the current directory
        project_root = Path(__file__).parent.parent
        logger.info(f"Installing package from: {project_root}")

        result = subprocess.run(
            [str(pip_exe), "install", str(project_root)],
            capture_output=True,
            text=True,
            timeout=300  # Increased to 5 minutes
        )

        if result.returncode != 0:
            pytest.fail(f"Installation failed:\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")

        logger.info("Package installed successfully")

        # Test that we can import the package
        result = subprocess.run(
            [str(python_exe), "-c", "import ravens; print(ravens.__version__)"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            pytest.fail(f"Import failed:\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")

        version_output = result.stdout.strip()
        logger.info(f"Imported version: {version_output}")

        assert version_output, "Version should not be empty"
        assert not version_output.endswith("-dev"), "Should not have -dev suffix when installed"

        # Test that we can import specific modules
        result = subprocess.run(
            [str(python_exe), "-c", "from ravens.xml import DssExport, RavensImport; print('SUCCESS')"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            pytest.fail(f"Module import failed:\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")

        assert "SUCCESS" in result.stdout
        logger.info("All imports successful in clean venv")


@pytest.mark.slow
def test_package_installs_from_git():
    """Test that package can be installed from git repository.

    This test is marked as slow and can be skipped with: pytest -m "not slow"
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        venv_path = Path(tmpdir) / "test_venv"
        logger.info(f"Creating test venv for git install at: {venv_path}")

        # Create virtual environment
        venv.create(venv_path, with_pip=True)

        # Get python and pip executables
        if sys.platform == "win32":
            python_exe = venv_path / "Scripts" / "python.exe"
            pip_exe = venv_path / "Scripts" / "pip.exe"
        else:
            python_exe = venv_path / "bin" / "python"
            pip_exe = venv_path / "bin" / "pip"

        # Upgrade pip first
        subprocess.run(
            [str(pip_exe), "install", "--upgrade", "pip"],
            capture_output=True,
            timeout=60
        )

        # Install from git
        logger.info("Installing from git (this may take a while)...")
        result = subprocess.run(
            [str(pip_exe), "install", "git+https://github.com/lanl-ansi/MG-RAVENS.git@develop"],
            capture_output=True,
            text=True,
            timeout=300  # Increased to 5 minutes
        )

        if result.returncode != 0:
            pytest.skip(f"Git installation failed (might be network issue):\n{result.stderr}")

        logger.info("Git installation successful")

        # Test import
        result = subprocess.run(
            [str(python_exe), "-c",
             "from ravens.xml import DssExport, RavensImport; "
             "import ravens; "
             "print(ravens.__version__)"],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            pytest.fail(f"Import failed after git install:\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}")

        version_output = result.stdout.strip()
        logger.info(f"Git install version: {version_output}")
        assert version_output, "Version should be printed"
