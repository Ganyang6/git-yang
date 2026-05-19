"""
帧缓冲队列模块
目标：保障 30+ FPS、延迟 <33ms 的实时数据流
特性：
  - 线程安全的 FIFO 队列
  - 可配置队列大小
  - 支持丢弃旧帧模式（保证实时性）
  - 记录帧时间戳用于延迟计算
"""

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Dict
import numpy as np


@dataclass
class FrameData:
    """帧数据结构"""
    frame_id: int
    timestamp: float  # 采集时间戳（秒）
    image: np.ndarray  # 原始帧
    landmarks: Optional[Any] = None  # 姿态关键点
    camera_id: int = 0
    processing_time_ms: float = 0.0  # 处理耗时


class FrameBuffer:
    """
    线程安全的帧缓冲队列

    设计原则：
    1. 固定大小队列，超出容量时根据配置丢弃旧帧或新帧
    2. 每帧携带时间戳，便于计算端到端延迟
    3. 支持多生产者多消费者模式
    """

    def __init__(self, max_size: int = 10, drop_old: bool = True):
        """
        初始化帧缓冲

        Args:
            max_size: 队列最大容量
            drop_old: True=丢弃最旧帧（保证实时性），False=丢弃最新帧
        """
        self.max_size = max_size
        self.drop_old = drop_old
        self._queue = queue.Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._stats = {
            'total_frames': 0,
            'dropped_frames': 0,
            'max_latency_ms': 0.0,
            'avg_latency_ms': 0.0
        }
        self._latency_sum = 0.0
        self._frame_id_counter = 0

    def put(self, frame: np.ndarray, landmarks: Any = None,
            camera_id: int = 0) -> Optional[FrameData]:
        """
        放入一帧到缓冲队列

        Args:
            frame: numpy 数组格式的图像
            landmarks: 姿态关键点数据（可选）
            camera_id: 摄像头ID

        Returns:
            FrameData: 封装的帧数据对象
        """
        current_time = time.perf_counter()
        self._frame_id_counter += 1

        frame_data = FrameData(
            frame_id=self._frame_id_counter,
            timestamp=current_time,
            image=frame,
            landmarks=landmarks,
            camera_id=camera_id
        )

        # N-P1-26: Use try/except instead of qsize() check to avoid TOCTOU race.
        # The underlying queue already handles thread-safety; we just need to
        # handle Full gracefully.
        if self.drop_old:
            # If queue is full, drop the oldest frame first
            try:
                self._queue.put_nowait(frame_data)
                self._stats['total_frames'] += 1
                return frame_data
            except queue.Full:
                # Queue full: remove one oldest, then try again
                try:
                    self._queue.get_nowait()
                    self._stats['dropped_frames'] += 1
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(frame_data)
                    self._stats['total_frames'] += 1
                    return frame_data
                except queue.Full:
                    self._stats['dropped_frames'] += 1
                    return None
        else:
            try:
                self._queue.put_nowait(frame_data)
                self._stats['total_frames'] += 1
                return frame_data
            except queue.Full:
                self._stats['dropped_frames'] += 1
                return None

    def get(self, timeout: float = 1.0) -> Optional[FrameData]:
        """
        从队列获取一帧

        Args:
            timeout: 超时时间（秒）

        Returns:
            FrameData: 帧数据，超时返回None
        """
        try:
            frame_data = self._queue.get(timeout=timeout)
            return frame_data
        except queue.Empty:
            return None

    def get_latest(self) -> Optional[FrameData]:
        """
        获取最新帧，丢弃队列中所有旧帧
        用于只需要最新数据的场景

        Returns:
            FrameData: 最新的帧数据
        """
        latest = None
        while True:
            try:
                frame = self._queue.get_nowait()
                latest = frame
            except queue.Empty:
                break
        return latest

    def calculate_latency(self, frame_data: FrameData) -> float:
        """
        计算帧的端到端延迟

        Args:
            frame_data: 帧数据

        Returns:
            float: 延迟时间（毫秒）
        """
        current_time = time.perf_counter()
        latency_ms = (current_time - frame_data.timestamp) * 1000.0

        # 更新统计
        with self._lock:
            if latency_ms > self._stats['max_latency_ms']:
                self._stats['max_latency_ms'] = latency_ms
            self._latency_sum += latency_ms
            count = self._stats['total_frames'] - self._stats['dropped_frames']
            if count > 0:
                self._stats['avg_latency_ms'] = self._latency_sum / count

        return latency_ms

    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓冲队列统计信息

        Returns:
            Dict: 包含总帧数、丢弃帧数、最大延迟、平均延迟
        """
        with self._lock:
            stats = self._stats.copy()
            stats['queue_size'] = self._queue.qsize()
            stats['max_size'] = self.max_size
            stats['drop_rate'] = (
                self._stats['dropped_frames'] / max(1, self._stats['total_frames']) * 100
            )
            return stats

    def clear(self) -> None:
        """清空队列"""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    @property
    def size(self) -> int:
        """当前队列大小"""
        return self._queue.qsize()

    @property
    def is_empty(self) -> bool:
        """队列是否为空"""
        return self._queue.empty()

    @property
    def is_full(self) -> bool:
        """队列是否已满"""
        return self._queue.full()


class MultiCameraBuffer:
    """
    多摄像头帧缓冲管理器
    为每个摄像头维护独立的缓冲队列
    """

    def __init__(self, buffer_config: Dict[str, Any]):
        """
        初始化多摄像头缓冲管理器

        Args:
            buffer_config: 缓冲配置 {'max_size': int, 'drop_old': bool}
        """
        self.max_size = buffer_config.get('max_size', 10)
        self.drop_old = buffer_config.get('drop_old', True)
        self._buffers: Dict[int, FrameBuffer] = {}
        self._lock = threading.Lock()

    def get_buffer(self, camera_id: int) -> FrameBuffer:
        """
        获取指定摄像头的缓冲队列，不存在则创建

        Args:
            camera_id: 摄像头ID

        Returns:
            FrameBuffer: 该摄像头的缓冲队列
        """
        with self._lock:
            if camera_id not in self._buffers:
                self._buffers[camera_id] = FrameBuffer(
                    max_size=self.max_size,
                    drop_old=self.drop_old
                )
            return self._buffers[camera_id]

    def put_frame(self, camera_id: int, frame: np.ndarray,
                  landmarks: Any = None) -> Optional[FrameData]:
        """向指定摄像头队列放入帧"""
        buffer = self.get_buffer(camera_id)
        return buffer.put(frame, landmarks, camera_id)

    def get_frame(self, camera_id: int, timeout: float = 1.0) -> Optional[FrameData]:
        """从指定摄像头队列获取帧"""
        if camera_id not in self._buffers:
            return None
        return self._buffers[camera_id].get(timeout)

    def get_all_stats(self) -> Dict[int, Dict[str, Any]]:
        """获取所有摄像头的统计信息"""
        stats = {}
        with self._lock:
            for cam_id, buffer in self._buffers.items():
                stats[cam_id] = buffer.get_stats()
        return stats

    def get_global_stats(self) -> Dict[str, Any]:
        """获取全局统计信息"""
        all_stats = self.get_all_stats()
        if not all_stats:
            return {}

        total_frames = sum(s['total_frames'] for s in all_stats.values())
        total_dropped = sum(s['dropped_frames'] for s in all_stats.values())
        max_latency = max(s['max_latency_ms'] for s in all_stats.values())
        avg_latency = sum(s['avg_latency_ms'] for s in all_stats.values()) / len(all_stats)

        return {
            'total_frames': total_frames,
            'total_dropped_frames': total_dropped,
            'max_latency_ms': max_latency,
            'avg_latency_ms': avg_latency,
            'drop_rate': total_dropped / max(1, total_frames) * 100,
            'camera_count': len(all_stats)
        }
