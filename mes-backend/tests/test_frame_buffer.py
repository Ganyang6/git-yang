"""
FrameBuffer 单元测试
覆盖：基本存取、容量控制、延迟计算、线程安全、统计信息
"""

import time
import threading
import numpy as np
import pytest


class TestFrameBufferBasic:
    """基本存取功能"""

    def test_put_returns_frame_data(self, frame_buffer_small, blank_frame_480p):
        """put() 应返回有效的 FrameData 对象"""
        result = frame_buffer_small.put(blank_frame_480p)
        assert result is not None

    def test_frame_id_increments(self, frame_buffer_small, blank_frame_480p):
        """frame_id 应从 1 开始单调递增"""
        first = frame_buffer_small.put(blank_frame_480p)
        second = frame_buffer_small.put(blank_frame_480p)
        assert first.frame_id == 1
        assert second.frame_id == 2

    def test_size_increases_on_put(self, frame_buffer_small, blank_frame_480p):
        """每次 put 后队列大小应增加"""
        assert frame_buffer_small.size == 0
        frame_buffer_small.put(blank_frame_480p)
        assert frame_buffer_small.size == 1

    def test_put_with_camera_id(self, frame_buffer_small, blank_frame_480p):
        """put() 携带 camera_id 应正常存入"""
        result = frame_buffer_small.put(blank_frame_480p, camera_id=2)
        assert result is not None


class TestFrameBufferCapacity:
    """容量限制与丢帧策略"""

    def test_drop_old_when_full(self, frame_buffer_small, blank_frame_480p):
        """drop_old=True 时，队列满后新帧仍能入队，旧帧被丢弃"""
        for _ in range(10):
            frame_buffer_small.put(blank_frame_480p)
        assert frame_buffer_small.size == 5

    def test_dropped_frames_counted(self, frame_buffer_small, blank_frame_480p):
        """丢弃的帧数应被统计"""
        for _ in range(10):
            frame_buffer_small.put(blank_frame_480p)
        stats = frame_buffer_small.get_stats()
        assert stats['dropped_frames'] > 0

    def test_no_drop_when_not_full(self, frame_buffer_large, blank_frame_480p):
        """未超出容量时不应丢帧"""
        for _ in range(50):
            frame_buffer_large.put(blank_frame_480p)
        stats = frame_buffer_large.get_stats()
        assert stats['dropped_frames'] == 0

    def test_max_size_respected(self, frame_buffer_small, blank_frame_480p):
        """队列大小永远不超过 max_size"""
        for _ in range(100):
            frame_buffer_small.put(blank_frame_480p)
        assert frame_buffer_small.size <= frame_buffer_small.max_size


class TestFrameBufferLatency:
    """延迟计算"""

    def test_latency_positive(self, frame_buffer_small, blank_frame_480p):
        """延迟值必须大于 0"""
        frame_data = frame_buffer_small.put(blank_frame_480p)
        time.sleep(0.005)
        latency = frame_buffer_small.calculate_latency(frame_data)
        assert latency > 0

    def test_latency_within_reasonable_range(self, frame_buffer_small, blank_frame_480p):
        """sleep 10ms 后，延迟应在 8~100ms 之间（留系统调度误差余量）"""
        frame_data = frame_buffer_small.put(blank_frame_480p)
        time.sleep(0.010)
        latency = frame_buffer_small.calculate_latency(frame_data)
        assert 8 < latency < 100

    def test_latency_increases_with_sleep(self, frame_buffer_small, blank_frame_480p):
        """等待时间越长，计算出的延迟应越大"""
        frame_data_1 = frame_buffer_small.put(blank_frame_480p)
        time.sleep(0.005)
        latency_1 = frame_buffer_small.calculate_latency(frame_data_1)

        frame_data_2 = frame_buffer_small.put(blank_frame_480p)
        time.sleep(0.020)
        latency_2 = frame_buffer_small.calculate_latency(frame_data_2)

        assert latency_2 > latency_1


class TestFrameBufferThreadSafety:
    """并发写入安全性"""

    def test_concurrent_put_no_exception(self, frame_buffer_large, blank_frame_480p):
        """多线程同时 put 不应抛出异常"""
        errors = []

        def worker():
            try:
                for _ in range(20):
                    frame_buffer_large.put(blank_frame_480p)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发写入产生异常: {errors}"

    def test_concurrent_put_frame_id_unique(self, frame_buffer_large, blank_frame_480p):
        """并发写入时每帧的 frame_id 应唯一"""
        frame_ids = []
        lock = threading.Lock()

        def worker():
            for _ in range(10):
                result = frame_buffer_large.put(blank_frame_480p)
                if result:
                    with lock:
                        frame_ids.append(result.frame_id)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(frame_ids) == len(set(frame_ids)), "存在重复的 frame_id"


class TestFrameBufferStats:
    """统计信息"""

    def test_stats_structure(self, frame_buffer_small):
        """get_stats() 应返回包含必要字段的字典"""
        stats = frame_buffer_small.get_stats()
        assert 'total_frames' in stats
        assert 'dropped_frames' in stats

    def test_total_frames_counts_all_puts(self, frame_buffer_small, blank_frame_480p):
        """total_frames 应等于 put() 的总调用次数（包括被丢弃的）"""
        put_count = 10
        for _ in range(put_count):
            frame_buffer_small.put(blank_frame_480p)
        stats = frame_buffer_small.get_stats()
        assert stats['total_frames'] == put_count
