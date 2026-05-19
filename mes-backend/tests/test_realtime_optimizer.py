"""
TDD Tests for Real-time Video Optimization Pipeline Integration
Target: Ensure VideoOptimizerPipeline is properly integrated in real-time camera mode
"""

import numpy as np
import pytest
from unittest.mock import Mock, patch


class TestRealtimeOptimizerIntegration:
    """Test that VideoOptimizerPipeline is used in real-time camera mode"""

    def test_realtime_pipeline_uses_video_optimizer(self):
        """Should use VideoOptimizerPipeline in real-time camera mode"""
        from main import run_realtime_pipeline
        
        # Mock dependencies
        with patch('camera_manager.CameraManager') as mock_camera_manager, \
             patch('pose_estimator.PoseEstimator') as mock_pose_estimator, \
             patch('frame_buffer.FrameBuffer') as mock_frame_buffer, \
             patch('main.cv2') as mock_cv2, \
             patch('main.time') as mock_time:
            
            # Setup mocks
            mock_camera = Mock()
            mock_camera.open.return_value = True
            mock_camera.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))
            mock_camera.close.return_value = None
            
            mock_camera_manager.return_value.add_camera.return_value = mock_camera
            
            mock_pose_result = Mock()
            mock_pose_result.landmarks = []
            mock_pose_estimator.return_value.estimate.return_value = mock_pose_result
            mock_pose_estimator.return_value.close.return_value = None
            mock_pose_estimator.return_value.get_stats.return_value = {}
            
            mock_frame_data = Mock()
            mock_frame_buffer.return_value.put.return_value = mock_frame_data
            mock_frame_buffer.return_value.calculate_latency.return_value = 10.0
            mock_frame_buffer.return_value.size = 0
            mock_frame_buffer.return_value.max_size = 10
            mock_frame_buffer.return_value.get_stats.return_value = {}
            
            mock_cv2.imshow = Mock()
            mock_cv2.waitKey.return_value = 113  # 'q' key to exit
            mock_cv2.destroyAllWindows = Mock()
            
            mock_time.perf_counter.side_effect = [0.0, 1.1, 2.1]  # Trigger FPS calculation
            
            # Import VideoOptimizer to check if it's used
            with patch('video_optimizer.VideoOptimizerPipeline') as mock_optimizer:
                # Run real-time pipeline (will exit quickly due to 'q' key mock)
                try:
                    run_realtime_pipeline(camera_id=0, show_display=True)
                except SystemExit:
                    pass  # Expected due to early exit
                except Exception:
                    pass  # Ignore other exceptions from mocks
                
                # Verify VideoOptimizerPipeline was instantiated
                mock_optimizer.assert_called_once()
                
    def test_optimizer_process_frame_called_in_realtime(self):
        """Should call process_frame on VideoOptimizerPipeline for each frame"""
        from main import run_realtime_pipeline
        
        # Mock dependencies
        with patch('camera_manager.CameraManager') as mock_camera_manager, \
             patch('pose_estimator.PoseEstimator') as mock_pose_estimator, \
             patch('frame_buffer.FrameBuffer') as mock_frame_buffer, \
             patch('main.cv2') as mock_cv2, \
             patch('main.time') as mock_time:
            
            # Setup mocks
            mock_camera = Mock()
            test_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            mock_camera.open.return_value = True
            # Return frame first call, then no frame to exit
            mock_camera.read.side_effect = [(True, test_frame), (False, None)]
            mock_camera.close.return_value = None
            
            mock_camera_manager.return_value.add_camera.return_value = mock_camera
            
            mock_pose_result = Mock()
            mock_pose_result.landmarks = []
            mock_pose_estimator.return_value.estimate.return_value = mock_pose_result
            mock_pose_estimator.return_value.close.return_value = None
            mock_pose_estimator.return_value.get_stats.return_value = {}
            
            mock_frame_data = Mock()
            mock_frame_buffer.return_value.put.return_value = mock_frame_data
            mock_frame_buffer.return_value.calculate_latency.return_value = 10.0
            mock_frame_buffer.return_value.size = 0
            mock_frame_buffer.return_value.max_size = 10
            mock_frame_buffer.return_value.get_stats.return_value = {}
            
            mock_cv2.imshow = Mock()
            mock_cv2.waitKey.return_value = 113  # 'q' key to exit
            mock_cv2.destroyAllWindows = Mock()
            
            mock_time.perf_counter.return_value = 0.0
            
            # Import VideoOptimizer and track calls
            with patch('video_optimizer.VideoOptimizerPipeline') as mock_optimizer_class:
                # Setup mock optimizer instance
                mock_optimizer_instance = Mock()
                mock_optimizer_instance.process_frame.return_value = {
                    'frame': test_frame,
                    'should_infer': True
                }
                mock_optimizer_class.return_value = mock_optimizer_instance
                
                # Run real-time pipeline
                try:
                    run_realtime_pipeline(camera_id=0, show_display=True)
                except SystemExit:
                    pass  # Expected due to early exit
                except Exception:
                    pass  # Ignore other exceptions from mocks
                
                # Verify process_frame was called with the frame
                mock_optimizer_instance.process_frame.assert_called_once()
                call_args = mock_optimizer_instance.process_frame.call_args
                assert call_args[0][0].shape == test_frame.shape
                assert call_args[0][1] == 0  # frame_index should start at 0
