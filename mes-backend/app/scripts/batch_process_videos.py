"""
批量处理视频：骨架提取 → 动作分类 → 生成标注 → 构建训练集

用法：
  python3 batch_process_videos.py --input-dir /path/to/videos

输入：视频文件（.mp4/.avi/.mov）
输出：骨架.npy + ProcessSegment标签 → 训练ST-GCN
"""

import os
import sys
import glob
import json
import subprocess
import numpy as np


def process_videos(input_dir, output_dir='mes-backend/data/skeleton_extended'):
    """批量处理视频"""
    os.makedirs(output_dir, exist_ok=True)
    video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.webm']

    videos = []
    for ext in video_exts:
        videos.extend(glob.glob(os.path.join(input_dir, f'*{ext}')))
        videos.extend(glob.glob(os.path.join(input_dir, f'*{ext.upper()}')))

    print(f"找到 {len(videos)} 个视频")
    for v in sorted(videos):
        basename = os.path.splitext(os.path.basename(v))[0]
        out_path = os.path.join(output_dir, f'{basename}.npy')
        if os.path.exists(out_path):
            print(f"  ⏭ {basename} (已处理)")
            continue

        # 用子进程调用骨架提取
        print(f"  ▶ 处理 {basename}...")
        result = subprocess.run([
            sys.executable, '-c', f'''
import cv2, mediapipe as mp, numpy as np
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, model_complexity=0)
cap = cv2.VideoCapture("{v}")
keypoints = []
while True:
    ret, frame = cap.read()
    if not ret:
        break
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = pose.process(frame_rgb)
    if results.pose_landmarks:
        kp = np.array([[lm.x, lm.y, lm.visibility] for lm in results.pose_landmarks.landmark])
        keypoints.append(kp)
    else:
        keypoints.append(np.zeros((33, 3)))
cap.release()
pose.close()
np.save("{out_path}", np.array(keypoints))
print(f"提取完成: {{len(keypoints)}}帧")
            '''], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            print(f"  ✅ {basename}: {result.stdout.strip()}")
        else:
            print(f"  ❌ {basename}: {result.stderr[:200]}")

    # 统计
    processed = [f for f in os.listdir(output_dir) if f.endswith('.npy')]
    print(f"\n✅ 共处理 {len(processed)} 个骨架文件")
    total_frames = sum(np.load(os.path.join(output_dir, f)).shape[0] for f in processed)
    print(f"   总帧数: {total_frames}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-dir', required=True, help='视频文件夹')
    parser.add_argument('--output-dir', default='mes-backend/data/skeleton_extended')
    args = parser.parse_args()
    process_videos(args.input_dir, args.output_dir)
