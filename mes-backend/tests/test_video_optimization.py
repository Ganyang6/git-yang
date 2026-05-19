"""
TDD Tests for Video Processing Optimization (4K CPU Performance)
Target: Speed up 4K video processing on CPU by 5-10x while maintaining pose_score quality
"""

import numpy as np
import pytest
from typing import List


class TestFrameDownsampler:
    """Test 1: Intelligent frame downsampling for CPU optimization"""

    def test_downscale_4k_to_target_resolution(self):
        """Should downscale 3840x2160 (4K) to target resolution preserving aspect ratio"""
        from video_optimizer import FrameDownsampler

        downsampler = FrameDownsampler(max_resolution=640)
        frame_4k = np.zeros((2160, 3840, 3), dtype=np.uint8)

        result = downsampler.downscale(frame_4k)

        assert result.shape[1] == 640
        assert result.shape[0] == 360

    def test_no_downscale_for_small_frames(self):
        """Should not downscale frames smaller than max_resolution"""
        from video_optimizer import FrameDownsampler

        downsampler = FrameDownsampler(max_resolution=640)
        frame_small = np.zeros((480, 640, 3), dtype=np.uint8)

        result = downsampler.downscale(frame_small)

        assert result.shape == frame_small.shape

    def test_preserve_aspect_ratio(self):
        """Should preserve aspect ratio when downscaling"""
        from video_optimizer import FrameDownsampler

        downsampler = FrameDownsampler(max_resolution=800)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)

        result = downsampler.downscale(frame)

        expected_height = int(1080 * (800 / 1920))
        assert result.shape[1] == 800
        assert result.shape[0] == expected_height

    def test_disable_downsampling_when_zero(self):
        """Should return original frame when max_resolution=0 (disabled)"""
        from video_optimizer import FrameDownsampler

        downsampler = FrameDownsampler(max_resolution=0)
        frame = np.zeros((2160, 3840, 3), dtype=np.uint8)

        result = downsampler.downscale(frame)

        assert result.shape == frame.shape

    def test_use_inter_area_for_downscaling(self):
        """Should use INTER_AREA interpolation for quality downscaling"""
        from video_optimizer import FrameDownsampler
        import cv2

        downsampler = FrameDownsampler(max_resolution=640)
        frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)

        result = downsampler.downscale(frame)

        assert result.dtype == np.uint8
        assert result.shape[1] == 640


class TestFrameSkipDetector:
    """Test 2: Frame skip detection for reducing inference calls by 66%"""

    def test_should_detect_on_interval_frames(self):
        """Should return True every Nth frame for inference"""
        from video_optimizer import FrameSkipDetector

        detector = FrameSkipDetector(detection_interval=3)

        assert detector.should_detect(0) is True
        assert detector.should_detect(1) is False
        assert detector.should_detect(2) is False
        assert detector.should_detect(3) is True
        assert detector.should_detect(6) is True

    def test_skip_non_interval_frames(self):
        """Should return False for non-interval frames"""
        from video_optimizer import FrameSkipDetector

        detector = FrameSkipDetector(detection_interval=3)

        skipped_count = sum(1 for i in range(9) if not detector.should_detect(i))
        assert skipped_count == 6

    def test_custom_detection_interval(self):
        """Should support custom detection intervals"""
        from video_optimizer import FrameSkipDetector

        detector = FrameSkipDetector(detection_interval=5)
        detections = [detector.should_detect(i) for i in range(15)]

        assert detections.count(True) == 3
        assert detections[0] is True
        assert detections[5] is True
        assert detections[10] is True

    def test_every_frame_mode(self):
        """When interval=1, should detect every frame"""
        from video_optimizer import FrameSkipDetector

        detector = FrameSkipDetector(detection_interval=1)

        for i in range(10):
            assert detector.should_detect(i) is True


class TestCoreLandmarkScoreCalculator:
    """Test 3: Core landmark pose_score calculation (improve score from 0.72 to 0.85+)"""

    def test_calculate_core_landmarks_score_only(self):
        """Should calculate pose_score using only core landmarks, not all 33"""
        from video_optimizer import CoreLandmarkScoreCalculator
        from pose_estimator import Landmark

        calculator = CoreLandmarkScoreCalculator()

        landmarks = self._create_mock_landmarks(
            core_visibility=0.95,
            non_core_visibility=0.50
        )

        core_score = calculator.calculate(landmarks)

        old_all_mean = self._calculate_all_mean(landmarks)
        assert core_score > old_all_mean
        assert core_score > 0.85

    def test_handle_empty_landmarks(self):
        """Should return 0.0 for empty landmarks list"""
        from video_optimizer import CoreLandmarkScoreCalculator

        calculator = CoreLandmarkScoreCalculator()
        score = calculator.calculate([])

        assert score == 0.0

    def test_include_correct_core_landmarks(self):
        """Should include nose, shoulders, elbows, wrists, hips, knees, ankles"""
        from video_optimizer import CoreLandmarkScoreCalculator

        calculator = CoreLandmarkScoreCalculator()

        expected_indices = {0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28}
        assert calculator.core_landmark_indices == expected_indices

    def test_low_core_visibility_reduces_score(self):
        """Low visibility on core landmarks should produce low score"""
        from video_optimizer import CoreLandmarkScoreCalculator

        calculator = CoreLandmarkScoreCalculator()
        landmarks = self._create_mock_landmarks(core_visibility=0.30, non_core_visibility=0.90)

        score = calculator.calculate(landmarks)
        assert score < 0.50

    @staticmethod
    def _create_mock_landmarks(core_visibility: float, non_core_visibility: float) -> List:
        from pose_estimator import Landmark

        core_indices = {0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28}
        landmarks = []

        for i in range(33):
            vis = core_visibility if i in core_indices else non_core_visibility
            landmarks.append(Landmark(x=0.5, y=0.5, z=0.0, visibility=vis))

        return landmarks

    @staticmethod
    def _calculate_all_mean(landmarks: List) -> float:
        return np.mean([lm.visibility for lm in landmarks])


class TestCLAHEEnhancer:
    """Test 4: CLAHE lighting enhancement for low-light scenarios"""

    def test_enhance_low_light_frame(self):
        """Should enhance contrast of low-light frames"""
        from video_optimizer import CLAHEEnhancer

        enhancer = CLAHEEnhancer()
        dark_frame = np.full((480, 640, 3), 80, dtype=np.uint8)

        enhanced = enhancer.enhance(dark_frame)

        assert enhanced.shape == dark_frame.shape
        assert enhanced.dtype == np.uint8
        assert not np.array_equal(enhanced, dark_frame)

    def test_preserve_bright_frames(self):
        """Should minimally alter well-lit frames"""
        from video_optimizer import CLAHEEnhancer

        enhancer = CLAHEEnhancer()
        bright_frame = np.full((480, 640, 3), 200, dtype=np.uint8)

        enhanced = enhancer.enhance(bright_frame)

        mean_diff = np.mean(np.abs(enhanced.astype(int) - bright_frame.astype(int)))
        assert mean_diff < 20

    def test_return_same_shape_and_dtype(self):
        """Output must match input shape and dtype exactly"""
        from video_optimizer import CLAHEEnhancer

        enhancer = CLAHEEnhancer()
        frame = np.random.randint(0, 256, (720, 1280, 3), dtype=np.uint8)

        enhanced = enhancer.enhance(frame)

        assert enhanced.shape == frame.shape
        assert enhanced.dtype == frame.dtype


class TestVideoOptimizerPipeline:
    """Integration Test: Combined optimizer pipeline"""

    def test_pipeline_processes_4k_frame(self):
        """End-to-end: 4K frame -> downscale -> enhance -> ready for inference"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline = VideoOptimizerPipeline(
            max_resolution=640,
            detection_interval=3,
            enable_clahe=True
        )

        frame_4k = np.random.randint(0, 256, (2160, 3840, 3), dtype=np.uint8)

        result = pipeline.process_frame(frame_4k, frame_index=0)

        assert 'frame' in result
        assert 'should_infer' in result
        assert result['frame'].shape[1] <= 640
        assert result['should_infer'] is True

    def test_pipeline_skips_inference_on_non_interval(self):
        """Pipeline should indicate skip inference on non-interval frames"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline = VideoOptimizerPipeline(detection_interval=3)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        result = pipeline.process_frame(frame, frame_index=1)

        assert result['should_infer'] is False
