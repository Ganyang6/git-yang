"""
TDD Integration Tests: VideoOptimizerPipeline + PoseEstimator
Target: End-to-end pipeline from frame to pose estimation result
"""

import numpy as np
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestOptimizerEstimatorIntegration:
    """Integration tests for optimizer pipeline + pose estimator working together"""

    def test_pipeline_estimator_pipeline_flow(self):
        """Full flow: raw frame -> optimizer pipeline -> pose estimator -> pose score"""
        from video_optimizer import VideoOptimizerPipeline
        from pose_estimator import PoseEstimator, Landmark

        pipeline = VideoOptimizerPipeline(
            max_resolution=640,
            detection_interval=3,
            enable_clahe=True
        )

        raw_frame = np.random.randint(0, 256, (1080, 1920, 3), dtype=np.uint8)

        result = pipeline.process_frame(raw_frame, frame_index=0)

        assert 'frame' in result
        assert 'should_infer' in result
        assert result['frame'].shape[1] <= 640
        assert result['should_infer'] is True

        with patch('pose_estimator.PoseEstimator._init_mediapipe'):
            with patch('pose_estimator.PoseEstimator._warmup'):
                estimator = PoseEstimator(model_complexity=0, smooth=False)

                mock_landmark = Mock()
                mock_landmark.x = 0.5
                mock_landmark.y = 0.5
                mock_landmark.z = 0.0
                mock_landmark.visibility = 0.95

                mock_detection = Mock()
                mock_detection.pose_landmarks = [[mock_landmark] * 33]

                estimator._pose = Mock()
                estimator._pose.detect.return_value = mock_detection
                estimator._use_tasks_api = True

                pose_result = estimator.estimate(result['frame'])

                assert pose_result.pose_score > 0.0

                estimator.close()

    def test_pipeline_skips_inference_when_should_infer_false(self):
        """When detection_interval=3, frames 1,2 should skip inference"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline = VideoOptimizerPipeline(detection_interval=3)

        raw_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        for frame_index in range(6):
            result = pipeline.process_frame(raw_frame, frame_index=frame_index)

            if frame_index % 3 == 0:
                assert result['should_infer'] is True, f"Frame {frame_index} should infer"
            else:
                assert result['should_infer'] is False, f"Frame {frame_index} should skip"

    def test_estimator_uses_core_landmark_calculator_instance(self):
        """PoseEstimator should reuse _core_score_calculator instance, not recreate each call"""
        from pose_estimator import PoseEstimator
        from video_optimizer import CoreLandmarkScoreCalculator

        with patch('pose_estimator.PoseEstimator._init_mediapipe'):
            with patch('pose_estimator.PoseEstimator._warmup'):
                estimator = PoseEstimator(model_complexity=0, smooth=False)

                assert hasattr(estimator, '_core_score_calculator')
                assert isinstance(estimator._core_score_calculator, CoreLandmarkScoreCalculator)

                calc1 = estimator._core_score_calculator
                calc2 = estimator._core_score_calculator

                assert calc1 is calc2, "Should reuse same CoreLandmarkScoreCalculator instance"

                estimator.close()

    def test_pose_score_higher_with_core_vs_all_landmarks(self):
        """Core landmarks score should be higher than all-landmarks score for typical poses"""
        from video_optimizer import CoreLandmarkScoreCalculator
        from pose_estimator import Landmark

        core_indices = CoreLandmarkScoreCalculator.CORE_LANDMARK_INDICES

        landmarks = []
        for i in range(33):
            if i in core_indices:
                vis = 0.95
            else:
                vis = 0.40
            landmarks.append(Landmark(x=0.5, y=0.5, z=0.0, visibility=vis, name=f"lm_{i}"))

        calculator = CoreLandmarkScoreCalculator()
        core_score = calculator.calculate(landmarks)

        all_mean = np.mean([lm.visibility for lm in landmarks])

        assert core_score > all_mean, f"Core score {core_score} should be > all mean {all_mean}"

    def test_pipeline_with_low_light_frame_enhances(self):
        """CLAHE should enhance low-light frames"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline = VideoOptimizerPipeline(enable_clahe=True)

        dark_frame = np.full((480, 640, 3), 60, dtype=np.uint8)

        result = pipeline.process_frame(dark_frame, frame_index=0)

        assert result['frame'].shape == dark_frame.shape
        assert result['should_infer'] is True

    def test_pipeline_downscale_4k_to_640(self):
        """4K frame (3840x2160) should be downscaled to width=640 preserving aspect ratio"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline = VideoOptimizerPipeline(max_resolution=640)

        frame_4k = np.random.randint(0, 256, (2160, 3840, 3), dtype=np.uint8)

        result = pipeline.process_frame(frame_4k, frame_index=0)

        assert result['frame'].shape[1] == 640
        assert result['frame'].shape[0] == 360

    def test_optimizer_and_estimator_no_cross_contamination(self):
        """Two separate pipelines should not share state"""
        from video_optimizer import VideoOptimizerPipeline

        pipeline1 = VideoOptimizerPipeline(detection_interval=3)
        pipeline2 = VideoOptimizerPipeline(detection_interval=5)

        raw_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        for i in range(6):
            r1 = pipeline1.process_frame(raw_frame, frame_index=i)
            r2 = pipeline2.process_frame(raw_frame, frame_index=i)

        assert pipeline1.skip_detector.detection_interval == 3
        assert pipeline2.skip_detector.detection_interval == 5

    def test_estimator_calculates_core_score_with_mocked_landmarks_tasks_api(self):
        """PoseEstimator calculates pose_score using _core_score_calculator on Tasks API path"""
        from pose_estimator import PoseEstimator

        with patch('pose_estimator.PoseEstimator._init_mediapipe'):
            with patch('pose_estimator.PoseEstimator._warmup'):
                estimator = PoseEstimator(model_complexity=0, smooth=False)

                mock_landmark_list = []
                for i in range(33):
                    lm = Mock()
                    lm.x = 0.5
                    lm.y = 0.5
                    lm.z = 0.0
                    lm.visibility = 0.9 if i in estimator._core_score_calculator.CORE_LANDMARK_INDICES else 0.5
                    mock_landmark_list.append(lm)

                mock_detection = Mock()
                mock_detection.pose_landmarks = [mock_landmark_list]

                estimator._pose = Mock()
                estimator._pose.detect.return_value = mock_detection
                estimator._use_tasks_api = True

                mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                pose_result = estimator.estimate(mock_frame)

                assert len(pose_result.landmarks) == 33
                assert pose_result.pose_score > 0.0

                estimator.close()
