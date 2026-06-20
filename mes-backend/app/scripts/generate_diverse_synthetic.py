"""
生成高多样性合成骨架数据
9类动作 × 80变体 × 多种姿势 = 720样本
"""
import numpy as np
import os

np.random.seed(42)

OUTPUT_DIR = 'mes-backend/data/synthetic_diverse'
os.makedirs(OUTPUT_DIR, exist_ok=True)

ACTIONS = ['reach', 'grasp', 'move', 'assemble', 'release', 'inspect', 'wait', 'hold', 'idle']
N_PER_CLASS = 80   # 每类80个
T = 48             # 序列长度
V = 33             # 关键点数
C = 3              # x, y, confidence

dataset = []
labels = []

# 身体类型变体
body_types = [
    {'shoulder_w': 0.25, 'height': 0.35, 'arm_l': 0.4},  # 矮小
    {'shoulder_w': 0.35, 'height': 0.25, 'arm_l': 0.5},  # 标准
    {'shoulder_w': 0.45, 'height': 0.20, 'arm_l': 0.6},  # 高大
    {'shoulder_w': 0.35, 'height': 0.30, 'arm_l': 0.45}, # 标准偏瘦
    {'shoulder_w': 0.40, 'height': 0.22, 'arm_l': 0.55}, # 宽肩
]

# 速度变体
speeds = [0.6, 0.8, 1.0, 1.2, 1.5]

for aid, action in enumerate(ACTIONS):
    for var_idx in range(N_PER_CLASS):
        bt = body_types[var_idx % len(body_types)]
        speed = speeds[var_idx % len(speeds)]
        noise_level = 0.003 + np.random.random() * 0.01
        traj_noise = np.random.random() * 0.05  # 轨迹随机性
        
        # 基础骨架
        skeleton = np.zeros((T, V, C))
        # 躯干关键点
        skeleton[:, 0] = [0.5, bt['height'], 0.95]           # 鼻子
        skeleton[:, 5] = [0.5 - bt['shoulder_w']/2, 0.28, 0.9]  # 左肩
        skeleton[:, 6] = [0.5 + bt['shoulder_w']/2, 0.28, 0.9]  # 右肩
        skeleton[:, 11] = [0.48 - bt['shoulder_w']/2, 0.45, 0.9] # 左肘
        skeleton[:, 12] = [0.52 + bt['shoulder_w']/2, 0.45, 0.9] # 右肘
        skeleton[:, 23] = [0.48, 0.55, 0.85]   # 左髋
        skeleton[:, 24] = [0.52, 0.55, 0.85]   # 右髋
        
        # 手臂末端位置偏移（随机起始位置）
        start_x = 0.3 + np.random.random() * 0.1
        start_y = 0.5 + np.random.random() * 0.15
        
        for t in range(T):
            p = min(1.0, t / (T * 0.55 * speed))
            
            if action == 'reach':
                tx = 0.4 + np.random.random() * 0.3
                ty = 0.3 + np.random.random() * 0.2
                skeleton[t, 16] = [start_x + p * (tx - start_x), start_y - p * (start_y - ty), 0.9]
                skeleton[t, 15] = [start_x + 0.1 + p * (tx - start_x) * 0.5, 0.6 - p * 0.05, 0.9]
                
            elif action == 'grasp':
                if t < T * 0.2 * speed:
                    skeleton[t, 16] = [start_x + t/(T*0.2*speed) * 0.15, start_y, 0.9]
                elif t < T * 0.5 * speed:
                    skeleton[t, 16] = [start_x + 0.15, start_y, 0.9]
                else:
                    pr = (t - T*0.5*speed) / (T*0.5*speed)
                    skeleton[t, 16] = [start_x + 0.15 - pr * 0.15, start_y, 0.9]
                skeleton[t, 15] = [start_x + 0.1, 0.55, 0.9]
                    
            elif action == 'move':
                dx = (np.random.random() - 0.5) * traj_noise * 2
                dy = (np.random.random() - 0.5) * traj_noise * 1.5
                if np.random.random() > 0.5:  # 水平运动
                    skeleton[t, 16] = [start_x + p*0.4, start_y + p*dy, 0.9]
                else:  # 垂直运动
                    skeleton[t, 16] = [start_x + p*dx, start_y - p*0.2, 0.9]
                    
            elif action == 'assemble':
                tx = 0.48 + np.random.random() * 0.04
                ty = 0.38 + np.random.random() * 0.04
                skeleton[t, 16] = [start_x + p*(tx-start_x), start_y - p*(start_y-ty), 0.9]
                skeleton[t, 15] = [start_x + 0.1 + p*(tx-start_x)*0.3, 0.5 - p*0.05, 0.9]
                if t > T*0.5:
                    skeleton[t, 16, 0] += np.random.normal(0, 0.005)  # 装配震颤
                    
            elif action == 'release':
                if t < T*0.4:
                    skeleton[t, 16] = [0.5, 0.4, 0.9]
                else:
                    pr = (t - T*0.4) / (T*0.6)
                    skeleton[t, 16] = [0.5 + pr*0.2, 0.4 + pr*0.15, 0.9]
                    
            elif action == 'inspect':
                angle = np.pi * p * 0.3
                skeleton[t, 0] = [0.5 + np.sin(angle)*0.05, bt['height'] + np.cos(angle)*0.03, 0.95]
                skeleton[t, 16] = [0.55, 0.35, 0.9]
                
            elif action == 'wait':
                skeleton[t, 16] = [start_x, start_y, 0.9]
                skeleton[t, 16, 1] += np.sin(t * 0.05) * 0.005  # 轻微呼吸
                
            elif action == 'hold':
                skeleton[t, 16] = [0.35, 0.35, 0.9]
                skeleton[t, 15] = [0.65, 0.35, 0.9]
                skeleton[t, 16, 0] += np.random.normal(0, 0.003)
                skeleton[t, 15, 0] += np.random.normal(0, 0.003)
                
            elif action == 'idle':
                skeleton[t, 16] = [start_x, start_y, 0.9]
                skeleton[t, 15] = [start_x + 0.2, 0.55, 0.9]
                skeleton[t, 0, 1] += np.sin(t * 0.03) * 0.003
                
        # 添加噪声
        skeleton += np.random.normal(0, noise_level, skeleton.shape)
        skeleton = np.clip(skeleton, 0, 1)
        
        # 转为 (C, T, V, 1)
        stgcn_data = skeleton.transpose(2, 0, 1)[:, :, :, np.newaxis]
        dataset.append(stgcn_data)
        labels.append(aid)

dataset = np.array(dataset)
labels = np.array(labels)

# 保存
np.savez(os.path.join(OUTPUT_DIR, 'synthetic_diverse.npz'),
         data=dataset, labels=labels, action_names=ACTIONS)
# 也保存单独的 .npy 文件供训练脚本用
for i in range(len(dataset)):
    np.save(os.path.join(OUTPUT_DIR, f'{ACTIONS[labels[i]]}_{i:04d}.npy'), dataset[i])

print(f"✅ 生成 {len(dataset)} 个样本")
print(f"   数据形状: {dataset.shape}")
print(f"   标签分布: {np.bincount(labels)}")
print(f"   保存到: {OUTPUT_DIR}")
