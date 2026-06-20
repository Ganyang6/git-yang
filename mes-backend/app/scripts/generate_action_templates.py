"""
参数化动作骨架生成器
用运动学模型生成 reach / grasp / assemble / move 等动作的骨架轨迹
不需要视频源，直接输出 (T, 33, 3) 骨架数据
"""

import numpy as np
import os


def generate_reach(T=50, target_x=0.6, target_y=0.4):
    """生成伸手动作：手从初始位置移动到目标位置"""
    skeleton = np.zeros((T, 33, 3))
    for t in range(T):
        progress = min(1.0, t / (T * 0.7))
        skeleton[t, 16] = [
            0.3 + progress * (target_x - 0.3),
            0.6 + progress * (target_y - 0.6),
            0.9,
        ]
        skeleton[t, 5] = [0.35, 0.25, 0.9]
        skeleton[t, 6] = [0.65, 0.25, 0.9]
        skeleton[t, 11] = [0.3, 0.45, 0.9]
        skeleton[t, 12] = [0.7, 0.45, 0.9]
        skeleton[t, 0] = [0.5, 0.1, 0.95]
        for j in range(33):
            if np.all(skeleton[t, j] == 0):
                skeleton[t, j] = [0.5, 0.5, 0.5]
    return skeleton


def generate_grasp(T=60):
    """生成抓取动作：伸手--合拢--收回"""
    skeleton = np.zeros((T, 33, 3))
    for t in range(T):
        if t < T * 0.3:
            reach = t / (T * 0.3)
            skeleton[t, 16] = [0.3 + reach * 0.3, 0.6, 0.9]
        elif t < T * 0.6:
            skeleton[t, 16] = [0.6, 0.6, 0.9]
        else:
            retract = (t - T * 0.6) / (T * 0.4)
            skeleton[t, 16] = [0.6 - retract * 0.3, 0.6, 0.9]
        skeleton[t, 5] = [0.35, 0.25, 0.9]
        skeleton[t, 6] = [0.65, 0.25, 0.9]
        skeleton[t, 0] = [0.5, 0.1, 0.95]
        for j in range(33):
            if np.all(skeleton[t, j] == 0):
                skeleton[t, j] = [0.5, 0.5, 0.5]
    return skeleton


def generate_all(output_dir="mes-backend/data/skeleton_extended"):
    """生成所有动作模板"""
    os.makedirs(output_dir, exist_ok=True)

    actions = {
        "reach": lambda: generate_reach(),
        "reach_far": lambda: generate_reach(target_x=0.8, target_y=0.3),
        "reach_high": lambda: generate_reach(target_x=0.5, target_y=0.2),
        "reach_low": lambda: generate_reach(target_x=0.5, target_y=0.7),
        "grasp": lambda: generate_grasp(),
        "grasp_slow": lambda: generate_grasp(T=90),
        "grasp_fast": lambda: generate_grasp(T=30),
        "move": lambda: generate_reach(target_x=0.7, target_y=0.5),
        "move_left": lambda: generate_reach(target_x=0.2, target_y=0.5),
        "assemble": lambda: generate_reach(T=70, target_x=0.5, target_y=0.5),
    }

    for name, gen in actions.items():
        data = gen()
        np.save(os.path.join(output_dir, f"template_{name}.npy"), data)
        print(f"  {name}: {data.shape[0]} frames, {data.shape}")

    return len(actions)


if __name__ == "__main__":
    count = generate_all()
    print(f"\nGenerated {count} action template skeletons")
