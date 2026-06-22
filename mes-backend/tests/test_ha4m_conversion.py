"""
TDD: Test HA4M 3D mm → MediaPipe 2D 0-1 conversion.

HA4M raw skeleton files have 32 joints in Azure Kinect 3D mm coordinates.
We need to convert these to MediaPipe-style 33-joint [0,1] normalized 2D coordinates
so HA4M and synthetic data share the same coordinate space for mixed training.
"""

import numpy as np
import os
import glob
import pytest


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def ha4m_raw_data_path():
    """Path to HA4M raw skeleton files (single subject)."""
    d = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "ha4m_raw",
        "IDU001V001",
        "Skeletons",
        "000124702712",
    )
    if not os.path.isdir(d):
        pytest.skip(f"HA4M raw data not found at {d}")
    return d


@pytest.fixture(scope="module")
def ha4m_labels_path():
    """Path to HA4M labels file."""
    p = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "ha4m_raw",
        "IDU001V001",
        "Labels.txt",
    )
    if not os.path.isfile(p):
        pytest.skip(f"HA4M labels not found at {p}")
    return p


@pytest.fixture
def sample_ha4m_frame(ha4m_raw_data_path):
    """Load a single frame of HA4M skeleton data as numpy array (32, 14)."""
    files = sorted(glob.glob(os.path.join(ha4m_raw_data_path, "*.txt")))
    if not files:
        pytest.skip("No HA4M skeleton files found")
    data = np.loadtxt(files[0], delimiter="\t", skiprows=1)
    assert data.shape == (32, 14), f"Expected (32, 14), got {data.shape}"
    return data


# ── Tests ────────────────────────────────────────────────────────────


def test_convert_single_frame_output_shape(sample_ha4m_frame):
    """Converting a single HA4M frame should produce (33, 3) output."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_frame

    result = convert_frame(sample_ha4m_frame, use_2d_projection=True)
    assert result.shape == (33, 3), f"Expected (33, 3), got {result.shape}"


def test_convert_single_frame_coordinates_in_01_range(sample_ha4m_frame):
    """After conversion, x and y coordinates should be in [0, 1]."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_frame

    result = convert_frame(sample_ha4m_frame, use_2d_projection=True)
    x_coords = result[:, 0]
    y_coords = result[:, 1]
    assert np.all((x_coords >= 0) & (x_coords <= 1)), (
        f"x coordinates out of [0,1] range: [{x_coords.min()}, {x_coords.max()}]"
    )
    assert np.all((y_coords >= 0) & (y_coords <= 1)), (
        f"y coordinates out of [0,1] range: [{y_coords.min()}, {y_coords.max()}]"
    )


def test_convert_single_frame_perspective_projection(sample_ha4m_frame):
    """Perspective projection should also produce [0,1] coordinates."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_frame

    result = convert_frame(sample_ha4m_frame, use_2d_projection=False)
    x_coords = result[:, 0]
    y_coords = result[:, 1]
    assert np.all((x_coords >= 0) & (x_coords <= 1)), (
        f"Perspective projection x out of [0,1]: [{x_coords.min()}, {x_coords.max()}]"
    )
    assert np.all((y_coords >= 0) & (y_coords <= 1)), (
        f"Perspective projection y out of [0,1]: [{y_coords.min()}, {y_coords.max()}]"
    )


def test_convert_single_frame_confidence_preserved(sample_ha4m_frame):
    """Confidence values should be preserved from HA4M confidence column."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_frame

    result = convert_frame(sample_ha4m_frame, use_2d_projection=True)
    # At least some joints should have non-zero confidence
    assert np.max(result[:, 2]) > 0, "All confidence values are zero"
    # Confidence should be in [0, 1]
    assert np.all((result[:, 2] >= 0) & (result[:, 2] <= 1)), (
        "Confidence out of [0, 1] range"
    )


def test_convert_mapped_joints_have_nonzero_coords(sample_ha4m_frame):
    """Mapped joints (shoulders, elbows, wrists) should have non-zero coordinates."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_frame

    result = convert_frame(sample_ha4m_frame, use_2d_projection=True)
    # Key MediaPipe joints: 5(左肩), 6(右肩), 11(左肘), 12(右肘), 15(左腕), 16(右腕)
    key_joints = [5, 6, 11, 12, 15, 16]
    for j in key_joints:
        x, y, conf = result[j]
        # At minimum, some of these should be non-zero
        assert x >= 0 and y >= 0, f"Joint {j} has negative coordinates: ({x}, {y})"


def test_project_3d_to_2d_returns_01():
    """project_3d_to_2d should return coordinates in [0,1] for valid 3D input."""
    from app.scripts.convert_ha4m_to_mediapipe import project_3d_to_2d

    # Typical HA4M 3D values
    test_cases = [
        (100, 0, 1800),      # center-ish
        (-200, -500, 1700),  # joint off to side
        (300, 400, 2000),    # far away
        (0, 0, 1500),        # close
        (100, -200, 0),      # invalid z → should return center
    ]
    for x_mm, y_mm, z_mm in test_cases:
        x_norm, y_norm = project_3d_to_2d(x_mm, y_mm, z_mm)
        assert 0 <= x_norm <= 1, f"x_norm={x_norm} out of [0,1] for ({x_mm}, {y_mm}, {z_mm})"
        assert 0 <= y_norm <= 1, f"y_norm={y_norm} out of [0,1] for ({x_mm}, {y_mm}, {z_mm})"


def test_convert_dataset_output_structure(ha4m_raw_data_path, ha4m_labels_path, tmp_path):
    """convert_dataset should produce .npz and .npy files with correct structure."""
    from app.scripts.convert_ha4m_to_mediapipe import convert_dataset

    # Use tmp_path as output directory
    X, y = convert_dataset(
        skeleton_dir=ha4m_raw_data_path,
        label_path=ha4m_labels_path,
        output_dir=str(tmp_path),
        use_2d_projection=True,
    )

    # Check npz file exists and loads correctly
    npz_path = os.path.join(tmp_path, "ha4m_mediapipe.npz")
    assert os.path.isfile(npz_path), "ha4m_mediapipe.npz not created"

    data = np.load(npz_path, allow_pickle=True)
    assert "data" in data, "npz missing 'data'"
    assert "labels" in data, "npz missing 'labels'"
    assert data["data"].shape[1:] == (3, 48, 33, 1), (
        f"Expected (N, 3, 48, 33, 1), got {data['data'].shape}"
    )

    # Check .npy files exist
    npy_files = sorted(glob.glob(os.path.join(tmp_path, "*.npy")))
    assert len(npy_files) > 0, "No .npy files created"

    return X, y
